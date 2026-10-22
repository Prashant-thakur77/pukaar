"""Rain and river data: live Open-Meteo forecasts, and archived replay files.

Live:   forecast API hourly precipitation (next 24 h) and root-zone soil
        moisture (the same request), every sweep; the same request names the
        models of PUKAAR_RAIN_MODELS (best_match, icon_seamless, gfs_seamless by
        default): best_match gives the 24-hour sum and soil, every model's hours
        feed the heavy-burst rule (risk_rules.rain_intensity); flood API daily river discharge
        for the village's river cell (past 2 days, today and the next 7 days), every
        sweep; the flood API's 51-member ensemble for lead days 1-7, once a day per
        cell (cached: days 1-3 for the level, 1-7 for the get-ready outlook's median);
        and official data as evidence (services/official_data.py).
Replay: files written by scripts/fetch_replay.py. Rain is the archived
        forecast (historical-forecast API; the other models under
        hourly_models); discharge is the flood API's
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
from Pukaar.services import fetch_cache, official_data, risk_rules, soil
from Pukaar.services.risk_rules import rain_level, river_level, scaled_bands
from Pukaar.store.models import Reading, Village

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
DISCHARGE_LOOKAHEAD_DAYS = 3
OUTLOOK_DAYS = 7  # the "get ready" outlook reads days 1..7 (services/readiness.py)
_LOG = get_logger("external_data")


def _reading(village: Village, at: datetime, hourly: list[tuple[str, float | None]], daily: list[tuple[str, float]],
             source: str, replay: bool, soil_root: float | None = None,
             models: dict[str, list[tuple[str, float | None]]] | None = None) -> Reading:
    # A missing hour is unknown, not 0 mm: the 24-hour sum is known only when all 24 hours are.
    window = hourly[:24]
    known = [(t, mm) for t, mm in window if mm is not None]
    rain_24h = round(sum(mm for _, mm in known), 1) if window and len(known) == len(window) == 24 else None
    today = at.date().isoformat()
    future = [(d, q) for d, q in daily if d >= today]
    ahead = future[: DISCHARGE_LOOKAHEAD_DAYS + 1]
    current = next((q for d, q in daily if d == today), None)
    peak = max((q for _, q in ahead), default=None)
    missing = []
    if rain_24h is None:
        missing.append("rain")
    if peak is None and village.thresholds is not None:
        missing.append("discharge")
    reading = Reading(
        village_id=village.id,
        at=clock.iso(at),
        rain_24h_mm=rain_24h,
        rain_hourly=[{"t": t, "mm": mm} for t, mm in known],
        # Other models' hours for the heavy-burst rule only; an unknown hour is left out, never 0 mm.
        rain_models={m: [{"t": t, "mm": mm} for t, mm in series[:24] if mm is not None]
                     for m, series in (models or {}).items() if any(mm is not None for _, mm in series[:24])},
        missing=missing,
        discharge=current,
        discharge_forecast=[{"date": d, "value": q} for d, q in ahead],
        discharge_peak=peak,
        discharge_outlook=[{"date": d, "value": q} for d, q in future[: OUTLOOK_DAYS + 1]],
        soil_moisture_root=soil_root,
        river_level=river_level(peak, village.thresholds),  # type: ignore[arg-type]
        source=source,
        replay=replay,
    )
    # The rain level uses the same bands as the rules (lowered only when the soil modifier is on), and
    # the heavy-burst rule on the hourly forecast: the higher of the two, as risk_rules.assess sets it.
    s = get_settings()
    info = soil.evaluate(reading, village.soil, s.soil_modifier_enabled)
    rain_24h_lvl = rain_level(rain_24h, scaled_bands(info["factor"]))
    burst = (risk_rules.rain_intensity(reading, village.thresholds, rain_24h_lvl, info)["level"]
             if s.rain_intensity_enabled else "normal")
    reading.rain_level = risk_rules._max(rain_24h_lvl, burst)  # type: ignore[assignment]
    return reading


def river_point(village: Village) -> tuple[float, float]:
    """The GloFAS cell to ask about: the calibrated river cell (data/river_cells.json), else the village."""
    th = village.thresholds
    if th is not None and th.cell_lat is not None and th.cell_lon is not None:
        return th.cell_lat, th.cell_lon
    return village.lat, village.lon


# -- the GloFAS ensemble, once a day ----------------------------------------------
# GloFAS issues one forecast a day, so the 51-member ensemble (control + 50) is fetched once per
# river cell per UTC day and cached (services/fetch_cache.py); rain stays every 15 minutes. A failed
# fetch is retried after ENSEMBLE_RETRY_MINUTES, never on every sweep.
ENSEMBLE_RETRY_MINUTES = 60
ENSEMBLE_CACHE_HOURS = 26
# Lead days kept from the ensemble: 1-3 set a level (risk_rules.ENSEMBLE_LEAD_DAYS); 1-7 give the
# get-ready outlook its median (services/readiness.py). Same single request, 8 days instead of 4.
ENSEMBLE_KEEP_DAYS = tuple(range(1, OUTLOOK_DAYS + 1))


def parse_ensemble(body: dict[str, Any], today: str) -> dict[str, Any]:
    """Sorted member discharges per lead day (1..7) from an ensemble=true flood API response."""
    daily = body.get("daily") or {}
    keys = [k for k in daily if k.startswith("river_discharge_member")]
    if not keys:
        raise ValueError("no ensemble members in the response")
    if "river_discharge" in daily:
        keys = ["river_discharge", *keys]  # the control run is the 51st member
    times = list(daily.get("time") or [])
    if today not in times:
        raise ValueError(f"the ensemble does not start by {today}")
    t0 = times.index(today)
    days = []
    for lead in ENSEMBLE_KEEP_DAYS:
        i = t0 + lead
        if i >= len(times):
            break
        values = sorted(round(float(daily[k][i]), 3) for k in keys if i < len(daily[k]) and daily[k][i] is not None)
        days.append({"date": times[i], "lead": lead, "values": values})
    if not any(d["values"] for d in days if d["lead"] in risk_rules.ENSEMBLE_LEAD_DAYS):
        raise ValueError("no member values for lead days 1-3")
    return {"status": "ok", "members": len(keys), "run_date": times[0], "days": days}


def fetch_ensemble(client: httpx.Client, lat: float, lon: float, at: datetime) -> dict[str, Any]:
    today = at.astimezone(timezone.utc).date().isoformat()

    def _fetch() -> dict[str, Any]:
        try:
            r = client.get(FLOOD_URL, params={"latitude": lat, "longitude": lon, "daily": "river_discharge",
                                              "ensemble": "true", "forecast_days": max(ENSEMBLE_KEEP_DAYS) + 1})
            r.raise_for_status()
            out = parse_ensemble(r.json(), today)
        except Exception as exc:
            log(_LOG, "river ensemble unavailable", 30, lat=lat, lon=lon, error=f"{type(exc).__name__}: {exc}"[:200])
            return {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"[:200], "fetched_at": clock.iso(clock.now())}
        return {**out, "fetched_at": clock.iso(clock.now()), "cell": {"lat": lat, "lon": lon}}

    return fetch_cache.get_or_fetch(f"ensemble:{lat:.3f},{lon:.3f}:{today}", ENSEMBLE_CACHE_HOURS * 3600, _fetch,
                                    failure_ttl_seconds=ENSEMBLE_RETRY_MINUTES * 60)


def split_models(h: dict[str, Any], models: tuple[str, ...]) -> tuple[dict[str, Any], dict[str, list]]:
    """(best_match's hourly block with plain variable names, {other model: [(t, mm)]}).

    A single-model response has plain names already. In a multi-model one every variable carries a
    _<model> suffix; best_match's precipitation and soil layers are the primary block (the 24-hour
    sum and soil read only it), the other models' precipitation feeds only the heavy-burst rule."""
    times = list(h.get("time", []))
    if "precipitation" in h or len(models) <= 1:
        return h, {}
    primary: dict[str, Any] = {"time": times}
    for var in ("precipitation", *soil.LAYERS):
        primary[var] = h.get(f"{var}_{models[0]}") or []
    others = {m: [(t, None if v is None else float(v)) for t, v in zip(times, h.get(f"precipitation_{m}") or [])]
              for m in models[1:]}
    return primary, others


