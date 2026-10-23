"""The duty officer's day: the 08:00 health digest, the shift handover note, and paging beyond e-mail.

Daily digest (maybe_send_digests, called by every sweep; sent once per district per day from
Settings.duty_digest_hour_ist, 08:00 IST): one message per district to the officers on duty for the shift
then running (services/roster.py; the village fallback list when nobody is rostered), on Telegram and
Web Push. It says, in Hindi and English: when the sweep last ran and how many villages have stale or
missing data; the gauges and sirens that are unhealthy (installed ones; simulators are named as such);
the open alerts; and the readiness gaps (an empty shift in the next 24 hours, a village with nobody
enrolled or no relay, last shift's handover note not acknowledged). The digest reads health without
emitting metrics, so it never doubles an alarm's data points. Each send is in the audit trail.

Handover (write_handover, acknowledge_handover): the outgoing officer writes what the next shift must
know; an officer of the incoming shift acknowledges it. One note per district shift, editable until it is
acknowledged; both steps are audited ("handover_written", "handover_acknowledged") and Cedar holds both to
the officer's district.

Paging (page_alarm, from handlers/pager.py, subscribed to the alarm SNS topic): every CloudWatch alarm that
goes to ALARM (or back to OK) is sent on Telegram and Web Push to the primary and backup officer on duty in
the district the alarm names (its District dimension), or in every district when it names none. E-mail
stays as it was.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.core.log import get_logger, log, metric
from Pukaar.services import roster
from Pukaar.store.models import AuditRow, HandoverNote, Village
from Pukaar.store.repo import ConflictError, Repo

_LOG = get_logger("duty")
HANDOVER_MAX = 1000
TELEGRAM_LIMIT = 3900


class DutyError(ValueError):
    """A handover that cannot be saved; the message says why."""


def _audit(repo: Repo, actor: str, role: str, action: str, resource: str, reason: str) -> None:
    repo.append_audit(AuditRow(at=clock.iso(clock.now()), id=new_id("aud"), actor=actor, role=role, action=action,
                               resource=resource, decision="allow", reason=reason[:900]))


def _villages(repo: Repo, district: str) -> list[Village]:
    return [v for v in repo.list_villages() if v.district == district]


def _fallback(villages: list[Village]) -> list[str]:
    return next((list(v.officers) for v in villages if v.officers), [])


# -- the digest -------------------------------------------------------------------------------------------
def digest(repo: Repo, district: str, now: datetime | None = None) -> dict[str, Any]:
    """The district's health this morning, as data (the console shows it; text() renders it)."""
    from Pukaar.api.views import COUNTERS_SUMMARY
    from Pukaar.services import gauge
    from Pukaar.services.devices import registry
    from Pukaar.store.models import level_rank

    now = now or clock.now()
    villages = _villages(repo, district)
    ids = {v.id for v in villages}
    summary = None
    try:
        summary = repo.get_summary(COUNTERS_SUMMARY)
    except Exception:
        summary = None
    stale = [{"village_id": v.id, "name": v.name, "status": v.data_status, "since": v.data_ok_at, "note": v.data_note}
             for v in villages if v.data_status != "ok"]
    last_data = max((v.data_ok_at for v in villages if v.data_ok_at), default=None)
    gauges = []
    since = clock.iso(now - timedelta(hours=24))
    for v in villages:
        if v.gauge is None:
            continue
        try:
            readings = repo.list_sensor_readings(v.id, since)
            latest = None if readings else repo.latest_sensor_reading(v.id, None, include_backfill=True)
            h = gauge.health(v.gauge, readings, now, latest)
        except Exception as exc:
            h = {"unhealthy": True, "reasons": [f"health unreadable: {type(exc).__name__}"]}
        gauges.append({"village_id": v.id, "device_id": v.gauge.device_id, "installed": v.gauge.installed,
                       "unhealthy": bool(h.get("unhealthy")), "reasons": list(h.get("reasons") or [])})
    devices = []
    for d in repo.list_devices():
        if d.village_id not in ids or d.kind not in registry.SOUNDERS:
            continue
        state, reasons = registry.health(d, now)
        devices.append({"device_id": d.device_id, "village_id": d.village_id, "kind": d.kind, "state": state,
                        "reasons": reasons, "installed": d.installed, "simulated": d.simulated,
                        "test_overdue": registry.test_overdue(d, now)})
    alerts = [a for a in repo.open_alerts() if a.village_id in ids and not a.replay]
    open_alerts = [{"alert_id": a.id, "village_name": a.village_name, "level": a.level, "status": a.status,
                    "created_at": a.created_at} for a in sorted(alerts, key=lambda a: -level_rank(a.level))]
    gaps = readiness_gaps(repo, district, villages, now)
    duty = roster.on_duty(repo, district, now, fallback=_fallback(villages))
    return {
        "district": district, "at": clock.iso(now), "duty": duty.view(),
        "sweep": {"last_run": summary[0] if summary else None, "last_complete_data": last_data,
                  "villages": len(villages), "stale": stale},
        "gauges": gauges, "gauges_unhealthy": [g for g in gauges if g["unhealthy"]],
        "sirens": devices, "sirens_unhealthy": [d for d in devices if d["state"] not in {"ok"} or d["test_overdue"]],
        "open_alerts": open_alerts, "gaps": gaps,
    }


