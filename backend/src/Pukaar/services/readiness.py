"""Two-stage readiness: a soft "get ready" outlook days out, beside the hard 24-hour levels.

Anticipatory action (Start Network, WFP Nepal, IFRC forecast-based financing)
uses a soft trigger days ahead to prepare and a hard trigger close in to act.
Here the hard trigger is the level set by risk_rules. The soft trigger is this
outlook: when any day 2 to 7 days ahead of the reading is forecast at or above
the village's Watch discharge threshold, the village is "get_ready".

It never sends an alert and never changes a level. Officers and pradhans see it
on the village page and the console, with the early-action checklist.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from Pukaar.store.models import Reading, Thresholds

FIRST_DAY, LAST_DAY = 2, 7
SOURCE = "Open-Meteo flood API (GloFAS) daily river discharge forecast, days 2-7"


def outlook(reading: Reading | None, thresholds: Thresholds | None) -> dict[str, Any]:
    base: dict[str, Any] = {"state": "none", "horizon_days": None, "peak_day": None, "peak_vs_watch_ratio": None,
                            "peak_discharge": None, "watch": thresholds.watch if thresholds else None,
                            "source": SOURCE, "window_days": [FIRST_DAY, LAST_DAY], "days": [],
                            "from_reading": reading.at if reading else None,
                            "replay": bool(reading.replay) if reading else False}
    if reading is None or thresholds is None or thresholds.watch <= 0:
        return {**base, "available": False}
    today = date.fromisoformat(reading.at[:10])
    days = []
    for point in reading.discharge_outlook:
        try:
            d = date.fromisoformat(str(point["date"])[:10])
            q = float(point["value"])
        except (KeyError, TypeError, ValueError):
            continue
        ahead = (d - today).days
        if FIRST_DAY <= ahead <= LAST_DAY:
            days.append({"date": d.isoformat(), "days_ahead": ahead, "value": q})
    if not days:
        return {**base, "available": False}
    peak = max(days, key=lambda p: p["value"])
    over = [p for p in days if p["value"] >= thresholds.watch]
    return {
        **base,
        "available": True,
        "state": "get_ready" if over else "none",
        "horizon_days": over[0]["days_ahead"] if over else None,
        "peak_day": peak["date"],
        "peak_discharge": round(peak["value"], 3),
        "peak_vs_watch_ratio": round(peak["value"] / thresholds.watch, 2),
        "days": days,
    }