def fetch_live(village: Village, at: datetime | None = None) -> Reading:
    s = get_settings()
    if not s.hydromet_enabled:
        raise RuntimeError("live hydromet fetch disabled (PUKAAR_HYDROMET_ENABLED=false)")
    at = at or clock.now()
    cell_lat, cell_lon = river_point(village)
    models = tuple(s.rain_models) or ("best_match",)
    with httpx.Client(timeout=s.hydromet_timeout_seconds) as client:
        params: dict[str, Any] = {"latitude": village.lat, "longitude": village.lon,
                                  "hourly": ",".join(("precipitation", *soil.LAYERS)), "forecast_hours": 24,
                                  "timezone": "GMT"}
        if len(models) > 1:
            # One request still: Open-Meteo returns each variable once per model, suffixed with its name.
            params["models"] = ",".join(models)
        rain = client.get(FORECAST_URL, params=params)
        rain.raise_for_status()
        flood = client.get(
            FLOOD_URL,
            params={"latitude": cell_lat, "longitude": cell_lon, "daily": "river_discharge",
                    "past_days": 2, "forecast_days": OUTLOOK_DAYS + 1},
        )
        flood.raise_for_status()
        ensemble = (fetch_ensemble(client, cell_lat, cell_lon, at)
                    if s.river_ensemble_enabled and village.thresholds is not None else {"status": "off"})
    h, others = split_models(rain.json().get("hourly", {}), models)
    # None stays None: a gap in the forecast is unknown rain, never 0 mm (decision_engine handles it).
    hourly = [(t, None if v is None else float(v)) for t, v in zip(h.get("time", []), h.get("precipitation", []))]
    soil_root = soil.root_zone(h, 0)  # the current hour: the antecedent state, not a forecast
    d = flood.json().get("daily", {})
    daily = [(t, float(v)) for t, v in zip(d.get("time", []), d.get("river_discharge", [])) if v is not None]
    reading = _reading(village, at, hourly, daily, "open-meteo", replay=False, soil_root=soil_root, models=others)
    reading.discharge_ensemble = ensemble
    # Evidence only (never raises: an unavailable source is an "unavailable" item).
    reading.official = official_data.for_village(village, at)
    reading.river_level = risk_rules.river_assessment(reading, village.thresholds)["level"]  # type: ignore[assignment]
    log(_LOG, "live reading fetched", village_id=village.id, hours=len(hourly), days=len(daily), soil=soil_root,
        ensemble=ensemble.get("status"), official=[i.get("status") for i in reading.official])
    return reading


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


def replay_reading(name: str, village: Village, at: datetime, models: tuple[str, ...] | None = None) -> Reading | None:
    """The archived reading at one hour. models: the rain models the burst rule may read (None: the
    PUKAAR_RAIN_MODELS setting); models other than best_match come from hourly_models when archived."""
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
    archived = series.get("hourly_models") or {}
    wanted = get_settings().rain_models if models is None else models
    others = {m: [(times[j], None if archived[m][j] is None else float(archived[m][j]))
                  for j in range(i, min(i + 24, len(times)))]
              for m in wanted if m != "best_match" and m in archived and hourly}
    daily = [(d, float(q)) for d, q in zip(series["daily"]["time"], series["daily"]["river_discharge"]) if q is not None]
    return _reading(village, at, hourly, daily, f"replay:{name}", replay=True, soil_root=soil_at(name, village.id, at),
                    models=others)
