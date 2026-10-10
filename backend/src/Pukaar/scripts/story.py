"""Build the landing page's "night the river rose" data from the real rules.

Steps through the himachal_2023_07 replay for one village exactly as the
back-test does (same readings, same risk rules, same hysteresis) and records,
hour by hour, the rain the sweep would read, the river discharge it would read,
the levels of each source and the final level. Writes
frontend/src/data/story-gohar-2023.json, so the chart can never disagree with
data/backtest.json.

    cd backend && PYTHONPATH=src .venv/bin/python -m Pukaar.scripts.story
"""

from __future__ import annotations

import json
from pathlib import Path

from Pukaar.core import clock
from Pukaar.scripts.backtest import villages_from_files
from Pukaar.services import external_data, replay, risk_rules

SCENARIO, VILLAGE = "himachal_2023_07", "gohar"
OUT = Path(__file__).resolve().parents[4] / "frontend" / "src" / "data" / "story-gohar-2023.json"


def main() -> None:
    village = next(v for v in villages_from_files() if v.id == VILLAGE)
    sc = external_data.load_scenario(SCENARIO)
    level, calm = "normal", 0
    points = []
    for at in external_data.replay_hours(SCENARIO):
        reading = external_data.replay_reading(SCENARIO, village, at)
        if reading is None:
            continue
        a = risk_rules.assess(reading, village.thresholds, [], at)
        level, calm, _ = risk_rules.apply_hysteresis(level, calm, a.level)
        points.append({
            "at": clock.iso(at),
            "rain_24h_mm": reading.rain_24h_mm,
            "discharge": reading.discharge,
            "discharge_peak": reading.discharge_peak,
            "rain_level": a.rain_level,
            "river_level": a.river_level,
            "level": level,
            "rules": a.rules_fired,
        })
    row = next(r for r in replay.backtest(SCENARIO, [village]) if r["village_id"] == VILLAGE)
    out = {
        "village": village.name,
        "village_hi": village.name_hi,
        "district": village.district,
        "scenario": sc.get("title"),
        "scenario_hi": sc.get("title_hi"),
        "sources": sc.get("sources"),
        "imd_bands_mm": {"watch": 64.5, "warning": 115.6, "critical": 204.5},
        "discharge_thresholds": village.thresholds.model_dump() if village.thresholds else None,
        "points": points,
        "first": {"watch": row["first_watch"], "warning": row["first_warning"], "critical": row["first_critical"]},
        "peak_discharge_day": row["peak_discharge_day"],
        "lead_hours_watch_to_peak_day": row["lead_hours_watch_to_peak_day"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(OUT, len(points), "hours; first", out["first"])


if __name__ == "__main__":
    main()
