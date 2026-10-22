"""Voice calls with "press 1": the provider-neutral side (docs/VOICE.md).

No AWS service places calls to Indian numbers, so a call goes through Exotel (delivery/exotel.py)
or Plivo (delivery/plivo.py), chosen by PUKAAR_VOICE_PROVIDER ("exotel", "plivo" or "off", the
default). The call plays the alert's Polly audio, then asks for one key:

    1  मिल गया (heard)       the delivery is acknowledged, exactly as the Telegram button
    2  मदद चाहिए (need help)  acknowledged, plus a need-help item (roll-call answer or SOS report)
    3  दोबारा सुनें (repeat)   the message plays again (at most twice)

An invalid key is asked again once, then the call ends. Silence is re-prompted once by the
provider's own menu, then the call ends.

Honesty rules, as for Telegram:
- Provider off, credentials missing or the webhook key missing: the delivery is FAILED with the
  reason. Nothing is ever recorded as a call that was not placed.
- The stub provider answers for replays only and says so (provider "stub", call_status
  "simulated"). place_call() never dials for a replay alert, whatever the caller passes.

Webhooks are authenticated twice: a static key in the URL (SSM voice_webhook_key) and a per-call
token (sign_call) carried in Exotel's CustomField or the Plivo URL, which names the alert, the
person and the attempt and is HMAC-signed with the link secret. Plivo's own request signature is
checked as well. The call id in a webhook must be one Pukaar placed for that person.

Phone numbers are never written to a log: errors from a provider pass through mask().
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

from Pukaar.core.config import get_settings
from Pukaar.core.secrets import get_secret
from Pukaar.store.models import Alert, Recipient

PROVIDERS = ("exotel", "plivo")
# Categories after which another call may still help ("not connected" counter).
NOT_CONNECTED = {"busy", "no_answer", "failed", "no_status", "provider_error", "machine"}
# Categories after which calling again cannot help: the person is flagged, or the owner must act.
TERMINAL = {"invalid_number", "provider_off", "blocked"}
FINAL_CALL_STATUSES = {"completed", "busy", "no_answer", "failed", "simulated"}
MAX_REPEATS = 2  # "3" plays the message again at most this many times per call
MAX_REPROMPTS = 1  # an invalid key is asked again once, then the call ends
IN_PROGRESS_GRACE_SECONDS = 180  # a call placed this recently with no final status is still ringing
TOKEN_TTL_HOURS = 48
EXOTEL_CUSTOMFIELD_MAX = 128


class VoiceError(RuntimeError):
    """A call that was not placed. category is a Delivery.error_category."""

    def __init__(self, message: str, category: str = "provider_error") -> None:
        super().__init__(mask(message))
        self.category = category


class VoiceUnavailable(VoiceError):
    """Voice is off or not configured: never retried, counted in DeliveryFailed (alarmed)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "provider_off")


@dataclass(frozen=True)
class CallAttempt:
    provider: str  # exotel | plivo | stub
    call_id: str | None
    status: str  # queued, or simulated for the replay stub
    attempt: int
    simulated: bool = False
    note: str = ""


class Provider(Protocol):
    name: str

    def place_call(self, recipient: Recipient, alert: Alert, audio_url: str | None, token: str,
                   attempt: int) -> CallAttempt: ...


_HTTP = None  # tests: an httpx.Client with a recorded or fake transport (set_http_client)


def set_http_client(client) -> None:
    global _HTTP
    _HTTP = client


def http_client():
    """(client, owned): the test client when set, else a new one the caller closes."""
    import httpx

    return (_HTTP, False) if _HTTP is not None else (httpx.Client(timeout=15), True)


# -- privacy -----------------------------------------------------------------------------------
_NUMBER = re.compile(r"\+?\d[\d \-]{6,}\d")


def mask(text: str) -> str:
    """Hide anything that looks like a phone number (7+ digits) in a provider message."""
    return _NUMBER.sub("<number>", str(text))


def mask_phone(phone: str | None) -> str:
    return f"{phone[:3]}******{phone[-2:]}" if phone and len(phone) > 6 else "<none>"


# -- per-call token ------------------------------------------------------------------------------
@dataclass(frozen=True)
class CallToken:
    alert_id: str
    recipient_id: str
    attempt: int
    expires: int


class TokenError(ValueError):
    pass


def _key() -> bytes:
    secret = get_secret("link_secret", generate_locally=True)
    if not secret:
        raise TokenError("link secret unavailable")
    return hmac.new(secret.encode(), b"pukaar-voice-v1", hashlib.sha256).digest()


def _mac(body: str) -> str:
    return base64.urlsafe_b64encode(hmac.new(_key(), body.encode(), hashlib.sha256).digest()[:16]).rstrip(b"=").decode()


