"""The district control room: duty roster, relays first, the all-clear and the night-time nudge.

services/roster.py (who is on duty, in IST), workflow/steps.py (the chain, the nudge, stand_down),
delivery/dispatch.py (relays first), policy/base.cedar ("officer-roster", "system-all-clear").
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from Pukaar.core import clock
from Pukaar.delivery import dispatch, voice
from Pukaar.policy.guard import SYSTEM, Principal, evaluate
from Pukaar.services import decision_engine as de
from Pukaar.services import roster
from Pukaar.store.models import Delivery, Reading, Recipient, RosterShift
from Pukaar.workflow import tokens
from Pukaar.workflow.client import LocalWorkflow, decide

from test_pilot_safety import metrics
from test_push import push, subscribe  # noqa: F401  (fixture)
from test_rollcall import tg  # noqa: F401  (fixture)
from test_workflow_steps import make_alert, steps

IST = timezone(timedelta(hours=5, minutes=30))


def ist(y, mo, d, h, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=IST).astimezone(timezone.utc)


def rostered(repo, day="2026-07-01", shift="day", primary="dso_day", backup="dso_backup", escalation="adm_mandi",
             title="ADM", district="Mandi") -> RosterShift:
    row = RosterShift(district=district, date=day, shift=shift, primary=primary, backup=backup, escalation=escalation,
                      escalation_title=title, updated_by="officer1", updated_at=clock.iso(clock.now()))
    repo.put_roster_shift(row)
    return row


# -- 1. who is on duty, in IST -------------------------------------------------------------------
@pytest.mark.parametrize(("when", "day", "shift"), [
    (ist(2026, 7, 1, 7, 59), "2026-06-30", "night"),   # before 08:00 IST: still last night's shift
    (ist(2026, 7, 1, 8, 0), "2026-07-01", "day"),
    (ist(2026, 7, 1, 19, 59), "2026-07-01", "day"),
    (ist(2026, 7, 1, 20, 0), "2026-07-01", "night"),
    (ist(2026, 7, 2, 2, 0), "2026-07-01", "night"),    # 02:00 IST belongs to the night that began at 20:00
    (datetime(2026, 7, 1, 20, 0, tzinfo=timezone.utc), "2026-07-01", "night"),  # 01:30 IST on 2 July
])
def test_the_shift_running_now_is_read_in_ist(when, day, shift):
    slot = roster.slot_at(when)
    assert (slot.date, slot.shift) == (day, shift)
    assert slot.starts_at <= when < slot.ends_at


def test_roster_resolution_across_the_evening_handover(repo, frozen):
    rostered(repo, "2026-07-01", "day", primary="dso_day", backup="dso_backup")
    rostered(repo, "2026-07-01", "night", primary="dso_night", backup="ddmo_mandi", escalation="dm_mandi", title="DM")
    before = roster.on_duty(repo, "Mandi", ist(2026, 7, 1, 19, 59))
    after = roster.on_duty(repo, "Mandi", ist(2026, 7, 1, 20, 0))
    late = roster.on_duty(repo, "Mandi", ist(2026, 7, 2, 3, 15))
    assert before.chain == ["dso_day", "dso_backup", "adm_mandi"]
    assert before.roles == ["primary", "backup", "escalation (ADM)"]
    assert after.chain == late.chain == ["dso_night", "ddmo_mandi", "dm_mandi"]
    assert late.roles[-1] == "escalation (DM)" and late.source == "roster"
    # A different district is not covered by Mandi's roster.
    assert roster.on_duty(repo, "Hamirpur", ist(2026, 7, 1, 21, 0)).source == "none"


def test_no_roster_falls_back_to_the_village_list(repo, frozen):
    village = repo.get_village("thunag")
    duty = roster.chain_for(repo, village)
    assert duty.source == "fallback" and duty.chain == village.officers == ["officer1", "officer2"]
    s = steps(repo)
    a = make_alert(repo)
    assert s.handle({"step": "draft", "alert_id": a.id})["officer_count"] == 2
    assert repo.get_alert(a.id).officer_chain == ["officer1", "officer2"]
    # A roster row for some other shift does not count for this one.
    rostered(repo, "2026-07-01", "day")  # NOW is 07:30 IST on 1 July: the night of 30 June is on duty
    assert roster.chain_for(repo, village).source == "fallback"


# -- 2. the escalation chain ----------------------------------------------------------------------
def test_escalation_order_is_primary_then_backup_then_adm(repo, frozen):
    rostered(repo, "2026-06-30", "night", primary="dso_night", backup="dso_backup", escalation="adm_mandi")
    s = steps(repo)
    a = make_alert(repo, "critical")
    out = s.handle({"step": "draft", "alert_id": a.id})
    assert out["officer_count"] == 3 and out["nudge_after_seconds"] + out["nudge_wait_seconds"] == 600
    asked = []
    index = 0
    while True:
        s.handle({"step": "ask_officer", "alert_id": a.id, "officer_index": index, "task_token": f"T{index}"})
        asked.append(repo.get_alert(a.id).officer_index)
        nxt = s.handle({"step": "next_officer", "alert_id": a.id, "officer_index": index})
        if not nxt["has_next"]:
            break
        index = nxt["officer_index"]
    alert = repo.get_alert(a.id)
    assert alert.officer_chain == ["dso_night", "dso_backup", "adm_mandi"] and asked == [0, 1, 2]
    assert alert.officers_asked == ["dso_night", "dso_backup", "adm_mandi"]
    lines = [t.detail for t in repo.list_timeline(a.id)]
    assert any("dso_night (primary) -> dso_backup (backup) -> adm_mandi (escalation (ADM))" in x for x in lines)
    timeouts = [t.detail for t in repo.list_timeline(a.id) if t.step == "officer_timeout"]
    assert timeouts == ["dso_night (primary) did not answer in time; asking dso_backup (backup)",
                        "dso_backup (backup) did not answer in time; asking adm_mandi (escalation (ADM))",
                        "adm_mandi (escalation (ADM)) did not answer in time; chain exhausted"]


def test_the_chain_is_frozen_when_drafted_so_a_shift_change_never_reorders_it(repo, frozen):
    rostered(repo, "2026-06-30", "night", primary="dso_night", backup="dso_backup")
    s = steps(repo)
    a = make_alert(repo)
    s.handle({"step": "draft", "alert_id": a.id})
    frozen["now"] = ist(2026, 7, 1, 8, 5)  # the day shift starts with someone else on the desk
    rostered(repo, "2026-07-01", "day", primary="dso_day", backup=None, escalation=None)
    s.handle({"step": "ask_officer", "alert_id": a.id, "officer_index": 1, "task_token": "T1"})
    assert repo.get_alert(a.id).officers_asked == ["dso_backup"]


def test_critical_auto_send_is_configurable_and_off_sends_nothing(repo, frozen, monkeypatch):
    from Pukaar.core.config import get_settings

    monkeypatch.setenv("PUKAAR_CRITICAL_AUTO_SEND", "false")
    get_settings.cache_clear()
    try:
        s = steps(repo)
        a = make_alert(repo, "critical")
        s.handle({"step": "draft", "alert_id": a.id})
        assert s.handle({"step": "auto_send", "alert_id": a.id})["mode"] == "off"
        alert = repo.get_alert(a.id)
        assert alert.status == "expired" and not repo.list_deliveries(a.id)
        assert "needs DDMA sign-off" in repo.list_timeline(a.id)[-1].detail
    finally:
        monkeypatch.delenv("PUKAAR_CRITICAL_AUTO_SEND")
        get_settings.cache_clear()


# -- 3. nobody on duty -----------------------------------------------------------------------------
def test_nobody_on_duty_emits_a_metric_per_district_without_a_roster(repo, frozen, capsys):
    capsys.readouterr()
    assert roster.nobody_on_duty(repo) == ["Hamirpur", "Mandi"]
    rows = [m for m in metrics(capsys) if "NobodyOnDuty" in m]
    assert sorted(m["District"] for m in rows) == ["Hamirpur", "Mandi"]
    rostered(repo, "2026-06-30", "night", district="Mandi")
    rostered(repo, "2026-06-30", "night", district="Hamirpur")
    assert roster.nobody_on_duty(repo) == []
    assert not [m for m in metrics(capsys) if "NobodyOnDuty" in m]


def test_the_sweep_handler_runs_the_on_duty_check(repo, frozen, monkeypatch, capsys):
    from Pukaar.handlers import sweep

    monkeypatch.setattr(sweep, "get_repo", lambda: repo)
    monkeypatch.setattr(sweep, "sweep_all", lambda r, workflow=None: [])
    monkeypatch.setattr(sweep, "get_workflow", lambda: None)
    monkeypatch.setattr(sweep.model_probe, "maybe_run", lambda r: None)
    capsys.readouterr()
    out = sweep.handler({})
    assert out["nobody_on_duty"] == ["Hamirpur", "Mandi"]
    assert any("NobodyOnDuty" in m for m in metrics(capsys))


def test_the_alarm_watches_the_metric():
    from test_template_safety import RES

    alarm = RES["NobodyOnDutyAlarm"]["Properties"]
    assert alarm["Metrics"][0]["Expression"] == "SELECT SUM(NobodyOnDuty) FROM Pukaar"
    assert alarm["Threshold"] == 1 and alarm["TreatMissingData"] == "notBreaching"


# -- 4. Cedar and the roster API -------------------------------------------------------------------
@pytest.mark.parametrize("action", ["edit_roster", "take_over_duty", "view_roster"])
def test_cedar_only_officers_touch_the_roster(action):
    assert evaluate(Principal("officer1", "officer"), action, "app", "pukaar").allowed
    assert not evaluate(Principal("pradhan_thunag", "pradhan", ["thunag"]), action, "app", "pukaar").allowed
    assert not evaluate(Principal("bot", "agent"), action, "app", "pukaar").allowed


@pytest.mark.parametrize("who", [Principal("judge", "officer"), Principal("judge_pradhan", "pradhan", ["thunag"])])
def test_cedar_judge_accounts_never_change_the_live_roster(who):
    for action in ("edit_roster", "take_over_duty"):
        d = evaluate(who, action, "app", "pukaar", {"replay": False})
        assert not d.allowed
    assert evaluate(Principal("judge", "officer"), "view_roster", "app", "pukaar").allowed


@pytest.fixture()
def api(repo, monkeypatch):
    from Pukaar.api import auth
    from Pukaar.api.routers import officer
    from Pukaar.main import app

    for mod in (auth, officer):
        monkeypatch.setattr(mod, "get_repo", lambda: repo)
    return TestClient(app)


def bearer(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_roster_api_edit_week_and_handover_are_audited(api, repo, frozen):
    h = bearer(api, "officer1")
    body = {"primary": "officer1", "backup": "officer2", "escalation": "adm_mandi", "escalation_title": "ADM"}
    r = api.post("/roster/Mandi/2026-06-30/night", json=body, headers=h)
    assert r.status_code == 200 and r.json()["primary"] == "officer1"
    week = api.get("/roster?district=Mandi&start=2026-06-30", headers=h).json()
    assert week["district"] == "Mandi" and week["districts"] == ["Hamirpur", "Mandi"]
    assert week["days"][0]["shifts"]["night"]["entry"]["escalation"] == "adm_mandi"
    assert week["critical_auto_send"] is True and week["critical_auto_send_label"] == "needs DDMA sign-off"
    now = {d["district"]: d for d in week["now"]}
    assert now["Mandi"]["chain"] == ["officer1", "officer2", "adm_mandi"] and now["Hamirpur"]["source"] == "fallback"
    # bad input is a 400 with the reason
    bad = api.post("/roster/Mandi/2026-06-30/night", json={**body, "backup": "officer1"}, headers=h)
    assert bad.status_code == 400 and "backup" in bad.json()["detail"]["reason"]
    assert api.post("/roster/Mandi/2026-06-30/evening", json=body, headers=h).status_code == 400
    # handover: officer2 takes over the shift running now
    r = api.post("/roster/Mandi/take-over", headers=bearer(api, "officer2"))
    assert r.status_code == 200
    row = repo.get_roster_shift("Mandi", "2026-06-30", "night")
    assert (row.primary, row.backup, row.taken_over_from) == ("officer2", "officer1", "officer1")
    audit = repo.list_audit(clock.iso(clock.now())[:10], "roster:Mandi/2026-06-30/night")
    actions = {a.action: a for a in audit}
    assert "roster_changed" in actions and "duty_taken_over" in actions
    assert actions["duty_taken_over"].actor == "officer2" and "from officer1" in actions["duty_taken_over"].reason
    assert api.delete("/roster/Mandi/2026-06-30/night", headers=h).json() == {"cleared": True}


def test_roster_api_refuses_pradhans_and_judge_accounts(api, repo, frozen):
    body = {"primary": "officer1"}
    for user in ("pradhan_thunag", "judge", "judge_pradhan"):
        h = bearer(api, user)
        assert api.post("/roster/Mandi/2026-07-01/day", json=body, headers=h).status_code == 403
        assert api.post("/roster/Mandi/take-over", headers=h).status_code == 403
        assert api.delete("/roster/Mandi/2026-07-01/day", headers=h).status_code == 403
    assert repo.get_roster_shift("Mandi", "2026-07-01", "day") is None
    assert api.get("/roster", headers=bearer(api, "pradhan_thunag")).status_code == 403
    assert api.get("/roster", headers=bearer(api, "judge")).status_code == 200
    assert api.get("/roster").status_code == 401


# -- 5. relays first ---------------------------------------------------------------------------------
def people(repo):
    """Two villagers registered before the pradhan, a task-force volunteer, and the gauge reader."""
    for rid, name, role in (("5550001", "Asha Devi", "villager"), ("5550002", "Ravi Kumar", "villager"),
                            ("5550003", "Mohan Lal", "pradhan"), ("5550004", "Sita Ram", "task_force"),
                            ("5550005", "Kamla", "gauge_reader")):
        repo.put_recipient(Recipient(id=rid, village_id="thunag", name=name, channel="telegram", role=role))


def approved(repo, workflow, level="warning", replay=False):
    s = steps(repo)
    a = make_alert(repo, level, replay)
    s.handle({"step": "draft", "alert_id": a.id})
    s.handle({"step": "ask_officer", "alert_id": a.id, "officer_index": 0, "task_token": "TOKEN-1"})
    decide(repo, workflow, a.id, "approved", "officer1")
    s.handle({"step": "deliver", "alert_id": a.id})
    return s, repo.get_alert(a.id)


def test_relays_are_contacted_first_and_told_to_sound_the_siren(repo, frozen, workflow, tg):
    people(repo)
    _, alert = approved(repo, workflow)
    order = [p["chat_id"] for p in tg.sent()]
    assert order[:3] == ["5550003", "5550004", "5550005"] and set(order[3:]) == {"5550001", "5550002"}
    texts = {p["chat_id"]: p["text"] for p in tg.sent()}
    assert texts["5550003"].startswith("आप गाँव के रिले हैं") and alert.text_hi in texts["5550003"]
    assert texts["5550001"] == alert.text_hi
    first = dispatch.relays_first(repo.list_recipients("thunag"))[:4]
    assert sorted(r.role for r in first) == ["gauge_reader", "pradhan", "pradhan", "task_force"]  # + the demo pradhan


def test_a_relay_acknowledgement_is_recorded_as_relay_done(repo, frozen, workflow, tg, api):
    people(repo)
    _, alert = approved(repo, workflow)
    dispatch.acknowledge(repo, alert.id, "5550003")
    dispatch.acknowledge(repo, alert.id, "5550003")  # a second tap changes nothing
    dispatch.acknowledge(repo, alert.id, "5550001")  # a villager's acknowledgement is not a relay
    done = [t.detail for t in repo.list_timeline(alert.id) if t.step == "relay_done"]
    assert done == ["relay done: siren and megaphone (Mohan, Pradhan, by telegram)"]
    detail = api.get(f"/alerts/{alert.id}", headers=bearer(api, "officer1")).json()
    rows = {d["recipient_id"]: d for d in detail["deliveries"]}
    assert rows["5550003"]["relay_role"] == "pradhan" and rows["5550004"]["relay_role"] == "task_force"
    assert rows["5550001"]["relay_role"] is None
    assert any(t["step"] == "relay_done" for t in detail["timeline"])


# -- 6. the all-clear ------------------------------------------------------------------------------
def all_clears(tg) -> dict[str, str]:
    return {p["chat_id"]: p["text"] for p in tg.sent() if "ख़तरा टल गया" in p["text"]}


def test_all_clear_reaches_exactly_those_contacted_and_the_officers_asked(repo, frozen, workflow, tg, push):
    from Pukaar.workflow.steps import stand_down_village

    repo.put_officer_chat("officer1", "9990001")
    repo.put_officer_chat("officer2", "9990002")  # never asked: no all-clear
    phone = subscribe(repo, push, "officer1", "a")
    people(repo)
    s, alert = approved(repo, workflow)
    # One person's Telegram failed, and one joined after the alert: neither was contacted.
    repo.update_delivery(alert.id, "5550002", status="failed", error="Forbidden: bot was blocked by the user")
    repo.put_recipient(Recipient(id="5550009", village_id="thunag", name="Late Joiner", channel="telegram"))
    tg.calls.clear()
    push.received.clear()
    out = stand_down_village(repo, "thunag", replay=False, by="system", reason="the village is back to normal")
    got = all_clears(tg)
    assert set(got) == {"5550001", "5550003", "5550004", "5550005", "9990001"}
    assert "Pukaar, Thunag: the flood danger has passed" in got["5550001"]
    assert f"Alert {alert.id} stood down: the village is back to normal." in got["9990001"]
    assert [p["kind"] for _, p, _ in push.received] == ["all_clear"] and push.received[0][0] == phone.endpoint
    a = repo.get_alert(alert.id)
    assert out["alerts"] == [alert.id] and (a.all_clear_sent, a.all_clear_failed) == (6, 0)  # 4 phones + 2 demo stubs
    assert a.all_clear_by == "system" and a.all_clear_at
    rows = {d.recipient_id: d for d in repo.list_deliveries(alert.id)}
    assert rows["5550002"].all_clear_status is None and rows["stub-thunag-1"].all_clear_status == "stub"
    assert rows["5550001"].all_clear_status == "sent"
    assert "All-clear to 6 people" in repo.list_timeline(alert.id)[-1].detail
    # Once only, and no warning is re-sent after the all-clear.
    tg.calls.clear()
    assert stand_down_village(repo, "thunag", replay=False, by="system", reason="again")["alerts"] == []
    assert s.handle({"step": "recall", "alert_id": alert.id})["resent"] == 0 and not tg.sent()


def test_all_clear_never_reaches_a_real_phone_for_a_replay(repo, frozen, workflow, tg, push):
    from Pukaar.workflow.steps import stand_down_village

    repo.put_officer_chat("officer1", "9990001")
    subscribe(repo, push, "officer1", "a")
    people(repo)
    _, alert = approved(repo, workflow, replay=True)
    # Even a row that somehow names Telegram on a replay alert is refused by Cedar, not sent.
    repo.put_delivery(Delivery(alert_id=alert.id, recipient_id="5550001", name="Asha Devi", channel="telegram",
                               status="sent", sent_at=clock.iso(clock.now()), attempts=1))
    tg.calls.clear()
    push.received.clear()
    stand_down_village(repo, "thunag", replay=True, by="system", reason="the replay village is back to normal")
    assert not tg.calls and not push.received
    rows = {d.recipient_id: d for d in repo.list_deliveries(alert.id)}
    assert rows["5550001"].all_clear_status == "failed" and "blocked" in rows["5550001"].all_clear_error
    assert all(d.all_clear_status == "stub" for rid, d in rows.items() if rid != "5550001")
    assert "replay: stub only, no real phone" in repo.list_timeline(alert.id)[-1].detail
    assert not evaluate(SYSTEM, "all_clear", "alert", alert.id, {"replay": True, "channel": "telegram"}).allowed
    assert not evaluate(SYSTEM, "all_clear", "alert", alert.id, {"replay": True, "channel": "voice"}).allowed
    assert evaluate(SYSTEM, "all_clear", "alert", alert.id, {"replay": True, "channel": "stub"}).allowed


def test_back_to_normal_in_the_sweep_stands_the_village_down(repo, frozen, workflow, tg):
    people(repo)
    _, alert = approved(repo, workflow)
    repo.update_village("thunag", level="watch", calm_sweeps=2)  # the third calm sweep steps down to normal
    v = repo.get_village("thunag")
    calm = Reading(village_id="thunag", at=clock.iso(frozen["now"]), rain_24h_mm=0.0, discharge=0.0)
    tg.calls.clear()
    res = de.recompute_village(repo, v, now=frozen["now"], reading=calm, workflow=workflow)
    assert res.level == "normal"
    assert set(all_clears(tg)) == {"5550001", "5550002", "5550003", "5550004", "5550005"}
    assert repo.get_alert(alert.id).all_clear_reason == "the village is back to normal"


def test_an_officer_all_clear_directive_stands_the_village_down(repo, frozen, workflow, tg, api):
    people(repo)
    _, alert = approved(repo, workflow)
    tg.calls.clear()
    r = api.post("/directives", json={"village_id": "thunag", "type": "all_clear"}, headers=bearer(api, "officer2"))
    assert r.status_code == 200 and r.json()["stood_down"]["alerts"] == [alert.id]
    assert len(all_clears(tg)) == 5
    a = repo.get_alert(alert.id)
    assert a.all_clear_by == "officer2" and a.all_clear_reason == "an officer issued the all-clear"


def test_all_clear_calls_voice_recipients_without_a_menu_or_counter(repo, frozen, workflow, tg, monkeypatch):
    """A voice recipient hears the all-clear by call (delivery/voice.py), signed as attempt 0."""
    from test_voice import EXOTEL_ENV, KEY, FakeProvider, _settings

    from Pukaar.api.routers import voice as voice_router
    from Pukaar.main import app
    from Pukaar.workflow.steps import stand_down_village

    _settings(monkeypatch, "exotel", **EXOTEL_ENV)
    fake = FakeProvider("exotel")
    voice.set_http_client(httpx.Client(transport=httpx.MockTransport(fake)))
    try:
        repo.put_recipient(Recipient(id="v_asha", village_id="thunag", name="Asha Devi", channel="voice",
                                     phone="+919812345678", consent="test", role="pradhan"))
        _, alert = approved(repo, workflow)
        before = repo.get_delivery(alert.id, "v_asha", "voice")
        assert fake.n == 1 and before.call_ids == ["exo-call-1"]
        stand_down_village(repo, "thunag", replay=False, by="officer1", reason="an officer issued the all-clear")
        row = repo.get_delivery(alert.id, "v_asha", "voice")
        assert fake.n == 2 and row.all_clear_status == "sent" and row.all_clear_call_id == "exo-call-2"
        assert fake.form()["CustomField"].split(".")[3] == str(voice.ALL_CLEAR_ATTEMPT)
        monkeypatch.setattr(voice_router, "get_repo", lambda: repo)
        client = TestClient(app)
        tok = voice.sign_call(alert.id, "v_asha", voice.ALL_CLEAR_ATTEMPT)
        greet = client.get("/voice/exotel/flow", params={"k": KEY, "CustomField": tok, "CallSid": "exo-call-2"})
        assert greet.status_code == 200 and "ख़तरा टल गया" in greet.text
        menu = client.get("/voice/exotel/flow", params={"k": KEY, "part": "menu", "CustomField": tok,
                                                        "CallSid": "exo-call-2"}).json()
        assert menu["repeat_menu"] == 0 and "1 दबाएँ" not in menu["gather_prompt"]["text"]
        key = client.get("/voice/exotel/gather", params={"k": KEY, "CustomField": tok, "CallSid": "exo-call-2",
                                                         "digits": '"1"'})
        assert key.text == "all_clear"
        status = client.post(f"/voice/exotel/status?k={KEY}&c={tok}", data={"CallSid": "exo-call-2", "Status": "busy"})
        assert status.json()["outcome"] == "all_clear"
        after = repo.get_delivery(alert.id, "v_asha", "voice")
        assert (after.attempts, after.not_connected, after.acknowledged_at, after.call_ids) == (
            before.attempts, before.not_connected, None, ["exo-call-1"])
        # An all-clear token never names an alert call, and an alert-call token never the all-clear call.
        forged = client.get("/voice/exotel/flow", params={"k": KEY, "CustomField": tok, "CallSid": "exo-call-1"})
        assert forged.status_code == 403
    finally:
        voice.set_http_client(None)
        from Pukaar.core.config import get_settings

        monkeypatch.delenv("PUKAAR_VOICE_PROVIDER")
        get_settings.cache_clear()


# -- 7. the night-friendly nudge -------------------------------------------------------------------
def test_the_primary_is_nudged_on_every_channel_before_escalating(repo, frozen, workflow, tg, push):
    rostered(repo, "2026-06-30", "night", primary="officer1", backup="officer2", escalation="adm_mandi")
    repo.put_officer_chat("officer1", "9990001")
    subscribe(repo, push, "officer1", "a")
    s = steps(repo)
    a = make_alert(repo)
    s.handle({"step": "draft", "alert_id": a.id})
    s.handle({"step": "ask_officer", "alert_id": a.id, "officer_index": 0, "task_token": "TOKEN-1"})
    first = repo.get_alert(a.id)
    tg.calls.clear()
    push.received.clear()
    out = s.handle({"step": "nudge_officer", "alert_id": a.id, "officer_index": 0, "task_token": "TOKEN-2"})
    assert out["officer"] == "officer1" and out["telegram"] is True and out["push"] == 1
    reminder = tg.sent()[0]
    assert reminder["chat_id"] == "9990001" and reminder["text"].startswith("पुकार, याद दिलाना")
    assert "next officer is asked in 5 min" in reminder["text"]
    p = push.received[0][1]
    assert p["title"].startswith("याद दिलाना · Reminder") and p["kind"] == "approval"
    nudged = repo.get_alert(a.id)
    assert nudged.task_token == "TOKEN-2" and nudged.token_version == first.token_version and nudged.nudges == 1
    assert repo.list_timeline(a.id)[-1].step == "nudged_officer"
    # The link from the first message still works, and the decision reaches the reminder's token.
    t = tokens.verify(p["data"]["token"], "approve")
    assert t.version == first.token_version
    decide(repo, workflow, a.id, "approved", "officer1", token_version=t.version)
    assert workflow.successes[-1][0] == "TOKEN-2"


def test_local_workflow_nudges_half_way_then_asks_the_backup(repo, frozen, monkeypatch):
    rostered(repo, "2026-06-30", "night", primary="officer1", backup="officer2", escalation=None)
    seen: list[tuple[str, int]] = []

    class Recorder:
        def __init__(self, r):
            self.inner = steps(r)

        def handle(self, e):
            if e["step"] in {"ask_officer", "nudge_officer"}:
                seen.append((e["step"], e["officer_index"]))
            return self.inner.handle(e)

    wf = LocalWorkflow(lambda: repo, Recorder, approval_timeout=0.02, ack_wait=0)
    a = make_alert(repo, "warning")
    wf._run(a.id)
    assert seen == [("ask_officer", 0), ("nudge_officer", 0), ("ask_officer", 1), ("nudge_officer", 1)]
    assert repo.get_alert(a.id).status == "expired"
