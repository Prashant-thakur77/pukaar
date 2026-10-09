"""Nowcast line: "likely <level> in about N hours", from the stored forecast.

Uses only the reading's own forecast series; returns None when nothing in the
forecast reaches a higher level.
"""

from __future__ import annotations

from datetime import datetime

from Pukaar.core import clock
from Pukaar.services.risk_rules import rain_level, river_level
from Pukaar.store.models import Reading, Thresholds, level_rank
from Pukaar.templates import hi


def nowcast(reading: Reading | None, thresholds: Thresholds | None, current: str) -> dict | None:
    if reading is None:
        return None
    at = clock.parse(reading.at)
    best: tuple[str, float] | None = None

    total = 0.0
    for i, point in enumerate(reading.rain_hourly):
        total += float(point.get("mm") or 0.0)
        lvl = rain_level(total)
        if level_rank(lvl) > level_rank(current):
            best = (lvl, float(i + 1))
            break

    for point in reading.discharge_forecast:
        lvl = river_level(point.get("value"), thresholds)
        if level_rank(lvl) > level_rank(current):
            day = datetime.fromisoformat(point["date"]).replace(tzinfo=at.tzinfo)
            hours = max(0.0, (day - at).total_seconds() / 3600.0)
            if best is None or level_rank(lvl) > level_rank(best[0]) or hours < best[1]:
                best = (lvl, hours)
            break

    if best is None:
        return None
    lvl, hours = best
    h = max(1, round(hours))
    return {
        "likely_level": lvl,
        "hours": h,
        "text_en": f"Likely {hi.LEVEL_EN[lvl]} in about {h} hours (from the forecast in reading {reading.at}).",
        "text_hi": f"लगभग {h} घंटों में {hi.LEVEL_HI[lvl]} की संभावना (पूर्वानुमान के अनुसार)।",
        "replay": reading.replay,
    }
