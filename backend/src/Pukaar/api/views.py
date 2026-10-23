"""JSON shapes returned by the API (docs/CONTRACT.md)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.services import checklist, gauge, rain_obs, readiness, risk_rules, rollcall, soil, staff_gauge, storage
from Pukaar.services.nowcast import nowcast
from Pukaar.store.models import Alert, Directive, Report, Village
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


def river_view(v: Village, latest) -> dict[str, Any] | None:
    """River evidence for the village page: the 2-, 5- and 20-year lines, the early (get-ready) line,
    and the ensemble's exceedance probability per level and lead day (shares only, never the member
    values). mode "deterministic" when there was no ensemble to read (unavailable, off, or a replay)."""
    if v.thresholds is None:
        return None
    info = risk_rules.river_assessment(latest, v.thresholds)
    return {
        "level": info["level"], "mode": info["mode"], "p_min": info["p_min"],
        "ensemble_status": info["ensemble_status"], "p_max": info.get("p_max"), "members": info.get("members"),
        "lead_days": info.get("days", []), "run_date": info.get("run_date"),
        "today": latest.discharge if latest else None, "peak": latest.discharge_peak if latest else None,
        "thresholds": v.thresholds.model_dump(),
        "at": latest.at if latest else None, "replay": bool(latest.replay) if latest else False,
    }


def soil_view(v: Village, latest) -> dict[str, Any]:
    info = soil.evaluate(latest, v.soil, get_settings().soil_modifier_enabled)
    return {**info, "at": latest.at if latest else None, "replay": bool(latest.replay) if latest else False}


def alert(a: Alert) -> dict[str, Any]:
    out = a.model_dump(exclude=_ALERT_HIDDEN)
    out["has_audio"] = bool(a.audio_key)
    return out


# Officer usernames on an alert: who decided, who was asked, who stood it down, who marked the
# outcome. Signed-in views keep them; a public page says what happened, never which officer.
_ALERT_PEOPLE = {"decided_by", "officer_chain", "officers_asked", "all_clear_by", "outcome_by"}


def _decider_role(a: Alert) -> str | None:
    who = a.decided_by or ""
    if not who:
        return None
    return "system" if who.startswith("system") else "officer"


def public_alert(a: Alert) -> dict[str, Any]:
    """An alert on a page that needs no sign-in: no officer usernames (docs/SECURITY.md)."""
    out = a.model_dump(exclude=_ALERT_HIDDEN | _ALERT_PEOPLE)
    out["has_audio"] = bool(a.audio_key)
    out["decided_by_role"] = _decider_role(a)
    return out


def public_directive(d: Directive) -> dict[str, Any]:
    """A directive on a public page: what was ordered and when, not which officer issued it."""
    return d.model_dump(exclude={"issued_by"})


# Fields that hold the username of whoever did something (an officer or a pradhan). A username is half
# of a sign-in, so a page that needs no sign-in never shows one: scrub_people() puts "staff" in its place
# ("system" for the system), and drops the lists of officers asked.
PEOPLE_KEYS = {"decided_by", "all_clear_by", "outcome_by", "issued_by", "done_by", "updated_by", "created_by",
               "renewed_by", "cleared_by", "confirmed_by", "thresholds_set_by", "opened_by_user", "verified_by"}
PEOPLE_LISTS = {"officer_chain", "officers_asked", "officers"}
PUBLIC_ACTOR = "staff"


def scrub_people(value: Any) -> Any:
    """A copy of a public answer with every username replaced (PEOPLE_KEYS) or dropped (PEOPLE_LISTS)."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k in PEOPLE_LISTS:
                continue
            if k in PEOPLE_KEYS and isinstance(v, str) and v:
                out[k] = "system" if v.startswith("system") else PUBLIC_ACTOR
            else:
                out[k] = scrub_people(v)
        return out
    if isinstance(value, list):
        return [scrub_people(v) for v in value]
    return value


# Who an alert reached, with the person left out (a public demo account on a live alert).
_DELIVERY_PEOPLE = {"recipient_id", "name", "call_ids", "error", "digit"}


def masked_delivery(row: dict[str, Any], n: int) -> dict[str, Any]:
    out = {k: v for k, v in row.items() if k not in _DELIVERY_PEOPLE}
    out.update(recipient_id=f"hidden-{n}", name=f"Recipient {n}", call_ids=[], error=None, digit=None, masked=True)
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
    # The salted source hashes stay in the table: officers see the flags they produce, never the hashes.
    out = r.model_dump(exclude={"photo_key", "audio_key", "masked_text", "source"})
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
        "alerts": [public_alert(a) for a in repo.list_alerts(village_id=v.id, limit=20)],
        "reports": [report(r, public=True) for r in reports],
        "past_events": [e.model_dump() for e in repo.list_past_events(v.id)],
        "directives": [public_directive(d) for d in repo.list_directives(v.id)[:5]],
        "nowcast": nowcast(readings[0] if readings else None, v.thresholds, v.level),
        "gauge": gauge.view(repo, v),
        "soil": soil_view(v, readings[0] if readings else None),
        # ensemble P, the return-period lines and the early line (risk_rules.river_assessment)
        "river": river_view(v, readings[0] if readings else None),
        "checklist": checklist.view(repo, v.id),
        # an open safety roll-call: counts only, never names (services/rollcall.py)
        "rollcall": rollcall.public_for_village(repo, v.id),
        # virtual staff gauges: reference photos, scales and recent readings (services/staff_gauge.py)
        "staff_gauges": staff_gauge.village_view(repo, v.id, reports),
        # observed rain from tipping buckets (services/rain_obs.py): windows, bands, quality; None without any
        "rain_obs": rain_obs.safe_view(repo, v),
        # the village's sirens in one line: count, sounding now, the last test. No ids, numbers or keys.
        "sirens": _sirens_line(repo, v.id),
    }


