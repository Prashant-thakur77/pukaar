"""Web Push to officers (feature 11): RFC 8291 encryption, VAPID, subscriptions, Cedar,
the push on ask_officer (live and drill, never replay) and cleanup of dead subscriptions."""

from __future__ import annotations

import json

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from Pukaar.delivery import webpush
from Pukaar.policy.guard import Principal, evaluate
from Pukaar.services import officer_push
from test_workflow_steps import make_alert, steps

FCM = "https://fcm.googleapis.com/fcm/send/"


# -- RFC 8291 Appendix A: the exact bytes ----------------------------------------------
RFC = {
    "plaintext": b"When I grow up, I want to be a watermelon",
    "as_private": "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw",
    "as_public": "BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8",
    "ua_private": "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94",
    "ua_public": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
    "auth": "BTBZMqHH6r4Tts7J_aSIgg",
    "salt": "DGv6ra1nlYgDCS1FRnbzlw",
    "message": "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6"
               "PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN",
}


def test_encrypt_matches_rfc8291_appendix_a():
    as_private = webpush.private_key_from_text(RFC["as_private"])
    assert webpush.public_key_text(as_private) == RFC["as_public"]
    out = webpush.encrypt(RFC["plaintext"], webpush.unb64u(RFC["ua_public"]), webpush.unb64u(RFC["auth"]),
                          salt=webpush.unb64u(RFC["salt"]), as_private=as_private)
    assert webpush.b64u(out) == RFC["message"]


def test_decrypt_with_the_browser_key_round_trips_fresh_messages():
    ua = ec.generate_private_key(ec.SECP256R1())
    auth = b"0123456789abcdef"
    msg = json.dumps({"title": "पुकार: थुनाग चेतावनी"}, ensure_ascii=False).encode()
    a = webpush.encrypt(msg, webpush.unb64u(webpush.public_key_text(ua)), auth)
    b = webpush.encrypt(msg, webpush.unb64u(webpush.public_key_text(ua)), auth)
    assert a != b  # fresh salt and server key for every message
    assert webpush.decrypt(a, ua, auth) == msg == webpush.decrypt(b, ua, auth)
    rfc_ua = webpush.private_key_from_text(RFC["ua_private"])
    assert webpush.decrypt(webpush.unb64u(RFC["message"]), rfc_ua, webpush.unb64u(RFC["auth"])) == RFC["plaintext"]


def test_oversize_payload_and_bad_keys_are_refused():
    ua = webpush.unb64u(RFC["ua_public"])
    with pytest.raises(webpush.PushError):
        webpush.encrypt(b"x" * (webpush.MAX_PAYLOAD + 1), ua, b"0" * 16)
    with pytest.raises(webpush.PushError):
        webpush.encrypt(b"hi", ua, b"short")
    with pytest.raises(webpush.PushError):
        webpush.public_key_from_bytes(b"\x04" + b"\x01" * 64)  # not on the curve


def test_vapid_header_is_an_es256_jwt_for_the_push_service_origin():
    key = ec.generate_private_key(ec.SECP256R1())
    header = webpush.vapid_header(FCM + "abc", key, "mailto:ops@example.org", now=1_700_000_000)
    assert header.startswith("vapid t=")
    t, k = header[len("vapid t="):].split(", k=")
    assert k == webpush.public_key_text(key)
    claims = jwt.decode(t, key.public_key(), algorithms=["ES256"], audience="https://fcm.googleapis.com",
                        options={"verify_exp": False})
    assert claims["sub"] == "mailto:ops@example.org"
    assert claims["exp"] - 1_700_000_000 <= 24 * 3600
    assert len(webpush.unb64u(t.split(".")[2])) == 64  # raw r||s, as JWS ES256 requires


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/fcm/send/x", "https://evil.example.com/push", "https://fcm.googleapis.com.evil.io/x",
    "https://169.254.169.254/latest", "ftp://updates.push.services.mozilla.com/x",
])
def test_endpoints_must_be_https_on_a_known_push_service(endpoint):
    with pytest.raises(webpush.PushError):
        webpush.check_endpoint(endpoint)


@pytest.mark.parametrize("endpoint", [
    FCM + "abc", "https://updates.push.services.mozilla.com/wpush/v2/abc", "https://web.push.apple.com/QF2x",
    "https://wns2-par02p.notify.windows.com/w/?token=abc",
])
def test_browser_push_services_are_accepted(endpoint):
    assert webpush.check_endpoint(endpoint) == endpoint


