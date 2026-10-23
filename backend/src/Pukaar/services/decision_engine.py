"""The sweep: reading -> risk rules -> hysteresis -> alert -> approval workflow.

recompute_village() is called by the 15-minute sweep, by each new report and
by the replay. Code decides the level; the model is never consulted here.

Also here: missing forecast data is unknown, never 0 (carried forward for a few
sweeps, then "data unavailable", and never counted as a calm sweep); and a live
alert that went unsent (declined or expired) is asked again while the level holds.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Protocol

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.core.log import get_logger, log, metric
from Pukaar.services import events, rain_obs, readiness, risk_rules
from Pukaar.services import gauge as gauge_mod
from Pukaar.services.nowcast import nowcast
from Pukaar.store.models import OPEN_ALERT_STATUSES, VERIFIED_STATES, Alert, Reading, Village, level_rank
from Pukaar.store.repo import Repo

_LOG = get_logger("sweep")
SWEEP_MINUTES = 15


class WorkflowStarter(Protocol):
    def start(self, alert: Alert) -> str | None: ...


@dataclass
class SweepResult:
    village_id: str
    skipped: bool = False
    level: str = "normal"
    raw_level: str = "normal"
    rose: bool = False
    alert_id: str | None = None
    note: str = ""


def sweep_window(at: datetime, prefix: str = "live") -> str:
    slot = at.replace(minute=(at.minute // SWEEP_MINUTES) * SWEEP_MINUTES, second=0, microsecond=0)
    return f"{prefix}:{clock.iso(slot)}"


def _recent_reports(repo: Repo, village_id: str, now: datetime, include_replay: bool):
    out = []
    for r in repo.list_reports(village_id, limit=50):
        created = clock.parse(r.created_at)
        if created > now or now - created > timedelta(hours=risk_rules.REPORT_ZERO_WEIGHT_HOURS):
            continue
        if r.state in {"duplicate", "false"}:
            continue
        if r.held and r.state not in VERIFIED_STATES:
            continue  # held by the guardrail: counts only once an officer verifies it
        if r.replay and not include_replay:
            continue
        out.append((r, created))
    return out


def build_trace(village: Village, reading: Reading | None, assessment: risk_rules.Assessment,
                previous: str, new_level: str, calm: int, now: datetime) -> dict:
    # Soft trigger only: shown beside the level and kept as outlook evidence, never used to set it.
    outlook = readiness.outlook(reading, village.thresholds)
    return {
        "schema": risk_rules.RULES_VERSION,
        "generated_at": clock.iso(now),
        "village_id": village.id,
        "previous_level": previous,
        "raw_level": assessment.level,
        "level": new_level,
        "rain_level": assessment.rain_level,
        "river_level": assessment.river_level,
        "report_level": assessment.report_level,
        "gauge_level": assessment.gauge_level,
        "staff_level": assessment.staff_level,
        "rain_obs_level": assessment.rain_obs_level,
        "rules_fired": assessment.rules_fired,
        "contradictions": assessment.contradictions,
        "data_disagrees": bool(assessment.contradictions),
        "hysteresis": {"calm_sweeps": calm, "needed_to_drop": risk_rules.HYSTERESIS_SWEEPS},
        "evidence": [*assessment.evidence, readiness.trace_item(outlook)],
        "forecast_snapshot": {
            "rain_24h_mm": reading.rain_24h_mm if reading else None,
            "discharge_forecast": reading.discharge_forecast if reading else [],
        },
        "nowcast": nowcast(reading, village.thresholds, new_level),
        "readiness": outlook,
        "replay": bool(reading.replay) if reading else False,
    }


def _escalate(repo: Repo, alert: Alert, village: Village, new_level: str, trace: dict) -> None:
    """Raise an alert that is still awaiting approval instead of stacking a second one.

    The text becomes the fixed template for the new level (no model call in the
    sweep), and the officer sees the change in the timeline.
    """
    from Pukaar.store.models import DraftCheck
    from Pukaar.templates import hi
    from Pukaar.voice import polly

    from Pukaar.services import safe_places

    safe = safe_places.nearest_usable(repo, village.id)
    if safe:
        trace = {**trace, "safe_place": safe}
    from Pukaar.services.cap import district_hi

    text_hi, text_en = hi.fallback_alert(new_level, village.name_hi, village.name, safe,
                                         district_hi=district_hi(village), district_en=village.district, trace=trace)
    # token_version moves on: a link for the old level can no longer approve the new text.
    repo.update_alert(alert.id, level=new_level, decision_trace=trace, text_hi=text_hi, text_en=text_en,
                      token_version=alert.token_version + 1,
                      reasoning_model="rule-fallback", audio_key=None,
                      reason_en=f"Escalated from {alert.level} before approval. Rules: {', '.join(trace['rules_fired'][:4])}.",
                      draft_check=DraftCheck(passed=False, reason="escalated before approval; fixed template for the new level"))
    audio_key = polly.synthesize_alert(alert.id, text_hi)
    if audio_key:
        repo.update_alert(alert.id, audio_key=audio_key)
    repo.add_timeline(alert.id, "escalated", f"{alert.level} -> {new_level} while awaiting approval")
    events.alert_changed(repo.get_alert(alert.id), kind="escalated")


# -- data freshness -----------------------------------------------------------
# Fields a provider can leave out, and the reading fields carried forward for each.
_CARRY = {
    "rain": ("rain_24h_mm", "rain_hourly", "rain_models", "rain_level"),
    "discharge": ("discharge", "discharge_forecast", "discharge_peak", "discharge_outlook", "river_level"),
}


def _last_complete(repo: Repo, village_id: str, limit: int) -> Reading | None:
    for r in repo.list_readings(village_id, limit=limit):
        if not r.replay and not r.missing and r.carried_from is None:
            return r
    return None


def _carry_forward(reading: Reading, last: Reading) -> Reading:
    update: dict = {"carried_from": last.at}
    for part in reading.missing:
        for name in _CARRY.get(part, ()):
            update[name] = getattr(last, name)
    return reading.model_copy(update=update)


def _stale_minutes(village: Village, now: datetime, missing_sweeps: int) -> float:
    if village.data_ok_at:
        return (now - clock.parse(village.data_ok_at)).total_seconds() / 60
    return missing_sweeps * SWEEP_MINUTES


def _data_quality(repo: Repo, village: Village, reading: Reading | None, now: datetime) -> tuple[Reading | None, dict]:
    """Missing values are unknown, never 0: carry the last complete values forward for at most
    stale_max_sweeps sweeps (status "stale"), then mark the village "data unavailable"."""
    s = get_settings()
    missing = ["rain", "discharge"] if reading is None else list(reading.missing)
    if not missing:
        return reading, {"status": "ok", "ok_at": clock.iso(now), "missing_sweeps": 0, "missing": [], "note": ""}
    sweeps = village.data_missing_sweeps + 1
    last = _last_complete(repo, village.id, s.stale_max_sweeps + 2) if sweeps <= s.stale_max_sweeps else None
    if reading is not None and last is not None:
        effective = _carry_forward(reading, last)
        status, note = "stale", f"{', '.join(missing)} missing from the forecast; using the values from {last.at}"
    else:
        effective = reading
        status = "unavailable"
        note = f"{', '.join(missing)} missing for {sweeps} sweeps; level held, not lowered"
    return effective, {"status": status, "ok_at": village.data_ok_at, "missing_sweeps": sweeps, "missing": missing,
                       "carried_from": last.at if status == "stale" and last else None, "note": note,
                       "stale_minutes": round(_stale_minutes(village, now, sweeps), 1)}


def _emit_stale(village: Village, quality: dict, now: datetime) -> None:
    minutes = quality.get("stale_minutes") or 0
    if quality["status"] != "ok" and minutes >= get_settings().stale_alarm_minutes:
        metric("VillageDataStale", 1, Village=village.id)
        log(_LOG, "village data stale", 30, village_id=village.id, minutes=minutes, status=quality["status"])


def note_fetch_failure(repo: Repo, village: Village, now: datetime, error: str) -> Village:
    """The forecast fetch failed: the level is held (nothing recomputed) and the village says so."""
    sweeps = village.data_missing_sweeps + 1
    status = "stale" if sweeps <= get_settings().stale_max_sweeps and village.data_ok_at else "unavailable"
    quality = {"status": status, "stale_minutes": round(_stale_minutes(village, now, sweeps), 1)}
    _emit_stale(village, quality, now)
    return repo.update_village(village.id, data_status=status, data_missing_sweeps=sweeps,
                               data_note=f"forecast fetch failed ({error[:80]}); level held, not lowered")


# -- re-ask -------------------------------------------------------------------
def _went_unsent(a: Alert) -> bool:
    """Declined, expired, or ended by the failsafe without being broadcast."""
    if a.status in {"declined", "expired"}:
        return True
    return a.status in {"failsafe", "closed"} and not a.approved and a.level != "critical"


def reask_due(repo: Repo, village: Village, level: str, now: datetime) -> dict | None:
    """A live alert that nobody sent (declined or expired) is asked again when the village is still
    at or above its level after the cooldown for the level now (Settings.reask_cooldown): a Critical
    0 to 5 minutes, so the next sweep asks again; a Warning 30, a Watch 60. Returns what the new
    alert's trace records."""
    if village.open_alert_id:
        current = repo.get_alert(village.open_alert_id)
        if current is not None and current.status in OPEN_ALERT_STATUSES:
            return None
    last = repo.get_alert(village.last_alert_id) if village.last_alert_id else None
    if last is None:  # villages from before last_alert_id: the newest live alert in the log
        last = next((a for a in repo.list_alerts(village_id=village.id, limit=10) if not a.replay), None)
    if last is None or last.replay or last.decision_trace.get("drill") or not _went_unsent(last):
        return None
    if level_rank(level) < level_rank(last.level):
        return None
    cooldown = get_settings().reask_cooldown(level)
    ended = clock.parse(last.decided_at or last.updated_at)
    if now - ended < timedelta(minutes=cooldown):
        return None
    return {"previous_alert_id": last.id, "previous_status": last.status, "previous_level": last.level,
            "previous_ended_at": clock.iso(ended), "previous_decided_by": last.decided_by,
            "cooldown_minutes": cooldown}


