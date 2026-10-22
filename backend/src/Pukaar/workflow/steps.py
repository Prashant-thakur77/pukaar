"""Approval workflow steps (one Lambda, dispatch on "step"; see infra/approval.asl.json).

Every step that can send calls the Cedar guard first. failsafe and close never
raise, even for an unknown alert, so a broken run always ends.

Who is asked: the district's duty roster for the shift on duty when the alert is drafted, in IST
(services/roster.py): the primary, then the backup, then the escalation officer above them (the
ADM or the DM), else the village's fallback list. Half-way through each officer's window the
officer is reminded on every channel they have (Web Push and Telegram) before the next is asked.

The all-clear (stand_down): when a village is back to normal, or an officer issues the all-clear,
everyone contacted for its alerts hears so on the channel they were warned on, and so does every
officer who was asked. A replay never reaches a real phone, here as everywhere.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

from boto3.dynamodb.conditions import Attr

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log, metric
from Pukaar.delivery import dispatch, telegram, voice
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


def approval_timers() -> dict[str, int]:
    """The two halves of an officer's approval window: the nudge comes after the first."""
    total = max(2, get_settings().approval_timeout_seconds)
    first = total // 2
    return {"nudge_after_seconds": first, "nudge_wait_seconds": total - first}


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
                "recipients_count": len(recipients), **approval_timers()}

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
        """Half the window has passed with no decision: remind the same officer on every channel they
        have (Web Push and Telegram), then wait the other half before the next officer is asked.

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
        wait = approval_timers()["nudge_wait_seconds"]
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
        metric("OfficerNudged", 1)
        self.repo.add_timeline(alert.id, "nudged_officer",
                               f"{officer} ({self._role(alert, index)}) has not answered half-way through; "
                               f"reminded: telegram={'yes' if sent else 'no'}; push={pushed}; "
                               f"next officer in {minutes} min")
        return {"alert_id": alert.id, "officer": officer, "telegram": sent, "push": pushed}

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
        return {"has_next": nxt < len(officers), "officer_index": nxt, "level": alert.level}

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
        sent, failed = dispatch.deliver(self.repo, alert, action=action)
        if action == "deliver":
            alert = self.repo.update_alert(alert.id, status="delivered")
            events.alert_changed(alert)
        # In people reached: a voice call counts once answered, a "both" recipient once (dispatch.recount).
        alert = dispatch.recount(self.repo, alert.id) or alert
        self.repo.add_timeline(alert.id, "delivered", f"sent={sent} failed={failed}")
        return {"alert_id": alert.id, "sent": sent, "failed": failed}

    def step_recall(self, e: dict) -> dict:
        """Re-send to people who have not acknowledged: Telegram once, voice calls up to
        PUKAAR_VOICE_MAX_ATTEMPTS in all. "again" asks the state machine for another voice round
        after VoiceRetrySeconds; recall_rounds bounds the loop even if a status callback never comes."""
        alert = self._alert(e["alert_id"])
        if alert.all_clear_at:  # stood down: never re-send a warning after the all-clear went out
            self.repo.add_timeline(alert.id, "recall", "skipped: the alert was stood down and the all-clear sent")
            return {"alert_id": alert.id, "resent": 0, "again": False, "round": alert.recall_rounds}
        action = "auto_send" if alert.status == "auto_sent_unapproved" else "deliver"
        rounds = alert.recall_rounds + 1
        alert = self.repo.update_alert(alert.id, recall_rounds=rounds)
        resent, _ = dispatch.deliver(self.repo, alert, action=action, recall=True)
        rows = self.repo.list_deliveries(alert.id)
        acked = {d.recipient_id for d in rows if d.acknowledged_at}
        metric("UnacknowledgedAlerts", len({d.recipient_id for d in rows} - acked))
        again = rounds < get_settings().voice_max_attempts - 1 and dispatch.voice_retry_due(self.repo, alert)
        self.repo.add_timeline(alert.id, "recall", f"round {rounds}: re-sent to {resent} without acknowledgement"
                                                   + ("; another voice round follows" if again else ""))
        return {"alert_id": alert.id, "resent": resent, "again": again, "round": rounds}

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
            sent = 0
            if broadcast:
                sent, _ = dispatch.deliver(self.repo, alert, action="failsafe")
                alert = dispatch.recount(self.repo, alert.id) or alert
            events.alert_changed(alert)
            if broadcast:
                events.counts_changed(alert)
            for officer in self._officers(alert):
                dispatch.notify_officer(self.repo, alert, officer,
                                        f"{get_settings().web_url}/console?alert={alert.id}")
            self.repo.add_timeline(alert.id, "failsafe",
                                   f"workflow error {error}; " + (f"fixed template sent to {sent}" if broadcast
                                                                   else "not critical and not approved: officers notified, nothing sent"))
            return {"alert_id": alert.id, "sent": sent}
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
