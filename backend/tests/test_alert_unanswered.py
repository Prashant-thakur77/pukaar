"""An unanswered alert is loud (scorecard cycle 4, gap 3).

When every officer in the chain timed out (a Watch or Warning, or a Critical with auto-send off), the last
call (workflow/steps.step_unanswered) emits AlertUnanswered (alarmed), tells every officer on duty for the
district and the ADM or DM on Telegram and Web Push with a fresh one-tap link that really approves, and
phones the ADM or DM when voice is on (and says honestly when it cannot). A replay reaches nobody. The sweep
asks again after a cooldown that follows the level: a Critical on the next sweep.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from Pukaar.core.config import get_settings
from Pukaar.services import decision_engine as de
from Pukaar.workflow import tokens
from Pukaar.workflow.client import decide

from test_pilot_safety import live_warning, metrics, reading
from test_push import push, subscribe  # noqa: F401  (fixture)
from test_roster import rostered
from test_rollcall import tg  # noqa: F401  (fixture)
from test_voice import EXOTEL_ENV, FakeProvider, _settings, calls, no_network  # noqa: F401
from test_workflow_steps import make_alert, steps

ADM_PHONE = "+919800000009"
CHATS = {"dso_night": "7001", "dso_backup": "7002", "adm_mandi": "7003", "dso_relief": "7004"}


def night_roster(repo, escalation="adm_mandi"):
    """conftest's NOW, 02:00 UTC on 1 July, is 07:30 IST: still the night shift of 30 June."""
    return rostered(repo, "2026-06-30", "night", primary="dso_night", backup="dso_backup", escalation=escalation)


def chats(repo):
    for who, chat in CHATS.items():
        repo.put_officer_chat(who, chat)


def chain_timed_out(repo, level="warning", replay=False, auto_send=None):
    """Draft, then ask and nudge each officer in turn with no answer, as the state machine does."""
    s = steps(repo)
    a = make_alert(repo, level, replay)
    out = s.handle({"step": "draft", "alert_id": a.id})
    for i in range(out["officer_count"]):
        s.handle({"step": "ask_officer", "alert_id": a.id, "officer_index": i, "task_token": f"ASK-{i}"})
        s.handle({"step": "nudge_officer", "alert_id": a.id, "officer_index": i, "task_token": f"NUDGE-{i}"})
        s.handle({"step": "next_officer", "alert_id": a.id, "officer_index": i})
    if auto_send is not None:
        assert s.handle({"step": "auto_send", "alert_id": a.id})["mode"] == auto_send
    return s, a


def last_call(s, a, token="LAST"):
    return s.handle({"step": "unanswered", "alert_id": a.id, "task_token": token})


def unanswered_metrics(capsys):
    return [m for m in metrics(capsys) if "AlertUnanswered" in m]


@pytest.fixture()
def auto_send_off(monkeypatch):
    monkeypatch.setenv("PUKAAR_CRITICAL_AUTO_SEND", "false")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("PUKAAR_CRITICAL_AUTO_SEND")
    get_settings.cache_clear()