# -- one village ----------------------------------------------------------------
def recompute_village(
    repo: Repo,
    village: Village,
    *,
    now: datetime | None = None,
    reading: Reading | None = None,
    fetch: Callable[[Village, datetime], Reading | None] | None = None,
    workflow: WorkflowStarter | None = None,
    window_prefix: str | None = None,
    replay: bool = False,
    only_if_rising: bool = False,
) -> SweepResult:
    """One evaluation for one village.

    window_prefix set: a scheduled sweep, deduplicated per 15-minute window.
    fetch set: a new reading is fetched and stored; otherwise the latest stored
    reading is reused (a new report triggered this).
    replay: works on the replay's own copy of the village (repo REPLAY / VILLAGE#id); the live
    record is never read for its level nor written. Without a running replay nothing happens.
    only_if_rising: change nothing unless the raw level is above the current one (a gauge
    reading arrives every minute; it must not count as a calm sweep for hysteresis).
    """
    now = now or clock.now()
    if replay:
        copy = repo.get_replay_village(village.id)
        if copy is None:
            return SweepResult(village.id, skipped=True, level=village.level, note="no replay copy; nothing changed")
        village = copy
    update = repo.update_replay_village if replay else repo.update_village
    if window_prefix is not None and not repo.claim_sweep(village.id, sweep_window(now, window_prefix)):
        return SweepResult(village.id, skipped=True, level=village.level, note="window already swept")

    fetched = False
    if reading is None and fetch is not None:
        reading = fetch(village, now)
        fetched = True
        if reading is not None:
            repo.put_reading(reading)
    if reading is None and not fetched:
        latest = repo.list_readings(village.id, limit=1)
        reading = latest[0] if latest and (latest[0].replay == replay) else None

    quality: dict | None = None
    if not replay:
        if fetched:
            reading, quality = _data_quality(repo, village, reading, now)
        elif reading is not None and reading.missing and village.data_status == "stale":
            last = _last_complete(repo, village.id, get_settings().stale_max_sweeps + 2)
            reading = _carry_forward(reading, last) if last else reading
    data_ok = (quality["status"] if quality else village.data_status) == "ok" or replay

    reports = _recent_reports(repo, village.id, now, include_replay=replay)
    # Gauge readings are live data: never mixed into a replay.
    sensor = None if replay or village.gauge is None else repo.latest_sensor_reading(
        village.id, risk_rules.GAUGE_FRESH_MINUTES, now=now)
    # Observed rain (tipping buckets) is live data too: never mixed into a replay.
    rain_info = None
    if not replay and get_settings().rain_obs_enabled:
        try:
            rain_info = rain_obs.village_info(repo, village, now, forecast=reading)
        except Exception as exc:  # missing observed rain is nothing, never a calm reading
            log(_LOG, "observed rain unavailable", 30, village_id=village.id, error=str(exc)[:200])
    # A gauge silent while it rains is a signal (risk_rules.silent_gauge_in_rain). Live only, like the readings.
    silence = None if replay else gauge_mod.silence(repo, village, now)
    assessment = risk_rules.assess(reading, village.thresholds, reports, now, sensor=sensor, gauge=village.gauge,
                                   soil=village.soil, allow_simulated=replay, rain_obs=rain_info,
                                   gauge_silence=silence)
    if any(r.startswith("gauge_silent_in_rain:") for r in assessment.rules_fired):
        # The officer is told by the Watch alert this raises; the metric pages the on-call (GaugeSilentInRain).
        metric("GaugeSilentInRain", 1, Village=village.id)
        log(_LOG, "gauge silent while it rains", 30, village_id=village.id,
            device_id=(silence or {}).get("device_id"), minutes=(silence or {}).get("minutes_silent"))
    previous = village.level
    if only_if_rising and level_rank(assessment.level) <= level_rank(previous):
        return SweepResult(village.id, skipped=True, level=previous, raw_level=assessment.level, note="not rising")
    if not data_ok and level_rank(assessment.level) < level_rank(previous):
        # Missing data is not a calm sweep: hold the level and the calm count.
        new_level, calm, rose = previous, village.calm_sweeps, False
    else:
        new_level, calm, rose = risk_rules.apply_hysteresis(previous, village.calm_sweeps, assessment.level)
    trace = build_trace(village, reading, assessment, previous, new_level, calm, now)
    if quality is not None:
        trace["data"] = quality
        _emit_stale(village, quality, now)

    fields: dict = {"level": new_level, "calm_sweeps": calm}
    if new_level != previous:
        fields["level_since"] = clock.iso(now)
    if quality is not None:
        fields.update(data_status=quality["status"], data_missing_sweeps=quality["missing_sweeps"],
                      data_note=quality["note"])
        if quality["status"] == "ok":
            fields["data_ok_at"] = quality["ok_at"]
    village = update(village.id, **fields)
    events.level_changed(village.id, new_level, previous, replay=replay)
    result = SweepResult(village.id, level=new_level, raw_level=assessment.level, rose=rose)
    log(_LOG, "village evaluated", village_id=village.id, previous=previous, raw=assessment.level,
        level=new_level, rose=rose, rules=assessment.rules_fired, replay=replay,
        data=quality["status"] if quality else village.data_status)

    if new_level == "normal":
        if previous != "normal":
            _stand_down(repo, village, replay)
        return result
    reask = None
    if not rose:
        # The level held. Ask again only if the last live alert went unsent and the cooldown passed.
        reask = None if replay or only_if_rising else reask_due(repo, village, new_level, now)
        if reask is None:
            return result
        trace["reask"] = reask

    # Quiet rules: no new alert while an open one already covers this level; daily cap.
    if village.open_alert_id:
        open_alert = repo.get_alert(village.open_alert_id)
        if open_alert and open_alert.status in OPEN_ALERT_STATUSES:
            if level_rank(open_alert.level) >= level_rank(new_level):
                result.note = "open alert already covers this level"
                return result
            if open_alert.status in {"drafting", "pending"}:
                _escalate(repo, open_alert, village, new_level, trace)
                result.alert_id, result.note = open_alert.id, "escalated the alert awaiting approval"
                return result
    cap = get_settings().alerts_per_village_per_day
    if repo.alerts_on_day(village.id, clock.iso(now)[:10]) >= cap:
        result.note = f"daily cap of {cap} alerts reached"
        log(_LOG, "alert suppressed by daily cap", 30, village_id=village.id)
        return result

    stamp = clock.iso(clock.now())
    alert = Alert(
        id=new_id("alr"), village_id=village.id, village_name=village.name, village_name_hi=village.name_hi,
        level=new_level, previous_level=previous, status="drafting", created_at=stamp, updated_at=stamp,
        decision_trace=trace, replay=replay,
    )
    repo.put_alert(alert)
    update(village.id, open_alert_id=alert.id, last_alert_id=alert.id)
    if reask is not None:
        repo.add_timeline(alert.id, "created",
                          f"asked again: {reask['previous_status']} alert {reask['previous_alert_id']} "
                          f"({reask['previous_level']}) at {reask['previous_ended_at']}; level still {new_level} "
                          f"after {reask['cooldown_minutes']} min")
        result.note = "asked again after an unsent alert"
    else:
        repo.add_timeline(alert.id, "created",
                          f"level {previous} -> {new_level}; rules: {', '.join(assessment.rules_fired)}")
    events.alert_changed(alert)
    result.alert_id = alert.id
    if workflow is not None:
        start_workflow(repo, workflow, alert)
    return result


