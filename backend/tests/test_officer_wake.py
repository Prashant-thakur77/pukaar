"""Wake the duty officer (scorecard gap 4) and the critical approval window.

At the nudge (PUKAAR_OFFICER_WAKE_SECONDS into the officer's window) an officer who has not opened the
approval link is phoned through the voice provider, at the same moment as the Web Push and Telegram
reminders. "1" on the call sends the one-tap approval link again; nothing on the call ever approves.
With voice off (or no phone on file, or a replay) the record says no call was possible, and the
nudge goes on. delivery/officer_call.py, workflow/steps.step_nudge_officer, api/routers/voice.py.
"""

from __future__ import annotations

import httpx
import pytest

from Pukaar.core.config import get_settings
from Pukaar.delivery import officer_call, plivo, voice
from Pukaar.workflow import tokens
from Pukaar.workflow.steps import approval_timers, approval_window

from test_push import push, subscribe  # noqa: F401  (fixture)
from test_rollcall import tg  # noqa: F401  (fixture)
from test_voice import KEY, PLIVO_ENV, FakeProvider, _settings, api, calls, no_network  # noqa: F401
from test_workflow_steps import make_alert, steps

OFFICER_PHONE = "+919800000001"
CHAT = "9990001"


def asked(repo, level="warning", replay=False):
    s = steps(repo)
    a = make_alert(repo, level, replay)
    s.handle({"step": "draft", "alert_id": a.id})
    s.handle({"step": "ask_officer", "alert_id": a.id, "officer_index": 0, "task_token": "TOKEN-1"})
    return s, a


def nudge(s, a, token="TOKEN-2"):
    return s.handle({"step": "nudge_officer", "alert_id": a.id, "officer_index": 0, "task_token": token})


def on_duty(repo, push=None, phone=True):
    if phone:
        repo.put_officer_phone("officer1", OFFICER_PHONE)
    repo.put_officer_chat("officer1", CHAT)
    if push is not None:
        subscribe(repo, push, "officer1", "a")


def wake_token(alert_id, officer="officer1"):
    return voice.sign_call(alert_id, officer_call.token_id(officer), voice.OFFICER_WAKE_ATTEMPT)


def untouched(repo, workflow, alert_id, token="TOKEN-2"):
    """The call never approves: still pending, not approved, nobody decided, the task token unspent."""
    a = repo.get_alert(alert_id)
    assert a.status == "pending" and a.approved is False and a.decided_by is None and a.task_token == token
    assert workflow.successes == []


# -- the call is placed with the reminders ---------------------------------------------------------------
def test_an_officer_who_has_not_opened_the_link_is_called_with_the_reminders(repo, frozen, workflow, calls, tg, push):
    on_duty(repo, push)
    s, a = asked(repo)
    tg.calls.clear()
    push.received.clear()
    out = nudge(s, a)
    # The same moment: Telegram, Web Push and the call.
    assert out["telegram"] is True and out["push"] == 1 and out["call"] == "placed"
    form = calls.form()
    assert form["From"] == OFFICER_PHONE and len(calls.requests) == 1
    tok = voice.verify_call(form["CustomField"])
    assert tok.attempt == voice.OFFICER_WAKE_ATTEMPT and officer_call.username_from(tok.recipient_id) == "officer1"
    call = repo.get_officer_call(a.id, "officer1")
    assert (call.status, call.provider, call.call_id, call.level) == ("placed", "exotel", "exo-call-1", "warning")
    assert "call=placed (exotel)" in repo.list_timeline(a.id)[-1].detail
    untouched(repo, workflow, a.id)
    assert repo.list_deliveries(a.id) == []  # an officer's call is not a villager delivery
    nudge(s, a, "TOKEN-3")  # a retried nudge step: never a second call
    assert len(calls.requests) == 1


