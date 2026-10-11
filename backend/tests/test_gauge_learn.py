"""Learning gauge thresholds from the gauge's own record: the maths, the floors, the faults, the
routes (Cedar, audit old -> new) and that nothing is ever applied on its own."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import NOW
from fastapi.testclient import TestClient
from Pukaar.core import clock
from Pukaar.policy.guard import SYSTEM, Principal, evaluate
from Pukaar.services import gauge_learn as gl
from Pukaar.store.models import GaugeConfig
from synthetic_gauge import series, store

G = GaugeConfig(device_id="gauge-thunag-sim", watch_cm=120, warning_cm=200, critical_cm=280)


def kinds(p):
    return {f["kind"] for f in p["faults"]}


# -- maths -----------------------------------------------------------------------------
def test_percentile_interpolates_like_numpy():
    v = [float(x) for x in range(101)]
    assert gl.percentile(v, 90) == 90 and gl.percentile(v, 99.5) == 99.5
    assert gl.percentile([1.0, 2.0], 50) == 1.5 and gl.percentile([5.0], 97) == 5.0
    with pytest.raises(ValueError):
        gl.percentile([], 50)


def test_needs_seven_days_or_two_thousand_readings():
    short = gl.propose(series(NOW, days=3), G)  # 864 readings over 3 days
    assert short["status"] == "insufficient" and "3.0 of 7 days" in short["note_en"] and short["note_hi"]
    assert "proposed" not in short and short["current"]["watch_cm"] == 120
    dense = gl.propose(series(NOW, days=2.5, step_min=1), G)  # 3600 readings in 2.5 days
    assert dense["status"] == "ready"
    sparse = gl.propose(series(NOW, days=8, step_min=10), G)  # 1152 readings over 8 days
    assert sparse["status"] == "ready"
    custom = gl.propose(series(NOW, days=3), G, min_days=2)
    assert custom["status"] == "ready" and custom["basis"]["min_days"] == 2
    assert gl.propose([], G)["status"] == "insufficient"


def test_proposal_is_the_records_own_percentiles_with_floors():
    readings = series(NOW, events=((4, 160, 12), (9, 90, 8)), noise_cm=2)
    p = gl.propose(readings, G)
    values = sorted(r.water_level_cm for r in readings)
    assert p["raw"]["critical"] == round(gl.percentile(values, 99.5), 1)
    w, wa, c = (p["proposed"][k] for k in ("watch_cm", "warning_cm", "critical_cm"))
    assert all(x == int(x) for x in (w, wa, c))  # whole cm, rounded up
    assert w >= p["baseline_cm"] + gl.BASELINE_MARGIN_CM
    assert wa - w >= gl.MIN_SEPARATION_CM and c - wa >= gl.MIN_SEPARATION_CM
    assert c >= p["raw"]["critical"] and c > 150  # the flood day sets critical, not a floor
    assert p["never_auto_applied"] is True and "officer accepts" in p["note_en"]
    assert [pt["p"] for pt in p["curve"]][-3:] == [99, 99.5, 100]
    assert len(p["daily"]) == 15 and p["basis"]["simulated"] is True


def test_a_dry_record_is_held_up_by_the_baseline_floor():
    p = gl.propose(series(NOW, diurnal_cm=2, noise_cm=0.5), G)
    assert p["baseline_cm"] == pytest.approx(57.4, abs=1.5)
    assert p["proposed"]["watch_cm"] == gl._ceil_cm(p["baseline_cm"] + gl.BASELINE_MARGIN_CM)
    assert [a["level"] for a in p["adjustments"]] == ["watch", "warning", "critical"]
    assert p["adjustments"][1]["rule"] == "watch + separation"


def test_percentiles_and_floors_are_configurable():
    readings = series(NOW, events=((4, 160, 12),))
    a = gl.propose(readings, G, percentiles={"watch": 80.0}, baseline_margin_cm=0, min_separation_cm=1)
    b = gl.propose(readings, G, baseline_margin_cm=0, min_separation_cm=1)
    assert a["percentiles"]["watch"] == 80 and a["raw"]["watch"] < b["raw"]["watch"]


def test_faults_are_left_out_of_the_proposal():
    spikes = tuple(range(100, 4000, 130))  # 31 echoes of +400 cm: 0.8% of the record
    clean = gl.propose(series(NOW, events=((4, 160, 12),)), G)
    raw = series(NOW, events=((4, 160, 12),), spikes=spikes, flat=(3000, 40))
    faulty = gl.propose(raw, G)
    assert gl.percentile(sorted(r.water_level_cm for r in raw), 99.5) > 400  # uncleaned, critical would be an echo
    assert faulty["basis"]["excluded"] == len(spikes) + 39
    for k in ("watch_cm", "warning_cm", "critical_cm"):
        assert abs(faulty["proposed"][k] - clean["proposed"][k]) <= 3
    assert {"jump", "flatline"} <= kinds(faulty) and kinds(clean) == set()


# -- faults ------------------------------------------------------------------------------
def test_flat_line_and_jumps_are_counted():
    f = {x.kind: x for x in gl.detect_faults(series(NOW, days=2, spikes=(100,), flat=(200, 20)))}
    assert f["flatline"].count == 1 and "95 min" in f["flatline"].message_en
    assert f["jump"].count == 2 and f["jump"].value == pytest.approx(400, abs=10)  # up and back down
    assert f["jump"].message_hi


def test_clock_offset_and_drift():
    f = {x.kind: x for x in gl.detect_faults(series(NOW, days=8, clock_drift_s_per_day=40))}
    assert f["clock_drift"].value == pytest.approx(40, abs=1)
    assert f["clock_offset"].value > gl.CLOCK_OFFSET_S and "behind" in f["clock_offset"].message_en
    ok = {x.kind for x in gl.detect_faults(series(NOW, days=8, clock_offset_s=3))}
    assert not ok & {"clock_drift", "clock_offset"}


def test_battery_trend_and_low_battery():
    f = {x.kind: x for x in gl.detect_faults(series(NOW, days=10, battery_drop_v_per_day=0.04))}
    assert f["battery_trend"].value == pytest.approx(-0.04, abs=0.005)
    assert "days to 3.5 V" in f["battery_trend"].message_en
    late = {x.kind for x in gl.detect_faults(series(NOW, days=14, battery_drop_v_per_day=0.06))}
    assert {"battery_trend", "battery_low"} <= late


def test_gaps_are_reported_as_info():
    rs = series(NOW, days=2)
    rs = rs[:100] + rs[130:]  # 150 minutes of silence
    f = {x.kind: x for x in gl.detect_faults(rs)}
    assert f["gaps"].severity == "info" and f["gaps"].value == pytest.approx(155, abs=1)


# -- Cedar --------------------------------------------------------------------------------
def test_cedar_threshold_policies():
    officer, pradhan = Principal("officer1", "officer"), Principal("pradhan_thunag", "pradhan", ["thunag"])
    own, other = {"village_id": "thunag"}, {"village_id": "gohar"}
    assert evaluate(officer, "view_gauge_proposal", "village", "gohar", other).allowed
    assert evaluate(officer, "set_gauge_thresholds", "village", "gohar", other).allowed
    assert evaluate(pradhan, "view_gauge_proposal", "village", "thunag", own).allowed
    assert not evaluate(pradhan, "view_gauge_proposal", "village", "gohar", other).allowed
    assert not evaluate(pradhan, "set_gauge_thresholds", "village", "thunag", own).allowed
    assert not evaluate(Principal("bot", "agent"), "set_gauge_thresholds", "village", "thunag", own).allowed
    assert not evaluate(SYSTEM, "set_gauge_thresholds", "village", "thunag", own).allowed


# -- routes ---------------------------------------------------------------------------------
@pytest.fixture()
def client(repo, monkeypatch):
    from Pukaar.api import auth
    from Pukaar.api.routers import gauges, public
    from Pukaar.main import app

    for mod in (auth, public, gauges):
        monkeypatch.setattr(mod, "get_repo", lambda: repo)
    return TestClient(app)


def token(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_proposal_route_and_accepting_it(client, repo, frozen):
    url = "/villages/thunag/gauge/proposal"
    officer, pradhan = token(client, "officer1"), token(client, "pradhan_thunag")
    assert client.get(url).status_code == 401
    empty = client.get(url, headers=officer).json()
    assert empty["status"] == "insufficient" and empty["basis"]["readings"] == 0

    store(repo, series(NOW - timedelta(minutes=1), days=9, events=((4, 160, 12),)))
    p = client.get(url, headers=pradhan)
    assert p.status_code == 200 and p.json()["status"] == "ready"
    assert client.get("/villages/gohar/gauge/proposal", headers=pradhan).status_code == 403
    before = repo.get_village("thunag").gauge
    assert before.watch_cm == client.get("/villages/thunag").json()["gauge"]["config"]["watch_cm"]  # never auto-applied

    prop = p.json()["proposed"]
    post = "/villages/thunag/gauge/thresholds"
    denied = client.post(post, json=prop, headers=pradhan)
    assert denied.status_code == 403 and denied.json()["detail"]["reason"] == "Only a district officer can change a gauge's thresholds."
    tampered = client.post(post, json={**prop, "critical_cm": prop["critical_cm"] + 100}, headers=officer)
    assert tampered.status_code == 409 and tampered.json()["detail"]["code"] == "proposal_changed"
    ok = client.post(post, json=prop, headers=officer)
    assert ok.status_code == 200, ok.text
    g = repo.get_village("thunag").gauge
    assert (g.watch_cm, g.warning_cm, g.critical_cm) == (prop["watch_cm"], prop["warning_cm"], prop["critical_cm"])
    assert g.thresholds_set_by == "officer1" and g.thresholds_source.startswith("learned from 9.0 days")
    assert g.device_id == before.device_id and g.installed == before.installed
    row = next(a for a in repo.list_audit(clock.iso(NOW)[:10], "village:thunag") if a.action == "set_gauge_thresholds")
    assert f"watch {before.watch_cm:g} -> {prop['watch_cm']:g} cm" in row.reason
    assert f"critical {before.critical_cm:g} -> {prop['critical_cm']:g} cm" in row.reason
    assert client.get("/villages/thunag").json()["gauge"]["config"]["thresholds_set_by"] == "officer1"


def test_manual_thresholds_must_rise(client, repo, frozen):
    officer = token(client, "officer1")
    post = "/villages/thunag/gauge/thresholds"
    bad = client.post(post, json={"watch_cm": 200, "warning_cm": 150, "critical_cm": 300, "from_proposal": False}, headers=officer)
    assert bad.status_code == 400 and bad.json()["detail"]["message_hi"]
    ok = client.post(post, json={"watch_cm": 110, "warning_cm": 190, "critical_cm": 270, "from_proposal": False,
                                 "note": "bridge flood mark 2023"}, headers=officer)
    assert ok.status_code == 200 and ok.json()["previous"]["watch_cm"] == 120
    assert repo.get_village("thunag").gauge.thresholds_source == "set by hand: bridge flood mark 2023"
    # A proposal that is not ready cannot be "accepted".
    assert client.post(post, json={"watch_cm": 1, "warning_cm": 2, "critical_cm": 3}, headers=officer).status_code == 409
