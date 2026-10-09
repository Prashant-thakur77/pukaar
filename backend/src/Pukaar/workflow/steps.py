"""Approval workflow steps (one Lambda, dispatch on "step"; see infra/approval.asl.json).

Every step that can send calls the Cedar guard first. failsafe and close never
raise, even for an unknown alert, so a broken run always ends.
"""

from __future__ import annotations

from typing import Any, Callable

from boto3.dynamodb.conditions import Attr

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log, metric
from Pukaar.delivery import dispatch
from Pukaar.llm.bedrock import BedrockLLM
from Pukaar.policy.guard import SYSTEM, authorize
from Pukaar.services.drafting import draft_alert
from Pukaar.store.models import Alert
from Pukaar.store.repo import ConflictError, Repo
from Pukaar.templates import hi
from Pukaar.voice import polly
from Pukaar.workflow import tokens

_LOG = get_logger("workflow")


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
        village = self.repo.get_village(alert.village_id)
        return list(village.officers) if village else []

    # -- steps -----------------------------------------------------------------
    def step_draft(self, e: dict) -> dict:
        alert = self._alert(e["alert_id"])
        village = self.repo.get_village(alert.village_id)
        if village is None:
            raise StepError(f"village {alert.village_id} not found")
        recipients = self.repo.list_recipients(alert.village_id)
        for _ in range(3):  # the sweep may escalate the level while we draft
            result = draft_alert(village, alert.level, alert.decision_trace, self.repo, self.llm)
            trace = dict(alert.decision_trace)
            if result.tools:
                trace["drafting_tools"] = result.tools
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
        self.repo.add_timeline(alert.id, "drafted",
                               f"model={result.reasoning_model}; check={'pass' if result.check.passed else 'fail'}: "
                               f"{result.check.reason}; recipients={len(recipients)}; audio={'yes' if audio_key else 'no'}")
        return {"alert_id": alert.id, "level": alert.level, "officer_count": len(self._officers(alert)),
                "recipients_count": len(recipients)}

    def step_ask_officer(self, e: dict) -> dict:
        alert = self._alert(e["alert_id"])
        officers = self._officers(alert)
        index = int(e.get("officer_index", 0))
        if index >= len(officers):
            raise StepError("officer index out of range")
        officer = officers[index]
        alert = self.repo.update_alert(alert.id, task_token=e["task_token"], officer_index=index,
                                       token_version=alert.token_version + 1, status="pending", approved=False)
        link = tokens.sign(alert.id, officer, alert.token_version, "approve")
        url = f"{get_settings().web_url}/a/{link}"
        sent = dispatch.notify_officer(self.repo, alert, officer, url)
        self.repo.add_timeline(alert.id, "asked_officer",
                               f"{officer} (#{index + 1} of {len(officers)}); telegram={'yes' if sent else 'no'}; console=yes")
        return {"alert_id": alert.id, "officer": officer}

    def step_next_officer(self, e: dict) -> dict:
        alert = self._alert(e["alert_id"])
        officers = self._officers(alert)
        nxt = int(e.get("officer_index", 0)) + 1
        self.repo.update_alert(alert.id, task_token=None, token_version=alert.token_version + 1)
        self.repo.add_timeline(alert.id, "officer_timeout",
                               f"officer #{nxt} did not answer in time" + ("" if nxt < len(officers) else "; list exhausted"))
        return {"has_next": nxt < len(officers), "officer_index": nxt, "level": alert.level}

    def step_auto_send(self, e: dict) -> dict:
        alert = self._alert(e["alert_id"])
        decision = authorize(SYSTEM, "auto_send", "alert", alert.id,
                             {"level": alert.level, "all_officers_timed_out": True, "replay": alert.replay},
                             repo=self.repo)
        if not decision.allowed:
            raise StepError(f"auto-send denied: {decision.reason}")
        text_hi, text_en = hi.fallback_alert(alert.level, alert.village_name_hi, alert.village_name)
        self.repo.update_alert(alert.id, status="auto_sent_unapproved", text_hi=text_hi, text_en=text_en,
                               decided_by="system:auto-send", decided_at=clock.iso(clock.now()))
        self.repo.add_timeline(alert.id, "auto_send", "every officer timed out at critical; fixed template, flagged unapproved")
        return {"alert_id": alert.id, "mode": "auto"}

    def step_expire(self, e: dict) -> dict:
        alert = self._alert(e["alert_id"])
        self.repo.update_alert(alert.id, status="expired", task_token=None)
        self.repo.add_timeline(alert.id, "expired", "no officer answered; not critical, so nothing was sent")
        return {"alert_id": alert.id, "outcome": "expired"}

    def step_deliver(self, e: dict) -> dict:
        alert = self._alert(e["alert_id"])
        action = "auto_send" if alert.status == "auto_sent_unapproved" else "deliver"
        if alert.status not in {"approved", "auto_sent_unapproved"}:
            raise StepError(f"deliver called with status {alert.status}")
        if action == "deliver":
            alert = self.repo.update_alert(alert.id, status="delivering")
        sent, failed = dispatch.deliver(self.repo, alert, action=action)
        fields: dict[str, Any] = {"delivered_count": sent}
        if action == "deliver":
            fields["status"] = "delivered"
        self.repo.update_alert(alert.id, **fields)
        self.repo.add_timeline(alert.id, "delivered", f"sent={sent} failed={failed}")
        return {"alert_id": alert.id, "sent": sent, "failed": failed}

    def step_recall(self, e: dict) -> dict:
        alert = self._alert(e["alert_id"])
        action = "auto_send" if alert.status == "auto_sent_unapproved" else "deliver"
        resent, _ = dispatch.deliver(self.repo, alert, action=action, recall=True)
        unacked = sum(1 for d in self.repo.list_deliveries(alert.id) if not d.acknowledged_at)
        metric("UnacknowledgedAlerts", unacked)
        self.repo.add_timeline(alert.id, "recall", f"re-sent once to {resent} without acknowledgement")
        return {"alert_id": alert.id, "resent": resent}

    def step_failsafe(self, e: dict) -> dict:
        """A broken workflow never means silence: critical or approved alerts go out
        with the fixed template; anything else is put in front of the officers only."""
        alert = self.repo.get_alert(e.get("alert_id", ""))
        if alert is None:
            log(_LOG, "failsafe for unknown alert", 40, alert_id=e.get("alert_id"), error=e.get("error"))
            return {"alert_id": e.get("alert_id"), "sent": 0}
        error = str(e.get("error"))[:200]
        try:
            text_hi, text_en = hi.fallback_alert(alert.level, alert.village_name_hi, alert.village_name)
            broadcast = alert.level == "critical" or alert.approved
            alert = self.repo.update_alert(alert.id, status="failsafe", text_hi=text_hi, text_en=text_en, task_token=None)
            sent = 0
            if broadcast:
                sent, _ = dispatch.deliver(self.repo, alert, action="failsafe")
                self.repo.update_alert(alert.id, delivered_count=sent)
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
            self.repo.update_alert(alert.id, status=status, task_token=None)
            village = self.repo.get_village(alert.village_id)
            if village and village.open_alert_id == alert.id:
                self.repo.update_village(village.id, open_alert_id=None)
            self.repo.add_timeline(alert.id, "closed", f"outcome={outcome}")
            return {"alert_id": alert.id, "status": status}
        except Exception as exc:
            log(_LOG, "close error", 40, alert_id=alert_id, error=str(exc)[:300])
            return {"alert_id": alert_id, "status": "error"}
