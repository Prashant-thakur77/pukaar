"""The duty officer (services/duty.py): the 08:00 IST digest, the shift handover note, and paging beyond e-mail
(handlers/pager.py via the worker's SNS subscription)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from Pukaar.core import clock
from Pukaar.services import duty, roster
from Pukaar.store.models import Alert, RosterShift

AT_0801_IST = datetime(2026, 7, 1, 2, 31, tzinfo=timezone.utc)


@pytest.fixture()
def sent(monkeypatch):
    out: list[tuple[str, str]] = []
    from Pukaar.delivery import telegram

    monkeypatch.setattr(telegram, "configured", lambda: True)
    monkeypatch.setattr(telegram, "send_text", lambda chat, text: out.append((chat, text)))
    return out


def _audit(repo, action):
    return [r for r in repo.list_audit(clock.iso(clock.now())[:10]) if r.action == action]


def test_the_digest_names_health_open_alerts_and_gaps(repo, frozen):
    frozen["now"] = AT_0801_IST
    repo.update_village("gohar", data_status="stale", data_note="forecast missing")
    now = clock.iso(clock.now())
    repo.put_alert(Alert(id="alr_open", village_id="thunag", village_name="Thunag", village_name_hi="थुनाग",
                         level="warning", status="pending", created_at=now, updated_at=now))
    d = duty.digest(repo, "Mandi")
    assert d["sweep"]["villages"] == 4 and [s["village_id"] for s in d["sweep"]["stale"]] == ["gohar"]
    assert [a["alert_id"] for a in d["open_alerts"]] == ["alr_open"]
    kinds = {g["kind"] for g in d["gaps"]}
    assert "roster" in kinds  # nobody rostered: the seed has no roster rows
    assert d["duty"]["source"] == "fallback" and d["duty"]["chain"] == ["officer1", "officer2"]
    text = duty.text(d)
    assert "Mandi" in text and "Gohar" in text and "Thunag warning" in text and "सुबह" in text
    assert len(text) <= duty.TELEGRAM_LIMIT


def test_the_digest_goes_once_per_district_per_day_from_0800_ist(repo, frozen, sent):
    repo.put_officer_chat("officer1", "111")
    frozen["now"] = AT_0801_IST - timedelta(minutes=2)  # 07:59 IST
    assert duty.maybe_send_digests(repo) == []
    frozen["now"] = AT_0801_IST
    assert sorted(duty.maybe_send_digests(repo)) == ["Hamirpur", "Mandi"]
    assert duty.maybe_send_digests(repo) == []  # the next sweep: already sent today
    assert len([c for c, _ in sent if c == "111"]) == 2 and "Pukaar morning check" in sent[0][1]
    assert len(_audit(repo, "duty_digest_sent")) == 2
    frozen["now"] = AT_0801_IST + timedelta(days=1)
    assert len(duty.maybe_send_digests(repo)) == 2


def test_the_rostered_shift_gets_the_digest(repo, frozen, sent):
    frozen["now"] = AT_0801_IST
    day = roster.today_ist(AT_0801_IST).isoformat()
    repo.put_roster_shift(RosterShift(district="Mandi", date=day, shift="day", primary="asha", backup="ravi",
                                      updated_by="officer1", updated_at=clock.iso(AT_0801_IST)))
    repo.put_officer_chat("asha", "222")
    out = duty.send_digest(repo, "Mandi")
    assert out["digest"]["duty"]["chain"] == ["asha", "ravi"] and [c for c, _ in sent] == ["222"]


def test_handover_written_by_the_outgoing_and_acknowledged_by_the_incoming(repo, frozen):
    frozen["now"] = AT_0801_IST - timedelta(hours=1)  # 07:01 IST: the night shift of 30 June
    note = duty.write_handover(repo, "officer1", "officer", "Mandi", "Gohar gauge silent since 03:00; check at 09:00.")
    assert (note.date, note.shift, note.for_shift) == ("2026-06-30", "night", "day")
    duty.write_handover(repo, "officer1", "officer", "Mandi", "Gohar gauge silent since 03:00. Pandoh road blocked.")
    frozen["now"] = AT_0801_IST  # the day shift
    view = duty.handover_view(repo, "Mandi")
    assert view["incoming"]["text"].endswith("Pandoh road blocked.") and view["outgoing"] is None
    with pytest.raises(duty.DutyError, match="incoming officer"):
        duty.acknowledge_handover(repo, "officer1", "officer", "Mandi", "2026-06-30", "night")
    acked = duty.acknowledge_handover(repo, "officer2", "officer", "Mandi", "2026-06-30", "night")
    assert acked.acknowledged_by == "officer2"
    with pytest.raises(duty.DutyError, match="already"):
        duty.acknowledge_handover(repo, "officer2", "officer", "Mandi", "2026-06-30", "night")
    assert sorted(r.reason.split(" for")[0] for r in _audit(repo, "handover_written")) == ["edited", "written"]
    assert _audit(repo, "handover_acknowledged")[0].actor == "officer2"
    # An acknowledged note is closed.
    frozen["now"] = AT_0801_IST - timedelta(hours=1)
    with pytest.raises(duty.DutyError, match="acknowledged"):
        duty.write_handover(repo, "officer1", "officer", "Mandi", "late addition")
    with pytest.raises(duty.DutyError):
        duty.write_handover(repo, "officer1", "officer", "Mandi", "   ")


def test_an_unacknowledged_handover_is_a_readiness_gap(repo, frozen):
    frozen["now"] = AT_0801_IST - timedelta(hours=1)
    duty.write_handover(repo, "officer1", "officer", "Mandi", "Check the Thunag siren.")
    frozen["now"] = AT_0801_IST
    assert "handover" in {g["kind"] for g in duty.digest(repo, "Mandi")["gaps"]}


ALARM = {"AlarmName": "pukaar-dev-nobody-on-duty", "AlarmDescription": "No officer is rostered for the shift.",
         "NewStateValue": "ALARM", "NewStateReason": "Threshold crossed",
         "Trigger": {"Dimensions": [{"name": "District", "value": "Hamirpur"}]}}


def test_an_alarm_pages_the_primary_and_backup_on_duty_not_the_escalation(repo, frozen, sent):
    frozen["now"] = AT_0801_IST
    day = roster.today_ist(AT_0801_IST).isoformat()
    repo.put_roster_shift(RosterShift(district="Hamirpur", date=day, shift="day", primary="asha", backup="ravi",
                                      escalation="adm_hamirpur", updated_by="officer1", updated_at=clock.iso(AT_0801_IST)))
    for who, chat in (("asha", "1"), ("ravi", "2"), ("adm_hamirpur", "3"), ("officer1", "4")):
        repo.put_officer_chat(who, chat)
    out = duty.page_alarm(repo, json.dumps(ALARM))
    assert out["paged"] == ["asha", "ravi"] and sorted(c for c, _ in sent) == ["1", "2"]
    assert "nobody-on-duty" in sent[0][1] and "ALARM" in sent[0][1]
    assert "asha" in _audit(repo, "alarm_paged")[0].reason


def test_an_alarm_without_a_district_pages_every_district_once_each_and_insufficient_data_is_skipped(repo, frozen, sent):
    frozen["now"] = AT_0801_IST
    repo.put_officer_chat("officer1", "4")
    out = duty.page_alarm(repo, {**ALARM, "Trigger": {}, "NewStateValue": "OK"})
    assert out["paged"] == ["officer1", "officer2"] and [c for c, _ in sent] == ["4"]
    assert "back to OK" in sent[0][1]
    assert duty.page_alarm(repo, {**ALARM, "NewStateValue": "INSUFFICIENT_DATA"})["paged"] == []


def test_the_worker_hands_alarm_topic_events_to_the_pager(repo, frozen, monkeypatch):
    from Pukaar.handlers import pager, worker

    monkeypatch.setattr(pager, "get_repo", lambda: repo)
    seen = []
    monkeypatch.setattr(duty, "page_alarm", lambda r, message: seen.append(json.loads(message)) or {"ok": 1})
    out = worker.handler({"Records": [{"EventSource": "aws:sns", "Sns": {"Message": json.dumps(ALARM)}}]})
    assert out == {"pages": [{"ok": 1}]} and seen[0]["AlarmName"] == ALARM["AlarmName"]


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


def test_routes_and_cedar(client, repo, frozen):
    frozen["now"] = AT_0801_IST
    officer, pradhan, judge = (_token(client, u) for u in ("officer1", "pradhan_thunag", "judge"))
    d = client.get("/duty/digest", params={"district": "Mandi"}, headers=officer).json()
    assert d["district"] == "Mandi" and "Pukaar morning check" in d["text"]
    assert client.get("/duty/digest", params={"district": "Mandi"}, headers=pradhan).status_code == 403
    r = client.post("/duty/handover/Mandi", json={"text": "All quiet."}, headers=officer)
    assert r.status_code == 200 and r.json()["outgoing"]["text"] == "All quiet."
    assert client.post("/duty/handover/Mandi", json={"text": "x"}, headers=judge).status_code == 403
    assert client.post("/duty/handover/Mandi", json={"text": "x"}, headers=pradhan).status_code == 403
    nxt = r.json()["shift"]
    assert client.post(f"/duty/handover/Mandi/{nxt['date']}/{nxt['shift']}/ack", headers=officer).status_code == 400
    ok = client.post(f"/duty/handover/Mandi/{nxt['date']}/{nxt['shift']}/ack", headers=_token(client, "officer2"))
    assert ok.status_code == 200 and ok.json()["outgoing"]["acknowledged_by"] == "officer2"