# -- the metric, and everyone on duty told with a link that works ---------------------------------------
def test_an_expired_warning_emits_the_metric_and_tells_the_roster_and_the_adm(repo, frozen, workflow, tg, push,
                                                                             no_network, capsys):
    night_roster(repo)
    chats(repo)
    subscribe(repo, push, "adm_mandi", "adm")
    subscribe(repo, push, "dso_night", "dso")
    s, a = chain_timed_out(repo)
    tg.calls.clear()
    push.received.clear()
    capsys.readouterr()

    out = last_call(s, a)

    rows = unanswered_metrics(capsys)
    assert len(rows) == 1 and rows[0]["AlertUnanswered"] == 1 and rows[0]["Level"] == "warning"
    assert out["officers"] == 3 and out["reached"] == 3 and out["telegram"] == 3 and out["push"] == 2
    by_chat = {m["chat_id"]: m["text"] for m in tg.sent()}
    assert set(by_chat) == {CHATS["dso_night"], CHATS["dso_backup"], CHATS["adm_mandi"]}
    adm_text = by_chat[CHATS["adm_mandi"]]
    assert "किसी अधिकारी ने मंज़ूरी नहीं दी" in adm_text and "nobody approved; it was NOT sent" in adm_text
    assert "Thunag Warning" in adm_text and "next 10 min" in adm_text
    # Each officer's own fresh link, at the alert's new token version: the alert is pending again.
    alert = repo.get_alert(a.id)
    assert alert.status == "pending" and alert.task_token == "LAST" and alert.unanswered_at
    for who, chat in CHATS.items():
        if chat not in by_chat:
            continue
        t = tokens.verify(by_chat[chat].rsplit("/a/", 1)[1], "approve")
        assert (t.alert_id, t.subject, t.version) == (a.id, who, alert.token_version)
    titles = [p["title"] for _, p, _ in push.received]
    assert len(titles) == 2 and all(t.startswith("किसी ने मंज़ूरी नहीं दी · Nobody approved") for t in titles)
    assert all(p["data"]["token"] and p["tag"] == f"{a.id}-unanswered" for _, p, _ in push.received)
    # The ADM's link approves: the decision goes to the waiting LastCall task.
    adm_link = tokens.verify(by_chat[CHATS["adm_mandi"]].rsplit("/a/", 1)[1], "approve")
    decided = decide(repo, workflow, a.id, "approved", "adm_mandi (link)", token_version=adm_link.version)
    assert decided.status == "approved" and workflow.successes[-1][0] == "LAST"
    detail = next(t.detail for t in repo.list_timeline(a.id) if t.step == "unanswered")
    assert "reached 3 of 3" in detail and "adm_mandi (escalation (ADM))" in detail


def test_officers_who_came_on_duty_meanwhile_are_told_too(repo, frozen, workflow, tg, no_network):
    night_roster(repo)
    chats(repo)
    s, a = chain_timed_out(repo)
    # The shift changed after the alert was drafted: the new primary is told as well as the frozen chain.
    rostered(repo, "2026-06-30", "night", primary="dso_relief", backup="dso_backup", escalation="adm_mandi")
    tg.calls.clear()
    out = last_call(s, a)
    assert out["officers"] == 4
    assert CHATS["dso_relief"] in {m["chat_id"] for m in tg.sent()}
    assert "dso_relief" in repo.get_alert(a.id).officers_asked  # the all-clear will reach them too


def test_a_critical_with_auto_send_off_goes_to_the_last_call(repo, frozen, workflow, tg, no_network, capsys,
                                                             auto_send_off):
    night_roster(repo)
    chats(repo)
    s, a = chain_timed_out(repo, "critical", auto_send="off")
    capsys.readouterr()
    tg.calls.clear()
    out = last_call(s, a)
    assert [m["Level"] for m in unanswered_metrics(capsys)] == ["critical"]
    assert out["telegram"] == 3 and "next 5 min" in tg.sent()[0]["text"]  # the critical window
    assert not repo.list_deliveries(a.id)  # nothing went to the village


def test_expiry_after_the_last_call_is_not_counted_twice_and_names_the_cooldown(repo, frozen, workflow, tg,
                                                                                no_network, capsys):
    night_roster(repo)
    s, a = chain_timed_out(repo)
    last_call(s, a)
    capsys.readouterr()
    s.handle({"step": "expire", "alert_id": a.id})
    assert repo.get_alert(a.id).status == "expired" and repo.get_alert(a.id).task_token is None
    assert unanswered_metrics(capsys) == []
    assert "asks again after 30 min" in repo.list_timeline(a.id)[-1].detail
    # A run that reached expire without the last call is still never silent.
    b = make_alert(repo, "watch")
    s.handle({"step": "draft", "alert_id": b.id})
    s.handle({"step": "expire", "alert_id": b.id})
    assert [m["Level"] for m in unanswered_metrics(capsys)] == ["watch"]
    assert "asks again after 60 min" in repo.list_timeline(b.id)[-1].detail