# -- a fake phone: a real key pair, and a push service that decrypts what it receives ---------
class Phone:
    def __init__(self, name: str = "a") -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = bytes(range(16))
        self.endpoint = FCM + name

    def body(self) -> dict:
        return {"endpoint": self.endpoint, "expirationTime": None,
                "keys": {"p256dh": webpush.public_key_text(self.key), "auth": webpush.b64u(self.auth)}}


class PushService:
    def __init__(self) -> None:
        self.phones: dict[str, Phone] = {}
        self.status: dict[str, int] = {}
        self.received: list[tuple[str, dict, httpx.Headers]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        status = self.status.get(url, 201)
        phone = self.phones.get(url)
        if phone is not None and status == 201:
            payload = json.loads(webpush.decrypt(request.content, phone.key, phone.auth))
            self.received.append((url, payload, request.headers))
        return httpx.Response(status)


@pytest.fixture()
def push(monkeypatch):
    svc = PushService()
    monkeypatch.setattr(officer_push, "_TRANSPORT", httpx.MockTransport(svc.handler))
    return svc


def subscribe(repo, svc: PushService, user="officer1", name="a", ua="") -> Phone:
    phone = Phone(name)
    svc.phones[phone.endpoint] = phone
    b = phone.body()
    officer_push.subscribe(repo, user, b["endpoint"], b["keys"]["p256dh"], b["keys"]["auth"], ua)
    return phone


def ask(repo, *, replay=False, drill=False, level="warning"):
    s = steps(repo)
    a = make_alert(repo, level, replay)
    if drill:
        repo.update_alert(a.id, decision_trace={"rules_fired": ["drill"], "drill": True})
    s.handle({"step": "draft", "alert_id": a.id})
    s.handle({"step": "ask_officer", "alert_id": a.id, "officer_index": 0, "task_token": "TOKEN-1"})
    return repo.get_alert(a.id)


def test_ask_officer_pushes_approve_and_decline_with_the_signed_link(repo, frozen, push):
    from Pukaar.workflow import tokens

    subscribe(repo, push, "officer1", "a")
    subscribe(repo, push, "officer2", "b")  # the second officer is not asked yet
    alert = ask(repo)
    assert len(push.received) == 1
    url, p, headers = push.received[0]
    assert url == FCM + "a"
    assert p["title"] == "पुकार: थुनाग चेतावनी"
    assert p["body"].startswith(alert.text_hi[:40]) and "Approve within 10 min" in p["body"]
    assert len(p["body"].split("\n")[0]) <= officer_push.BODY_CHARS + 1
    assert p["tag"] == alert.id and p["renotify"] is True and p["requireInteraction"] is True
    assert p["actions"] == [{"action": "approve", "title": "✅ मंज़ूर"}, {"action": "decline", "title": "✖ नहीं"}]
    t = tokens.verify(p["data"]["token"], "approve")
    assert (t.alert_id, t.subject, t.version) == (alert.id, "officer1", alert.token_version)
    assert p["data"]["url"].endswith(f"/a/{p['data']['token']}") and p["data"]["alert_id"] == alert.id
    assert headers["TTL"] == "600" and headers["Urgency"] == "high" and headers["Content-Encoding"] == "aes128gcm"
    assert headers["Authorization"].startswith("vapid t=")
    assert "push=1" in repo.list_timeline(alert.id)[-1].detail
    assert repo.list_push_subscriptions("officer1")[0].last_sent_at is not None


def test_replay_never_pushes(repo, frozen, push):
    subscribe(repo, push)
    alert = ask(repo, replay=True)
    assert push.received == []
    assert "push=0" in repo.list_timeline(alert.id)[-1].detail


def test_a_drill_is_pushed_and_labelled(repo, frozen, push):
    subscribe(repo, push)
    ask(repo, drill=True, level="watch")
    p = push.received[0][1]
    assert "DRILL" in p["title"] and p["data"]["drill"] is True


def test_gone_subscription_is_deleted_and_the_step_still_succeeds(repo, frozen, push, monkeypatch):
    metrics = []
    monkeypatch.setattr(officer_push, "metric", lambda name, *a, **k: metrics.append(name))
    dead = subscribe(repo, push, name="dead")
    live = subscribe(repo, push, name="live")
    push.status[dead.endpoint] = 410
    alert = ask(repo)
    assert [u for u, _, _ in push.received] == [live.endpoint]
    assert [s.endpoint for s in repo.list_push_subscriptions("officer1")] == [live.endpoint]
    assert metrics.count("PushFailed") == 1 and metrics.count("PushSent") == 1
    assert alert.status == "pending"


def test_push_service_errors_and_network_failures_never_break_ask_officer(repo, frozen, monkeypatch):
    def boom(request):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(officer_push, "_TRANSPORT", httpx.MockTransport(boom))
    metrics = []
    monkeypatch.setattr(officer_push, "metric", lambda name, *a, **k: metrics.append(name))
    phone = Phone()
    officer_push.subscribe(repo, "officer1", phone.endpoint, *phone.body()["keys"].values())
    alert = ask(repo)
    assert alert.status == "pending" and metrics == ["PushFailed"]
    assert len(repo.list_push_subscriptions("officer1")) == 1  # a network error is not "gone"
    # a 500 from the push service is a failure too, and keeps the subscription
    svc = PushService()
    svc.status[phone.endpoint] = 500
    monkeypatch.setattr(officer_push, "_TRANSPORT", httpx.MockTransport(svc.handler))
    assert officer_push.send_test(repo, "officer1").failed == 1
    assert len(repo.list_push_subscriptions("officer1")) == 1


def test_no_keys_means_no_push_and_no_error(repo, frozen, push, monkeypatch):
    subscribe(repo, push)
    monkeypatch.setattr(officer_push, "vapid_keys", lambda: None)
    ask(repo)
    assert push.received == []


def test_mismatched_keys_are_treated_as_not_set_up(monkeypatch):
    priv, _ = webpush.generate_keys()
    _, other_pub = webpush.generate_keys()
    monkeypatch.setenv("PUKAAR_VAPID_PRIVATE_KEY", priv)
    monkeypatch.setenv("PUKAAR_VAPID_PUBLIC_KEY", other_pub)
    assert officer_push.vapid_keys() is None
    monkeypatch.setenv("PUKAAR_VAPID_PUBLIC_KEY", webpush.public_key_text(webpush.private_key_from_text(priv)))
    assert officer_push.public_key() == webpush.public_key_text(webpush.private_key_from_text(priv))


def test_subscribing_again_replaces_and_old_phones_beyond_the_cap_are_dropped(repo, frozen, push):
    first = subscribe(repo, push, name="p0", ua="Mozilla/5.0 (Linux; Android 14) Chrome/130.0 Mobile Safari/537.36")
    officer_push.subscribe(repo, "officer1", first.endpoint, *first.body()["keys"].values())
    subs = repo.list_push_subscriptions("officer1")
    assert len(subs) == 1 and subs[0].id == officer_push.subscription_id(first.endpoint)
    for i in range(1, officer_push.MAX_SUBSCRIPTIONS_PER_USER + 2):
        subscribe(repo, push, name=f"p{i}")
    assert len(repo.list_push_subscriptions("officer1")) == officer_push.MAX_SUBSCRIPTIONS_PER_USER


def test_subscriptions_expire_after_180_days(repo, frozen, push):
    from datetime import timedelta

    subscribe(repo, push)
    assert len(repo.list_push_subscriptions("officer1")) == 1
    frozen["now"] = frozen["now"] + timedelta(days=181)
    assert repo.list_push_subscriptions("officer1") == []


def test_subscription_id_matches_the_web_app():
    # frontend/src/lib/push.test.ts asserts the same value for the same endpoint
    assert officer_push.subscription_id("https://fcm.googleapis.com/fcm/send/abc") == "4e9bdab8bbe7189c00aebb09"


@pytest.mark.parametrize("ua,summary", [
    ("Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36", "Chrome on Android"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
     "Safari on iOS"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36 Edg/130.0", "Edge on Windows"),
    ("Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0", "Firefox on Linux"),
    ("", "Browser"),
])
def test_user_agent_is_reduced_to_a_short_summary(ua, summary):
    assert officer_push.summarize_user_agent(ua) == summary


# -- Cedar -----------------------------------------------------------------------------
def test_cedar_subscribe_push_is_for_officers_and_pradhans_only():
    assert evaluate(Principal("officer1", "officer"), "subscribe_push", "app", "pukaar").allowed
    assert evaluate(Principal("p", "pradhan", ["thunag"]), "subscribe_push", "app", "pukaar").allowed
    assert not evaluate(Principal("pukaar-system", "system"), "subscribe_push", "app", "pukaar").allowed
    assert not evaluate(Principal("drafting", "agent"), "subscribe_push", "app", "pukaar").allowed


# -- HTTP routes -----------------------------------------------------------------------
@pytest.fixture()
def client(repo, monkeypatch):
    from Pukaar.api import auth
    from Pukaar.api.routers import push as push_router
    from Pukaar.main import app

    for mod in (auth, push_router):
        monkeypatch.setattr(mod, "get_repo", lambda: repo)
    return TestClient(app)


def bearer(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_public_key_is_public_and_a_usable_p256_point(client):
    r = client.get("/push/vapid-public-key")
    assert r.status_code == 200 and r.json()["configured"] is True
    webpush.public_key_from_bytes(webpush.unb64u(r.json()["key"]))


def test_subscription_crud_over_http(client, repo, frozen, push):
    h = bearer(client, "officer1")
    phone = Phone()
    push.phones[phone.endpoint] = phone
    assert client.post("/me/push-subscriptions", json=phone.body()).status_code == 401
    r = client.post("/me/push-subscriptions", json=phone.body(),
                    headers={**h, "User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/130.0 Mobile Safari/537.36"})
    assert r.status_code == 200, r.text
    sub = r.json()
    assert sub == {"id": officer_push.subscription_id(phone.endpoint), "user_agent": "Chrome on Android",
                   "created_at": sub["created_at"], "last_sent_at": None}
    listed = client.get("/me/push-subscriptions", headers=h).json()
    assert listed == [sub]  # never the endpoint or the keys
    # another user cannot see or remove it
    other = bearer(client, "officer2")
    assert client.get("/me/push-subscriptions", headers=other).json() == []
    assert client.delete(f"/me/push-subscriptions/{sub['id']}", headers=other).status_code == 404
    # test notification, then the rate limit
    r = client.post("/me/push-test", headers=h)
    assert r.status_code == 200 and r.json() == {"sent": 1, "failed": 0, "removed": 0}
    assert push.received[-1][1]["kind"] == "test" and push.received[-1][1]["actions"] == []
    r = client.post("/me/push-test", headers=h)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "rate_limited"
    assert client.delete(f"/me/push-subscriptions/{sub['id']}", headers=h).json() == {"ok": True, "id": sub["id"]}
    assert client.get("/me/push-subscriptions", headers=h).json() == []
    assert client.delete(f"/me/push-subscriptions/{sub['id']}", headers=h).status_code == 404


def test_pradhan_may_subscribe_and_bad_subscriptions_are_400(client, repo, frozen):
    h = bearer(client, "pradhan_thunag")
    good = Phone().body()
    assert client.post("/me/push-subscriptions", json=good, headers=h).status_code == 200
    bad_host = {**good, "endpoint": "https://attacker.example/x"}
    assert client.post("/me/push-subscriptions", json=bad_host, headers=h).status_code == 400
    bad_key = {**good, "keys": {"p256dh": "AAAA", "auth": good["keys"]["auth"]}}
    assert client.post("/me/push-subscriptions", json=bad_key, headers=h).status_code == 400
    bad_auth = {**good, "keys": {"p256dh": good["keys"]["p256dh"], "auth": "AAAA"}}
    assert client.post("/me/push-subscriptions", json=bad_auth, headers=h).status_code == 400


def test_push_test_needs_a_subscription(client, repo, frozen):
    r = client.post("/me/push-test", headers=bearer(client, "officer2"))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_subscription"


def test_vapid_keys_script_stores_secure_private_key_and_never_prints_it(capsys, monkeypatch):
    from moto import mock_aws
    from Pukaar.scripts import vapid_keys

    with mock_aws():
        import boto3

        ssm = boto3.client("ssm", region_name="us-east-1")
        assert vapid_keys.main([]) == 0
        priv = ssm.get_parameter(Name="/pukaar/vapid_private_key", WithDecryption=True)["Parameter"]
        pub = ssm.get_parameter(Name="/pukaar/vapid_public_key")["Parameter"]
        assert priv["Type"] == "SecureString" and pub["Type"] == "String"
        assert webpush.public_key_text(webpush.private_key_from_text(priv["Value"])) == pub["Value"]
        out = capsys.readouterr().out
        assert priv["Value"] not in out and pub["Value"] in out
        assert vapid_keys.main([]) == 0  # kept
        assert ssm.get_parameter(Name="/pukaar/vapid_public_key")["Parameter"]["Value"] == pub["Value"]
        assert vapid_keys.main(["--rotate"]) == 0
        assert ssm.get_parameter(Name="/pukaar/vapid_public_key")["Parameter"]["Value"] != pub["Value"]
        new_priv = ssm.get_parameter(Name="/pukaar/vapid_private_key", WithDecryption=True)["Parameter"]["Value"]
        assert new_priv not in capsys.readouterr().out