def test_pressing_1_sends_the_link_again_and_never_approves(repo, frozen, workflow, calls, api, tg, push):
    on_duty(repo, push)
    s, a = asked(repo)
    nudge(s, a)
    token = wake_token(a.id)
    greet = api.get("/voice/exotel/flow", params={"k": KEY, "CustomField": token, "CallSid": "exo-call-1"})
    assert greet.status_code == 200
    assert "थुनाग को अभी आपकी मंज़ूरी चाहिए, चेतावनी" in greet.text
    assert "Pukaar: Thunag needs your approval now, Warning." in greet.text
    menu = api.get("/voice/exotel/flow", params={"k": KEY, "part": "menu", "CustomField": token, "CallSid": "exo-call-1"})
    assert "Press 1 to get your approval link on Telegram" in menu.json()["gather_prompt"]["text"]
    assert repo.get_officer_call(a.id, "officer1").status == "answered"
    tg.calls.clear()
    push.received.clear()
    key = api.get("/voice/exotel/gather", params={"k": KEY, "CustomField": token, "CallSid": "exo-call-1",
                                                  "digits": '"1"'})
    assert key.status_code == 302  # back to the greeting, which now says the link went out
    sent = tg.sent()
    assert len(sent) == 1 and sent[0]["chat_id"] == CHAT
    link = sent[0]["text"].rsplit("/a/", 1)[1]
    t = tokens.verify(link, "approve")  # the officer's own one-tap link, at the alert's token version
    assert (t.alert_id, t.subject, t.version) == (a.id, "officer1", repo.get_alert(a.id).token_version)
    assert len(push.received) == 1
    again = api.get("/voice/exotel/flow", params={"k": KEY, "CustomField": token, "CallSid": "exo-call-1"})
    assert again.text.startswith("आपकी मंज़ूरी का लिंक") and "Opening your approval link" in again.text
    menu2 = api.get("/voice/exotel/flow", params={"k": KEY, "part": "menu", "CustomField": token,
                                                  "CallSid": "exo-call-1"})
    assert menu2.json()["input_timeout"] == 1  # nothing more to press
    end = api.get("/voice/exotel/gather", params={"k": KEY, "CustomField": token, "CallSid": "exo-call-1",
                                                  "digits": ""})
    assert end.status_code == 200
    # A provider retrying the same key press sends nothing more.
    api.get("/voice/exotel/gather", params={"k": KEY, "CustomField": token, "CallSid": "exo-call-1", "digits": '"1"'})
    assert len(tg.sent()) == 1
    call = repo.get_officer_call(a.id, "officer1")
    assert call.status == "link_sent" and call.digit == "1" and call.link_channels == ["telegram", "push"]
    untouched(repo, workflow, a.id)
    assert any(t.step == "officer_call_key" and "the decision stays in the app" in t.detail
               for t in repo.list_timeline(a.id))


@pytest.mark.parametrize("digits", ['"2"', '"3"', '"9"', ""])
def test_no_other_key_does_anything(repo, frozen, workflow, calls, api, tg, digits):
    on_duty(repo)
    s, a = asked(repo)
    nudge(s, a)
    tg.calls.clear()
    r = api.get("/voice/exotel/gather", params={"k": KEY, "CustomField": wake_token(a.id), "CallSid": "exo-call-1",
                                                "digits": digits})
    assert r.status_code == 200 and tg.sent() == []
    untouched(repo, workflow, a.id)


def test_a_decided_alert_is_not_sent_again_and_a_forged_call_is_refused(repo, frozen, workflow, calls, api, tg):
    on_duty(repo)
    s, a = asked(repo)
    nudge(s, a)
    forged = api.get("/voice/exotel/gather", params={"k": KEY, "CustomField": wake_token(a.id),
                                                     "CallSid": "someone-elses-call", "digits": '"1"'})
    assert forged.status_code == 403
    other = api.get("/voice/exotel/gather", params={"k": KEY, "CustomField": wake_token(a.id, "officer2"),
                                                    "CallSid": "exo-call-1", "digits": '"1"'})
    assert other.status_code == 403  # a token for another officer names no call of theirs
    repo.update_alert(a.id, status="declined")
    tg.calls.clear()
    r = api.get("/voice/exotel/gather", params={"k": KEY, "CustomField": wake_token(a.id), "CallSid": "exo-call-1",
                                                "digits": '"1"'})
    assert r.status_code == 200 and r.text == "decided" and tg.sent() == []


