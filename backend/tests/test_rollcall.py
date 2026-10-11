""""Surakshit Hoon" safety roll-call: opening rules, Telegram buttons, counts, reminders, Cedar,
family links and what the public routes may show."""

from __future__ import annotations

import json
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from Pukaar.core import clock
from Pukaar.policy.guard import SYSTEM, Principal, evaluate
from Pukaar.services import rollcall as rcs
from Pukaar.store.models import Recipient
from Pukaar.templates import hi
from Pukaar.workflow import tokens
from Pukaar.workflow.client import decide
from test_workflow_steps import drafted_and_asked

OFFICER = Principal("officer1", "officer")
PRADHAN = Principal("pradhan_thunag", "pradhan", ["thunag"])
SECRET = "test-webhook-secret"


class FakeTelegram:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, method, payload=None, files=None):
        self.calls.append((method, payload or {}))
        return {"message_id": len(self.calls)}

    def sent(self, method="sendMessage"):
        return [p for m, p in self.calls if m == method]


@pytest.fixture()
def tg(monkeypatch):
    from Pukaar.delivery import telegram

    fake = FakeTelegram()
    monkeypatch.setattr(telegram, "configured", lambda: True)
    monkeypatch.setattr(telegram, "_call", fake)
    return fake


def add_phone(repo, chat_id="5550001", name="Asha Devi", village="thunag"):
    repo.put_recipient(Recipient(id=chat_id, village_id=village, name=name, channel="telegram"))
    return chat_id


def closed_alert(repo, workflow, level="warning", replay=False, drill=False):
    s, a, _ = drafted_and_asked(repo, level, replay)
    if drill:
        repo.update_alert(a.id, decision_trace={**repo.get_alert(a.id).decision_trace, "drill": True})
    decide(repo, workflow, a.id, "approved", "officer1")
    s.handle({"step": "deliver", "alert_id": a.id})
    return s.handle({"step": "close", "alert_id": a.id, "outcome": "delivered"}), a


def open_by_officer(repo, village="thunag", principal=OFFICER, **kw):
    return rcs.open_rollcall(repo, repo.get_village(village), principal=principal, **kw)


# -- opening ---------------------------------------------------------------------
def test_live_warning_close_opens_a_rollcall(repo, frozen, workflow):
    out, a = closed_alert(repo, workflow, "warning")
    rc = repo.get_rollcall(out["rollcall_id"])
    assert rc.alert_id == a.id and rc.opened_by == "system" and rc.exercise is False
    assert rc.asked == 2  # the two seeded demo recipients
    assert clock.parse(rc.closes_at) - clock.parse(rc.opened_at) == timedelta(hours=48)
    assert [r for r in repo.list_audit(rc.opened_at[:10], "village:thunag") if r.action == "open_rollcall"
            and r.decision == "allow"]
    assert any(t.step == "rollcall_opened" for t in repo.list_timeline(a.id))
    # demo recipients have no phone: recorded as stub, nothing claimed as sent
    assert {x.channel for x in repo.list_rollcall_asked(rc.id)} == {"stub"}


def test_replay_never_opens_a_rollcall(repo, frozen, workflow):
    out, _ = closed_alert(repo, workflow, "critical", replay=True)
    assert "rollcall_id" not in out and repo.list_rollcalls("thunag") == []


def test_watch_or_declined_opens_nothing(repo, frozen, workflow):
    out, _ = closed_alert(repo, workflow, "watch")
    assert "rollcall_id" not in out
    s, a, _ = drafted_and_asked(repo, "warning")
    decide(repo, workflow, a.id, "declined", "officer1")
    assert "rollcall_id" not in s.handle({"step": "close", "alert_id": a.id, "outcome": "declined"})
    assert repo.list_rollcalls("thunag") == []


def test_a_drill_opens_an_exercise_rollcall_labelled_as_such(repo, frozen, workflow, tg):
    add_phone(repo)
    out, _ = closed_alert(repo, workflow, "warning", drill=True)
    rc = repo.get_rollcall(out["rollcall_id"])
    assert rc.exercise is True
    question = [p for p in tg.sent() if "reply_markup" in p and "safe:" in json.dumps(p["reply_markup"])]
    assert question and question[0]["text"].startswith(hi.ROLLCALL_DRILL_HI)


def test_a_second_open_for_the_same_village_is_refused(repo, frozen):
    first = open_by_officer(repo)
    with pytest.raises(rcs.RollCallError) as exc:
        open_by_officer(repo)
    assert exc.value.code == "already_open" and exc.value.extra["rollcall_id"] == first.id


