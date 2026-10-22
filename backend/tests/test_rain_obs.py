"""Observed rain (services/rain_obs.py, risk_rules.observed_rain): a tipping bucket as a level source that
only raises, needs 2 of the last 3 evaluations, stops at Warning on its own, is one source with the forecast,
and ignores stuck, chattering, simulated and backfilled buckets. Every series here is SYNTHETIC.
"""

from __future__ import annotations

from datetime import timedelta

from Pukaar.core import clock
from Pukaar.handlers import gauge_ingest
from Pukaar.services import cap, rain_obs, risk_rules
from Pukaar.services.decision_engine import recompute_village
from Pukaar.store.models import Alert, Device, RainGaugeConfig, Reading, SensorReading

NODE = "rain-gohar-01"


def node(repo, device=NODE, village="gohar", simulated=False):
    repo.put_device(Device(device_id=device, village_id=village, kind="rain", installed=True, simulated=simulated,
                           created_at=clock.iso(clock.now())))


def feed(repo, frozen, rates_mm_h, *, device=NODE, village="gohar", step_min=5.0, start_total=1000, origin="live",
         simulated=False, extra=None):
    """One reading per step at each rate (mm/h), the clock moving with them. Returns the stored readings."""
    v = repo.get_village(village)
    total, out = start_total, []
    cfg = rain_obs.config(v)
    for i, rate in enumerate(rates_mm_h):
        frozen["now"] = frozen["now"] + timedelta(minutes=step_min)
        tips = round(rate * step_min / 60 / cfg.mm_per_tip)
        total += tips
        fields = rain_obs.RainFields(at=clock.iso(frozen["now"]), rain_tips_total=total, rain_tips_window=tips,
                                     seq=int(frozen["now"].timestamp()), boot=1, simulated=simulated, **(extra or {}))
        r = rain_obs.ingest(repo, v, device, fields, frozen["now"], now=frozen["now"], transport="mqtt", origin=origin,
                            source="rain_node")
        out.append(r)
    return out


def assess(repo, frozen, village="gohar", reading=None, sensor=None, **kw):
    v = repo.get_village(village)
    info = rain_obs.village_info(repo, v, frozen["now"], forecast=reading)
    return risk_rules.assess(reading, v.thresholds, [], frozen["now"], sensor=sensor, gauge=v.gauge, soil_modifier=False,
                             rain_intensity_on=False, rain_obs=info, **kw)


def test_the_correction_formula():
    cfg = RainGaugeConfig()
    assert cfg.correction_c == 0.0005 and cfg.i0_mm_h == 50
    # 150 mm/h for 5 minutes = 12.5 mm raw; +5 % at 150 mm/h (c x (150 - 50))
    assert round(12.5 * (1 + cfg.correction_c * (150 - cfg.i0_mm_h)), 4) == 13.125


def test_counter_differences_across_a_gap_and_a_reset(repo, frozen):
    v = repo.get_village("gohar")
    f = rain_obs.RainFields
    t0 = frozen["now"]
    a = rain_obs.ingest(repo, v, NODE, f(at=clock.iso(t0), rain_tips_total=100, rain_tips_window=5), t0, now=t0,
                        transport="mqtt")
    assert a.tips == 5 and a.minutes == 5.0  # the first reading: its own window over the usual 5 minutes
    t1 = t0 + timedelta(minutes=20)  # a 20-minute gap: 40 tips spread over the 20 minutes
    b = rain_obs.ingest(repo, v, NODE, f(at=clock.iso(t1), rain_tips_total=140, rain_tips_window=10), t1, now=t1,
                        transport="mqtt")
    assert b.tips == 40 and b.minutes == 20.0 and b.mm_raw == 8.0 and b.rate_mm_h == 24.0
    assert b.windows["15min"] == 6.0  # three quarters of the gap's rain falls in the last 15 minutes
    t2 = t1 + timedelta(minutes=5)  # the counter went backwards (a reboot): the window count is used
    c = rain_obs.ingest(repo, v, NODE, f(at=clock.iso(t2), rain_tips_total=3, rain_tips_window=3, rain_err=2), t2,
                        now=t2, transport="mqtt")
    assert c.tips == 3 and c.quality == "good"
    assert rain_obs.ingest(repo, v, NODE, f(at=clock.iso(t2), rain_tips_total=3, rain_tips_window=3), t2, now=t2,
                           transport="mqtt") is None  # the same reading again


