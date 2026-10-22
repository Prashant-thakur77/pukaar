"""Voice calls with "press 1" (delivery/voice.py, exotel.py, plivo.py, ivr.py, api/routers/voice.py).

Providers are faked at the HTTP layer (httpx.MockTransport) with the response shapes their docs give;
nothing here reaches the network. docs/VOICE.md has the live steps.
"""

from __future__ import annotations

import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from Pukaar.delivery import dispatch, exotel, plivo, voice
from Pukaar.store.models import Recipient
from Pukaar.workflow.client import decide

from test_pilot_safety import metrics
from test_workflow_steps import drafted_and_asked

KEY = "test-voice-webhook-key-0123456789"
API = "https://api.example.test"
PHONE = "+919812345678"
EXOTEL_ENV = {"PUKAAR_EXOTEL_SID": "pukaar1", "PUKAAR_EXOTEL_TOKEN": "tok", "PUKAAR_EXOTEL_CALLER_ID": "08047112345",
              "PUKAAR_EXOTEL_APP_ID": "777"}
PLIVO_ENV = {"PUKAAR_PLIVO_AUTH_ID": "MAPLIVO", "PUKAAR_PLIVO_AUTH_TOKEN": "plivo-secret", "PUKAAR_PLIVO_CALLER_ID": "+918035000000"}


class FakeProvider:
    """Records each request and answers as the provider's docs say it does."""

    def __init__(self, kind: str = "exotel", status: int | None = None, body: dict | None = None) -> None:
        self.kind, self.requests, self.n = kind, [], 0
        self.status, self.body = status, body

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.n += 1
        if self.status:
            return httpx.Response(self.status, json=self.body or {})
        if self.kind == "exotel":
            return httpx.Response(200, json={"Call": {"Sid": f"exo-call-{self.n}", "Status": "in-progress",
                                                      "Direction": "outbound-api", "To": None}})
        return httpx.Response(201, json={"api_id": "a1", "message": "call fired", "request_uuid": f"plivo-req-{self.n}"})

    def form(self, i: int = -1) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(self.requests[i].content.decode()).items()}


def _settings(monkeypatch, provider: str = "exotel", **env: str) -> None:
    from Pukaar.core.config import get_settings

    monkeypatch.setenv("PUKAAR_VOICE_PROVIDER", provider)
    monkeypatch.setenv("PUKAAR_API_URL", API)
    monkeypatch.setenv("PUKAAR_VOICE_WEBHOOK_KEY", KEY)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


@pytest.fixture()
def calls(monkeypatch):
    """Exotel on, with a fake Exotel. Yields the fake; every request it got is in .requests."""
    _settings(monkeypatch, "exotel", **EXOTEL_ENV)
    fake = FakeProvider("exotel")
    voice.set_http_client(httpx.Client(transport=httpx.MockTransport(fake)))
    yield fake
    voice.set_http_client(None)
    from Pukaar.core.config import get_settings

    monkeypatch.delenv("PUKAAR_VOICE_PROVIDER")
    get_settings.cache_clear()


@pytest.fixture()
def no_network(monkeypatch):
    def refuse(request):
        raise AssertionError(f"a call was placed: {request.url}")

    voice.set_http_client(httpx.Client(transport=httpx.MockTransport(refuse)))
    yield
    voice.set_http_client(None)
    from Pukaar.core.config import get_settings

    get_settings.cache_clear()


@pytest.fixture()
def api(repo, monkeypatch):
    from Pukaar.api.routers import voice as router
    from Pukaar.main import app

    monkeypatch.setattr(router, "get_repo", lambda: repo)
    return TestClient(app)


def _voice_person(repo, village="thunag", rid="v_asha", channel="voice", role="villager", name="Asha Devi"):
    r = Recipient(id=rid, village_id=village, name=name, channel=channel, phone=PHONE, consent="test", role=role)
    repo.put_recipient(r)
    return r


