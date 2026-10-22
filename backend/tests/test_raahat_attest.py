"""Impact attestation and payout receipts (raahat/attest.py, raahat/receipts.py; PLAN.md Step 3).

Three attesters, each once per alert: the satellite (Sentinel-2 water before and after, severity from the newly
flooded share of the compared area), a district officer, and the village's pradhan (a verified photo report's S3
object hash). Receipts: the village's cash-out agent records one per household with a Merkle proof built from the
register snapshot and a hash of the UPI or cash reference. A fake chain client stands in for the RPC.
"""

from __future__ import annotations

import json

import pytest
from eth_utils import keccak

from Pukaar.policy.guard import Principal, evaluate
from Pukaar.raahat import anchor, attest, households, receipts
from test_raahat_relief import FakeChain, _anchored, _bearer

OFFICER = Principal("officer1", "officer")
PRADHAN = Principal("pradhan_thunag", "pradhan", ["thunag"])
JUDGE = Principal("judge", "officer")
JUDGE_PRADHAN = Principal("judge_pradhan", "pradhan", ["thunag"])


class FakeAttestChain(FakeChain):
    def __init__(self, **over):
        super().__init__(**over)
        self.attested: list[tuple] = []
        self.receipted: list[tuple] = []
        self.onchain: dict[int, dict] = {}

    def attest(self, alert_key, who, severity, evidence_hash, *, village_id=""):
        if self.fail:
            return None
        self.attested.append((alert_key, who, severity, evidence_hash))
        self.onchain[who] = {"by": f"0x{who:040x}", "severity": severity, "evidence_hash": "0x" + evidence_hash.hex()}
        return "0x" + keccak(alert_key + bytes([who])).hex()

    def read_attestations(self, alert_key):
        sev = [a["severity"] for a in self.onchain.values()]
        return {"attestations": dict(self.onchain), "confirmed": sum(1 for s in sev if s >= 2) >= 2}

    roots: dict = {}

    def household_root(self, village_key):
        return self.roots.get(village_key)

    def receipt(self, alert_key, household, proof, upi_ref_hash):
        if self.fail:
            return None
        self.receipted.append((alert_key, household, proof, upi_ref_hash))
        return "0x" + keccak(household).hex()


@pytest.fixture()
def fake(monkeypatch, repo):
    from Pukaar.handlers import worker
    from Pukaar.raahat import relief
    from Pukaar.store.models import ReplayState

    monkeypatch.setattr(worker, "get_repo", lambda: repo)
    monkeypatch.setattr(worker, "dispatch", lambda event: worker.run_task(event))
    repo.put_replay(ReplayState(active=True, scenario="himachal_2023_07"))  # the replay the 2023 imagery is from
    c = FakeAttestChain()
    for mod in (relief, attest, receipts):
        monkeypatch.setattr(mod, "_client", lambda: c)
    return c


# -- satellite ---------------------------------------------------------------------------------------------
def test_severity_from_the_newly_flooded_share():
    assert attest.severity_from_fraction(0.0, 300) == 0
    assert attest.severity_from_fraction(-1.0, 300) == 0  # less water than before is no evidence of a flood
    assert attest.severity_from_fraction(0.1, 300) == 1   # 0.03%
    assert attest.severity_from_fraction(0.6, 300) == 2   # 0.2%
    assert attest.severity_from_fraction(2.03, 317.7) == 3  # July 2023: 0.64% of the crop newly water
    assert attest.severity_from_fraction(1.0, 0) == 0


def test_evidence_file_is_what_the_baked_imagery_gives():
    """data/raahat/satellite_2023.json is rebuilt from frontend/public/satellite/2023 by attest.bake()."""
    assert json.loads(attest.EVIDENCE_FILE.read_text(encoding="utf-8")) == attest.bake()


def test_satellite_covers_only_villages_inside_the_crop():
    ev = attest.bake()
    assert ev["covers"] == ["pandoh"]
    after = ev["scenes"][0]
    assert after["date"] == "2023-07-23" and after["severity"] == 3
    png = (attest.SATELLITE_DIR / after["water"]).read_bytes()
    assert after["evidence_hash"] == "0x" + keccak(png).hex()  # anyone can re-hash the public PNG


