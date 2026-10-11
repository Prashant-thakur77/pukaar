"""Web Push to officers: the approval request on the phone's lock screen, with Approve and
Decline buttons that work while the console is closed.

The notification carries the same signed one-tap link the officer gets on Telegram
(workflow/tokens.py); the service worker (frontend/src/sw.ts) POSTs the decision to the
public /approval/{token} route, so a tap resolves the Step Functions task token exactly as
opening the link would. Push is an extra channel: a failure here never breaks the step.

Keys: SSM /pukaar/vapid_private_key (SecureString) and /pukaar/vapid_public_key (String),
made once with `make vapid-keys`. Local mode without keys makes a pair per process.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric import ec

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log, metric
from Pukaar.core.secrets import get_secret
from Pukaar.delivery import webpush
from Pukaar.store.models import Alert, PushSubscription
from Pukaar.store.repo import Repo
from Pukaar.templates import hi

_LOG = get_logger("push")
MAX_SUBSCRIPTIONS_PER_USER = 10
TEST_INTERVAL_SECONDS = 60
BODY_CHARS = 120
APPROVE_TITLE = "✅ मंज़ूर"
DECLINE_TITLE = "✖ नहीं"
GONE = {404, 410}  # the push service says this subscription no longer exists

_LOCAL_KEYS: dict[str, str] = {}
# Tests swap in an httpx.MockTransport; None is the real network.
_TRANSPORT: httpx.BaseTransport | None = None


@dataclass(frozen=True)
class VapidKeys:
    private: ec.EllipticCurvePrivateKey
    public: str  # base64url uncompressed point: the browser's applicationServerKey


@dataclass
class PushResult:
    sent: int = 0
    failed: int = 0
    removed: int = 0


def vapid_keys() -> VapidKeys | None:
    """None when Web Push is not set up (no keys in SSM). A private key that does not match the
    public key is treated as not set up: browsers subscribed with the public one."""
    priv = get_secret("vapid_private_key")
    pub = get_secret("vapid_public_key")
    if not (priv and pub) and get_settings().is_local:
        if not _LOCAL_KEYS:
            _LOCAL_KEYS["private"], _LOCAL_KEYS["public"] = webpush.generate_keys()
        priv, pub = _LOCAL_KEYS["private"], _LOCAL_KEYS["public"]
    if not (priv and pub):
        return None
    try:
        key = webpush.private_key_from_text(priv)
    except (webpush.PushError, ValueError) as exc:
        log(_LOG, "vapid private key unreadable", 40, error=str(exc)[:200])
        return None
    if webpush.public_key_text(key) != pub.strip():
        log(_LOG, "vapid keys do not match; run make vapid-keys ROTATE=1", 40)
        return None
    return VapidKeys(key, pub.strip())


def public_key() -> str | None:
    keys = vapid_keys()
    return keys.public if keys else None


def subject() -> str:
    """VAPID 'sub': a contact for the push service. https web URL, or a mailto: for local runs."""
    explicit = os.environ.get("PUKAAR_VAPID_SUBJECT", "").strip()
    if explicit:
        return explicit
    web = get_settings().web_url
    return web if web.startswith("https://") else "mailto:pukaar@localhost"


def subscription_id(endpoint: str) -> str:
    """Same endpoint, same id (frontend/src/lib/push.ts computes it the same way)."""
    return hashlib.sha256(endpoint.encode()).hexdigest()[:24]


def summarize_user_agent(ua: str) -> str:
    """"Chrome on Android": enough for an officer to recognise the phone, nothing more is stored."""
    ua = ua or ""
    browser = next((name for pat, name in (
        (r"EdgA?/|Edg/", "Edge"), (r"SamsungBrowser/", "Samsung Internet"), (r"OPR/|Opera", "Opera"),
        (r"Firefox/|FxiOS/", "Firefox"), (r"CriOS/|Chrome/", "Chrome"), (r"Safari/", "Safari"),
    ) if re.search(pat, ua)), "Browser")
    system = next((name for pat, name in (
        (r"Android", "Android"), (r"iPhone|iPad|iPod", "iOS"), (r"Windows", "Windows"),
        (r"Mac OS X|Macintosh", "macOS"), (r"CrOS", "ChromeOS"), (r"Linux", "Linux"),
    ) if re.search(pat, ua)), "")
    return f"{browser} on {system}" if system else browser


def subscribe(repo: Repo, username: str, endpoint: str, p256dh: str, auth: str, user_agent: str = "") -> PushSubscription:
    """Validate and store one browser subscription. Raises webpush.PushError for a bad one."""
    webpush.check_endpoint(endpoint)
    try:
        key, secret = webpush.unb64u(p256dh), webpush.unb64u(auth)
    except ValueError as exc:
        raise webpush.PushError("keys must be base64url") from exc
    webpush.public_key_from_bytes(key)
    if len(secret) != 16:
        raise webpush.PushError("auth must be 16 bytes")
    sub = PushSubscription(id=subscription_id(endpoint), username=username, endpoint=endpoint,
                           p256dh=webpush.b64u(key), auth=webpush.b64u(secret), created_at=clock.iso(clock.now()),
                           user_agent=summarize_user_agent(user_agent))
    existing = [s for s in repo.list_push_subscriptions(username) if s.id != sub.id]
    for old in existing[:max(0, len(existing) - (MAX_SUBSCRIPTIONS_PER_USER - 1))]:  # keep the newest
        repo.delete_push_subscription(username, old.id)
    repo.put_push_subscription(sub)
    return sub


def view(sub: PushSubscription) -> dict:
    """What the console sees: never the endpoint or the keys."""
    return {"id": sub.id, "user_agent": sub.user_agent, "created_at": sub.created_at, "last_sent_at": sub.last_sent_at}


def _http() -> httpx.Client:
    return httpx.Client(timeout=6.0, transport=_TRANSPORT)


def send_to_user(repo: Repo, username: str, payload: dict[str, Any], *, ttl: int, urgency: str = "high",
                 kind: str = "approval") -> PushResult:
    """Send one message to every subscription of this user. Never raises.
    404/410 from the push service deletes the subscription."""
    result = PushResult()
    try:
        subs = repo.list_push_subscriptions(username)
        if not subs:
            return result
        keys = vapid_keys()
        if keys is None:
            log(_LOG, "push skipped: no VAPID keys", 30, user=username)
            return result
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        sub_claim = subject()
        with _http() as client:
            for s in subs:
                try:
                    status = webpush.send(webpush.Target(s.endpoint, s.p256dh, s.auth), body, private_key=keys.private,
                                          subject=sub_claim, ttl=ttl, urgency=urgency, client=client)
                except Exception as exc:  # network, timeout, or a subscription that no longer validates
                    status, error = 0, str(exc)[:200]
                else:
                    error = ""
                if 200 <= status < 300:
                    result.sent += 1
                    repo.touch_push_subscription(username, s.id, clock.iso(clock.now()))
                    metric("PushSent", 1, Kind=kind)
                    continue
                result.failed += 1
                metric("PushFailed", 1, Kind=kind)
                if status in GONE:
                    repo.delete_push_subscription(username, s.id)
                    result.removed += 1
                log(_LOG, "push failed", 30, user=username, sub=s.id, status=status, error=error,
                    removed=status in GONE)
    except Exception as exc:
        result.failed += 1
        metric("PushFailed", 1, Kind=kind)
        log(_LOG, "push error", 40, user=username, error=str(exc)[:300])
    return result


def approval_payload(alert: Alert, token: str, url: str, minutes: int) -> dict[str, Any]:
    drill = bool(alert.decision_trace.get("drill"))
    flag = " [अभ्यास DRILL]" if drill else ""
    text = " ".join((alert.text_hi or "").split())
    snippet = text if len(text) <= BODY_CHARS else text[:BODY_CHARS].rstrip() + "…"
    return {
        "kind": "approval",
        "title": f"पुकार{flag}: {alert.village_name_hi} {hi.LEVEL_HI.get(alert.level, alert.level)}",
        "body": f"{snippet}\n{minutes} मिनट में मंज़ूरी दें · Approve within {minutes} min",
        "tag": alert.id,
        "renotify": True,
        "requireInteraction": True,
        "actions": [{"action": "approve", "title": APPROVE_TITLE}, {"action": "decline", "title": DECLINE_TITLE}],
        "data": {"url": url, "alert_id": alert.id, "token": token, "drill": drill},
    }


def notify_approval(repo: Repo, alert: Alert, officer: str, token: str, url: str) -> PushResult:
    """ask_officer: push the approval request to this officer's phones. Live alerts only: a replay
    never reaches a real device. Drills go out, labelled as drills."""
    if alert.replay:
        return PushResult()
    try:
        s = get_settings()
        minutes = max(1, round(s.approval_timeout_seconds / 60))
        payload = approval_payload(alert, token, url, minutes)
    except Exception as exc:
        metric("PushFailed", 1, Kind="approval")
        log(_LOG, "push payload error", 40, alert_id=alert.id, error=str(exc)[:300])
        return PushResult(failed=1)
    return send_to_user(repo, officer, payload, ttl=s.approval_timeout_seconds)


def send_test(repo: Repo, username: str) -> PushResult:
    web = get_settings().web_url
    payload = {
        "kind": "test",
        "title": "पुकार: जाँच सूचना · Test notification",
        "body": "यह फ़ोन मंज़ूरी की सूचनाएँ पाएगा। This phone will get approval alerts.",
        "tag": "pukaar-test",
        "renotify": True,
        "requireInteraction": False,
        "actions": [],
        "data": {"url": f"{web}/console"},
    }
    return send_to_user(repo, username, payload, ttl=300, urgency="normal", kind="test")