# -- the wake-up call to the ADM or DM -----------------------------------------------------------------
def timed_out_without_calls(repo, level="warning"):
    """The chain ran out with no reminder call on record (each officer had opened the link, say)."""
    s = steps(repo)
    a = make_alert(repo, level)
    s.handle({"step": "draft", "alert_id": a.id})
    for i in range(3):
        s.handle({"step": "next_officer", "alert_id": a.id, "officer_index": i})
    return s, a


def test_with_voice_off_the_call_is_recorded_as_not_possible(repo, frozen, workflow, tg, no_network):
    night_roster(repo)
    repo.put_officer_phone("adm_mandi", ADM_PHONE)
    s, a = timed_out_without_calls(repo)
    out = last_call(s, a)
    assert out["call"] == "not_possible"
    call = repo.get_officer_call(a.id, "adm_mandi")
    assert call.status == "not_possible" and "voice provider is off" in call.reason
    assert "call=not possible (voice provider is off" in repo.list_timeline(a.id)[-1].detail


def test_with_voice_on_the_adm_is_phoned(repo, frozen, workflow, calls, tg):
    night_roster(repo)
    repo.put_officer_phone("adm_mandi", ADM_PHONE)
    s, a = timed_out_without_calls(repo)
    out = last_call(s, a)
    assert out["call"] == "placed"
    assert calls.form()["From"] == ADM_PHONE and len(calls.requests) == 1
    assert repo.get_officer_call(a.id, "adm_mandi").status == "placed"
    assert "adm_mandi (escalation (ADM)) call=placed (exotel)" in repo.list_timeline(a.id)[-1].detail
    assert repo.get_alert(a.id).status == "pending"  # the call never approves


def test_an_adm_rung_at_their_own_reminder_is_not_rung_twice(repo, frozen, workflow, calls, tg):
    night_roster(repo)
    repo.put_officer_phone("adm_mandi", ADM_PHONE)
    s, a = chain_timed_out(repo)  # the ADM's own reminder rang them
    assert len(calls.requests) == 1
    out = last_call(s, a)
    assert out["call"] == "placed" and len(calls.requests) == 1
    assert "at their own reminder, not rung twice" in repo.list_timeline(a.id)[-1].detail


def test_no_adm_on_the_roster_is_said_plainly(repo, frozen, workflow, tg, no_network):
    night_roster(repo, escalation=None)
    s, a = chain_timed_out(repo)
    out = last_call(s, a)
    assert out["call"] == "not_possible" and out["officers"] == 2
    assert "no ADM or DM on the roster" in repo.list_timeline(a.id)[-1].detail


# -- replays never reach a real officer -----------------------------------------------------------------
def test_a_replay_notifies_nobody_and_pages_nobody(repo, frozen, workflow, tg, push, calls, capsys):
    night_roster(repo)
    chats(repo)
    repo.put_officer_phone("adm_mandi", ADM_PHONE)
    subscribe(repo, push, "adm_mandi", "adm")
    s, a = chain_timed_out(repo, replay=True)
    tg.calls.clear()
    push.received.clear()
    capsys.readouterr()
    out = last_call(s, a)
    assert out == {"alert_id": a.id, "officers": 0, "reached": 0, "telegram": 0, "push": 0, "call": "not_possible"}
    assert tg.calls == [] and push.received == [] and calls.requests == []
    assert unanswered_metrics(capsys) == []
    assert "Replay: no officer is messaged or phoned" in repo.list_timeline(a.id)[-1].detail
    s.handle({"step": "expire", "alert_id": a.id})
    assert unanswered_metrics(capsys) == []


