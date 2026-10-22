"""Replay archived hours through the same sweep code with a simulated clock.

A replay never touches live state:
  - it works on its own copy of each village (repo REPLAY / VILLAGE#id: level, hysteresis, open
    alert), made at start(); the live village record is never written;
  - everything it writes (copies, readings, alerts, reports) carries replay=True, and reset()
    removes only those items: live alerts, live readings and live levels are left alone;
  - the live sweep keeps running, and keeps raising live alerts, while a replay runs.
The public views show the replay's level on a village only while its live level is normal and it
has no open live alert, always with the live level beside it (views.village).
Audit rows stay: they are append-only. ReplayEnabled=false turns replays off for a real pilot.
"""

from __future__ import annotations

import time
from datetime import datetime

from Pukaar.core import clock
from Pukaar.core.log import get_logger, log
from Pukaar.services import external_data, readiness, risk_rules
from Pukaar.services.decision_engine import recompute_village
from Pukaar.store.models import ReplayState, Village, level_rank
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
    """Active and still making progress; a replay whose worker died stops being shown as running."""
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


def _replay_copy(v: Village) -> Village:
    """The replay's own copy of a village: same places and thresholds, its own level and alerts."""
    return v.model_copy(update={"level": "normal", "calm_sweeps": 0, "level_since": None, "open_alert_id": None,
                                "last_alert_id": None, "replay": True, "data_status": "ok", "data_ok_at": None,
                                "data_missing_sweeps": 0, "data_note": ""})


def reset(repo: Repo) -> ReplayState:
    """Stop the replay and remove what it wrote. Only replay-labelled items are touched."""
    shown = repo.list_replay_villages()
    repo.put_replay(ReplayState(active=False))
    removed = repo.delete_where(lambda item: bool(item.get("replay")) and item.get("kind") != "village")
    from Pukaar.services import events

    for v in repo.list_villages():
        if v.replay:
            # A flag the old shared-record replay left on a live record: only the flag is cleared.
            repo.update_village(v.id, replay=False)
        copy = shown.get(v.id)
        if copy is not None and copy.level != v.level:
            # Pages that showed the replay's level go back to the live level, which never changed.
            events.level_changed(v.id, v.level, copy.level, replay=True)
    log(_LOG, "replay reset", removed=removed)
    return repo.get_replay()