def readiness_gaps(repo: Repo, district: str, villages: list[Village], now: datetime) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    slot = roster.slot_at(now)
    for i in range(3):  # this shift and the next two: 24 hours ahead
        s = roster.slot_at(slot.starts_at + timedelta(hours=12 * i, minutes=1))
        entry = repo.get_roster_shift(district, s.date, s.shift)
        if entry is None or not entry.primary:
            gaps.append({"kind": "roster", "en": f"nobody rostered for the {s.label()}",
                         "hi": f"{s.date} की {'दिन' if s.shift == 'day' else 'रात'} की पाली में कोई ड्यूटी पर नहीं"})
    for v in villages:
        people = [r for r in repo.list_recipients(v.id) if r.channel != "stub"]
        if not people:
            gaps.append({"kind": "enrolment", "en": f"{v.name}: nobody enrolled", "hi": f"{v.name_hi}: कोई नहीं जुड़ा"})
        elif not any(r.is_relay for r in people):
            gaps.append({"kind": "relay", "en": f"{v.name}: no pradhan, gauge reader or task force enrolled",
                         "hi": f"{v.name_hi}: कोई प्रधान, गेज रीडर या टास्क फ़ोर्स नहीं जुड़ा"})
    prev = roster.slot_at(slot.starts_at - timedelta(minutes=1))
    note = repo.get_handover(district, prev.date, prev.shift)
    if note is not None and not note.acknowledged_by:
        gaps.append({"kind": "handover", "en": f"the handover note of the {prev.label()} is not acknowledged",
                     "hi": "पिछली पाली का हैंडओवर नोट स्वीकार नहीं हुआ"})
    return gaps


def text(d: dict[str, Any]) -> str:
    """The digest as one Telegram message (Hindi, then English), under Telegram's limit."""
    sw, district = d["sweep"], d["district"]
    stale = ", ".join(s["name"] for s in sw["stale"]) or "-"
    gu = ", ".join(f"{g['device_id']}{'' if g['installed'] else ' (simulator)'}" for g in d["gauges_unhealthy"]) or "-"
    si = ", ".join(f"{s['device_id']} {s['state']}{' test overdue' if s['test_overdue'] else ''}"
                   f"{' (simulator)' if s['simulated'] else ''}" for s in d["sirens_unhealthy"]) or "-"
    al = ", ".join(f"{a['village_name']} {a['level']} ({a['status']})" for a in d["open_alerts"]) or "-"
    gaps_en = "; ".join(g["en"] for g in d["gaps"]) or "none"
    gaps_hi = "; ".join(g["hi"] for g in d["gaps"]) or "कोई नहीं"
    last = (sw["last_run"] or sw["last_complete_data"] or "unknown")[:16].replace("T", " ")
    body = (
        f"पुकार सुबह की जाँच · {district}\n"
        f"स्वीप: आख़िरी {last} UTC; {len(sw['stale'])}/{sw['villages']} गाँवों का डेटा पुराना या नहीं ({stale})\n"
        f"गेज ठीक नहीं: {gu}\nसायरन ठीक नहीं: {si}\nखुली चेतावनियाँ: {al}\nकमियाँ: {gaps_hi}\n\n"
        f"Pukaar morning check · {district}\n"
        f"Sweep: last {last} UTC; {len(sw['stale'])} of {sw['villages']} villages with stale or missing data ({stale})\n"
        f"Gauges unhealthy: {gu}\nSirens unhealthy: {si}\nOpen alerts: {al}\nReadiness gaps: {gaps_en}\n"
        f"{get_settings().web_url}/console/roster"
    )
    return body if len(body) <= TELEGRAM_LIMIT else body[: TELEGRAM_LIMIT - 2] + " …"


