"""Safe places: the baked OpenStreetMap data, the shelter ledger, its Cedar rules, the API and the alert line."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from Pukaar.core import clock
from Pukaar.llm.bedrock import AlertDraft
from Pukaar.policy.guard import Principal, evaluate
from Pukaar.services import drafting, safe_places
from Pukaar.services.drafting import draft_alert
from Pukaar.store.models import Alert, ShelterStatus
from Pukaar.templates import hi

DATA = Path(__file__).resolve().parents[2] / "data" / "safe_places"
VILLAGES = json.loads((DATA.parent / "villages.json").read_text(encoding="utf-8"))["villages"]
OFFICER = Principal("officer1", "officer")
PRADHAN = Principal("pradhan_thunag", "pradhan", ["thunag"])


# -- the baked data ----------------------------------------------------------------
def test_every_village_has_a_baked_file_with_attribution():
    summary = json.loads((DATA / "summary.json").read_text(encoding="utf-8"))
    assert summary["attribution"] == "© OpenStreetMap contributors (ODbL)"
    assert "ground" in summary["method"]["limits"]
    for v in VILLAGES:
        geo = json.loads((DATA / f"{v['id']}.geojson").read_text(encoding="utf-8"))
        assert geo["attribution"] == "© OpenStreetMap contributors (ODbL)" and "ODbL" in geo["license"]
        assert v["id"] in summary["villages"]
        # A village with no place says so; it never gets an invented one.
        if not summary["villages"][v["id"]]["places"]:
            assert summary["villages"][v["id"]]["notes"]


@pytest.mark.parametrize("village_id", [v["id"] for v in VILLAGES])
def test_baked_places_are_named_osm_features_high_above_the_river(village_id):
    geo = json.loads((DATA / f"{village_id}.geojson").read_text(encoding="utf-8"))
    feats = geo["features"]
    places = [f["properties"] for f in feats if f["properties"]["feature"] == "place"]
    routes = [f["properties"] for f in feats if f["properties"]["feature"] == "route"]
    assert len(places) <= 3
    for p in places:
        assert p["id"].startswith("osm-") and p["osm_url"].startswith("https://www.openstreetmap.org/")
        assert p["name"] and p["name_hi"]
        assert p["headroom_m"] >= 15
        assert p["route_length_m"] > 0 and p["walk_min"] == -(-p["route_length_m"] // 50)  # 3 km/h, rounded up
        assert isinstance(p["max_grade"], (int, float)) and p["max_grade"] >= 0
        assert any(r["place_id"] == p["id"] for r in routes)
    assert {r["place_id"] for r in routes} <= {p["id"] for p in places}


# -- Cedar --------------------------------------------------------------------------
def test_officer_may_update_any_shelter_and_pradhan_only_their_own():
    assert evaluate(OFFICER, "set_shelter_status", "village", "gohar", {"village_id": "gohar"}).allowed
    assert evaluate(PRADHAN, "set_shelter_status", "village", "thunag", {"village_id": "thunag"}).allowed
    denied = evaluate(PRADHAN, "set_shelter_status", "village", "gohar", {"village_id": "gohar"})
    assert not denied.allowed and "pradhan of this village" in denied.reason
    # No village in the context is not a loophole for a pradhan.
    assert not evaluate(PRADHAN, "set_shelter_status", "village", "thunag", {"village_id": ""}).allowed
    assert not evaluate(Principal("drafting-agent", "agent"), "set_shelter_status", "village", "thunag",
                        {"village_id": "thunag"}).allowed


# -- the ledger and the alert line (synthetic places, so the test does not depend on OSM) --
FAKE = {
    "thunag": {
        "type": "FeatureCollection", "attribution": "© OpenStreetMap contributors (ODbL)", "metadata": {},
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [77.17, 31.56]},
             "properties": {"feature": "place", "id": "osm-node-1", "name": "Govt School Thunag",
                            "name_hi": "राजकीय विद्यालय थुनाग", "kind": "school", "headroom_m": 40.0,
                            "route_length_m": 800, "walk_min": 16, "rank": 1}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [77.18, 31.57]},
             "properties": {"feature": "place", "id": "osm-node-2", "name": "Mata Temple",
                            "name_hi": "माता मंदिर", "kind": "place_of_worship", "headroom_m": 120.0,
                            "route_length_m": 2100, "walk_min": 42, "rank": 2}},
        ],
    },
    "gohar": {
        "type": "FeatureCollection", "metadata": {},
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [77.04, 31.58]},
             "properties": {"feature": "place", "id": "osm-node-9", "name": "Civil Hospital Gohar",
                            "name_hi": "सिविल अस्पताल गोहर", "kind": "hospital", "headroom_m": 20.0,
                            "route_length_m": 1200, "walk_min": 24, "rank": 1}},
        ],
    },
}


@pytest.fixture()
def fake_places(monkeypatch):
    monkeypatch.setattr(safe_places, "load", lambda vid: FAKE.get(vid))


def mark(repo, place_id, status, village="thunag", by="pradhan_thunag"):
    repo.put_shelter(ShelterStatus(village_id=village, place_id=place_id, status=status, updated_by=by,
                                   updated_at=clock.iso(clock.now())))


def _draft(**kw):
    base = dict(time_window_hi="अगले 24 घंटों में", advice_hi="नाले के पास न जाएँ।", advice_en="Keep away from the stream.",
                reason_en="River peak 2.94 m3/s is above the warning threshold 2.5.", evidence_ids=[])
    base.update(kw)
    return AlertDraft(**base)


TRACE = {"evidence": [{"discharge_peak": 2.94, "thresholds": {"warning": 2.5}}], "rules_fired": ["river_warning"]}


class FixedLLM:
    model_name = "us.amazon.nova-2-lite-v1:0"

    def __init__(self, draft):
        self.draft = draft

    def draft_alert(self, *a, **k):
        return self.draft


def test_no_line_when_no_place_is_confirmed(repo, fake_places):
    v = repo.get_village("thunag")
    out = draft_alert(v, "warning", TRACE, repo, None)
    assert out.safe_place is None
    assert "सुरक्षित जगह:" not in out.text_hi and "Nearest safe place" not in out.text_en
    mark(repo, "osm-node-1", "FULL")
    mark(repo, "osm-node-2", "CLOSED")
    out = draft_alert(v, "critical", TRACE, repo, None)
    assert out.safe_place is None and "सुरक्षित जगह:" not in out.text_hi


def test_fixed_template_names_the_nearest_open_place(repo, fake_places):
    v = repo.get_village("thunag")
    mark(repo, "osm-node-2", "OPEN")
    mark(repo, "osm-node-1", "STANDBY")
    out = draft_alert(v, "warning", TRACE, repo, None)
    # OPEN beats STANDBY even when the STANDBY place is nearer.
    assert out.safe_place["id"] == "osm-node-2" and out.safe_place["status"] == "OPEN"
    assert "सबसे पास सुरक्षित जगह: माता मंदिर।" in out.text_hi
    assert "Nearest safe place: Mata Temple." in out.text_en
    assert out.text_hi.endswith(hi.CALL_112_HI)
    mark(repo, "osm-node-2", "FULL")
    out = draft_alert(v, "warning", TRACE, repo, None)
    assert out.safe_place["id"] == "osm-node-1" and "राजकीय विद्यालय थुनाग" in out.text_hi


def test_checker_accepts_the_place_in_the_trace_and_rejects_any_other(repo, fake_places):
    v = repo.get_village("thunag")
    mark(repo, "osm-node-1", "OPEN")
    ok = draft_alert(v, "warning", TRACE, repo, FixedLLM(_draft(advice_en="Walk to Govt School Thunag now.")))
    assert ok.check.passed and ok.reasoning_model != "rule-fallback"
    assert ok.text_hi.count("राजकीय विद्यालय थुनाग") == 1  # the code-built line, once
    # A place that is baked but not the one in the trace (closed, unconfirmed or another village's) is refused.
    for other in ("Mata Temple", "माता मंदिर", "Civil Hospital Gohar"):
        bad = draft_alert(v, "warning", TRACE, repo, FixedLLM(_draft(advice_en=f"Go to {other}.")))
        assert bad.reasoning_model == "rule-fallback" and "another place" in bad.check.reason, other
        assert "सबसे पास सुरक्षित जगह: राजकीय विद्यालय थुनाग।" in bad.text_hi  # fallback still names it


def test_checker_rejects_a_safe_place_when_none_is_in_the_trace(repo, fake_places):
    v = repo.get_village("thunag")
    out = draft_alert(v, "warning", TRACE, repo, FixedLLM(_draft(advice_en="Go to Govt School Thunag.")))
    assert out.reasoning_model == "rule-fallback" and "another place" in out.check.reason
    check = drafting.check_draft(_draft(advice_en="Go to Govt School Thunag."), v,
                                 {"trace": TRACE, "safe_place": None}, ["Govt School Thunag"])
    assert not check.passed


def test_workflow_records_the_place_in_the_decision_trace(repo, frozen, fake_places):
    from Pukaar.core.ids import new_id
    from Pukaar.workflow.steps import Steps

    mark(repo, "osm-node-1", "OPEN")
    v = repo.get_village("thunag")
    stamp = clock.iso(clock.now())
    a = Alert(id=new_id("alr"), village_id=v.id, village_name=v.name, village_name_hi=v.name_hi, level="critical",
              status="drafting", created_at=stamp, updated_at=stamp, decision_trace={"rules_fired": ["test"]})
    repo.put_alert(a)
    Steps(repo, None, synthesize=lambda *_: None).handle({"step": "draft", "alert_id": a.id})
    alert = repo.get_alert(a.id)
    assert alert.decision_trace["safe_place"]["name"] == "Govt School Thunag"
    assert "OpenStreetMap" in alert.decision_trace["safe_place"]["source"]
    assert "राजकीय विद्यालय थुनाग" in alert.text_hi
    # The auto-send fallback keeps the same place, read from the trace.
    text_hi, _ = hi.fallback_alert("critical", v.name_hi, v.name, alert.decision_trace.get("safe_place"))
    assert "राजकीय विद्यालय थुनाग" in text_hi


def test_drafting_tool_lists_only_confirmed_places(repo, fake_places):
    from Pukaar.llm.tools import DataTools

    tools = DataTools(repo)
    assert tools.get_safe_places("thunag") == []
    mark(repo, "osm-node-2", "STANDBY")
    mark(repo, "osm-node-1", "CLOSED")
    got = tools.get_safe_places("thunag")
    assert [p["id"] for p in got] == ["osm-node-2"] and got[0]["status"] == "STANDBY"


# -- HTTP ------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    from Pukaar.main import app

    return TestClient(app)


def token(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def _village_with_places() -> tuple[str, str] | None:
    summary = json.loads((DATA / "summary.json").read_text(encoding="utf-8"))
    for vid, meta in summary["villages"].items():
        if meta["places"]:
            return vid, meta["places"][0]["id"]
    return None


def test_safe_places_are_public_and_carry_attribution(client):
    for v in VILLAGES:
        r = client.get(f"/villages/{v['id']}/safe-places")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["available"] is True and body["attribution"] == "© OpenStreetMap contributors (ODbL)"
        assert body["limits_en"] and body["limits_hi"]
        states = {"UNCONFIRMED", "OPEN", "STANDBY", "FULL", "CLOSED"}
        assert all(p["ledger"]["status"] in states for p in body["places"])
        assert body["routes"]["type"] == "FeatureCollection"
    assert client.get("/villages/atlantis/safe-places").status_code == 404


def test_shelter_ledger_write_needs_the_right_person_and_is_audited(client):
    found = _village_with_places()
    assert found, "at least one village should have a baked safe place"
    vid, pid = found
    url = f"/villages/{vid}/shelters/{pid}"
    assert client.post(url, json={"status": "OPEN"}).status_code == 401
    other = "gohar" if vid != "gohar" else "sujanpur"
    if vid != "thunag":  # the demo pradhan runs Thunag only
        r = client.post(url, json={"status": "OPEN"}, headers=token(client, "pradhan_thunag"))
        assert r.status_code == 403 and "pradhan of this village" in r.json()["detail"]["reason"]
    h = token(client, "officer1")
    assert client.post(url, json={"status": "MAYBE"}, headers=h).status_code == 400
    assert client.post(url, json={"status": "OPEN", "capacity": -1}, headers=h).status_code == 400
    assert client.post(f"/villages/{vid}/shelters/osm-node-0", json={"status": "OPEN"}, headers=h).status_code == 404
    assert client.post(f"/villages/{other}/shelters/{pid}", json={"status": "OPEN"}, headers=h).status_code == 404
    r = client.post(url, json={"status": "open", "capacity": 120, "note": "keys with the headmaster"}, headers=h)
    assert r.status_code == 200, r.text
    place = next(p for p in r.json()["places"] if p["id"] == pid)
    assert place["ledger"]["status"] == "OPEN" and place["ledger"]["capacity"] == 120
    assert place["ledger"]["updated_by"] == "officer1"
    audit = client.get("/audit", params={"resource": f"shelter:{vid}/{pid}"}, headers=h).json()
    assert any(a["action"] == "shelter_changed" and "UNCONFIRMED -> OPEN" in a["reason"] for a in audit)
    # Leave the shared app in a state no other test's alert text depends on.
    assert client.post(url, json={"status": "CLOSED"}, headers=h).json()["places"]