def test_a_band_counts_in_two_of_the_last_three_evaluations(repo, frozen):
    node(repo)
    first = feed(repo, frozen, [300 * 0.99])[0]  # one heavy 5 minutes: 24.75 mm in 15 min, Warning band
    assert first.eval_level == "warning" and first.confirmed_level == "normal"
    a = assess(repo, frozen)
    assert a.rain_obs_level == "normal" and "rain_obs_unconfirmed:warning" in a.rules_fired
    second = feed(repo, frozen, [60])[0]
    assert second.eval_level == "warning" and second.confirmed_level == "warning"
    a = assess(repo, frozen)
    assert a.rain_obs_level == "warning" and a.level == "warning"
    assert any(r.startswith("rain_obs:15min=") and r.endswith(":warning") for r in a.rules_fired)
    assert next(e for e in a.evidence if e["kind"] == "rain_obs")["device_id"] == NODE


def test_observed_rain_alone_is_capped_at_warning(repo, frozen):
    node(repo)
    feed(repo, frozen, [120] * 12)  # an hour at 120 mm/h: twice the illustrative 1 h Warning band
    a = assess(repo, frozen)
    assert a.level == "warning" and a.rain_obs_level == "warning"
    assert "rain_obs_capped:warning" in a.rules_fired and "two_sources_agree:+1" not in a.rules_fired


def test_forecast_and_observed_rain_are_one_source_but_a_gauge_is_another(repo, frozen):
    node(repo)
    feed(repo, frozen, [120] * 3)
    v = repo.get_village("gohar")
    wet = Reading(village_id="gohar", at=clock.iso(frozen["now"]), rain_24h_mm=80.0)  # forecast: the Watch band
    a = assess(repo, frozen, reading=wet)
    assert a.rain_level == "watch" and a.rain_obs_level == "warning"
    assert "two_sources_agree:+1" not in a.rules_fired and a.level == "warning"
    g = v.gauge
    sensor = SensorReading(village_id="gohar", device_id=g.device_id, at=clock.iso(frozen["now"]),
                           water_level_cm=g.watch_cm + 5, effective_level="watch", confirmed_level="watch")
    a = assess(repo, frozen, sensor=sensor, allow_simulated=True)
    assert "two_sources_agree:+1" in a.rules_fired and a.level == "critical"


def test_a_stuck_bucket_is_suspect_and_changes_nothing(repo, frozen, capsys):
    node(repo)
    start = frozen["now"]
    feed(repo, frozen, [0] * 37)  # 3 h of readings, no tip at all
    hours = [{"t": clock.iso(start + timedelta(hours=h)), "mm": 8.0} for h in range(4)]
    repo.put_reading(Reading(village_id="gohar", at=clock.iso(frozen["now"]), rain_hourly=hours))
    a = assess(repo, frozen)
    assert "rain_obs_suspect:stuck" in a.rules_fired and a.rain_obs_level == "normal"
    assert '"RainGaugeSuspect"' in capsys.readouterr().out
    # dry forecast: not stuck, just a dry day
    frozen2 = {"now": frozen["now"]}
    repo.put_reading(Reading(village_id="gohar", at=clock.iso(frozen2["now"] + timedelta(seconds=1)),
                             rain_hourly=[{**h, "mm": 0.0} for h in hours]))
    assert "rain_obs_suspect:stuck" not in assess(repo, frozen).rules_fired


def test_chatter_is_suspect_and_never_counts(repo, frozen):
    node(repo)
    bouncy = feed(repo, frozen, [120, 120], extra={"rain_min_tip_ms": 120, "rain_bounce": 6})
    assert all(r.quality == "suspect" and any(q.startswith("chatter:min_tip") for q in r.quality_reasons)
               for r in bouncy)
    a = assess(repo, frozen)
    assert a.rain_obs_level == "normal" and "rain_obs_suspect:chatter" in a.rules_fired
    fast = feed(repo, frozen, [400], device="rain-gohar-02")[0]
    assert fast.quality == "suspect" and any(q.startswith("chatter:rate") for q in fast.quality_reasons)