def test_satellite_attests_a_replay_in_coverage_and_refuses_elsewhere(repo, frozen, fake):
    a = _anchored(repo, village="pandoh")
    out = attest.attest_satellite(repo, a.id, by="officer1")
    assert out["state"] == "sent" and out["severity"] == 3
    key, who, severity, evidence = fake.attested[0]
    assert (key, who, severity) == (anchor.alert_key(a.id), attest.SATELLITE, 3)
    assert "0x" + evidence.hex() == attest.bake()["scenes"][0]["evidence_hash"]
    b = _anchored(repo, village="sujanpur")
    with pytest.raises(attest.AttestRefused) as e:
        attest.attest_satellite(repo, b.id, by="officer1")
    assert e.value.code == "no_satellite_coverage"


def test_satellite_never_attests_a_live_alert_from_2023_imagery(repo, frozen, fake):
    a = _anchored(repo, village="pandoh", replay=False)
    with pytest.raises(attest.AttestRefused) as e:
        attest.attest_satellite(repo, a.id, by="officer1")
    assert e.value.code == "no_satellite_coverage"


# -- officer and pradhan -----------------------------------------------------------------------------------
def test_officer_attests_once_with_a_hash_of_the_note(repo, frozen, fake):
    a = _anchored(repo, village="pandoh")
    out = attest.attest_officer(repo, a.id, severity=2, note="Bridge at Pandoh under water", by="officer1")
    assert out["state"] == "sent" and fake.attested[0][1] == attest.OFFICER
    with pytest.raises(attest.AttestRefused) as e:
        attest.attest_officer(repo, a.id, severity=3, note="again", by="officer2")
    assert e.value.code == "already_attested"


def test_pradhan_attests_from_a_verified_photo_report_of_the_village(repo, frozen, fake):
    from Pukaar.services import storage

    a = _anchored(repo, village="thunag")
    rid = _report(repo, "thunag", state="verified", photo=b"\xff\xd8 flood photo")
    out = attest.attest_pradhan(repo, a.id, report_id=rid, severity=3, by="pradhan_thunag")
    assert out["state"] == "sent"
    _, who, severity, evidence = fake.attested[0]
    assert (who, severity) == (attest.PRADHAN, 3)
    assert evidence == keccak(storage.get_bytes(repo.get_report(rid).photo_key)[0])


@pytest.mark.parametrize("state, photo, village, code", [
    ("unverified", b"img", "thunag", "report_not_verified"),
    ("verified", None, "thunag", "report_has_no_photo"),
    ("verified", b"img", "gohar", "report_from_another_village"),
])
def test_pradhan_attestation_needs_a_verified_photo_of_this_village(repo, frozen, fake, state, photo, village, code):
    a = _anchored(repo, village="thunag")
    rid = _report(repo, village, state=state, photo=photo)
    with pytest.raises(attest.AttestRefused) as e:
        attest.attest_pradhan(repo, a.id, report_id=rid, severity=2, by="pradhan_thunag")
    assert e.value.code == code and fake.attested == []


def test_status_reads_the_chain_and_says_when_confirmed(repo, frozen, fake):
    a = _anchored(repo, village="pandoh")
    attest.attest_officer(repo, a.id, severity=2, note="seen", by="officer1")
    assert attest.status(repo, a.id)["confirmed"] is False
    attest.attest_satellite(repo, a.id, by="officer1")
    st = attest.status(repo, a.id)
    assert st["confirmed"] is True and set(st["attestations"]) == {"pradhan", "officer", "satellite"}
    assert st["attestations"]["pradhan"] is None and st["attestations"]["satellite"]["severity"] == 3
    assert st["satellite_covers"] is True


def test_failed_attestation_can_be_sent_again(repo, frozen, fake):
    a = _anchored(repo, village="pandoh")
    fake.fail = True
    assert attest.attest_officer(repo, a.id, severity=2, note="x", by="officer1")["state"] == "failed"
    fake.fail = False
    assert attest.attest_officer(repo, a.id, severity=2, note="x", by="officer1")["state"] == "sent"