def test_the_status_callback_records_how_the_call_ended(repo, frozen, workflow, calls, api):
    on_duty(repo)
    s, a = asked(repo)
    nudge(s, a)
    r = api.post(f"/voice/exotel/status?k={KEY}&c={wake_token(a.id)}", data={"CallSid": "exo-call-1",
                                                                              "Status": "no-answer"})
    assert r.json()["outcome"] == "not_connected"
    call = repo.get_officer_call(a.id, "officer1")
    assert call.status == "not_connected" and call.call_status == "no_answer"
    assert any(t.step == "officer_call_ended" for t in repo.list_timeline(a.id))
    assert repo.list_deliveries(a.id) == []  # no villager counter moved


def test_plivo_wake_call_says_press_1_and_only_1(repo, frozen, workflow, monkeypatch, api, tg):
    _settings(monkeypatch, "plivo", **PLIVO_ENV)
    fake = FakeProvider("plivo")
    voice.set_http_client(httpx.Client(transport=httpx.MockTransport(fake)))
    try:
        on_duty(repo)
        s, a = asked(repo, "critical")
        assert nudge(s, a)["call"] == "placed"
        token = wake_token(a.id)
        answer_url = f"http://testserver/voice/plivo/answer?k={KEY}&c={token}"
        p = {"RequestUUID": "plivo-req-1", "CallUUID": "c-uuid"}
        sig = plivo.signature("plivo-secret", "POST", answer_url, p, "n1")
        ans = api.post(answer_url, data=p, headers={"X-Plivo-Signature-V3-Nonce": "n1", "X-Plivo-Signature-V3": sig})
        assert ans.status_code == 200 and 'validDigits="1"' in ans.text
        assert "needs your approval now, Critical" in ans.text and "Press 1" in ans.text
        digits_url = f"http://testserver/voice/plivo/digits?k={KEY}&c={token}"
        p2 = {**p, "Digits": "1"}
        sig2 = plivo.signature("plivo-secret", "POST", digits_url, p2, "n2")
        tg.calls.clear()
        out = api.post(digits_url, data=p2, headers={"X-Plivo-Signature-V3-Nonce": "n2", "X-Plivo-Signature-V3": sig2})
        assert out.status_code == 200 and "Opening your approval link" in out.text and "<Hangup/>" in out.text
        assert len(tg.sent()) == 1
        untouched(repo, workflow, a.id)
    finally:
        voice.set_http_client(None)
        monkeypatch.delenv("PUKAAR_VOICE_PROVIDER")
        get_settings.cache_clear()


# -- no call possible: said honestly, and the nudge goes on --------------------------------------------
def test_voice_off_records_that_no_call_was_possible_and_the_nudge_goes_on(repo, frozen, workflow, tg, push,
                                                                           no_network):
    on_duty(repo, push)
    s, a = asked(repo)
    tg.calls.clear()
    out = nudge(s, a)
    assert out["call"] == "not_possible" and out["telegram"] is True and out["push"] == 1
    call = repo.get_officer_call(a.id, "officer1")
    assert call.status == "not_possible" and call.call_id is None
    assert call.reason == "voice provider is off (PUKAAR_VOICE_PROVIDER=off)"
    assert "call=not possible (voice provider is off" in repo.list_timeline(a.id)[-1].detail
    untouched(repo, workflow, a.id)


def test_no_phone_on_file_or_a_replay_is_recorded_without_dialling(repo, frozen, workflow, calls, tg):
    on_duty(repo, phone=False)
    s, a = asked(repo)
    assert nudge(s, a)["call"] == "not_possible"
    assert repo.get_officer_call(a.id, "officer1").reason.startswith("no phone number on file for officer1")
    repo.put_officer_phone("officer1", OFFICER_PHONE)
    s2, replay = asked(repo, replay=True)
    assert nudge(s2, replay)["call"] == "not_possible"
    assert repo.get_officer_call(replay.id, "officer1").reason == "replay: no real phone is called"
    assert calls.requests == []


def test_a_refused_call_is_failed_with_the_reason(repo, frozen, workflow, monkeypatch, tg):
    _settings(monkeypatch, "exotel", PUKAAR_EXOTEL_SID="pukaar1", PUKAAR_EXOTEL_TOKEN="tok",
              PUKAAR_EXOTEL_CALLER_ID="08047112345", PUKAAR_EXOTEL_APP_ID="777")
    fake = FakeProvider("exotel", status=500, body={"RestException": {"Message": "down for +919800000001"}})
    voice.set_http_client(httpx.Client(transport=httpx.MockTransport(fake)))
    try:
        on_duty(repo)
        s, a = asked(repo)
        assert nudge(s, a)["call"] == "failed"
        call = repo.get_officer_call(a.id, "officer1")
        assert call.status == "failed" and "<number>" in call.reason and OFFICER_PHONE not in call.reason
        assert "call=failed" in repo.list_timeline(a.id)[-1].detail
    finally:
        voice.set_http_client(None)
        monkeypatch.delenv("PUKAAR_VOICE_PROVIDER")
        get_settings.cache_clear()