def _sirens_line(repo: Repo, village_id: str) -> dict[str, Any] | None:
    from Pukaar.services.devices import registry

    try:
        return registry.village_sirens(repo, village_id)
    except Exception:
        return None


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


def _reached_a_phone(repo: Repo, a: Alert) -> bool:
    """The alert reached at least one real phone. phones_reached_count says so at once; an alert counted before
    that counter existed (or never repaired) is read from its rows."""
    if a.phones_reached_count > 0:
        return True
    return any(d.channel in {"telegram", "voice"} and d.status in _REAL_PHONE_DELIVERY for d in repo.list_deliveries(a.id))


def _village_counts(repo: Repo, v: Village, since: str, until: str) -> tuple[int, int, int, int]:
    """(reports, forecast checks, gauge readings, of which simulated) for one village: COUNT queries only."""
    gauged = v.gauge is not None
    return (repo.count_live_reports(v.id), repo.count_live_readings(v.id, since, until),
            repo.count_sensor_readings(v.id, since, until) if gauged else 0,
            repo.count_sensor_readings(v.id, since, until, simulated=True) if gauged else 0)


def counters(repo: Repo, now: datetime | None = None) -> dict[str, int]:
    """The public counters. Each one counts real records only (docs/CONTRACT.md):

    alerts_sent / phones_acknowledged  live flood alerts that went out; never replays, never drills
    drills_delivered                   drill alerts that reached at least one real phone (Telegram, or a call answered)
    replay_alerts_approved             replay alerts an officer approved through the approval workflow
    forecast_checks_24h                forecast readings the sweep stored (one per village per sweep), last 24 h
    gauge_readings_24h[_simulated]     river-gauge readings received in the last 24 h (of which simulated)

    The per-village counts are COUNT queries (no item bodies), run PUKAAR_SWEEP_CONCURRENCY at a time on AWS.
    The sweep stores the result (refresh_counters) and /public/overview reads that one item (public_counters).
    """
    now = now or clock.now()
    since, until = clock.iso(now - timedelta(hours=COUNTER_WINDOW_HOURS)), clock.iso(now)
    villages = repo.list_villages()
    alerts = repo.list_alerts(limit=500)
    sent = [a for a in alerts if went_out(a) and not is_replay(a) and not is_drill(a)]
    drills = [a for a in alerts if is_drill(a) and went_out(a)]
    s = get_settings()
    if s.is_local or len(villages) < 2:  # moto's in-process table is not safe for threads; DynamoDB is
        per = [_village_counts(repo, v, since, until) for v in villages]
    else:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(s.sweep_concurrency, len(villages))) as pool:
            per = list(pool.map(lambda v: _village_counts(repo, v, since, until), villages))
    return {
        "villages_watched": len(villages),
        "alerts_sent": len(sent),
        "phones_acknowledged": sum(a.acknowledged_count for a in sent),
        "reports_received": sum(p[0] for p in per),
        "drills_delivered": sum(1 for a in drills if _reached_a_phone(repo, a)),
        "replay_alerts_approved": sum(1 for a in alerts if is_replay(a) and a.approved),
        "forecast_checks_24h": sum(p[1] for p in per),
        "gauge_readings_24h": sum(p[2] for p in per),
        "gauge_readings_24h_simulated": sum(p[3] for p in per),
    }


COUNTERS_SUMMARY = "counters"


def refresh_counters(repo: Repo, now: datetime | None = None) -> dict[str, int] | None:
    """Compute the counters and store them (repo SUMMARY counters). The sweep calls it once a run. Never raises."""
    now = now or clock.now()
    try:
        body = counters(repo, now)
        repo.put_summary(COUNTERS_SUMMARY, body, clock.iso(now))
        return body
    except Exception as exc:
        from Pukaar.core.log import get_logger, log

        log(get_logger("views"), "counters not refreshed", 30, error=str(exc)[:200])
        return None


def public_counters(repo: Repo, now: datetime | None = None) -> tuple[dict[str, int], str]:
    """(counters, when they were counted) for a public page: the stored summary while it is younger than
    PUKAAR_COUNTERS_MAX_AGE_SECONDS (the sweep writes it every 15 minutes), so a page read costs one GetItem
    whatever the number of villages; otherwise computed now and stored."""
    now = now or clock.now()
    max_age = get_settings().counters_max_age_seconds
    if max_age > 0:
        stored = repo.get_summary(COUNTERS_SUMMARY)
        if stored is not None and 0 <= (now - clock.parse(stored[0])).total_seconds() <= max_age:
            return stored[1], stored[0]
    body = counters(repo, now)
    if max_age > 0:
        try:
            repo.put_summary(COUNTERS_SUMMARY, body, clock.iso(now))
        except Exception:
            pass
    return body, clock.iso(now)