# -- Cedar ----------------------------------------------------------------------------------------------------
def test_cedar_attest_impact():
    live = {"replay": False, "village_id": "thunag"}
    assert evaluate(OFFICER, "attest_impact", "alert", "a", live).allowed
    assert evaluate(PRADHAN, "attest_impact", "alert", "a", live).allowed
    other = evaluate(PRADHAN, "attest_impact", "alert", "a", {"replay": False, "village_id": "gohar"})
    assert not other.allowed and "own village" in other.reason
    assert not evaluate(JUDGE, "attest_impact", "alert", "a", live).allowed
    assert evaluate(JUDGE, "attest_impact", "alert", "a", {"replay": True, "village_id": "gohar"}).allowed
    assert not evaluate(JUDGE_PRADHAN, "attest_impact", "alert", "a", live).allowed


def test_cedar_record_receipt_is_the_pradhans_of_the_village():
    live = {"replay": False, "village_id": "thunag"}
    assert evaluate(PRADHAN, "record_receipt", "alert", "a", live).allowed
    d = evaluate(PRADHAN, "record_receipt", "alert", "a", {"replay": False, "village_id": "gohar"})
    assert not d.allowed and "own village" in d.reason
    assert not evaluate(OFFICER, "record_receipt", "alert", "a", live).allowed
    assert not evaluate(JUDGE_PRADHAN, "record_receipt", "alert", "a", live).allowed
    assert evaluate(JUDGE_PRADHAN, "record_receipt", "alert", "a", {"replay": True, "village_id": "thunag"}).allowed


# -- receipts --------------------------------------------------------------------------------------------------
def _released(repo, village="thunag"):
    from Pukaar.raahat import relief

    a = _anchored(repo, village=village)
    households.seed(repo, None, households.LOCAL_SALT)
    relief.release(repo, a.id, 1, by="officer1")
    return a


def test_household_list_shows_first_names_and_demo_labels_only(repo, frozen, fake):
    from Pukaar.store.models import Recipient

    repo.put_recipient(Recipient(id="555001", village_id="thunag", name="Asha Devi", channel="telegram",
                                 phone=None))
    a = _released(repo)
    rows = receipts.households_for(repo, a.id)
    assert len(rows) == 28  # 2 demo phones + Asha + 25 labelled demo households
    labels = {r["label"] for r in rows}
    assert "Asha" in labels and "Asha Devi" not in json.dumps(rows) and "555001" not in json.dumps(rows)
    assert all(r["receipt"] is None for r in rows)


def test_record_receipt_with_proof_once_per_household(repo, frozen, fake):
    a = _released(repo)
    row = receipts.households_for(repo, a.id)[0]
    out = receipts.record(repo, a.id, row["household"], "UPI-REF-417", by="pradhan_thunag")
    assert out["state"] == "sent"
    key, hh_, proof, upi = fake.receipted[0]
    assert key == anchor.alert_key(a.id) and "0x" + hh_.hex() == row["household"]
    assert upi == keccak(text="UPI-REF-417")
    tree = households.snapshot_tree(repo, "thunag")
    assert proof == tree.proof(hh_)
    with pytest.raises(receipts.ReceiptRefused) as e:
        receipts.record(repo, a.id, row["household"], "UPI-REF-418", by="pradhan_thunag")
    assert e.value.code == "already_receipted"
    assert receipts.households_for(repo, a.id)[0]["receipt"]["state"] == "sent"
    assert "UPI-REF-417" not in json.dumps(repo._query(anchor.PK + a.id), default=str)  # only its hash is kept


def test_receipt_refusals(repo, frozen, fake):
    a = _released(repo)
    stranger = "0x" + households.household_hash("gohar", "x", households.LOCAL_SALT).hex()
    with pytest.raises(receipts.ReceiptRefused) as e:
        receipts.record(repo, a.id, stranger, "UPI-1", by="pradhan_thunag")
    assert e.value.code == "household_not_in_village"
    b = _anchored(repo, village="gohar")  # anchored, nothing released
    households.seed(repo, None, households.LOCAL_SALT)
    gh = receipts.households_for(repo, b.id)[0]["household"]
    with pytest.raises(receipts.ReceiptRefused) as e:
        receipts.record(repo, b.id, gh, "UPI-2", by="pradhan")
    assert e.value.code == "nothing_released"
    with pytest.raises(receipts.ReceiptRefused) as e:
        receipts.record(repo, a.id, receipts.households_for(repo, a.id)[1]["household"], "  ", by="pradhan")
    assert e.value.code == "no_reference"


