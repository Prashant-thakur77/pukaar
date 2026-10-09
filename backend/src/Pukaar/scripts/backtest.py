"""Back-test the risk rules on every replay scenario.

For each village: the first time each level was reached, the day of peak
discharge, and the lead time. Reports whatever the data shows, including
"never crossed". Writes data/backtest.json (also served to the Impact page).

    python -m Pukaar.scripts.backtest
"""

from __future__ import annotations

import json

from Pukaar.core.config import get_settings
from Pukaar.services import external_data, replay
from Pukaar.store.models import Thresholds, Village


def villages_from_files() -> list[Village]:
    s = get_settings()
    cfg = json.loads((s.data_dir / "villages.json").read_text(encoding="utf-8"))
    th = json.loads((s.data_dir / "thresholds.json").read_text(encoding="utf-8"))
    out = []
    for v in cfg["villages"]:
        t = th.get(v["id"])
        out.append(Village(id=v["id"], name=v["name"], name_hi=v["name_hi"], district=v["district"], lat=v["lat"],
                           lon=v["lon"], thresholds=Thresholds(watch=t["watch"], warning=t["warning"],
                                                               critical=t["critical"], source=t["source"]) if t else None))
    return out


def main() -> None:
    s = get_settings()
    villages = villages_from_files()
    result = {"rules": "risk-rules-v1", "scenarios": []}
    for name in external_data.list_scenarios():
        sc = external_data.load_scenario(name)
        rows = replay.backtest(name, villages)
        result["scenarios"].append({"name": name, "title": sc.get("title"), "title_hi": sc.get("title_hi"),
                                    "start": sc["start"], "end": sc["end"], "sources": sc.get("sources"), "villages": rows})
        print(f"\n{sc.get('title')}")
        for r in rows:
            print(f"  {r['village']:<10} {r['outcome']:<18} watch={r['first_watch']} warning={r['first_warning']} "
                  f"critical={r['first_critical']} peak={r['peak_discharge']} on {r['peak_discharge_day']} "
                  f"max rain 24h={r['max_rain_24h_mm']} mm")
    (s.data_dir / "backtest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
