"""The siren tier (services/sirens.py, handlers/device_ingest.py, the SoundSirens step): who may sound a
siren, with which pattern, what "verified" means, and that a siren never stands in for a person reached.

Everything runs against moto and a fake shadow transport; the devices are the seeded labelled simulators
plus, where a test needs one, a registered "real" siren (installed, not simulated).
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from Pukaar.core import clock
from Pukaar.handlers import device_ingest
from Pukaar.policy.guard import SYSTEM, Principal, evaluate
from Pukaar.services import cap, risk_rules, sirens
from Pukaar.services.devices import keys, protocol, registry, shadow
from Pukaar.store.models import Device
from Pukaar.workflow.steps import stand_down
from test_workflow_steps import make_alert, steps

SIM = "siren-thunag-sim"
REAL = "siren-thunag-01"
BOX = "box-thunag-sim"


class FakeShadow:
    def __init__(self) -> None:
        self.docs: list[tuple[str, str, dict]] = []
        self.fail = False

    def update_desired(self, thing, name, desired):
        if self.fail:
            raise RuntimeError("iot-data unavailable")
        self.docs.append((thing, name, json.loads(json.dumps(desired))))
        return len(self.docs)

    def cmds(self, thing=None):
        return [d["cmd"] for t, n, d in self.docs if n == "siren" and "cmd" in d and (thing is None or t == thing)]


@pytest.fixture()
def fake_shadow():
    s = FakeShadow()
    shadow.set_client(s)
    yield s
    shadow.set_client(None)


@pytest.fixture()
def told(monkeypatch):
    calls: list[dict] = []

    def fake(repo, village, text, *, title, kind, url, exclude=frozenset()):
        calls.append({"village": village.id, "text": text, "kind": kind, "exclude": set(exclude)})
        return 1

    monkeypatch.setattr(sirens, "_tell_officers", fake)
    return calls


def add_real_siren(repo, village="thunag", device=REAL, *, lora_addr=0x0103, **extra):
    d = Device(device_id=device, village_id=village, kind="siren", installed=True, simulated=False,
               lora_addr=lora_addr, created_at=clock.iso(clock.now()), **extra)
    repo.put_device(d)
    return d


def approved(repo, level="warning", trace=None, replay=False, status="approved", approved_flag=True, village="thunag"):
    a = make_alert(repo, level, replay, village)
    t = {"rules_fired": ["test"], "raw_level": level, **(trace or {})}
    return repo.update_alert(a.id, status=status, approved=approved_flag, decided_by="officer1",
                             decided_at=clock.iso(clock.now()), decision_trace=t)


def event(repo, device, etype, *, seq, cmd_id=None, meas=None, village="thunag", kind="siren", **extra):
    body = {"device_kind": kind, "village_id": village, "device_id": device, "topic_kind": "event", "v": 1,
            "seq": seq, "boot": 1, "at": clock.iso(clock.now()), "type": etype, "cmd_id": cmd_id, "meas": meas,
            "simulated": device.endswith("-sim"), **extra}
    return device_ingest.handle({k: v for k, v in body.items() if v is not None}, repo)


GOOD = {"amp_a": 3.1, "amp_a_ref": 3.3, "spl_rise_db": 24.5}


# -- the approval path ------------------------------------------------------------------------------
def test_approved_warning_commands_each_siren_once_with_a_signed_w1(repo, frozen, fake_shadow):
    add_real_siren(repo)
    a = approved(repo)
    out = steps(repo).handle({"step": "sirens", "mode": "sound", "alert_id": a.id})
    assert out["commanded"] == 2 and out["pattern"] == "W1"
    for dev in (SIM, REAL):
        (cmd,) = fake_shadow.cmds(dev)
        assert cmd["pattern"] == "W1" and cmd["level"] == "warning" and cmd["alert_id"] == a.id
        assert protocol.command_sig_ok(keys.derive(dev, 1), cmd, dev)  # signed for that device only
        assert not protocol.command_sig_ok(keys.derive(SIM if dev == REAL else REAL, 1), cmd, dev)
        assert cmd["exp"] - cmd["iat"] <= sirens.CMD_LIFETIME_S
    # Idempotent on (alert, device, round): a retried step commands nobody again.
    again = steps(repo).handle({"step": "sirens", "mode": "sound", "alert_id": a.id})
    assert again["commanded"] == 0 and len(fake_shadow.cmds()) == 2
    alert = repo.get_alert(a.id)
    assert alert.sirens_total == 2 and alert.siren_pattern == "W1"
    boxes = [d for t, n, d in fake_shadow.docs if t == BOX and "level" in d]
    assert boxes and boxes[0]["level"] == "warning"


def test_watch_never_commands_a_siren_only_the_pradhan_box(repo, frozen, fake_shadow):
    a = approved(repo, "watch")
    out = sirens.sound_for_alert(repo, a)
    assert out["commanded"] == 0 and out["reason"] == "watch_no_outdoor"
    assert fake_shadow.cmds() == []
    assert [(t, d["clip"]) for t, n, d in fake_shadow.docs] == [(BOX, "chime")]


def test_a_replay_never_commands_a_real_siren(repo, frozen, fake_shadow):
    add_real_siren(repo)
    a = approved(repo, replay=True)
    out = sirens.sound_for_alert(repo, a)
    assert out["devices"] == [SIM]  # the labelled simulator only
    assert fake_shadow.cmds(REAL) == []
    rows = {r.device_id: r for r in repo.list_siren_rows(a.id)}
    assert rows[REAL].status == "skipped" and "replay" in rows[REAL].error.lower()


def test_a_drill_plays_the_drill_pattern_only(repo, frozen, fake_shadow):
    a = approved(repo, trace={"drill": True})
    out = sirens.sound_for_alert(repo, a)
    assert out["pattern"] == "D1"
    (cmd,) = fake_shadow.cmds(SIM)
    assert cmd["action"] == "test" and cmd["pattern"] == "D1" and cmd["level"] == "drill"
    # sound_siren itself is forbidden for a drill
    assert not evaluate(SYSTEM, "sound_siren", "alert", a.id, {"level": "warning", "approved": True, "pattern": "W1",
                                                             "drill": True}).allowed


def test_critical_from_reports_only_sounds_w1_and_needs_a_second_officer(repo, frozen, fake_shadow, told):
    a = approved(repo, "critical", trace={"rules_fired": ["verified_reports:critical"], "report_level": "critical"})
    out = sirens.sound_for_alert(repo, a)
    assert out["pattern"] == "W1" and out["commanded"] == 1 and out["request_id"]
    assert repo.get_alert(a.id).siren_note == "needs_second_officer"
    assert told and told[-1]["kind"] == "siren_request" and "officer1" in told[-1]["exclude"]
    req = repo.get_siren_request(out["request_id"])
    assert req.requested_by == "officer1" and req.alert_id == a.id
    # The approver cannot be their own second officer.
    with pytest.raises(sirens.RequestError) as same:
        sirens.confirm_request(repo, req.id, Principal("officer1", "officer"))
    assert same.value.code == "same_officer"
    res = sirens.confirm_request(repo, req.id, Principal("officer2", "officer"))
    assert res.pattern == "C1" and res.commanded == 1
    assert [c["pattern"] for c in fake_shadow.cmds(SIM)] == ["W1", "C1"]


def test_an_unconfirmed_critical_keeps_w1_after_the_request_expires(repo, frozen, fake_shadow, told):
    a = approved(repo, "critical")
    out = sirens.sound_for_alert(repo, a)
    frozen["now"] = frozen["now"] + timedelta(seconds=sirens.REQUEST_SECONDS + 1)
    with pytest.raises(sirens.RequestError) as late:
        sirens.confirm_request(repo, out["request_id"], Principal("officer2", "officer"))
    assert late.value.code == "expired"
    assert [c["pattern"] for c in fake_shadow.cmds(SIM)] == ["W1"]  # never silence


def test_critical_with_a_confirmed_gauge_needs_one_approval(repo, frozen, fake_shadow):
    a = approved(repo, "critical", trace={"gauge_level": "critical", "rules_fired": ["gauge>=280cm:critical"]})
    out = sirens.sound_for_alert(repo, a)
    assert out["pattern"] == "C1" and out["request_id"] is None
    assert sirens.machine_evidence_critical({"river_level": "critical"})
    assert sirens.machine_evidence_critical({"rules_fired": ["official:cwc:critical"]})
    assert not sirens.machine_evidence_critical({"rules_fired": ["official_corroborates:cwc:critical"]})
    # observed rain alone is not enough; with a second machine source that made it Critical, it is
    assert not sirens.machine_evidence_critical({"raw_level": "critical", "rain_obs_level": "warning"})
    assert sirens.machine_evidence_critical({"raw_level": "critical", "rain_obs_level": "warning",
                                             "gauge_level": "warning", "rules_fired": ["two_sources_agree:+1"]})


def test_critical_auto_send_sounds_and_stays_flagged_unapproved(repo, frozen, fake_shadow, monkeypatch):
    from Pukaar.core.config import get_settings

    a = approved(repo, "critical", trace={"gauge_level": "critical"}, status="auto_sent_unapproved", approved_flag=False)
    monkeypatch.setenv("PUKAAR_CRITICAL_AUTO_SEND", "false")
    get_settings.cache_clear()
    try:
        off = sirens.sound_for_alert(repo, a)
        assert off["commanded"] == 0 and off["skipped"]  # Cedar: auto-send is off, nothing sounds
        monkeypatch.setenv("PUKAAR_CRITICAL_AUTO_SEND", "true")
        get_settings.cache_clear()
        a2 = approved(repo, "critical", trace={"gauge_level": "critical"}, status="auto_sent_unapproved",
                      approved_flag=False)
        on = steps(repo).handle({"step": "sirens", "alert_id": a2.id})
        assert on["commanded"] == 1 and on["pattern"] == "C1"
        assert repo.get_alert(a2.id).status == "auto_sent_unapproved"
    finally:
        monkeypatch.delenv("PUKAAR_CRITICAL_AUTO_SEND")
        get_settings.cache_clear()


def test_the_failsafe_sounds_a_critical(repo, frozen, fake_shadow):
    a = make_alert(repo, "critical")
    repo.update_alert(a.id, decision_trace={"gauge_level": "critical", "rules_fired": ["x"]})
    steps(repo).handle({"step": "failsafe", "alert_id": a.id, "error": {"Error": "Boom"}})
    assert [c["pattern"] for c in fake_shadow.cmds(SIM)] == ["C1"]
    assert fake_shadow.cmds(SIM)[0]["src"] == "failsafe"


def test_a_shadow_failure_never_fails_the_step_or_the_delivery(repo, frozen, fake_shadow):
    fake_shadow.fail = True
    a = approved(repo)
    out = steps(repo).handle({"step": "sirens", "alert_id": a.id})
    assert out["commanded"] == 0
    assert [r.status for r in repo.list_siren_rows(a.id)] == ["failed"]
    fake_shadow.fail = False
    done = steps(repo).handle({"step": "deliver", "alert_id": a.id})
    assert done["sent"] >= 1  # the people still get it


# -- what the device reports --------------------------------------------------------------------------
def test_started_and_verified_fill_the_tier_but_never_count_as_people(repo, frozen, fake_shadow):
    a = approved(repo)
    sirens.sound_for_alert(repo, a)
    (cmd,) = fake_shadow.cmds(SIM)
    assert event(repo, SIM, "cmd_received", seq=1, cmd_id=cmd["id"])["status"] == "accepted"
    event(repo, SIM, "started", seq=2, cmd_id=cmd["id"])
    out = event(repo, SIM, "verified", seq=3, cmd_id=cmd["id"], meas=GOOD)
    assert out["verified"] is True
    alert = repo.get_alert(a.id)
    assert (alert.sirens_total, alert.sirens_started, alert.sirens_verified) == (1, 1, 1)
    assert alert.siren_first_verified_at and alert.delivered_count == 0 and alert.acknowledged_count == 0
    assert all(d.channel != "siren" for d in repo.list_deliveries(a.id))  # no people row for a siren
    tier = sirens.tier(repo, alert)
    assert tier["rows"][0]["status"] == "verified" and tier["rows"][0]["meas"] == {"amp_a": 3.1, "spl_rise_db": 24.5}
    assert any(t.step == "siren_verified" and "3.1 A" in t.detail and "+24.5 dB" in t.detail
               for t in repo.list_timeline(a.id))
    assert repo.get_device(SIM).last_sound["verified"] is True
    # the same event again is a duplicate (device, boot, seq)
    assert event(repo, SIM, "verified", seq=3, cmd_id=cmd["id"], meas=GOOD)["status"] == "duplicate"


def test_verified_needs_current_and_the_microphone_or_a_known_mic_fault(repo, frozen, fake_shadow):
    a = approved(repo)
    sirens.sound_for_alert(repo, a)
    (cmd,) = fake_shadow.cmds(SIM)
    weak = event(repo, SIM, "verified", seq=1, cmd_id=cmd["id"], meas={"amp_a": 1.0, "spl_rise_db": 30})
    assert weak["verified"] is False and repo.get_alert(a.id).sirens_verified == 0
    quiet = event(repo, SIM, "verified", seq=2, cmd_id=cmd["id"], meas={"amp_a": 3.1})
    assert quiet["verified"] is False  # no microphone rise and no known microphone fault
    mic_dead = event(repo, SIM, "verified", seq=3, cmd_id=cmd["id"], meas={"amp_a": 3.1}, faults=["mic_dead"])
    assert mic_dead["verified"] is True and repo.get_alert(a.id).sirens_verified == 1


def test_an_unconfirmed_siren_after_180_s_tells_the_officer_emits_the_metric_and_offers_sms(
        repo, frozen, fake_shadow, told, capsys):
    add_real_siren(repo, sim_number="+919800000099")
    a = approved(repo)
    sirens.sound_for_alert(repo, a)
    assert sirens.check_unconfirmed(repo) == []  # not yet: 180 s
    frozen["now"] = frozen["now"] + timedelta(seconds=181)
    capsys.readouterr()
    marked = sirens.check_unconfirmed(repo)
    assert len(marked) == 2
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if '"SirenUnconfirmed"' in x]
    assert len(lines) == 1  # the real siren only; the simulator pages nobody
    assert [c["kind"] for c in told] == ["siren_unconfirmed"] and "प्रधान को फ़ोन करें" in told[0]["text"]
    rows = {r.device_id: r.status for r in repo.list_siren_rows(a.id)}
    assert rows == {SIM: "not_confirmed", REAL: "not_confirmed"}
    assert any(t.step == "siren_not_confirmed" for t in repo.list_timeline(a.id))
    cmd_id = repo.get_device(REAL).pending_cmd["cmd_id"]
    sms = sirens.sms_fallback(repo, repo.get_device(REAL), cmd_id, Principal("officer1", "officer"))
    parsed = protocol.parse_sms(sms["text"])
    assert parsed.device == REAL and protocol.sms_sig_ok(keys.derive(REAL, 1), parsed)
    assert sms["sms_uri"].startswith("sms:+919800000099?body=PKR1%20")
    # Recall re-issues to the sirens that did not verify (a new id and counter)
    sirens.recall(repo, repo.get_alert(a.id))
    again = fake_shadow.cmds(REAL)
    assert len(again) == 2 and again[1]["ctr"] > again[0]["ctr"] and again[1]["src"] == "recall"


def test_the_all_clear_sounds_a1_only_on_sirens_that_started(repo, frozen, fake_shadow):
    add_real_siren(repo)
    a = approved(repo)
    sirens.sound_for_alert(repo, a)
    cmd = fake_shadow.cmds(SIM)[0]
    event(repo, SIM, "started", seq=1, cmd_id=cmd["id"])
    stand_down(repo, [repo.get_alert(a.id)], by="system", reason="back to normal")
    assert [c["pattern"] for c in fake_shadow.cmds(SIM)] == ["W1", "A1"]
    assert [c["pattern"] for c in fake_shadow.cmds(REAL)] == ["W1"]  # never started: no all-clear tone


def test_at_most_six_sound_commands_per_village_per_hour(repo, frozen, fake_shadow):
    results = [sirens.sound_for_alert(repo, approved(repo)) for _ in range(7)]
    assert [r["commanded"] for r in results] == [1] * 6 + [0]
    assert results[-1]["reason"] == "rate_limited"
    first = repo.get_alert(results[0]["cmd_ids"] and repo.get_command(SIM, results[0]["cmd_ids"][0]).alert_id)
    rows = repo.list_siren_rows(first.id)
    assert sirens.sound_for_alert(repo, first, round_no=max(r.round for r in rows) + 1)["commanded"] == 1  # a re-issue


# -- by hand ------------------------------------------------------------------------------------------
def test_the_pradhan_box_trigger_is_audited_told_reported_capped_and_passed_on(repo, frozen, fake_shadow, told,
                                                                               workflow, monkeypatch):
    from Pukaar.workflow import client

    monkeypatch.setattr(client, "get_workflow", lambda: workflow)
    out = event(repo, BOX, "manual_trigger", seq=1, kind="box", button="key_critical")
    assert out["status"] == "accepted"
    manual = out["manual"]
    assert manual["level"] == "critical" and manual["commanded"] == 1 and manual["report_id"]
    assert [c["pattern"] for c in fake_shadow.cmds(SIM)] == ["C1"] and fake_shadow.cmds(SIM)[0]["src"] == "pradhan_box"
    assert told and told[0]["kind"] == "siren_manual" and "प्रधान ने" in told[0]["text"]
    audit = repo.list_audit(clock.iso(clock.now())[:10])
    assert any(r.action == "manual_siren" and r.actor == BOX and r.decision == "allow" for r in audit)
    report = repo.get_report(manual["report_id"])
    assert report.state == "verified_auto" and report.severity == "high" and report.parser_source == "pradhan_box"
    assessed = risk_rules.assess(None, None, [(report, clock.now())], clock.now(), soil_modifier=False,
                                 rain_intensity_on=False)
    assert assessed.report_level == "warning" and assessed.level == "warning"  # a critical key press: still Warning at most
    # A box that got a LoRa ACK from the sirens is not passed on again by the cloud.
    acked = event(repo, BOX, "manual_trigger", seq=2, kind="box", button="key_warning", lora_acked=True)
    assert acked["manual"]["commanded"] == 0


def test_box_water_rising_is_a_watch_report_and_rate_limited(repo, frozen, fake_shadow):
    out = event(repo, BOX, "report", seq=1, kind="box", button="water_rising", src="pradhan_box")
    assert out["status"] == "accepted" and out["report"]["report_id"]
    report = repo.get_report(out["report"]["report_id"])
    assert (report.report_type, report.severity, report.state, report.parser_source) == \
        ("water_rising", "medium", "verified_auto", "pradhan_box")
    assessed = risk_rules.assess(None, None, [(report, clock.now())], clock.now(), soil_modifier=False,
                                 rain_intensity_on=False)
    assert assessed.report_level == "watch"  # the pradhan's word alone: Watch
    assert all(event(repo, BOX, "report", seq=s, kind="box", button="water_rising")["report"]["report_id"]
               for s in (2, 3))
    assert event(repo, BOX, "report", seq=4, kind="box", button="water_rising")["report"]["reason"] == "rate_limited"
    # a press that comes late, from the box's buffer, is recorded but never acted on
    late = sirens.box_report(repo, repo.get_device(BOX), {"type": "report", "at": clock.iso(clock.now())}, live=False)
    assert late["report_id"] is None
    # a siren cannot send a box event
    assert "report" not in event(repo, SIM, "report", seq=5)


def test_box_mil_gaya_acknowledges_the_pradhans_own_delivery(repo, frozen, fake_shadow):
    from Pukaar.store.models import Delivery

    a = approved(repo)
    repo.put_delivery(Delivery(alert_id=a.id, recipient_id="stub-thunag-1", name="Pradhan", channel="telegram",
                               status="sent", sent_at=clock.iso(clock.now()), attempts=1))
    out = event(repo, BOX, "ack", seq=1, kind="box", button="ack", alert_id=a.id)
    assert out["status"] == "accepted" and out["ack"] == {"alert_id": a.id, "acknowledged": True}
    (row,) = repo.get_deliveries(a.id, ["stub-thunag-1"])
    assert row.acknowledged_at and row.status == "acknowledged"
    assert event(repo, BOX, "ack", seq=2, kind="box", alert_id=a.id)["ack"]["acknowledged"] is False  # once
    other = approved(repo, village="gohar")
    assert event(repo, BOX, "ack", seq=3, kind="box", alert_id=other.id)["ack"]["reason"] == "no_alert"


def test_each_siren_command_reaches_the_box_as_a_relay_cmd_it_cannot_forge(repo, frozen, fake_shadow):
    sirens.sound_for_alert(repo, approved(repo))
    (cmd,) = fake_shadow.cmds(SIM)
    entries = [d["relay_cmd"] for t, n, d in fake_shadow.docs if t == BOX and n == "siren" and "relay_cmd" in d]
    entry = entries[0][SIM]
    assert (entry["cmd_id"], entry["dst"], entry["exp"]) == (cmd["id"], repo.get_device(SIM).lora_addr, cmd["exp"])
    payload = protocol.b64url_decode(entry["payload"])
    inner = protocol.open_compact_command(keys.derive(SIM, 1), payload, SIM)
    assert inner["cmd_id48"] == protocol.cmd_id48(cmd["id"]).hex() and inner["pattern"] == "W1"
    assert inner["ctr"] == cmd["ctr"] and inner["level"] == "warning"
    assert protocol.open_compact_command(keys.derive(BOX, 1), payload, SIM) is None  # the box cannot sign one
    # the siren names a command it took over LoRa by its cmd_id48; the cloud maps it back
    started = event(repo, SIM, "started", seq=1, cmd_id=inner["cmd_id48"], via="lora")
    assert started["cmd_id"] == cmd["id"] and repo.get_command(SIM, cmd["id"]).state == "started"
    with pytest.raises(protocol.ProtocolError):
        protocol.relay_cmd(keys.derive(SIM, 1), cmd, SIM, protocol.BROADCAST)
    # never a test: the compact form has no volume, so a silent test relayed on LoRa would play aloud
    before = len(fake_shadow.docs)
    sirens.test(repo, repo.get_device(SIM), "silent", Principal("officer1", "officer"), reason="weekly")
    assert not [d for t, n, d in fake_shadow.docs[before:] if t == BOX]
    # one entry per siren survives the shadow merge (IoT Core merges nested objects; so does local mode)
    assert shadow.merge_desired({"level": "watch", "relay_cmd": {"a": {"x": 1}}}, {"relay_cmd": {"b": {"x": 2}}}) == \
        {"level": "watch", "relay_cmd": {"a": {"x": 1}, "b": {"x": 2}}}


def test_a_pradhan_cannot_trigger_another_village(repo, frozen, fake_shadow):
    pradhan = Principal("pradhan_thunag", "pradhan", ["thunag"])
    with pytest.raises(PermissionError):
        sirens.manual_sound(repo, repo.get_village("gohar"), "warning", pradhan)
    assert sirens.manual_sound(repo, repo.get_village("thunag"), "warning", pradhan).commanded == 1
    # a box registered in Thunag publishing under Gohar's topic is refused
    out = event(repo, BOX, "manual_trigger", seq=1, kind="box", button="key_warning", village="gohar")
    assert out["status"] == "rejected" and out["code"] == "wrong_device"
    # the cloud passes a box trigger on only inside the box's own village
    assert not evaluate(SYSTEM, "sound_siren", "village", "gohar",
                        {"src": "pradhan_box", "village_id": "gohar", "device_village_id": "thunag",
                         "pattern": "W1"}).allowed


def test_an_officers_critical_needs_a_distinct_second_officer(repo, frozen, fake_shadow, told):
    officer1, officer2 = Principal("officer1", "officer"), Principal("officer2", "officer")
    with pytest.raises(PermissionError):
        sirens.manual_sound(repo, repo.get_village("thunag"), "critical", officer1)
    req = sirens.request_critical(repo, repo.get_village("thunag"), officer1, "evacuation")
    with pytest.raises(sirens.RequestError):
        sirens.confirm_request(repo, req.id, officer1)
    res = sirens.confirm_request(repo, req.id, officer2)
    assert res.pattern == "C1" and res.commanded == 1
    assert fake_shadow.cmds(SIM)[0]["src"] == "officer_manual"
    with pytest.raises(sirens.RequestError):  # used once
        sirens.confirm_request(repo, req.id, Principal("officer3", "officer"))


def test_agents_and_judges_can_never_sound_stop_or_test(repo):
    agent = Principal("drafting-agent", "agent")
    judge, judge_p = Principal("judge", "officer"), Principal("judge_pradhan", "pradhan", ["thunag"])
    for who in (agent, judge, judge_p):
        for action, rtype, ctx in (("sound_siren", "village", {"level": "warning", "village_id": "thunag"}),
                                   ("stop_siren", "village", {"village_id": "thunag", "started_by_self": True}),
                                   ("test_siren", "device", {"kind": "silent"}),
                                   ("manage_device", "device", {"change": "settings"})):
            assert not evaluate(who, action, rtype, "x", {**ctx, "replay": True}).allowed, (who.username, action)
            assert not evaluate(who, action, rtype, "x", ctx).allowed, (who.username, action)
    assert evaluate(judge, "view_devices", "app", "pukaar", {}).allowed  # they can see


def test_an_audible_test_is_refused_at_night_and_one_test_per_ten_minutes(repo, frozen, fake_shadow):
    officer = Principal("officer1", "officer")
    d = repo.get_device(SIM)
    assert sirens.hour_ist(frozen["now"]) < 9  # 07:30 IST
    with pytest.raises(PermissionError):
        sirens.test(repo, d, "audible", officer)
    cmd = sirens.test(repo, d, "silent", officer)
    assert cmd.pattern == "T1" and cmd.volume == 0
    with pytest.raises(sirens.RequestError) as soon:
        sirens.test(repo, d, "silent", officer)
    assert soon.value.status == 429
    frozen["now"] = frozen["now"] + timedelta(hours=3)  # 10:30 IST
    assert sirens.test(repo, d, "audible", officer).volume == 50


def test_a_failed_test_marks_the_siren_fault(repo, frozen, fake_shadow, capsys):
    cmd = sirens.test(repo, repo.get_device(SIM), "silent", Principal("officer1", "officer"))
    capsys.readouterr()
    event(repo, SIM, "test_result", seq=1, cmd_id=cmd.id, ok=False, detail="amplifier open", meas={"amp_a": 0.1})
    assert '"SirenTestFailed"' in capsys.readouterr().out
    d = repo.get_device(SIM)
    assert d.last_test_silent["ok"] is False and registry.health(d)[0] == "fault"


def test_an_autonomous_siren_opens_an_alert_for_confirmation_and_no_cap(repo, frozen, fake_shadow, workflow, monkeypatch):
    from Pukaar.workflow import client

    monkeypatch.setattr(client, "get_workflow", lambda: workflow)
    out = event(repo, SIM, "autonomous_trigger", seq=1, frame_src="gauge-janjehli-01")
    alert = repo.get_alert(out["autonomous"]["alert_id"])
    assert alert.level == "critical" and alert.status == "drafting" and alert.decision_trace["edge_autonomous"]
    assert workflow.started == [alert.id] and not cap.is_published(alert)


# -- health, presence, LoRa -----------------------------------------------------------------------
def test_events_are_idempotent_across_live_and_backfill(repo, frozen, fake_shadow):
    a = approved(repo)
    sirens.sound_for_alert(repo, a)
    cmd = fake_shadow.cmds(SIM)[0]
    at = clock.iso(clock.now())
    items = [{"v": 1, "seq": s, "boot": 1, "at": at, "type": t, "cmd_id": cmd["id"], "simulated": True}
             for s, t in ((1, "cmd_received"), (2, "started"))]
    body = {"device_kind": "siren", "village_id": "thunag", "device_id": SIM, "topic_kind": "backfill", "events": items}
    first = device_ingest.handle(body, repo)
    second = device_ingest.handle(body, repo)
    assert (first["stored"], second["stored"], second["duplicate"]) == (2, 0, 2)
    assert repo.get_alert(a.id).sirens_started == 1


def test_one_old_event_on_the_live_topic_is_kept_as_backfill_not_rejected(repo, frozen, fake_shadow):
    """A node back online drains a single queued record to /event: history, stored, and still deduped."""
    from datetime import timedelta

    a = approved(repo)
    sirens.sound_for_alert(repo, a)
    cmd = fake_shadow.cmds(SIM)[0]
    hour_ago = clock.iso(clock.now() - timedelta(hours=1))
    out = event(repo, SIM, "cmd_received", seq=1, cmd_id=cmd["id"], at=hour_ago)
    assert out["status"] == "accepted"
    rows = repo.list_device_events(SIM)
    assert len(rows) == 1 and rows[0]["live"] is False
    assert event(repo, SIM, "cmd_received", seq=1, cmd_id=cmd["id"], at=hour_ago)["status"] == "duplicate"
    too_old = clock.iso(clock.now() - timedelta(days=30))
    assert event(repo, SIM, "started", seq=2, cmd_id=cmd["id"], at=too_old)["code"] == "stale"
    future = clock.iso(clock.now() + timedelta(hours=1))
    assert event(repo, SIM, "started", seq=3, cmd_id=cmd["id"], at=future)["code"] == "stale"


def test_a_lora_heartbeat_is_checked_with_the_origins_key_and_a_forwarder_cannot_forge(repo, frozen):
    box = repo.get_device(BOX)
    siren = repo.get_device(SIM)
    now = int(clock.now().timestamp())
    hb = protocol.pack_payload(protocol.FrameType.HEARTBEAT, {"state": 0, "soc": 71, "batt_dv": 131, "faults": 0,
                                                               "outbox": 0})
    genuine = protocol.encode_frame(keys.derive(SIM), ftype=protocol.FrameType.HEARTBEAT, src=siren.lora_addr,
                                    dst=0xFFFF, ctr=5, ts=now, payload=hb)
    forged = protocol.encode_frame(keys.derive(BOX), ftype=protocol.FrameType.HEARTBEAT, src=siren.lora_addr,
                                   dst=0xFFFF, ctr=6, ts=now, payload=hb)
    import base64

    body = {"device_kind": "mesh", "village_id": "thunag", "device_id": box.device_id, "topic_kind": "relay",
            "frames": [base64.b64encode(genuine).decode(), base64.b64encode(forged).decode(),
                       base64.b64encode(genuine).decode()]}
    out = device_ingest.handle(body, repo)
    assert out["accepted"] == 1 and out["rejected"] == ["bad_mac", "replayed"]
    d = repo.get_device(SIM)
    assert d.last_seen_path == "lora" and d.soc == 71
    assert "lora_only" in registry.health(d)[1]


def test_a_disconnect_alone_is_not_offline_until_20_minutes_of_silence(repo, frozen):
    d = add_real_siren(repo)
    ts = int(clock.now().timestamp() * 1000)
    device_ingest.handle({"clientId": REAL, "eventType": "connected", "timestamp": ts, "versionNumber": 1}, repo)
    device_ingest.handle({"clientId": REAL, "eventType": "disconnected", "timestamp": ts + 1000,
                          "versionNumber": 1}, repo)
    d = repo.get_device(REAL)
    assert d.connected is False and registry.health(d)[0] != "offline"
    assert registry.health(d, clock.now() + timedelta(minutes=21))[0] == "offline"
    # an older presence event never overwrites a newer one
    device_ingest.handle({"clientId": REAL, "eventType": "connected", "timestamp": ts - 5000, "versionNumber": 1}, repo)
    assert repo.get_device(REAL).connected is False


def test_the_offline_metric_counts_installed_sirens_only_and_during_an_alert(repo, frozen, capsys):
    add_real_siren(repo, last_seen=clock.iso(clock.now() - timedelta(hours=1)))
    sim = repo.get_device(SIM)
    repo.update_device("thunag", SIM, last_seen=clock.iso(clock.now() - timedelta(hours=1)))
    assert registry.health(repo.get_device(SIM))[0] == "offline" and sim.simulated
    out = sirens.health_scan(repo)
    assert out["offline"] == [REAL] and out["offline_during_alert"] == []
    a = make_alert(repo, "warning")
    repo.update_alert(a.id, status="delivering")
    assert sirens.health_scan(repo)["offline_during_alert"] == [REAL]
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if '"SirenOffline"' in x]
    assert lines and lines[-1]["SirenOffline"] == 1


def test_a_silent_test_overdue_after_eight_days(repo, frozen):
    d = add_real_siren(repo, last_seen=clock.iso(clock.now()), soc=90,
                       last_test_silent={"at": clock.iso(clock.now() - timedelta(days=7)), "ok": True})
    assert registry.health(d)[0] == "ok"
    later = clock.now() + timedelta(days=1, minutes=1)
    assert registry.test_overdue(d, later)
    assert "test_overdue" in registry.health(d.model_copy(update={"last_seen": clock.iso(later)}), later)[1]
    assert registry.health(Device(device_id="siren-x-01", village_id="thunag", kind="siren"))[0] == "unknown"


def test_a_simulated_payload_from_real_hardware_is_refused(repo, frozen):
    add_real_siren(repo)
    out = event(repo, REAL, "started", seq=1, cmd_id="cmd_x", simulated=True)
    assert out["status"] == "rejected" and out["code"] == "simulated"