def _delivered(repo, workflow):
    s, a, _ = drafted_and_asked(repo)
    decide(repo, workflow, a.id, "approved", "officer1")
    s.handle({"step": "deliver", "alert_id": a.id})
    return s, repo.get_alert(a.id)


def _row(repo, alert_id, rid="v_asha"):
    return repo.get_delivery(alert_id, rid, "voice")


def _gather(api, row, digits, key=KEY, call_id=None, token=None):
    token = token or voice.sign_call(row.alert_id, row.recipient_id, row.attempts)
    return api.get("/voice/exotel/gather", params={"k": key, "CustomField": token, "CallSid": call_id or row.call_ids[-1],
                                                   "digits": f'"{digits}"'}, follow_redirects=False)


def _status(api, row, status):
    token = voice.sign_call(row.alert_id, row.recipient_id, row.attempts)
    return api.post(f"/voice/exotel/status?k={KEY}&c={token}",
                    data={"CallSid": row.call_ids[-1], "Status": status, "CustomField": token})


# -- the recipient model ---------------------------------------------------------------------------
def test_recipient_phone_must_be_e164_and_voice_needs_one():
    assert Recipient(id="v_1", village_id="gohar", name="A", channel="voice", phone="+91 98123-45678").phone == PHONE
    with pytest.raises(ValueError, match="E.164"):
        Recipient(id="v_1", village_id="gohar", name="A", channel="voice", phone="09812345678")
    with pytest.raises(ValueError, match="needs a phone"):
        Recipient(id="v_1", village_id="gohar", name="A", channel="both")
    old = Recipient(id="123", village_id="gohar", name="A")  # records from before voice: still Telegram
    assert old.channel == "telegram" and old.takes_telegram and not old.takes_voice


# -- adapters ------------------------------------------------------------------------------------------
def test_exotel_request_carries_a_signed_custom_field_and_no_secret(repo, frozen, monkeypatch):
    _settings(monkeypatch, "exotel", **EXOTEL_ENV)
    fake = FakeProvider("exotel")
    provider = exotel.from_secrets(client=httpx.Client(transport=httpx.MockTransport(fake)))
    r = _voice_person(repo)
    from test_workflow_steps import make_alert

    alert = make_alert(repo)
    attempt = provider.place_call(r, alert, None, voice.sign_call(alert.id, r.id, 1), 1)
    assert attempt.provider == "exotel" and attempt.call_id == "exo-call-1" and attempt.status == "queued"
    req = fake.requests[0]
    assert req.url == "https://api.exotel.com/v1/Accounts/pukaar1/Calls/connect.json"
    assert req.headers["authorization"].startswith("Basic ")  # SID (or API key) and token
    form = fake.form()
    assert form["From"] == PHONE and form["CallerId"] == "08047112345" and form["CallType"] == "trans"
    assert form["Url"] == "http://my.exotel.com/pukaar1/exoml/start_voice/777"
    assert len(form["CustomField"]) <= 128
    tok = voice.verify_call(form["CustomField"])
    assert (tok.alert_id, tok.recipient_id, tok.attempt) == (alert.id, r.id, 1)
    cb = urlsplit(form["StatusCallback"])
    assert f"{cb.scheme}://{cb.netloc}{cb.path}" == f"{API}/voice/exotel/status"
    assert parse_qs(cb.query)["k"] == [KEY] and parse_qs(cb.query)["c"] == [form["CustomField"]]
    assert {form["StatusCallbackEvents[0]"], form["StatusCallbackEvents[1]"]} == {"terminal", "answered"}
    assert "tok" not in json.dumps(form)  # the API token goes in the auth header only