def _stand_down(repo: Repo, village: Village, replay: bool) -> None:
    """Back to normal: the all-clear to everyone contacted for the village's recent alerts
    (workflow/steps.stand_down; a replay's all-clear is a stub record only). Never raises."""
    try:
        from Pukaar.workflow.steps import stand_down_village

        stand_down_village(repo, village.id, replay=replay, by="system",
                           reason="the village is back to normal")
    except Exception as exc:
        log(_LOG, "all-clear failed", 40, village_id=village.id, error=str(exc)[:300])


def start_workflow(repo: Repo, workflow: WorkflowStarter, alert: Alert) -> bool:
    """Start the approval execution; on failure the next sweep retries (restart_stuck)."""
    try:
        arn = workflow.start(alert)
    except Exception as exc:
        if "ExecutionAlreadyExists" in type(exc).__name__ or "ExecutionAlreadyExists" in str(exc):
            return True
        log(_LOG, "workflow start failed; will retry next sweep", 40, alert_id=alert.id, error=str(exc)[:300])
        repo.add_timeline(alert.id, "start_failed", f"{type(exc).__name__}; retried by the next sweep")
        return False
    if arn:
        repo.update_alert(alert.id, execution_arn=arn)
    return True


def restart_stuck(repo: Repo, workflow: WorkflowStarter, now: datetime, min_age_seconds: int = 120) -> list[str]:
    """Alerts still drafting with no execution (start failed) get another start."""
    restarted = []
    for alert in repo.open_alerts():
        if alert.status != "drafting" or alert.execution_arn:
            continue
        if (now - clock.parse(alert.created_at)).total_seconds() < min_age_seconds:
            continue
        if start_workflow(repo, workflow, alert):
            restarted.append(alert.id)
    return restarted


