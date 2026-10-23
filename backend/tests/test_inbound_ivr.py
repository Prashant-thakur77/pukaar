"""Inbound calls (delivery/inbound.py, api/routers/voice.py): IVR self-enrolment, "report what you see" and the
missed-call callback, on the local fakes. Plivo's requests carry a real X-Plivo-Signature-V3 made with the test
token; nothing here reaches a network. With voice off every inbound route refuses."""

from __future__ import annotations

from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from Pukaar.core import clock
from Pukaar.delivery import inbound, plivo
from Pukaar.store.models import Recipient

KEY = "test-voice-webhook-key-0123456789"
PLIVO_ENV = {"PUKAAR_PLIVO_AUTH_ID": "MAPLIVO", "PUKAAR_PLIVO_AUTH_TOKEN": "plivo-secret",
             "PUKAAR_PLIVO_CALLER_ID": "+918035000000"}
CALLER = "919812345678"
PHONE = "+919812345678"


def _voice(monkeypatch, provider: str, **env: str) -> None:
    from Pukaar.core.config import get_settings

    monkeypatch.setenv("PUKAAR_VOICE_PROVIDER", provider)
    monkeypatch.setenv("PUKAAR_API_URL", "https://api.example.test")
    monkeypatch.setenv("PUKAAR_VOICE_WEBHOOK_KEY", KEY)
    for k, v in {**PLIVO_ENV, **env}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


@pytest.fixture()
def api(repo, monkeypatch):
    from Pukaar.api.routers import voice as router
    from Pukaar.core.config import get_settings
    from Pukaar.main import app

    monkeypatch.setattr(router, "get_repo", lambda: repo)
    monkeypatch.setattr(inbound, "_fetch_recording", lambda url: (b"ID3-fake-mp3", "audio/mpeg"))
    yield TestClient(app)
    get_settings.cache_clear()


def _plivo(api, params: dict, step: str = "", path: str = "/voice/plivo/inbound"):
    query = {"k": KEY, **({"step": step} if step else {})}
    url = f"http://testserver{path}?{urlencode(query)}"
    nonce = "n-1"
    sig = plivo.signature("plivo-secret", "POST", url, params, nonce)
    return api.post(url, data=params, headers={"X-Plivo-Signature-V3": sig, "X-Plivo-Signature-V3-Nonce": nonce})


def _call(api, call_id: str, *digits: str, frm: str = CALLER):
    base = {"CallUUID": call_id, "From": frm, "To": "918035000000", "Direction": "inbound"}
    out = [_plivo(api, base)]
    for d in digits:
        out.append(_plivo(api, {**base, "Digits": d}))
    return out


def test_voice_off_refuses_every_inbound_route(api, monkeypatch):
    _voice(monkeypatch, "off")
    assert _plivo(api, {"CallUUID": "c0", "From": CALLER}).status_code == 403
    r = api.get("/voice/exotel/inbound/prompt", params={"k": KEY, "CallSid": "c0", "CallFrom": "09812345678"})
    assert r.status_code == 403


def test_a_wrong_signature_or_key_is_refused(api, monkeypatch):
    _voice(monkeypatch, "plivo")
    r = api.post(f"/voice/plivo/inbound?k={KEY}", data={"CallUUID": "c1", "From": CALLER},
                 headers={"X-Plivo-Signature-V3": "bad", "X-Plivo-Signature-V3-Nonce": "n"})
    assert r.status_code == 403
    assert api.get("/voice/exotel/inbound/prompt", params={"k": "wrong", "CallSid": "c1"}).status_code == 403


def test_self_enrolment_by_keypad_stores_nothing_before_agreeing(api, repo, monkeypatch, frozen):
    _voice(monkeypatch, "plivo")
    menu, notice = _call(api, "call-1", "1")
    assert menu.status_code == 200 and "<GetDigits" in menu.text and "एक दबाएँ" in menu.text
    assert "सूचना" in notice.text and "नौ दबाएँ" in notice.text
    assert not [r for r in repo.list_recipients("thunag") if r.phone == PHONE]  # nothing before "1"
    code = _plivo(api, {"CallUUID": "call-1", "From": CALLER, "Digits": "1"})
    assert 'finishOnKey="#"' in code.text
    confirm = _plivo(api, {"CallUUID": "call-1", "From": CALLER, "Digits": "1001#"})
    assert "थुनाग" in confirm.text
    done = _plivo(api, {"CallUUID": "call-1", "From": CALLER, "Digits": "1"})
    assert "<Hangup/>" in done.text and "जुड़ गए" in done.text
    person = next(r for r in repo.list_recipients("thunag") if r.phone == PHONE)
    assert person.channel == "voice" and person.enrolled_via == "ivr" and person.enrolled_by == "self"
    assert inbound.NOTICE_VERSION in person.consent and PHONE not in person.consent
    assert repo.get_inbound("call-1") is None  # the session (and the number in it) is gone
    rows = [r for r in repo.list_audit(clock.iso(clock.now())[:10]) if r.action == "household_enrolled"]
    assert rows and PHONE not in rows[0].reason
    # Calling again: already enrolled, nothing doubled.
    again = _call(api, "call-2", "1", "1", "1001", "1")[-1]
    assert "पहले से जुड़ा" in again.text
    assert len([r for r in repo.list_recipients("thunag") if r.phone == PHONE]) == 1


def test_declining_the_notice_or_an_unknown_code_stores_nothing(api, repo, monkeypatch, frozen):
    _voice(monkeypatch, "plivo")
    assert "कुछ नहीं रखा" in _call(api, "call-3", "1", "2")[-1].text
    replies = _call(api, "call-4", "1", "1", "999", "998")
    assert "कोड नहीं मिला" in replies[-1].text and "<Hangup/>" in replies[-1].text
    assert not [r for r in repo.list_recipients("thunag") if r.phone == PHONE]