def test_officer_cannot_open_one_during_a_replay(repo, frozen):
    repo.update_village("thunag", replay=True)
    with pytest.raises(rcs.RollCallError) as exc:
        open_by_officer(repo)
    assert exc.value.code == "denied"


# -- Telegram --------------------------------------------------------------------
def test_question_has_two_buttons_and_callbacks_are_idempotent(repo, frozen, tg):
    chat = add_phone(repo)
    rc = open_by_officer(repo)
    q = [p for p in tg.sent() if p.get("chat_id") == chat][0]
    assert "क्या आप सुरक्षित हैं? / Are you safe?" in q["text"]
    buttons = q["reply_markup"]["inline_keyboard"][0]
    assert [b["callback_data"] for b in buttons] == [f"safe:{rc.id}", f"help:{rc.id}"]
    assert buttons[0]["text"] == "✅ मैं सुरक्षित हूँ" and buttons[1]["text"] == "🆘 मदद चाहिए"
    assert all(len(b["callback_data"].encode()) <= 64 for b in buttons)

    first = rcs.answer(repo, rc.id, chat, "safe")
    again = rcs.answer(repo, rc.id, chat, "safe")
    assert first.outcome == "recorded" and again.outcome == "same"
    assert first.share_link and "/safe/" in first.share_link
    assert len(repo.list_rollcall_responses(rc.id)) == 1 and repo.get_rollcall(rc.id).safe == 1

    switched = rcs.answer(repo, rc.id, chat, "need_help")  # last answer wins
    rc2 = repo.get_rollcall(rc.id)
    assert switched.outcome == "recorded" and (rc2.safe, rc2.need_help) == (0, 1)


@pytest.fixture()
def client(repo, monkeypatch):
    from Pukaar.api import auth
    from Pukaar.api.routers import public, rollcall, telegram
    from Pukaar.main import app

    for mod in (auth, public, rollcall, telegram):
        monkeypatch.setattr(mod, "get_repo", lambda: repo)
    monkeypatch.setenv("PUKAAR_TELEGRAM_WEBHOOK_SECRET", SECRET)
    return TestClient(app)


def hook(client, body):
    r = client.post("/telegram/webhook", json=body, headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})
    assert r.status_code == 200, r.text


def tap(client, chat, data, n=1):
    hook(client, {"callback_query": {"id": f"cb{n}", "data": data, "message": {"chat": {"id": int(chat)}}}})


