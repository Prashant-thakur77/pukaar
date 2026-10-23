"""The live jury demo (services/demo.py, api/routers/demo.py, docs/DEMO_LIVE.md): jurors join by a rotating code
after a notice, the presenter approves one labelled practice alert, and only the jurors' phones get it.

What is held here: the demo village and its alerts are excluded everywhere they should be (lists, the sweep, the
public pages, the CAP feed, SACHET, the counters, the ten pilot metrics, the sirens); a demo alert never reaches a
real village's people and a real alert never reaches a demo person; consent comes before anything is stored; the
code rotates and expires; at most 50 people and one alert per 2 minutes; everything is erased after 24 hours; and
the Cedar matrix (run_demo, view_demo; the public demo accounts watch but never start)."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from Pukaar.core import clock
from Pukaar.delivery import dispatch
from Pukaar.policy.guard import SYSTEM, Principal, authorize, evaluate
from Pukaar.services import demo, sachet_request
from Pukaar.store.models import Alert, Recipient
from Pukaar.workflow.client import decide
from Pukaar.workflow.steps import Steps

from test_rollcall import SECRET, FakeTelegram

OFFICER = Principal("officer1", "officer")
JUDGE = Principal("judge", "officer")


@pytest.fixture()
def tg(monkeypatch):
    from Pukaar.delivery import telegram

    fake = FakeTelegram()
    monkeypatch.setattr(telegram, "configured", lambda: True)
    monkeypatch.setattr(telegram, "_call", fake)
    return fake


@pytest.fixture()
def client(repo, monkeypatch, workflow):
    from Pukaar.api import auth
    from Pukaar.api.routers import demo as demo_router
    from Pukaar.api.routers import officer, public, reach, reports, status, telegram
    from Pukaar.main import app

    for mod in (auth, public, officer, telegram, demo_router, reach, reports, status):
        monkeypatch.setattr(mod, "get_repo", lambda: repo)
    monkeypatch.setattr("Pukaar.store.repo.get_repo", lambda: repo)
    for mod in (demo_router, officer):
        monkeypatch.setattr(mod, "get_workflow", lambda: workflow)
    monkeypatch.setenv("PUKAAR_TELEGRAM_WEBHOOK_SECRET", SECRET)
    return TestClient(app)


def token(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def say(client, text, chat, first="Asha"):
    r = client.post("/telegram/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
                    json={"message": {"text": text, "chat": {"id": int(chat), "first_name": first}}})
    assert r.status_code == 200, r.text


def press(client, data, chat, first="Asha", n=1):
    r = client.post("/telegram/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
                    json={"callback_query": {"id": f"cb{n}", "data": data, "from": {"first_name": first, "last_name": "Rao"},
                                             "message": {"chat": {"id": int(chat)}}}})
    assert r.status_code == 200, r.text


def join_by_telegram(client, code, chat, first="Asha"):
    say(client, f"/start demo-{code}", chat, first)
    press(client, f"dconsent:{code}", chat, first)


def joined(repo, n, *, start=7000):
    """n demo people by the service (no Telegram), with the current code."""
    code = repo.get_demo_session()["code"]
    for i in range(n):
        chat = str(start + i)
        demo.ask_consent(repo, chat, code)
        demo.join(repo, chat, code, f"J{i}")
    return [str(start + i) for i in range(n)]


def run_to_delivery(repo, workflow, alert_id, by="officer1"):
    """The approval workflow for a demo alert as Step Functions would run it, the presenter approving."""
    s = Steps(repo, synthesize=lambda *_: None)
    s.handle({"step": "draft", "alert_id": alert_id})
    s.handle({"step": "ask_officer", "alert_id": alert_id, "officer_index": 0, "task_token": "tok-1"})
    decide(repo, workflow, alert_id, "approved", by)
    s.handle({"step": "sirens", "alert_id": alert_id})
    s.handle({"step": "deliver", "alert_id": alert_id})
    return s


def demo_alert(repo, workflow, frozen, n_people=2, deliver=True):
    demo.open_session(repo, "officer1")
    people = joined(repo, n_people)
    a = demo.start_alert(repo, workflow, "officer1")
    if deliver:
        run_to_delivery(repo, workflow, a.id)
    return repo.get_alert(a.id), people


# -- the demo village: excluded everywhere -------------------------------------------------------------------
def test_the_demo_village_is_in_no_list_and_hidden_by_id(repo, frozen, workflow, tg):
    a, _ = demo_alert(repo, workflow, frozen)
    assert "demo" not in repo.village_ids()
    assert all(not v.demo and v.id != "demo" for v in repo.list_villages())
    assert repo.get_village("demo") is None
    assert repo.get_village("demo", include_demo=True).demo is True
    # every list of alerts reads ALERTLOG; the demo alert is in DEMOLOG only
    assert a.id not in repo.all_alert_ids() and a.id not in {x.id for x in repo.list_alerts(limit=500)}
    assert [aid for _, aid in repo.demo_alert_ids()] == [a.id]


def test_public_pages_feeds_and_counters_never_show_the_demo(client, repo, frozen, workflow, tg):
    a, _ = demo_alert(repo, workflow, frozen)
    assert a.status == "delivered" and a.delivered_count == 2
    assert "demo" not in {v["id"] for v in client.get("/villages").json()}
    for path in ("/villages/demo", "/villages/demo/safe-places", "/public/villages/demo/now", "/cap/alerts/" + a.id + ".xml"):
        assert client.get(path).status_code == 404, path
    overview = client.get("/public/overview").json()
    assert "demo" not in {v["id"] for v in overview["villages"]}
    assert a.id not in {x["id"] for x in overview["recent_alerts"]}
    assert overview["counters"]["alerts_sent"] == 0 and overview["counters"]["drills_delivered"] == 0
    assert overview["counters"]["villages_watched"] == len(repo.list_villages())
    assert a.id not in client.get("/cap/alerts.atom").text
    pm = client.get("/public/pilot-metrics").json()
    assert pm["ten"]["drill"]["alerts"] == 0 and pm["ten"]["live"]["alerts"] == 0 and pm["ten"]["replay"]["alerts"] == 0
    assert pm["ten"]["coverage"]["villages"] == len(repo.list_villages())
    assert pm["ten"]["coverage"]["registered_phones"] == 0  # the jurors are not anyone's coverage
    assert a.id not in json.dumps(pm) and "डेमो" not in json.dumps(pm, ensure_ascii=False)
    # a report, a household form or a staff list never reaches the demo village
    assert client.post("/reports", data={"village_id": "demo", "text": "पानी"}).status_code == 404
    h = token(client, "officer1")
    assert client.get("/villages/demo/households", headers=h).status_code == 404


def test_sweep_sirens_and_sachet_never_touch_the_demo(repo, frozen, workflow, tg):
    from Pukaar.services import decision_engine as de

    from test_sweep import make_reading

    a, _ = demo_alert(repo, workflow, frozen)
    results = de.sweep_all(repo, now=frozen["now"], fetch=lambda v, at: make_reading(v, at, 0.1), workflow=workflow)
    assert "demo" not in {r.village_id for r in results} and results
    assert repo.list_readings("demo") == []
    assert repo.list_devices("demo") == [] and repo.list_siren_rows(a.id) == []
    with pytest.raises(sachet_request.NotRequestable):
        sachet_request.prepare(repo, a, "officer1", "officer")
    assert not evaluate(OFFICER, "request_sachet", "alert", a.id, {"level": "warning", "demo": True}).allowed
    assert not evaluate(SYSTEM, "sound_siren", "alert", a.id,
                        {"level": "warning", "approved": True, "pattern": "W1", "demo": True}).allowed
    # no roll-call and no after-action report when it closes
    s = Steps(repo, synthesize=lambda *_: None)
    out = s.handle({"step": "close", "alert_id": a.id, "outcome": "delivered"})
    assert "rollcall_id" not in out and "after_action_key" not in out
    assert repo.list_rollcalls("demo") == []
    assert repo.get_village("demo", include_demo=True).open_alert_id is None


def test_no_outcome_and_no_why_we_warned_note_for_a_demo_alert(client, repo, frozen, workflow, tg):
    from Pukaar.services import followup

    a, _ = demo_alert(repo, workflow, frozen)
    Steps(repo, synthesize=lambda *_: None).handle({"step": "close", "alert_id": a.id, "outcome": "delivered"})
    r = client.post(f"/alerts/{a.id}/outcome", json={"outcome": "no_flood"}, headers=token(client, "officer1"))
    assert r.status_code == 409
    assert followup.send(repo, repo.get_alert(a.id), "outcome") is None


def test_demo_alerts_are_kind_demo_and_never_pooled(repo, frozen, workflow, tg):
    from Pukaar.api import views
    from Pukaar.services import pilot_metrics

    a, _ = demo_alert(repo, workflow, frozen)
    assert pilot_metrics.kind_of(a) == "demo" and views.is_demo(a) and not views.is_drill(a)
    pooled = pilot_metrics.ten(repo, [a])  # even handed the alert, nothing pools it
    assert pooled["live"]["alerts"] == pooled["drill"]["alerts"] == pooled["replay"]["alerts"] == 0
    assert views.counters(repo)["drills_delivered"] == 0


# -- isolation: demo to demo people only, real to real people only --------------------------------------------
def test_a_demo_alert_reaches_only_demo_people(repo, frozen, workflow, tg):
    repo.put_recipient(Recipient(id="9100", village_id="gohar", name="Real Person", channel="telegram"))
    # a non-demo person written into the demo village by hand is never sent the demo alert either
    repo.put_recipient(Recipient(id="9101", village_id="demo", name="Stray", channel="telegram"))
    a, people = demo_alert(repo, workflow, frozen)
    rows = {d.recipient_id for d in repo.list_deliveries(a.id)}
    assert rows == set(people)
    sent_to = {str(p["chat_id"]) for p in tg.sent("sendMessage") + tg.sent("sendAudio") if "reply_markup" in p
               and "ack:" in json.dumps(p["reply_markup"])}
    assert sent_to <= set(people) and "9100" not in sent_to and "9101" not in sent_to


def test_a_real_alert_never_reaches_a_demo_person(repo, frozen, workflow, tg):
    demo.open_session(repo, "officer1")
    people = joined(repo, 2)
    # a demo-joined person written into a real village by hand is still never sent a real alert
    repo.put_recipient(Recipient(id="9200", village_id="gohar", name="X", channel="telegram", enrolled_via="demo"))
    repo.put_recipient(Recipient(id="9201", village_id="gohar", name="Real", channel="telegram"))
    stamp = clock.iso(frozen["now"])
    real = Alert(id="alr_real1", village_id="gohar", village_name="Gohar", village_name_hi="गोहर", level="warning",
                 status="approved", approved=True, created_at=stamp, updated_at=stamp, text_hi="चेतावनी", text_en="w")
    repo.put_alert(real)
    dispatch.deliver(repo, repo.get_alert(real.id))
    rows = {d.recipient_id for d in repo.list_deliveries(real.id)}
    assert "9201" in rows and "9200" not in rows and not rows & set(people)
    assert all(r == "9201" or r.startswith("stub-") for r in rows)  # the seeded stub recipients aside


def test_cedar_keeps_a_demo_alert_in_the_demo_village():
    approved = {"approved": True, "level": "warning", "channel": "telegram"}
    for action in ("deliver", "all_clear", "followup"):
        assert evaluate(SYSTEM, action, "alert", "a", {**approved, "demo": True, "village_demo": True}).allowed, action
        assert not evaluate(SYSTEM, action, "alert", "a", {**approved, "demo": True, "village_demo": False}).allowed
        assert not evaluate(SYSTEM, action, "alert", "a", {**approved, "demo": False, "village_demo": True}).allowed
    assert evaluate(SYSTEM, "deliver", "alert", "a", {**approved}).allowed  # a live alert is unchanged
    crit = {"level": "critical", "all_officers_timed_out": True, "approved": True, "demo": True, "village_demo": True}
    assert not evaluate(SYSTEM, "auto_send", "alert", "a", crit).allowed
    assert not evaluate(SYSTEM, "failsafe", "alert", "a", crit).allowed


def test_the_demo_failsafe_sends_nothing(repo, frozen, workflow, tg):
    a, _ = demo_alert(repo, workflow, frozen, deliver=False)
    s = Steps(repo, synthesize=lambda *_: None)
    s.handle({"step": "draft", "alert_id": a.id})
    out = s.handle({"step": "failsafe", "alert_id": a.id, "error": "boom"})
    assert out["sent"] == 0 and repo.list_deliveries(a.id) == []


# -- the message ------------------------------------------------------------------------------------------------
def test_the_fixed_script_is_labelled_and_names_the_demo_village(repo, frozen, workflow, tg):
    a, people = demo_alert(repo, workflow, frozen)
    assert a.text_hi.startswith("अभ्यास / DEMO — यह असली चेतावनी नहीं है (this is not a real warning)")
    assert "डेमो गाँव" in a.text_hi and "Demo village" in a.text_en and a.reasoning_model == "fixed-demo-script"
    from Pukaar.templates import script

    body = a.text_hi.removeprefix(demo.LABEL_HI).strip()
    assert all(script.elements(body, "warning", "डेमो गाँव").values())
    assert not script.voice_check(a.text_hi)["over"]
    # the presenter was the one officer asked, with no wake-up call
    assert a.officer_chain == ["officer1"] and a.decided_by == "officer1"
    audio = tg.sent("sendAudio") or tg.sent("sendMessage")
    assert any("ack:" + a.id in json.dumps(p.get("reply_markup") or {}) for p in audio)


# -- consent before storage --------------------------------------------------------------------------------------
def test_consent_comes_before_anything_is_stored(client, repo, frozen, tg):
    code = demo.open_session(repo, "officer1")["code"]
    say(client, f"/start demo-{code}", "4401")
    assert repo.get_recipient("demo", "4401") is None and repo.get_demo_session()["joined"] == 0
    notice = tg.sent()[-1]
    assert ("This is a demo for the Tata Imagination Challenge jury; you will get one practice alert marked DEMO; "
            "your Telegram name and chat id are deleted within 24 hours.") in notice["text"]
    assert "टाटा इमेजिनेशन चैलेंज" in notice["text"]
    assert [b["callback_data"] for b in notice["reply_markup"]["inline_keyboard"][0]] == [f"dconsent:{code}", "noconsent"]
    press(client, "noconsent", "4401")
    press(client, f"dconsent:{code}", "4401", n=2)  # the wait was dropped: nothing stored
    assert repo.get_recipient("demo", "4401") is None
    join_by_telegram(client, code, "4402", first="Meera")
    r = repo.get_recipient("demo", "4402")
    assert r is not None and r.name == "Meera" and r.enrolled_via == "demo" and r.channel == "telegram"
    assert r.consent.startswith(f"telegram button, {demo.NOTICE_VERSION}") and r.joined_at
    assert repo.get_demo_session()["joined"] == 1
    press(client, f"dconsent:{code}", "4402", n=3)  # a double tap: still one
    assert repo.get_demo_session()["joined"] == 1


def test_a_demo_join_never_enrols_anyone_in_a_real_village(client, repo, frozen, tg):
    code = demo.open_session(repo, "officer1")["code"]
    join_by_telegram(client, code, "4410")
    assert repo.chat_villages("4410") == ["demo"]
    # "/start demo" (the village id) and a forged "consent:demo" button never enrol anyone
    say(client, "/start demo", "4411")
    press(client, "consent:demo", "4411")
    assert repo.get_recipient("demo", "4411") is None
    # /stop leaves the demo too
    say(client, "/stop", "4410")
    assert repo.get_recipient("demo", "4410") is None


# -- the code: rotation and expiry ---------------------------------------------------------------------------------
def test_the_code_rotates_and_expires(client, repo, frozen, tg):
    first = demo.open_session(repo, "officer1")["code"]
    assert len(first) == 4 and first.isdigit()
    second = demo.open_session(repo, "officer1")["code"]
    assert second != first
    say(client, f"/start demo-{first}", "4501")  # the old code
    assert tg.sent()[-1]["text"] == demo.EXPIRED and repo.get_recipient("demo", "4501") is None
    say(client, f"/start demo-{second}", "4502")  # notice shown, then the code changes before "I agree"
    demo.open_session(repo, "officer1")
    press(client, f"dconsent:{second}", "4502")
    assert repo.get_recipient("demo", "4502") is None
    third = repo.get_demo_session()["code"]
    frozen["now"] += timedelta(seconds=demo.CODE_TTL_SECONDS + 1)
    say(client, f"/start demo-{third}", "4503")
    assert tg.sent()[-1]["text"] == demo.EXPIRED and repo.get_recipient("demo", "4503") is None
    assert demo.status(repo, show_code=True)["code"] is None  # an expired code is not shown either
    say(client, "/start demo-0000", "4504")
    assert repo.get_recipient("demo", "4504") is None


# -- rate and abuse limits ---------------------------------------------------------------------------------------
def test_at_most_fifty_people_per_session(repo, frozen):
    demo.open_session(repo, "officer1")
    joined(repo, demo.MAX_PEOPLE)
    code = repo.get_demo_session()["code"]
    with pytest.raises(demo.DemoError) as e:
        demo.ask_consent(repo, "8999", code)
    assert e.value.code == "full"
    # a notice shown before the session filled cannot squeeze in either
    assert len(repo.list_recipients("demo")) == demo.MAX_PEOPLE
    repo.update_demo_session({"joined": demo.MAX_PEOPLE - 1})
    demo.ask_consent(repo, "8998", code)
    demo.ask_consent(repo, "8997", code)
    demo.join(repo, "8998", code, "A")
    with pytest.raises(demo.DemoError) as e:
        demo.join(repo, "8997", code, "B")
    assert e.value.code == "full" and repo.get_recipient("demo", "8997") is None


def test_one_demo_alert_per_two_minutes(repo, frozen, workflow, tg):
    a, _ = demo_alert(repo, workflow, frozen)
    repo.update_alert(a.id, status="delivered")
    repo.update_village("demo", open_alert_id=None)
    frozen["now"] += timedelta(seconds=60)
    with pytest.raises(demo.DemoError) as e:
        demo.start_alert(repo, workflow, "officer1")
    assert e.value.code == "too_soon" and e.value.status == 429 and 55 <= e.value.extra["retry_after"] <= 60
    frozen["now"] += timedelta(seconds=61)
    b = demo.start_alert(repo, workflow, "officer1")
    assert b.id != a.id
    frozen["now"] += timedelta(seconds=200)
    with pytest.raises(demo.DemoError) as e:  # the first is still waiting for its approval
        demo.start_alert(repo, workflow, "officer1")
    assert e.value.code == "open"


def test_no_alert_without_a_session_and_none_on_prod(repo, frozen, workflow, monkeypatch):
    with pytest.raises(demo.DemoError) as e:
        demo.start_alert(repo, workflow, "officer1")
    assert e.value.code == "no_session"
    monkeypatch.setattr(demo, "enabled", lambda: False)
    with pytest.raises(demo.DemoError) as e:
        demo.open_session(repo, "officer1")
    assert e.value.code == "disabled"


def test_live_demo_is_off_on_prod_by_default(monkeypatch):
    from Pukaar.core.config import get_settings

    monkeypatch.setenv("PUKAAR_STAGE", "prod")
    monkeypatch.delenv("PUKAAR_LIVE_DEMO", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().live_demo_enabled is False
        monkeypatch.setenv("PUKAAR_LIVE_DEMO", "true")
        get_settings.cache_clear()
        assert get_settings().live_demo_enabled is True
    finally:
        monkeypatch.delenv("PUKAAR_STAGE")
        monkeypatch.delenv("PUKAAR_LIVE_DEMO", raising=False)
        get_settings.cache_clear()
    assert get_settings().live_demo_enabled is True


# -- erasure ------------------------------------------------------------------------------------------------------
def test_everything_demo_is_erased_after_24_hours(repo, frozen, workflow, tg):
    repo.put_recipient(Recipient(id="7000", village_id="gohar", name="Also Real", channel="telegram"))
    a, people = demo_alert(repo, workflow, frozen)
    assert repo.list_deliveries(a.id)
    frozen["now"] += timedelta(hours=23)
    assert demo.erase_due(repo) == {"people": 0, "alerts": 0, "session": 0}
    frozen["now"] += timedelta(hours=1, seconds=1)
    out = demo.erase_due(repo)
    assert out == {"people": 2, "alerts": 1, "session": 1}
    assert repo.list_recipients("demo") == [] and repo.get_alert(a.id) is None and repo.list_deliveries(a.id) == []
    assert repo.demo_alert_ids() == [] and repo.get_demo_session() is None
    # the juror who is also enrolled in a real village keeps that enrolment
    assert repo.get_recipient("gohar", "7000") is not None and repo.chat_villages("7000") == ["gohar"]
    rows = repo.list_audit(clock.iso(frozen["now"])[:10])
    erase = [r for r in rows if r.action == "demo_erase"]
    assert erase and erase[-1].resource.startswith("demo:")
    for r in rows:
        if r.action.startswith("demo_"):
            assert not any(p in f"{r.reason} {r.resource}" for p in people + ["J0", "J1"]), r


def test_the_sweep_runs_the_demo_erasure(repo, frozen, workflow, tg, monkeypatch):
    from Pukaar.handlers import sweep

    a, _ = demo_alert(repo, workflow, frozen)
    frozen["now"] += timedelta(hours=25)
    monkeypatch.setattr(sweep, "get_repo", lambda: repo)
    monkeypatch.setattr(sweep, "get_workflow", lambda: workflow)
    monkeypatch.setattr(sweep, "sweep_all", lambda *a, **k: [])
    out = sweep.handler({})
    assert out["demo_erased"]["alerts"] == 1 and repo.get_alert(a.id) is None


def test_reset_erases_people_alerts_and_the_code(client, repo, frozen, workflow, tg):
    a, _ = demo_alert(repo, workflow, frozen)
    code = repo.get_demo_session()["code"]
    r = client.post("/demo/reset", headers=token(client, "officer1"))
    assert r.status_code == 200 and r.json()["erased"] == {"people": 2, "alerts": 1}
    assert repo.list_recipients("demo") == [] and repo.get_alert(a.id) is None and repo.get_demo_session() is None
    say(client, f"/start demo-{code}", "4601")
    assert repo.get_recipient("demo", "4601") is None


# -- the Cedar matrix ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("who", "role", "view", "run"), [
    ("officer1", "officer", True, True),
    ("state_operator1", "state_operator", True, True),
    ("judge", "officer", True, False),
    ("judge_pradhan", "pradhan", False, False),
    ("pradhan_thunag", "pradhan", False, False),
    ("ddma_mandi", "ddma_head", False, False),
    ("model", "agent", False, False),
])
def test_cedar_matrix_run_and_view_demo(who, role, view, run):
    p = Principal(who, role)
    assert evaluate(p, "view_demo", "app", "demo", {}).allowed is view
    assert evaluate(p, "run_demo", "app", "demo", {}).allowed is run


def test_the_presenter_approves_and_the_judge_cannot(repo, frozen, workflow, tg):
    a, _ = demo_alert(repo, workflow, frozen, deliver=False)
    Steps(repo, synthesize=lambda *_: None).handle({"step": "draft", "alert_id": a.id})
    ctx = {"replay": False, "level": "warning", "village_id": "demo"}
    # officer1 is assigned to no "Demo" district: the demo village is not held to one
    assert authorize(OFFICER, "approve", "alert", a.id, ctx, repo=repo).allowed
    assert authorize(Principal("state_operator1", "state_operator"), "approve", "alert", a.id, ctx, repo=repo).allowed
    assert not authorize(JUDGE, "approve", "alert", a.id, ctx, repo=repo).allowed
    assert not authorize(Principal("pradhan_thunag", "pradhan", ["thunag"]), "approve", "alert", a.id, ctx,
                         repo=repo).allowed
    # a caller cannot claim "demo" for a real village: the fact is read from the record
    real = {"replay": False, "level": "warning", "village_id": "sujanpur", "demo": True}
    assert not authorize(Principal("stranger", "officer"), "approve", "alert", "alr_x", real, repo=repo).allowed


def test_the_routes_follow_the_matrix(client, repo, frozen, workflow, tg):
    officer, judge, pradhan = token(client, "officer1"), token(client, "judge"), token(client, "pradhan_thunag")
    assert client.get("/demo").status_code == 401
    assert client.get("/demo", headers=pradhan).status_code == 403
    r = client.post("/demo/open", headers=officer)
    assert r.status_code == 200 and r.json()["code"] and r.json()["join_url"].endswith(f"start=demo-{r.json()['code']}")
    watch = client.get("/demo", headers=judge)
    assert watch.status_code == 200 and watch.json()["can_run"] is False
    assert watch.json()["code"] is None and watch.json()["join_url"] is None  # the code is the presenter's only
    for path in ("/demo/open", "/demo/alert", "/demo/reset"):
        assert client.post(path, headers=judge).status_code == 403, path
    assert repo.get_demo_session() is not None


def test_the_presenter_screen_counts_and_times(client, repo, frozen, workflow, tg):
    officer = token(client, "officer1")
    code = client.post("/demo/open", headers=officer).json()["code"]
    for chat, first in (("5001", "Asha"), ("5002", "Ravi"), ("5003", "Meena")):
        join_by_telegram(client, code, chat, first)
    assert client.get("/demo", headers=officer).json()["joined"] == 3
    r = client.post("/demo/alert", headers=officer)
    assert r.status_code == 200, r.text
    aid = r.json()["alert"]["id"]
    again = client.post("/demo/alert", headers=officer)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "open"
    s = Steps(repo, synthesize=lambda *_: None)
    s.handle({"step": "draft", "alert_id": aid})
    s.handle({"step": "ask_officer", "alert_id": aid, "officer_index": 0, "task_token": "tok-1"})
    # the normal approval route, as the console's hold-to-approve calls it
    assert client.post(f"/alerts/{aid}/approve", headers=token(client, "judge")).status_code == 403
    frozen["now"] += timedelta(seconds=4)
    assert client.post(f"/alerts/{aid}/approve", headers=officer).status_code == 200
    frozen["now"] += timedelta(seconds=2)
    s.handle({"step": "deliver", "alert_id": aid})
    frozen["now"] += timedelta(seconds=5)
    press(client, f"ack:{aid}", "5001")
    frozen["now"] += timedelta(seconds=10)
    press(client, f"ack:{aid}", "5002", n=2)
    press(client, f"ack:{aid}", "5002", n=3)  # a second tap counts once
    body = client.get("/demo", headers=officer).json()
    al = body["alert"]
    assert (al["targeted"], al["delivered"], al["confirmed"]) == (3, 3, 2)
    assert al["seconds"]["approved_to_first_sent"] == 2.0
    assert al["seconds"]["first_sent_to_first_ack"] == 5.0 and al["seconds"]["first_sent_to_median_ack"] == 10.0
    assert al["times"]["approved"] and al["times"]["first_sent"] and al["times"]["first_ack"]
    text = json.dumps(body, ensure_ascii=False)
    for personal in ("5001", "5002", "Asha", "Ravi", "Meena"):
        assert personal not in text
    # the same per-alert metrics a DDMA sees, from the console route
    m = client.get(f"/alerts/{aid}/metrics", headers=officer).json()
    assert m["kind"] == "demo" and m["confirmed_reach"]["confirmed"] == 2
