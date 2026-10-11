"""Road blocks on evacuation routes: Cedar, storage and TTL, route selection, the alert line and the API."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from conftest import NOW
from fastapi.testclient import TestClient
from test_safe_places import FAKE, TRACE, FixedLLM, _draft, mark

from Pukaar.core import clock
from Pukaar.llm.tools import DataTools
from Pukaar.policy.guard import Principal, evaluate
from Pukaar.services import safe_places
from Pukaar.services.drafting import draft_alert

OFFICER = Principal("officer1", "officer")
PRADHAN = Principal("pradhan_thunag", "pradhan", ["thunag"])
AGENT = Principal("drafting-agent", "agent")

# Two baked routes from the same start: east to the school (rank 1), north then east to the temple (rank 2,
# split where it turns steep, as the baker does).
ROUTED = json.loads(json.dumps(FAKE))
ROUTED["thunag"]["features"] += [
    {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[77.170, 31.560], [77.172, 31.560],
                                                                             [77.174, 31.561]]},
     "properties": {"feature": "route", "rank": 1, "place_id": "osm-node-1", "steep": False}},
    {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[77.170, 31.560], [77.170, 31.565]]},
     "properties": {"feature": "route", "rank": 2, "place_id": "osm-node-2", "steep": False}},
    {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[77.170, 31.565], [77.180, 31.570]]},
     "properties": {"feature": "route", "rank": 2, "place_id": "osm-node-2", "steep": True}},
]
ON_ROUTE_1 = (31.5600, 77.1715)  # on the school route only (about 140 m from the temple route)
ON_ROUTE_2 = (31.5670, 77.1740)  # on the temple route's steep stretch only
SHARED = (31.5601, 77.1701)      # the shared start: blocks both


@pytest.fixture()
def routed(monkeypatch):
    monkeypatch.setattr(safe_places, "load", lambda vid: ROUTED.get(vid))


def block(repo, at, note="Landslide on the path", village="thunag", by="officer1", label=""):
    b = safe_places.new_roadblock(village, f"rb_{at[0]}_{at[1]}", at[0], at[1], label, note, by, clock.now())
    repo.put_roadblock(b)
    return b


# -- Cedar -------------------------------------------------------------------------------
def test_cedar_block_road_officer_anywhere_pradhan_own_village_agent_never():
    assert evaluate(OFFICER, "block_road", "village", "gohar", {"village_id": "gohar"}).allowed
    assert evaluate(PRADHAN, "block_road", "village", "thunag", {"village_id": "thunag"}).allowed
    denied = evaluate(PRADHAN, "block_road", "village", "gohar", {"village_id": "gohar"})
    assert not denied.allowed and "pradhan of this village" in denied.reason
    # No village in the context is not a loophole for a pradhan.
    assert not evaluate(PRADHAN, "block_road", "village", "thunag", {"village_id": ""}).allowed
    agent = evaluate(AGENT, "block_road", "village", "thunag", {"village_id": "thunag"})
    assert not agent.allowed and agent.policy_ids == ["agents-never-send"]


# -- geometry ----------------------------------------------------------------------------
def test_distance_to_a_route_line():
    line = [[77.170, 31.560], [77.172, 31.560]]
    assert safe_places.distance_to_line_m(31.560, 77.171, line) < 1
    north = safe_places.distance_to_line_m(31.5609, 77.171, line)  # 0.0009 degrees of latitude is about 100 m
    assert 95 < north < 105
    assert safe_places.distance_to_line_m(31.56, 77.17, []) == float("inf")


def test_a_block_must_sit_on_a_baked_route_and_carry_a_note(routed):
    with pytest.raises(ValueError, match="walking routes"):
        safe_places.new_roadblock("thunag", "rb_x", 31.60, 77.30, "", "Flooded", "officer1", NOW)
    with pytest.raises(ValueError, match="note"):
        safe_places.new_roadblock("thunag", "rb_x", *ON_ROUTE_1, "", "   ", "officer1", NOW)
    with pytest.raises(ValueError, match="walking routes"):  # the fake Gohar has no baked route at all
        safe_places.new_roadblock("gohar", "rb_x", *ON_ROUTE_1, "", "Flooded", "officer1", NOW)
    ok = safe_places.new_roadblock("thunag", "rb_x", *ON_ROUTE_1, " Khad bridge ", " Washed out ", "o", NOW)
    assert ok.label == "Khad bridge" and ok.note == "Washed out"


# -- storage -----------------------------------------------------------------------------
def test_roadblock_storage_ttl_expiry_renew_and_clear(repo, frozen, routed):
    b = block(repo, ON_ROUTE_1, label="Khad bridge")
    item = repo._get("VILLAGE#thunag", f"ROADBLOCK#{b.id}")
    assert item["kind"] == "roadblock" and int(item["ttl"]) == int(clock.parse(b.expires_at).timestamp())
    assert clock.parse(b.expires_at) - clock.parse(b.created_at) == timedelta(days=7)
    assert [x.id for x in repo.list_roadblocks("thunag")] == [b.id] and repo.list_roadblocks("gohar") == []
    # Six days on, someone renews it: seven more days from then.
    frozen["now"] = NOW + timedelta(days=6)
    repo.put_roadblock(safe_places.renewed(b, "pradhan_thunag", clock.now()))
    frozen["now"] = NOW + timedelta(days=11)
    (live,) = repo.list_roadblocks("thunag")
    assert live.renewed_by == "pradhan_thunag" and live.note == "Landslide on the path"
    assert int(repo._get("VILLAGE#thunag", f"ROADBLOCK#{b.id}")["ttl"]) == int((NOW + timedelta(days=13)).timestamp())
    # Not renewed again: it lapses, even before DynamoDB's lazy TTL removes the row.
    frozen["now"] = NOW + timedelta(days=14)
    assert repo.list_roadblocks("thunag") == []
    assert len(repo.list_roadblocks("thunag", active_only=False)) == 1
    # Cleared by a person: gone at once, the row kept for the record until its TTL.
    frozen["now"] = NOW + timedelta(days=11)
    repo.put_roadblock(safe_places.cleared(live, "officer1", clock.now()))
    assert repo.list_roadblocks("thunag") == []
    assert repo.list_roadblocks("thunag", active_only=False)[0].cleared_by == "officer1"


# -- route selection ---------------------------------------------------------------------
def test_blocked_route_is_crossed_out_and_the_next_baked_route_promoted(repo, frozen, routed):
    view = safe_places.view(repo, "thunag")
    assert view["roadblocks"] == [] and view["route_limit_en"].startswith("Routes are worked out in advance")
    assert view["route_limit_hi"]
    assert [p["best_open_route"] for p in view["places"]] == [True, False]
    b = block(repo, ON_ROUTE_1, note="Bridge washed away", label="Khad bridge")
    view = safe_places.view(repo, "thunag")
    school, temple = view["places"]
    assert school["route_blocked"] and school["route_blocks"] == [
        {"id": b.id, "label": "Khad bridge", "note": "Bridge washed away"}]
    assert not school["best_open_route"] and temple["best_open_route"] and not temple["route_blocked"]
    routes = [f["properties"] for f in view["routes"]["features"] if f["properties"]["feature"] == "route"]
    assert [(r["place_id"], r["blocked"], r["best"]) for r in routes] == [
        ("osm-node-1", True, False), ("osm-node-2", False, True), ("osm-node-2", False, True)]
    assert routes[0]["block_note"] == "Bridge washed away"
    assert view["roadblocks"][0]["place_ids"] == ["osm-node-1"]
    # A block on the temple route's steep stretch blocks that whole route: no open route is left.
    block(repo, ON_ROUTE_2)
    view = safe_places.view(repo, "thunag")
    assert all(p["route_blocked"] and not p["best_open_route"] for p in view["places"])
    # The baked file itself is never changed by a block.
    assert "blocked" not in ROUTED["thunag"]["features"][-1]["properties"]


def test_a_block_at_the_shared_start_blocks_every_route_through_it(repo, frozen, routed):
    block(repo, SHARED, note="Road gone at the village end")
    assert sorted(safe_places.blocked_routes("thunag", repo.list_roadblocks("thunag"))) == ["osm-node-1", "osm-node-2"]


# -- the alert line ----------------------------------------------------------------------
def test_alert_line_falls_back_to_the_next_place_with_an_open_route(repo, frozen, routed):
    v = repo.get_village("thunag")
    mark(repo, "osm-node-1", "OPEN")
    mark(repo, "osm-node-2", "OPEN")
    assert safe_places.nearest_usable(repo, "thunag")["id"] == "osm-node-1"
    block(repo, ON_ROUTE_1, note="Bridge washed away")
    out = draft_alert(v, "warning", TRACE, repo, None)
    assert out.safe_place["id"] == "osm-node-2"
    assert "सबसे पास सुरक्षित जगह: माता मंदिर।" in out.text_hi and "राजकीय विद्यालय थुनाग" not in out.text_hi
    # The checker still allows only the place in the trace: the school, though OPEN, is now refused.
    bad = draft_alert(v, "warning", TRACE, repo, FixedLLM(_draft(advice_en="Go to Govt School Thunag.")))
    assert bad.reasoning_model == "rule-fallback" and "another place" in bad.check.reason
    assert "माता मंदिर" in bad.text_hi
    # The drafting agent's tool does not offer the blocked place either.
    assert [p["id"] for p in DataTools(repo).get_safe_places("thunag")] == ["osm-node-2"]
    # Every route blocked: no place is named at all.
    block(repo, ON_ROUTE_2)
    out = draft_alert(v, "critical", TRACE, repo, None)
    assert out.safe_place is None and "सुरक्षित जगह:" not in out.text_hi


# -- HTTP --------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    from Pukaar.main import app

    return TestClient(app)


def token(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_roadblock_api_needs_the_right_person_and_is_audited(client):
    vid = "gohar"
    geo = safe_places.load(vid)
    route = next(f for f in geo["features"] if f["properties"]["feature"] == "route")
    coords = route["geometry"]["coordinates"]
    lon, lat = coords[len(coords) // 2]
    url = f"/villages/{vid}/roadblocks"
    body = {"lat": lat, "lon": lon, "note": "Landslide across the road", "label": "Hospital road"}
    assert client.post(url, json=body).status_code == 401
    r = client.post(url, json=body, headers=token(client, "pradhan_thunag"))
    assert r.status_code == 403 and "pradhan of this village" in r.json()["detail"]["reason"]
    h = token(client, "officer1")
    assert client.post(url, json=body | {"lat": lat + 0.05}, headers=h).status_code == 400
    assert client.post(url, json=body | {"note": " "}, headers=h).status_code == 400
    assert client.post("/villages/atlantis/roadblocks", json=body, headers=h).status_code == 404
    r = client.post(url, json=body, headers=h)
    assert r.status_code == 200, r.text
    view = r.json()
    (rb,) = view["roadblocks"]
    assert rb["note"] == "Landslide across the road" and rb["label"] == "Hospital road"
    assert rb["created_by"] == "officer1" and rb["place_ids"] == [route["properties"]["place_id"]]
    assert next(p for p in view["places"] if p["id"] == rb["place_ids"][0])["route_blocked"]
    assert client.get(f"/villages/{vid}/safe-places").json()["roadblocks"][0]["id"] == rb["id"]  # public read
    assert client.post(f"{url}/{rb['id']}/renew", headers=h).json()["roadblocks"][0]["renewed_by"] == "officer1"
    assert client.post(f"{url}/{rb['id']}/clear", headers=h).json()["roadblocks"] == []
    assert client.post(f"{url}/{rb['id']}/clear", headers=h).status_code == 404
    assert client.post(f"{url}/{rb['id']}/renew", headers=h).status_code == 404
    audit = client.get("/audit", params={"resource": f"roadblock:{vid}/{rb['id']}"}, headers=h).json()
    assert {a["action"] for a in audit} >= {"road_blocked", "road_block_renewed", "road_block_cleared"}
    assert any("open -> BLOCKED" in a["reason"] for a in audit)
    assert client.get(f"/villages/{vid}/safe-places").json()["roadblocks"] == []
