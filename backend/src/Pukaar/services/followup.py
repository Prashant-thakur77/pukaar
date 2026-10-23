"""The "why we warned" note: one short Hindi and English message to everyone an alert reached, after it ends.

The cry-wolf evidence is mixed, and Bihar's trust rose while false alarms doubled; what keeps a warning believed is
explaining it (Jagnani and Pande 2024; Watanabe et al. 2026: people who felt relieved by a false alarm kept
evacuating). So after each alert Pukaar says what it saw, what happened, and thanks the person for confirming (or
asks them to confirm next time).

When: the first of these, once per alert (a conditional write on Alert.followup_at):
  outcome    an officer recorded "was this real?" (api/routers/officer.set_outcome): the note says what happened
  all_clear  the alert was stood down FOLLOWUP_DELAY_MINUTES (60) ago with no answer yet: "the danger has passed"
  expired    a closed alert with no all-clear, EXPIRE_HOURS (24) after it was made
The sweep looks for due alerts every 15 minutes (run_due); the outcome route sends at once.

Who: every person a delivery row says was contacted (sent, acknowledged, or a call still pending), each once. A
Telegram row gets the note; a voice-only person is not called again for it (a call is billed by the minute) and is
counted as skipped; a demo stub row is recorded and sends nothing. Replays never: they reached no real phone. A drill
says DRILL. Every send passes Cedar ("followup"; a replay may reach the stub only).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

from boto3.dynamodb.conditions import Attr

from Pukaar.core import clock
from Pukaar.core.log import get_logger, log, metric
from Pukaar.store.models import OPEN_ALERT_STATUSES, Alert
from Pukaar.store.repo import ConflictError, Repo
from Pukaar.templates import care, script

_LOG = get_logger("followup")
FOLLOWUP_DELAY_MINUTES = max(0, int(os.environ.get("PUKAAR_FOLLOWUP_DELAY_MINUTES", "60") or "60"))
EXPIRE_HOURS = max(1, int(os.environ.get("PUKAAR_FOLLOWUP_EXPIRE_HOURS", "24") or "24"))
LOOK_BACK_DAYS = 7
CONTACTED = {"sent", "acknowledged", "pending"}


def _is_replay(a: Alert) -> bool:
    return bool(a.replay or a.decision_trace.get("replay"))


def seen_key(trace: dict[str, Any] | None) -> str:
    rules = [str(r) for r in ((trace or {}).get("rules_fired") or [])]
    if any(r.startswith("gauge_silent_in_rain:") for r in rules):
        return "gauge_silent"
    key = script.hazard_key(trace)
    if key == "flood" and any(r.startswith(("verified_reports", "verified_impact_report", "staff_gauge")) for r in rules):
        return "reports"
    return key


def due(a: Alert, now: datetime) -> str | None:
    """The trigger that makes this alert's note due now, or None."""
    if _is_replay(a) or a.followup_at or a.status in OPEN_ALERT_STATUSES or a.delivered_count <= 0:
        return None  # a declined or expired alert reached nobody: there is nobody to explain it to
    if a.outcome:
        return "outcome"
    if a.all_clear_at and now - clock.parse(a.all_clear_at) >= timedelta(minutes=FOLLOWUP_DELAY_MINUTES):
        return "all_clear"
    if not a.all_clear_at and now - clock.parse(a.created_at) >= timedelta(hours=EXPIRE_HOURS):
        return "expired"
    return None


def send(repo: Repo, alert: Alert, trigger: str, now: datetime | None = None) -> dict[str, Any] | None:
    """Send the note for this alert once. None when it was sent already, or the alert is a replay or still open.
    Never raises."""
    now = now or clock.now()
    if _is_replay(alert) or alert.status in OPEN_ALERT_STATUSES:
        return None
    try:
        rows = [d for d in repo.list_deliveries(alert.id) if d.status in CONTACTED]
        try:  # claim: of the sweep and the outcome route at the same moment, one sends
            alert = repo.update_alert(alert.id, condition=Attr("followup_at").not_exists(),
                                      followup_at=clock.iso(now), followup_trigger=trigger)
        except ConflictError:
            return None
        if not rows:
            repo.add_timeline(alert.id, "followup", f"why-we-warned note ({trigger}): nobody was reached, none sent")
            return {"sent": 0, "failed": 0, "skipped": 0}
        return _send_rows(repo, alert, trigger, rows)
    except Exception as exc:
        log(_LOG, "follow-up failed", 40, alert_id=alert.id, error=str(exc)[:300])
        return None


def _send_rows(repo: Repo, alert: Alert, trigger: str, rows: list) -> dict[str, Any]:
    from Pukaar.delivery import telegram
    from Pukaar.policy.guard import SYSTEM, authorize

    drill = bool(alert.decision_trace.get("drill"))
    seen = seen_key(alert.decision_trace)
    confirmed = {d.recipient_id for d in rows if d.acknowledged_at}
    telegram_people = {d.recipient_id for d in rows if d.channel == "telegram"}
    decisions: dict[str, Any] = {}
    sent = failed = skipped = 0
    done: set[str] = set()
    for d in sorted(rows, key=lambda r: r.channel != "telegram"):  # Telegram first: a "both" person gets it there
        if d.recipient_id in done:
            continue
        done.add(d.recipient_id)
        if d.channel == "voice" and d.recipient_id not in telegram_people:
            skipped += 1  # not called again for a note: voice is billed per minute
            continue
        if d.channel not in decisions:
            decisions[d.channel] = authorize(SYSTEM, "followup", "alert", alert.id,
                                             {"replay": _is_replay(alert), "channel": d.channel, "level": alert.level},
                                             repo=repo)
        if not decisions[d.channel].allowed:
            failed += 1
            continue
        if d.channel == "stub":
            skipped += 1
            continue
        text = care.why_we_warned(alert.village_name_hi, alert.village_name, alert.level, seen, alert.outcome,
                                  d.recipient_id in confirmed, drill)
        try:
            if not telegram.configured():
                raise telegram.TelegramError("Telegram token unavailable")
            telegram.send_text(d.recipient_id, text)
            sent += 1
        except Exception as exc:
            failed += 1
            log(_LOG, "follow-up send failed", 30, alert_id=alert.id, error=str(exc)[:200])
    repo.update_alert(alert.id, followup_sent=sent, followup_failed=failed, followup_skipped=skipped)
    repo.add_timeline(alert.id, "followup",
                      f"why-we-warned note ({trigger}{', outcome ' + alert.outcome if alert.outcome else ''}): "
                      f"sent {sent}, failed {failed}, skipped {skipped} (voice-only or demo)")
    if sent:
        metric("FollowupSent", sent)
    if failed:
        metric("FollowupFailed", failed)
    return {"sent": sent, "failed": failed, "skipped": skipped}


def run_due(repo: Repo, now: datetime | None = None) -> int:
    """The sweep: send each due note among the alerts of the last LOOK_BACK_DAYS. Returns how many alerts. Never raises."""
    now = now or clock.now()
    n = 0
    try:
        since = now - timedelta(days=LOOK_BACK_DAYS)
        for a in repo.list_alerts(limit=200):
            if clock.parse(a.created_at) < since:
                continue
            trigger = due(a, now)
            if trigger and send(repo, a, trigger, now) is not None:
                n += 1
    except Exception as exc:
        log(_LOG, "follow-up sweep failed", 40, error=str(exc)[:300])
    return n