def clear_if_finished(repo: Repo, now: datetime | None = None) -> bool:
    """Remove a replay that finished (or whose worker died) more than 30 minutes ago.

    Called by the live sweep, so the "replay finished" banner does not stay for ever. It only
    removes replay items; live levels and alerts are not touched.
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
    reset(repo)  # an earlier replay's items only
    hours = external_data.replay_hours(scenario)
    for v in repo.list_villages():
        repo.put_replay_village(_replay_copy(v))
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
            # replay=True: recompute_village works on the replay's copy, never the live record.
            recompute_village(repo, village, now=at, reading=reading, workflow=workflow,
                              window_prefix=f"replay-{st.scenario}-{current.started_at}", replay=True)
        current.clock, current.hours_done, current.updated_at = clock.iso(at), i + 1, clock.iso(clock.now())
        repo.put_replay(current)
        time.sleep(speed_seconds_per_hour)
    final = repo.get_replay()
    final.active = False
    repo.put_replay(final)
    log(_LOG, "replay finished", scenario=st.scenario)
    return final


def _hours_before(day: str | None, at: str | None) -> float | None:
    """Hours from `at` to 00:00 UTC of `day` (negative when `at` is later)."""
    if not day or not at:
        return None
    t = clock.parse(at)
    return round((datetime.fromisoformat(day).replace(tzinfo=t.tzinfo) - t).total_seconds() / 3600, 1)


def backtest(scenario: str, villages, soil_modifier: bool | None = None) -> list[dict]:
    """Pure rules over the archived data, no store: first time each level is reached, the first
    get-ready outlook (services/readiness.py: evidence only, never a level), the day of peak
    forecast discharge, and the lead times to it. A first time equal to the first archived hour
    is flagged (`*_from_first_hour`): the lead is then a lower bound."""
    rows = []
    hours = external_data.replay_hours(scenario)
    sc = external_data.load_scenario(scenario)
    first_hour = clock.iso(hours[0]) if hours else None
    for v in villages:
        first: dict[str, str | None] = {"watch": None, "warning": None, "critical": None}
        level, calm = "normal", 0
        max_rain = 0.0
        first_ready: str | None = None
        trigger: dict | None = None
        ready_hours = 0
        for at in hours:
            reading = external_data.replay_reading(scenario, v, at)
            if reading is None:
                continue
            max_rain = max(max_rain, reading.rain_24h_mm or 0.0)
            a = risk_rules.assess(reading, v.thresholds, [], at, soil=v.soil, soil_modifier=soil_modifier)
            level, calm, _ = risk_rules.apply_hysteresis(level, calm, a.level)
            for lvl in first:
                if first[lvl] is None and level_rank(level) >= level_rank(lvl):
                    first[lvl] = clock.iso(at)
            out = readiness.outlook(reading, v.thresholds)
            ready_hours += out["state"] == "get_ready"
            if first_ready is None and out["state"] == "get_ready":
                first_ready = clock.iso(at)
                over = next(d for d in out["days"] if d["over"])
                trigger = {"line": out["line"], "line_cms": out["early"] if out["line"] == "early" else out["watch"],
                           "first_day_over": over["date"], "first_day_over_cms": over["value"],
                           "days_ahead": over["days_ahead"], "basis": out["basis"],
                           "peak_day": out["peak_day"], "peak_cms": out["peak_discharge"]}
        series = sc["villages"].get(v.id, {}).get("daily", {})
        window = [(d, q) for d, q in zip(series.get("time", []), series.get("river_discharge", []))
                  if q is not None and hours[0].date().isoformat() <= d <= hours[-1].date().isoformat()]
        peak_day, peak_q = max(window, key=lambda x: x[1]) if window else (None, None)
        rows.append({
            "village_id": v.id, "village": v.name, "first_watch": first["watch"], "first_warning": first["warning"],
            "first_critical": first["critical"], "peak_discharge_day": peak_day, "peak_discharge": peak_q,
            "thresholds": v.thresholds.model_dump() if v.thresholds else None, "max_rain_24h_mm": round(max_rain, 1),
            "lead_hours_watch_to_peak_day": _hours_before(peak_day, first["watch"]),
            "watch_from_first_hour": first["watch"] is not None and first["watch"] == first_hour,
            # The soft outlook: the river forecast for day 1-7 at or over the early line. Never an alert.
            "first_get_ready": first_ready,
            "get_ready_from_first_hour": first_ready is not None and first_ready == first_hour,
            "lead_hours_get_ready_to_peak_day": _hours_before(peak_day, first_ready),
            "get_ready_trigger": trigger,
            "get_ready_hours": ready_hours,
            "outcome": "never crossed" if first["watch"] is None
            else "reached " + max((k for k, t in first.items() if t), key=level_rank),
        })
    return rows


def display(repo: Repo, villages: list[Village]) -> dict[str, dict]:
    """What the public views show for each village while a replay's copies exist.

    The replay's level is shown only while the live level is normal and no live alert is open,
    so a replay can never hide a live warning. The live level is always given beside it.
    """
    copies = repo.list_replay_villages()
    out: dict[str, dict] = {}
    for v in villages:
        copy = copies.get(v.id)
        shown = copy is not None and v.level == "normal" and not v.open_alert_id
        out[v.id] = {
            "level": copy.level if shown else v.level,  # type: ignore[union-attr]
            "level_since": copy.level_since if shown else v.level_since,  # type: ignore[union-attr]
            "calm_sweeps": copy.calm_sweeps if shown else v.calm_sweeps,  # type: ignore[union-attr]
            "open_alert_id": copy.open_alert_id if shown else v.open_alert_id,  # type: ignore[union-attr]
            "replay": shown,
            "live_level": v.level,
            "live_level_since": v.level_since,
            "replay_level": copy.level if copy is not None else None,
        }
    return out
