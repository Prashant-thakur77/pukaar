"""Rain and river data: live Open-Meteo forecasts, and archived replay files.

Live:   forecast API hourly precipitation (next 24 h) and root-zone soil
        moisture (the same request), and flood API daily river discharge
        (past 2 days, today and the next 7 days).
Replay: files written by scripts/fetch_replay.py. Rain is the archived
        forecast (historical-forecast API); discharge is the flood API's
        archived daily series, which stands in for a perfect discharge
        forecast; soil moisture (soil.json, when present) is the archived
        forecast's root-zone layers. Every replay reading carries replay=True.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log
from Pukaar.services import soil
from Pukaar.services.risk_rules import rain_level, river_level, scaled_bands
from Pukaar.store.models import Reading, Village

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
DISCHARGE_LOOKAHEAD_DAYS = 3
OUTLOOK_DAYS = 7  # the "get ready" outlook reads days 2..7 (services/readiness.py)
_LOG = get_logger("external_data")


def _reading(village: Village, at: datetime, hourly: list[tuple[str, float]], daily: list[tuple[str, float]],
             source: str, replay: bool, soil_root: float | None = None) -> Reading:
    rain_24h = round(sum(mm for _, mm in hourly[:24]), 1) if hourly else None
    today = at.date().isoformat()
    future = [(d, q) for d, q in daily if d >= today]
    ahead = future[: DISCHARGE_LOOKAHEAD_DAYS + 1]
    current = next((q for d, q in daily if d == today), None)
    peak = max((q for _, q in ahead), default=None)
    reading = Reading(
        village_id=village.id,
        at=clock.iso(at),
        rain_24h_mm=rain_24h,
        rain_hourly=[{"t": t, "mm": mm} for t, mm in hourly[:24]],
        discharge=current,
        discharge_forecast=[{"date": d, "value": q} for d, q in ahead],
        discharge_peak=peak,
        discharge_outlook=[{"date": d, "value": q} for d, q in future[: OUTLOOK_DAYS + 1]],
        soil_moisture_root=soil_root,
        river_level=river_level(peak, village.thresholds),  # type: ignore[arg-type]
        source=source,
        replay=replay,
    )
    # The rain level uses the same bands as the rules: lowered only when the soil modifier is on.
    info = soil.evaluate(reading, village.soil, get_settings().soil_modifier_enabled)
    reading.rain_level = rain_level(rain_24h, scaled_bands(info["factor"]))  # type: ignore[assignment]
    return reading


def fetch_live(village: Village, at: datetime | None = None) -> Reading:
    s = get_settings()
    if not s.hydromet_enabled:
        raise RuntimeError("live hydromet fetch disabled (PUKAAR_HYDROMET_ENABLED=false)")
    at = at or clock.now()
    with httpx.Client(timeout=s.hydromet_timeout_seconds) as client:
        rain = client.get(
            FORECAST_URL,
            params={"latitude": village.lat, "longitude": village.lon,
                    "hourly": ",".join(("precipitation", *soil.LAYERS)), "forecast_hours": 24, "timezone": "GMT"},
        )
        rain.raise_for_status()
        flood = client.get(
            FLOOD_URL,
            params={"latitude": village.lat, "longitude": village.lon, "daily": "river_discharge",
                    "past_days": 2, "forecast_days": OUTLOOK_DAYS + 1},
        )
        flood.raise_for_status()
    h = rain.json().get("hourly", {})
    hourly = [(t, float(v or 0.0)) for t, v in zip(h.get("time", []), h.get("precipitation", []))]
    soil_root = soil.root_zone(h, 0)  # the current hour: the antecedent state, not a forecast
    d = flood.json().get("daily", {})
    daily = [(t, float(v)) for t, v in zip(d.get("time", []), d.get("river_discharge", [])) if v is not None]
    log(_LOG, "live reading fetched", village_id=village.id, hours=len(hourly), days=len(daily), soil=soil_root)
    return _reading(village, at, hourly, daily, "open-meteo", replay=False, soil_root=soil_root)


# -- replay ---------------------------------------------------------------

def replay_dir() -> Path:
    return get_settings().data_dir / "replay"


@lru_cache(maxsize=8)
def load_scenario(name: str) -> dict[str, Any]:
    path = replay_dir() / name / "scenario.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def load_soil(name: str) -> dict[str, Any]:
    """Archived root-zone soil moisture for a scenario ({} when not fetched yet)."""
    path = replay_dir() / name / "soil.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def soil_at(name: str, village_id: str, at: datetime) -> float | None:
    data = load_soil(name)
    values = data.get("villages", {}).get(village_id)
    if not values or "start" not in data:
        return None
    i = int((at - clock.parse(data["start"])).total_seconds() // 3600)
    return float(values[i]) if 0 <= i < len(values) and values[i] is not None else None


def list_scenarios() -> list[str]:
    root = replay_dir()
    if not root.exists():
        return []
    return sorted(p.parent.name for p in root.glob("*/scenario.json"))


def replay_hours(name: str) -> list[datetime]:
    sc = load_scenario(name)
    start = clock.parse(sc["start"])
    end = clock.parse(sc["end"])
    hours = []
    t = start
    while t <= end:
        hours.append(t)
        t += timedelta(hours=1)
    return hours


def replay_reading(name: str, village: Village, at: datetime) -> Reading | None:
    sc = load_scenario(name)
    series = sc["villages"].get(village.id)
    if series is None:
        return None
    at = at.astimezone(timezone.utc)
    key = at.strftime("%Y-%m-%dT%H:00")
    times: list[str] = series["hourly"]["time"]
    if key not in times:
        return None
    i = times.index(key)
    precip = series["hourly"]["precipitation"]
    hourly = [(times[j], float(precip[j] or 0.0)) for j in range(i, min(i + 24, len(times)))]
    if len(hourly) < 24:
        # Not enough archived hours ahead: rain is unknown rather than guessed.
        hourly = []
    daily = [(d, float(q)) for d, q in zip(series["daily"]["time"], series["daily"]["river_discharge"]) if q is not None]
    return _reading(village, at, hourly, daily, f"replay:{name}", replay=True, soil_root=soil_at(name, village.id, at))
