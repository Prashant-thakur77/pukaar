"""Back-test the risk rules on every replay scenario.

For each village: the first time each level was reached (the alert), the first get-ready outlook
(services/readiness.py; evidence only, never an alert), the day of peak discharge, and the lead
time of each to the peak day and, where data/ground_truth.json has one, to the event day. Reports
whatever the data shows, including "never crossed". Writes data/backtest.json (also served to the
Impact and Pilot pages).

    python -m Pukaar.scripts.backtest
"""

from __future__ import annotations

import json

from Pukaar.core.config import get_settings
from Pukaar.services import external_data, replay, risk_rules
from Pukaar.store.models import SoilRange, Thresholds, Village


def villages_from_files() -> list[Village]:
    s = get_settings()
    cfg = json.loads((s.data_dir / "villages.json").read_text(encoding="utf-8"))
    th = json.loads((s.data_dir / "thresholds.json").read_text(encoding="utf-8"))
    out = []
    for v in cfg["villages"]:
        t = th.get(v["id"])
        out.append(Village(id=v["id"], name=v["name"], name_hi=v["name_hi"], district=v["district"], lat=v["lat"],
                           lon=v["lon"], thresholds=Thresholds.from_file(t) if t else None,
                           soil=SoilRange.model_validate(t["soil"]) if t and t.get("soil") else None))
    return out


def with_truth(rows: list[dict], truth: dict) -> list[dict]:
    """Add the ground truth and, for a verified event, the lead of the outlook and of the alert to the event day."""
    for r in rows:
        t = truth.get(r["village_id"], {})
        r["truth"] = t.get("truth", "uncertain")
        r["event_day"] = t.get("event_day")
        r["lead_hours_get_ready_to_event"] = replay._hours_before(r["event_day"], r["first_get_ready"])
        r["lead_hours_watch_to_event"] = replay._hours_before(r["event_day"], r["first_watch"])
    return rows


def _fmt(h: float | None, lower_bound: bool) -> str:
    return "-" if h is None else f"{'>=' if lower_bound else ''}{h:g} h"


def main() -> None:
    s = get_settings()
    villages = villages_from_files()
    truth_path = s.data_dir / "ground_truth.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8")).get("scenarios", {}) if truth_path.exists() else {}
    result = {"rules": risk_rules.RULES_VERSION,
              "outlook": "get-ready: river forecast (ensemble median, else the single forecast) for day 1-7 at or "
                         "over early_cms, the 90th percentile of daily discharge at the river cell; never an alert",
              "burst_rule": "rain_intensity: the highest 1-, 3- and 6-hour totals of the next 24 forecast hours "
                            f"(models {', '.join(s.rain_models)}, combined by {s.rain_models_combine}) against "
                            + ", ".join(f"{d} h {mm:g} mm" for d, mm in risk_rules.BURST_WINDOWS_MM.items())
                            + " (no 1 h window on a large river); Watch, or Warning with a 24-hour band or "
                              "saturated soil",
              "scenarios": []}
    for name in external_data.list_scenarios():
        sc = external_data.load_scenario(name)
        rows = with_truth(replay.backtest(name, villages), truth.get(name, {}))
        result["scenarios"].append({"name": name, "title": sc.get("title"), "title_hi": sc.get("title_hi"),
                                    "start": sc["start"], "end": sc["end"], "sources": sc.get("sources"), "villages": rows})
        print(f"\n{sc.get('title')}")
        for r in rows:
            print(f"  {r['village']:<10} {r['outcome']:<16} get-ready={r['first_get_ready']} "
                  f"({_fmt(r['lead_hours_get_ready_to_peak_day'], r['get_ready_from_first_hour'])} to peak day) "
                  f"watch={r['first_watch']} ({_fmt(r['lead_hours_watch_to_peak_day'], r['watch_from_first_hour'])}) "
                  f"warning={r['first_warning']} critical={r['first_critical']} peak={r['peak_discharge']} on "
                  f"{r['peak_discharge_day']} max rain 24h={r['max_rain_24h_mm']} mm "
                  f"max burst={r['max_burst_mm']} first burst={r['first_burst']} truth={r['truth']}")
    (s.data_dir / "backtest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