def test_leaving_by_pressing_nine(api, repo, monkeypatch, frozen):
    _voice(monkeypatch, "plivo")
    repo.put_recipient(Recipient(id="v_asha", village_id="thunag", name="Asha", channel="voice", phone=PHONE, consent="t"))
    last = _call(api, "call-5", "9", "1001", "1")[-1]
    assert "हटा दिया" in last.text and repo.get_recipient("thunag", "v_asha") is None


def _relay(repo, role="gauge_reader"):
    repo.put_recipient(Recipient(id="v_reader", village_id="thunag", name="Gopal", channel="voice", phone=PHONE,
                                 consent="t", role=role))


def test_a_gauge_readers_report_is_auto_verified_and_evaluated_at_once(api, repo, monkeypatch, frozen):
    _voice(monkeypatch, "plivo")
    _relay(repo)
    seen = []
    monkeypatch.setattr("Pukaar.services.decision_engine.recompute_village",
                        lambda repo, village, **kw: seen.append(village.id))
    replies = _call(api, "call-6", "2", "1001")
    assert "<Record" in replies[-1].text and 'maxLength="20"' in replies[-1].text
    thanks = _plivo(api, {"CallUUID": "call-6", "From": CALLER, "RecordUrl": "https://media.plivo.test/r.mp3"},
                    step="recorded")
    assert "धन्यवाद" in thanks.text
    r = repo.list_reports("thunag")[0]
    assert r.report_type == "water_rising" and r.severity == "high" and r.state == "verified_auto"
    assert "caller_role:gauge_reader" in r.flags and "caller_id_matched" in r.flags and r.audio_key
    assert r.verified_by == "auto:ivr-relay:gauge_reader" and seen == ["thunag"]


def test_an_unknown_callers_report_waits_for_an_officer(api, repo, monkeypatch, frozen):
    _voice(monkeypatch, "plivo")
    _call(api, "call-7", "3", "1001")
    # Hung up during the recording: the report is still made.
    _plivo(api, {"CallUUID": "call-7", "From": CALLER, "CallStatus": "completed"}, path="/voice/plivo/inbound-hangup")
    r = repo.list_reports("thunag")[0]
    assert r.report_type == "road_cut" and r.state == "unverified"
    assert "caller_unknown" in r.flags and "no_recording" in r.flags


def test_the_exotel_flow_walks_the_same_menu(api, repo, monkeypatch, frozen):
    _voice(monkeypatch, "exotel", PUKAAR_EXOTEL_SID="s", PUKAAR_EXOTEL_TOKEN="t", PUKAAR_EXOTEL_CALLER_ID="0804",
           PUKAAR_EXOTEL_APP_ID="1")
    q = {"k": KEY, "CallSid": "exo-1", "CallFrom": "09812345678"}

    def get(part, **extra):
        return api.get(f"/voice/exotel/inbound/{part}", params={**q, **extra}, follow_redirects=False)

    menu = get("prompt").json()
    assert menu["max_input_digits"] == 1 and "एक दबाएँ" in menu["gather_prompt"]["text"]
    assert get("key", digits='"1"').status_code == 302  # back to the Gather: the notice
    assert "सूचना" in get("prompt").json()["gather_prompt"]["text"]
    assert get("key", digits='"1"').status_code == 302
    assert get("prompt").json()["finish_on_key"] == "#"
    assert get("key", digits='"1001"').status_code == 302
    assert get("key", digits='"1"').status_code == 200  # onwards: the end
    assert get("next").status_code == 302  # not a recording: the closing Greeting
    assert "जुड़ गए" in get("closing").text
    assert any(r.phone == PHONE and r.enrolled_via == "ivr" for r in repo.list_recipients("thunag"))


def test_a_missed_call_is_called_back_once_a_day_when_switched_on(api, repo, monkeypatch, frozen):
    placed = []
    monkeypatch.setattr(inbound, "place_callback", lambda phone, provider: placed.append((phone, provider)) or "cb-1")
    _voice(monkeypatch, "plivo")
    assert "<GetDigits" in _plivo(api, {"CallUUID": "m-0", "From": CALLER}).text  # off: answered normally
    _voice(monkeypatch, "plivo", PUKAAR_IVR_MISSED_CALL_CALLBACK="true")
    r = _plivo(api, {"CallUUID": "m-1", "From": CALLER})
    assert 'reason="rejected"' in r.text and placed == [(PHONE, "plivo")]
    _plivo(api, {"CallUUID": "m-2", "From": CALLER})
    assert len(placed) == 1  # one callback per number a day
    # The callback itself is an outbound call into the menu: answered, never rejected.
    cb = _plivo(api, {"CallUUID": "cb-1", "From": "918035000000", "To": CALLER, "Direction": "outbound"})
    assert "<GetDigits" in cb.text


def test_the_script_prints_the_inbound_urls_and_the_village_codes(repo, monkeypatch, capsys):
    from Pukaar.scripts import voice as script

    _voice(monkeypatch, "exotel")
    monkeypatch.setattr(script, "get_repo", lambda: repo)
    script.urls("https://api.example.test")
    out = capsys.readouterr().out
    assert f"/voice/exotel/inbound/prompt?k={KEY}" in out and f"/voice/plivo/inbound?k={KEY}" in out
    script.codes()
    assert "1001  thunag" in capsys.readouterr().out


def test_village_codes_and_caller_numbers(repo):
    assert inbound.village_by_code(repo, "1003").id == "gohar" and inbound.village_by_code(repo, "9999") is None
    assert inbound.caller_number("919812345678") == PHONE and inbound.caller_number("09812345678") == PHONE
    assert inbound.caller_number("anonymous") is None and inbound.caller_number("") is None
