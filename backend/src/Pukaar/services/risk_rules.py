"""Risk rules. Plain code: the model never sets a level."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from Pukaar.services import soil as soil_mod
from Pukaar.store.models import (
    LEVELS,
    VERIFIED_STATES,
    GaugeConfig,
    Reading,
    Report,
    SensorReading,
    SoilRange,
    Thresholds,
    level_rank,
)

# IMD 24-hour rainfall bands (heavy, very heavy, extremely heavy), in mm.
RAIN_BANDS = (("critical", 204.5), ("warning", 115.6), ("watch", 64.5))
HYSTERESIS_SWEEPS = 3
REPORT_FULL_WEIGHT_HOURS = 1.0
REPORT_ZERO_WEIGHT_HOURS = 3.0
# Report types that floor the village at warning once verified.
IMPACT_TYPES = {"road_cut", "bridge_unsafe", "homes_affected", "people_trapped", "landslide"}
SEVERITY_TO_LEVEL = {"low": "normal", "medium": "watch", "high": "warning", "critical": "critical"}
RULES_VERSION = "risk-rules-v2"
AUTO_VERIFIED_CAP = "warning"
# A gauge reading older than this changes nothing.
GAUGE_FRESH_MINUTES = 30


def scaled_bands(factor: float = 1.0) -> tuple[tuple[str, float], ...]:
    """The IMD bands times a soil factor, never below soil.FLOOR (70%) of IMD.

    Rounded up to 0.1 mm, so rounding can never take a band below the floor.
    """
    f = max(soil_mod.FLOOR, min(1.0, factor))
    return tuple((lvl, math.ceil(round(mm * f * 10, 6)) / 10) for lvl, mm in RAIN_BANDS)


def rain_level(rain_24h_mm: float | None, bands: tuple[tuple[str, float], ...] = RAIN_BANDS) -> str:
    if rain_24h_mm is None:
        return "normal"
    for level, mm in bands:
        if rain_24h_mm >= mm:
            return level
    return "normal"


def river_level(peak_discharge: float | None, thresholds: Thresholds | None) -> str:
    if peak_discharge is None or thresholds is None:
        return "normal"
    if peak_discharge >= thresholds.critical:
        return "critical"
    if peak_discharge >= thresholds.warning:
        return "warning"
    if peak_discharge >= thresholds.watch:
        return "watch"
    return "normal"


# -- river: the GloFAS ensemble ---------------------------------------------------
# A level is raised when at least P_MIN of the ensemble members reach its threshold on a lead
# day (the ECMWF/GloFAS reporting-point convention); Settings.river_ensemble_p_min overrides it.
ENSEMBLE_P_MIN = 0.3
ENSEMBLE_LEAD_DAYS = (1, 2, 3)
RIVER_LEVELS = ("watch", "warning", "critical")


def exceedance_probabilities(days: list[dict[str, Any]], thresholds: Thresholds) -> list[dict[str, Any]]:
    """Per lead day: the share of ensemble members at or above each threshold.

    days: [{"date", "lead", "values": [member discharges]}] (Reading.discharge_ensemble["days"]).
    Members with no value are left out of both counts; a day with none is skipped.
    """
    out = []
    for day in days:
        if day.get("lead") not in ENSEMBLE_LEAD_DAYS:
            continue
        values = [float(v) for v in day.get("values") or [] if v is not None]
        if not values:
            continue
        p = {lvl: round(sum(1 for v in values if v >= getattr(thresholds, lvl)) / len(values), 3) for lvl in RIVER_LEVELS}
        out.append({"date": day.get("date"), "lead": day["lead"], "members": len(values), "p": p})
    return out


def ensemble_level(probabilities: list[dict[str, Any]], p_min: float = ENSEMBLE_P_MIN) -> tuple[str, dict[str, float]]:
    """(the highest level whose exceedance probability reaches p_min on any lead day, max P per level)."""
    p_max = {lvl: max((d["p"][lvl] for d in probabilities), default=0.0) for lvl in RIVER_LEVELS}
    level = "normal"
    for lvl in RIVER_LEVELS:
        if p_max[lvl] >= p_min:
            level = lvl
    return level, p_max


def river_assessment(reading: Reading | None, thresholds: Thresholds | None, p_min: float | None = None,
                     use_ensemble: bool | None = None) -> dict[str, Any]:
    """The river level and how it was reached.

    With an ensemble ("ensemble" mode): the higher of today's discharge against the thresholds and
    the highest level whose probability reaches p_min on lead day 1-3. A deterministic forecast that
    crosses a threshold while fewer than p_min of the members do raises nothing: that is the point.
    Without one ("deterministic" mode: no ensemble, unavailable, switched off, or a replay): the
    peak of today and the next three days, as before. Missing discharge never reads as a calm
    river: decision_engine carries the last values forward or holds the level.
    """
    if use_ensemble is None or p_min is None:
        from Pukaar.core.config import get_settings

        s = get_settings()
        use_ensemble = getattr(s, "river_ensemble_enabled", True) if use_ensemble is None else use_ensemble
        p_min = getattr(s, "river_ensemble_p_min", ENSEMBLE_P_MIN) if p_min is None else p_min
    out: dict[str, Any] = {"level": "normal", "mode": "none", "p_min": p_min, "ensemble_status": None,
                           "p_at_level": None}
    if reading is None or thresholds is None:
        return out
    ens = reading.discharge_ensemble or {}
    out["ensemble_status"] = ens.get("status") if ens else None
    deterministic = river_level(reading.discharge_peak, thresholds)
    probabilities = exceedance_probabilities(ens.get("days") or [], thresholds) if ens.get("status") == "ok" else []
    if use_ensemble and probabilities:
        today = river_level(reading.discharge, thresholds)
        ens_lvl, p_max = ensemble_level(probabilities, p_min)
        level = _max(today, ens_lvl)
        out.update(level=level, mode="ensemble", today_level=today, ensemble_level=ens_lvl,
                   deterministic_level=deterministic, p_max=p_max, days=probabilities,
                   members=max(d["members"] for d in probabilities),
                   # The probability behind the level; None when today's discharge set it.
                   p_at_level=p_max[level] if level != "normal" and ens_lvl == level else None,
                   run_date=ens.get("run_date"), fetched_at=ens.get("fetched_at"))
        return out
    out.update(level=deterministic, mode="deterministic", deterministic_level=deterministic)
    return out


def official_level(items: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """The highest level any available official source implies, and which sources said so.
    An unavailable or switched-off source says nothing (never "normal")."""
    level, sources = "normal", []
    for item in items:
        lvl = item.get("level")
        if item.get("status") != "ok" or lvl not in LEVELS or lvl == "normal":
            continue
        if level_rank(lvl) > level_rank(level):
            level, sources = lvl, [str(item.get("source", "?"))]
        elif lvl == level:
            sources.append(str(item.get("source", "?")))
    return level, sources


def gauge_level(stage_cm: float | None, gauge: GaugeConfig | None) -> str:
    if stage_cm is None or gauge is None:
        return "normal"
    if stage_cm >= gauge.critical_cm:
        return "critical"
    if stage_cm >= gauge.warning_cm:
        return "warning"
    if stage_cm >= gauge.watch_cm:
        return "watch"
    return "normal"


def gauge_counted_level(sensor: SensorReading, gauge: GaugeConfig) -> str:
    """The level a stored reading counts for. Ingest (services/gauge.py) sets effective_level: 2 of
    the last 3 good live readings at or above a stage, spikes and out-of-range readings left out,
    one step up when rising fast. A backfilled reading never counts. A row stored before ingest
    computed the effective level falls back to its own stage."""
    if sensor.origin == "backfill":
        return "normal"
    if sensor.effective_level in LEVELS:
        return sensor.effective_level
    return gauge_level(sensor.water_level_cm, gauge)


def gauge_is_fresh(sensor: SensorReading | None, now: datetime) -> bool:
    if sensor is None:
        return False
    age = (now - datetime.fromisoformat(sensor.at.replace("Z", "+00:00"))).total_seconds()
    # A few minutes of device clock skew into the future is tolerated, not more.
    return -300 <= age <= GAUGE_FRESH_MINUTES * 60


def report_weight(created_at: datetime, now: datetime) -> float:
    """1.0 for the first hour, fading linearly to 0 at three hours."""
    hours = max(0.0, (now - created_at).total_seconds() / 3600.0)
    if hours <= REPORT_FULL_WEIGHT_HOURS:
        return 1.0
    if hours >= REPORT_ZERO_WEIGHT_HOURS:
        return 0.0
    return 1.0 - (hours - REPORT_FULL_WEIGHT_HOURS) / (REPORT_ZERO_WEIGHT_HOURS - REPORT_FULL_WEIGHT_HOURS)


def _max(*levels: str) -> str:
    return max(levels, key=level_rank)


def _up(level: str) -> str:
    return LEVELS[min(level_rank(level) + 1, len(LEVELS) - 1)]


@dataclass
class Assessment:
    level: str
    rain_level: str
    river_level: str
    report_level: str
    rules_fired: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    gauge_level: str = "normal"
    staff_level: str = "normal"


def assess(
    reading: Reading | None,
    thresholds: Thresholds | None,
    reports: list[tuple[Report, datetime]],
    now: datetime,
    *,
    sensor: SensorReading | None = None,
    gauge: GaugeConfig | None = None,
    soil: SoilRange | None = None,
    soil_modifier: bool | None = None,
    allow_simulated: bool = False,
    ensemble_p_min: float | None = None,
    official_raises: bool | None = None,
) -> Assessment:
    """Raw level for one sweep, before hysteresis. reports = (report, created_at).

    sensor/gauge: the village gauge's latest reading and its stage thresholds. Only a
    reading at most GAUGE_FRESH_MINUTES old counts; a stale or missing one changes nothing.
    A simulated reading (scripts/gauge_sim*.py, a "-sim" device) is evidence only: it never
    sets a level unless allow_simulated (replays only).
    soil/soil_modifier: the village's soil range and whether the soil modifier may lower the
    rain bands (None reads the PUKAAR_SOIL_MODIFIER setting).
    ensemble_p_min: the share of ensemble members that raises a river level (None: the setting).
    official_raises: whether official data may raise the level (None: the setting); never lowers it.
    """
    rules: list[str] = []
    evidence: list[dict[str, Any]] = []

    if soil_modifier is None:
        from Pukaar.core.config import get_settings

        soil_modifier = get_settings().soil_modifier_enabled
    soil_info = soil_mod.evaluate(reading, soil, soil_modifier)
    bands = scaled_bands(soil_info["factor"])
    if soil_info["applied"]:
        rules.append(soil_mod.rule_tag(soil_info))
    rain = rain_level(reading.rain_24h_mm if reading else None, bands)
    river_info = river_assessment(reading, thresholds, ensemble_p_min)
    river = river_info["level"]
    if reading is not None:
        evidence.append(
            {
                "kind": "reading",
                "at": reading.at,
                "source": reading.source,
                "rain_24h_mm": reading.rain_24h_mm,
                "rain_level": rain,
                "rain_bands_mm": {lvl: mm for lvl, mm in bands},
                "rain_bands_imd_mm": {lvl: mm for lvl, mm in RAIN_BANDS},
                "discharge_peak": reading.discharge_peak,
                "river_level": river,
                "thresholds": thresholds.model_dump() if thresholds else None,
                "replay": reading.replay,
                "missing": list(reading.missing),
                "carried_from": reading.carried_from,
            }
        )
        for part in reading.missing:
            # Unknown, not 0 mm: decision_engine carries the last complete value or holds the level.
            rules.append(f"{part}_carried_forward" if reading.carried_from else f"{part}_unknown")
        if soil_info["moisture_root"] is not None:
            evidence.append({"kind": "soil", "at": reading.at, **soil_info})
        if rain != "normal":
            rules.append(f"rain_24h>={dict(bands)[rain]}mm:{rain}")
        if thresholds is not None:
            evidence.append({"kind": "river", "at": reading.at, "cell": {"lat": thresholds.cell_lat, "lon": thresholds.cell_lon},
                             "river": thresholds.river, "cell_verified": thresholds.cell_verified,
                             "method": thresholds.method, "return_period_years": thresholds.return_period_years,
                             **{k: v for k, v in river_info.items() if k != "days"},
                             "lead_days": river_info.get("days", [])})
            if river_info["mode"] == "ensemble" and river != "normal":
                if river_info["p_at_level"] is not None:
                    rules.append(f"river_ensemble:P({river})={river_info['p_at_level']:g}>={river_info['p_min']:g}:{river}")
                else:
                    rules.append(f"discharge_today>={getattr(thresholds, river)}:{river}")
            elif river != "normal":
                rules.append(f"discharge>={getattr(thresholds, river)}:{river}")
            if river_info["ensemble_status"] == "unavailable":
                rules.append("river_ensemble_unavailable")
    else:
        rules.append("no_reading")

    gauge_lvl = "normal"
    if gauge is not None and gauge_is_fresh(sensor, now):
        assert sensor is not None
        measured = gauge_level(sensor.water_level_cm, gauge)
        counted = gauge_counted_level(sensor, gauge)
        confirmed = sensor.confirmed_level if sensor.confirmed_level in LEVELS else counted
        ignored = (sensor.simulated and not allow_simulated) or sensor.origin == "backfill"
        gauge_lvl = "normal" if ignored else counted
        evidence.append(
            {
                "kind": "gauge",
                "at": sensor.at,
                "device_id": sensor.device_id,
                "water_level_cm": sensor.water_level_cm,
                "gauge_level": measured,
                "confirmed_level": confirmed,
                "effective_level": counted,
                "quality": sensor.quality,
                "rising_fast": sensor.rising_fast,
                "rise_cm": sensor.rise_cm,
                "counted": not ignored,
                "thresholds_cm": {"watch": gauge.watch_cm, "warning": gauge.warning_cm, "critical": gauge.critical_cm},
                "battery_v": sensor.battery_v,
                "simulated": sensor.simulated,
            }
        )
        if gauge_lvl != "normal":
            if confirmed != "normal":
                rules.append(f"gauge>={getattr(gauge, confirmed + '_cm'):g}cm:{confirmed}")
            if sensor.rising_fast and counted != confirmed:
                rules.append(f"gauge_rising_fast:+{sensor.rise_cm or 0:g}cm/{gauge.rise_minutes:g}min:{counted}")
        elif not ignored and measured != "normal" and confirmed == "normal":
            # One reading at a stage is not enough (2 of the last 3 good readings must agree).
            rules.append(f"gauge_unconfirmed:{measured}")
        if ignored:
            # Stored and shown, never a live level: a simulator must not raise a real alert.
            rules.append("gauge_simulated_ignored")
        elif sensor.simulated:
            rules.append("gauge_simulated")

    level = _max(rain, river, gauge_lvl)

    # Official data (CWC, IMD, Flood Hub, BIPAD) is evidence for the officer. It raises the level only
    # when official_raises_level is on, and only ever upwards; it is not a source for "two agree".
    if reading is not None and reading.official:
        if official_raises is None:
            from Pukaar.core.config import get_settings

            official_raises = bool(getattr(get_settings(), "official_raises_level", False))
        evidence.append({"kind": "official", "at": reading.at, "raises_level": official_raises,
                         "items": list(reading.official)})
        off_level, off_sources = official_level(reading.official)
        if off_level != "normal":
            if official_raises and level_rank(off_level) > level_rank(level):
                level = off_level
                rules.append(f"official:{'+'.join(off_sources)}:{off_level}")
            else:
                rules.append(f"official_corroborates:{'+'.join(off_sources)}:{off_level}")

    report_level = "normal"
    impact_verified = False
    # Reports carrying an officer-confirmed staff gauge reading form one observation with that
    # reading; every other report is another. Kept apart so one photo never counts twice.
    staff_level = "normal"
    staff_report_ids: set[str] = set()
    report_levels: dict[str, str] = {}
    for report, created_at in reports:
        weight = report_weight(created_at, now)
        if weight <= 0:
            continue
        sr = report.staff_reading
        if sr is not None:
            confirmed = sr.status == "confirmed"
            evidence.append(
                {
                    "kind": "staff_gauge",
                    "report_id": report.id,
                    "gauge_id": sr.gauge_id,
                    "gauge_name": sr.gauge_name,
                    "at": report.created_at,
                    "mark": sr.confirmed_mark if confirmed else sr.mark,
                    "villager_mark": sr.mark,
                    "height_cm": sr.confirmed_height_cm if confirmed else sr.height_cm,
                    "status": sr.status,
                    "confirmed_by": sr.confirmed_by if confirmed else None,
                    "confirmed_at": sr.confirmed_at if confirmed else None,
                    "level": sr.confirmed_level if confirmed else None,
                    "weight": round(weight, 3),
                    "replay": report.replay,
                }
            )
            # Only a reading an officer confirmed can change a level; the villager's own mark is evidence.
            if confirmed and sr.confirmed_level and sr.confirmed_level != "normal":
                eff = sr.confirmed_level if weight >= 0.5 else LEVELS[max(0, level_rank(sr.confirmed_level) - 1)]
                if eff != "normal":
                    staff_level = _max(staff_level, eff)
                    staff_report_ids.add(report.id)
                    rules.append(f"staff_gauge:{sr.confirmed_mark}:{eff}")
        verified = report.state in VERIFIED_STATES
        sev_level = SEVERITY_TO_LEVEL[report.severity]
        evidence.append(
            {
                "kind": "report",
                "report_id": report.id,
                "at": report.created_at,
                "type": report.report_type,
                "severity": report.severity,
                "state": report.state,
                "verified": verified,
                "weight": round(weight, 3),
                "replay": report.replay,
            }
        )
        if not verified:
            continue  # only verified reports can raise a level
        # A faded report counts one level lower.
        effective = sev_level if weight >= 0.5 else LEVELS[max(0, level_rank(sev_level) - 1)]
        if report.state == "verified_auto" and level_rank(effective) > level_rank(AUTO_VERIFIED_CAP):
            # Code-verified (not officer-verified) reports can raise a village to warning at most.
            effective = AUTO_VERIFIED_CAP
            rules.append(f"auto_verified_capped:{report.id}")
        report_level = _max(report_level, effective)
        report_levels[report.id] = effective
        if report.report_type in IMPACT_TYPES:
            impact_verified = True

    if report_level != "normal":
        rules.append(f"verified_reports:{report_level}")
        level = _max(level, report_level)
    if staff_level != "normal":
        rules.append(f"staff_gauge_confirmed:{staff_level}")
        level = _max(level, staff_level)

    other_reports = _max("normal", *(lvl for rid, lvl in report_levels.items() if rid not in staff_report_ids))
    staff_obs = _max(staff_level, *(lvl for rid, lvl in report_levels.items() if rid in staff_report_ids))
    independent = [lvl for lvl in (rain, river, gauge_lvl, other_reports, staff_obs)
                   if level_rank(lvl) >= level_rank("watch")]
    if len(independent) >= 2:
        level = _up(level)
        rules.append("two_sources_agree:+1")

    if impact_verified and level_rank(level) < level_rank("warning"):
        level = "warning"
        rules.append("verified_impact_report:floor_warning")

    contradictions: list[str] = []
    data_level = _max(rain, river, gauge_lvl)
    unverified_high = [
        r for r, at in reports if r.state not in VERIFIED_STATES and r.severity in {"high", "critical"} and report_weight(at, now) > 0
    ]
    if data_level == "normal" and (report_level in {"warning", "critical"} or unverified_high):
        contradictions.append("data_low_reports_high")
    if level_rank(data_level) >= level_rank("warning") and reports and all(r.severity == "low" for r, _ in reports):
        contradictions.append("data_high_reports_low")
    if contradictions:
        rules.append("data_disagrees")

    return Assessment(level, rain, river, report_level, rules, contradictions, evidence, gauge_lvl, staff_level)


def apply_hysteresis(current: str, calm_sweeps: int, raw: str) -> tuple[str, int, bool]:
    """Rise at once; drop one level only after three sweeps below the current level.

    Returns (new_level, new_calm_sweeps, rose).
    """
    if level_rank(raw) > level_rank(current):
        return raw, 0, True
    if level_rank(raw) == level_rank(current):
        return current, 0, False
    calm = calm_sweeps + 1
    if calm >= HYSTERESIS_SWEEPS:
        return LEVELS[level_rank(current) - 1], 0, False
    return current, calm, False