@pytest.mark.parametrize(("status", "message", "category"), [
    (400, "From 919812345678 is not a valid phone number", "invalid_number"),
    (403, "Trial accounts can only call verified numbers", "blocked"),
    (500, "Internal error", "provider_error"),
])
def test_exotel_errors_have_a_category_and_never_echo_the_number(repo, monkeypatch, status, message, category):
    _settings(monkeypatch, "exotel", **EXOTEL_ENV)
    fake = FakeProvider("exotel", status=status, body={"RestException": {"Status": status, "Message": message}})
    provider = exotel.from_secrets(client=httpx.Client(transport=httpx.MockTransport(fake)))
    from test_workflow_steps import make_alert

    with pytest.raises(voice.VoiceError) as exc:
        provider.place_call(_voice_person(repo), make_alert(repo), None, "v1.a.b.1.x.y", 1)
    assert exc.value.category == category and "9812345678" not in str(exc.value)


def test_plivo_request_and_answer_xml(repo, monkeypatch):
    _settings(monkeypatch, "plivo", **PLIVO_ENV)
    fake = FakeProvider("plivo")
    provider = plivo.from_secrets(client=httpx.Client(transport=httpx.MockTransport(fake)))
    from test_workflow_steps import make_alert

    alert, r = make_alert(repo), _voice_person(repo)
    attempt = provider.place_call(r, alert, None, voice.sign_call(alert.id, r.id, 1), 1)
    assert attempt.call_id == "plivo-req-1"
    req = fake.requests[0]
    assert str(req.url) == "https://api.plivo.com/v1/Account/MAPLIVO/Call/"
    body = json.loads(req.content)
    assert body["to"] == PHONE.lstrip("+") and body["answer_method"] == "POST" and body["machine_detection"] == "hangup"
    assert body["answer_url"].startswith(f"{API}/voice/plivo/answer?k=") and "&c=v1." in body["answer_url"]
    xml = plivo.answer_xml(audio_url="https://s3/x.mp3?a=1&b=2", text_hi="t", menu_url=None,
                           digits_url=f"{API}/voice/plivo/digits?k=a&c=b")
    assert 'numDigits="1"' in xml and 'retries="1"' in xml and 'validDigits="123"' in xml
    assert "<Play>https://s3/x.mp3?a=1&amp;b=2</Play>" in xml and "&amp;c=b" in xml  # escaped


def test_plivo_signature_round_trip_and_tamper():
    url = f"{API}/voice/plivo/digits?k=K&c=C"
    params = {"Digits": "1", "CallUUID": "u1", "From": "918035000000"}
    sig = plivo.signature("plivo-secret", "POST", url, params, "nonce1")
    assert plivo.validate_v3("plivo-secret", "POST", url, params, "nonce1", sig)
    assert plivo.validate_v3("plivo-secret", "POST", url, params, "nonce1", f"other,{sig}")  # several tokens
    assert not plivo.validate_v3("plivo-secret", "POST", url, {**params, "Digits": "2"}, "nonce1", sig)
    assert not plivo.validate_v3("plivo-secret", "POST", url, params, "nonce2", sig)
    assert not plivo.validate_v3("wrong", "POST", url, params, "nonce1", sig)
    assert plivo.base_string("POST", url, params) == f"{API}/voice/plivo/digits?c=C&k=K.CallUUIDu1Digits1From918035000000"


def test_call_token_is_signed_and_expires():
    t = voice.sign_call("alr_01abc", "v_x", 2, now=1_000_000)
    assert voice.verify_call(t, now=1_000_000 + 3600).attempt == 2
    with pytest.raises(voice.TokenError, match="expired"):
        voice.verify_call(t, now=1_000_000 + 49 * 3600)
    forged = t.replace("v_x", "v_y")
    with pytest.raises(voice.TokenError, match="bad signature"):
        voice.verify_call(forged, now=1_000_000)


# -- honesty: off means failed, replay never dials -----------------------------------------------------
def test_provider_off_is_failed_with_reason_not_sent(repo, frozen, workflow, no_network, capsys):
    from Pukaar.core.config import get_settings

    get_settings.cache_clear()
    assert get_settings().voice_provider == "off"
    _voice_person(repo)
    s, alert = _delivered(repo, workflow)
    d = _row(repo, alert.id)
    assert d.status == "failed" and d.error_category == "provider_off" and "off" in d.error and d.call_ids == []
    assert alert.delivered_count == 2  # the two stub demo phones only
    assert any(m.get("DeliveryFailed") == 1 and m.get("Channel") == "voice" for m in metrics(capsys))
    out = s.handle({"step": "recall", "alert_id": alert.id})
    assert out["again"] is False and _row(repo, alert.id).attempts == 1  # off is never retried


