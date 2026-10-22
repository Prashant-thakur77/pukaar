"""JSON shapes returned by the API (docs/CONTRACT.md)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.services import checklist, gauge, readiness, rollcall, soil, staff_gauge, storage
from Pukaar.services.nowcast import nowcast
from Pukaar.store.models import Alert, Report, Village
from Pukaar.store.repo import Repo

_ALERT_HIDDEN = {"task_token", "token_version", "execution_arn", "audio_key"}


def village(repo: Repo, v: Village, shown: dict[str, Any] | None = None) -> dict[str, Any]:
    """Public village view. No officer usernames. While a replay runs, `shown` (replay.display)
    puts the replay's level on a village whose live level is normal; live_level is always there."""
    latest = repo.list_readings(v.id, limit=1)
    out = v.model_dump(exclude={"officers", "last_alert_id"})
    if shown is None:
        from Pukaar.services import replay

        shown = replay.display(repo, [v])[v.id]
    out.update(shown)
    out["latest_reading"] = latest[0].model_dump() if latest else None
    # The soft "get ready" outlook: never changes the level (services/readiness.py).
    out["readiness"] = readiness.outlook(latest[0] if latest else None, v.thresholds)
    return out


def soil_view(v: Village, latest) -> dict[str, Any]:
    info = soil.evaluate(latest, v.soil, get_settings().soil_modifier_enabled)
    return {**info, "at": latest.at if latest else None, "replay": bool(latest.replay) if latest else False}


def alert(a: Alert) -> dict[str, Any]:
    out = a.model_dump(exclude=_ALERT_HIDDEN)
    out["has_audio"] = bool(a.audio_key)
    return out


# What a public (signed-out) page may show about a villager's report: the coarse facts only.
# Never the words, the exact GPS, the voice or photo, a name or a tracking code; officers read
# those on /reports, under Cedar.
PUBLIC_REPORT_FIELDS = ("id", "village_id", "created_at", "report_type", "severity", "state", "replay")


def public_report(r: Report) -> dict[str, Any]:
    out: dict[str, Any] = {k: getattr(r, k) for k in PUBLIC_REPORT_FIELDS}
    out["held"] = r.held
    out["has_location"] = r.lat is not None and r.lon is not None
    out["has_photo"], out["has_audio"] = bool(r.photo_key), bool(r.audio_key)
    return out


def report(r: Report, *, public: bool = False) -> dict[str, Any]:
    if public:
        return public_report(r)
    out = r.model_dump(exclude={"photo_key", "audio_key", "masked_text"})
    out["photo_url"] = storage.url_for(r.photo_key)
    out["audio_url"] = storage.url_for(r.audio_key)
    out["held"] = r.held
    if r.masked_text and r.screen is not None:
        # Show the guardrail's copy: phone numbers and e-mails masked. The original stays in the table.
        out[r.screen.field] = r.masked_text
    return out


def village_detail(repo: Repo, v: Village) -> dict[str, Any]:
    readings = repo.list_readings(v.id, limit=96)
    reports = repo.list_reports(v.id, limit=30)
    return {
        "village": village(repo, v),
        "readings": [r.model_dump() for r in readings],
        "alerts": [alert(a) for a in repo.list_alerts(village_id=v.id, limit=20)],
        "reports": [report(r, public=True) for r in reports],
        "past_events": [e.model_dump() for e in repo.list_past_events(v.id)],
        "directives": [d.model_dump() for d in repo.list_directives(v.id)[:5]],
        "nowcast": nowcast(readings[0] if readings else None, v.thresholds, v.level),
        "gauge": gauge.view(repo, v),
        "soil": soil_view(v, readings[0] if readings else None),
        "checklist": checklist.view(repo, v.id),
        # an open safety roll-call: counts only, never names (services/rollcall.py)
        "rollcall": rollcall.public_for_village(repo, v.id),
        # virtual staff gauges: reference photos, scales and recent readings (services/staff_gauge.py)
        "staff_gauges": staff_gauge.village_view(repo, v.id, reports),
    }


# Alert statuses that mean the alert reached people. "failsafe" and "closed" only count when the
# alert was actually broadcast: the failsafe sends only critical or already-approved alerts.
_WENT_OUT = {"delivered", "auto_sent_unapproved"}
_REAL_PHONE_DELIVERY = {"sent", "acknowledged"}
COUNTER_WINDOW_HOURS = 24


def went_out(a: Alert) -> bool:
    if a.status in _WENT_OUT:
        return True
    if a.status == "failsafe":
        return a.level == "critical" or a.approved
    if a.status == "closed":
        return a.approved
    return False


def is_replay(a: Alert) -> bool:
    return bool(a.replay or a.decision_trace.get("replay"))


def is_drill(a: Alert) -> bool:
    """A hand-started test alert (scripts/drill.py): real phones, but never a flood warning."""
    return bool(a.decision_trace.get("drill")) and not is_replay(a)


def counters(repo: Repo, now: datetime | None = None) -> dict[str, int]:
    """The public counters. Each one counts real records only (docs/CONTRACT.md):

    alerts_sent / phones_acknowledged  live flood alerts that went out; never replays, never drills
    drills_delivered                   drill alerts that reached at least one real phone (Telegram)
    replay_alerts_approved             replay alerts an officer approved through the approval workflow
    forecast_checks_24h                forecast readings the sweep stored (one per village per sweep), last 24 h
    gauge_readings_24h[_simulated]     river-gauge readings received in the last 24 h (of which simulated)
    """
    now = now or clock.now()
    since, until = clock.iso(now - timedelta(hours=COUNTER_WINDOW_HOURS)), clock.iso(now)
    villages = repo.list_villages()
    alerts = repo.list_alerts(limit=500)
    sent = [a for a in alerts if went_out(a) and not is_replay(a) and not is_drill(a)]
    drills = [a for a in alerts if is_drill(a) and went_out(a)]
    gauged = [v for v in villages if v.gauge is not None]
    return {
        "villages_watched": len(villages),
        "alerts_sent": len(sent),
        "phones_acknowledged": sum(a.acknowledged_count for a in sent),
        "reports_received": sum(1 for v in villages for r in repo.list_reports(v.id, limit=500) if not r.replay),
        "drills_delivered": sum(1 for a in drills if any(d.channel == "telegram" and d.status in _REAL_PHONE_DELIVERY
                                                         for d in repo.list_deliveries(a.id))),
        "replay_alerts_approved": sum(1 for a in alerts if is_replay(a) and a.approved),
        "forecast_checks_24h": sum(repo.count_live_readings(v.id, since, until) for v in villages),
        "gauge_readings_24h": sum(repo.count_sensor_readings(v.id, since, until) for v in gauged),
        "gauge_readings_24h_simulated": sum(repo.count_sensor_readings(v.id, since, until, simulated=True)
                                            for v in gauged),
    }
