"""The console's decision panel: an officer may change what a pending alert says (E) or set it aside for ten
minutes (S). An edit is held to the model draft's rules; a snooze changes nothing but the audit trail."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from Pukaar.core import clock
from Pukaar.policy.guard import Principal, evaluate
from Pukaar.services.drafting import check_officer_edit
from Pukaar.store.models import Alert, Village
from Pukaar.templates import hi


@pytest.fixture(scope="module")
def client():
    from Pukaar.main import app

    return TestClient(app)


def _h(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def _pending(repo, aid: str, *, replay: bool = False) -> Alert:
    text_hi, text_en = hi.fallback_alert("warning", "गोहर", "Gohar", None)
    now = clock.iso(clock.now())
    a = Alert(id=aid, village_id="gohar", village_name="Gohar", village_name_hi="गोहर", level="warning",
              previous_level="watch", status="pending", created_at=now, updated_at=now, replay=replay,
              text_hi=text_hi, text_en=text_en, decision_trace={"rules_fired": ["rain_24h>=115.6mm:warning"]})
    repo.put_alert(a)
    return a


def _close(repo, *ids: str) -> None:
    # The app's table is shared with tests that list pending alerts: leave nothing pending behind.
    for i in ids:
        if repo.get_alert(i):
            repo.update_alert(i, status="closed")


VILLAGE = Village(id="gohar", name="Gohar", name_hi="गोहर", district="Mandi", lat=31.5, lon=77.0)


def test_an_edit_keeps_the_village_the_level_and_the_numbers():
    old_hi, old_en = hi.fallback_alert("warning", "गोहर", "Gohar", None)
    ok = check_officer_edit(f"{old_hi} बुज़ुर्गों को पहले ले जाएँ।", old_en, old_hi, old_en, VILLAGE, "warning", ["Thunag", "थुनाग"])
    assert ok.passed, ok.reason
    assert "numbers" in check_officer_edit(old_hi + " 3 बजे तक।", old_en, old_hi, old_en, VILLAGE, "warning", []).reason
    assert "must name" in check_officer_edit(old_hi.replace("गोहर", "गाँव"), old_en, old_hi, old_en, VILLAGE, "warning", []).reason
    assert "level word" in check_officer_edit(old_hi.replace(hi.LEVEL_HI["warning"], "सूचना"), old_en, old_hi, old_en, VILLAGE, "warning", []).reason
    assert "another place" in check_officer_edit(old_hi + " थुनाग जाएँ।", old_en, old_hi, old_en, VILLAGE, "warning", ["थुनाग"]).reason
    assert "contradicts" in check_officer_edit(old_hi + " कोई ख़तरा नहीं।", old_en, old_hi, old_en, VILLAGE, "warning", []).reason
    assert "link" in check_officer_edit(old_hi + " www.x.in", old_en, old_hi, old_en, VILLAGE, "warning", []).reason


def test_an_officer_edits_a_pending_alert_and_the_trail_says_so(client):
    from Pukaar.store.repo import get_repo

    repo = get_repo()
    a = _pending(repo, "alr_edit_route")
    try:
        officer = _h(client, "officer1")
        new_hi = f"{a.text_hi} बुज़ुर्गों और बच्चों को पहले ले जाएँ।"
        r = client.post(f"/alerts/{a.id}/edit", json={"text_hi": new_hi, "text_en": a.text_en}, headers=officer)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["text_hi"] == new_hi and body["status"] == "pending"
        assert "edited by officer1" in body["draft_check"]["reason"] and body["draft_check"]["passed"] is True
        assert any(t.step == "edited" for t in repo.list_timeline(a.id))
        # A new number, or a pradhan, or no sign-in: refused, and nothing changes.
        bad = client.post(f"/alerts/{a.id}/edit", json={"text_hi": new_hi + " 7 बजे।"}, headers=officer)
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "edit_rejected"
        assert client.post(f"/alerts/{a.id}/edit", json={"text_hi": new_hi}, headers=_h(client, "pradhan_thunag")).status_code == 403
        assert client.post(f"/alerts/{a.id}/edit", json={"text_hi": new_hi}).status_code == 401
        assert repo.get_alert(a.id).text_hi == new_hi
        # The public demo account cannot change what a live alert says.
        assert client.post(f"/alerts/{a.id}/edit", json={"text_hi": a.text_hi}, headers=_h(client, "judge")).status_code == 403
        # Once decided, it can no longer be edited.
        repo.update_alert(a.id, status="declined")
        assert client.post(f"/alerts/{a.id}/edit", json={"text_hi": a.text_hi}, headers=officer).status_code == 409
    finally:
        _close(repo, a.id)


def test_snooze_sets_an_alert_aside_and_changes_nothing_else(client):
    from Pukaar.store.repo import get_repo

    repo = get_repo()
    a = _pending(repo, "alr_snooze_route")
    replay = _pending(repo, "alr_snooze_replay", replay=True)
    try:
        r = client.post(f"/alerts/{a.id}/snooze", json={"minutes": 10}, headers=_h(client, "officer1"))
        assert r.status_code == 200, r.text
        until = datetime.fromisoformat(r.json()["snoozed_until"].replace("Z", "+00:00"))
        assert 9.5 * 60 <= (until - clock.now()).total_seconds() <= 10.5 * 60
        after = repo.get_alert(a.id)
        assert after.status == "pending" and after.officer_index == a.officer_index
        assert any(t.step == "snoozed" and "escalation continues" in t.detail for t in repo.list_timeline(a.id))
        assert client.post(f"/alerts/{a.id}/snooze", headers=_h(client, "judge")).status_code == 403
        assert client.post(f"/alerts/{a.id}/snooze", headers=_h(client, "pradhan_thunag")).status_code == 403
        # The demo account may snooze a replay alert: nothing it does there reaches a phone.
        assert client.post(f"/alerts/{replay.id}/snooze", headers=_h(client, "judge")).status_code == 200
    finally:
        _close(repo, a.id, replay.id)


def test_no_agent_may_edit_an_alert():
    agent = Principal(username="drafting-agent", role="agent", village_ids=[])
    assert not evaluate(agent, "edit_alert", "alert", "alr_x", {"village_id": "gohar"}).allowed