# -- the API -----------------------------------------------------------------------------------------------------
@pytest.fixture()
def api(monkeypatch, repo):
    from fastapi.testclient import TestClient

    import Pukaar.api.auth as auth
    import Pukaar.api.routers.raahat as routes
    from Pukaar.main import app

    monkeypatch.setattr(routes, "get_repo", lambda: repo)
    monkeypatch.setattr(auth, "get_repo", lambda: repo)
    return TestClient(app), auth


def test_api_attest_and_receipt_follow_cedar(api, repo, frozen, fake):
    client, auth = api
    a = _released(repo)  # thunag, a replay
    officer = client.post(f"/raahat/alerts/{a.id}/attest", json={"who": "officer", "severity": 2, "note": "seen"},
                          headers=_bearer(auth, "officer1"))
    assert officer.status_code == 200 and officer.json()["state"] == "sent"
    sat = client.post(f"/raahat/alerts/{a.id}/attest", json={"who": "satellite"}, headers=_bearer(auth, "officer1"))
    assert sat.status_code == 409 and sat.json()["detail"]["code"] == "no_satellite_coverage"
    hh_ = client.get(f"/raahat/alerts/{a.id}/households", headers=_bearer(auth, "pradhan_thunag")).json()
    r = client.post("/raahat/receipts", json={"alert_id": a.id, "household": hh_[0]["household"],
                                              "upi_ref": "UPI-9"}, headers=_bearer(auth, "pradhan_thunag"))
    assert r.status_code == 200 and r.json()["state"] == "sent"
    assert client.post("/raahat/receipts", json={"alert_id": a.id, "household": hh_[1]["household"], "upi_ref": "U"},
                       headers=_bearer(auth, "officer1")).status_code == 403
    assert client.get(f"/raahat/alerts/{a.id}/attestations").status_code == 200  # public


def test_api_pradhan_cannot_attest_as_officer(api, repo, frozen, fake):
    client, auth = api
    a = _released(repo)
    r = client.post(f"/raahat/alerts/{a.id}/attest", json={"who": "officer", "severity": 2, "note": "x"},
                    headers=_bearer(auth, "pradhan_thunag"))
    assert r.status_code == 403 and fake.attested == []


# -- helpers -----------------------------------------------------------------------------------------------------
def _report(repo, village: str, *, state: str, photo: bytes | None) -> str:
    from Pukaar.core import clock
    from Pukaar.core.ids import new_id
    from Pukaar.services import storage
    from Pukaar.store.models import Report

    rid = new_id("rep")
    key = None
    if photo is not None:
        key = f"reports/{rid}/photo.jpg"
        storage.put_bytes(key, photo, "image/jpeg")
    now = clock.iso(clock.now())
    repo.put_report(Report(id=rid, village_id=village, report_type="water_rising", state=state, created_at=now,
                           photo_key=key, text="water at the bridge", replay=True))
    return rid


def test_satellite_refuses_imagery_from_another_flood(repo, frozen, fake):
    """The 2023 Sentinel-2 pair is never evidence for a replay of a different flood (Mandi 2025)."""
    from Pukaar.store.models import ReplayState

    a = _anchored(repo, village="pandoh")
    repo.put_replay(ReplayState(active=True, scenario="mandi_2025"))
    with pytest.raises(attest.AttestRefused) as e:
        attest.attest_satellite(repo, a.id, by="officer1")
    assert e.value.code == "no_satellite_coverage" and fake.attested == []