def _reach(repo: Repo, people: list[str], message: str, title: str, body: str, tag: str) -> dict[str, int]:
    from Pukaar.delivery import telegram
    from Pukaar.services import officer_push

    sent = {"telegram": 0, "push": 0, "people": len(people)}
    for who in people:
        chat = repo.get_officer_chat(who)
        if chat and telegram.configured():
            try:
                telegram.send_text(chat, message)
                sent["telegram"] += 1
            except Exception as exc:
                log(_LOG, "duty telegram failed", 30, error=str(exc)[:200])
        sent["push"] += officer_push.send_to_user(repo, who, {
            "kind": "info", "title": title, "body": body, "tag": tag, "data": {"url": "/console/roster"}},
            ttl=6 * 3600, urgency="normal", kind="duty").sent
    return sent


def send_digest(repo: Repo, district: str, now: datetime | None = None, by: str = "pukaar-system") -> dict[str, Any]:
    now = now or clock.now()
    d = digest(repo, district, now)
    people = list(d["duty"]["chain"])
    title = f"पुकार सुबह की जाँच · Morning check: {district}"
    short = (f"{len(d['open_alerts'])} open alerts, {len(d['gauges_unhealthy'])} gauges and "
             f"{len(d['sirens_unhealthy'])} sirens unhealthy, {len(d['gaps'])} gaps")
    sent = _reach(repo, people, text(d), title, short, f"digest-{district}")
    _audit(repo, by, "system" if by.startswith("pukaar") else "officer", "duty_digest_sent", f"district:{district}",
           f"to {', '.join(people) or 'nobody on duty'}: telegram {sent['telegram']}, push {sent['push']}; {short}")
    metric("DutyDigestSent", 1, District=district)
    return {"district": district, "sent": sent, "digest": d}


def maybe_send_digests(repo: Repo, now: datetime | None = None) -> list[str]:
    """Called by every sweep: from the digest hour (IST), each district's digest once that day. Never raises."""
    now = now or clock.now()
    s = get_settings()
    done: list[str] = []
    if not s.duty_digest_enabled:
        return done
    try:
        local = now.astimezone(roster.IST)
        if local.hour < s.duty_digest_hour_ist:
            return done
        for district in roster.districts(repo):
            if repo.claim_once("digest", f"{local.date().isoformat()}#{district}"):
                try:
                    send_digest(repo, district, now)
                    done.append(district)
                except Exception as exc:
                    log(_LOG, "digest failed", 40, district=district, error=str(exc)[:200])
    except Exception as exc:
        log(_LOG, "digest pass failed", 40, error=str(exc)[:200])
    return done


# -- the handover note ------------------------------------------------------------------------------------
def _next(slot: roster.ShiftSlot) -> roster.ShiftSlot:
    return roster.slot_at(slot.ends_at + timedelta(minutes=1))


def write_handover(repo: Repo, actor: str, role: str, district: str, body: str,
                   now: datetime | None = None) -> HandoverNote:
    now = now or clock.now()
    if district not in roster.districts(repo):
        raise DutyError(f"unknown district {district!r}")
    words = re.sub(r"[ \t]+", " ", body or "").strip()
    if not words:
        raise DutyError("write what the next shift must know")
    if len(words) > HANDOVER_MAX:
        raise DutyError(f"keep the note under {HANDOVER_MAX} characters")
    slot = roster.slot_at(now)
    old = repo.get_handover(district, slot.date, slot.shift)
    if old is not None and old.acknowledged_by:
        raise DutyError("the next shift already acknowledged this note; it can no longer be changed")
    nxt = _next(slot)
    note = HandoverNote(district=district, date=slot.date, shift=slot.shift, text=words, written_by=actor,  # type: ignore[arg-type]
                        written_at=clock.iso(now), for_date=nxt.date, for_shift=nxt.shift)  # type: ignore[arg-type]
    repo.put_handover(note)
    _audit(repo, actor, role, "handover_written", f"handover:{district}/{slot.date}/{slot.shift}",
           f"{'edited' if old else 'written'} for the {nxt.label()} ({len(words)} characters)")
    return note


