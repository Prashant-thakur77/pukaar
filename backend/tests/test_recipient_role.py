"""A pradhan registered on Telegram can be made a relay (pradhan, gauge reader, task force).

/start <village> registers an ordinary villager. The operator script (make voice-add ROLE=... CHAT=...,
make recipient-role) and an officer-only API route (a pradhan for their own village; the public demo
accounts refused) set the role; every change is audited. services/recipients.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from Pukaar.policy.guard import Principal, evaluate
from Pukaar.scripts import voice as voice_script
from Pukaar.store.models import Recipient

CHAT = "5551234"


def telegram_person(repo, village="thunag", chat=CHAT, name="Ram Lal"):
    repo.put_recipient(Recipient(id=chat, village_id=village, name=name, channel="telegram"))


@pytest.fixture()
def script_repo(repo, monkeypatch):
    monkeypatch.setattr(voice_script, "get_repo", lambda: repo)
    return repo


# -- the script ------------------------------------------------------------------------------------
def test_voice_add_with_a_chat_id_honours_role(script_repo, capsys):
    repo = script_repo
    telegram_person(repo)
    voice_script.add("thunag", "Ram Lal", "+919811111111", "verbal, 2026-10-25", "pradhan", CHAT)
    r = repo.get_recipient("thunag", CHAT)
    assert (r.role, r.channel, r.is_relay) == ("pradhan", "both", True)
    assert "pradhan" in capsys.readouterr().out


def test_voice_add_with_a_chat_id_and_no_role_keeps_the_existing_role(script_repo):
    repo = script_repo
    repo.put_recipient(Recipient(id=CHAT, village_id="thunag", name="Ram Lal", channel="telegram",
                                 role="gauge_reader"))
    voice_script.add("thunag", "Ram Lal", "+919811111111", "verbal", "", CHAT)
    assert repo.get_recipient("thunag", CHAT).role == "gauge_reader"


def test_voice_add_new_voice_person_takes_the_role_and_refuses_an_unknown_one(script_repo):
    repo = script_repo
    voice_script.add("thunag", "Sita", "+919822222222", "verbal", "task_force")
    assert [r.role for r in repo.list_recipients("thunag") if r.name == "Sita"] == ["task_force"]
    with pytest.raises(SystemExit, match="role must be one of"):
        voice_script.add("thunag", "Gita", "+919833333333", "verbal", "officer")


def test_role_command_sets_a_telegram_person_by_chat_id(script_repo, capsys):
    repo = script_repo
    telegram_person(repo)
    voice_script.main(["role", "thunag", CHAT, "pradhan"])
    assert repo.get_recipient("thunag", CHAT).role == "pradhan"
    voice_script.main(["role", "thunag", CHAT, "villager"])
    assert repo.get_recipient("thunag", CHAT).role == "villager"
    with pytest.raises(SystemExit, match="no recipient"):
        voice_script.main(["role", "thunag", "999", "pradhan"])
    with pytest.raises(SystemExit, match="role must be one of"):
        voice_script.main(["role", "thunag", CHAT, "boss"])


def test_the_makefile_passes_role_through_unchanged():
    from pathlib import Path

    make = (Path(__file__).resolve().parents[2] / "Makefile").read_text(encoding="utf-8")
    add = make.split("\nvoice-add:", 1)[1].split("\n\n", 1)[0]
    assert '"$(ROLE)" "$(CHAT)"' in add  # empty ROLE keeps an existing role; no silent "villager"
    assert "\nrecipient-role:" in make and "Pukaar.scripts.voice role" in make


# -- Cedar --------------------------------------------------------------------------------------------
OFFICER = Principal("officer1", "officer")
PRADHAN = Principal("pradhan_thunag", "pradhan", ["thunag"])


def test_cedar_officers_anywhere_pradhan_own_village_demo_and_agents_never():
    ctx = {"village_id": "gohar"}
    assert evaluate(OFFICER, "set_recipient_role", "village", "gohar", ctx).allowed
    assert evaluate(PRADHAN, "set_recipient_role", "village", "thunag", {"village_id": "thunag"}).allowed
    denied = evaluate(PRADHAN, "set_recipient_role", "village", "gohar", ctx)
    assert not denied.allowed and "pradhan of this village" in denied.reason
    assert not evaluate(PRADHAN, "set_recipient_role", "village", "thunag", {"village_id": ""}).allowed
    for judge in (Principal("judge", "officer"), Principal("judge_pradhan", "pradhan", ["thunag"])):
        d = evaluate(judge, "set_recipient_role", "village", "thunag", {"village_id": "thunag"})
        assert not d.allowed and d.policy_ids == ["public-demo-accounts-replay-only"]
    assert not evaluate(Principal("drafting-agent", "agent"), "set_recipient_role", "village", "thunag",
                        {"village_id": "thunag"}).allowed


# -- the API route ----------------------------------------------------------------------------------
@pytest.fixture()
def client(repo, monkeypatch):
    from Pukaar.api import auth
    from Pukaar.api.routers import officer
    from Pukaar.main import app

    monkeypatch.setattr(officer, "get_repo", lambda: repo)
    monkeypatch.setattr(auth, "get_repo", lambda: repo)
    return TestClient(app)


def token(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_api_sets_the_role_for_the_right_people_and_audits_it(repo, client):
    telegram_person(repo, "thunag")
    telegram_person(repo, "gohar", chat="5559999", name="Mohan")
    url = f"/villages/thunag/recipients/{CHAT}/role"
    assert client.post(url, json={"role": "pradhan"}).status_code == 401
    for judge in ("judge", "judge_pradhan"):
        assert client.post(url, json={"role": "pradhan"}, headers=token(client, judge)).status_code == 403
    p = token(client, "pradhan_thunag")
    other = client.post("/villages/gohar/recipients/5559999/role", json={"role": "pradhan"}, headers=p)
    assert other.status_code == 403
    r = client.post(url, json={"role": "pradhan"}, headers=p)
    assert r.status_code == 200, r.text
    assert r.json() == {"id": CHAT, "village_id": "thunag", "name": "Ram Lal", "role": "pradhan",
                        "channel": "telegram", "relay": True}
    assert "phone" not in r.json()
    h = token(client, "officer1")
    assert client.post("/villages/gohar/recipients/5559999/role", json={"role": "task_force"},
                       headers=h).json()["role"] == "task_force"
    assert client.post(url, json={"role": "officer"}, headers=h).status_code == 400
    assert client.post("/villages/thunag/recipients/404/role", json={"role": "pradhan"}, headers=h).status_code == 404
    assert client.post("/villages/atlantis/recipients/x/role", json={"role": "pradhan"}, headers=h).status_code == 404
    audit = client.get("/audit", params={"resource": f"recipient:thunag/{CHAT}"}, headers=h).json()
    changed = [a for a in audit if a["action"] == "recipient_role_changed"]
    assert len(changed) == 1 and changed[0]["reason"] == "villager -> pradhan" and changed[0]["actor"] == "pradhan_thunag"
    assert repo.get_recipient("thunag", CHAT).role == "pradhan"
