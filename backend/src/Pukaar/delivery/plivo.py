"""Plivo adapter (fallback): an outbound call whose answer is a GetDigits menu.

    POST https://api.plivo.com/v1/Account/<auth id>/Call/   (HTTP Basic: auth id, auth token)
      {from, to, answer_url, answer_method: POST, hangup_url, hangup_method: POST,
       ring_timeout, machine_detection: "hangup", time_limit}
    -> 201 {"message": "call fired", "request_uuid": "...", "api_id": "..."}

    POST /voice/plivo/answer?k=..&c=..   -> <GetDigits numDigits=1 retries=1 validDigits=123> alert + menu
    POST /voice/plivo/digits?k=..&c=..   -> thank you, or <Redirect> back to answer for "3"
    POST /voice/plivo/hangup?k=..&c=..   -> the call's end status (CallStatus, HangupCause, Machine)

Every Plivo webhook carries X-Plivo-Signature-V3 and X-Plivo-Signature-V3-Nonce: HMAC-SHA256 with
the auth token over the URL, the sorted POST parameters and the nonce (validate_v3 below follows
plivo-python's utils.validate_v3_signature). Plain httpx, no SDK. Credentials from SSM
SecureString: plivo_auth_id, plivo_auth_token, plivo_caller_id.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from xml.sax.saxutils import escape, quoteattr

import httpx

from Pukaar.core.config import get_settings
from Pukaar.core.secrets import get_secret
from Pukaar.delivery.voice import CallAttempt, VoiceError, VoiceUnavailable, callback_url, http_client, mask
from Pukaar.store.models import Alert, Recipient
from Pukaar.templates import hi

API = "https://api.plivo.com/v1"
CALL_TIME_LIMIT_SECONDS = 300


@dataclass(frozen=True)
class PlivoCredentials:
    auth_id: str
    auth_token: str
    caller_id: str


def credentials() -> PlivoCredentials | None:
    values = {n: get_secret(f"plivo_{n}") for n in ("auth_id", "auth_token", "caller_id")}
    if not all(values.values()):
        return None
    return PlivoCredentials(**values)  # type: ignore[arg-type]


def from_secrets(client: httpx.Client | None = None) -> "Plivo":
    creds = credentials()
    if creds is None:
        raise VoiceUnavailable("Plivo credentials unavailable (SSM /pukaar/plivo_auth_id, plivo_auth_token, "
                               "plivo_caller_id not all set, or SSM could not be read)")
    return Plivo(creds, client=client)


class Plivo:
    name = "plivo"

    def __init__(self, creds: PlivoCredentials, *, client: httpx.Client | None = None) -> None:
        self.creds = creds
        self.client = client

    def request(self, recipient: Recipient, token: str) -> tuple[str, dict[str, Any]]:
        s = get_settings()
        body = {
            "from": self.creds.caller_id.lstrip("+"),
            "to": (recipient.phone or "").lstrip("+"),
            "answer_url": callback_url("/voice/plivo/answer", token),
            "answer_method": "POST",
            "hangup_url": callback_url("/voice/plivo/hangup", token),
            "hangup_method": "POST",
            "ring_timeout": s.voice_ring_timeout_seconds,
            "machine_detection": "hangup",
            "time_limit": CALL_TIME_LIMIT_SECONDS,
        }
        return f"{API}/Account/{self.creds.auth_id}/Call/", body

    def place_call(self, recipient: Recipient, alert: Alert, audio_url: str | None, token: str,
                   attempt: int) -> CallAttempt:
        """audio_url is not sent: the answer XML is built when Plivo asks for it (/voice/plivo/answer)."""
        url, body = self.request(recipient, token)
        client, owned = (self.client, False) if self.client is not None else http_client()
        try:
            r = client.post(url, json=body, auth=(self.creds.auth_id, self.creds.auth_token))
        except httpx.HTTPError as exc:
            raise VoiceError(f"Plivo unreachable: {type(exc).__name__}", "provider_error") from exc
        finally:
            if owned:
                client.close()
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code >= 400:
            message = mask(str(data.get("error") or data or r.status_code))[:160]
            category = "invalid_number" if r.status_code == 400 and "number" in message.lower() else "provider_error"
            raise VoiceError(f"Plivo {r.status_code}: {message}", category)
        request_uuid = data.get("request_uuid")
        if isinstance(request_uuid, list):
            request_uuid = request_uuid[0] if request_uuid else None
        if not request_uuid:
            raise VoiceError(f"Plivo answered {r.status_code} without a request_uuid", "provider_error")
        return CallAttempt("plivo", str(request_uuid), "queued", attempt)


# -- signature (X-Plivo-Signature-V3) -------------------------------------------------------------
def _sorted_query(params: Mapping[str, Any]) -> str:
    return "&".join(f"{k}={v}" for k in sorted(params) for v in _values(params[k]))


def _sorted_body(params: Mapping[str, Any]) -> str:
    return "".join(f"{k}{v}" for k in sorted(params) for v in _values(params[k]))


def _values(v: Any) -> list[str]:
    return sorted(str(x) for x in v) if isinstance(v, (list, tuple)) else [str(v)]


def base_string(method: str, url: str, params: Mapping[str, Any] | None = None) -> str:
    parts = urlsplit(url)
    base = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    query: dict[str, list[str]] = {}
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        query.setdefault(k, []).append(v)
    params = dict(params or {})
    if method.upper() == "GET":
        for k, v in params.items():
            query.setdefault(k, []).extend(_values(v))
        q = _sorted_query(query)
        return f"{base}?{q}" if q else base
    q = _sorted_query(query)
    out = f"{base}?{q}" if q else base
    if params:
        out += ("." if q else "") + _sorted_body(params)
    return out


def signature(auth_token: str, method: str, url: str, params: Mapping[str, Any] | None, nonce: str) -> str:
    msg = f"{base_string(method, url, params)}.{nonce}".encode()
    return base64.b64encode(hmac.new(auth_token.encode(), msg, hashlib.sha256).digest()).decode()


def validate_v3(auth_token: str, method: str, url: str, params: Mapping[str, Any] | None, nonce: str,
                header: str) -> bool:
    if not (auth_token and nonce and header):
        return False
    expected = signature(auth_token, method, url, params, nonce)
    return any(hmac.compare_digest(expected, s.strip()) for s in header.split(","))


# -- answer XML ----------------------------------------------------------------------------------
def _say(audio_url: str | None, text: str) -> str:
    if audio_url:
        return f"<Play>{escape(audio_url)}</Play>"
    return f'<Speak language="hi-IN" voice="Polly.Aditi">{escape(text)}</Speak>'


def answer_xml(*, audio_url: str | None, text_hi: str, menu_url: str | None, digits_url: str,
               menu_text: str = hi.VOICE_MENU_HI, valid_digits: str = "123") -> str:
    """The alert, then "press 1, 2 or 3": silence or a wrong key is asked again once (retries=1).
    The officer's wake-up call (delivery/officer_call.py) passes its own menu and only "1"."""
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<GetDigits action={quoteattr(digits_url)} method="POST" numDigits="1" timeout="8" retries="1" '
            f'validDigits={quoteattr(valid_digits)} playBeep="false" redirect="true">'
            f"{_say(audio_url, text_hi)}{_say(menu_url, menu_text)}</GetDigits>"
            f"{_say(None, hi.VOICE_GOODBYE_HI)}<Hangup/></Response>")


def end_xml(text_hi: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{_say(None, text_hi)}<Hangup/></Response>'


def redirect_xml(answer_url: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Redirect method="POST">{escape(answer_url)}</Redirect></Response>'