def token(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_webhook_buttons_reply_in_hindi_and_help_reaches_the_board(client, repo, frozen, tg):
    chat = add_phone(repo)
    rc = open_by_officer(repo)
    tg.calls.clear()
    tap(client, chat, f"safe:{rc.id}")
    assert tg.sent("answerCallbackQuery")[-1]["text"] == hi.ROLLCALL_SAFE_THANKS_HI
    link_msg = tg.sent()[-1]["text"]
    assert "/safe/" in link_msg and "परिवार" in link_msg
    tap(client, chat, f"safe:{rc.id}", 2)
    assert tg.sent("answerCallbackQuery")[-1]["text"] == hi.ROLLCALL_SAME_HI
    assert len(tg.sent()) == 1  # no second link message for a repeated tap

    tap(client, chat, f"help:{rc.id}", 3)
    assert tg.sent("answerCallbackQuery")[-1]["text"] == hi.ROLLCALL_HELP_THANKS_HI
    reply = tg.sent()[-1]["text"]
    assert "112" in reply and "अधिकारी" in reply
    hook(client, {"message": {"chat": {"id": int(chat)}, "text": "school ki chhat par, 4 log"}})
    assert repo.get_rollcall_response(rc.id, chat).note == "school ki chhat par, 4 log"
    assert [r for r in repo.list_audit(clock.iso(clock.now())[:10], f"rollcall:{rc.id}")
            if r.action == "rollcall_need_help"]

    board = client.get(f"/rollcalls/{rc.id}", headers=token(client, "officer1")).json()
    assert board["rollcall"]["need_help"] == 1 and board["need_help"][0]["name"] == "Asha Devi"
    assert board["need_help"][0]["note"] == "school ki chhat par, 4 log"
    assert chat not in json.dumps(board)  # no chat id (or phone) on the board


def test_a_chat_that_was_not_asked_cannot_answer(client, repo, frozen, tg):
    rc = open_by_officer(repo)
    tap(client, "999999", f"safe:{rc.id}")
    assert tg.sent("answerCallbackQuery")[-1]["text"] == hi.ROLLCALL_NOT_ASKED_HI
    assert repo.list_rollcall_responses(rc.id) == []


def test_answers_after_closing_are_not_recorded(repo, frozen, tg):
    chat = add_phone(repo)
    rc = open_by_officer(repo)
    frozen["now"] = frozen["now"] + timedelta(hours=49)
    assert rcs.answer(repo, rc.id, chat, "safe").outcome == "closed"
    assert rcs.current_open(repo, "thunag") is None


# -- counts and board ------------------------------------------------------------
def test_counts_and_need_help_first(repo, frozen):
    rc = open_by_officer(repo)
    rcs.simulate_stub_answer(repo, rc.id, "stub-thunag-1", "safe")
    frozen["now"] = frozen["now"] + timedelta(minutes=3)
    rcs.simulate_stub_answer(repo, rc.id, "stub-thunag-2", "need_help")
    rc = repo.get_rollcall(rc.id)
    summary = rcs.summary(rc)
    assert (summary["safe"], summary["need_help"], summary["not_answered"], summary["asked"]) == (1, 1, 0, 2)
    board = rcs.board(repo, rc)
    assert list(board)[:4] == ["rollcall", "need_help", "safe", "not_answered"]
    assert board["need_help"][0]["simulated"] is True  # never shown as a real tap


def test_simulated_answers_only_for_stub_recipients(repo, frozen, tg):
    chat = add_phone(repo)
    rc = open_by_officer(repo)
    with pytest.raises(ValueError):
        rcs.simulate_stub_answer(repo, rc.id, chat, "safe")


# -- reminders -------------------------------------------------------------------
def test_reminder_goes_to_non_responders_once_per_30_minutes(repo, frozen, tg):
    a = add_phone(repo, "5550001", "Asha Devi")
    b = add_phone(repo, "5550002", "Bhola Ram")
    rc = open_by_officer(repo)
    rcs.answer(repo, rc.id, a, "safe")
    tg.calls.clear()
    out = rcs.remind(repo, repo.get_rollcall(rc.id))
    assert out["reminded"] == 1 and out["waiting"] == 3 and out["demo_without_phone"] == 2
    assert [p["chat_id"] for p in tg.sent()] == [b]
    with pytest.raises(rcs.RollCallError) as exc:
        rcs.remind(repo, repo.get_rollcall(rc.id))
    assert exc.value.code == "rate_limited" and 0 < exc.value.extra["retry_after_seconds"] <= 1800
    frozen["now"] = frozen["now"] + timedelta(minutes=31)
    assert rcs.remind(repo, repo.get_rollcall(rc.id))["reminded"] == 1


def test_remind_route_returns_429_when_too_soon(client, repo, frozen):
    rc = open_by_officer(repo)
    h = token(client, "officer1")
    assert client.post(f"/rollcalls/{rc.id}/remind", headers=h).status_code == 200
    r = client.post(f"/rollcalls/{rc.id}/remind", headers=h)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "rate_limited" and r.headers["Retry-After"]
    assert r.json()["detail"]["message_hi"]


# -- Cedar -----------------------------------------------------------------------
def test_cedar_rollcall_policies():
    ctx = {"village_id": "thunag"}
    for action in ("open_rollcall", "view_rollcall", "remind_rollcall"):
        assert evaluate(OFFICER, action, "rollcall", "rc_1", {"village_id": "gohar"}).allowed
        assert evaluate(PRADHAN, action, "rollcall", "rc_1", ctx).allowed
        assert not evaluate(PRADHAN, action, "rollcall", "rc_1", {"village_id": "gohar"}).allowed
        assert not evaluate(Principal("bot", "agent"), action, "rollcall", "rc_1", ctx).allowed
    assert not evaluate(OFFICER, "open_rollcall", "village", "thunag", {**ctx, "replay": True}).allowed
    assert not evaluate(SYSTEM, "open_rollcall", "village", "thunag", {**ctx, "level": "warning", "replay": True}).allowed
    assert evaluate(SYSTEM, "open_rollcall", "village", "thunag", {**ctx, "level": "critical"}).allowed
    assert not evaluate(SYSTEM, "open_rollcall", "village", "thunag", {**ctx, "level": "watch"}).allowed
    assert not evaluate(SYSTEM, "remind_rollcall", "rollcall", "rc_1", ctx).allowed


def test_another_villages_pradhan_is_denied_on_every_route(client, repo, frozen):
    gohar = open_by_officer(repo, "gohar")
    h = token(client, "pradhan_thunag")
    assert client.get(f"/rollcalls/{gohar.id}", headers=h).status_code == 403
    assert client.post(f"/rollcalls/{gohar.id}/remind", headers=h).status_code == 403
    assert client.get("/rollcalls?village_id=gohar", headers=h).status_code == 403
    assert client.post("/rollcalls", json={"village_id": "gohar"}, headers=h).status_code == 403
    own = client.post("/rollcalls", json={"village_id": "thunag"}, headers=h)
    assert own.status_code == 200 and own.json()["rollcall"]["opened_by_user"] == "pradhan_thunag"
    listed = client.get("/rollcalls", headers=h).json()
    assert {r["village_id"] for r in listed} == {"thunag"}
    assert client.get("/rollcalls").status_code == 401


# -- family link -----------------------------------------------------------------
def test_family_link_shows_only_first_name_time_and_village(client, repo, frozen, tg):
    chat = add_phone(repo, name="Asha Devi")
    rc = open_by_officer(repo)
    link = rcs.answer(repo, rc.id, chat, "safe").share_link
    tok = link.rsplit("/", 1)[1]
    assert chat not in tok and chat not in tokens._unb64(tok.split(".")[0]).decode()
    body = client.get(f"/safe/{tok}").json()
    assert set(body) == {"first_name", "village_name", "village_name_hi", "at", "status", "exercise", "simulated"}
    assert body["first_name"] == "Asha" and body["village_name"] == "Thunag" and body["status"] == "safe"
    assert "Devi" not in json.dumps(body) and chat not in json.dumps(body)


def test_family_link_tamper_and_expiry(client, repo, frozen, tg):
    chat = add_phone(repo)
    rc = open_by_officer(repo)
    tok = rcs.answer(repo, rc.id, chat, "safe").share_link.rsplit("/", 1)[1]
    body_b64, mac = tok.split(".")
    forged = json.loads(tokens._unb64(body_b64))
    forged["e"] += 10 * 86400
    forged_tok = tokens._b64(json.dumps(forged, separators=(",", ":")).encode()) + "." + mac
    r = client.get(f"/safe/{forged_tok}")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid"
    share_id = tokens.verify(tok, "safe").subject
    old = tokens.sign(rc.id, share_id, 0, "safe", ttl=rcs.SHARE_TTL_SECONDS, now=time.time() - 8 * 86400)
    r = client.get(f"/safe/{old}")
    assert r.status_code == 410 and r.json()["detail"]["code"] == "expired"
    approve = tokens.sign(rc.id, share_id, 0, "approve")  # another kind of signed link is not a family link
    assert client.get(f"/safe/{approve}").status_code == 400


def test_family_link_stops_when_the_person_asks_for_help(client, repo, frozen, tg):
    chat = add_phone(repo)
    rc = open_by_officer(repo)
    tok = rcs.answer(repo, rc.id, chat, "safe").share_link.rsplit("/", 1)[1]
    rcs.answer(repo, rc.id, chat, "need_help")
    r = client.get(f"/safe/{tok}")
    assert r.status_code == 410 and r.json()["detail"]["code"] == "not_current"
    assert "need" not in json.dumps(r.json()).lower()  # the link does not reveal what changed


# -- public pages ----------------------------------------------------------------
def test_public_routes_show_counts_only(client, repo, frozen, tg):
    chat = add_phone(repo, name="Asha Devi")
    rc = open_by_officer(repo)
    rcs.answer(repo, rc.id, chat, "need_help")
    rcs.simulate_stub_answer(repo, rc.id, "stub-thunag-1", "safe")
    detail = client.get("/villages/thunag").json()
    assert detail["rollcall"] == {"open": True, "exercise": False, "asked": 3, "safe": 1, "need_help": 1,
                                  "not_answered": 1, "opened_at": rc.opened_at, "closes_at": rc.closes_at}
    overview = client.get("/public/overview").json()
    by_id = {v["id"]: v for v in overview["villages"]}
    assert by_id["thunag"]["rollcall"]["need_help"] == 1 and by_id["gohar"]["rollcall"] is None
    for text in (json.dumps(detail), json.dumps(overview)):
        assert "Asha" not in text and chat not in text and rc.id not in text