def test_missing_credentials_are_failed_with_reason(repo, frozen, workflow, no_network, monkeypatch):
    _settings(monkeypatch, "exotel")  # provider on, no SSM credentials
    _voice_person(repo)
    _, alert = _delivered(repo, workflow)
    d = _row(repo, alert.id)
    assert d.status == "failed" and d.error_category == "provider_off" and "credentials unavailable" in d.error


def test_stub_provider_refuses_a_live_alert(repo):
    from test_workflow_steps import make_alert

    with pytest.raises(voice.VoiceError, match="replays only"):
        voice.StubProvider().place_call(_voice_person(repo), make_alert(repo), None, "", 1)


def test_replay_never_dials(repo, frozen, workflow, no_network, monkeypatch):
    _settings(monkeypatch, "exotel", **EXOTEL_ENV)  # a real provider is configured; the replay must not use it
    _voice_person(repo, channel="both", rid="555")
    s, a, _ = drafted_and_asked(repo, "warning", replay=True)
    decide(repo, workflow, a.id, "approved", "officer1")
    s.handle({"step": "deliver", "alert_id": a.id})
    rows = [d for d in repo.list_deliveries(a.id) if d.recipient_id == "555"]
    assert [(d.channel, d.provider, d.call_status) for d in rows] == [("stub", "stub", "simulated")]
    assert s.handle({"step": "recall", "alert_id": a.id})["again"] is False


def test_cedar_forbids_voice_for_a_replay(repo):
    from Pukaar.policy.guard import SYSTEM, authorize

    d = authorize(SYSTEM, "deliver", "alert", "a1", {"approved": True, "level": "warning", "replay": True,
                                                    "channel": "voice", "all_officers_timed_out": False}, repo=repo)
    assert not d.allowed and d.policy_ids == ["no-replay-to-phones"]


# -- the call itself -----------------------------------------------------------------------------
def test_live_alert_places_a_call_and_it_is_pending_until_answered(repo, frozen, workflow, calls):
    _voice_person(repo)
    _, alert = _delivered(repo, workflow)
    d = _row(repo, alert.id)
    assert (d.status, d.provider, d.call_ids, d.attempts) == ("pending", "exotel", ["exo-call-1"], 1)
    assert d.sent_at is None and alert.delivered_count == 2  # not reached until answered


def test_press_1_acknowledges_like_telegram(repo, frozen, workflow, calls, api):
    _voice_person(repo)
    _, alert = _delivered(repo, workflow)
    row = _row(repo, alert.id)
    greet = api.get("/voice/exotel/flow", params={"k": KEY, "CustomField": voice.sign_call(alert.id, "v_asha", 1),
                                                  "CallSid": "exo-call-1"})
    assert greet.status_code == 200 and greet.headers["content-type"].startswith("text/plain")
    assert greet.text == alert.text_hi  # no Polly offline: Exotel speaks the text
    head = api.head("/voice/exotel/flow", params={"k": KEY, "CustomField": voice.sign_call(alert.id, "v_asha", 1),
                                                  "CallSid": "exo-call-1"})
    assert head.status_code == 200
    assert _row(repo, alert.id).status == "sent" and repo.get_alert(alert.id).delivered_count == 3  # the voice reached the ear
    menu = api.get("/voice/exotel/flow", params={"k": KEY, "part": "menu", "CallSid": "exo-call-1",
                                                 "CustomField": voice.sign_call(alert.id, "v_asha", 1)}).json()
    assert menu["max_input_digits"] == 1 and menu["repeat_menu"] == 1 and "1 दबाएँ" in menu["gather_prompt"]["text"]
    r = _gather(api, row, "1")
    assert r.status_code == 200 and r.text == "acknowledged"
    d = _row(repo, alert.id)
    assert d.status == "acknowledged" and d.acknowledged_at and d.digit == "1"
    assert repo.get_alert(alert.id).acknowledged_count == 1
    again = _gather(api, row, "1")  # the provider retries the same webhook
    assert again.status_code == 200 and again.text == "already"
    assert repo.get_alert(alert.id).acknowledged_count == 1
    _status(api, _row(repo, alert.id), "completed")
    assert _row(repo, alert.id).no_key == 0  # acknowledged: no "no key" count


