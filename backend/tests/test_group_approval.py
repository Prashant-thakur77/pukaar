"""Grouped approval (services/group_approval.py, POST /alert-groups/decide): villages of one district pending
together from one cause are reviewed as a group and decided in one action, but each alert keeps its own Cedar
check, its own audited decision and its own task token."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from Pukaar.core import clock
from Pukaar.policy.guard import Principal
from Pukaar.services import group_approval as ga
from Pukaar.store.models import Alert, Village


def _pending(repo, village, level="warning", minutes=0, rain="warning", river="normal", replay=False, n=1):
    v = repo.get_village(village)
    at = clock.iso(clock.now() + timedelta(minutes=minutes))
    a = Alert(id=f"alr_grp_{village}_{n}", village_id=village, village_name=v.name, village_name_hi=v.name_hi,
              level=level, status="pending", created_at=at, updated_at=at, replay=replay, task_token=f"TOK-{village}-{n}",
              text_hi=f"{v.name_hi}: चेतावनी", text_en=f"Warning for {v.name}",
              decision_trace={"rain_level": rain, "river_level": river, "gauge_level": "normal", "report_level": "normal",
                              "rules_fired": [f"rain_24h:{rain}", "official_corroborates:imd:watch"],
                              "evidence": [{"kind": "official", "items": [
                                  {"source": "sachet", "name": "SACHET", "status": "ok", "level": "watch",
                                   "detail": "1 SACHET alert in force for Mandi"}]}]})
    repo.put_alert(a)
    return repo.get_alert(a.id)


def test_villages_of_one_district_from_one_cause_form_a_group(repo, frozen):
    a = [_pending(repo, v, minutes=i) for i, v in enumerate(["thunag", "janjehli", "gohar", "pandoh"])]
    _pending(repo, "sujanpur")  # Hamirpur: another district, never in Mandi's group
    groups = ga.groups_for(repo)
    assert len(groups) == 1
    g = groups[0].view()
    assert g["district"] == "Mandi" and g["cause"] == "rain" and g["count"] == 4
    assert {v["alert_id"] for v in g["villages"]} == {x.id for x in a}
    assert g["shared"]["drivers"] == ["rain", "official"]
    assert g["shared"]["official"][0]["source"] == "sachet"
    assert "rain_24h:warning" in g["shared"]["rules"]


def test_another_cause_a_late_alert_or_a_replay_is_not_in_the_group(repo, frozen):
    _pending(repo, "thunag")
    _pending(repo, "janjehli", minutes=5)
    _pending(repo, "gohar", rain="normal", river="warning")  # the river, not rain
    _pending(repo, "pandoh", minutes=400)  # past the window
    groups = ga.groups_for(repo)
    assert [sorted(v["village_id"] for v in g.view()["villages"]) for g in groups] == [["janjehli", "thunag"]]
    # A replay never groups with live alerts.
    assert ga.key_of(_pending(repo, "gohar", replay=True, n=2)) != ga.key_of(repo.get_alert("alr_grp_thunag_1"))


def test_one_decision_approves_some_and_declines_the_rest_each_with_its_own_token(repo, frozen, workflow):
    a = [_pending(repo, v, minutes=i) for i, v in enumerate(["thunag", "janjehli", "gohar"])]
    officer = Principal("officer1", "officer")
    results = ga.decide_group(repo, workflow, officer, [
        {"alert_id": a[0].id, "decision": "approved"}, {"alert_id": a[1].id, "decision": "approved"},
        {"alert_id": a[2].id, "decision": "declined"}], reason="valley-wide rain", group_id="g1")
    assert [r["outcome"] for r in results] == ["decided"] * 3
    assert sorted(t for t, _ in workflow.successes) == sorted(x.task_token for x in a)
    assert {repo.get_alert(x.id).status for x in a[:2]} == {"approved"}
    assert repo.get_alert(a[2].id).status == "declined"
    day = clock.iso(clock.now())[:10]
    rows = repo.list_audit(day)
    per_alert = [r for r in rows if r.action in {"approve", "decline"} and r.decision == "allow"]
    assert {r.resource for r in per_alert} == {f"alert:{x.id}" for x in a}
    group_row = next(r for r in rows if r.action == "group_decision")
    assert "2 approved, 1 declined" in group_row.reason and group_row.actor == "officer1"


def test_cedar_checks_each_village_so_an_out_of_district_one_is_denied(repo, frozen, workflow):
    repo.put_village(Village(id="kasol", name="Kasol", name_hi="कसोल", district="Kullu", lat=32.0, lon=77.3))
    ok = _pending(repo, "thunag")
    other = _pending(repo, "kasol")
    asha = Principal("asha", "officer")
    repo.put_staff_scope("asha", ["Mandi"])
    with pytest.raises(ga.GroupError):  # one district per group
        ga.decide_group(repo, workflow, asha, [{"alert_id": ok.id, "decision": "approved"},
                                               {"alert_id": other.id, "decision": "approved"}])
    res = ga.decide_group(repo, workflow, asha, [{"alert_id": other.id, "decision": "approved"}])
    assert res[0]["outcome"] == "denied" and repo.get_alert(other.id).status == "pending"
    assert workflow.successes == []


def test_a_late_alert_in_the_group_does_not_stop_the_others(repo, frozen, workflow):
    a = _pending(repo, "thunag")
    b = _pending(repo, "janjehli")
    repo.update_alert(b.id, status="expired", task_token=None)
    res = ga.decide_group(repo, workflow, Principal("officer1", "officer"),
                          [{"alert_id": a.id, "decision": "approved"}, {"alert_id": b.id, "decision": "approved"}])
    assert [r["outcome"] for r in res] == ["decided", "late"]


@pytest.fixture()
def client(repo, monkeypatch, workflow):
    from Pukaar.api import auth
    from Pukaar.api.routers import reach
    from Pukaar.main import app

    for mod in (auth, reach):
        monkeypatch.setattr(mod, "get_repo", lambda: repo)
    monkeypatch.setattr(reach, "get_workflow", lambda: workflow)
    monkeypatch.setattr("Pukaar.store.repo.get_repo", lambda: repo)
    return TestClient(app)


def _token(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_the_routes_list_and_decide_a_group_and_refuse_the_public_demo_account(client, repo, frozen, workflow):
    a = [_pending(repo, v, minutes=i) for i, v in enumerate(["thunag", "janjehli"])]
    groups = client.get("/alert-groups", params={"district": "Mandi"}, headers=_token(client, "officer1")).json()
    assert len(groups) == 1 and groups[0]["count"] == 2
    body = {"decisions": [{"alert_id": x.id, "decision": "approved"} for x in a], "group_id": groups[0]["id"]}
    judge = client.post("/alert-groups/decide", json=body, headers=_token(client, "judge")).json()
    assert {r["outcome"] for r in judge["results"]} == {"denied"}  # live alerts: never the demo account's
    r = client.post("/alert-groups/decide", json=body, headers=_token(client, "officer1"))
    assert r.status_code == 200 and r.json()["decided"] == 2
    assert client.post("/alert-groups/decide", json={"decisions": []}, headers=_token(client, "officer1")).status_code == 422