# -- the re-ask cooldown follows the level --------------------------------------------------------------
def _unsent(repo, frozen, workflow, level):
    v = repo.get_village("thunag")
    peak = getattr(v.thresholds, level)
    first = de.recompute_village(repo, v, now=frozen["now"], reading=reading(v, frozen["now"], peak),
                                 workflow=workflow).alert_id
    assert first and repo.get_alert(first).level == level
    s = steps(repo)
    s.handle({"step": "draft", "alert_id": first})
    s.handle({"step": "expire", "alert_id": first})
    s.handle({"step": "close", "alert_id": first, "outcome": "expired"})
    return first, peak


def _sweep(repo, frozen, workflow, peak):
    v = repo.get_village("thunag")
    return de.recompute_village(repo, v, now=frozen["now"], reading=reading(v, frozen["now"], peak),
                                workflow=workflow).alert_id


@pytest.mark.parametrize("level,cooldown", [("critical", 5), ("warning", 30), ("watch", 60)])
def test_reask_cooldown_follows_the_level(repo, frozen, workflow, level, cooldown):
    first, peak = _unsent(repo, frozen, workflow, level)
    frozen["now"] += timedelta(minutes=cooldown) - timedelta(seconds=30)
    assert _sweep(repo, frozen, workflow, peak) is None  # inside the cooldown
    frozen["now"] += timedelta(seconds=60)
    again = _sweep(repo, frozen, workflow, peak)
    assert again and again != first
    assert repo.get_alert(again).decision_trace["reask"]["cooldown_minutes"] == cooldown


def test_a_critical_is_asked_again_on_the_next_sweep(repo, frozen, workflow):
    first, peak = _unsent(repo, frozen, workflow, "critical")
    frozen["now"] += timedelta(minutes=15)  # the next 15-minute sweep
    assert _sweep(repo, frozen, workflow, peak) not in {None, first}


def test_cooldowns_are_configurable_and_a_critical_never_waits_more_than_5_minutes(monkeypatch):
    monkeypatch.setenv("PUKAAR_REASK_COOLDOWN_CRITICAL_MINUTES", "0")
    monkeypatch.setenv("PUKAAR_REASK_COOLDOWN_WARNING_MINUTES", "20")
    monkeypatch.setenv("PUKAAR_REASK_COOLDOWN_WATCH_MINUTES", "90")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert (s.reask_cooldown("critical"), s.reask_cooldown("warning"), s.reask_cooldown("watch")) == (0, 20, 90)
        monkeypatch.setenv("PUKAAR_REASK_COOLDOWN_CRITICAL_MINUTES", "30")
        get_settings.cache_clear()
        assert get_settings().reask_cooldown("critical") == 5
    finally:
        for k in ("CRITICAL", "WARNING", "WATCH"):
            monkeypatch.delenv(f"PUKAAR_REASK_COOLDOWN_{k}_MINUTES")
        get_settings.cache_clear()
    d = get_settings()
    assert (d.reask_cooldown("critical"), d.reask_cooldown("warning"), d.reask_cooldown("watch")) == (5, 30, 60)


# -- the local runner follows the state machine -----------------------------------------------------------
def test_the_local_runner_gives_the_last_call_then_expires(repo, frozen, tg, no_network, capsys):
    from Pukaar.workflow.client import LocalWorkflow
    from Pukaar.workflow.steps import Steps

    night_roster(repo)
    chats(repo)
    a = make_alert(repo, "warning")
    wf = LocalWorkflow(lambda: repo, lambda r: Steps(r, None, synthesize=lambda *_: None),
                       approval_timeout=0.02, ack_wait=0)
    wf.start(a)
    wf.threads[-1].join(timeout=10)
    steps_run = [t.step for t in repo.list_timeline(a.id)]
    assert "unanswered" in steps_run and steps_run.index("unanswered") < steps_run.index("expired")
    assert repo.get_alert(a.id).status == "expired"
    assert len(unanswered_metrics(capsys)) == 1