def test_no_call_when_the_officer_already_opened_the_link(repo, frozen, workflow, calls, monkeypatch):
    from Pukaar.api.routers import public

    monkeypatch.setattr(public, "get_repo", lambda: repo)
    on_duty(repo)
    s, a = asked(repo)
    link = tokens.sign(a.id, "officer1", repo.get_alert(a.id).token_version, "approve")
    assert public.approval_view(link)["valid"] is True
    opened = repo.get_alert(a.id)
    assert opened.approval_opened_by == "officer1" and opened.approval_opened_version == opened.token_version
    out = nudge(s, a)
    assert out["call"] == "not_needed" and calls.requests == []
    assert "call=not needed (the link was opened)" in repo.list_timeline(a.id)[-1].detail
    # The next officer has not opened anything: their nudge calls them.
    s.handle({"step": "next_officer", "alert_id": a.id, "officer_index": 0})
    s.handle({"step": "ask_officer", "alert_id": a.id, "officer_index": 1, "task_token": "TOKEN-3"})
    repo.put_officer_phone("officer2", "+919800000002")
    assert s.handle({"step": "nudge_officer", "alert_id": a.id, "officer_index": 1,
                     "task_token": "TOKEN-4"})["call"] == "placed"
    assert calls.form()["From"] == "+919800000002"


# -- the critical window -------------------------------------------------------------------------------
@pytest.fixture()
def env(monkeypatch):
    def apply(**kw):
        for k, v in kw.items():
            monkeypatch.setenv(k, str(v))
        get_settings.cache_clear()

    yield apply
    monkeypatch.undo()
    get_settings.cache_clear()


def test_critical_waits_5_minutes_per_officer_and_the_nudge_comes_at_3(env):
    assert approval_window("warning") == approval_window("watch") == 600
    assert approval_window("critical") == 300
    assert approval_timers("warning") == {"nudge_after_seconds": 180, "nudge_wait_seconds": 420}
    assert approval_timers("critical") == {"nudge_after_seconds": 150, "nudge_wait_seconds": 150}
    env(PUKAAR_CRITICAL_APPROVAL_TIMEOUT_SECONDS=120, PUKAAR_OFFICER_WAKE_SECONDS=45)
    assert approval_timers("critical") == {"nudge_after_seconds": 45, "nudge_wait_seconds": 75}
    env(PUKAAR_APPROVAL_TIMEOUT_SECONDS=60)  # filming: the critical window is never longer than the general one
    assert approval_window("critical") == 60
    assert approval_timers("warning") == {"nudge_after_seconds": 30, "nudge_wait_seconds": 30}
    env(PUKAAR_OFFICER_WAKE_SECONDS=0, PUKAAR_APPROVAL_TIMEOUT_SECONDS=600)
    assert approval_timers("warning") == {"nudge_after_seconds": 300, "nudge_wait_seconds": 300}  # half-way


def test_a_chain_of_three_holds_a_critical_15_minutes_not_30(repo, frozen):
    from test_roster import rostered

    rostered(repo, "2026-06-30", "night", primary="dso_night", backup="dso_backup", escalation="adm_mandi")
    s = steps(repo)
    a = make_alert(repo, "critical")
    out = s.handle({"step": "draft", "alert_id": a.id})
    assert out["officer_count"] * (out["nudge_after_seconds"] + out["nudge_wait_seconds"]) == 15 * 60


def test_an_alert_raised_to_critical_gives_the_next_officer_the_critical_window(repo, frozen):
    s, a = asked(repo, "warning")
    repo.update_alert(a.id, level="critical")  # the sweep escalated it while officer1 waited
    nxt = s.handle({"step": "next_officer", "alert_id": a.id, "officer_index": 0})
    assert nxt["level"] == "critical" and nxt["nudge_after_seconds"] + nxt["nudge_wait_seconds"] == 300
