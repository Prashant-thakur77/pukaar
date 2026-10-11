"""Antecedent soil moisture: a bounded modifier on the IMD rain bands.

The same rain on wet ground does more damage: antecedent rainfall and soil
moisture condition Himalayan landslides and flash floods (NASA LHASA v2 uses
SMAP soil moisture; Darjeeling thresholds fit best on 20-day antecedent rain).

Reading: root-zone moisture is the mean of Open-Meteo's 9-27 cm and 27-81 cm
layers (m³/m³). The top layers (0-1, 1-3, 3-9 cm) swing with every shower;
the root zone is what stays wet after days of rain, which is the antecedent
state we want.

Saturation S = clip((sm - dry) / (wet - dry), 0, 1), where dry and wet are the
village's own 5th and 95th percentiles over two years of hourly values
(scripts/calibrate.py --soil). Without a calibrated range the defaults 0.15 and
0.45 m³/m³ are used and labelled as such.

Modifier: when S >= 0.8 the rain bands are multiplied by
1 - 0.3 * (S - 0.8) / 0.2, so at most 30% lower at full saturation, never below
70% of the IMD values. It only moves the rain bands: dry rain never becomes a
level, and soil alone never raises one.
"""

from __future__ import annotations

from typing import Any

from Pukaar.store.models import Reading, SoilRange

LAYERS = ("soil_moisture_9_to_27cm", "soil_moisture_27_to_81cm")
DEFAULT_RANGE = SoilRange(dry=0.15, wet=0.45, source="default 0.15/0.45 m³/m³ (no calibrated range for this village)")
SATURATED_AT = 0.8
MAX_CUT = 0.3
FLOOR = 1.0 - MAX_CUT


def root_zone(values: dict[str, list[Any]], index: int = 0) -> float | None:
    """Mean of the root-zone layers at one hourly index, or None if any layer is missing."""
    picked = []
    for layer in LAYERS:
        series = values.get(layer) or []
        if index >= len(series) or series[index] is None:
            return None
        picked.append(float(series[index]))
    return round(sum(picked) / len(picked), 4)


def saturation(sm: float | None, soil: SoilRange | None) -> float | None:
    if sm is None:
        return None
    rng = soil or DEFAULT_RANGE
    span = rng.wet - rng.dry
    if span <= 0:
        return None
    return round(min(1.0, max(0.0, (sm - rng.dry) / span)), 3)


def band_factor(s: float | None) -> float:
    """1.0 below S = 0.8; down to 0.7 at S = 1.0; never below 0.7."""
    if s is None or s < SATURATED_AT:
        return 1.0
    return round(max(FLOOR, 1.0 - MAX_CUT * (s - SATURATED_AT) / (1.0 - SATURATED_AT)), 3)


def evaluate(reading: Reading | None, soil: SoilRange | None, enabled: bool) -> dict[str, Any]:
    """Soil state for one reading: S, the factor, and whether the rules used it."""
    sm = reading.soil_moisture_root if reading else None
    rng = soil or DEFAULT_RANGE
    s = saturation(sm, soil)
    factor = band_factor(s)
    applied = enabled and factor < 1.0
    if sm is None:
        state = "no_reading"
    elif not enabled:
        state = "off"
    elif applied:
        state = "applied"
    else:
        state = "below_threshold"
    return {
        "moisture_root": sm,
        "saturation": s,
        "dry": rng.dry,
        "wet": rng.wet,
        "range_source": rng.source,
        "calibrated": soil is not None,
        "factor": factor if applied else 1.0,
        "factor_if_on": factor,
        "enabled": enabled,
        "applied": applied,
        "state": state,
        "saturated_at": SATURATED_AT,
        "layers": list(LAYERS),
    }


def rule_tag(info: dict[str, Any]) -> str:
    return f"soil_saturated:S={info['saturation']:.2f}:bands x{info['factor']:.2f}"
