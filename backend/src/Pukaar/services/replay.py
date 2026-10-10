"""Replay archived hours through the same sweep code with a simulated clock.

Everything replay writes carries replay=True. While a replay is active the live
sweep still stores readings but does not change village levels; reset() puts
every village back to normal and removes replay-labelled items (audit rows
stay: they are append-only).
"""

from __future__ import annotations

import time
from datetime import datetime

from Pukaar.core import clock
from Pukaar.core.log import get_logger, log
from Pukaar.services import external_data, risk_rules
from Pukaar.services.decision_engine import recompute_village
from Pukaar.store.models import ReplayState, level_rank
from Pukaar.store.repo import Repo

_LOG = get_logger("replay")
DEFAULT_SCENARIO = "himachal_2023_07"
WORKER_BUDGET_SECONDS = 780  # the worker Lambda times out at 900 s
STALE_AFTER_SECONDS = 300
CLEAR_AFTER_SECONDS = 1800  # a finished replay stays on screen this long (long enough to record a demo)


def max_speed(hours_total: int) -> float:
    """Seconds per simulated hour that still fit the whole replay in one worker run."""
    return WORKER_BUDGET_SECONDS / max(1, hours_total) * 0.8


def is_running(repo: Repo) -> bool:
    """Active and still making progress; a replay whose worker died stops owning the levels."""
    st = repo.get_replay()
    if not st.active:
        return False
    beat = st.updated_at or st.started_at
    return beat is None or (clock.now() - clock.parse(beat)).total_seconds() < STALE_AFTER_SECONDS


def status(repo: Repo) -> dict:
    st = repo.get_replay()
    scenarios = external_data.list_scenarios()
    meta = {}
    if st.scenario and st.scenario in scenarios:
        sc = external_data.load_scenario(st.scenario)
        meta = {"title": sc.get("title"), "title_hi": sc.get("title_hi"), "sources": sc.get("sources")}
    return {**st.model_dump(), "stale": st.active and not is_running(repo), "available": scenarios, **meta}


def reset(repo: Repo) -> ReplayState:
    repo.put_replay(ReplayState(active=False))
    removed = repo.delete_where(lambda item: bool(item.get("replay")) and item.get("kind") != "village")
    for v in repo.list_villages():
        repo.update_village(v.id, level="normal", calm_sweeps=0, level_since=None, open_alert_id=None, replay=False)
    log(_LOG, "replay reset", removed=removed)
    return repo.get_replay()


def clear_if_finished(repo: Repo, now: datetime | None = None) -> bool:
    """Reset a replay that finished (or whose worker died) more than 30 minutes ago.

    Called by the live sweep: otherwise hysteresis walks down from the replay's
    last level for hours and the "replay finished" banner never goes away.
    """
    st = repo.get_replay()
    if not st.scenario or is_running(repo):
        return False
    beat = st.updated_at or st.started_at
    now = now or clock.now()
    if beat is not None and (now - clock.parse(beat)).total_seconds() < CLEAR_AFTER_SECONDS:
        return False
    log(_LOG, "clearing finished replay before the live sweep", scenario=st.scenario, updated_at=beat)
    reset(repo)
    return True


def start(repo: Repo, scenario: str = DEFAULT_SCENARIO) -> ReplayState:
    from Pukaar.core.config import get_settings

    if not get_settings().replay_enabled:
        raise PermissionError("replay is disabled on this stack (ReplayEnabled=false)")
    if scenario not in external_data.list_scenarios():
        raise ValueError(f"unknown scenario {scenario}; run python -m Pukaar.scripts.fetch_replay")
    reset(repo)
    hours = external_data.replay_hours(scenario)
    for v in repo.list_villages():
        repo.update_village(v.id, replay=True)
    now = clock.iso(clock.now())
    st = ReplayState(active=True, scenario=scenario, clock=clock.iso(hours[0]), hours_total=len(hours), hours_done=0,
                     started_at=now, updated_at=now, source=external_data.load_scenario(scenario).get("title"))
    repo.put_replay(st)
    return st


def run(repo: Repo, *, speed_seconds_per_hour: float = 2.0, workflow=None) -> ReplayState:
    """Walk every hour of the active scenario. Stops early if reset() was called."""
    st = repo.get_replay()
    if not st.active or not st.scenario:
        return st
    for i, at in enumerate(external_data.replay_hours(st.scenario)):
        if i < st.hours_done:
            continue
        current = repo.get_replay()
        if not current.active or current.scenario != st.scenario:
            log(_LOG, "replay stopped")
            return current
        for village in repo.list_villages():
            reading = external_data.replay_reading(st.scenario, village, at)
            if reading is not None:
                repo.put_reading(reading)
            recompute_village(repo, village, now=at, reading=reading, workflow=workflow,
                              window_prefix=f"replay-{st.scenario}-{current.started_at}", replay=True)
        current.clock, current.hours_done, current.updated_at = clock.iso(at), i + 1, clock.iso(clock.now())
        repo.put_replay(current)
        time.sleep(speed_seconds_per_hour)
    final = repo.get_replay()
    final.active = False
    repo.put_replay(final)
    for v in repo.list_villages():
        repo.update_village(v.id, replay=False)
    log(_LOG, "replay finished", scenario=st.scenario)
    return final


def backtest(scenario: str, villages) -> list[dict]:
    """Pure rules over the archived data, no store: first time each level is
    reached, time of peak forecast discharge, and the lead time between them."""
    rows = []
    hours = external_data.replay_hours(scenario)
    sc = external_data.load_scenario(scenario)
    for v in villages:
        first: dict[str, str | None] = {"watch": None, "warning": None, "critical": None}
        level, calm = "normal", 0
        max_rain = 0.0
        for at in hours:
            reading = external_data.replay_reading(scenario, v, at)
            if reading is None:
                continue
            max_rain = max(max_rain, reading.rain_24h_mm or 0.0)
            a = risk_rules.assess(reading, v.thresholds, [], at)
            level, calm, _ = risk_rules.apply_hysteresis(level, calm, a.level)
            for lvl in first:
                if first[lvl] is None and level_rank(level) >= level_rank(lvl):
                    first[lvl] = clock.iso(at)
        series = sc["villages"].get(v.id, {}).get("daily", {})
        window = [(d, q) for d, q in zip(series.get("time", []), series.get("river_discharge", []))
                  if q is not None and hours[0].date().isoformat() <= d <= hours[-1].date().isoformat()]
        peak_day, peak_q = max(window, key=lambda x: x[1]) if window else (None, None)
        lead = None
        if first["watch"] and peak_day:
            peak_at = datetime.fromisoformat(peak_day).replace(tzinfo=clock.parse(first["watch"]).tzinfo)
            lead = round((peak_at - clock.parse(first["watch"])).total_seconds() / 3600, 1)
        rows.append({
            "village_id": v.id, "village": v.name, "first_watch": first["watch"], "first_warning": first["warning"],
            "first_critical": first["critical"], "peak_discharge_day": peak_day, "peak_discharge": peak_q,
            "thresholds": v.thresholds.model_dump() if v.thresholds else None, "max_rain_24h_mm": round(max_rain, 1),
            "lead_hours_watch_to_peak_day": lead,
            "outcome": "never crossed" if first["watch"] is None
            else "reached " + max((k for k, t in first.items() if t), key=level_rank),
        })
    return rows
