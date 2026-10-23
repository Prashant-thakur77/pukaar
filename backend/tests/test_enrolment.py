"""Enrolling households (services/enrolment.py, api/routers/reach.py): the officer and pradhan form, the vetted
CSV import, Cedar (an officer in their district, a pradhan in their own village), the consent record and the
audit trail. No phone number is ever written to the audit trail or returned unmasked."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from Pukaar.core import clock
from Pukaar.policy.guard import Principal, evaluate
from Pukaar.services import enrolment
from Pukaar.store.models import Village

PHONE = "+919812345678"
CONSENT = {"method": "in_person", "given_by": "self", "taken_by": "Asha (ASHA worker)", "date": "2026-06-30"}


def _audit(repo, action):
    return [r for r in repo.list_audit(clock.iso(clock.now())[:10]) if r.action == action]


def test_phone_numbers_are_normalised_from_list_forms():
    for raw in ("98123 45678", "09812345678", "919812345678", "+91 98123-45678", "0091 9812345678"):
        assert enrolment.normalise_phone(raw) == PHONE, raw
    for bad in ("12345", "+91 5812345678", "phone"):
        with pytest.raises(enrolment.EnrolError):
            enrolment.normalise_phone(bad)


def test_the_form_adds_a_household_with_its_consent_record_and_audits_it(repo, frozen):
    v = repo.get_village("thunag")
    person, created = enrolment.save(repo, v, {"phone": "98123 45678", "assisted": True, "role": "villager",
                                                "consent": CONSENT}, actor="officer1", actor_role="officer")
    assert created and person.phone == PHONE and person.channel == "voice" and person.name == enrolment.DEFAULT_NAME
    assert person.assisted is True and person.enrolled_via == "form" and person.enrolled_by == "officer1"
    assert "in_person" in person.consent and "taken by Asha" in person.consent
    assert enrolment.NOTICE_VERSION in person.consent and "entered by officer1" in person.consent
    row = _audit(repo, "household_enrolled")[0]
    assert PHONE not in row.reason and "+91******78" in row.reason
    view = enrolment.view(person)
    assert view["phone_masked"] == "+91******78" and "phone" not in view


def test_consent_is_required_and_checked(repo, frozen):
    v = repo.get_village("thunag")
    with pytest.raises(enrolment.EnrolError, match="consent method"):
        enrolment.save(repo, v, {"phone": PHONE}, actor="officer1", actor_role="officer")
    with pytest.raises(enrolment.EnrolError, match="consent date"):
        enrolment.save(repo, v, {"phone": PHONE, "consent": {**CONSENT, "date": "2030-01-01"}},
                       actor="officer1", actor_role="officer")
    assert not [r for r in repo.list_recipients("thunag") if r.phone == PHONE]


def test_edit_keeps_the_consent_unless_the_number_changes_and_duplicates_are_refused(repo, frozen):
    v = repo.get_village("thunag")
    person, _ = enrolment.save(repo, v, {"phone": PHONE, "name": "Asha Devi", "consent": CONSENT},
                               actor="officer1", actor_role="officer")
    edited, created = enrolment.save(repo, v, {"recipient_id": person.id, "role": "gauge_reader", "assisted": False},
                                     actor="pradhan_thunag", actor_role="pradhan")
    assert not created and edited.role == "gauge_reader" and edited.consent == person.consent
    assert "role villager -> gauge_reader" in _audit(repo, "household_updated")[0].reason
    with pytest.raises(enrolment.EnrolError, match="consent method"):  # a new number needs new consent
        enrolment.save(repo, v, {"recipient_id": person.id, "phone": "+919812345600"}, actor="officer1",
                       actor_role="officer")
    with pytest.raises(enrolment.EnrolError, match="already enrolled"):
        enrolment.save(repo, v, {"phone": "9812345678", "consent": CONSENT}, actor="officer1", actor_role="officer")
    with pytest.raises(enrolment.EnrolError, match="Telegram is joined by the person"):
        enrolment.save(repo, v, {"phone": "+919812345611", "channel": "telegram", "consent": CONSENT},
                       actor="officer1", actor_role="officer")


def test_remove_takes_the_household_off_and_schedules_erasure(repo, frozen):
    v = repo.get_village("thunag")
    person, _ = enrolment.save(repo, v, {"phone": PHONE, "consent": CONSENT}, actor="officer1", actor_role="officer")
    assert enrolment.remove(repo, v, person.id, actor="officer1", actor_role="officer", reason="moved away")
    assert repo.get_recipient("thunag", person.id) is None
    assert any(e["recipient_id"] == person.id for e in repo.list_erasures())
    assert "moved away" in _audit(repo, "household_removed")[0].reason


CSV = """Name,Mobile,Assisted,Consent method,Given by,Consent date
Asha Devi,98123 45678,yes,in_person,self,2026-06-30
Ram Lal,98123 45679,,,,
Bad,12345,,in_person,self,2026-06-30
Asha again,+919812345678,,in_person,self,2026-06-30
Mohan,9812345680,no,signed_form,family,2026-06-29
"""


def test_the_import_previews_every_row_and_stores_nothing(repo, frozen):
    v = repo.get_village("thunag")
    before = len(repo.list_recipients("thunag"))
    rows = {r.n: r for r in enrolment.preview(repo, v, CSV, {}, "officer1")}
    assert rows[1].status == "ok" and rows[5].status == "ok"
    assert rows[2].status == "error" and any("consent" in e for e in rows[2].errors)  # no consent given
    assert rows[3].status == "error" and any("mobile" in e for e in rows[3].errors)
    assert rows[4].status == "duplicate" and rows[4].duplicate_of == 1
    assert len(repo.list_recipients("thunag")) == before
    # A default attestation fills a row that has none.
    with_default = {r.n: r for r in enrolment.preview(repo, v, CSV, {"method": "in_person"}, "officer1")}
    assert with_default[2].status == "ok"


def test_commit_stores_only_attested_ok_rows(repo, frozen):
    v = repo.get_village("thunag")
    enrolment.save(repo, v, {"phone": "+919812345680", "consent": CONSENT}, actor="officer1", actor_role="officer")
    with pytest.raises(enrolment.EnrolError, match="tick the rows"):
        enrolment.commit(repo, v, CSV, attested_rows=[], attestation={}, source="panchayat list", actor="officer1",
                         actor_role="officer")
    out = enrolment.commit(repo, v, CSV, attested_rows=[1, 4, 5], attestation={"taken_by": "Patwari Gohar"},
                           source="panchayat household list 2026", actor="officer1", actor_role="officer")
    assert [s["row"] for s in out["stored"]] == [1]  # 4 is a duplicate, 5 already enrolled, 2 and 3 not ok
    reasons = {s["row"]: s["reason"] for s in out["skipped"]}
    assert reasons == {2: "error", 3: "error", 4: "duplicate", 5: "exists"}
    stored = repo.get_recipient("thunag", out["stored"][0]["recipient_id"])
    assert stored.assisted and stored.enrolled_via.startswith("csv: panchayat") and "Patwari Gohar" in stored.consent
    summary = _audit(repo, "households_imported")[0]
    assert "1 stored with attested consent" in summary.reason


def test_cedar_officer_in_district_pradhan_in_own_village():
    pr = Principal("pradhan_thunag", "pradhan", ["thunag"])
    assert evaluate(pr, "enrol_household", "village", "thunag", {"village_id": "thunag"}).allowed
    assert not evaluate(pr, "enrol_household", "village", "gohar", {"village_id": "gohar"}).allowed
    off = Principal("asha", "officer")
    ctx = {"village_id": "gohar", "district": "Mandi", "scoped": True}
    assert evaluate(off, "enrol_household", "village", "gohar", {**ctx, "in_scope": True}).allowed
    assert not evaluate(off, "enrol_household", "village", "gohar", {**ctx, "in_scope": False}).allowed
    assert not evaluate(Principal("judge", "officer"), "enrol_household", "village", "gohar",
                        {**ctx, "in_scope": True}).allowed
    assert not evaluate(Principal("bot", "agent"), "enrol_household", "village", "gohar", ctx).allowed


@pytest.fixture()
def client(repo, monkeypatch):
    from Pukaar.api import auth
    from Pukaar.api.routers import reach
    from Pukaar.main import app

    for mod in (auth, reach):
        monkeypatch.setattr(mod, "get_repo", lambda: repo)
    monkeypatch.setattr("Pukaar.store.repo.get_repo", lambda: repo)
    return TestClient(app)


def _token(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_routes(client, repo, frozen):
    officer, pradhan = _token(client, "officer1"), _token(client, "pradhan_thunag")
    r = client.post("/villages/thunag/households", json={"phone": "9812345678", "consent": CONSENT}, headers=pradhan)
    assert r.status_code == 200 and r.json()["created"] and r.json()["household"]["phone_masked"] == "+91******78"
    assert client.post("/villages/gohar/households", json={"phone": "9812345679", "consent": CONSENT},
                       headers=pradhan).status_code == 403
    assert client.post("/villages/thunag/households", json={"phone": "9812345679"}, headers=officer).status_code == 400
    listed = client.get("/villages/thunag/households", headers=officer).json()
    assert listed["ivr_code"] == "1001" and PHONE not in str(listed)
    assert any(h["phone_masked"] == "+91******78" for h in listed["households"])
    prev = client.post("/villages/thunag/households/import", json={"csv": CSV}, headers=officer).json()
    assert prev["counts"]["ok"] == 1 and prev["counts"]["exists"] == 1  # row 1 was enrolled above
    assert "result" not in prev and PHONE not in str(prev)
    done = client.post("/villages/thunag/households/import",
                       json={"csv": CSV, "commit": True, "source": "patwari list", "attested_rows": [5]},
                       headers=officer).json()
    assert [s["row"] for s in done["result"]["stored"]] == [5]
    rid = done["result"]["stored"][0]["recipient_id"]
    assert client.delete(f"/villages/thunag/households/{rid}", headers=officer).json() == {"removed": True}
    assert client.post("/villages/thunag/households", json={"phone": "9812345611", "consent": CONSENT},
                       headers=_token(client, "judge")).status_code == 403


def test_a_village_of_another_district_is_refused_to_an_officer_there(client, repo, frozen):
    repo.put_village(Village(id="kasol", name="Kasol", name_hi="कसोल", district="Kullu", lat=32.0, lon=77.3))
    r = client.post("/villages/kasol/households", json={"phone": "9812345678", "consent": CONSENT},
                    headers=_token(client, "officer1"))
    assert r.status_code == 403
