"""Two-stage readiness: a soft "get ready" outlook days out, beside the hard levels.

Anticipatory action (Start Network, WFP Nepal, IFRC forecast-based financing) uses a soft trigger
days ahead to prepare and a hard trigger close in to act. Here the hard trigger is the level set by
risk_rules (Watch at the 2-year discharge). The soft trigger is this outlook: "Get ready: the river
is forecast to run high" when the river flow forecast for any day 1 to 7 days ahead of the reading
reaches the village's early line.

The early line (Thresholds.early, `early_cms` in data/thresholds.json) is the 90th percentile of
daily discharge at the village's river cell: the statistic the old Watch line used. It is crossed
for weeks in most monsoons, which is why it is an outlook and not an alert. Without an early line
the Watch discharge is used (`line` says which).

The flow for each day is the ensemble median when that day's ensemble is available (fetched once a
day, lead days 1-7), else the single deterministic forecast. `basis` says which, so a page never
calls a single forecast an ensemble.

It never creates an alert, never sends and never changes a level. Officers and pradhans see it on
the village page and the console with the early-action checklist; decision_engine puts it in the
decision trace as an "outlook" evidence item.
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import Any

from Pukaar.store.models import Reading, Thresholds

FIRST_DAY, LAST_DAY = 1, 7
SOURCE = "Open-Meteo flood API (GloFAS) daily river discharge forecast, days 1-7"


def _ensemble_medians(reading: Reading) -> dict[str, float]:
    """Median member discharge per forecast date, from the reading's daily ensemble (status ok only)."""
    ens = reading.discharge_ensemble or {}
    if ens.get("status") != "ok":
        return {}
    out = {}
    for day in ens.get("days") or []:
        values = [float(v) for v in day.get("values") or [] if v is not None]
        if values and day.get("date"):
            out[str(day["date"])[:10]] = statistics.median(values)
    return out


def outlook(reading: Reading | None, thresholds: Thresholds | None) -> dict[str, Any]:
    early = thresholds.early if thresholds and thresholds.early and thresholds.early > 0 else None
    watch = thresholds.watch if thresholds else None
    line = early if early is not None else watch
    base: dict[str, Any] = {"state": "none", "horizon_days": None, "peak_day": None, "peak_vs_watch_ratio": None,
                            "peak_vs_early_ratio": None, "peak_discharge": None, "watch": watch, "early": early,
                            "line": "early" if early is not None else "watch", "basis": None,
                            "first_day_over": None, "days_over": 0, "reaches_watch": False,
                            "source": SOURCE, "window_days": [FIRST_DAY, LAST_DAY], "days": [],
                            "never_sets_level": True,
                            "from_reading": reading.at if reading else None,
                            "replay": bool(reading.replay) if reading else False}
    if reading is None or thresholds is None or not line or line <= 0:
        return {**base, "available": False}
    today = date.fromisoformat(reading.at[:10])
    medians = _ensemble_medians(reading)
    days = []
    for point in reading.discharge_outlook:
        try:
            d = date.fromisoformat(str(point["date"])[:10])
            q = float(point["value"])
        except (KeyError, TypeError, ValueError):
            continue
        ahead = (d - today).days
        if FIRST_DAY <= ahead <= LAST_DAY:
            median = medians.get(d.isoformat())
            value, basis = (median, "ensemble_median") if median is not None else (q, "single_forecast")
            days.append({"date": d.isoformat(), "days_ahead": ahead, "value": round(value, 3), "basis": basis,
                         "single_forecast": q, "over": value >= line})
    if not days:
        return {**base, "available": False}
    peak = max(days, key=lambda p: p["value"])
    over = [p for p in days if p["over"]]
    bases = {p["basis"] for p in days}
    return {
        **base,
        "available": True,
        "state": "get_ready" if over else "none",
        "horizon_days": over[0]["days_ahead"] if over else None,
        "first_day_over": over[0]["date"] if over else None,
        "days_over": len(over),
        "reaches_watch": bool(watch) and peak["value"] >= watch,  # type: ignore[operator]
        "peak_day": peak["date"],
        "peak_discharge": peak["value"],
        "peak_vs_watch_ratio": round(peak["value"] / watch, 2) if watch else None,
        "peak_vs_early_ratio": round(peak["value"] / early, 2) if early else None,
        "basis": bases.pop() if len(bases) == 1 else "mixed",
        "days": days,
    }


def trace_item(out: dict[str, Any]) -> dict[str, Any]:
    """The outlook as a decision-trace evidence item: evidence only, never a level."""
    keep = ("state", "available", "line", "early", "watch", "basis", "horizon_days", "first_day_over", "days_over",
            "peak_day", "peak_discharge", "peak_vs_early_ratio", "reaches_watch", "window_days", "source")
    return {"kind": "outlook", "at": out.get("from_reading"), "never_sets_level": True,
            **{k: out.get(k) for k in keep}}