def test_ledger_shows_attesters_confirmation_and_receipts_without_names(repo, frozen, fake):
    from Pukaar.raahat import relief

    a = _released(repo, village="pandoh")
    attest.attest_officer(repo, a.id, severity=2, note="Officer Sharma saw it", by="officer1")
    attest.attest_satellite(repo, a.id, by="officer1")
    row = receipts.households_for(repo, a.id)[0]
    receipts.record(repo, a.id, row["household"], "UPI-REF-77", by="pradhan_pandoh")
    item = next(i for i in relief.ledger(repo)["items"] if i["alert_id"] == a.id)
    assert set(item["attestations"]) == {"officer", "satellite"} and item["confirmed"] is True
    assert item["attestations"]["satellite"]["severity"] == 3 and item["receipts"] == 1
    text = json.dumps(relief.ledger(repo), default=str)
    assert "Sharma" not in text and "UPI-REF-77" not in text and "officer1" not in text


def test_missing_snapshot_is_rebuilt_only_when_it_matches_the_root_on_chain(repo, frozen, fake):
    """The API's table may lack the snapshot the seeding run wrote (local mode: another process). It is rebuilt
    from the register, and kept only if its root is the one on chain; otherwise no proof is ever built from it."""
    from Pukaar.raahat import relief

    a = _anchored(repo, village="thunag")
    tree = households.tree_of("thunag", (households.household_hash("thunag", no, households.LOCAL_SALT)
                                         for no, _ in households.register(repo, "thunag")))
    fake.roots = {households.village_key("thunag"): tree.root}
    relief.release(repo, a.id, 1, by="officer1")
    assert households.snapshot(repo, "thunag") is None
    rows = receipts.households_for(repo, a.id)
    assert len(rows) == 27 and households.snapshot(repo, "thunag")["root"] == "0x" + tree.root.hex()

    b = _anchored(repo, village="gohar")
    fake.roots[households.village_key("gohar")] = b"\x01" * 32  # the chain holds a different register
    with pytest.raises(receipts.ReceiptRefused) as e:
        receipts.households_for(repo, b.id)
    assert e.value.code == "register_changed" and households.snapshot(repo, "gohar") is None


def test_demo_photo_report_is_a_replay_never_a_live_report(repo, frozen, fake):
    """make raahat-demo-photo: a labelled demo photo for the pradhan's attestation in a replay. It is filed as a
    replay report (never on the live village page, never raising a live level) and verified by the demo officer."""
    from Pukaar.raahat import demo

    rid = demo.photo_report(repo, "pandoh", b"\xff\xd8 labelled demo photo", by="officer1")
    r = repo.get_report(rid)
    assert r.replay is True and r.state == "verified" and r.verified_by == "officer1" and r.photo_key
    assert "DEMO" in r.text and "replay" in r.text.lower()
    a = _anchored(repo, village="pandoh")
    out = attest.attest_pradhan(repo, a.id, report_id=rid, severity=2, by="pradhan_pandoh")
    assert out["state"] == "sent"


# -- review fix: a pradhan's photo is evidence for this alert only ------------------------------------------
def test_pradhan_evidence_must_belong_to_this_alert(repo, frozen, fake):
    from datetime import timedelta

    from Pukaar.core import clock

    live = _anchored(repo, village="thunag", replay=False)
    replay_photo = _report(repo, "thunag", state="verified", photo=b"img")  # _report files replay reports
    with pytest.raises(attest.AttestRefused) as e:
        attest.attest_pradhan(repo, live.id, report_id=replay_photo, severity=2, by="pradhan_thunag")
    assert e.value.code == "report_from_another_flood"  # a replay's (or demo) photo never attests a live alert

    a = _anchored(repo, village="thunag")
    old = _report(repo, "thunag", state="verified", photo=b"old")
    r = repo.get_report(old)
    repo.put_report(r.model_copy(update={"created_at": clock.iso(clock.now() - timedelta(days=400))}))
    with pytest.raises(attest.AttestRefused) as e:
        attest.attest_pradhan(repo, a.id, report_id=old, severity=2, by="pradhan_thunag")
    assert e.value.code == "report_too_old"

    fresh = _report(repo, "thunag", state="verified", photo=b"fresh")
    assert attest.attest_pradhan(repo, a.id, report_id=fresh, severity=2, by="pradhan_thunag")["state"] == "sent"
    b = _anchored(repo, village="thunag")
    with pytest.raises(attest.AttestRefused) as e:
        attest.attest_pradhan(repo, b.id, report_id=fresh, severity=2, by="pradhan_thunag")
    assert e.value.code == "report_already_used"
