"""Signed one-tap links.

HMAC-SHA256 over a compact JSON body {a: alert id, o: officer or recipient,
v: token_version, e: expiry, k: kind}, base64url, constant-time compare.
Approval links are single use: the approval route consumes them with a
conditional update on token_version (store/repo.consume_task_token).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from Pukaar.core.secrets import get_secret

APPROVAL_TTL_SECONDS = 30 * 60
ACK_TTL_SECONDS = 3 * 24 * 3600


class TokenError(ValueError):
    pass


@dataclass(frozen=True)
class LinkToken:
    alert_id: str
    subject: str  # officer username or recipient id
    version: int
    expires: int
    kind: str  # "approve" or "ack"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _key() -> bytes:
    secret = get_secret("link_secret", generate_locally=True)
    if not secret:
        raise TokenError("link secret unavailable")
    return secret.encode()


def sign(alert_id: str, subject: str, version: int, kind: str, ttl: int | None = None, now: float | None = None) -> str:
    ttl = ttl if ttl is not None else (APPROVAL_TTL_SECONDS if kind == "approve" else ACK_TTL_SECONDS)
    body = json.dumps({"a": alert_id, "o": subject, "v": version, "e": int((now or time.time()) + ttl), "k": kind},
                      separators=(",", ":")).encode()
    mac = hmac.new(_key(), body, hashlib.sha256).digest()
    return f"{_b64(body)}.{_b64(mac)}"


def verify(token: str, kind: str, now: float | None = None) -> LinkToken:
    try:
        body_b64, mac_b64 = token.split(".", 1)
        body = _unb64(body_b64)
        mac = _unb64(mac_b64)
    except Exception as exc:
        raise TokenError("malformed token") from exc
    if not hmac.compare_digest(hmac.new(_key(), body, hashlib.sha256).digest(), mac):
        raise TokenError("bad signature")
    data = json.loads(body)
    if data.get("k") != kind:
        raise TokenError("wrong token kind")
    if int(data["e"]) < (now or time.time()):
        raise TokenError("expired")
    return LinkToken(str(data["a"]), str(data["o"]), int(data["v"]), int(data["e"]), str(data["k"]))
