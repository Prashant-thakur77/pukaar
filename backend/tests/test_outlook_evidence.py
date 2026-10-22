"""Cycle 2: the get-ready outlook on the early line, the nowcast that follows the ensemble, the
back-test that reports both lead times, and the evidence the village page and sensors board serve."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from conftest import NOW

from Pukaar.api import pilot, views
from Pukaar.core import clock
from Pukaar.scripts import backtest as backtest_script
from Pukaar.services import agents as agents_svc
from Pukaar.services import external_data, replay
from Pukaar.services import risk_rules as rr
from Pukaar.services.nowcast import nowcast
from Pukaar.store.models import Reading, SensorReading, Thresholds

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
TH = Thresholds(watch=100.0, warning=150.0, critical=220.0, early=80.0, method="return_period",
                return_period_years={"watch": 2, "warning": 5, "critical": 20})


def ens(*days: list[float]) -> dict:
    return {"status": "ok", "members": len(days[0]), "run_date": "2026-07-01",
            "days": [{"date": f"2026-07-0{lead + 1}", "lead": lead, "values": sorted(v)} for lead, v in enumerate(days, 1)]}


def reading(*, today=50.0, forecast=None, ensemble=None, rain=None) -> Reading:
    fc = forecast or [today]
    return Reading(village_id="pandoh", at="2026-07-01T02:00:00Z", rain_24h_mm=0.0, discharge=today,
                   discharge_forecast=[{"date": f"2026-07-0{i + 1}", "value": q} for i, q in enumerate(fc)],
                   discharge_peak=max(fc), discharge_ensemble=ensemble,
                   rain_hourly=[{"t": f"h{i}", "mm": mm} for i, mm in enumerate(rain or [])])


# -- nowcast ----------------------------------------------------------------------------
def test_nowcast_follows_the_ensemble_and_counts_the_runs():
    # Day 2: 4 of 10 members over Warning (150), every member over Watch.
    members = [120] * 6 + [160] * 4
    n = nowcast(reading(forecast=[50, 90, 170], ensemble=ens([60] * 10, members)), TH, "normal")
    assert n["basis"] == "ensemble" and n["source"] == "river" and n["likely_level"] == "warning"
    assert (n["agree"], n["members"], n["p"]) == (4, 10, 0.4) and n["hours"] == 46
    assert "4 of 10 forecast runs" in n["text_en"] and "5-year flood level" in n["text_en"]
    assert n["text_en"].startswith("Warning possible") and "10 में से 4" in n["text_hi"]


def test_nowcast_never_hints_at_a_rise_the_ensemble_does_not_support():
    # The single forecast crosses Critical on day 1; only 2 of 10 members reach even Watch.
    quiet = ens([50] * 8 + [120, 300], [50] * 10, [50] * 10)
    assert nowcast(reading(forecast=[50, 300, 300], ensemble=quiet), TH, "normal") is None


def test_without_an_ensemble_the_line_says_single_forecast():
    n = nowcast(reading(forecast=[50, 90, 120]), TH, "normal")
    assert n["basis"] == "single_forecast" and n["likely_level"] == "watch" and n["p"] is None
    assert "single river forecast" in n["text_en"] and "एकल" in n["text_hi"]
    off = nowcast(reading(forecast=[50, 90, 120], ensemble={"status": "unavailable"}), TH, "normal")
    assert off["basis"] == "single_forecast"


def test_rain_nowcast_is_labelled_a_single_forecast():
    n = nowcast(reading(rain=[10.0] * 10), TH, "normal")
    assert n["source"] == "rain" and n["basis"] == "single_forecast" and n["hours"] == 7
    assert "rain forecast (a single forecast)" in n["text_en"]


# -- the ensemble keeps 7 lead days, the level reads 1-3 --------------------------------------
def test_parse_ensemble_keeps_lead_days_1_to_7_and_the_level_reads_only_1_to_3():
    times = [f"2026-07-{d:02d}" for d in range(1, 10)]
    daily = {"time": times, **{f"river_discharge_member{m:02d}": [10.0] * 4 + [500.0] * 5 for m in range(1, 51)}}
    out = external_data.parse_ensemble({"daily": daily}, "2026-07-01")
    assert [d["lead"] for d in out["days"]] == [1, 2, 3, 4, 5, 6, 7]
    r = reading(ensemble=out)
    a = rr.river_assessment(r, TH, p_min=0.3, use_ensemble=True)
    assert a["mode"] == "ensemble" and a["level"] == "normal"  # 500 on days 4-7 never sets a level
    assert [d["lead"] for d in a["days"]] == [1, 2, 3]


# -- back-test ------------------------------------------------------------------------------
def test_backtest_file_is_current_and_reports_both_lead_times():
    bt = json.loads((DATA / "backtest.json").read_text(encoding="utf-8"))
    truth = json.loads((DATA / "ground_truth.json").read_text(encoding="utf-8"))["scenarios"]
    villages = backtest_script.villages_from_files()
    for sc in bt["scenarios"]:
        fresh = backtest_script.with_truth(replay.backtest(sc["name"], villages), truth.get(sc["name"], {}))
        assert json.loads(json.dumps(fresh)) == sc["villages"], f"data/backtest.json is stale for {sc['name']}"
        for v in sc["villages"]:
            assert {"first_get_ready", "lead_hours_get_ready_to_peak_day", "get_ready_from_first_hour",
                    "first_watch", "lead_hours_watch_to_peak_day", "watch_from_first_hour"} <= set(v)


def test_pandoh_2023_get_ready_before_the_alert_and_the_alert_by_rain():
    rows = {r["village_id"]: r for r in replay.backtest("himachal_2023_07", backtest_script.villages_from_files())}
    p = rows["pandoh"]
    assert p["first_get_ready"] is not None and p["first_get_ready"] < p["first_watch"]
    assert p["lead_hours_watch_to_peak_day"] == 19.0
    assert p["lead_hours_get_ready_to_peak_day"] >= 48 and p["get_ready_from_first_hour"]
    # The outlook is evidence only: the Watch time is what the rules alone give.
    assert p["peak_discharge"] < p["thresholds"]["watch"]


def test_story_data_matches_the_backtest():
    story = json.loads((ROOT / "frontend" / "src" / "data" / "story-gohar-2023.json").read_text(encoding="utf-8"))
    bt = json.loads((DATA / "backtest.json").read_text(encoding="utf-8"))
    gohar = next(v for s in bt["scenarios"] if s["name"] == "himachal_2023_07" for v in s["villages"]
                 if v["village_id"] == "gohar")
    assert story["first"] == {"get_ready": gohar["first_get_ready"], "watch": gohar["first_watch"],
                              "warning": gohar["first_warning"], "critical": gohar["first_critical"]}
    assert story["lead_hours_watch_to_peak_day"] == gohar["lead_hours_watch_to_peak_day"]
    assert story["lead_hours_get_ready_to_peak_day"] == gohar["lead_hours_get_ready_to_peak_day"]
    assert story["discharge_thresholds"]["method"] == "return_period"


def test_pilot_metrics_carry_both_lead_times(repo, frozen):
    out = pilot.metrics(repo)["backtest"]
    sc = next(s for s in out["scenarios"] if s["name"] == "himachal_2023_07")
    p = next(v for v in sc["villages"] if v["village_id"] == "pandoh")
    assert p["lead_hours"] == 19.0 and not p["lead_is_lower_bound"]
    assert p["get_ready_lead_hours"] == 48.0 and p["get_ready_is_lower_bound"]
    assert sc["villages_get_ready"] == 5


# -- evidence served to the pages ---------------------------------------------------------------
def test_village_view_serves_ensemble_shares_not_member_values(repo, frozen):
    v = repo.get_village("pandoh")
    r = reading(forecast=[50, 90, 120], ensemble=ens([100.0] * 7 + [400.0] * 3, [50.0] * 10, [50.0] * 10))
    out = views.river_view(v, r)
    assert out["mode"] == "ensemble" and out["members"] == 10
    assert out["lead_days"][0]["p"]["watch"] == 0.3 and out["thresholds"]["early"] == v.thresholds.early
    assert out["thresholds"]["return_period_years"] == {"watch": 2, "warning": 5, "critical": 20}
    assert "values" not in json.dumps(out)
    assert views.river_view(v, None)["mode"] == "none"


def test_sensor_board_carries_quality_measured_and_health(repo, frozen):
    v = repo.get_village("gohar")
    for i in range(3):
        assert repo.put_sensor_reading(SensorReading(
            village_id="gohar", device_id=v.gauge.device_id, at=clock.iso(NOW - timedelta(minutes=6 - 2 * i)),
            water_level_cm=v.gauge.watch_cm + 5, battery_v=4.0, simulated=True, quality="good",
            measured_level="watch", confirmed_level="watch" if i else "normal", effective_level="watch",
            received_at=clock.iso(NOW - timedelta(minutes=6 - 2 * i))))
    g = next(r for r in agents_svc.sensors(repo)["villages"] if r["id"] == "gohar")
    assert g["latest"]["quality"] == "good" and g["latest"]["measured_level"] == "watch"
    assert g["measured_level"] == "watch" and g["rising_fast"] is False
    assert {"status", "reasons", "last_seen", "battery_v", "bad_share_24h"} <= set(g["health"])


def test_outlook_trace_item_is_evidence_only():
    from Pukaar.services import readiness

    r = reading()
    r.discharge_outlook = [{"date": f"2026-07-0{i + 1}", "value": 90.0} for i in range(8)]
    item = readiness.trace_item(readiness.outlook(r, TH))
    assert item["kind"] == "outlook" and item["never_sets_level"] is True and item["state"] == "get_ready"
    assert "level" not in item and item["early"] == 80.0 and item["basis"] == "single_forecast"