def test_call_audio_is_made_once_and_the_greeting_plays_it(repo, frozen, workflow, calls, api, monkeypatch):
    made = []

    def synth(alert_id, text):
        made.append(alert_id)
        return f"audio/calls/{alert_id}.mp3"

    monkeypatch.setattr("Pukaar.voice.polly.synthesize_call_audio", synth)
    monkeypatch.setattr("Pukaar.voice.polly.menu_audio_key", lambda client=None: "audio/calls/menu-hi-v1.mp3")
    _voice_person(repo)
    _voice_person(repo, rid="v_ravi", name="Ravi")
    _, alert = _delivered(repo, workflow)
    assert made == [alert.id] and alert.call_audio_key == f"audio/calls/{alert.id}.mp3"
    greet = api.get("/voice/exotel/flow", params={"k": KEY, "CustomField": voice.sign_call(alert.id, "v_asha", 1),
                                                  "CallSid": _row(repo, alert.id).call_ids[-1]})
    assert greet.status_code == 200 and greet.text.strip().endswith(f"audio/calls/{alert.id}.mp3")


def test_press_2_creates_a_need_help_report_once(repo, frozen, workflow, calls, api):
    _voice_person(repo)
    _, alert = _delivered(repo, workflow)
    row = _row(repo, alert.id)
    assert _gather(api, row, "2").status_code == 200
    assert _gather(api, row, "2").text == "already"  # idempotent on (call id, digit)
    reports = [r for r in repo.list_reports("thunag") if "voice_need_help" in r.flags]
    assert len(reports) == 1
    rep = reports[0]
    assert rep.severity == "high" and rep.state == "unverified" and rep.reporter_name == "Asha Devi"
    assert PHONE not in rep.model_dump_json() and "9812345678" not in rep.model_dump_json()
    assert _row(repo, alert.id).acknowledged_at  # they heard it
    assert any(t.step == "voice_need_help" for t in repo.list_timeline(alert.id))


def test_press_2_answers_an_open_rollcall_as_need_help(repo, frozen, workflow, calls, api):
    from Pukaar.policy.guard import Principal
    from Pukaar.services import rollcall

    _voice_person(repo)
    _, alert = _delivered(repo, workflow)
    rc = rollcall.open_rollcall(repo, repo.get_village("thunag"), principal=Principal("officer1", "officer"))
    asked = repo.get_rollcall_asked(rc.id, "v_asha")
    assert asked.channel == "voice" and "voice call" in asked.error  # not asked by call: said so
    _gather(api, _row(repo, alert.id), "2")
    assert repo.get_rollcall_response(rc.id, "v_asha").status == "need_help"
    assert repo.get_rollcall(rc.id).need_help == 1


def test_press_3_repeats_then_invalid_reprompts_once(repo, frozen, workflow, calls, api):
    _voice_person(repo)
    _, alert = _delivered(repo, workflow)
    row = _row(repo, alert.id)
    assert [_gather(api, row, "3").status_code for _ in range(3)] == [302, 302, 200]  # at most two repeats
    assert _gather(api, row, "7").status_code == 302  # wrong key: asked again once
    assert _gather(api, row, "9").status_code == 200  # then the call ends
    assert _gather(api, row, "").status_code == 200  # silence after the menu's own re-prompt ends the call
    assert not _row(repo, alert.id).acknowledged_at