def test_backfilled_rain_never_triggers(repo, frozen):
    node(repo)
    stored = feed(repo, frozen, [120] * 4, origin="backfill")
    assert all(r.origin == "backfill" for r in stored)
    assert rain_obs.village_info(repo, repo.get_village("gohar"), frozen["now"]) is None
    assert assess(repo, frozen).rain_obs_level == "normal"


def test_simulated_rain_is_shown_but_never_raises_a_live_village(repo, frozen):
    feed(repo, frozen, [120] * 4, device="gauge-gohar-sim", simulated=True)
    a = assess(repo, frozen)
    assert a.rain_obs_level == "normal" and a.level == "normal"
    assert "rain_obs_simulated_ignored:warning" in a.rules_fired
    view = rain_obs.view(repo, repo.get_village("gohar"))
    assert view["level"] == "normal" and view["simulated_level"] == "warning"


def test_rain_obs_driving_the_level_is_a_flash_flood_in_cap():
    a = Alert(id="alr_x", village_id="gohar", village_name="Gohar", village_name_hi="गोहर", level="warning",
              created_at="2026-07-01T02:00:00Z", updated_at="2026-07-01T02:00:00Z",
              decision_trace={"rain_level": "normal", "rain_obs_level": "warning", "river_level": "normal",
                              "gauge_level": "normal", "staff_level": "normal"})
    assert cap.is_flash_flood(a) and cap.event_code(a) == cap.OET_FLASH_FLOOD


def test_watch_or_above_re_evaluates_the_village_at_once(repo, frozen, workflow, monkeypatch):
    from Pukaar.workflow import client

    monkeypatch.setattr(client, "get_workflow", lambda: workflow)
    node(repo)
    out = None
    total = 5000
    for _ in range(3):
        frozen["now"] = frozen["now"] + timedelta(minutes=1, seconds=1)
        total += 25  # 5 mm a minute (300 mm/h, the plausible limit)
        out = gauge_ingest.handle({"village_id": "gohar", "device_id": NODE, "topic_kind": "reading",
                                   "at": clock.iso(frozen["now"]), "rain_tips_total": total, "rain_tips_window": 25,
                                   "v": 3, "seq": total, "boot": 1}, repo, frozen["now"])
    assert out["status"] == "accepted" and out["kind"] == "rain" and out["rain_level"] != "normal"
    assert repo.get_village("gohar").level in {"watch", "warning"} and workflow.started


def test_synthetic_mandi_30_june_2025_point_gauge_replay_raises_gohar_to_warning(repo, frozen, workflow, monkeypatch):
    """SYNTHETIC: no hourly gauge record exists for Seraj, Thunag or Gohar in the 2025 cloudbursts. A bucket in
    the upper catchment at 120 mm/h for 20 minutes, as a point gauge would have seen a cloudburst."""
    from Pukaar.workflow import client

    monkeypatch.setattr(client, "get_workflow", lambda: workflow)
    node(repo)
    feed(repo, frozen, [5, 10, 120, 120, 120, 120])
    v = repo.get_village("gohar")
    res = recompute_village(repo, v, now=frozen["now"], workflow=workflow)
    assert res.level == "warning" and res.alert_id
    trace = repo.get_alert(res.alert_id).decision_trace
    assert trace["rain_obs_level"] == "warning" and trace["schema"] == risk_rules.RULES_VERSION == "risk-rules-v4"
    assert any(r.startswith("rain_obs:") for r in trace["rules_fired"])


def test_a_rain_node_must_be_registered_for_its_village(repo, frozen):
    out = gauge_ingest.handle({"village_id": "gohar", "device_id": "rain-gohar-09", "topic_kind": "reading",
                               "at": clock.iso(frozen["now"]), "rain_tips_total": 1, "rain_tips_window": 1}, repo,
                              frozen["now"])
    assert out["status"] == "rejected" and out["code"] == "wrong_device"
