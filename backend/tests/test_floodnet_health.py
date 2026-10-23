"""FloodNet-style device health (services/devices/floodnet.py): a battery that empties within a week at its slope,
more than 20% packet loss from the sequence numbers, and a value stuck while it rains. Each is a reason in
registry.health and in a gauge's own health, and shows on /how#sensors and in the console."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from Pukaar.core import clock
from Pukaar.services import gauge
from Pukaar.services.devices import floodnet, registry
from Pukaar.store.models import Device, Reading, SensorReading

NOW = datetime(2026, 7, 1, 2, 0, tzinfo=timezone.utc)


def _falling(hours=48, start=3700.0, per_day=-50.0, every=2):
    return [(NOW - timedelta(hours=h), start + per_day * (hours - h) / 24) for h in range(hours, -1, -every)]


def test_a_falling_battery_gives_days_to_empty():
    trend = floodnet.battery_trend(_falling(), 3500.0, NOW)
    assert trend["slope_per_day"] == -50.0 and trend["days_to_empty"] == 2.0 and trend["unit"] == "mv"
    sig = floodnet.signals(now=NOW, battery=_falling(), empty=3500.0)
    assert sig["reasons"] == ["battery_empty_in_2d"]
    # Slow: 30 days to empty is not a visit yet. Rising (a sunny week) never is.
    assert floodnet.signals(now=NOW, battery=_falling(per_day=-5.0), empty=3500.0)["reasons"] == []
    assert floodnet.signals(now=NOW, battery=_falling(per_day=20.0), empty=3500.0)["reasons"] == []


def test_too_few_or_too_close_samples_say_nothing():
    assert floodnet.battery_trend(_falling()[:3], 3500.0, NOW) is None
    short = [(NOW - timedelta(minutes=m), 3700.0 - m) for m in range(0, 300, 30)]  # 4.5 h only
    assert floodnet.battery_trend(short, 3500.0, NOW) is None
    assert floodnet.signals(now=NOW)["reasons"] == []  # nothing measured, nothing claimed


def test_packet_loss_from_sequence_numbers_per_boot():
    seqs = [(1, s) for s in range(1, 30) if s % 3]  # 1..29 with every third missing: 20 of 29
    loss = floodnet.packet_loss(seqs)
    assert loss == {"expected": 29, "received": 20, "loss": 0.31}
    assert floodnet.signals(now=NOW, seqs=seqs)["reasons"] == ["packet_loss_31pct"]
    # A reboot starts a new count: two clean runs are no loss.
    two = [(1, s) for s in range(100, 120)] + [(2, s) for s in range(1, 15)]
    assert floodnet.packet_loss(two)["loss"] == 0.0
    # Under 10 expected: too few to judge.
    assert floodnet.packet_loss([(1, 1), (1, 5)])["loss"] is None
    assert floodnet.signals(now=NOW, seqs=[(1, s) for s in range(1, 21) if s % 7])["reasons"] == []  # 15% < 20%


def test_a_stuck_value_counts_only_while_it_rains():
    values = [41.0, 40.2, 52.3, 52.3, 52.3, 52.3, 52.3, 52.3]
    assert floodnet.stuck_run(values) == 6
    assert floodnet.signals(now=NOW, values=values, raining=True)["reasons"] == ["stuck_6_readings"]
    assert floodnet.signals(now=NOW, values=values, raining=False)["reasons"] == []
    assert floodnet.stuck_run([1.0, 2.0, 3.0]) == 1 and floodnet.stuck_run([]) == 0


def test_signals_make_an_ok_device_degraded_and_add_to_other_states():
    d = Device(device_id="siren-x-1", village_id="thunag", kind="siren", last_seen=clock.iso(NOW - timedelta(minutes=2)),
               soc=90, last_test_silent={"at": clock.iso(NOW - timedelta(days=1)), "ok": True})
    assert registry.health(d, NOW) == ("ok", [])
    state, reasons = registry.health(d, NOW, {"reasons": ["battery_empty_in_3d"]})
    assert state == "degraded" and reasons == ["battery_empty_in_3d"]
    off = d.model_copy(update={"last_seen": clock.iso(NOW - timedelta(hours=2))})
    assert registry.health(off, NOW, {"reasons": ["battery_empty_in_0d"]}) == ("offline", ["silent_120_min",
                                                                                          "battery_empty_in_0d"])


def test_heartbeats_keep_an_hourly_battery_history_and_it_gives_the_slope(repo):
    d = Device(device_id="siren-hist-1", village_id="thunag", kind="siren")
    repo.put_device(d)
    for h in range(48, -1, -1):  # every hour for two days, falling 1% an hour... and two heartbeats in one hour
        at = clock.iso(NOW - timedelta(hours=h))
        cur = repo.get_device(d.device_id)
        registry.apply_heartbeat(repo, cur, {"soc": 90 - (48 - h), "batt_mv": 3900}, at)
        registry.apply_heartbeat(repo, repo.get_device(d.device_id), {"soc": 90 - (48 - h)},
                                 clock.iso(NOW - timedelta(hours=h) + timedelta(minutes=20)))
    stored = repo.get_device(d.device_id)
    assert len(stored.batt_hist) == 49  # one point an hour
    sig = registry.device_signals(repo, stored, NOW + timedelta(minutes=20))
    assert sig["battery"]["unit"] == "soc" and sig["battery"]["slope_per_day"] == -24.0
    assert sig["reasons"] == ["battery_empty_in_1d"]  # 42% left, 10% is empty, 24% a day
    view = registry.view(stored, NOW + timedelta(minutes=20), signals=sig, public=True)
    assert "batt_hist" not in view and view["health_signals"]["battery"]["days_to_empty"] == 1.3
    assert "battery_empty_in_1d" in view["health_reasons"]
    assert floodnet.append_history([], "2026-07-01T00:00:00Z", None, None) == []


def _gauge_rows(repo, seqs, level=40.0, battery=3.9):
    for i, s in enumerate(seqs):
        at = clock.iso(NOW - timedelta(minutes=5 * (len(seqs) - i)))
        repo.put_sensor_reading(SensorReading(village_id="thunag", device_id="gauge-thunag-sim", at=at, received_at=at,
                                              water_level_cm=level, seq=s, boot=1, battery_v=battery), min_interval_s=0)


def test_a_gauge_with_lost_packets_and_a_stuck_level_in_rain(repo, frozen):
    _gauge_rows(repo, [s for s in range(1, 41) if s % 2])  # every second reading lost
    repo.put_reading(Reading(village_id="thunag", at=clock.iso(NOW), rain_24h_mm=30.0))  # moderate rain
    d = repo.get_device("gauge-thunag-sim")
    sig = registry.device_signals(repo, d, NOW)
    assert sig["packet_loss"]["loss"] == 0.487 and "packet_loss_49pct" in sig["reasons"]
    assert sig["stuck"]["run"] >= 6 and sig["raining"] is True and any(r.startswith("stuck_") for r in sig["reasons"])
    h = gauge.view(repo, repo.get_village("thunag"))["health"]
    assert h["unhealthy"] and "packet_loss_49pct" in h["reasons"] and any(r.startswith("stuck_") for r in h["reasons"])
    assert h["signals"]["packet_loss"]["expected"] == 39


def test_a_steady_river_in_dry_weather_is_not_stuck(repo, frozen):
    _gauge_rows(repo, list(range(1, 21)))
    repo.put_reading(Reading(village_id="thunag", at=clock.iso(NOW), rain_24h_mm=2.0))
    sig = registry.device_signals(repo, repo.get_device("gauge-thunag-sim"), NOW)
    assert sig["reasons"] == [] and sig["stuck"]["run"] == 20 and sig["raining"] is False