def acknowledge_handover(repo: Repo, actor: str, role: str, district: str, date: str, shift: str,
                         now: datetime | None = None) -> HandoverNote:
    now = now or clock.now()
    note = repo.get_handover(district, date, shift)
    if note is None:
        raise DutyError("no handover note for that shift")
    if note.acknowledged_by:
        raise DutyError(f"already acknowledged by {note.acknowledged_by}")
    if note.written_by == actor:
        raise DutyError("the incoming officer acknowledges the note, not the one who wrote it")
    try:
        note = repo.acknowledge_handover(district, date, shift, actor, clock.iso(now))
    except ConflictError:
        raise DutyError("already acknowledged") from None
    _audit(repo, actor, role, "handover_acknowledged", f"handover:{district}/{date}/{shift}",
           f"note by {note.written_by} acknowledged for the {note.for_date} {note.for_shift} shift")
    return note


def handover_view(repo: Repo, district: str, now: datetime | None = None) -> dict[str, Any]:
    """This shift's note (to the next one), the previous shift's note (to acknowledge), the last week's."""
    now = now or clock.now()
    slot = roster.slot_at(now)
    prev = roster.slot_at(slot.starts_at - timedelta(minutes=1))
    week = repo.list_handovers(district, (roster.today_ist(now) - timedelta(days=7)).isoformat(),
                               roster.today_ist(now).isoformat())
    current = repo.get_handover(district, slot.date, slot.shift)
    incoming = repo.get_handover(district, prev.date, prev.shift)
    return {"district": district, "shift": {"date": slot.date, "shift": slot.shift, "label": slot.label()},
            "next": {"date": _next(slot).date, "shift": _next(slot).shift, "label": _next(slot).label()},
            "previous": {"date": prev.date, "shift": prev.shift, "label": prev.label()},
            "outgoing": current.model_dump() if current else None,
            "incoming": incoming.model_dump() if incoming else None,
            "history": [n.model_dump() for n in sorted(week, key=lambda n: (n.date, n.shift), reverse=True)]}


# -- paging ----------------------------------------------------------------------------------------------
def parse_alarm(message: str | dict[str, Any]) -> dict[str, Any]:
    """The fields of a CloudWatch alarm notification (the SNS message body)."""
    try:
        m = json.loads(message) if isinstance(message, str) else dict(message)
    except (TypeError, ValueError):
        return {"name": "unknown alarm", "state": "ALARM", "reason": str(message)[:300], "districts": []}
    dims = (m.get("Trigger") or {}).get("Dimensions") or []
    districts = [str(d.get("value")) for d in dims if str(d.get("name") or d.get("Name")) == "District"]
    return {"name": str(m.get("AlarmName") or "alarm"), "state": str(m.get("NewStateValue") or "ALARM"),
            "description": str(m.get("AlarmDescription") or "")[:300], "reason": str(m.get("NewStateReason") or "")[:300],
            "at": m.get("StateChangeTime"), "districts": districts}


def page_alarm(repo: Repo, message: str | dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Page the primary and backup on duty (the alarm's district, or every district) on Telegram and Web Push."""
    now = now or clock.now()
    alarm = parse_alarm(message)
    if alarm["state"] not in {"ALARM", "OK"}:
        return {"alarm": alarm["name"], "paged": [], "skipped": alarm["state"]}
    districts = [d for d in alarm["districts"] if d] or roster.districts(repo)
    people: list[str] = []
    for d in districts:
        duty = roster.on_duty(repo, d, now, fallback=_fallback(_villages(repo, d)))
        people += [p for p, r in zip(duty.chain, duty.roles) if not r.startswith("escalation")][:2]
    people = list(dict.fromkeys(people))
    ok = alarm["state"] == "OK"
    word_hi, word_en = ("ठीक हो गया", "back to OK") if ok else ("अलार्म", "ALARM")
    msg = (f"पुकार {word_hi}: {alarm['name']}\n{alarm['description']}\n\n"
           f"Pukaar {word_en}: {alarm['name']}\n{alarm['description']}\n{alarm['reason']}\n"
           f"Runbook: docs/RUNBOOK.md · {get_settings().web_url}/console/system")
    sent = _reach(repo, people, msg[:TELEGRAM_LIMIT], f"पुकार {word_hi} · {word_en}: {alarm['name']}",
                  (alarm["description"] or alarm["reason"])[:160], f"alarm-{alarm['name']}")
    _audit(repo, "pukaar-system", "system", "alarm_paged", f"alarm:{alarm['name']}",
           f"{alarm['state']} to {', '.join(people) or 'nobody on duty'} ({', '.join(districts)}): "
           f"telegram {sent['telegram']}, push {sent['push']}")
    metric("AlarmPaged", 1, State=alarm["state"])
    return {"alarm": alarm["name"], "state": alarm["state"], "paged": people, "sent": sent}
