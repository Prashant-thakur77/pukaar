"""River gauge, field grade: the false-alarm guard, payload v2, backfill, rate of rise and health."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from conftest import NOW
from fastapi.testclient import TestClient
from Pukaar.core import clock
from Pukaar.handlers import gauge_ingest
from Pukaar.services import gauge
from Pukaar.services import risk_rules as rr
from Pukaar.store.models import GaugeConfig, Reading, SensorReading, Thresholds
from pydantic import ValidationError

DEV = "gauge-thunag-01"
SECRET = "test-link-secret-at-least-32-bytes-long"


@pytest.fixture()
def live(repo, frozen, workflow, monkeypatch):
    """thunag with real hardware registered (watch 120, warning 200, critical 280 cm)."""
    import Pukaar.workflow.client as wc

    monkeypatch.setattr(wc, "get_workflow", lambda: workflow)
    v = repo.get_village("thunag")
    repo.update_village("thunag", gauge=v.gauge.model_copy(update={"device_id": DEV}))
    return repo


def configure(repo, **cfg) -> GaugeConfig:
    g = repo.get_village("thunag").gauge.model_copy(update=cfg)
    repo.update_village("thunag", gauge=g)
    return g


def send(repo, minutes_ago: float, cm: float | None = None, device: str = DEV, **kw) -> gauge.IngestResult:
    fields = gauge.ReadingFields(at=clock.iso(NOW - timedelta(minutes=minutes_ago)), water_level_cm=cm, **kw)
    return gauge.ingest(repo, "thunag", device, fields, clock.parse(fields.at), now=NOW)


def stored(repo) -> list[SensorReading]:
    return repo.list_sensor_readings("thunag", clock.iso(NOW - timedelta(days=4)))


def gauge_audits(repo) -> list:
    return [a for a in repo.list_audit(NOW.date().isoformat()) if a.action == "gauge_level"]


# -- 2 of 3 confirmation --------------------------------------------------
def test_one_reading_at_warning_changes_nothing_two_of_the_last_three_do(live, workflow):
    first = send(live, 3, 210)
    assert (first.gauge_level, first.confirmed_level, first.effective_level) == ("warning", "normal", "normal")
    assert first.alert_id is None and workflow.started == [] and live.get_village("thunag").level == "normal"
    dip = send(live, 2, 100)  # 210, 100: still only one at a stage
    assert dip.effective_level == "normal" and workflow.started == []
    second = send(live, 1, 212)  # 210, 100, 212: two of the last three at warning
    assert second.confirmed_level == second.effective_level == "warning"
    assert second.alert_id and workflow.started == [second.alert_id]
    trace = live.get_alert(second.alert_id).decision_trace
    assert "gauge>=200cm:warning" in trace["rules_fired"] and trace["gauge_level"] == "warning"
    ev = next(e for e in trace["evidence"] if e["kind"] == "gauge")
    assert ev["confirmed_level"] == "warning" and ev["quality"] == "good"


def test_the_confirmation_window_is_the_last_three_good_fresh_readings():
    g = GaugeConfig(device_id=DEV, watch_cm=120, warning_cm=200, critical_cm=280)

    def r(cm):
        return SensorReading(village_id="thunag", device_id=DEV, at=clock.iso(NOW), water_level_cm=cm)

    assert gauge.confirmed([r(290), r(100), r(100)], g) == "normal"
    assert gauge.confirmed([r(290), r(290), r(100), r(100)], g) == "normal"  # only the last three count
    assert gauge.confirmed([r(290), r(210), r(100)], g) == "warning"  # both at or above warning
    assert gauge.confirmed([r(290), r(285)], g) == "critical"
    assert gauge.confirmed([r(290)], g) == "normal"


def test_stale_readings_do_not_confirm(live, workflow):
    send(live, 40, 230)  # older than the 30-minute freshness window
    out = send(live, 0, 231)
    assert out.confirmed_level == "normal" and workflow.started == []


# -- spikes ---------------------------------------------------------------
def test_a_spike_is_stored_flagged_and_never_counted(live, workflow):
    send(live, 3, 100)
    send(live, 2, 101)
    a = send(live, 1, 400)  # 299 cm in a minute: an echo off debris
    b = send(live, 0, 102)
    assert a.quality == "spike" and a.gauge_level == "critical" and a.effective_level == "normal"
    assert b.quality == "good"  # compared with the last good reading, not with the spike
    rows = stored(live)
    assert [r.quality for r in rows] == ["good", "good", "spike", "good"]
    assert rows[2].quality_reasons == ["rate>30cm/min"] and rows[2].water_level_cm == 400  # kept for officers
    assert all(r.effective_level == "normal" for r in rows) and workflow.started == []


def test_two_readings_in_a_row_that_agree_are_a_real_step(live):
    send(live, 3, 100)
    send(live, 2, 101)
    first = send(live, 1, 170)  # 69 cm/min: a spike on its own
    second = send(live, 0, 172)  # agrees with it: the river really stepped (a surge), so it counts
    assert first.quality == "spike" and second.quality == "good"


def test_spike_limit_is_per_gauge(live):
    configure(live, max_rise_cm_per_min=100)
    send(live, 1, 100)
    assert send(live, 0, 180).quality == "good"


def test_a_lone_spike_between_good_readings():
    g = GaugeConfig(device_id=DEV, watch_cm=120, warning_cm=200, critical_cm=280)
    hist = [SensorReading(village_id="t", device_id=DEV, at=clock.iso(NOW - timedelta(minutes=2)), water_level_cm=100)]
    up = SensorReading(village_id="t", device_id=DEV, at=clock.iso(NOW - timedelta(minutes=1)), water_level_cm=129)
    assert not gauge.is_spike(up, hist, g)  # 29 cm/min: fast, but possible
    up.water_level_cm = 140
    assert gauge.is_spike(up, hist, g)
    assert not gauge.is_spike(up, [], g)  # nothing to compare with


# -- range ----------------------------------------------------------------
def test_range_check_against_the_mount_height_and_blind_zone(live, workflow):
    configure(live, mount_height_cm=400, blind_zone_mm=250, max_range_mm=4500)
    # v1: 390 cm with the face at 400 cm is 10 cm from the sensor, inside the blind zone
    for minutes in (3, 2, 1):
        out = send(live, minutes, 390)
        assert out.quality == "out_of_range" and out.gauge_level == "critical" and out.effective_level == "normal"
    assert workflow.started == []
    assert stored(live)[-1].quality_reasons == ["blind_zone:100<=250mm"]
    # v2: the raw distance is checked as sent
    assert send(live, 0, distance_mm=4600).quality == "out_of_range"


@pytest.mark.parametrize(("distance", "quality"), [(250, "out_of_range"), (251, "good"), (4499, "good"),
                                                    (4500, "out_of_range"), (0, "out_of_range")])
def test_range_edges(distance, quality):
    g = GaugeConfig(device_id=DEV, watch_cm=120, warning_cm=200, critical_cm=280, mount_height_cm=500)
    assert (gauge.out_of_range(distance, g) is None) == (quality == "good")


# -- payload v1 and v2 ----------------------------------------------------
def test_payload_v1_is_still_accepted(live):
    out = send(live, 0, 80.5, battery_v=3.9, rssi=-70)
    r = stored(live)[-1]
    assert out.quality == "good" and r.schema_version == 1 and r.water_level_cm == 80.5 and r.distance_mm is None


def test_payload_v2_stage_comes_from_the_server_datum(live):
    configure(live, mount_height_cm=420, sensor="radar")
    send(live, 0, 999.0, v=2, seq=7, boot=3, distance_mm=2400, samples_ok=9, samples_n=11, iqr_mm=4, quality=92,
         err=8, temp_c=31, battery_mv=3312, solar_mv=5900, rssi=-81, fw="2.0.0", reset_cause="deepsleep")
    r = stored(live)[-1]
    # the device's own 999 cm is ignored: 420 - 240 = 180 cm (radar: no temperature correction)
    assert r.water_level_cm == 180.0 and r.schema_version == 2
    assert (r.seq, r.boot, r.distance_mm, r.samples_ok, r.samples_n, r.iqr_mm, r.device_quality) == (7, 3, 2400, 9, 11, 4, 92)
    assert (r.err, r.temp_c, r.battery_v, r.solar_mv, r.fw, r.reset_cause) == (8, 31, 3.312, 5900, "2.0.0", "deepsleep")
    assert r.quality == "good"  # err 8 (clock unsynced) is informational


def test_payload_v2_without_a_datum(live):
    out = send(live, 1, 150.0, v=2, seq=1, distance_mm=2400)
    assert out.quality == "good" and stored(live)[-1].water_level_cm == 150.0  # the device's stage, no range check
    with pytest.raises(gauge.IngestError) as exc:
        send(live, 0, None, seq=2, distance_mm=2400)
    assert exc.value.code == "no_datum" and exc.value.status == 400


@pytest.mark.parametrize(("extra", "reason"), [
    ({"err": 1}, "err:no_echo"), ({"err": 2 | 64}, "err:few_samples"), ({"samples_ok": 3, "samples_n": 9}, "samples:3/9"),
    ({"iqr_mm": 400}, "iqr:400mm"), ({"quality": 20}, "device_quality:20"),
])
def test_device_diagnostics_make_a_reading_suspect(live, extra, reason):
    out = send(live, 0, 150.0, **extra)
    assert out.quality == "suspect" and reason in stored(live)[-1].quality_reasons


def test_payload_validation():
    with pytest.raises(ValidationError):
        gauge.ReadingFields(at=clock.iso(NOW))  # neither a stage nor a distance
    with pytest.raises(ValidationError):
        gauge.ReadingFields(at=clock.iso(NOW), distance_mm=1000, samples_ok=10, samples_n=9)
    with pytest.raises(ValidationError):
        gauge.ReadingFields(at=clock.iso(NOW), water_level_cm=1, fw="bad fw; drop")
    assert gauge.ReadingFields(at=clock.iso(NOW), water_level_cm=1).schema_version == 1
    assert gauge.ReadingFields(at=clock.iso(NOW), water_level_cm=1, temp_c=20).schema_version == 2


def test_temperature_compensation_for_ultrasonic_only():
    assert gauge.speed_of_sound(20) == pytest.approx(343.2, abs=0.1)
    assert gauge.speed_of_sound(0) == pytest.approx(331.3)
    warm = gauge.corrected_distance_mm(3000, 40, "ultrasonic")
    assert warm == pytest.approx(3000 * gauge.speed_of_sound(40) / gauge.speed_of_sound(20))
    assert 3095 < warm < 3105  # about 10 cm longer than the 20 C figure
    assert gauge.corrected_distance_mm(3000, 20, "ultrasonic") == pytest.approx(3000)
    assert gauge.corrected_distance_mm(3000, 40, "radar") == 3000
    assert gauge.corrected_distance_mm(3000, None, "ultrasonic") == 3000
    g = GaugeConfig(device_id=DEV, watch_cm=120, warning_cm=200, critical_cm=280, mount_height_cm=500)
    cm, d = gauge.stage(gauge.ReadingFields(at=clock.iso(NOW), distance_mm=3000, temp_c=40), g)
    assert cm == pytest.approx(500 - warm / 10, abs=0.06) and d == pytest.approx(warm)


# -- backfill -------------------------------------------------------------
def _items(*pairs, buffered=True):
    return [gauge.ReadingFields(at=clock.iso(NOW - timedelta(minutes=m)), water_level_cm=cm, seq=seq, buffered=buffered)
            for seq, m, cm in pairs]


def test_backfill_is_idempotent_and_never_alerts(live, workflow):
    items = _items((101, 50, 210), (102, 45, 290), (103, 40, 295))  # warning and critical, buffered
    first = gauge.ingest_backfill(live, "thunag", DEV, items, now=NOW)
    assert (first.stored, first.duplicate, first.rejected) == (3, 0, [])
    again = gauge.ingest_backfill(live, "thunag", DEV, items, now=NOW)
    assert (again.stored, again.duplicate) == (0, 3)
    rows = stored(live)
    assert len(rows) == 3 and all(r.origin == "backfill" and r.buffered for r in rows)
    assert workflow.started == [] and live.get_village("thunag").level == "normal" and not gauge_audits(live)
    # older than the latest is fine for backfill (live readings refuse it)
    send(live, 20, 90)
    late = gauge.ingest_backfill(live, "thunag", DEV, _items((104, 30, 296)), now=NOW)
    assert late.stored == 1 and workflow.started == []


def test_backfill_never_becomes_the_latest_reading_the_rules_read(live, workflow):
    from Pukaar.services.decision_engine import recompute_village

    send(live, 20, 90)
    gauge.ingest_backfill(live, "thunag", DEV, _items((201, 5, 300), (202, 4, 301), (203, 3, 302)), now=NOW)
    assert live.latest_sensor_reading("thunag", 30, now=NOW).water_level_cm == 90
    assert live.latest_sensor_reading("thunag", 30, now=NOW, include_backfill=True).water_level_cm == 302
    res = recompute_village(live, live.get_village("thunag"), now=NOW,
                            reading=Reading(village_id="thunag", at=clock.iso(NOW), rain_24h_mm=0, discharge_peak=0.1),
                            workflow=workflow)
    assert res.level == "normal" and res.alert_id is None and workflow.started == []
    # and the rules ignore a backfilled reading even if one is handed to them
    b = stored(live)[-1]
    a = rr.assess(None, None, [], NOW, sensor=b, gauge=live.get_village("thunag").gauge)
    assert a.gauge_level == "normal" and not any(e.get("counted") for e in a.evidence if e["kind"] == "gauge")


def test_backfill_rejects_items_without_seq_or_outside_its_window(live):
    items = [gauge.ReadingFields(at=clock.iso(NOW - timedelta(minutes=5)), water_level_cm=100),  # no seq
             gauge.ReadingFields(at=clock.iso(NOW - timedelta(hours=73)), water_level_cm=100, seq=1),
             gauge.ReadingFields(at=clock.iso(NOW + timedelta(minutes=5)), water_level_cm=100, seq=2),
             gauge.ReadingFields(at=clock.iso(NOW - timedelta(hours=71)), water_level_cm=100, seq=3)]
    out = gauge.ingest_backfill(live, "thunag", DEV, items, now=NOW)
    assert out.stored == 1 and sorted(r["code"] for r in out.rejected) == ["no_seq", "stale", "stale"]
    with pytest.raises(gauge.IngestError) as exc:
        gauge.ingest_backfill(live, "thunag", "gauge-other", items, now=NOW)
    assert exc.value.code == "wrong_device"
    with pytest.raises(gauge.IngestError):
        gauge.ingest_backfill(live, "thunag", DEV, items * 16, now=NOW)  # over the batch limit


def test_a_reading_sent_live_and_again_from_the_buffer_is_stored_once(live):
    send(live, 2, 100, seq=55, boot=1)
    out = gauge.ingest_backfill(live, "thunag", DEV, [gauge.ReadingFields(
        at=clock.iso(NOW - timedelta(minutes=2)), water_level_cm=100, seq=55, boot=1)], now=NOW)
    assert (out.stored, out.duplicate) == (0, 1) and len(stored(live)) == 1
    # a live reading whose seq was already backfilled is ignored too
    gauge.ingest_backfill(live, "thunag", DEV, _items((60, 1, 100)), now=NOW)
    assert send(live, 0, 101, seq=60).status == "ignored"


def test_backfill_over_mqtt_and_a_buffered_reading_on_the_live_topic(live, workflow):
    base = {"village_id": "thunag", "device_id": DEV, "topic_kind": "backfill"}
    readings = [{"at": clock.iso(NOW - timedelta(hours=2, minutes=m)), "water_level_cm": 250.0, "seq": 300 + m}
                for m in range(3)]
    out = gauge_ingest.handle({**base, "readings": readings + [{"at": clock.iso(NOW), "water_level_cm": "250",
                                                                 "seq": 9}]}, repo=live, now=NOW)
    assert out["status"] == "accepted" and out["stored"] == 3 and out["rejected"][0]["code"] == "bad_payload"
    assert gauge_ingest.handle({**base, "readings": readings}, repo=live, now=NOW)["duplicate"] == 3
    assert gauge_ingest.handle({**base, "readings": []}, repo=live, now=NOW)["code"] == "bad_payload"
    assert gauge_ingest.handle({**base, "readings": readings, "device_id": "x y"}, repo=live, now=NOW)["code"] == "bad_payload"
    assert gauge_ingest.handle({**base, "topic_kind": "shadow"}, repo=live, now=NOW)["code"] == "bad_topic"
    # an hour old on the live topic would be stale; marked buffered it is backfill instead
    old = {"village_id": "thunag", "device_id": DEV, "at": clock.iso(NOW - timedelta(hours=1)),
           "water_level_cm": 260.0, "seq": 400}
    assert gauge_ingest.handle(old, repo=live, now=NOW)["code"] == "stale"
    out = gauge_ingest.handle({**old, "buffered": True}, repo=live, now=NOW)
    assert out["kind"] == "backfill" and out["stored"] == 1
    assert workflow.started == [] and live.get_village("thunag").level == "normal"


# -- rate of rise ---------------------------------------------------------
def test_a_sustained_rise_raises_the_gauge_one_step_and_is_traced(live, workflow):
    for minutes, cm in ((15, 60), (10, 70), (5, 80)):
        assert send(live, minutes, cm).rising_fast is False
    out = send(live, 0, 92)  # +32 cm in 15 minutes across four good readings
    assert out.rising_fast and out.confirmed_level == "normal" and out.effective_level == "watch"
    assert stored(live)[-1].rise_cm == 32
    assert out.alert_id and workflow.started == [out.alert_id]
    trace = live.get_alert(out.alert_id).decision_trace
    assert "gauge_rising_fast:+32cm/30min:watch" in trace["rules_fired"]
    ev = next(e for e in trace["evidence"] if e["kind"] == "gauge")
    assert ev["rising_fast"] is True and ev["rise_cm"] == 32 and ev["effective_level"] == "watch"
    audit = gauge_audits(live)[-1]
    assert "normal -> watch" in audit.reason and "rising fast +32 cm" in audit.reason


def test_rising_fast_on_top_of_a_confirmed_stage():
    g = GaugeConfig(device_id=DEV, watch_cm=120, warning_cm=200, critical_cm=280)
    s = SensorReading(village_id="thunag", device_id=DEV, at=clock.iso(NOW), water_level_cm=240,
                      confirmed_level="warning", effective_level="critical", rising_fast=True, rise_cm=41)
    a = rr.assess(None, None, [], NOW, sensor=s, gauge=g)
    assert a.gauge_level == "critical"
    assert "gauge>=200cm:warning" in a.rules_fired and "gauge_rising_fast:+41cm/30min:critical" in a.rules_fired


@pytest.mark.parametrize("series", [
    ((15, 60), (10, 95), (5, 70), (0, 92)),  # a dip of 25 cm: not sustained
    ((5, 60), (0, 92)),                      # only two readings
    ((25, 60), (15, 70), (5, 80), (0, 85)),  # 25 cm: under the 30 cm rise
    ((45, 40), (35, 60), (5, 65), (0, 69)),  # the rise is older than the 30-minute window
])
def test_no_rising_fast(live, series):
    outs = [send(live, m, cm) for m, cm in series]
    assert not outs[-1].rising_fast and outs[-1].effective_level == "normal"


def test_rise_settings_are_per_gauge(live):
    configure(live, rise_cm=10, rise_minutes=10)
    for minutes, cm in ((4, 60), (2, 65), (0, 71)):
        out = send(live, minutes, cm)
    assert out.rising_fast and out.effective_level == "watch"


def test_bad_readings_do_not_count_toward_a_rise(live):
    send(live, 15, 60)
    send(live, 10, 70, err=1)  # suspect
    send(live, 5, 80, err=1)
    assert not send(live, 0, 92).rising_fast  # two good readings only


# -- health ---------------------------------------------------------------
def _r(minutes, battery=4.0, quality="good", kind="live"):
    at = clock.iso(NOW - timedelta(minutes=minutes))
    return SensorReading(village_id="thunag", device_id=DEV, at=at, received_at=at, water_level_cm=80,
                         battery_v=battery, quality=quality, origin=kind)


def test_health_flags_silence_low_battery_and_mostly_bad_readings():
    g = GaugeConfig(device_id=DEV, watch_cm=120, warning_cm=200, critical_cm=280)
    ok = gauge.health(g, [_r(m) for m in (20, 10, 1)], NOW)
    assert ok["status"] == "ok" and ok["reasons"] == [] and ok["minutes_since"] == 1 and ok["bad_share_24h"] == 0
    silent = gauge.health(g, [_r(m) for m in (60, 45, 31)], NOW)
    assert silent["status"] == "gauge_unhealthy" and silent["reasons"] == ["silent"]
    low = gauge.health(g, [_r(5, battery=4.0), _r(1, battery=3.31)], NOW)
    assert low["reasons"] == ["low_battery"] and low["battery_v"] == 3.31
    lifepo4 = gauge.health(g.model_copy(update={"low_battery_mv": 3100}), [_r(1, battery=3.31)], NOW)
    assert lifepo4["reasons"] == []
    bad = gauge.health(g, [_r(m, quality="spike" if m % 2 else "good") for m in range(1, 9)], NOW)
    assert bad["reasons"] == ["bad_quality"] and bad["bad_share_24h"] == 0.5 and bad["by_quality"] == {"spike": 4, "good": 4}
    never = gauge.health(g, [], NOW)
    assert never["reasons"] == ["silent"] and never["last_seen"] is None
    # a backfill arriving now is contact: the gauge is alive again
    back = _r(300, kind="backfill")
    back.received_at = clock.iso(NOW - timedelta(minutes=2))
    assert gauge.health(g, [back], NOW)["reasons"] == [] and gauge.health(g, [back], NOW)["backfilled_24h"] == 1


def test_health_scan_emits_the_metric_and_is_shown_to_officers(live, capsys):
    configure(live, installed=True)
    send(live, 5, 80, battery_v=3.2)
    capsys.readouterr()
    rows = {h["village_id"]: h for h in gauge.health_scan(live, NOW)}
    assert rows["thunag"]["reasons"] == ["low_battery"] and rows["thunag"]["installed"] is True
    assert rows["gohar"]["reasons"] == ["silent"] and rows["gohar"]["installed"] is False
    out = capsys.readouterr().out
    metric = next(json.loads(line) for line in out.splitlines() if '"GaugeUnhealthy"' in line and "_aws" in line)
    assert metric["GaugeUnhealthy"] == 1  # installed gauges only: the silent simulators are not paged
    assert gauge.health_scan("not a repo", NOW) == []  # never raises into the sweep

    from Pukaar.api import views
    from Pukaar.services import agents

    g = views.village_detail(live, live.get_village("thunag"))["gauge"]
    assert g["health"]["status"] == "gauge_unhealthy" and g["health"]["battery_low"] is True
    row = next(r for r in agents.sensors(live)["villages"] if r["id"] == "thunag")
    assert row["health"]["reasons"] == ["low_battery"]


# -- simulated readings never raise a live level ---------------------------
def test_simulated_readings_confirm_but_never_raise_a_live_village(repo, frozen, workflow, monkeypatch):
    import Pukaar.workflow.client as wc
    from Pukaar.services.decision_engine import recompute_village

    monkeypatch.setattr(wc, "get_workflow", lambda: workflow)
    sim = repo.get_village("thunag").gauge.device_id
    assert sim.endswith("-sim")
    for minutes in (3, 2, 1):
        out = send(repo, minutes, 300, device=sim)
    assert out.simulated and out.confirmed_level == "critical" and out.alert_id is None
    res = recompute_village(repo, repo.get_village("thunag"), now=NOW, workflow=workflow,
                            reading=Reading(village_id="thunag", at=clock.iso(NOW), rain_24h_mm=0, discharge_peak=0.1))
    assert res.level == "normal" and workflow.started == [] and repo.get_village("thunag").level == "normal"
    a = rr.assess(None, Thresholds(watch=10, warning=20, critical=30), [], NOW,
                  sensor=repo.latest_sensor_reading("thunag", 30, now=NOW), gauge=repo.get_village("thunag").gauge)
    assert a.gauge_level == "normal" and "gauge_simulated_ignored" in a.rules_fired


def test_unconfirmed_reading_is_named_in_the_trace():
    g = GaugeConfig(device_id=DEV, watch_cm=120, warning_cm=200, critical_cm=280)
    s = SensorReading(village_id="thunag", device_id=DEV, at=clock.iso(NOW), water_level_cm=210,
                      measured_level="warning", confirmed_level="normal", effective_level="normal")
    a = rr.assess(None, None, [], NOW, sensor=s, gauge=g)
    assert a.gauge_level == "normal" and "gauge_unconfirmed:warning" in a.rules_fired


# -- HTTPS backfill route ---------------------------------------------------
@pytest.fixture(scope="module")
def client():
    from Pukaar.main import app

    return TestClient(app)


def _signed(client, path, payload, device="gauge-janjehli-sim"):
    raw = json.dumps(payload).encode()
    sig = gauge.sign(gauge.device_key(SECRET, device), raw)
    return client.post(path, content=raw, headers={"content-type": "application/json", "X-Pukaar-Signature": sig})


def test_https_backfill_is_signed_idempotent_and_takes_old_readings(client):
    now = datetime.now(UTC)
    readings = [{"at": clock.iso(now - timedelta(hours=2, minutes=5 * i)), "water_level_cm": 300.0 + i,
                 "seq": 9000 + i, "v": 2, "battery_mv": 3900} for i in range(3)]
    body = {"device_id": "gauge-janjehli-sim", "readings": readings}
    before = client.get("/villages/janjehli").json()["village"]["live_level"]
    r = _signed(client, "/sensors/janjehli/backfill", body)
    assert r.status_code == 202 and r.json()["stored"] == 3 and r.json()["kind"] == "backfill"
    again = _signed(client, "/sensors/janjehli/backfill", body)
    assert again.status_code == 202 and (again.json()["stored"], again.json()["duplicate"]) == (0, 3)
    assert client.get("/villages/janjehli").json()["village"]["live_level"] == before
    bad = client.post("/sensors/janjehli/backfill", content=json.dumps(body).encode(),
                      headers={"X-Pukaar-Signature": "00" * 32})
    assert bad.status_code == 401
    assert _signed(client, "/sensors/janjehli/backfill", {**body, "readings": []}).status_code == 400
    wrong = _signed(client, "/sensors/thunag/backfill", body)
    assert wrong.status_code == 403
    # a buffered reading on the live route goes to backfill: its age is not a replay
    one = {"device_id": "gauge-janjehli-sim", **readings[0], "seq": 9100, "buffered": True,
           "at": clock.iso(now - timedelta(hours=1))}
    r = _signed(client, "/sensors/janjehli/readings", one)
    assert r.status_code == 202 and r.json()["kind"] == "backfill" and r.json()["stored"] == 1
    g = client.get("/villages/janjehli").json()["gauge"]
    assert any(p.get("backfill") for p in g["series"])


def test_template_lists_the_backfill_route_as_public_and_throttled():
    from test_template_safety import RES

    events = RES["ApiFunction"]["Properties"]["Events"]
    routes = [e["Properties"] for e in events.values() if e["Properties"]["Path"] == "/sensors/{id}/backfill"]
    assert len(routes) == 1 and routes[0]["Method"] == "POST" and routes[0]["Auth"]["Authorizer"] == "NONE"
    settings = RES["HttpApi"]["Properties"]["RouteSettings"]
    assert settings["POST /sensors/{id}/backfill"]["ThrottlingRateLimit"] <= 2


def test_the_fast_simulator_plan_backfills_then_confirms_on_the_second_live_reading(client):
    from Pukaar.scripts import gauge_sim

    cfg = client.get("/villages/gohar").json()["gauge"]["config"]
    back, live_points = gauge_sim.fast_plan(cfg, "warning", datetime.now(UTC))
    device = cfg["device_id"]
    readings = [{**gauge_sim.reading_body(at, cm, 4.05), "buffered": True} for at, cm in back]
    r = _signed(client, "/sensors/gohar/backfill", {"device_id": device, "readings": readings}, device=device)
    assert r.status_code == 202 and r.json()["stored"] == len(back) and r.json()["rejected"] == []
    outs = [_signed(client, "/sensors/gohar/readings", {"device_id": device, **gauge_sim.reading_body(at, cm, 4.0)},
                    device=device).json() for at, cm in live_points]
    assert [o["quality"] for o in outs] == ["good"] * 5
    assert outs[0]["confirmed_level"] == "normal" and outs[1]["confirmed_level"] == "warning"
    assert not any(o["rising_fast"] for o in outs) and all(o["alert_id"] is None for o in outs)  # simulated
