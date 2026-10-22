"""Nowcast line: "<level> possible in about N hours", from the stored forecast.

River: when the day's GloFAS ensemble is available, only a level that at least p_min of the members
reach (the same cut-off that raises a level, risk_rules.ENSEMBLE_P_MIN) gives a line, worded with the
member count ("18 of 51 forecast runs ..."), so the line never hints at a rise the ensemble does not
support. Without an ensemble the deterministic forecast is used and the line says "single forecast".
Rain: the hourly rain forecast, always a single forecast, and labelled so.
Heavy burst (risk_rules.rain_intensity): "Heavy burst of rain possible in the next N hours (forecast)",
N being the hours until the end of the first burst window. Because the rule already raises the level
when the forecast shows a burst, this line is given while its level is at or above the current level
(the other lines need a higher level).

Returns None when nothing in the forecast reaches a higher level than the current one and no burst
is forecast.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.services.risk_rules import RIVER_LEVELS, rain_intensity, rain_level, river_assessment, river_level
from Pukaar.store.models import Reading, Thresholds, level_rank
from Pukaar.templates import hi

Candidate = dict[str, Any]


def _hours_until(day: str, at: datetime) -> float:
    start = datetime.fromisoformat(str(day)[:10]).replace(tzinfo=at.tzinfo)
    return max(0.0, (start - at).total_seconds() / 3600.0)


def _rain(reading: Reading, current: str) -> Candidate | None:
    total = 0.0
    for i, point in enumerate(reading.rain_hourly):
        total += float(point.get("mm") or 0.0)
        lvl = rain_level(total)
        if level_rank(lvl) > level_rank(current):
            return {"level": lvl, "hours": float(i + 1), "source": "rain", "basis": "single_forecast"}
    return None


def _burst(reading: Reading, thresholds: Thresholds | None, current: str) -> Candidate | None:
    if not get_settings().rain_intensity_enabled:
        return None
    info = rain_intensity(reading, thresholds, rain_level(reading.rain_24h_mm), None)
    if not info["burst"] or level_rank(info["level"]) < level_rank(current):
        return None
    first = min(info["hit"], key=lambda h: (h["start_hour"] + h["hours"], h["hours"]))
    models = sorted(info["models"])
    return {"level": info["level"], "hours": float(info["hours_to_end"]), "source": "rain_burst",
            "basis": "models" if len(models) > 1 else "single_forecast", "burst": first, "models": models,
            "combine": info["combine"]}


def _river(reading: Reading, thresholds: Thresholds | None, current: str, at: datetime) -> Candidate | None:
    if thresholds is None:
        return None
    info = river_assessment(reading, thresholds)
    if info["mode"] == "ensemble":
        # The earliest lead day on which a level above the current one reaches the cut-off; on that
        # day, the highest such level.
        for day in sorted(info.get("days") or [], key=lambda d: d["lead"]):
            above = [lvl for lvl in RIVER_LEVELS
                     if level_rank(lvl) > level_rank(current) and day["p"][lvl] >= info["p_min"]]
            if above:
                lvl = above[-1]
                p = day["p"][lvl]
                return {"level": lvl, "hours": _hours_until(day["date"], at), "source": "river", "basis": "ensemble",
                        "p": p, "members": day["members"], "agree": round(p * day["members"]), "lead_day": day["lead"]}
        return None
    for point in reading.discharge_forecast:
        lvl = river_level(point.get("value"), thresholds)
        if level_rank(lvl) > level_rank(current):
            return {"level": lvl, "hours": _hours_until(point["date"], at), "source": "river",
                    "basis": "single_forecast"}
    return None


def _years(thresholds: Thresholds | None, lvl: str) -> int | None:
    rp = (thresholds.return_period_years or {}) if thresholds else {}
    return rp.get(lvl)


def _text(c: Candidate, h: int, thresholds: Thresholds | None) -> tuple[str, str]:
    lvl = c["level"]
    en_level, hi_level = hi.LEVEL_EN[lvl], f"“{hi.LEVEL_HI[lvl]}” स्तर"
    if c["basis"] == "ensemble":
        word_en, word_hi = ("Likely", "की संभावना") if c["p"] >= 0.8 else ("Possible", "संभव")
        years = _years(thresholds, lvl)
        mark_en = f"its {years}-year flood level" if years else f"its {en_level.lower()} line"
        mark_hi = f"{years} साल वाले बाढ़-स्तर" if years else f"“{hi.LEVEL_HI[lvl]}” सीमा"
        return (f"{en_level} {word_en.lower()} in about {h} hours: {c['agree']} of {c['members']} forecast runs "
                f"take the river past {mark_en}.",
                f"लगभग {h} घंटों में {hi_level} {word_hi}: {c['members']} में से {c['agree']} पूर्वानुमान-रन नदी को "
                f"{mark_hi} से ऊपर दिखाते हैं।")
    if c["source"] == "rain_burst":
        b = c["burst"]
        hrs_en = "1 hour" if b["hours"] == 1 else f"{b['hours']} hours"
        n = len(c["models"])
        if c["basis"] != "models":
            src_en, src_hi = "a single forecast", "एकल पूर्वानुमान"
        elif c["combine"] == "mean":
            src_en, src_hi = f"the mean of {n} forecast models", f"{n} पूर्वानुमान-मॉडलों का औसत"
        else:
            src_en, src_hi = f"the highest of {n} forecast models", f"{n} पूर्वानुमान-मॉडलों में सबसे ऊँचा"
        return (f"Heavy burst of rain possible in the next {h} hours (forecast): up to {b['mm']:g} mm in {hrs_en} "
                f"({src_en}). Level: {en_level}.",
                f"अगले {h} घंटों में भारी बारिश का तेज़ दौर संभव (पूर्वानुमान): {b['hours']} घंटे में {b['mm']:g} मिमी तक "
                f"({src_hi})। स्तर: “{hi.LEVEL_HI[lvl]}”।")
    if c["source"] == "river":
        return (f"{en_level} in about {h} hours on the single river forecast (no ensemble to check it).",
                f"नदी के एकल पूर्वानुमान के अनुसार लगभग {h} घंटों में {hi_level} (जाँचने को एन्सेम्बल नहीं)।")
    return (f"{en_level} in about {h} hours on the rain forecast (a single forecast).",
            f"बारिश के एकल पूर्वानुमान के अनुसार लगभग {h} घंटों में {hi_level}।")


def nowcast(reading: Reading | None, thresholds: Thresholds | None, current: str) -> dict | None:
    if reading is None:
        return None
    at = clock.parse(reading.at)
    found = [c for c in (_rain(reading, current), _river(reading, thresholds, current, at),
                         _burst(reading, thresholds, current)) if c]
    if not found:
        return None
    # The higher level first; at the same level, the sooner one.
    best = min(found, key=lambda c: (-level_rank(c["level"]), c["hours"]))
    h = max(1, round(best["hours"]))
    text_en, text_hi = _text(best, h, thresholds)
    return {
        "likely_level": best["level"],
        "hours": h,
        "source": best["source"],
        "basis": best["basis"],
        "p": best.get("p"),
        "members": best.get("members"),
        "agree": best.get("agree"),
        "burst": best.get("burst"),
        "text_en": text_en,
        "text_hi": text_hi,
        "from_reading": reading.at,
        "replay": reading.replay,
    }
