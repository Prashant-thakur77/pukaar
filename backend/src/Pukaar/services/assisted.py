"""Assisted households and the village's observers.

Assisted households (Recipient.assisted: older, disabled, living alone, pregnant). When one has not confirmed a live
or drill alert PUKAAR_ASSISTED_ESCALATE_MINUTES (10) after the first send, the person named to check on them
(Recipient.escalate_to, a neighbour or relay of the same village; else the village's relays, the pradhan first) gets
one Telegram message with a "देख लिया / Checked" button. Once per person per alert: a conditional write on the
delivery row's escalated_at claims it before anything is sent. The check runs on each recall round and on each
15-minute sweep (run_due). Replays never: they reach no real phone. Pilot metric 3 counts the assisted households
confirmed, and the ones their neighbour checked.

Two observers per village. Babai 2014 had one gauge, one reader and one phone. A village is ready when at least
two people hold an observer or relay role (pradhan, gauge reader, task force), and half of them women is encouraged
(Bangladesh's Cyclone Preparedness Programme: 76,020 volunteers, half women). Recipient.gender is optional and only
counts coverage here; it never decides who is warned or in what order. village_care() names the gaps for the roster
page.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

from boto3.dynamodb.conditions import Attr

from Pukaar.core import clock
from Pukaar.core.ids import new_id
from Pukaar.core.log import get_logger, log, metric
from Pukaar.store.models import RELAY_ROLES, Alert, AuditRow, Recipient
from Pukaar.store.repo import ConflictError, Repo
from Pukaar.templates import care

_LOG = get_logger("assisted")
ESCALATE_MINUTES = max(1, int(os.environ.get("PUKAAR_ASSISTED_ESCALATE_MINUTES", "10") or "10"))
MIN_OBSERVERS = 2
WOMEN_SHARE_GOAL = 0.5
REASONS = ("elderly", "disabled", "alone", "pregnant", "other")
GENDERS = ("female", "male", "other")
# Alerts whose people may still need a check: sent, and not stood down.
SENT = {"delivering", "delivered", "auto_sent_unapproved", "failsafe", "closed"}
LOOK_BACK_HOURS = 12


class CareError(ValueError):
    """The assisted flag, neighbour or gender cannot be set; the message says why."""


def set_care(repo: Repo, village_id: str, recipient_id: str, *, assisted: bool | None = None,
             reason: str | None = None, escalate_to: str | None = None, gender: str | None = None,
             actor: str, actor_role: str) -> Recipient:
    """Set who needs a check and who checks on them, and the optional gender; audited ("recipient_care_changed").
    KeyError for an unknown recipient. An empty string clears escalate_to, reason or gender."""
    r = repo.get_recipient(village_id, recipient_id)
    if r is None:
        raise KeyError(recipient_id)
    if r.role == "officer":
        raise CareError("an officer's entry is not changed here")
    update: dict[str, Any] = {}
    if assisted is not None:
        update["assisted"] = bool(assisted)
    if reason is not None:
        if reason and reason not in REASONS:
            raise CareError(f"reason must be one of {', '.join(REASONS)}")
        update["assisted_reason"] = reason or None
    if escalate_to is not None:
        if escalate_to:
            if escalate_to == recipient_id:
                raise CareError("a person cannot be their own neighbour to check")
            other = repo.get_recipient(village_id, escalate_to)
            if other is None:
                raise CareError("the neighbour must be a registered person of the same village")
        update["escalate_to"] = escalate_to or None
    if gender is not None:
        if gender and gender not in GENDERS:
            raise CareError(f"gender must be one of {', '.join(GENDERS)}, or empty")
        update["gender"] = gender or None
    before = {k: getattr(r, k) for k in update}
    if update:
        r = r.model_copy(update=update)
        repo.put_recipient(r)
    changed = ", ".join(f"{k}: {before[k]} -> {update[k]}" for k in update if before[k] != update[k]) or "no change"
    repo.append_audit(AuditRow(at=clock.iso(clock.now()), id=new_id("aud"), actor=actor, role=actor_role,
                               action="recipient_care_changed", resource=f"recipient:{village_id}/{recipient_id}",
                               decision="allow", reason=changed[:300]))
    return r


def view(r: Recipient) -> dict[str, Any]:
    return {"assisted": r.assisted, "assisted_reason": r.assisted_reason, "escalate_to": r.escalate_to,
            "gender": r.gender}


# -- escalation --------------------------------------------------------------------------------------
def _first_send(rows: list) -> str | None:
    times = [d.sent_at or d.last_attempt_at for d in rows if d.sent_at or d.last_attempt_at]
    return min(times) if times else None


def _targets(person: Recipient, people: dict[str, Recipient]) -> list[Recipient]:
    named = people.get(person.escalate_to or "")
    if named is not None and named.takes_telegram:
        return [named]
    relays = sorted((p for p in people.values() if p.is_relay and p.id != person.id and p.takes_telegram),
                    key=lambda p: (p.role != "pradhan", p.id))
    return relays[:2]


def escalate_due(repo: Repo, alert: Alert, now: datetime | None = None) -> int:
    """Ask a neighbour or relay to check on each assisted household that has not confirmed in time. Returns how many
    were escalated now. Never raises."""
    now = now or clock.now()
    if alert.replay or alert.status not in SENT or alert.all_clear_at:
        return 0
    try:
        people = {p.id: p for p in repo.list_recipients(alert.village_id)}
        assisted = {pid: p for pid, p in people.items() if p.assisted}
        if not assisted:
            return 0
        rows = repo.list_deliveries(alert.id)
        first = _first_send([d for d in rows if d.channel != "stub"])
        if first is None or now - clock.parse(first) < timedelta(minutes=ESCALATE_MINUTES):
            return 0
        acked = {d.recipient_id for d in rows if d.acknowledged_at}
        done = {d.recipient_id for d in rows if d.escalated_at}
        n = 0
        for d in rows:
            person = assisted.get(d.recipient_id)
            if person is None or d.recipient_id in acked or d.recipient_id in done or d.channel == "stub":
                continue
            if _escalate_one(repo, alert, person, d, people, now):
                n += 1
            done.add(d.recipient_id)
        if n:
            metric("AssistedEscalated", n)
        return n
    except Exception as exc:
        log(_LOG, "assisted escalation failed", 40, alert_id=alert.id, error=str(exc)[:300])
        return 0


def _escalate_one(repo: Repo, alert: Alert, person: Recipient, d, people: dict[str, Recipient], now: datetime) -> bool:
    from Pukaar.delivery import telegram
    from Pukaar.policy.guard import SYSTEM, authorize

    targets = _targets(person, people)
    at = clock.iso(now)
    try:  # claim first: of any number of sweeps and recall rounds, one sends
        repo.update_delivery(alert.id, d.recipient_id, channel=d.channel, condition=Attr("escalated_at").not_exists(),
                             escalated_at=at, escalated_to=",".join(t.id for t in targets)[:200] or None)
    except ConflictError:
        return False
    first = care.first_name(person.name)
    if not targets:
        repo.update_delivery(alert.id, d.recipient_id, channel=d.channel,
                             escalation_error="nobody named to check, and no relay on Telegram")
        repo.add_timeline(alert.id, "assisted_unchecked", f"{first} (assisted) has not confirmed; nobody is named to "
                                                          f"check on them and the village has no relay on Telegram")
        return True
    action = "auto_send" if alert.status == "auto_sent_unapproved" else "deliver"
    decision = authorize(SYSTEM, action, "alert", alert.id,
                         {"approved": alert.approved, "level": alert.level, "replay": alert.replay,
                          "channel": "telegram", "all_officers_timed_out": alert.status == "auto_sent_unapproved"},
                         repo=repo)
    drill = bool(alert.decision_trace.get("drill"))
    text = care.assisted_check(first, person.assisted_reason, alert.village_name_hi, alert.village_name, alert.level,
                               ESCALATE_MINUTES, drill)
    sent, errors = [], []
    for t in targets:
        if not decision.allowed:
            errors.append(f"blocked: {decision.reason}")
            break
        if not telegram.configured():
            errors.append("Telegram token unavailable")
            break
        try:
            telegram._call("sendMessage", {"chat_id": t.id, "text": text[:4096], "reply_markup": {
                "inline_keyboard": [[{"text": care.CHECKED_BUTTON,
                                      "callback_data": f"chk:{alert.id}:{person.id}"[:64]}]]}})
            sent.append(care.first_name(t.name))
        except Exception as exc:
            errors.append(str(exc)[:120])
    if errors and not sent:
        repo.update_delivery(alert.id, d.recipient_id, channel=d.channel, escalation_error="; ".join(errors)[:200])
    repo.add_timeline(alert.id, "assisted_escalated",
                      f"{first} (assisted) had not confirmed after {ESCALATE_MINUTES} min; asked "
                      + (", ".join(sent) if sent else "nobody (" + "; ".join(errors)[:120] + ")") + " to check")
    return True


def checked(repo: Repo, alert_id: str, recipient_id: str, by_chat: str) -> str:
    """The neighbour pressed "देख लिया": recorded once, and only from someone asked. Returns the toast text."""
    rows = [d for d in repo.get_deliveries(alert_id, [recipient_id]) if d.escalated_at]
    if not rows:
        return care.CHECK_NOT_YOURS
    asked = {x for d in rows for x in (d.escalated_to or "").split(",") if x}
    if by_chat not in asked:
        return care.CHECK_NOT_YOURS
    d = rows[0]
    try:
        repo.update_delivery(alert_id, recipient_id, channel=d.channel, condition=Attr("checked_at").not_exists(),
                             checked_at=clock.iso(clock.now()), checked_by=by_chat)
    except ConflictError:
        return care.CHECK_SAME
    try:
        alert = repo.get_alert(alert_id)
        who = repo.get_recipient(alert.village_id, by_chat) if alert else None
        person = repo.get_recipient(alert.village_id, recipient_id) if alert else None
        repo.add_timeline(alert_id, "assisted_checked",
                          f"{care.first_name(who.name if who else '?')} checked on "
                          f"{care.first_name(person.name if person else d.name)} (assisted)")
        metric("AssistedChecked", 1)
    except Exception as exc:
        log(_LOG, "checked record failed", 30, alert_id=alert_id, error=str(exc)[:200])
    return care.CHECK_THANKS


def run_due(repo: Repo, now: datetime | None = None) -> int:
    """The sweep: escalations due on alerts sent in the last LOOK_BACK_HOURS. Never raises."""
    now = now or clock.now()
    n = 0
    try:
        since = now - timedelta(hours=LOOK_BACK_HOURS)
        for a in repo.list_alerts(limit=200):
            if a.replay or a.status not in SENT or clock.parse(a.created_at) < since:
                continue
            n += escalate_due(repo, a, now)
    except Exception as exc:
        log(_LOG, "assisted sweep failed", 40, error=str(exc)[:300])
    return n


# -- the village's observers and assisted households, for the roster page ---------------------------------
def village_care(repo: Repo, village_id: str) -> dict[str, Any]:
    """Counts and gaps, first names only: observers and relays (two wanted, half women encouraged), assisted
    households and whether each has someone named to check on them, and coverage against the household list."""
    people = [p for p in repo.list_recipients(village_id) if p.role != "officer"]
    phones = [p for p in people if p.channel != "stub"]
    observers = [p for p in phones if p.role in RELAY_ROLES]
    women = sum(1 for p in observers if p.gender == "female")
    known = sum(1 for p in observers if p.gender)
    assisted = [p for p in phones if p.assisted]
    no_one = [p for p in assisted if not p.escalate_to]
    v = repo.get_village(village_id)
    households = v.households if v else None
    gaps: list[str] = []
    if len(observers) < MIN_OBSERVERS:
        gaps.append("observers")
    if observers and known == len(observers) and women / len(observers) < WOMEN_SHARE_GOAL:
        gaps.append("women_observers")
    if no_one:
        gaps.append("assisted_without_neighbour")
    if households is None:
        gaps.append("household_list")
    return {
        "village_id": village_id,
        "observers": len(observers), "observers_needed": MIN_OBSERVERS,
        "observer_roles": sorted({p.role for p in observers}),
        "women_observers": women, "observers_gender_known": known, "women_share_goal": WOMEN_SHARE_GOAL,
        "assisted": len(assisted), "assisted_without_neighbour": [care.first_name(p.name) for p in no_one],
        "registered_phones": len(phones), "households": households,
        "coverage": round(min(1.0, len(phones) / households), 3) if households else None,
        "gaps": gaps,
    }