# -- authentication ------------------------------------------------------------------------------
def test_forged_key_presses_are_refused_and_change_nothing(repo, frozen, workflow, calls, api):
    _voice_person(repo)
    _, alert = _delivered(repo, workflow)
    row = _row(repo, alert.id)
    good = voice.sign_call(alert.id, "v_asha", 1)
    assert _gather(api, row, "1", key="").status_code == 403  # no URL key
    assert _gather(api, row, "1", key="guess-guess-guess-guess").status_code == 403  # wrong URL key
    assert _gather(api, row, "1", token=good[:-3] + "AAA").status_code == 403  # tampered CustomField
    assert _gather(api, row, "1", token="v1.alr_x.v_asha.1.zz.abc").status_code == 403  # made-up token
    assert _gather(api, row, "1", call_id="someone-elses-call").status_code == 403  # not a call Pukaar placed
    other = voice.sign_call(alert.id, "stub-thunag-1", 1)  # a real token for a person with no call
    assert _gather(api, row, "1", token=other).status_code == 403
    assert api.get("/voice/exotel/flow", params={"CustomField": good, "CallSid": "exo-call-1"}).status_code == 403
    assert api.post("/voice/exotel/status", data={"CallSid": "exo-call-1", "Status": "busy"}).status_code == 403
    d = _row(repo, alert.id)
    assert not d.acknowledged_at and d.status == "pending" and d.not_connected == 0
    assert repo.get_alert(alert.id).acknowledged_count == 0


def test_no_webhook_key_in_ssm_refuses_everything(repo, frozen, workflow, calls, api, monkeypatch):
    _voice_person(repo)
    _, alert = _delivered(repo, workflow)
    row = _row(repo, alert.id)
    monkeypatch.delenv("PUKAAR_VOICE_WEBHOOK_KEY")
    assert _gather(api, row, "1", key="").status_code == 403
    assert _gather(api, row, "1", key="None").status_code == 403


def test_plivo_webhooks_need_the_provider_signature(repo, frozen, workflow, monkeypatch, api):
    _settings(monkeypatch, "plivo", **PLIVO_ENV)
    fake = FakeProvider("plivo")
    voice.set_http_client(httpx.Client(transport=httpx.MockTransport(fake)))
    try:
        _voice_person(repo)
        _, alert = _delivered(repo, workflow)
        row = _row(repo, alert.id)
        assert row.call_ids == ["plivo-req-1"]
        token = voice.sign_call(alert.id, "v_asha", 1)
        url = f"http://testserver/voice/plivo/digits?k={KEY}&c={token}"
        params = {"Digits": "1", "RequestUUID": "plivo-req-1", "CallUUID": "c-uuid"}
        unsigned = api.post(url, data=params)
        assert unsigned.status_code == 403
        bad = api.post(url, data=params, headers={"X-Plivo-Signature-V3-Nonce": "n1", "X-Plivo-Signature-V3": "AAAA"})
        assert bad.status_code == 403 and not _row(repo, alert.id).acknowledged_at
        sig = plivo.signature("plivo-secret", "POST", url, params, "n1")
        ok = api.post(url, data=params, headers={"X-Plivo-Signature-V3-Nonce": "n1", "X-Plivo-Signature-V3": sig})
        assert ok.status_code == 200 and "<Hangup/>" in ok.text and _row(repo, alert.id).acknowledged_at
        answer_url = f"http://testserver/voice/plivo/answer?k={KEY}&c={token}"
        p2 = {"RequestUUID": "plivo-req-1", "CallUUID": "c-uuid"}
        ans = api.post(answer_url, data=p2, headers={"X-Plivo-Signature-V3-Nonce": "n2",
                                                     "X-Plivo-Signature-V3": plivo.signature("plivo-secret", "POST", answer_url, p2, "n2")})
        assert ans.status_code == 200 and "<GetDigits" in ans.text and "/voice/plivo/digits?" in ans.text
    finally:
        voice.set_http_client(None)