def sweep_all(repo: Repo, *, now: datetime | None = None, fetch=None, workflow: WorkflowStarter | None = None) -> list[SweepResult]:
    """The live sweep. It runs in full whether or not a replay is running: a replay works on its
    own copies of the villages and never pauses live levels or live alerts."""
    from Pukaar.services.external_data import fetch_live

    now = now or clock.now()
    results = []
    from Pukaar.services.replay import clear_if_finished

    clear_if_finished(repo, now)  # removes a finished replay's own items only
    if workflow is not None:
        restart_stuck(repo, workflow, now)
    fetcher = fetch or (lambda v, t: fetch_live(v, t))

    def one(village: Village) -> SweepResult:
        try:
            return recompute_village(repo, village, now=now, fetch=fetcher, workflow=workflow, window_prefix="live")
        except Exception as exc:  # one bad village never stops the sweep
            log(_LOG, "village sweep failed", 40, village_id=village.id, error=str(exc)[:300])
            try:  # the level is held, never lowered, and the village says its data is stale or unavailable
                note_fetch_failure(repo, repo.get_village(village.id) or village, now, f"{type(exc).__name__}: {exc}")
            except Exception as inner:
                log(_LOG, "data status update failed", 40, village_id=village.id, error=str(inner)[:200])
            return SweepResult(village.id, skipped=True, level=village.level, note=f"error: {type(exc).__name__}")

    # Villages are independent (each reads and writes only its own items, and claims its own sweep
    # window), so they are evaluated at once on a bounded pool: the time is set by the slowest
    # forecast fetch, not the sum of them. The table client is made before the pool starts.
    villages = repo.list_villages()
    workers = max(1, min(get_settings().sweep_concurrency, len(villages)))
    if workers == 1:
        return results + [one(v) for v in villages]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sweep") as pool:
        results.extend(pool.map(one, villages))  # in village order
    return results
