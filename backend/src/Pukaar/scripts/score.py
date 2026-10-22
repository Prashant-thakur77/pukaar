"""Score the back-test against ground truth, and ablate the data sources.

Same code path as backtest.py: the archived hours of each replay scenario go
through risk_rules.assess and the production hysteresis. Four configurations:

  rain only       level = assessment.rain_level
  river only      level = assessment.river_level
  both (Pukaar)   level = assessment.level (rain + river, +1 when both agree)
  both + soil     the same, with the soil-moisture modifier on the rain bands
                  (services/soil.py; archived soil in data/replay/*/soil.json)

The first three always run with the soil modifier off, whatever the setting,
so they stay comparable with earlier scores.

Each runs through the same hysteresis. Against data/ground_truth.json:

  hit          truth = event and Watch reached by the end of the event day (UTC)
  miss         truth = event and no Watch by then
  false alarm  truth = no_event and Warning reached at any time
  lead hours   event day 00:00 UTC minus first Watch, for hits (median)

Villages marked "uncertain" are left out. Writes data/scores.json and a copy
for the Impact page at frontend/src/data/scores.json.

    python -m Pukaar.scripts.score          # writes the files, prints the table
    python -m Pukaar.scripts.score --soil   # also prints the with/without soil comparison per village
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Pukaar.core import clock
from Pukaar.core.config import DEFAULT_RAIN_MODELS, get_settings
from Pukaar.scripts.backtest import villages_from_files
from Pukaar.services import external_data, risk_rules
from Pukaar.store.models import level_rank

CONFIGS = (("rain", "rain only"), ("river", "river only"), ("both", "both (Pukaar)"), ("both_soil", "both + soil"))
# The heavy-burst rule (risk_rules.rain_intensity), before and after, kept apart from CONFIGS so the
# Impact page's four configurations keep their meaning ("rain" now includes the burst rule).
BURST_CONFIGS = (
    ("rain_24h", "24 h rain only (before)"),
    ("burst", "heavy burst only (3 models, max)"),
    ("both_before", "both, without the burst rule (before)"),
    ("both_best_match", "both, burst on best_match alone"),
    ("both", "both (Pukaar): burst on 3 models, max"),
    ("both_models_mean", "both, burst on 3 models, mean"),
)
# The shipped default (core.config.DEFAULT_RAIN_MODELS, combine "max"), fixed here so the scores never
# depend on the PUKAAR_RAIN_MODELS setting of the machine that runs them.
MULTI_MODELS = DEFAULT_RAIN_MODELS
LEVELS_TRACKED = ("watch", "warning", "critical")


def _replay(scenario: str, village, at: datetime, models: tuple[str, ...]):
    return external_data.replay_reading(scenario, village, at, models=models)


def raw_levels(scenario: str, village, soil_out: list | None = None,
               burst_out: list | None = None) -> list[tuple[datetime, dict[str, str]]]:
    """Per archived hour, the raw level each configuration would set.

    soil_out, when given, collects the soil saturation S per hour (None when no archived value).
    burst_out, when given, collects the heavy-burst evidence per hour.
    Every configuration reads the shipped default (MULTI_MODELS, combine "max") except both_best_match
    and both_models_mean, and the replay archive's best_match alone gives the 24-hour sum.
    """
    out = []
    for at in external_data.replay_hours(scenario):
        reading = _replay(scenario, village, at, MULTI_MODELS)
        if reading is None:
            continue
        single = _replay(scenario, village, at, ("best_match",))

        def run(r, soil_on=False, burst_on=True, combine="max"):
            return risk_rules.assess(r, village.thresholds, [], at, soil=village.soil, soil_modifier=soil_on,
                                     rain_intensity_on=burst_on, rain_combine=combine)

        a, s, b = run(reading), run(reading, soil_on=True), run(reading, burst_on=False)
        bm, mn = run(single), run(reading, combine="mean")
        out.append((at, {"rain": a.rain_level, "river": a.river_level, "both": a.level, "both_soil": s.level,
                         "rain_24h": a.rain_24h_level, "burst": a.rain_intensity_level, "both_before": b.level,
                         "both_best_match": bm.level, "both_models_mean": mn.level}))
        if soil_out is not None:
            info = next((e for e in s.evidence if e.get("kind") == "soil"), None)
            soil_out.append(info["saturation"] if info else None)
        if burst_out is not None:
            burst_out.append((at, next((e for e in a.evidence if e.get("kind") == "rain_intensity"), None)))
    return out


def _event_end(truth: dict) -> datetime:
    """The end of the event day (UTC): a hit needs Watch before it (judge)."""
    return datetime.fromisoformat(truth["event_day"]).replace(tzinfo=timezone.utc) + timedelta(days=1)


def burst_peaks(burst: list, until: datetime | None = None) -> dict:
    """The highest 1-, 3- and 6-hour forecast totals per model, and when; only forecasts made before `until`."""
    peaks: dict = {}
    for at, ev in burst:
        if until is not None and at >= until:
            continue
        for model, maxima in (ev or {}).get("models", {}).items():
            for d, mm in maxima.items():
                if mm is None:
                    continue
                cur = peaks.setdefault(model, {}).get(d)
                if cur is None or mm > cur["mm"]:
                    peaks[model][d] = {"mm": mm, "forecast_at": clock.iso(at)}
    return peaks


def held_levels(series: list[tuple[datetime, str]]) -> list[str]:
    """The level held each hour after the production hysteresis."""
    held, level, calm = [], "normal", 0
    for _, raw in series:
        level, calm, _ = risk_rules.apply_hysteresis(level, calm, raw)
        held.append(level)
    return held


def soil_effect(village, raw: list[tuple[datetime, dict[str, str]]], sat: list, truth: dict) -> dict:
    """What the soil modifier changed for one village, scored or not: first times and hours at each level.

    Uncertain villages are included on purpose: with no village verified as quiet, extra Warning
    hours there are the only sign of a possible false alarm.
    """
    row: dict = {"village_id": village.id, "village": village.name, "truth": truth.get("truth", "uncertain"),
                 "max_saturation": max((x for x in sat if x is not None), default=None),
                 "hours_saturated": sum(1 for x in sat if x is not None and x >= 0.8),
                 "hours_with_soil": sum(1 for x in sat if x is not None)}
    for key in ("both", "both_soil"):
        series = [(at, levels[key]) for at, levels in raw]
        first = first_times(series)
        held = held_levels(series)
        row[key] = {**{f"first_{lvl}": clock.iso(t) if t else None for lvl, t in first.items()},
                    **{f"hours_{lvl}_or_above": sum(1 for h in held if level_rank(h) >= level_rank(lvl))
                       for lvl in LEVELS_TRACKED}}
    row["changed"] = row["both"] != row["both_soil"]
    return row


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


def _judged_row(raw, key: str, t: dict) -> dict:
    first = first_times([(at, levels[key]) for at, levels in raw])
    j = judge(first, t)
    return {**j, "first_watch": clock.iso(first["watch"]) if first["watch"] else None,
            "first_warning": clock.iso(first["warning"]) if first["warning"] else None,
            # Watch already held at the first archived hour: the lead is a lower bound.
            "watch_at_window_start": bool(raw) and first["watch"] == raw[0][0]}


def _configs(spec, per_village: list[dict]) -> list[dict]:
    out = []
    for key, label in spec:
        judged = [r[key] for r in per_village]
        censored = any(j["result"] == "hit" and j["watch_at_window_start"] for j in judged)
        out.append({"key": key, "label": label, **tally(judged), "lead_is_lower_bound": censored})
    return out


def score_scenario(scenario: str, villages, truth: dict) -> dict:
    per_village, burst_rows = [], []
    effects = []
    for v in villages:
        t = truth.get(v.id, {"truth": "uncertain"})
        sat: list = []
        burst: list = []
        raw = raw_levels(scenario, v, sat, burst)
        effects.append(soil_effect(v, raw, sat, t))
        row = {"village_id": v.id, "village": v.name, "truth": t["truth"], "event_day": t.get("event_day")}
        for key, _ in CONFIGS:
            row[key] = _judged_row(raw, key, t)
        per_village.append(row)
        brow = {"village_id": v.id, "village": v.name, "truth": t["truth"], "event_day": t.get("event_day"),
                "forecast_peaks_mm": burst_peaks(burst),
                "forecast_peaks_by_event_end_mm": burst_peaks(burst, _event_end(t)) if t.get("event_day") else None}
        for key, _ in BURST_CONFIGS:
            brow[key] = _judged_row(raw, key, t)
        burst_rows.append(brow)
    return {"configs": _configs(CONFIGS, per_village),
            "villages": per_village,
            "soil_effect": effects,
            "burst": {"configs": _configs(BURST_CONFIGS, burst_rows), "villages": burst_rows}}


# -- the burst rule's burden: 2019-2024 hourly forecast history (scripts/fetch_replay.py --history) ----
# A perfect-forecast estimate: at every hour the next 24 archived hours stand in for the forecast,
# exactly as the replay does, and go through the same functions as the sweep (rain_level on the
# 24-hour sum, rain_intensity on the hours). Soil is off, as in production.
BURDEN_SETS = (
    # (key, label, models, combine, years)
    ("best_match", "best_match, 2019-2024", ("best_match",), "max", tuple(range(2019, 2025))),
    ("best_match_2023_2024", "best_match, 2023-2024", ("best_match",), "max", (2023, 2024)),
    ("models_max", "3 models (max), 2023-2024", MULTI_MODELS, "max", (2023, 2024)),
    ("models_mean", "3 models (mean), 2023-2024", MULTI_MODELS, "mean", (2023, 2024)),
)


def _load_history(data_dir: Path, village_id: str, model: str, years) -> tuple[list[str], list[float | None]] | None:
    times: list[str] = []
    values: list[float | None] = []
    for year in years:
        p = data_dir / ".cache" / "rain_history" / f"{village_id}_{model}_{year}.json"
        if not p.exists():
            return None
        body = json.loads(p.read_text(encoding="utf-8"))
        times += body["time"]
        values += [None if x is None else float(x) for x in body["precipitation"]]
    return times, values


class _Hours:
    """Just what risk_rules.rain_intensity reads from a Reading (pydantic is slow for 50,000 hours)."""

    def __init__(self, hourly, models):
        self.rain_hourly, self.rain_models = hourly, models


def burden_one(village, series: dict[str, tuple[list[str], list]], combine: str,
               windows_mm: dict[int, float] | None = None) -> dict:
    """Days a year at Watch and Warning, and rises to Watch, before (24-hour bands) and after (with bursts)."""
    times, primary = series["best_match"]
    per_year: dict[str, dict] = {}
    held = {"before": "normal", "after": "normal"}
    calm = {"before": 0, "after": 0}
    seen: set[tuple[str, str, str]] = set()
    for i in range(len(times)):
        window = primary[i:i + 24]
        r24 = round(sum(window), 1) if len(window) == 24 and all(x is not None for x in window) else None
        lvl_24 = risk_rules.rain_level(r24)
        hourly = [{"t": times[j], "mm": primary[j]} for j in range(i, min(i + 24, len(times))) if primary[j] is not None]
        others = {m: [{"t": times[j], "mm": vals[j]} for j in range(i, min(i + 24, len(times))) if vals[j] is not None]
                  for m, (_, vals) in series.items() if m != "best_match"}
        info = risk_rules.rain_intensity(_Hours(hourly, others), village.thresholds, lvl_24, None, combine, windows_mm)  # type: ignore[arg-type]
        levels = {"before": lvl_24, "after": risk_rules._max(lvl_24, info["level"]), "burst": info["level"]}
        year, day = times[i][:4], times[i][:10]
        y = per_year.setdefault(year, {f"{k}_{lvl}_days": 0 for k in ("before", "after", "burst")
                                       for lvl in ("watch", "warning")} | {"before_rises": 0, "after_rises": 0})
        for k, lvl in levels.items():
            for tracked in ("watch", "warning"):
                if level_rank(lvl) >= level_rank(tracked) and (k, tracked, day) not in seen:
                    seen.add((k, tracked, day))
                    y[f"{k}_{tracked}_days"] += 1
        for k in ("before", "after"):
            new, calm[k], rose = risk_rules.apply_hysteresis(held[k], calm[k], levels[k])
            if rose and held[k] == "normal":
                y[f"{k}_rises"] += 1
            held[k] = new
    n = len(per_year) or 1
    mean = {k: round(sum(y[k] for y in per_year.values()) / n, 1) for k in next(iter(per_year.values()), {})}
    return {"per_year": per_year, "mean": mean, "years": len(per_year)}


def burst_burden(data_dir: Path, villages, windows_mm: dict[int, float] | None = None, sets=BURDEN_SETS) -> dict:
    out: dict = {"method": "perfect forecast from the Open-Meteo historical-forecast archive (next 24 archived "
                           "hours at every hour), the same rain_level and rain_intensity as the sweep, soil off; "
                           "a day counts when any of its hours is at the level; rises go through the production "
                           "hysteresis",
                 "windows_mm": {str(d): mm for d, mm in (windows_mm or risk_rules.BURST_WINDOWS_MM).items()},
                 "sets": {}}
    for key, label, models, combine, years in sets:
        rows = []
        for v in villages:
            series = {m: _load_history(data_dir, v.id, m, years) for m in models}
            if any(s is None for s in series.values()):
                continue
            rows.append({"village_id": v.id, "village": v.name,
                         **burden_one(v, series, combine, windows_mm)})  # type: ignore[arg-type]
        out["sets"][key] = {"label": label, "models": list(models), "combine": combine, "years": list(years),
                            "villages": rows}
    return out


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


def print_soil(result: dict) -> None:
    print("\nSoil modifier: Pukaar rules without and with it, every village (uncertain ones too)")
    print(f"{'scenario':<18} {'village':<10} {'truth':<9} {'max S':>5} {'h S>=.8':>7}  "
          f"{'first watch (off -> on)':<45} {'first warning (off -> on)':<45} {'h >= warning':>12}")
    for s in result["scenarios"]:
        for e in s.get("soil_effect", []):
            ms = "-" if e["max_saturation"] is None else f"{e['max_saturation']:.2f}"
            fw = f"{e['both']['first_watch']} -> {e['both_soil']['first_watch']}"
            fwa = f"{e['both']['first_warning']} -> {e['both_soil']['first_warning']}"
            hw = f"{e['both']['hours_warning_or_above']} -> {e['both_soil']['hours_warning_or_above']}"
            print(f"{s['name']:<18} {e['village']:<10} {e['truth']:<9} {ms:>5} {e['hours_saturated']:>7}  "
                  f"{fw:<45} {fwa:<45} {hw:>12}")


def needed_to_catch(result: dict) -> dict | None:
    """The burst thresholds, scaled down together, that would have caught every missed event village
    with the highest model's forecast before the end of its event day. A diagnostic, never a setting:
    it is reported with its burden (burst_burden_sensitivity) to show what a hit would have cost."""
    factors = []
    for sc in result["scenarios"]:
        for v in sc.get("burst", {}).get("villages", []):
            if v["truth"] != "event" or v["both"]["result"] == "hit":
                continue
            by_model = (v.get("forecast_peaks_by_event_end_mm") or {}).values()
            peaks = {d: max(p[d]["mm"] for p in by_model if d in p)
                     for d in {d for p in by_model for d in p}}
            ratios = [peaks[d] / mm for d, mm in ((str(k), x) for k, x in risk_rules.BURST_WINDOWS_MM.items())
                      if d in peaks]
            if not ratios:
                return None
            factors.append(max(ratios))
    if not factors:
        return None
    f = min(factors)
    return {"factor": round(f, 3),
            "windows_mm": {str(d): math.floor(mm * f * 10) / 10 for d, mm in risk_rules.BURST_WINDOWS_MM.items()}}


SENSITIVITY_SETS = (BURDEN_SETS[0], BURDEN_SETS[2])


def sensitivity(data_dir: Path, villages, result: dict) -> dict:
    out: dict = {}
    alt = {"dh_x027": {"label": "Dahal-Hasegawa curve x 0.27 (1 h 20, 3 h 25, 6 h 30 mm)",
                       "windows_mm": {1: 20.0, 3: 25.0, 6: 30.0}}}
    need = needed_to_catch(result)
    if need is not None:
        alt["needed_2025"] = {"label": f"what the 2025 misses would have needed (x{need['factor']:g})",
                              "windows_mm": {int(d): mm for d, mm in need["windows_mm"].items()}}
    for key, spec in alt.items():
        b = burst_burden(data_dir, villages, spec["windows_mm"], SENSITIVITY_SETS)
        out[key] = {"label": spec["label"], **b}
    return out


def print_burst(result: dict) -> None:
    print("\nHeavy-burst rule: before and after, per scenario")
    for s in result["scenarios"]:
        for c in s.get("burst", {}).get("configs", []):
            lead = "-" if c["median_lead_hours"] is None else f"{c['median_lead_hours']:g}"
            print(f"{s['name']:<18} {c['label']:<40} hits {c['hits']} miss {c['misses']} lead {lead}")
    for key, block in (("burst_burden", result.get("burst_burden")),
                       *((f"sensitivity:{k}", v) for k, v in (result.get("burst_burden_sensitivity") or {}).items())):
        if not block:
            continue
        print(f"\n{key}: windows {block['windows_mm']}")
        for name, st in block["sets"].items():
            for v in st["villages"]:
                m = v["mean"]
                print(f"  {name:<22} {v['village']:<10} watch days {m['before_watch_days']} -> {m['after_watch_days']} "
                      f"(burst {m['burst_watch_days']}), warning days {m['before_warning_days']} -> "
                      f"{m['after_warning_days']}, rises {m['before_rises']} -> {m['after_rises']}")


def main() -> None:
    s = get_settings()
    result = run(s.data_dir)
    previous = s.data_dir / "scores.json"
    if "--history" in sys.argv[1:]:
        villages = villages_from_files()
        result["burst_burden"] = burst_burden(s.data_dir, villages)
        result["burst_burden_sensitivity"] = sensitivity(s.data_dir, villages, result)
    elif previous.exists():
        # The history is not in git (data/.cache): keep the last computed burden.
        old = json.loads(previous.read_text(encoding="utf-8"))
        for key in ("burst_burden", "burst_burden_sensitivity"):
            if key in old:
                result[key] = old[key]
    body = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    (s.data_dir / "scores.json").write_text(body, encoding="utf-8")
    web = s.data_dir.parent / "frontend" / "src" / "data"
    if web.is_dir():
        (web / "scores.json").write_text(body, encoding="utf-8")
    print_table(result)
    if "--soil" in sys.argv[1:]:
        print_soil(result)
    print_burst(result)


if __name__ == "__main__":
    main()
