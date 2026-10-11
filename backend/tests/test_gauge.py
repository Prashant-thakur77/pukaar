"""River gauge: a third evidence source beside the rain and river forecasts."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from conftest import NOW
from fastapi.testclient import TestClient
from Pukaar.core import clock
from Pukaar.services import gauge as gauge_svc
from Pukaar.services import risk_rules as rr
from Pukaar.store.models import GaugeConfig, Reading, SensorReading, Thresholds

TH = Thresholds(watch=10.0, warning=20.0, critical=30.0)
G = GaugeConfig(device_id="gauge-thunag-sim", watch_cm=120, warning_cm=200, critical_cm=280)
SECRET = "test-link-secret-at-least-32-bytes-long"


def reading(rain=None, peak=None):
    return Reading(village_id="thunag", at="2026-07-01T02:00:00Z", rain_24h_mm=rain, discharge_peak=peak)


def sensor(cm, minutes_old=5, simulated=False):
    return SensorReading(village_id="thunag", device_id=G.device_id, at=clock.iso(NOW - timedelta(minutes=minutes_old)),
                         water_level_cm=cm, simulated=simulated)


# -- risk rules -----------------------------------------------------------
def test_gauge_bands():
    assert rr.gauge_level(119.9, G) == "normal"
    assert rr.gauge_level(120, G) == "watch"
    assert rr.gauge_level(200, G) == "warning"
    assert rr.gauge_level(300, G) == "critical"
    assert rr.gauge_level(300, None) == "normal"


def test_fresh_gauge_raises_level():
    a = rr.assess(reading(rain=0, peak=1), TH, [], NOW, sensor=sensor(210), gauge=G)
    assert a.gauge_level == "warning" and a.level == "warning"
    assert "gauge>=200cm:warning" in a.rules_fired
    assert any(e["kind"] == "gauge" and e["water_level_cm"] == 210 for e in a.evidence)


def test_stale_or_missing_gauge_changes_nothing():
    base = rr.assess(reading(rain=70, peak=1), TH, [], NOW)
    stale = rr.assess(reading(rain=70, peak=1), TH, [], NOW, sensor=sensor(300, minutes_old=31), gauge=G)
    none = rr.assess(reading(rain=70, peak=1), TH, [], NOW, sensor=None, gauge=G)
    no_cfg = rr.assess(reading(rain=70, peak=1), TH, [], NOW, sensor=sensor(300), gauge=None)
    for a in (stale, none, no_cfg):
        assert (a.level, a.rules_fired, a.gauge_level) == (base.level, base.rules_fired, "normal")
        assert not any(e["kind"] == "gauge" for e in a.evidence)


def test_gauge_and_forecast_agree_bumps_one_level():
    a = rr.assess(reading(rain=0, peak=12), TH, [], NOW, sensor=sensor(130), gauge=G)
    assert (a.river_level, a.gauge_level) == ("watch", "watch")
    assert a.level == "warning" and "two_sources_agree:+1" in a.rules_fired
    b = rr.assess(reading(rain=70, peak=1), TH, [], NOW, sensor=sensor(130), gauge=G)
    assert b.level == "warning" and "two_sources_agree:+1" in b.rules_fired


def test_simulated_gauge_is_labelled():
    a = rr.assess(reading(rain=0, peak=1), TH, [], NOW, sensor=sensor(130, simulated=True), gauge=G)
    assert "gauge_simulated" in a.rules_fired
    assert next(e for e in a.evidence if e["kind"] == "gauge")["simulated"] is True


# -- repo and sweep -------------------------------------------------------
def test_repo_rate_limits_and_latest(repo, frozen):
    r1 = sensor(100, minutes_old=10)
    assert repo.put_sensor_reading(r1)
    assert not repo.put_sensor_reading(sensor(101, minutes_old=10))  # same time: replayed body
    assert not repo.put_sensor_reading(sensor(101, minutes_old=9.5))  # under a minute later
    assert not repo.put_sensor_reading(sensor(101, minutes_old=20))  # out of order
    assert repo.put_sensor_reading(sensor(105, minutes_old=9))
    assert repo.latest_sensor_reading("thunag", 30).water_level_cm == 105
    assert repo.latest_sensor_reading("thunag", 5) is None
    assert [r.water_level_cm for r in repo.list_sensor_readings("thunag", clock.iso(NOW - timedelta(hours=1)))] == [100, 105]


def test_sweep_uses_fresh_gauge_and_traces_it(repo, frozen, workflow):
    from Pukaar.services.decision_engine import recompute_village

    v = repo.get_village("thunag")
    assert v.gauge is not None and v.gauge.installed is False  # seeded, illustrative
    repo.put_sensor_reading(SensorReading(village_id="thunag", device_id=v.gauge.device_id, at=clock.iso(NOW),
                                          water_level_cm=v.gauge.warning_cm + 5, simulated=True))
    res = recompute_village(repo, v, now=NOW, reading=reading(rain=0, peak=0.1), workflow=workflow)
    assert res.level == "warning" and res.alert_id
    trace = repo.get_alert(res.alert_id).decision_trace
    assert trace["gauge_level"] == "warning"
    assert "gauge_simulated" in trace["rules_fired"]


# -- ingestion API --------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    from Pukaar.main import app

    return TestClient(app)


def _post(client, village, payload, key_device=None, sig=None):
    raw = json.dumps(payload).encode()
    key = gauge_svc.device_key(SECRET, key_device or payload["device_id"])
    headers = {"content-type": "application/json", "X-Pukaar-Signature": sig if sig is not None else gauge_svc.sign(key, raw)}
    return client.post(f"/sensors/{village}/readings", content=raw, headers=headers)


def _at(seconds_ago):
    return clock.iso(datetime.now(timezone.utc) - timedelta(seconds=seconds_ago))


def test_ingest_rejects_bad_signature_old_timestamp_and_wrong_device(client):
    good = {"device_id": "gauge-sujanpur-sim", "at": _at(240), "water_level_cm": 40.0}
    assert _post(client, "sujanpur", good, sig="00" * 32).status_code == 401
    assert _post(client, "sujanpur", good, key_device="gauge-other").status_code == 401
    unsigned = client.post("/sensors/sujanpur/readings", content=json.dumps(good).encode())
    assert unsigned.status_code == 401
    old = {**good, "at": _at(6 * 60)}
    r = _post(client, "sujanpur", old)
    assert r.status_code == 401 and r.json()["detail"]["code"] == "stale"
    wrong = {**good, "device_id": "gauge-gohar-sim"}
    r = _post(client, "sujanpur", wrong)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "wrong_device"
    assert _post(client, "sujanpur", {**good, "water_level_cm": "x"}).status_code == 400


def test_ingest_accepts_rate_limits_and_shows_on_village_page(client):
    first = {"device_id": "gauge-sujanpur-sim", "at": _at(200), "water_level_cm": 50.5, "battery_v": 3.9}
    r = _post(client, "sujanpur", first)
    assert r.status_code == 202 and r.json()["status"] == "accepted" and r.json()["simulated"] is True
    again = _post(client, "sujanpur", first)  # exact replay of a signed body
    assert again.status_code == 202 and again.json()["status"] == "ignored"
    too_soon = _post(client, "sujanpur", {**first, "at": _at(170)})
    assert too_soon.json()["status"] == "ignored"
    rising = _post(client, "sujanpur", {**first, "at": _at(100), "water_level_cm": 310.0})
    assert rising.status_code == 202 and rising.json()["gauge_level"] == "warning"
    assert rising.json()["village_level"] in {"warning", "critical"}

    g = client.get("/villages/sujanpur").json()["gauge"]
    assert g["config"]["device_id"] == "gauge-sujanpur-sim" and g["config"]["installed"] is False
    assert g["fresh"] is True and g["level"] == "warning"
    assert g["latest"]["water_level_cm"] == 310.0 and g["latest"]["simulated"] is True
    assert [p["cm"] for p in g["series"]] == [50.5, 310.0]


# -- simulator ------------------------------------------------------------
def test_simulator_rises_past_watch_and_warning_and_signs_like_the_server():
    from Pukaar.scripts import gauge_sim

    cfg = G.model_dump()
    stages = gauge_sim.profile(cfg, 5, "warning")
    assert stages[0] < G.watch_cm and stages[-1] > G.warning_cm and stages == sorted(stages)
    # --fast spacing fits the server's one-per-minute and five-minute rules
    assert gauge_sim.FAST_STEP_S >= 60 and gauge_sim.FAST_OLDEST_S < gauge_svc.MAX_AGE_SECONDS
    body = b'{"device_id":"gauge-thunag-sim"}'
    sig = gauge_svc.sign(gauge_svc.device_key(SECRET, "gauge-thunag-sim"), body)
    assert gauge_svc.signature_ok(SECRET, "gauge-thunag-sim", body, sig)
    assert not gauge_svc.signature_ok(SECRET, "gauge-gohar-sim", body, sig)
