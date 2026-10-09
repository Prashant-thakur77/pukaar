"""Risk rules (PLAN.md section 7). Plain code: the model never sets a level."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from Pukaar.store.models import LEVELS, VERIFIED_STATES, Reading, Report, Thresholds, level_rank

# IMD 24-hour rainfall bands (heavy, very heavy, extremely heavy), in mm.
RAIN_BANDS = (("critical", 204.5), ("warning", 115.6), ("watch", 64.5))
HYSTERESIS_SWEEPS = 3
REPORT_FULL_WEIGHT_HOURS = 1.0
REPORT_ZERO_WEIGHT_HOURS = 3.0
# Report types that floor the village at warning once verified.
IMPACT_TYPES = {"road_cut", "bridge_unsafe", "homes_affected", "people_trapped", "landslide"}
SEVERITY_TO_LEVEL = {"low": "normal", "medium": "watch", "high": "warning", "critical": "critical"}
RULES_VERSION = "risk-rules-v1"
AUTO_VERIFIED_CAP = "warning"


def rain_level(rain_24h_mm: float | None) -> str:
    if rain_24h_mm is None:
        return "normal"
    for level, mm in RAIN_BANDS:
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


def assess(
    reading: Reading | None,
    thresholds: Thresholds | None,
    reports: list[tuple[Report, datetime]],
    now: datetime,
) -> Assessment:
    """Raw level for one sweep, before hysteresis. reports = (report, created_at)."""
    rules: list[str] = []
    evidence: list[dict[str, Any]] = []

    rain = rain_level(reading.rain_24h_mm if reading else None)
    river = river_level(reading.discharge_peak if reading else None, thresholds)
    if reading is not None:
        evidence.append(
            {
                "kind": "reading",
                "at": reading.at,
                "source": reading.source,
                "rain_24h_mm": reading.rain_24h_mm,
                "rain_level": rain,
                "rain_bands_mm": {lvl: mm for lvl, mm in RAIN_BANDS},
                "discharge_peak": reading.discharge_peak,
                "river_level": river,
                "thresholds": thresholds.model_dump() if thresholds else None,
                "replay": reading.replay,
            }
        )
        if rain != "normal":
            rules.append(f"rain_24h>={dict(RAIN_BANDS)[rain]}mm:{rain}")
        if river != "normal" and thresholds is not None:
            rules.append(f"discharge>={getattr(thresholds, river)}:{river}")
    else:
        rules.append("no_reading")

    level = _max(rain, river)

    report_level = "normal"
    impact_verified = False
    for report, created_at in reports:
        weight = report_weight(created_at, now)
        if weight <= 0:
            continue
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
        if report.report_type in IMPACT_TYPES:
            impact_verified = True

    if report_level != "normal":
        rules.append(f"verified_reports:{report_level}")
        level = _max(level, report_level)

    independent = [lvl for lvl in (rain, river, report_level) if level_rank(lvl) >= level_rank("watch")]
    if len(independent) >= 2:
        level = _up(level)
        rules.append("two_sources_agree:+1")

    if impact_verified and level_rank(level) < level_rank("warning"):
        level = "warning"
        rules.append("verified_impact_report:floor_warning")

    contradictions: list[str] = []
    data_level = _max(rain, river)
    unverified_high = [
        r for r, at in reports if r.state not in VERIFIED_STATES and r.severity in {"high", "critical"} and report_weight(at, now) > 0
    ]
    if data_level == "normal" and (report_level in {"warning", "critical"} or unverified_high):
        contradictions.append("data_low_reports_high")
    if level_rank(data_level) >= level_rank("warning") and reports and all(r.severity == "low" for r, _ in reports):
        contradictions.append("data_high_reports_low")
    if contradictions:
        rules.append("data_disagrees")

    return Assessment(level, rain, river, report_level, rules, contradictions, evidence)


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
