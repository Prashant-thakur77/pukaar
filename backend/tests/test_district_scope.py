"""District scope (services/scope.py, policy/base.cedar "staff-own-district"): an officer acts only on villages
of the districts they are assigned to or rostered on; the state operator reads everything and acts only where
assigned; the DDMA head reads their districts and changes their settings. Seeding gives every village the same
demo officers on dev only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from Pukaar.core import clock
from Pukaar.policy.guard import SYSTEM, Principal, authorize, evaluate
from Pukaar.services import district_settings, roster
from Pukaar.store.models import RosterShift, Village

ACTS = ["approve", "decline", "edit_alert", "snooze_alert", "set_report_state", "issue_directive", "open_rollcall",
        "remind_rollcall", "set_alert_outcome", "block_road", "set_shelter_status"]
READS = ["view_console", "view_reports", "view_recipients", "view_rollcall", "view_after_action", "read_audit"]


def ctx(in_scope: bool, district: str = "Mandi", **kw):
    return {"village_id": "gohar", "district": district, "scoped": True, "in_scope": in_scope, **kw}


# -- the Cedar matrix (policy only: the scope facts given) ----------------------------------------------
@pytest.mark.parametrize("role", ["officer", "state_operator"])
@pytest.mark.parametrize("action", ACTS)
def test_officer_and_state_operator_act_only_in_scope(role, action):
    p = Principal("asha", role)
    rtype, rid = ("village", "gohar") if action in {"block_road", "set_shelter_status"} else ("alert", "alr_1")
    assert evaluate(p, action, rtype, rid, ctx(True)).allowed, (role, action)
    assert not evaluate(p, action, rtype, rid, ctx(False)).allowed, (role, action)
    # A replay is a rehearsal: never held to a district.
    if role == "officer" and action not in {"open_rollcall", "remind_rollcall"}:  # replays never ask phones
        assert evaluate(p, action, rtype, rid, ctx(False, replay=True)).allowed


@pytest.mark.parametrize("action", ["sound_siren", "set_gauge_thresholds", "edit_roster", "take_over_duty",
                                    "set_recipient_role", "tick_checklist", "pour_test", "manage_device"])
def test_an_officer_out_of_district_cannot_touch_sirens_gauges_or_the_roster(action):
    p = Principal("asha", "officer")
    base = {"level": "warning", "pattern": "W1", "kind": "silent", "hour_ist": 10}
    assert not evaluate(p, action, "village", "gohar", {**ctx(False), **base}).allowed


@pytest.mark.parametrize("action", READS)
def test_reads_are_not_scoped_for_officers_and_state_operators(action):
    for role in ("officer", "state_operator"):
        assert evaluate(Principal("asha", role), action, "alert", "alr_1", ctx(False)).allowed, (role, action)


def test_state_operator_never_sirens_and_never_approves_unassigned():
    so = Principal("sdma1", "state_operator")
    assert not evaluate(so, "sound_siren", "village", "gohar", {**ctx(True), "level": "warning"}).allowed
    assert not evaluate(so, "approve", "alert", "a", ctx(False)).allowed
    assert not evaluate(so, "change_settings", "app", "pukaar", ctx(True)).allowed


def test_ddma_head_reads_and_sets_only_their_district():
    head = Principal("ddma_mandi", "ddma_head", district_ids=["Mandi"])
    for action in ("view_console", "view_reports", "view_rollcall", "view_after_action", "view_roster"):
        assert evaluate(head, action, "village", "gohar", ctx(False)).allowed, action
        assert not evaluate(head, action, "village", "sujanpur", ctx(False, "Hamirpur")).allowed, action
    assert evaluate(head, "change_settings", "app", "pukaar", {"district": "Mandi"}).allowed
    assert not evaluate(head, "change_settings", "app", "pukaar", {"district": "Hamirpur"}).allowed
    for action in ("approve", "decline", "view_recipients", "sound_siren", "issue_directive"):
        assert not evaluate(head, action, "alert", "a", ctx(True)).allowed, action
    # An officer cannot change district settings.
    assert not evaluate(Principal("officer1", "officer"), "change_settings", "app", "pukaar", ctx(True)).allowed


def test_system_and_pradhan_are_unchanged():
    assert evaluate(SYSTEM, "deliver", "alert", "a", {"approved": True, **ctx(False)}).allowed
    pr = Principal("pradhan_thunag", "pradhan", ["thunag"])
    assert evaluate(pr, "view_reports", "village", "thunag", {"village_id": "thunag"}).allowed


# -- the facts, read from the records ------------------------------------------------------------------
def _alert(repo, village="gohar"):
    from Pukaar.store.models import Alert

    now = clock.iso(clock.now())
    a = Alert(id=f"alr_scope_{village}", village_id=village, village_name=village, village_name_hi="गाँव",
              level="warning", status="pending", created_at=now, updated_at=now)
    repo.put_alert(a)
    return repo.get_alert(a.id)


def test_scope_comes_from_assignment_village_list_or_roster(repo, frozen):
    a = _alert(repo, "gohar")  # Mandi
    b = _alert(repo, "sujanpur")  # Hamirpur
    assert a.district == "Mandi" and b.district == "Hamirpur"
    new = Principal("asha", "officer")
    assert not authorize(new, "approve", "alert", a.id, repo=repo).allowed
    repo.put_staff_scope("asha", ["Mandi"])  # make staff-assign
    assert authorize(new, "approve", "alert", a.id, repo=repo).allowed
    assert not authorize(new, "approve", "alert", b.id, repo=repo).allowed
    # Rostered today in Hamirpur: may act there today.
    day = roster.today_ist(frozen["now"]).isoformat()
    repo.put_roster_shift(RosterShift(district="Hamirpur", date=day, shift="day", primary="asha",
                                      updated_by="officer1", updated_at=clock.iso(frozen["now"])))
    assert authorize(new, "approve", "alert", b.id, repo=repo).allowed
    # The seeded demo officers are on every village's list (dev): in scope everywhere.
    assert authorize(Principal("officer1", "officer"), "approve", "alert", b.id, repo=repo).allowed


def test_a_caller_cannot_claim_scope_in_the_context(repo, frozen):
    a = _alert(repo, "gohar")
    d = authorize(Principal("asha", "officer"), "approve", "alert", a.id,
                  {"village_id": "gohar", "scoped": False, "in_scope": True}, repo=repo)
    assert not d.allowed


def test_critical_auto_send_is_the_ddma_heads_district_setting(repo, frozen):
    head = Principal("ddma_mandi", "ddma_head", district_ids=["Mandi"])
    assert district_settings.critical_auto_send(repo, "Mandi") is False  # the deployment's default
    district_settings.set_critical_auto_send(repo, "Mandi", True, head)
    assert district_settings.critical_auto_send(repo, "Mandi") is True
    assert district_settings.critical_auto_send(repo, "Hamirpur") is False
    rows = [r for r in repo.list_audit(clock.iso(frozen["now"])[:10]) if r.action == "change_settings"]
    assert rows and rows[0].actor == "ddma_mandi" and "True" in rows[0].reason
    district_settings.set_critical_auto_send(repo, "Mandi", None, head)
    assert district_settings.critical_auto_send(repo, "Mandi") is False


@pytest.fixture()
def client(repo, monkeypatch):
    from Pukaar.api import auth
    from Pukaar.api.routers import officer, public
    from Pukaar.main import app

    for mod in (auth, public, officer):
        monkeypatch.setattr(mod, "get_repo", lambda: repo)
    monkeypatch.setattr("Pukaar.store.repo.get_repo", lambda: repo)
    return TestClient(app)


def token(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_settings_route_is_the_ddma_heads_only(client, repo, frozen):
    head, officer = token(client, "ddma_mandi"), token(client, "officer1")
    assert client.patch("/districts/Mandi/settings", json={"critical_auto_send": True}, headers=officer).status_code == 403
    assert client.patch("/districts/Hamirpur/settings", json={"critical_auto_send": True}, headers=head).status_code == 403
    r = client.patch("/districts/Mandi/settings", json={"critical_auto_send": True}, headers=head)
    assert r.status_code == 200 and r.json()["critical_auto_send"] is True
    assert client.get("/districts/Mandi/settings", headers=officer).json()["critical_auto_send"] is True
    # The DDMA head's inbox is their district's villages only.
    _alert(repo, "gohar"), _alert(repo, "sujanpur")
    ids = {a["village_id"] for a in client.get("/alerts", headers=head).json()}
    assert ids == {"gohar"}
    so = client.get("/alerts", headers=token(client, "state_operator1")).json()
    assert {a["village_id"] for a in so} == {"gohar", "sujanpur"}


def test_seed_gives_every_village_the_demo_officers_on_dev_only():
    from Pukaar.scripts.seed import village_officers

    assert village_officers({"id": "gohar"}, {}, ["officer1", "officer2"], production=False) == ["officer1", "officer2"]
    assert village_officers({"id": "gohar"}, {"officers": ["dc_mandi"]}, ["officer1", "officer2"],
                            production=True) == ["dc_mandi"]
    assert village_officers({"id": "gohar"}, {}, ["officer1", "officer2"], production=True) == []
    assert village_officers({"id": "gohar", "officers": ["sdm_gohar"]}, {}, ["officer1"], production=True) == ["sdm_gohar"]


def test_districts_come_from_data_not_code():
    data = json.loads((Path(__file__).resolve().parents[2] / "data" / "districts.json").read_text(encoding="utf-8"))
    assert data["districts"]["Mandi"]["lgd_code"] == "22" and data["districts"]["Hamirpur"]["lgd_code"] == "17"
    src = (Path(__file__).resolve().parents[1] / "src" / "Pukaar" / "services" / "cap.py").read_text(encoding="utf-8")
    assert '"Mandi": "22"' not in src and "LGD_DISTRICT_CODES" not in src


def test_a_village_of_another_district_is_out_of_scope(repo, frozen):
    repo.put_village(Village(id="kasol", name="Kasol", name_hi="कसोल", district="Kullu", lat=32.0, lon=77.3))
    p = Principal("officer1", "officer")
    assert not authorize(p, "block_road", "village", "kasol", {"village_id": "kasol"}, repo=repo).allowed
    # No such village: the role decides and the route answers 404; there is nothing there to act on.
    assert authorize(p, "block_road", "village", "nowhere", {"village_id": "nowhere"}, repo=repo).allowed
