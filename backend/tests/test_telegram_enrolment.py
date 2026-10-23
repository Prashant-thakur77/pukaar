"""Telegram enrolment under the DPDP Act (api/routers/telegram.py, services/privacy.py): a notice and an
explicit consent button before anything is stored; /stop and "बंद करें" remove the person at once; what is
left of them (delivery rows, roll-call rows, their number in reports) is erased N days later, except the
minimal record. And /start with an unknown code answers in one short message at any number of villages."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from Pukaar.core import clock
from Pukaar.delivery import dispatch
from Pukaar.services import privacy
from Pukaar.store.models import Alert, Delivery, Recipient, Report, Village
from Pukaar.templates import hi

from test_rollcall import SECRET, FakeTelegram

CHAT = "5551234"


@pytest.fixture()
def tg(monkeypatch):
    from Pukaar.delivery import telegram

    fake = FakeTelegram()
    monkeypatch.setattr(telegram, "configured", lambda: True)
    monkeypatch.setattr(telegram, "_call", fake)
    return fake


@pytest.fixture()
def client(repo, monkeypatch):
    from Pukaar.api.routers import telegram
    from Pukaar.main import app

    monkeypatch.setattr(telegram, "get_repo", lambda: repo)
    monkeypatch.setenv("PUKAAR_TELEGRAM_WEBHOOK_SECRET", SECRET)
    return TestClient(app)


def say(client, text, chat=CHAT, first="Asha"):
    r = client.post("/telegram/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
                    json={"message": {"text": text, "chat": {"id": int(chat), "first_name": first}}})
    assert r.status_code == 200, r.text


def press(client, data, chat=CHAT, n=1):
    r = client.post("/telegram/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
                    json={"callback_query": {"id": f"cb{n}", "data": data, "from": {"first_name": "Asha", "last_name": "Devi"},
                                             "message": {"chat": {"id": int(chat)}}}})
    assert r.status_code == 200, r.text


def test_start_shows_the_notice_and_stores_nothing_until_the_button(client, repo, frozen, tg):
    say(client, "/start gohar")
    assert repo.get_recipient("gohar", CHAT) is None
    notice = tg.sent()[-1]
    for words in ("What we keep", "Why", "How long", "/stop", "हम क्या रखेंगे", "बंद करें"):
        assert words in notice["text"], words
    buttons = notice["reply_markup"]["inline_keyboard"][0]
    assert [b["callback_data"] for b in buttons] == ["consent:gohar", "noconsent"]
    press(client, "consent:gohar")
    r = repo.get_recipient("gohar", CHAT)
    assert r is not None and r.name == "Asha Devi" and r.consent.startswith(f"telegram button, {hi.NOTICE_VERSION}")
    press(client, "consent:gohar", n=2)  # a double tap: still one registration
    assert len([x for x in repo.list_recipients("gohar") if x.id == CHAT]) == 1


def test_declining_or_a_stale_button_stores_nothing(client, repo, frozen, tg):
    say(client, "/start gohar")
    press(client, "noconsent")
    assert repo.get_recipient("gohar", CHAT) is None
    press(client, "consent:gohar", n=2)  # the wait was dropped: expired
    assert repo.get_recipient("gohar", CHAT) is None
    press(client, "consent:thunag", n=3)  # a button for a village the notice was never shown for
    assert repo.get_recipient("thunag", CHAT) is None


@pytest.mark.parametrize("word", ["/stop", "बंद करें"])
def test_stop_removes_the_person_from_every_village_at_once(client, repo, frozen, tg, word):
    for v in ("gohar", "thunag"):
        say(client, f"/start {v}")
        press(client, f"consent:{v}")
    say(client, word)
    assert repo.get_recipient("gohar", CHAT) is None and repo.get_recipient("thunag", CHAT) is None
    assert repo.chat_villages(CHAT) == []
    assert "/start" in tg.sent()[-1]["text"]
    due = repo.list_erasures()
    assert len(due) == 1 and set(due[0]["villages"]) == {"gohar", "thunag"}
    say(client, "/stop")
    assert "not registered" in tg.sent()[-1]["text"]


def test_erasure_after_n_days_keeps_only_the_minimal_record(repo, frozen):
    now = frozen["now"]
    repo.put_recipient(Recipient(id=CHAT, village_id="gohar", name="Asha Devi", channel="telegram",
                                 consent=privacy.consent_record(now)))
    a = Alert(id="alr_er", village_id="gohar", village_name="Gohar", village_name_hi="गोहर", level="warning",
              status="delivered", approved=True, created_at=clock.iso(now), updated_at=clock.iso(now))
    repo.put_alert(a)
    repo.put_delivery(Delivery(alert_id=a.id, recipient_id=CHAT, name="Asha Devi", channel="telegram", status="sent",
                               sent_at=clock.iso(now), attempts=1))
    dispatch.count_reached(repo, a.id, CHAT, "telegram")
    dispatch.acknowledge(repo, a.id, CHAT)
    repo.put_report(Report(id="rep_er", village_id="gohar", created_at=clock.iso(now), track_code="PKER01",
                           text=f"pani badh raha hai, call me {CHAT} or 9812345678"))
    repo.put_recipient(Recipient(id="v_er", village_id="gohar", name="Ram", channel="voice", phone="+919812345678",
                                 consent="verbal"))

    privacy.stop(repo, CHAT, now)
    privacy.remove_recipient(repo, "gohar", "v_er", "test", now)
    assert privacy.run_due(repo, now + timedelta(days=29))["erased"] == 0  # not yet due (30 days)
    out = privacy.run_due(repo, now + timedelta(days=31))
    assert out["erased"] == 2 and repo.list_erasures() == []

    rows = repo.list_deliveries(a.id)
    assert len(rows) == 1 and rows[0].erased and rows[0].recipient_id.startswith("erased_")
    assert rows[0].name == "(erased)" and rows[0].status == "acknowledged" and rows[0].sent_at
    assert CHAT not in str(repo.t.scan()["Items"])  # no chat id left anywhere but the audit (none there either)
    got = repo.get_alert(a.id)
    assert (got.delivered_count, got.acknowledged_count) == (1, 1)  # counts unchanged
    assert dispatch.repair_counts(repo, a.id, emit=False).acknowledged_count == 1
    text = repo.get_report("rep_er").text
    assert CHAT not in text and "9812345678" not in text and "[removed]" in text
    audit = [r for r in repo.list_audit(clock.iso(now + timedelta(days=31))[:10]) if r.action == "erase_personal_data"]
    assert len(audit) == 2 and all(CHAT not in r.resource + r.reason for r in audit)


def test_joining_again_cancels_the_erasure(client, repo, frozen, tg):
    say(client, "/start gohar")
    press(client, "consent:gohar")
    say(client, "/stop")
    assert len(repo.list_erasures()) == 1
    say(client, "/start gohar")
    press(client, "consent:gohar", n=2)
    assert repo.list_erasures() == []


def test_unknown_code_is_one_short_answer_at_1000_villages(client, repo, frozen, tg):
    for i in range(1000):
        repo.put_village(Village(id=f"gaon{i:04d}", name=f"Gaon {i:04d}", name_hi=f"गाँव {i}",
                                 district=f"District{i % 12:02d}", lat=31.0, lon=77.0))
    say(client, "/start nowhere-at-all")
    text = tg.sent()[-1]["text"]
    assert len(text) <= hi.TELEGRAM_MAX_CHARS and "gaon0001" not in text
    assert "Mandi" in text and "/live" in text  # the districts and where to find the code
    say(client, "/start District03")  # a district's name: that district's codes, still one message
    text = tg.sent()[-1]["text"]
    assert len(text) <= hi.TELEGRAM_MAX_CHARS and "/start gaon0003" in text and "gaon0004" not in text
    say(client, "/start gaon")  # the first letters of 1,000 villages: cut to fit, says how to narrow it
    text = tg.sent()[-1]["text"]
    assert len(text) <= hi.TELEGRAM_MAX_CHARS and "more" in text
    say(client, "/start")
    assert len(tg.sent()[-1]["text"]) <= hi.TELEGRAM_MAX_CHARS


def test_a_failed_reply_never_fails_the_webhook(client, repo, frozen, monkeypatch):
    from Pukaar.delivery import telegram

    def boom(*a, **k):
        raise telegram.TelegramError("down")

    monkeypatch.setattr(telegram, "_call", boom)
    monkeypatch.setattr(telegram, "configured", lambda: True)
    say(client, "/start nowhere")
    say(client, "/start gohar")
    say(client, "/stop")
