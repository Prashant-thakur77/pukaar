"""Web Push without a push library: RFC 8291 message encryption (aes128gcm, RFC 8188)
and RFC 8292 VAPID (an ES256 JWT), over httpx.

Written here instead of adding pywebpush because pywebpush 2.x pulls aiohttp and its
compiled dependencies into every Lambda image; `cryptography` and `pyjwt` are already
there. tests/test_push.py checks encrypt() byte for byte against RFC 8291 Appendix A.

Keys use the format browsers and every Web Push library share: the private key is the
32-byte P-256 scalar and the public key the 65-byte uncompressed point, both base64url.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RECORD_SIZE = 4096
# One aes128gcm record: header (86 bytes) + payload + 1 delimiter + 16 tag must fit what push
# services accept (4096 bytes of body); 3800 leaves room and keeps every message one record.
MAX_PAYLOAD = 3800
JWT_LIFETIME_SECONDS = 12 * 3600  # RFC 8292: at most 24 hours

# Push services the browsers use. A subscription's endpoint must be https on one of these, so a
# signed-in user cannot point the workflow Lambda's POSTs at an arbitrary host.
PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com",            # Chrome, Edge on Android, Samsung Internet, Opera
    "android.googleapis.com",        # older Chrome subscriptions
    "push.services.mozilla.com",     # Firefox (updates.push.services.mozilla.com)
    "notify.windows.com",            # Edge on Windows (wns2-*.notify.windows.com)
    "push.apple.com",                # Safari and iOS home-screen apps (web.push.apple.com)
)


class PushError(ValueError):
    pass


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    text = text.strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def _point(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def public_key_from_bytes(raw: bytes) -> ec.EllipticCurvePublicKey:
    if len(raw) != 65 or raw[0] != 4:
        raise PushError("p256dh must be a 65-byte uncompressed P-256 point")
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError as exc:
        raise PushError("p256dh is not a point on P-256") from exc


def private_key_from_text(text: str) -> ec.EllipticCurvePrivateKey:
    """base64url raw scalar (what scripts/vapid_keys.py stores), or a PEM key."""
    text = text.strip()
    if text.startswith("-----BEGIN"):
        key = serialization.load_pem_private_key(text.encode(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise PushError("VAPID key is not an EC key")
        return key
    raw = unb64u(text)
    if len(raw) != 32:
        raise PushError("VAPID private key must be 32 bytes")
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


def private_key_text(key: ec.EllipticCurvePrivateKey) -> str:
    return b64u(key.private_numbers().private_value.to_bytes(32, "big"))


def public_key_text(key: ec.EllipticCurvePrivateKey | ec.EllipticCurvePublicKey) -> str:
    pub = key.public_key() if isinstance(key, ec.EllipticCurvePrivateKey) else key
    return b64u(_point(pub))


def generate_keys() -> tuple[str, str]:
    """(private, public) as base64url."""
    key = ec.generate_private_key(ec.SECP256R1())
    return private_key_text(key), public_key_text(key)


def encrypt(plaintext: bytes, ua_public: bytes, auth_secret: bytes, *,
            salt: bytes | None = None, as_private: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """RFC 8291 section 3.4: one aes128gcm record. salt and as_private are for the RFC test vector only;
    in use both are fresh for every message."""
    if len(auth_secret) != 16:
        raise PushError("auth secret must be 16 bytes")
    if len(plaintext) > MAX_PAYLOAD:
        raise PushError("payload too large")
    salt = salt if salt is not None else os.urandom(16)
    as_private = as_private or ec.generate_private_key(ec.SECP256R1())
    as_public = _point(as_private.public_key())
    ecdh_secret = as_private.exchange(ec.ECDH(), public_key_from_bytes(ua_public))
    prk_key = _hmac(auth_secret, ecdh_secret)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    ciphertext = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)  # 0x02: last (and only) record
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + ciphertext


def decrypt(body: bytes, ua_private: ec.EllipticCurvePrivateKey, auth_secret: bytes) -> bytes:
    """The browser's side, for tests and the local check: undo encrypt()."""
    salt, idlen = body[:16], body[20]
    as_public = body[21:21 + idlen]
    ua_public = _point(ua_private.public_key())
    ecdh_secret = ua_private.exchange(ec.ECDH(), public_key_from_bytes(as_public))
    prk_key = _hmac(auth_secret, ecdh_secret)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    padded = AESGCM(cek).decrypt(nonce, body[21 + idlen:], None)
    return padded.rstrip(b"\x00")[:-1]


def audience(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    return f"{parts.scheme}://{parts.netloc}"


def check_endpoint(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or len(endpoint) > 1024:
        raise PushError("endpoint must be an https URL")
    if not any(host == s or host.endswith("." + s) for s in PUSH_HOST_SUFFIXES):
        raise PushError("endpoint is not a known browser push service")
    return endpoint


def vapid_header(endpoint: str, private_key: ec.EllipticCurvePrivateKey, subject: str, now: float | None = None) -> str:
    claims = {"aud": audience(endpoint), "exp": int((now or time.time()) + JWT_LIFETIME_SECONDS), "sub": subject}
    token = jwt.encode(claims, private_key, algorithm="ES256", headers={"typ": "JWT"})
    return f"vapid t={token}, k={public_key_text(private_key)}"


@dataclass(frozen=True)
class Target:
    endpoint: str
    p256dh: str
    auth: str


def send(target: Target, payload: bytes, *, private_key: ec.EllipticCurvePrivateKey, subject: str, ttl: int,
         urgency: str = "high", client: httpx.Client | None = None, timeout: float = 6.0) -> int:
    """POST one encrypted message; returns the push service's HTTP status (201 is success).
    Raises PushError for a bad subscription and httpx errors for the network."""
    check_endpoint(target.endpoint)
    body = encrypt(payload, unb64u(target.p256dh), unb64u(target.auth))
    headers = {
        "Authorization": vapid_header(target.endpoint, private_key, subject),
        "TTL": str(max(0, int(ttl))),
        "Urgency": urgency,
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
    }
    if client is not None:
        return client.post(target.endpoint, content=body, headers=headers, timeout=timeout).status_code
    with httpx.Client(timeout=timeout) as c:
        return c.post(target.endpoint, content=body, headers=headers).status_code
