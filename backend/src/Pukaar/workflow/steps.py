"""Approval workflow steps (one Lambda, dispatch on "step"; see infra/approval.asl.json).

Every step that can send calls the Cedar guard first. failsafe and close never
raise, even for an unknown alert, so a broken run always ends.

Who is asked: the district's duty roster for the shift on duty when the alert is drafted, in IST
(services/roster.py): the primary, then the backup, then the escalation officer above them (the
ADM or the DM), else the village's fallback list. PUKAAR_OFFICER_WAKE_SECONDS into each officer's
window (3 minutes, or half-way through a shorter window) the officer is reminded on every channel
they have (Web Push and Telegram) and, if they have not opened the link, phoned
(delivery/officer_call.py: the call can only send the link again, never approve) before the next
is asked. A critical alert's window is PUKAAR_CRITICAL_APPROVAL_TIMEOUT_SECONDS (5 minutes).

Delivery at scale: deliver, recall and failsafe send the first batch of recipients themselves and
return the other batches; the Map state runs them (deliver_batch) and deliver_done finishes the round
or runs the batches with sends still queued again (dispatch.py, docs/CONTRACT.md).

The all-clear (stand_down): when a village is back to normal, or an officer issues the all-clear,
everyone contacted for its alerts hears so on the channel they were warned on, and so does every
officer who was asked. A replay never reaches a real phone, here as everywhere.
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

from boto3.dynamodb.conditions import Attr

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log, metric
from Pukaar.delivery import dispatch, officer_call, telegram, voice
from Pukaar.llm.bedrock import BedrockLLM
from Pukaar.policy.guard import SYSTEM, authorize
from Pukaar.services import after_action, events, officer_push, rollcall, roster
from Pukaar.services.drafting import draft_alert
from Pukaar.store.models import Alert, Delivery
from Pukaar.store.repo import ConflictError, Repo
from Pukaar.templates import hi
from Pukaar.voice import polly
from Pukaar.workflow import tokens

_LOG = get_logger("workflow")
# A delivery row that reached, or was ringing, the person: they hear the all-clear on that channel.
CONTACTED = {"sent", "acknowledged", "pending"}
ALL_CLEAR_WINDOW_HOURS = 72  # alerts older than this are not stood down again by a later return to normal


def approval_window(level: str | None = None) -> int:
    """Seconds each officer has to decide. A critical alert gets PUKAAR_CRITICAL_APPROVAL_TIMEOUT_SECONDS
    (5 minutes by default), never more than the general window: three officers then hold a critical for
    at most 15 minutes, not 30, before it is sent automatically or expires."""
    s = get_settings()
    total = max(2, s.approval_timeout_seconds)
    if level == "critical":
        total = max(2, min(total, s.approval_timeout_critical_seconds))
    return total


def approval_timers(level: str | None = None) -> dict[str, int]:
    """The two parts of an officer's approval window. The nudge, with the wake-up call to an officer
    who has not opened the link, comes PUKAAR_OFFICER_WAKE_SECONDS in (3 minutes), or half-way
    through a window shorter than twice that."""
    total = approval_window(level)
    wake = get_settings().officer_wake_seconds
    first = max(1, min(wake, total // 2) if wake > 0 else total // 2)
    return {"nudge_after_seconds": first, "nudge_wait_seconds": total - first}


def drive_delivery(handle: Callable[[dict], dict], result: dict, *, sleep: Callable[[float], None] = time.sleep) -> dict:
    """What the Map state of infra/approval.asl.json does, in this process: run the batches a deliver,
    recall or failsafe step left (concurrency at a time), then deliver_done, until nothing is left.
    Used by the local runner and the tests; in AWS, Step Functions does this."""
    while result.get("more"):
        alert_id = result["alert_id"]
        if result.get("wait_seconds"):  # WaitBeforeBatches: the retry_after Telegram asked for
            sleep(float(result["wait_seconds"]))

        def one(item: dict) -> dict:
            try:
                return handle({"step": "deliver_batch", "alert_id": alert_id, **item})
            except Exception as exc:  # the Map's Catch: the batch is reported unfinished, the run goes on
                log(_LOG, "batch failed", 40, alert_id=alert_id, batch=item.get("batch"), error=str(exc)[:200])
                return {"spec": item, "unfinished": True}

        with ThreadPoolExecutor(max_workers=max(1, int(result.get("concurrency") or 1))) as pool:
            results = list(pool.map(one, result["batches"]))
        result = handle({"step": "deliver_done", "alert_id": alert_id, "mode": result["mode"],
                         "pass": result["pass"], "counts": result.get("counts"), "results": results})
    return result


class StepError(RuntimeError):
    pass


class Steps:
    def __init__(self, repo: Repo, llm: BedrockLLM | None = None, synthesize: Callable | None = None) -> None:
        self.repo = repo
        self.llm = llm
        self.synthesize = synthesize or polly.synthesize_alert

    def handle(self, event: dict[str, Any]) -> dict[str, Any]:
        step = event.get("step")
        fn = getattr(self, f"step_{step}", None)
        if fn is None:
            raise StepError(f"unknown step {step!r}")
        log(_LOG, "step", step=step, alert_id=event.get("alert_id"))
        return fn(event)

    def _alert(self, alert_id: str) -> Alert:
        alert = self.repo.get_alert(alert_id)
        if alert is None:
            raise StepError(f"alert {alert_id} not found")
        return alert

    def _officers(self, alert: Alert) -> list[str]:
        """The approval chain, in order: frozen on the alert when it was drafted, so a shift change
        mid-approval never reorders it. An alert drafted before chains were stored resolves it now."""
        if alert.officer_chain:
            return list(alert.officer_chain)
        return self._duty(alert).chain

    def _duty(self, alert: Alert) -> roster.Duty:
        """Who is on duty now (IST) for the alert's district; the village's own list as the fallback."""
        village = self.repo.get_village(alert.village_id)
        if village is None:
            return roster.Duty("", roster.slot_at(clock.now()), "none")
        return roster.chain_for(self.repo, village)

    @staticmethod
    def _role(alert: Alert, index: int) -> str:
        roles = alert.officer_chain_roles
        return roles[index] if index < len(roles) else f"#{index + 1}"

    # -- steps -----------------------------------------------------------------
    def step_draft(self, e: dict) -> dict:
        alert = self._alert(e["alert_id"])
        village = self.repo.get_village(alert.village_id)
        if village is None:
            raise StepError(f"village {alert.village_id} not found")
        recipients = self.repo.list_recipients(alert.village_id)
        for _ in range(3):  # the sweep may escalate the level while we draft
            result = draft_alert(village, alert.level, alert.decision_trace, self.repo, self.llm)
            if alert.decision_trace.get("drill"):  # a hand-started test (scripts/drill.py): say so in the message
                result.text_hi = f"अभ्यास (DRILL), असली चेतावनी नहीं। {result.text_hi}"
                result.text_en = f"DRILL, not a real warning. {result.text_en}"
            trace = dict(alert.decision_trace)
            if result.tools:
                trace["drafting_tools"] = result.tools
            if result.safe_place:  # the place named in the text, so the record shows where it came from
                trace["safe_place"] = result.safe_place
            try:
                alert = self.repo.update_alert(alert.id, condition=Attr("level").eq(alert.level),
                                               text_hi=result.text_hi, text_en=result.text_en,
                                               reason_en=result.reason_en, reasoning_model=result.reasoning_model,
                                               draft_check=result.check, decision_trace=trace,
                                               recipients_count=len(recipients), status="pending")
                break
            except ConflictError:
                alert = self._alert(alert.id)
        else:
            raise StepError("level kept changing while drafting")
        audio_key = self.synthesize(alert.id, alert.text_hi)
        if audio_key:
            self.repo.update_alert(alert.id, audio_key=audio_key)
        # Freeze who is asked, in order, for this alert: the duty roster now (IST), else the fallback list.
        duty = self._duty(alert)
        alert = self.repo.update_alert(alert.id, officer_chain=duty.chain, officer_chain_roles=duty.roles)
        events.alert_changed(alert)  # pending: the console shows the approval card at once
        chain = " -> ".join(f"{who} ({role})" for who, role in zip(duty.chain, duty.roles)) or "nobody"
        self.repo.add_timeline(alert.id, "drafted",
                               f"model={result.reasoning_model}; check={'pass' if result.check.passed else 'fail'}: "
                               f"{result.check.reason}; recipients={len(recipients)}; audio={'yes' if audio_key else 'no'}; "
                               f"officers ({duty.source}, {duty.slot.label()}): {chain}")
        return {"alert_id": alert.id, "level": alert.level, "officer_count": len(duty.chain),
                "recipients_count": len(recipients), **approval_timers(alert.level)}

    def _asked(self, alert: Alert, officer: str) -> list[str]:
        return alert.officers_asked if officer in alert.officers_asked else [*alert.officers_asked, officer]

    def step_ask_officer(self, e: dict) -> dict:
        alert = self._alert(e["alert_id"])
        officers = self._officers(alert)
        index = int(e.get("officer_index", 0))
        if index >= len(officers):
            raise StepError("officer index out of range")
        officer = officers[index]
        alert = self.repo.update_alert(alert.id, task_token=e["task_token"], officer_index=index,
                                       token_version=alert.token_version + 1, status="pending", approved=False,
                                       officers_asked=self._asked(alert, officer))
        link = tokens.sign(alert.id, officer, alert.token_version, "approve")
        url = f"{get_settings().web_url}/a/{link}"
        sent = dispatch.notify_officer(self.repo, alert, officer, url)
        pushed = officer_push.notify_approval(self.repo, alert, officer, link, url)  # never raises
        self.repo.add_timeline(alert.id, "asked_officer",
                               f"{officer} ({self._role(alert, index)}, #{index + 1} of {len(officers)}); "
                               f"telegram={'yes' if sent else 'no'}; push={pushed.sent}; console=yes")
        return {"alert_id": alert.id, "officer": officer}

    def step_nudge_officer(self, e: dict) -> dict:
        """No decision PUKAAR_OFFICER_WAKE_SECONDS into the window: remind the same officer on every channel
        they have (Web Push and Telegram) and, if they have not opened the link, phone them: the night-time
        escalation of the reminder (delivery/officer_call.py; with voice off the record says the call was
        not possible). Then wait the rest of the window before the next officer is asked.

        Takes the new task token but keeps token_version, so the link sent first still works."""
        alert = self._alert(e["alert_id"])
        officers = self._officers(alert)
        index = int(e.get("officer_index", 0))
        if index >= len(officers):
            raise StepError("officer index out of range")
        officer = officers[index]
        alert = self.repo.update_alert(alert.id, task_token=e["task_token"], officer_index=index, status="pending",
                                       approved=False, nudges=alert.nudges + 1,
                                       officers_asked=self._asked(alert, officer))
        link = tokens.sign(alert.id, officer, alert.token_version, "approve")
        url = f"{get_settings().web_url}/a/{link}"
        wait = approval_timers(alert.level)["nudge_wait_seconds"]
        minutes = max(1, round(wait / 60))
        sent = False
        chat = self.repo.get_officer_chat(officer)
        if chat and telegram.configured():
            try:
                telegram.send_text(chat, hi.nudge_officer(alert.village_name_hi, alert.level, minutes, url, alert.replay))
                sent = True
            except Exception as exc:
                log(_LOG, "nudge by telegram failed", 30, alert_id=alert.id, error=str(exc)[:200])
        pushed = 0
        if not alert.replay:  # a replay never reaches a real device
            payload = officer_push.approval_payload(alert, link, url, minutes)
            payload["title"] = f"याद दिलाना · Reminder: {payload['title']}"
            pushed = officer_push.send_to_user(self.repo, officer, payload, ttl=wait, kind="nudge").sent
        # The wake-up call, at the same moment: only to an officer who has not opened the link.
        if officer_call.opened(alert, officer):
            call_status, call_note = "not_needed", "call=not needed (the link was opened)"
        else:
            call = officer_call.wake(self.repo, alert, officer, index)  # never raises
            call_status, call_note = call.status, officer_call.describe(call)
        metric("OfficerNudged", 1)
        self.repo.add_timeline(alert.id, "nudged_officer",
                               f"{officer} ({self._role(alert, index)}) has not answered; "
                               f"reminded: telegram={'yes' if sent else 'no'}; push={pushed}; {call_note}; "
                               f"next officer in {minutes} min")
        return {"alert_id": alert.id, "officer": officer, "telegram": sent, "push": pushed, "call": call_status}

    def step_next_officer(self, e: dict) -> dict:
        alert = self._alert(e["alert_id"])
        officers = self._officers(alert)
        index = int(e.get("officer_index", 0))
        nxt = index + 1
        self.repo.update_alert(alert.id, task_token=None, token_version=alert.token_version + 1)
        who = f"{officers[index]} ({self._role(alert, index)})" if index < len(officers) else f"officer #{nxt}"
        then = (f"; asking {officers[nxt]} ({self._role(alert, nxt)})" if nxt < len(officers)
                else "; chain exhausted")
        self.repo.add_timeline(alert.id, "officer_timeout", f"{who} did not answer in time{then}")
        # The next officer's window follows the level now: an alert raised to critical while it waited
        # gets the shorter critical window from here on.
        return {"has_next": nxt < len(officers), "officer_index": nxt, "level": alert.level,
                **approval_timers(alert.level)}

    def step_auto_send(self, e: dict) -> dict:
        alert = self._alert(e["alert_id"])
        if not get_settings().critical_auto_send:
            # Off by configuration (PUKAAR_CRITICAL_AUTO_SEND=false): nothing goes out without a person.
            events.alert_changed(self.repo.update_alert(alert.id, status="expired", task_token=None))
            self.repo.add_timeline(alert.id, "auto_send_off",
                                   f"every officer timed out at critical, but critical auto-send is off "
                                   f"({roster.DDMA_LABEL}): nothing was sent. If the level holds, the sweep asks "
                                   f"again after {get_settings().reask_cooldown_minutes} min")
            return {"alert_id": alert.id, "mode": "off"}
        decision = authorize(SYSTEM, "auto_send", "alert", alert.id,
                             {"level": alert.level, "all_officers_timed_out": True, "replay": alert.replay},
                             repo=self.repo)
        if not decision.allowed:
            raise StepError(f"auto-send denied: {decision.reason}")
        text_hi, text_en = hi.fallback_alert(alert.level, alert.village_name_hi, alert.village_name,
                                             alert.decision_trace.get("safe_place"))
        events.alert_changed(self.repo.update_alert(alert.id, status="auto_sent_unapproved", text_hi=text_hi,
                                                    text_en=text_en, decided_by="system:auto-send",
                                                    decided_at=clock.iso(clock.now())))
        self.repo.add_timeline(alert.id, "auto_send", "every officer timed out at critical; fixed template, flagged unapproved")
        return {"alert_id": alert.id, "mode": "auto"}

    def step_expire(self, e: dict) -> dict:
        alert = self._alert(e["alert_id"])
        events.alert_changed(self.repo.update_alert(alert.id, status="expired", task_token=None))
        self.repo.add_timeline(alert.id, "expired",
                               "no officer answered; not critical, so nothing was sent. If the level holds, the sweep "
                               f"asks again after {get_settings().reask_cooldown_minutes} min")
        return {"alert_id": alert.id, "outcome": "expired"}

    def step_deliver(self, e: dict) -> dict:
        alert = self._alert(e["alert_id"])
        action = "auto_send" if alert.status == "auto_sent_unapproved" else "deliver"
        if alert.status not in {"approved", "auto_sent_unapproved"}:
            raise StepError(f"deliver called with status {alert.status}")
        if action == "deliver":
            alert = self.repo.update_alert(alert.id, status="delivering")
            events.alert_changed(alert)
        return self._start_round(alert, "deliver", action)

    def step_recall(self, e: dict) -> dict:
        """Re-send to people who have not acknowledged: Telegram once, voice calls up to
        PUKAAR_VOICE_MAX_ATTEMPTS in all. "again" asks the state machine for another voice round
        after VoiceRetrySeconds; recall_rounds bounds the loop even if a status callback never comes."""
        alert = self._alert(e["alert_id"])
        if alert.all_clear_at:  # stood down: never re-send a warning after the all-clear went out
            self.repo.add_timeline(alert.id, "recall", "skipped: the alert was stood down and the all-clear sent")
            return {"alert_id": alert.id, "resent": 0, "again": False, "round": alert.recall_rounds,
                    "mode": "recall", "more": False}
        action = "auto_send" if alert.status == "auto_sent_unapproved" else "deliver"
        rounds = alert.recall_rounds + 1
        alert = self.repo.update_alert(alert.id, recall_rounds=rounds)
        return self._start_round(alert, "recall", action, recall=True)

    # -- delivery at scale: the first batch here, the rest in the Map state --------------------------
    @staticmethod
    def _mode(alert: Alert, mode: str) -> tuple[str, bool]:
        """(the Cedar action, recall?) for a delivery mode."""
        if mode == "failsafe":
            return "failsafe", False
        return ("auto_send" if alert.status == "auto_sent_unapproved" else "deliver"), mode == "recall"

    def _start_round(self, alert: Alert, mode: str, action: str, *, recall: bool = False) -> dict:
        """Send batch 0 (the relays first, and the one upload of the audio) here; return the other batches
        for the Map state, or finish the round when everyone fitted in one batch."""
        s = get_settings()
        people = dispatch.ordered_recipients(self.repo, alert)
        alert = dispatch.prepare(self.repo, alert, people)  # the call audio, once per alert, before any batch
        deadline = time.monotonic() + s.delivery_budget_seconds
        res = dispatch.deliver_round(self.repo, alert, action=action, recall=recall, batch=0, recipients=people,
                                     deadline=deadline)
        specs = dispatch.batch_specs(people)
        counts = {"sent": len(res.sent), "failed": len(res.failed - res.sent), "batches": len(specs)}
        todo = (specs[:1] if res.deferred else []) + specs[1:]
        if todo:
            return self._more(alert.id, mode, todo, 1, res.retry_after, counts)
        return self._finish_round(alert.id, mode, counts, passes=1, batches=1)

    @staticmethod
    def _more(alert_id: str, mode: str, specs: list[dict], pass_no: int, retry_after: float, counts: dict) -> dict:
        s = get_settings()
        concurrency = max(1, min(s.delivery_concurrency, len(specs)))
        items = [{"batch": int(sp["batch"]), "first": sp.get("first"), "last": sp.get("last"), "mode": mode,
                  "share": concurrency} for sp in specs]
        return {"alert_id": alert_id, "mode": mode, "more": True, "pass": pass_no, "counts": counts,
                "batches": items, "concurrency": concurrency,
                "wait_seconds": int(min(60, max(0, math.ceil(retry_after))))}

    def step_deliver_batch(self, e: dict) -> dict:
        """One batch of recipients (a Map iteration). Never raises for a rate limit: sends that could not go
        out in time are put back unsent and reported as deferred, and deliver_done runs the batch again."""
        alert = self._alert(e["alert_id"])
        spec = {"batch": int(e["batch"]), "first": e.get("first"), "last": e.get("last")}
        action, recall = self._mode(alert, e.get("mode", "deliver"))
        deadline = time.monotonic() + get_settings().delivery_budget_seconds
        res = dispatch.deliver_round(self.repo, alert, action=action, recall=recall, spec=spec, deadline=deadline,
                                     share=int(e.get("share") or 1))
        return {"spec": spec, **res.as_dict()}

    def step_deliver_done(self, e: dict) -> dict:
        """After the Map: batches with sends still queued (a 429, out of time) or that stopped are run again
        after wait_seconds, at most PUKAAR_DELIVERY_MAX_PASSES passes in all; then the round is finished."""
        alert = self._alert(e["alert_id"])
        mode, pass_no = e.get("mode", "deliver"), int(e.get("pass") or 1)
        results = [r for r in (e.get("results") or []) if isinstance(r, dict)]
        counts = dict(e.get("counts") or {"sent": 0, "failed": 0})
        for r in results:
            counts["sent"] = counts.get("sent", 0) + int(r.get("sent") or 0)
            counts["failed"] = counts.get("failed", 0) + int(r.get("failed") or 0)
        todo = sorted((r["spec"] for r in results if isinstance(r.get("spec"), dict)
                       and (r.get("unfinished") or r.get("deferred"))), key=lambda sp: int(sp["batch"]))
        retry = max((float(r.get("retry_after") or 0) for r in results), default=0.0)
        if todo and pass_no < get_settings().delivery_max_passes:
            out = self._more(alert.id, mode, todo, pass_no + 1, retry, counts)
            self.repo.add_timeline(alert.id, "delivery_pass",
                                   f"{mode} pass {pass_no}: {len(todo)} batch(es) still have sends queued "
                                   f"(rate limit or time); sending them again in {out['wait_seconds']} s")
            return out
        if todo:
            counts["failed"] += self._not_reached(alert, mode, todo, pass_no)
        return self._finish_round(alert.id, mode, counts, passes=pass_no,
                                  batches=int(counts.get("batches") or len(results)))

    def _not_reached(self, alert: Alert, mode: str, specs: list[dict], passes: int) -> int:
        """Out of passes: anyone in these batches the round never got to is recorded as failed, with the
        reason (the recall re-sends to them). Rows put back unsent already say "queued, not sent"."""
        if mode == "recall":
            return 0
        missing = 0
        for spec in specs:
            chunk = dispatch.batch_people(self.repo, alert, spec)
            have = {(d.recipient_id, d.channel) for d in self.repo.get_deliveries(alert.id, [r.id for r in chunk])}
            for r in chunk:
                for ch in dispatch._channels(r, alert):
                    if (r.id, ch) in have:
                        continue
                    self.repo.put_delivery(Delivery(alert_id=alert.id, recipient_id=r.id, name=r.name, channel=ch,
                                                    status="failed", error=f"not sent: the delivery stopped before "
                                                                           f"this person after {passes} passes"))
                    missing += 1
        if missing:
            metric("DeliveryFailed", missing, Channel="unsent")
        return missing

    def _finish_round(self, alert_id: str, mode: str, counts: dict, *, passes: int, batches: int) -> dict:
        alert = self._alert(alert_id)
        sent, failed = int(counts.get("sent", 0)), int(counts.get("failed", 0))
        scale = f" ({batches} batches, {passes} pass{'es' if passes > 1 else ''})" if batches > 1 else ""
        if mode == "recall":
            rows = self.repo.list_deliveries(alert.id)
            acked = {d.recipient_id for d in rows if d.acknowledged_at}
            metric("UnacknowledgedAlerts", len({d.recipient_id for d in rows} - acked))
            rounds = alert.recall_rounds
            again = rounds < get_settings().voice_max_attempts - 1 and dispatch.voice_retry_due(self.repo, alert)
            self.repo.add_timeline(alert.id, "recall", f"round {rounds}: re-sent to {sent} without acknowledgement"
                                   + scale + ("; another voice round follows" if again else ""))
            return {"alert_id": alert.id, "resent": sent, "again": again, "round": rounds, "mode": "recall",
                    "more": False}
        if mode == "deliver" and alert.status == "delivering":
            alert = self.repo.update_alert(alert.id, status="delivered")
            events.alert_changed(alert)
        # In people reached: a voice call counts once answered, a "both" recipient once (dispatch.recount).
        alert = dispatch.recount(self.repo, alert.id) or alert
        if mode == "failsafe":
            events.counts_changed(alert)
            self.repo.add_timeline(alert.id, "failsafe_delivery", f"fixed template sent={sent} failed={failed}{scale}")
        else:
            self.repo.add_timeline(alert.id, "delivered", f"sent={sent} failed={failed}{scale}")
        return {"alert_id": alert.id, "sent": sent, "failed": failed, "mode": mode, "more": False}

    def step_failsafe(self, e: dict) -> dict:
        """A broken workflow never means silence: critical or approved alerts go out
        with the fixed template; anything else is put in front of the officers only."""
        alert = self.repo.get_alert(e.get("alert_id", ""))
        if alert is None:
            log(_LOG, "failsafe for unknown alert", 40, alert_id=e.get("alert_id"), error=e.get("error"))
            return {"alert_id": e.get("alert_id"), "sent": 0}
        error = str(e.get("error"))[:200]
        try:
            text_hi, text_en = hi.fallback_alert(alert.level, alert.village_name_hi, alert.village_name,
                                                 alert.decision_trace.get("safe_place"))
            broadcast = alert.level == "critical" or alert.approved
            alert = self.repo.update_alert(alert.id, status="failsafe", text_hi=text_hi, text_en=text_en, task_token=None)
            events.alert_changed(alert)
            for officer in self._officers(alert):
                dispatch.notify_officer(self.repo, alert, officer,
                                        f"{get_settings().web_url}/console?alert={alert.id}")
            self.repo.add_timeline(alert.id, "failsafe",
                                   f"workflow error {error}; " + ("fixed template to everyone" if broadcast
                                                                   else "not critical and not approved: officers notified, nothing sent"))
            if not broadcast:
                return {"alert_id": alert.id, "sent": 0, "mode": "failsafe", "more": False}
            out = self._start_round(alert, "failsafe", "failsafe")  # the rest, if any, in the Map state
            return {**out, "sent": out.get("sent", out.get("counts", {}).get("sent", 0))}
        except Exception as exc:
            log(_LOG, "failsafe error", 40, alert_id=alert.id, error=str(exc)[:300])
            return {"alert_id": alert.id, "sent": 0}

    def step_close(self, e: dict) -> dict:
        alert_id = e.get("alert_id", "")
        outcome = e.get("outcome") or "closed"
        try:
            alert = self.repo.get_alert(alert_id)
            if alert is None:
                return {"alert_id": alert_id, "status": "missing"}
            status = outcome if outcome in {"delivered", "declined", "expired", "auto_sent_unapproved", "failsafe"} else "closed"
            events.alert_changed(self.repo.update_alert(alert.id, status=status, task_token=None), kind="closed")
            # A replay alert belongs to the replay's copy of the village, never the live record.
            if alert.replay:
                village = self.repo.get_replay_village(alert.village_id)
                if village and village.open_alert_id == alert.id:
                    self.repo.update_replay_village(village.id, open_alert_id=None)
            else:
                village = self.repo.get_village(alert.village_id)
                if village and village.open_alert_id == alert.id:
                    self.repo.update_village(village.id, open_alert_id=None)
            self.repo.add_timeline(alert.id, "closed", f"outcome={outcome}")
            out: dict[str, Any] = {"alert_id": alert.id, "status": status}
            try:  # "Surakshit Hoon": live warning/critical alerts that reached phones open a safety roll-call
                rc = rollcall.open_after_alert(self.repo, self.repo.get_alert(alert.id) or alert, status)
                if rc is not None:
                    out["rollcall_id"] = rc.id
            except Exception as exc:  # a roll-call problem never breaks closing the alert
                log(_LOG, "roll-call open error", 40, alert_id=alert.id, error=str(exc)[:300])
            try:  # after-action report: stored in S3, e-mailed with SES when configured; never breaks closing
                report = after_action.on_close(self.repo, alert.id)
                if report.get("stored"):
                    out["after_action_key"] = report["stored"]
            except Exception as exc:
                log(_LOG, "after-action error", 40, alert_id=alert.id, error=str(exc)[:300])
                metric("AfterActionFailed")
            return out
        except Exception as exc:
            log(_LOG, "close error", 40, alert_id=alert_id, error=str(exc)[:300])
            return {"alert_id": alert_id, "status": "error"}


# -- the all-clear --------------------------------------------------------------------------------
def stand_down_village(repo: Repo, village_id: str, *, replay: bool, by: str, reason: str,
                       now: datetime | None = None) -> dict[str, Any]:
    """Stand down every recent alert of the village (live, or the replay's own) that reached anyone."""
    now = now or clock.now()
    alerts = [a for a in repo.list_alerts(village_id=village_id, limit=50)
              if a.replay == replay and a.all_clear_at is None
              and now - clock.parse(a.created_at) <= timedelta(hours=ALL_CLEAR_WINDOW_HOURS)]
    return stand_down(repo, alerts, by=by, reason=reason)


def stand_down(repo: Repo, alerts: Iterable[Alert], *, by: str, reason: str) -> dict[str, Any]:
    """Send a short Hindi and English all-clear to every person contacted for these alerts, on the
    same channels (Telegram; a call for a voice row), and to every officer who was asked or decided.

    Once per alert (a conditional write on all_clear_at), and once per person and channel even when
    several alerts reached them. Every send passes Cedar ("all_clear"): a replay goes to the stub
    only and never to a real phone, and its officers are not messaged either. Never raises.
    """
    summary: dict[str, Any] = {"alerts": [], "people": 0, "failed": 0, "officers": 0}
    done: dict[tuple[str, str], tuple[str, str | None, str | None]] = {}
    officers_done: set[str] = set()
    for alert in alerts:
        try:
            _stand_down_one(repo, alert, by, reason, done, officers_done, summary)
        except Exception as exc:
            log(_LOG, "all-clear error", 40, alert_id=alert.id, error=str(exc)[:300])
    return summary


def _stand_down_one(repo: Repo, alert: Alert, by: str, reason: str, done: dict, officers_done: set[str],
                    summary: dict[str, Any]) -> None:
    rows = [d for d in repo.list_deliveries(alert.id) if d.status in CONTACTED and d.all_clear_status is None]
    if not rows:
        return
    at = clock.iso(clock.now())
    try:
        alert = repo.update_alert(alert.id, condition=Attr("all_clear_at").not_exists(), all_clear_at=at,
                                  all_clear_by=by, all_clear_reason=reason[:200])
    except ConflictError:
        return  # stood down already (a second sweep, or an officer at the same moment)
    drill = bool(alert.decision_trace.get("drill"))
    text = hi.all_clear_message(alert.village_name_hi, alert.village_name, drill)
    decisions: dict[str, Any] = {}
    sent: set[str] = set()
    failed: set[str] = set()
    by_channel: dict[str, int] = {}
    for d in rows:
        key = (d.recipient_id, d.channel)
        if key not in done:
            done[key] = _all_clear_row(repo, alert, d, text, drill, decisions)
        status, error, call_id = done[key]
        fields = {k: v for k, v in {"all_clear_status": status, "all_clear_at": at, "all_clear_error": error,
                                    "all_clear_call_id": call_id}.items() if v is not None}
        try:
            repo.update_delivery(alert.id, d.recipient_id, channel=d.channel, **fields)
        except ConflictError:
            pass
        if status == "failed":
            failed.add(d.recipient_id)
        else:
            sent.add(d.recipient_id)
            by_channel[d.channel] = by_channel.get(d.channel, 0) + 1
    failed -= sent
    officers = _officers_contacted(alert)
    told = 0
    if not alert.replay:  # a replay's officers are real phones too: the console shows it, nothing is sent
        for officer in officers:
            if officer in officers_done or _tell_officer(repo, alert, officer, reason, drill):
                told += 1
            officers_done.add(officer)
    alert = repo.update_alert(alert.id, all_clear_sent=len(sent), all_clear_failed=len(failed))
    channels = ", ".join(f"{c} {n}" for c, n in sorted(by_channel.items())) or "none"
    repo.add_timeline(alert.id, "all_clear",
                      f"stood down by {by}: {reason}. All-clear to {len(sent)} people ({channels}) and "
                      f"{told} of {len(officers)} officers; {len(failed)} failed"
                      + ("; replay: stub only, no real phone" if alert.replay else ""))
    metric("AllClearSent", len(sent))
    if failed:
        metric("AllClearFailed", len(failed))
    events.alert_changed(alert)
    summary["alerts"].append(alert.id)
    summary["people"] += len(sent)
    summary["failed"] += len(failed)
    summary["officers"] += told


def _officers_contacted(alert: Alert) -> list[str]:
    people = list(alert.officers_asked)
    decider = (alert.decided_by or "").split(" ")[0]  # "officer1 (link)" decided from the one-tap link
    if decider and not decider.startswith("system") and decider not in people:
        people.append(decider)
    return people


def _all_clear_row(repo: Repo, alert: Alert, d: Delivery, text: str, drill: bool,
                   decisions: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """(status, error, all-clear call id) for one person on one channel."""
    channel = d.channel
    if channel not in decisions:
        decisions[channel] = authorize(SYSTEM, "all_clear", "alert", alert.id,
                                       {"replay": alert.replay, "channel": channel, "level": alert.level}, repo=repo)
    decision = decisions[channel]
    if not decision.allowed:
        return "failed", f"blocked: {decision.reason}"[:200], None
    if channel == "stub":
        return "stub", None, None
    try:
        if channel == "telegram":
            if not telegram.configured():
                raise telegram.TelegramError("Telegram token unavailable")
            telegram.send_text(d.recipient_id, text)
            return "sent", None, None
        if channel == "voice":
            person = repo.get_recipient(alert.village_id, d.recipient_id)
            if person is None or not person.takes_voice:
                return "failed", "no longer takes calls", None
            attempt = voice.place_call(person, alert, None, attempt=voice.ALL_CLEAR_ATTEMPT)
            return "sent", None, attempt.call_id
        return "failed", f"unknown channel {channel}", None
    except Exception as exc:
        log(_LOG, "all-clear send failed", 30, alert_id=alert.id, channel=channel, error=voice.mask(str(exc))[:200])
        return "failed", voice.mask(str(exc))[:200], None


def _tell_officer(repo: Repo, alert: Alert, officer: str, reason: str, drill: bool) -> bool:
    """Telegram and Web Push, whichever the officer has. True if either reached them."""
    ok = False
    chat = repo.get_officer_chat(officer)
    if chat and telegram.configured():
        try:
            telegram.send_text(chat, hi.all_clear_officer(alert.village_name_hi, alert.village_name, alert.id,
                                                          reason, drill))
            ok = True
        except Exception as exc:
            log(_LOG, "officer all-clear failed", 30, alert_id=alert.id, error=str(exc)[:200])
    payload = {
        "kind": "all_clear",
        "title": f"पुकार: {alert.village_name_hi} – ख़तरा टला · All clear",
        "body": f"{alert.village_name}: stood down ({reason}). The all-clear went to everyone contacted.",
        "tag": f"{alert.id}-clear", "renotify": True, "requireInteraction": False, "actions": [],
        "data": {"url": f"{get_settings().web_url}/console", "alert_id": alert.id},
    }
    if officer_push.send_to_user(repo, officer, payload, ttl=3600, urgency="normal", kind="all_clear").sent:
        ok = True
    return ok