# -- the two retry counters ----------------------------------------------------------------------
def test_not_connected_counter_recall_and_unreachable_flag(repo, frozen, workflow, calls, api, monkeypatch):
    sent_to_pradhan = []
    monkeypatch.setenv("PUKAAR_TELEGRAM_TOKEN", "fake")
    monkeypatch.setattr("Pukaar.delivery.telegram.send_text", lambda chat, text: sent_to_pradhan.append((chat, text)))
    monkeypatch.setattr("Pukaar.delivery.telegram.send_alert", lambda *a, **k: None)
    repo.put_recipient(Recipient(id="777", village_id="thunag", name="Pradhan Ji", role="pradhan", channel="telegram"))
    _voice_person(repo)
    s, alert = _delivered(repo, workflow)
    assert _status(api, _row(repo, alert.id), "busy").json()["outcome"] == "not_connected"
    d = _row(repo, alert.id)
    assert (d.status, d.not_connected, d.no_key, d.error_category) == ("failed", 1, 0, "busy")
    assert _status(api, d, "busy").json()["outcome"] == "already"  # a repeated final status counts once

    out = s.handle({"step": "recall", "alert_id": alert.id})  # after AckWaitSeconds
    assert out["again"] is True and _row(repo, alert.id).call_ids == ["exo-call-1", "exo-call-2"]
    _status(api, _row(repo, alert.id), "no-answer")
    out = s.handle({"step": "recall", "alert_id": alert.id})  # after VoiceRetrySeconds
    assert out["again"] is False and _row(repo, alert.id).attempts == 3
    _status(api, _row(repo, alert.id), "failed")
    d = _row(repo, alert.id)
    assert d.not_connected == 3 and d.unreachable and d.status == "failed"
    assert any(t.step == "voice_unreachable" for t in repo.list_timeline(alert.id))
    flagged = [t for chat, t in sent_to_pradhan if chat == "777"]
    assert flagged and "Asha" in flagged[0] and "9812345678" not in flagged[0]
    assert s.handle({"step": "recall", "alert_id": alert.id})["again"] is False  # never a fourth call
    assert len(calls.requests) == 3


def test_answered_without_a_key_is_the_second_counter(repo, frozen, workflow, calls, api):
    _voice_person(repo)
    s, alert = _delivered(repo, workflow)
    _status(api, _row(repo, alert.id), "completed")
    d = _row(repo, alert.id)
    assert (d.status, d.no_key, d.not_connected, d.error_category) == ("sent", 1, 0, "no_key")
    assert d.sent_at and repo.get_alert(alert.id).delivered_count == 3  # reached, not acknowledged
    s.handle({"step": "recall", "alert_id": alert.id})
    d = _row(repo, alert.id)
    assert d.attempts == 2 and d.status == "sent" and d.sent_at  # still reached while the re-call rings
    _gather(api, d, "1")
    assert s.handle({"step": "recall", "alert_id": alert.id})["again"] is False
    assert len(calls.requests) == 2 and not _row(repo, alert.id).unreachable


def test_a_lost_status_callback_is_retried_as_no_status(repo, frozen, workflow, calls):
    _voice_person(repo)
    s, alert = _delivered(repo, workflow)
    assert s.handle({"step": "recall", "alert_id": alert.id})["resent"] == 2  # stubs only: the call may still ring
    assert len(calls.requests) == 1
    frozen["now"] = frozen["now"] + timedelta(minutes=10)
    s.handle({"step": "recall", "alert_id": alert.id})
    d = _row(repo, alert.id)
    assert d.attempts == 2 and d.not_connected == 1 and d.error_category == "no_status"


def test_telegram_ack_stops_the_recall_of_a_both_recipient(repo, frozen, workflow, calls, monkeypatch):
    monkeypatch.setenv("PUKAAR_TELEGRAM_TOKEN", "fake")
    monkeypatch.setattr("Pukaar.delivery.telegram.send_alert", lambda *a, **k: None)
    _voice_person(repo, rid="4242", channel="both")
    s, alert = _delivered(repo, workflow)
    assert {d.channel for d in repo.list_deliveries(alert.id) if d.recipient_id == "4242"} == {"telegram", "voice"}
    dispatch.acknowledge(repo, alert.id, "4242")  # the Telegram button
    a = repo.get_alert(alert.id)
    assert a.acknowledged_count == 1 and a.delivered_count == 3  # one person, counted once
    s.handle({"step": "recall", "alert_id": alert.id})
    assert len(calls.requests) == 1  # no re-call after "मिल गया" on Telegram


