"""The heavy-burst rule (risk_rules.rain_intensity): rolling 1/3/6-hour maxima of the hourly forecast,
the thresholds, the one-level cap, the combination with the 24-hour total and soil, several forecast
models, the CAP event code, the nowcast wording, and that the back-test and scores reproduce."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from Pukaar.core import config
from Pukaar.core.ids import new_id
from Pukaar.scripts import backtest as backtest_script
from Pukaar.scripts import score
from Pukaar.services import cap, decision_engine, external_data
from Pukaar.services import risk_rules as rr
from Pukaar.services.nowcast import nowcast
from Pukaar.store.models import Alert, Reading, Thresholds, Village

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
T0 = datetime(2026, 7, 1, 2, tzinfo=timezone.utc)
KHAD = Thresholds(watch=1.4, warning=2.0, critical=2.7, method="return_period")  # a small steep catchment
BEAS = Thresholds(watch=366.0, warning=445.0, critical=546.0, method="return_period")  # a large river
SATURATED = {"enabled": True, "saturation": 0.9}
DRY = {"enabled": True, "saturation": 0.3}


def hours(mm: list[float | None], start: datetime = T0) -> list[dict]:
    return [{"t": (start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00"), "mm": x} for i, x in enumerate(mm)]


def reading(mm: list[float | None], *, rain_24h: float | None = None, models: dict | None = None,
            peak: float | None = None) -> Reading:
    known = [x for x in mm if x is not None]
    return Reading(village_id="thunag", at=T0.isoformat(), rain_24h_mm=sum(known) if rain_24h is None else rain_24h,
                   rain_hourly=[p for p in hours(mm) if p["mm"] is not None],
                   rain_models={m: [p for p in hours(v) if p["mm"] is not None] for m, v in (models or {}).items()},
                   discharge=peak, discharge_peak=peak)


def burst(mm, th=KHAD, rain_24h_level="normal", soil=None, combine="max", models=None) -> dict:
    return rr.rain_intensity(reading(mm, models=models), th, rain_24h_level, soil, combine)


# -- rolling maxima -----------------------------------------------------------------------------
def test_rolling_maxima_find_the_highest_window_and_when():
    series = [0, 1, 2, 18, 3, 0, 0, 10, 10, 10, 0] + [0] * 13
    m = rr.rolling_maxima(series)
    assert m[1] == {"mm": 18, "start": 3, "complete": True}
    assert m[3]["mm"] == 30 and m[3]["start"] == 7
    assert m[6]["mm"] == 41 and m[6]["start"] == 3 and m[6]["complete"]


def test_rolling_maxima_read_only_the_next_24_hours():
    m = rr.rolling_maxima([0.0] * 24 + [99.0])
    assert m[1]["mm"] == 0 and m[6]["mm"] == 0


def test_a_missing_hour_is_unknown_and_the_window_a_lower_bound():
    m = rr.rolling_maxima([5.0, None, 5.0] + [0.0] * 21)
    assert m[3] == {"mm": 10.0, "start": 0, "complete": False}
    assert rr.rolling_maxima([None] * 24)[1]["mm"] is None


def test_hours_are_placed_by_their_time_not_their_position():
    # Two hours 5 hours apart are never one 3-hour window, even when the gap was dropped from the list.
    pts = [{"t": "2026-07-01T02:00", "mm": 30.0}, {"t": "2026-07-01T07:00", "mm": 30.0}]
    series = rr._hour_series(pts)
    assert series[0] == 30.0 and series[5] == 30.0 and series[1] is None
    assert rr.rolling_maxima(series)[3]["mm"] == 30.0


# -- thresholds -----------------------------------------------------------------------------------
@pytest.mark.parametrize("mm,level", [
    ([19.9] + [0] * 23, "normal"),
    ([20.0] + [0] * 23, "watch"),            # 1 h >= 20 mm
    ([15.0, 15.0, 14.9] + [0] * 21, "normal"),
    ([15.0, 15.0, 15.0] + [0] * 21, "watch"),  # 3 h >= 45 mm
    ([8.3] * 6 + [0] * 18, "normal"),          # 49.8 mm in 6 h
    ([0] * 18 + [8.4] * 6, "watch"),           # 50.4 mm in 6 h, at the end of the 24 hours
    ([5.0] * 24, "normal"),                    # steady rain is not a burst, however long
])
def test_burst_thresholds(mm, level):
    assert burst(mm)["level"] == level


def test_a_large_river_does_not_read_the_one_hour_window():
    one_hour = [25.0] + [0] * 23
    assert burst(one_hour, KHAD)["level"] == "watch"
    big = burst(one_hour, BEAS)
    assert big["level"] == "normal" and big["catchment"] == "large_river" and "1" not in big["windows_mm"]
    assert burst([25.0, 25.0] + [0] * 22, BEAS)["level"] == "watch"  # 50 mm in 3 h still counts


# -- the one-level cap and the combination ---------------------------------------------------------
def test_a_burst_alone_raises_one_level_and_never_more():
    cloudburst = [150.0] + [0] * 23  # IMD's cloudburst rate itself
    info = burst(cloudburst)
    assert info["level"] == "watch" and info["reason"] is None


def test_a_burst_on_a_heavy_day_or_saturated_ground_is_warning():
    mm = [25.0] + [0] * 23
    assert burst(mm, rain_24h_level="watch")["level"] == "warning"
    assert burst(mm, rain_24h_level="watch")["reason"] == "24h"
    assert burst(mm, soil=SATURATED)["level"] == "warning"
    assert burst(mm, soil=SATURATED)["reason"] == "soil"
    assert burst(mm, soil=DRY)["level"] == "watch"
    # Soil counts only when the soil modifier is on (default off, docs/SCORING.md).
    assert burst(mm, soil={"enabled": False, "saturation": 1.0})["level"] == "watch"
    # Never above Warning, whatever the 24-hour band says.
    assert burst(mm, rain_24h_level="critical")["level"] == "warning"


def test_assess_takes_the_higher_of_the_24h_bands_and_the_burst():
    burst_only = rr.assess(reading([30.0] + [0] * 23), KHAD, [], T0, soil_modifier=False, rain_intensity_on=True)
    assert (burst_only.rain_24h_level, burst_only.rain_intensity_level, burst_only.rain_level) == ("normal", "watch", "watch")
    assert burst_only.level == "watch"
    assert any(r == "rain_intensity:1h=30>=20mm:watch" for r in burst_only.rules_fired)
    ev = next(e for e in burst_only.evidence if e["kind"] == "rain_intensity")
    assert ev["maxima"]["1"]["mm"] == 30.0 and ev["hit"][0]["hours"] == 1

    heavy_day = rr.assess(reading([30.0, 20.0, 20.0] + [0] * 21), KHAD, [], T0, soil_modifier=False,
                          rain_intensity_on=True)  # 70 mm in 24 h: the IMD heavy band
    assert (heavy_day.rain_24h_level, heavy_day.rain_intensity_level) == ("watch", "warning")
    assert heavy_day.level == "warning" and any("+rain_24h:warning" in r for r in heavy_day.rules_fired)

    very_heavy = rr.assess(reading([30.0] + [5.0] * 23), KHAD, [], T0, soil_modifier=False, rain_intensity_on=True,
                           )  # 145 mm: the 24-hour band alone is Warning; the burst adds nothing on top
    assert very_heavy.rain_level == "warning" and very_heavy.level == "warning"


def test_the_burst_is_rain_and_rain_is_one_source():
    # A burst (rain) and the river at Watch are two sources: the usual +1, no more.
    a = rr.assess(reading([30.0] + [0] * 23, peak=1.5), KHAD, [], T0, soil_modifier=False, rain_intensity_on=True)
    assert a.rain_level == "watch" and a.river_level == "watch" and a.level == "warning"
    assert a.rules_fired.count("two_sources_agree:+1") == 1


def test_switched_off_the_rule_changes_nothing():
    a = rr.assess(reading([30.0] + [0] * 23), KHAD, [], T0, soil_modifier=False, rain_intensity_on=False)
    assert a.level == "normal" and a.rain_intensity_level == "normal"
    assert not any(e["kind"] == "rain_intensity" for e in a.evidence)


def test_soil_enters_through_assess_only_when_the_modifier_is_on():
    from Pukaar.store.models import SoilRange

    r = reading([30.0] + [0] * 23)
    r.soil_moisture_root = 0.40
    rng = SoilRange(dry=0.2, wet=0.4)
    on = rr.assess(r, KHAD, [], T0, soil=rng, soil_modifier=True, rain_intensity_on=True)
    off = rr.assess(r, KHAD, [], T0, soil=rng, soil_modifier=False, rain_intensity_on=True)
    assert on.rain_intensity_level == "warning" and off.rain_intensity_level == "watch"


# -- several forecast models -----------------------------------------------------------------------
def test_models_combine_by_max_or_by_mean():
    quiet = [2.0] * 24
    loud = [24.0] + [0] * 23
    mx = burst(quiet, combine="max", models={"gfs_seamless": loud})
    assert mx["level"] == "watch" and mx["hit"][0]["model"] == "gfs_seamless"
    assert set(mx["models"]) == {"best_match", "gfs_seamless"}
    mean = burst(quiet, combine="mean", models={"gfs_seamless": loud})
    assert mean["level"] == "normal" and mean["maxima"]["1"]["mm"] == 13.0  # (2 + 24) / 2


def test_a_model_with_no_hours_is_left_out():
    info = burst([25.0] + [0] * 23, combine="mean", models={"icon_seamless": [None] * 24})
    assert set(info["models"]) == {"best_match"} and info["level"] == "watch"


def test_rain_models_setting_keeps_best_match_first_and_drops_unknown_names():
    assert config._rain_models("gfs_seamless,best_match,nonsense,icon_seamless") == (
        "best_match", "gfs_seamless", "icon_seamless")
    assert config._rain_models("") == ("best_match",)
    assert config.get_settings().rain_models == config.DEFAULT_RAIN_MODELS
    assert config.get_settings().rain_models_combine == "max"


def test_a_multi_model_response_is_split_into_best_match_and_the_others():
    body = {"time": ["2026-07-01T02:00", "2026-07-01T03:00"],
            "precipitation_best_match": [1.0, 2.0], "precipitation_gfs_seamless": [30.0, None],
            "precipitation_icon_seamless": [0.5, 0.5],
            "soil_moisture_9_to_27cm_best_match": [0.3, 0.3], "soil_moisture_27_to_81cm_best_match": [0.32, 0.32],
            "soil_moisture_9_to_27cm_gfs_seamless": [None, None]}
    primary, others = external_data.split_models(body, ("best_match", "icon_seamless", "gfs_seamless"))
    assert primary["precipitation"] == [1.0, 2.0] and primary["soil_moisture_27_to_81cm"] == [0.32, 0.32]
    assert others["gfs_seamless"] == [("2026-07-01T02:00", 30.0), ("2026-07-01T03:00", None)]
    # A single-model response is used as it is.
    plain = {"time": ["t"], "precipitation": [1.0]}
    assert external_data.split_models(plain, ("best_match",)) == (plain, {})


def test_replay_readings_carry_the_archived_models():
    v = next(x for x in backtest_script.villages_from_files() if x.id == "sujanpur")
    at = datetime(2023, 7, 8, tzinfo=timezone.utc)
    multi = external_data.replay_reading("himachal_2023_07", v, at, models=score.MULTI_MODELS)
    single = external_data.replay_reading("himachal_2023_07", v, at, models=("best_match",))
    assert set(multi.rain_models) == {"icon_seamless", "gfs_seamless"} and single.rain_models == {}
    assert multi.rain_24h_mm == single.rain_24h_mm  # the 24-hour sum reads best_match alone
    assert all(len(points) == 24 for points in multi.rain_models.values())


# -- CAP: a burst that sets the level is a flash flood ----------------------------------------------
def test_cap_calls_a_burst_alert_a_flash_flood():
    village = Village(id="thunag", name="Thunag", name_hi="थुनाग", district="Mandi", lat=31.56, lon=77.17,
                      thresholds=KHAD)
    r = reading([30.0] + [0] * 23, peak=0.5)
    a = rr.assess(r, KHAD, [], T0, soil_modifier=False, rain_intensity_on=True)
    trace = decision_engine.build_trace(village, r, a, "normal", a.level, 0, T0)
    alert = Alert(id=new_id("alr"), village_id="thunag", village_name="Thunag", village_name_hi="थुनाग",
                  level=a.level, previous_level="normal", status="delivered", created_at=T0.isoformat(),
                  updated_at=T0.isoformat(), decision_trace=trace, text_hi="x", text_en="x")
    assert trace["rain_level"] == "watch" and trace["river_level"] == "normal"
    assert cap.event_code(alert) == cap.OET_FLASH_FLOOD and cap.event_name(alert) == "Flash Flood"
    # The river at the same level as the burst: an ordinary flood.
    r2 = reading([30.0] + [0] * 23, peak=1.5)
    a2 = rr.assess(r2, KHAD, [], T0, soil_modifier=False, rain_intensity_on=True)
    alert2 = alert.model_copy(update={"decision_trace": decision_engine.build_trace(village, r2, a2, "normal", a2.level, 0, T0)})
    assert cap.event_code(alert2) == cap.OET_FLOOD


# -- nowcast wording ---------------------------------------------------------------------------------
def test_nowcast_says_a_heavy_burst_is_possible_in_the_next_n_hours():
    r = reading([0.0] * 4 + [26.0] + [0.0] * 19)
    n = nowcast(r, KHAD, "watch")  # the rule has already set Watch: the line still says why
    assert n["source"] == "rain_burst" and n["likely_level"] == "watch" and n["hours"] == 5
    assert n["text_en"].startswith("Heavy burst of rain possible in the next 5 hours (forecast)")
    assert "26 mm in 1 hour" in n["text_en"] and "a single forecast" in n["text_en"]
    assert n["text_hi"].startswith("अगले 5 घंटों में भारी बारिश का तेज़ दौर संभव (पूर्वानुमान)")
    assert n["burst"]["hours"] == 1


def test_nowcast_names_the_models_and_stays_quiet_above_the_burst_level():
    r = reading([1.0] * 24, models={"gfs_seamless": [0.0, 0.0, 30.0] + [0.0] * 21, "icon_seamless": [1.0] * 24})
    n = nowcast(r, KHAD, "normal")
    assert n["basis"] == "models" and "the highest of 3 forecast models" in n["text_en"] and n["hours"] == 3
    assert "3 पूर्वानुमान-मॉडलों में सबसे ऊँचा" in n["text_hi"]
    assert nowcast(reading([30.0] + [0] * 23), KHAD, "warning") is None


# -- the back-test reproduces -----------------------------------------------------------------------
def test_scores_file_is_current():
    stored = json.loads((DATA / "scores.json").read_text(encoding="utf-8"))
    fresh = score.run(DATA)
    assert stored["rules"] == rr.RULES_VERSION
    assert json.loads(json.dumps(fresh["scenarios"], ensure_ascii=False)) == stored["scenarios"], \
        "data/scores.json is stale: python -m Pukaar.scripts.score --history"


def test_backtest_names_the_burst_rule_and_the_2025_misses_stay_misses():
    bt = json.loads((DATA / "backtest.json").read_text(encoding="utf-8"))
    assert "rain_intensity" in bt["burst_rule"] and bt["rules"] == rr.RULES_VERSION
    mandi = next(s for s in bt["scenarios"] if s["name"] == "mandi_2025")
    for v in mandi["villages"]:
        if v["truth"] == "event":
            # The archived global forecasts never came near a burst at the villages that were hit.
            assert v["first_watch"] is None and v["first_burst"] is None
            assert max(v["max_burst_mm"].values()) < min(rr.BURST_WINDOWS_MM.values())


def test_scores_report_before_and_after_and_the_burden():
    sc = json.loads((DATA / "scores.json").read_text(encoding="utf-8"))
    for scenario in sc["scenarios"]:
        keys = [c["key"] for c in scenario["burst"]["configs"]]
        assert keys == [k for k, _ in score.BURST_CONFIGS]
    mandi = next(s for s in sc["scenarios"] if s["name"] == "mandi_2025")
    both = {c["key"]: c for c in mandi["burst"]["configs"]}
    assert (both["both"]["hits"], both["both"]["misses"]) == (0, 3)
    burden = sc["burst_burden"]
    assert burden["windows_mm"] == {str(d): mm for d, mm in rr.BURST_WINDOWS_MM.items()}
    assert {"best_match", "models_max", "models_mean"} <= set(burden["sets"])
    assert len(burden["sets"]["best_match"]["villages"]) == 5
    assert all(v["years"] == 6 for v in burden["sets"]["best_match"]["villages"])
    assert "needed_2025" in sc["burst_burden_sensitivity"]


def test_burden_counts_days_and_rises_through_the_same_rules():
    times = [(datetime(2030, 1, 1) + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(24 * 10)]
    values = [0.0] * len(times)
    values[24 * 5 + 12] = 30.0  # one burst, day 6 at noon
    v = Village(id="x", name="X", name_hi="x", district="T", lat=0, lon=0, thresholds=KHAD)
    out = score.burden_one(v, {"best_match": (times, values)}, "max")
    y = out["per_year"]["2030"]
    # Seen from day 5 noon (24 hours ahead) until the burst hour on day 6: two days at Watch.
    assert y["burst_watch_days"] == 2 and y["after_watch_days"] == 2 and y["before_watch_days"] == 0
    assert y["after_rises"] == 1 and y["before_rises"] == 0