def sign_call(alert_id: str, recipient_id: str, attempt: int, *, ttl_hours: int = TOKEN_TTL_HOURS,
              now: float | None = None) -> str:
    """"v1.<alert>.<recipient>.<attempt>.<expiry, hours, base 36>.<mac>": fits Exotel's 128-character CustomField."""
    for part in (alert_id, recipient_id):
        if not part or "." in part:
            raise TokenError("ids in a call token must be non-empty and contain no '.'")
    expires = int((now or time.time()) // 3600) + ttl_hours
    body = f"v1.{alert_id}.{recipient_id}.{attempt}.{_b36(expires)}"
    token = f"{body}.{_mac(body)}"
    if len(token) > EXOTEL_CUSTOMFIELD_MAX:
        raise TokenError("call token longer than Exotel's CustomField allows")
    return token


def verify_call(token: str, now: float | None = None) -> CallToken:
    parts = (token or "").strip().strip('"').split(".")
    if len(parts) != 6 or parts[0] != "v1":
        raise TokenError("malformed call token")
    body, mac = ".".join(parts[:5]), parts[5]
    if not hmac.compare_digest(_mac(body), mac):
        raise TokenError("bad signature")
    try:
        attempt, expires = int(parts[3]), int(parts[4], 36)
    except ValueError as exc:
        raise TokenError("malformed call token") from exc
    if expires * 3600 < (now or time.time()):
        raise TokenError("expired")
    return CallToken(parts[1], parts[2], attempt, expires)


def _b36(n: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out or "0"


# -- webhook key and URLs ------------------------------------------------------------------------
def webhook_key() -> str | None:
    key = get_secret("voice_webhook_key")
    return key if key and len(key) >= 16 else None


def webhook_key_ok(given: str | None) -> bool:
    """Fails closed: with no key in SSM every voice webhook is refused."""
    key = webhook_key()
    return bool(key and given and hmac.compare_digest(key.encode(), given.encode()))


def callback_url(path: str, token: str | None = None) -> str:
    """The API URL a provider calls back, with the webhook key (and the call token)."""
    key = webhook_key()
    if not key:
        raise VoiceUnavailable("voice webhook key not set (SSM /pukaar/voice_webhook_key)")
    base = get_settings().api_url
    if not base.startswith("https://"):
        raise VoiceUnavailable(f"PUKAAR_API_URL must be an https URL the provider can reach (got {base!r})")
    query = {"k": key, **({"c": token} if token else {})}
    return f"{base}{path}?{urlencode(query)}"


# -- placing a call ------------------------------------------------------------------------------
class StubProvider:
    """Replays only. No network, no number dialled; the record says "simulated"."""

    name = "stub"

    def place_call(self, recipient: Recipient, alert: Alert, audio_url: str | None, token: str,
                   attempt: int) -> CallAttempt:
        if not alert.replay:
            raise VoiceError("the stub voice provider answers for replays only; a live alert needs a real provider",
                             "blocked")
        return CallAttempt("stub", None, "simulated", attempt, simulated=True, note="replay: no call placed")


def get_provider(alert: Alert) -> Provider:
    if alert.replay:
        return StubProvider()
    name = get_settings().voice_provider
    if name == "exotel":
        from Pukaar.delivery import exotel

        return exotel.from_secrets()
    if name == "plivo":
        from Pukaar.delivery import plivo

        return plivo.from_secrets()
    raise VoiceUnavailable("voice provider is off (PUKAAR_VOICE_PROVIDER=off): no call placed")


def place_call(recipient: Recipient, alert: Alert, audio_url: str | None, *, attempt: int = 1) -> CallAttempt:
    """Place one call, or raise VoiceError with a category. A replay alert never dials."""
    provider = get_provider(alert)
    if provider.name == "stub":
        return provider.place_call(recipient, alert, audio_url, "", attempt)
    if not recipient.phone:
        raise VoiceError("recipient has no phone number", "invalid_number")
    return provider.place_call(recipient, alert, audio_url, sign_call(alert.id, recipient.id, attempt), attempt)


# -- reading provider status -----------------------------------------------------------------------
@dataclass(frozen=True)
class CallStatus:
    call_status: str
    category: str | None  # set when the call was not connected
    answered: bool
    final: bool


def exotel_status(status: str) -> CallStatus:
    s = (status or "").strip().lower()
    if s == "completed":
        return CallStatus("completed", None, True, True)
    if s in {"in-progress", "answered"}:
        return CallStatus("answered", None, True, False)
    if s == "busy":
        return CallStatus("busy", "busy", False, True)
    if s in {"no-answer", "no_answer"}:
        return CallStatus("no_answer", "no_answer", False, True)
    if s in {"failed", "canceled", "cancelled"}:
        return CallStatus("failed", "failed", False, True)
    return CallStatus(s or "queued", None, False, False)


_INVALID_CAUSES = ("UNALLOCATED", "INVALID_NUMBER", "INVALID NUMBER", "NO_ROUTE_DESTINATION", "INVALID DESTINATION")


def plivo_status(call_status: str, hangup_cause: str = "", machine: str = "") -> CallStatus:
    s = (call_status or "").strip().lower()
    cause = (hangup_cause or "").upper()
    if machine.strip().lower() == "true":
        return CallStatus("failed", "machine", False, True)
    if any(c in cause for c in _INVALID_CAUSES):
        return CallStatus("failed", "invalid_number", False, True)
    if s == "completed":
        return CallStatus("completed", None, True, True)
    if s in {"in-progress", "answered"}:
        return CallStatus("answered", None, True, False)
    if s == "busy":
        return CallStatus("busy", "busy", False, True)
    if s in {"no-answer", "timeout"}:
        return CallStatus("no_answer", "no_answer", False, True)
    if s in {"failed", "cancel", "canceled"}:
        return CallStatus("failed", "failed", False, True)
    return CallStatus(s or "queued", None, False, False)


def clean_digit(raw: str | None) -> str:
    """Exotel sends digits wrapped in double quotes ("\\"1\\""); Plivo sends them bare."""
    return (raw or "").strip().strip('"').strip()