# -- drills ----------------------------------------------------------------------------------------
def test_voice_drill_calls_only_voice_numbers(repo, frozen, workflow, calls, monkeypatch):
    from Pukaar.workflow.steps import Steps

    sent = []
    monkeypatch.setenv("PUKAAR_TELEGRAM_TOKEN", "fake")
    monkeypatch.setattr("Pukaar.delivery.telegram.send_alert", lambda chat, *a, **k: sent.append(chat))
    repo.put_recipient(Recipient(id="1001", village_id="gohar", name="Telegram only", channel="telegram"))
    _voice_person(repo, village="gohar")
    from Pukaar.scripts import drill

    monkeypatch.setattr(drill, "get_repo", lambda: repo)
    monkeypatch.setattr(drill, "get_workflow", lambda: workflow)
    drill.main("gohar", "watch", "voice")
    alert_id = workflow.started[-1]
    a = repo.get_alert(alert_id)
    assert a.decision_trace["drill_channel"] == "voice"
    s = Steps(repo, None, synthesize=lambda *a: None)
    s.handle({"step": "draft", "alert_id": alert_id})
    s.handle({"step": "ask_officer", "alert_id": alert_id, "officer_index": 0, "task_token": "T"})
    officer = repo.get_village("gohar").officers[0]
    decide(repo, workflow, alert_id, "approved", officer)
    s.handle({"step": "deliver", "alert_id": alert_id})
    assert sent == [] and len(calls.requests) == 1
    assert repo.get_alert(alert_id).text_hi.startswith("अभ्यास (DRILL)")


def test_voice_drill_needs_recorded_consent(repo, monkeypatch, workflow):
    from Pukaar.scripts import drill

    repo.put_recipient(Recipient(id="v_no", village_id="gohar", name="No consent", channel="voice", phone=PHONE))
    monkeypatch.setattr(drill, "get_repo", lambda: repo)
    monkeypatch.setattr(drill, "get_workflow", lambda: workflow)
    with pytest.raises(SystemExit, match="consent"):
        drill.main("gohar", "watch", "voice")
    assert workflow.started == []


def test_mask_hides_numbers():
    assert voice.mask("To +91 98123 45678 failed") == "To <number> failed"
    assert voice.mask_phone(PHONE) == "+91******78"


def test_register_script_adds_masks_and_removes(repo, monkeypatch, capsys):
    from Pukaar.scripts import voice as script

    monkeypatch.setattr(script, "get_repo", lambda: repo)
    with pytest.raises(SystemExit, match="agreed"):
        script.add("gohar", "Asha Devi", PHONE, " ")
    script.add("gohar", "Asha Devi", "+91 98123 45678", "verbal, field visit")
    out = capsys.readouterr().out
    assert "+91******78" in out and "9812345678" not in out
    r = next(x for x in repo.list_recipients("gohar") if x.channel == "voice")
    assert r.phone == PHONE and r.id.startswith("v_") and r.consent == "verbal, field visit"
    with pytest.raises(SystemExit, match="already registered"):
        script.add("gohar", "Asha again", PHONE, "verbal")
    repo.put_recipient(Recipient(id="9001", village_id="gohar", name="Ravi", channel="telegram"))
    script.add("gohar", "Ravi", "+919800000001", "verbal", "villager", "9001")
    assert repo.get_recipient("gohar", "9001").channel == "both"
    script.remove("gohar", "9001")
    kept = repo.get_recipient("gohar", "9001")
    assert kept.channel == "telegram" and kept.phone is None
    script.remove("gohar", r.id)
    assert repo.get_recipient("gohar", r.id) is None
