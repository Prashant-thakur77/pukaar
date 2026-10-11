"""Score the back-test against ground truth, and ablate the data sources.

Same code path as backtest.py: the archived hours of each replay scenario go
through risk_rules.assess and the production hysteresis. Three configurations:

  rain only       level = assessment.rain_level
  river only      level = assessment.river_level
  both (Pukaar)   level = assessment.level (rain + river, +1 when both agree)

Each runs through the same hysteresis. Against data/ground_truth.json:

  hit          truth = event and Watch reached by the end of the event day (UTC)
  miss         truth = event and no Watch by then
  false alarm  truth = no_event and Warning reached at any time
  lead hours   event day 00:00 UTC minus first Watch, for hits (median)

Villages marked "uncertain" are left out. Writes data/scores.json and a copy
for the Impact page at frontend/src/data/scores.json.

    python -m Pukaar.scripts.score
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.scripts.backtest import villages_from_files
from Pukaar.services import external_data, risk_rules
from Pukaar.store.models import level_rank

CONFIGS = (("rain", "rain only"), ("river", "river only"), ("both", "both (Pukaar)"))
LEVELS_TRACKED = ("watch", "warning", "critical")


def raw_levels(scenario: str, village) -> list[tuple[datetime, dict[str, str]]]:
    """Per archived hour, the raw level each configuration would set."""
    out = []
    for at in external_data.replay_hours(scenario):
        reading = external_data.replay_reading(scenario, village, at)
        if reading is None:
            continue
        a = risk_rules.assess(reading, village.thresholds, [], at)
        out.append((at, {"rain": a.rain_level, "river": a.river_level, "both": a.level}))
    return out


def first_times(series: list[tuple[datetime, str]]) -> dict[str, datetime | None]:
    """First time each level is held, after the production hysteresis."""
    first: dict[str, datetime | None] = {lvl: None for lvl in LEVELS_TRACKED}
    level, calm = "normal", 0
    for at, raw in series:
        level, calm, _ = risk_rules.apply_hysteresis(level, calm, raw)
        for lvl in LEVELS_TRACKED:
            if first[lvl] is None and level_rank(level) >= level_rank(lvl):
                first[lvl] = at
    return first


def judge(first: dict[str, datetime | None], truth: dict) -> dict:
    """One village, one configuration: hit / miss / false_alarm / correct_quiet, plus lead hours."""
    kind = truth["truth"]
    if kind == "event":
        day = datetime.fromisoformat(truth["event_day"]).replace(tzinfo=timezone.utc)
        watch = first["watch"]
        if watch is not None and watch < day + timedelta(days=1):
            return {"result": "hit", "lead_hours": round((day - watch).total_seconds() / 3600, 1)}
        return {"result": "miss", "lead_hours": None}
    if kind == "no_event":
        return {"result": "false_alarm" if first["warning"] is not None else "correct_quiet", "lead_hours": None}
    return {"result": "uncertain", "lead_hours": None}


def tally(judged: list[dict]) -> dict:
    leads = [j["lead_hours"] for j in judged if j["result"] == "hit"]
    return {
        "hits": sum(j["result"] == "hit" for j in judged),
        "misses": sum(j["result"] == "miss" for j in judged),
        "false_alarms": sum(j["result"] == "false_alarm" for j in judged),
        "correct_quiet": sum(j["result"] == "correct_quiet" for j in judged),
        "scored": sum(j["result"] != "uncertain" for j in judged),
        "median_lead_hours": statistics.median(leads) if leads else None,
    }


def score_scenario(scenario: str, villages, truth: dict) -> dict:
    per_village = []
    by_config: dict[str, list[dict]] = {key: [] for key, _ in CONFIGS}
    for v in villages:
        t = truth.get(v.id, {"truth": "uncertain"})
        raw = raw_levels(scenario, v)
        row = {"village_id": v.id, "village": v.name, "truth": t["truth"], "event_day": t.get("event_day")}
        for key, _ in CONFIGS:
            first = first_times([(at, levels[key]) for at, levels in raw])
            j = judge(first, t)
            by_config[key].append(j)
            row[key] = {**j, "first_watch": clock.iso(first["watch"]) if first["watch"] else None,
                        "first_warning": clock.iso(first["warning"]) if first["warning"] else None,
                        # Watch already held at the first archived hour: the lead is a lower bound.
                        "watch_at_window_start": bool(raw) and first["watch"] == raw[0][0]}
        per_village.append(row)
    configs = []
    for key, label in CONFIGS:
        censored = any(r[key]["result"] == "hit" and r[key]["watch_at_window_start"] for r in per_village)
        configs.append({"key": key, "label": label, **tally(by_config[key]), "lead_is_lower_bound": censored})
    return {"configs": configs,
            "villages": per_village}


def run(data_dir: Path, villages=None) -> dict:
    gt = json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))
    villages = villages if villages is not None else villages_from_files()
    result = {"rules": risk_rules.RULES_VERSION, "ground_truth": "data/ground_truth.json", "scenarios": []}
    for name in external_data.list_scenarios():
        truth = gt["scenarios"].get(name, {})
        sc = external_data.load_scenario(name)
        result["scenarios"].append({"name": name, "title": sc.get("title"), "title_hi": sc.get("title_hi"),
                                    **score_scenario(name, villages, truth)})
    return result


def print_table(result: dict) -> None:
    print(f"{'scenario':<18} {'config':<15} {'hits':>4} {'miss':>4} {'FA':>4} {'scored':>6} {'median lead h':>13}")
    for s in result["scenarios"]:
        for c in s["configs"]:
            lead = "-" if c["median_lead_hours"] is None else f"{c['median_lead_hours']:g}"
            print(f"{s['name']:<18} {c['label']:<15} {c['hits']:>4} {c['misses']:>4} {c['false_alarms']:>4} "
                  f"{c['scored']:>6} {lead:>13}")


def main() -> None:
    s = get_settings()
    result = run(s.data_dir)
    body = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    (s.data_dir / "scores.json").write_text(body, encoding="utf-8")
    web = s.data_dir.parent / "frontend" / "src" / "data"
    if web.is_dir():
        (web / "scores.json").write_text(body, encoding="utf-8")
    print_table(result)


if __name__ == "__main__":
    main()
