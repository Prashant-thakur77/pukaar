"""The "why we warned" note after an alert ends (services/followup.py), and assisted households with a named
neighbour, plus the two-observer readiness check (services/assisted.py)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from Pukaar.core import clock
from Pukaar.delivery import dispatch
from Pukaar.policy.guard import SYSTEM, evaluate
from Pukaar.services import assisted, followup
from Pukaar.store.models import Delivery, Recipient

from test_rollcall import tg  # noqa: F401  (fixture)
from test_roster import approved, people


def _notes(tg) -> dict[str, str]:
    return {p["chat_id"]: p["text"] for p in tg.sent() if "क्यों दी" in p["text"]}


def _closed(repo, workflow, **kw):
    s, alert = approved(repo, workflow, **kw)
    s.handle({"step": "close", "alert_id": alert.id, "outcome": "delivered"})
    return s, repo.get_alert(alert.id)


# -- the why-we-warned note ------------------------------------------------------------------------
def test_the_outcome_sends_one_note_to_everyone_reached(repo, frozen, workflow, tg):
    people(repo)
    _, alert = _closed(repo, workflow)
    dispatch.acknowledge(repo, alert.id, "5550001")
    tg.calls.clear()
    a = repo.update_alert(alert.id, outcome="no_flood", outcome_by="officer1", outcome_at=clock.iso(frozen["now"]))
    assert followup.due(a, frozen["now"]) == "outcome"
    out = followup.send(repo, a, "outcome")
    notes = _notes(tg)
    assert set(notes) == {"5550001", "5550002", "5550003", "5550004", "5550005"}
    assert "इस बार बाढ़ नहीं आई" in notes["5550002"] and "No flood came this time" in notes["5550002"]
    assert "Thank you for pressing" in notes["5550001"] and "Next time please press" in notes["5550002"]
    assert "भारी बारिश" in notes["5550001"] or "बाढ़ के संकेत" in notes["5550001"] or "नदी" in notes["5550001"]
    got = repo.get_alert(alert.id)
    assert out["sent"] == 5 and got.followup_trigger == "outcome" and got.followup_sent == 5
    assert got.followup_skipped == 2  # the two demo stubs
    assert any(t.step == "followup" for t in repo.list_timeline(alert.id))
    # Once per alert, whatever triggers it next.
    tg.calls.clear()
    assert followup.send(repo, got, "outcome") is None and followup.due(got, frozen["now"]) is None
    assert followup.run_due(repo, frozen["now"] + timedelta(days=2)) == 0 and not tg.calls


def test_after_the_all_clear_the_note_waits_an_hour_for_an_answer(repo, frozen, workflow, tg):
    from Pukaar.workflow.steps import stand_down_village

    people(repo)
    _, alert = _closed(repo, workflow)
    stand_down_village(repo, "thunag", replay=False, by="system", reason="back to normal")
    tg.calls.clear()
    assert followup.run_due(repo, frozen["now"] + timedelta(minutes=30)) == 0 and not _notes(tg)
    assert followup.run_due(repo, frozen["now"] + timedelta(minutes=61)) == 1
    notes = _notes(tg)
    assert len(notes) == 5 and "The danger has passed" in notes["5550001"]
    assert repo.get_alert(alert.id).followup_trigger == "all_clear"


def test_a_closed_alert_without_an_all_clear_gets_it_after_a_day(repo, frozen, workflow, tg):
    people(repo)
    _, alert = _closed(repo, workflow)
    tg.calls.clear()
    assert followup.run_due(repo, frozen["now"] + timedelta(hours=23)) == 0
    assert followup.run_due(repo, frozen["now"] + timedelta(hours=25)) == 1
    assert repo.get_alert(alert.id).followup_trigger == "expired" and len(_notes(tg)) == 5


def test_never_for_a_replay_and_never_to_a_real_phone_from_one(repo, frozen, workflow, tg):
    people(repo)
    _, alert = _closed(repo, workflow, replay=True)
    a = repo.update_alert(alert.id, outcome="real_flood")
    tg.calls.clear()
    assert followup.due(a, frozen["now"] + timedelta(days=2)) is None
    assert followup.send(repo, a, "outcome") is None and not tg.calls
    assert not evaluate(SYSTEM, "followup", "alert", a.id, {"replay": True, "channel": "telegram"}).allowed
    assert evaluate(SYSTEM, "followup", "alert", a.id, {"replay": False, "channel": "telegram"}).allowed


def test_an_alert_that_reached_nobody_has_nobody_to_explain_to(repo, frozen, workflow, tg):
    from test_workflow_steps import make_alert

    a = make_alert(repo, "warning", False)
    a = repo.update_alert(a.id, status="declined")
    assert followup.due(a, frozen["now"] + timedelta(days=2)) is None


def test_a_voice_only_person_is_not_called_for_the_note(repo, frozen, workflow, tg):
    people(repo)
    _, alert = _closed(repo, workflow)
    repo.put_delivery(Delivery(alert_id=alert.id, recipient_id="v_1", name="Voice Only", channel="voice",
                               status="sent", sent_at=clock.iso(frozen["now"]), attempts=1))
    out = followup.send(repo, repo.get_alert(alert.id), "outcome")
    assert out["skipped"] == 3 and out["sent"] == 5  # two demo stubs and the voice-only person


@pytest.fixture()
def api(repo, monkeypatch):
    from Pukaar.api import auth
    from Pukaar.api.routers import officer
    from Pukaar.main import app

    for mod in (auth, officer):
        monkeypatch.setattr(mod, "get_repo", lambda: repo)
    return TestClient(app)


def _h(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_recording_the_outcome_sends_the_note_and_keeps_the_onset(api, repo, frozen, workflow, tg):
    people(repo)
    _, alert = _closed(repo, workflow)
    tg.calls.clear()
    onset = clock.iso(frozen["now"] + timedelta(minutes=45))
    r = api.post(f"/alerts/{alert.id}/outcome", json={"outcome": "real_flood", "onset_at": onset},
                 headers=_h(api, "officer1"))
    assert r.status_code == 200, r.text
    assert len(_notes(tg)) == 5 and "बाढ़ या नुक़सान दर्ज हुआ" in next(iter(_notes(tg).values()))
    got = repo.get_alert(alert.id)
    assert got.outcome_onset_at == onset and got.followup_trigger == "outcome"
    # A correction later changes the record, never sends a second note.
    tg.calls.clear()
    assert api.post(f"/alerts/{alert.id}/outcome", json={"outcome": "no_flood"}, headers=_h(api, "officer1")).status_code == 200
    assert not _notes(tg)
    assert api.post(f"/alerts/{alert.id}/outcome", json={"outcome": "no_flood", "onset_at": "yesterday"},
                    headers=_h(api, "officer1")).status_code == 400


# -- assisted households ---------------------------------------------------------------------------
def _assisted(repo, neighbour="5550004"):
    people(repo)
    repo.put_recipient(Recipient(id="5550010", village_id="thunag", name="Dadi Ma", channel="telegram"))
    return assisted.set_care(repo, "thunag", "5550010", assisted=True, reason="elderly", escalate_to=neighbour,
                             actor="officer1", actor_role="officer")


def _checks(tg):
    return [p for p in tg.sent() if "reply_markup" in p and "chk:" in str(p["reply_markup"])]


def test_an_unconfirmed_assisted_household_brings_the_named_neighbour(repo, frozen, workflow, tg):
    _assisted(repo)
    _, alert = approved(repo, workflow)
    tg.calls.clear()
    assert assisted.escalate_due(repo, repo.get_alert(alert.id), frozen["now"] + timedelta(minutes=5)) == 0
    later = frozen["now"] + timedelta(minutes=11)
    assert assisted.escalate_due(repo, repo.get_alert(alert.id), later) == 1
    sent = _checks(tg)
    assert [p["chat_id"] for p in sent] == ["5550004"]
    assert "Dadi" in sent[0]["text"] and "बुज़ुर्ग" in sent[0]["text"] and "5550010" not in sent[0]["text"]
    assert sent[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"chk:{alert.id}:5550010"
    # Once per person per alert, however many sweeps and recall rounds look.
    assert assisted.escalate_due(repo, repo.get_alert(alert.id), later + timedelta(minutes=15)) == 0
    assert len(_checks(tg)) == 1
    assert any(t.step == "assisted_escalated" and "Dadi" in t.detail for t in repo.list_timeline(alert.id))
    # Only the person asked can mark the check, once.
    assert assisted.checked(repo, alert.id, "5550010", by_chat="5550002") == "यह अनुरोध आपके लिए नहीं था। · This request was not for you."
    assert assisted.checked(repo, alert.id, "5550010", by_chat="5550004").startswith("धन्यवाद")
    assert assisted.checked(repo, alert.id, "5550010", by_chat="5550004").startswith("पहले ही")
    row = repo.get_delivery(alert.id, "5550010")
    assert row.checked_by == "5550004" and row.escalated_to == "5550004"


def test_a_confirmed_assisted_household_brings_nobody(repo, frozen, workflow, tg):
    _assisted(repo)
    _, alert = approved(repo, workflow)
    dispatch.acknowledge(repo, alert.id, "5550010")
    tg.calls.clear()
    assert assisted.escalate_due(repo, repo.get_alert(alert.id), frozen["now"] + timedelta(minutes=11)) == 0
    assert not _checks(tg)


def test_without_a_named_neighbour_the_relays_are_asked(repo, frozen, workflow, tg):
    _assisted(repo, neighbour="")
    _, alert = approved(repo, workflow)
    tg.calls.clear()
    assert assisted.run_due(repo, frozen["now"] + timedelta(minutes=11)) == 1
    assert {p["chat_id"] for p in _checks(tg)} == {"5550003", "5550004"}  # the pradhan first, then one more relay


def test_never_for_a_replay(repo, frozen, workflow, tg):
    _assisted(repo)
    _, alert = approved(repo, workflow, replay=True)
    tg.calls.clear()
    assert assisted.escalate_due(repo, repo.get_alert(alert.id), frozen["now"] + timedelta(hours=1)) == 0
    assert not tg.calls


def test_care_is_validated_and_audited(repo, frozen):
    people(repo)
    with pytest.raises(assisted.CareError):
        assisted.set_care(repo, "thunag", "5550001", reason="old", actor="o", actor_role="officer")
    with pytest.raises(assisted.CareError):
        assisted.set_care(repo, "thunag", "5550001", escalate_to="5550001", actor="o", actor_role="officer")
    with pytest.raises(assisted.CareError):
        assisted.set_care(repo, "thunag", "5550001", escalate_to="nobody", actor="o", actor_role="officer")
    with pytest.raises(assisted.CareError):
        assisted.set_care(repo, "thunag", "5550001", gender="x", actor="o", actor_role="officer")
    with pytest.raises(KeyError):
        assisted.set_care(repo, "thunag", "missing", assisted=True, actor="o", actor_role="officer")
    r = assisted.set_care(repo, "thunag", "5550001", assisted=True, reason="alone", escalate_to="5550002",
                          gender="female", actor="officer1", actor_role="officer")
    assert (r.assisted, r.assisted_reason, r.escalate_to, r.gender) == (True, "alone", "5550002", "female")
    rows = repo.list_audit(clock.iso(clock.now())[:10], "recipient:thunag/5550001")
    assert rows and rows[-1].action == "recipient_care_changed" and "assisted: False -> True" in rows[-1].reason
    r = assisted.set_care(repo, "thunag", "5550001", escalate_to="", gender="", actor="officer1", actor_role="officer")
    assert r.escalate_to is None and r.gender is None


def test_the_care_route_follows_the_relay_rule(api, repo, frozen):
    people(repo)
    body = {"assisted": True, "assisted_reason": "disabled", "escalate_to": "5550003"}
    r = api.post("/villages/thunag/recipients/5550001/care", json=body, headers=_h(api, "pradhan_thunag"))
    assert r.status_code == 200 and r.json()["assisted"] is True and r.json()["escalate_to"] == "5550003"
    assert api.post("/villages/gohar/recipients/5550001/care", json=body,
                    headers=_h(api, "pradhan_thunag")).status_code == 403
    assert api.post("/villages/thunag/recipients/5550001/care", json=body, headers=_h(api, "judge")).status_code == 403
    assert api.post("/villages/thunag/recipients/5550001/care", json={"gender": "x"},
                    headers=_h(api, "officer1")).status_code == 400
    care = api.get("/care/villages", headers=_h(api, "officer1")).json()
    thunag = next(v for v in care["villages"] if v["village_id"] == "thunag")
    assert thunag["assisted"] == 1 and thunag["observers"] == 3 and "observers" not in thunag["gaps"]
    assert "household_list" in thunag["gaps"] and thunag["coverage"] is None
    gohar = next(v for v in care["villages"] if v["village_id"] == "gohar")
    assert gohar["observers"] == 0 and "observers" in gohar["gaps"]  # demo stubs are not observers
    mine = api.get("/care/villages", headers=_h(api, "pradhan_thunag")).json()
    assert [v["village_id"] for v in mine["villages"]] == ["thunag"]


def test_village_readiness_wants_two_observers_and_counts_women(repo, frozen):
    repo.put_recipient(Recipient(id="1", village_id="gohar", name="Gita", channel="telegram", role="pradhan",
                                 gender="female"))
    c = assisted.village_care(repo, "gohar")
    assert c["observers"] == 1 and "observers" in c["gaps"]
    repo.put_recipient(Recipient(id="2", village_id="gohar", name="Raju", channel="telegram", role="gauge_reader",
                                 gender="male"))
    repo.put_recipient(Recipient(id="3", village_id="gohar", name="Dev", channel="telegram", role="task_force",
                                 gender="male"))
    c = assisted.village_care(repo, "gohar")
    assert c["observers"] == 3 and c["women_observers"] == 1 and "women_observers" in c["gaps"]
    repo.put_recipient(Recipient(id="4", village_id="gohar", name="Old", channel="telegram", assisted=True))
    c = assisted.village_care(repo, "gohar")
    assert c["assisted_without_neighbour"] == ["Old"] and "assisted_without_neighbour" in c["gaps"]
    repo.put_village(repo.get_village("gohar").model_copy(update={"households": 8}))
    c = assisted.village_care(repo, "gohar")
    assert c["coverage"] == 0.5 and "household_list" not in c["gaps"]
