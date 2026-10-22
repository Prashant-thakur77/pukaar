"""Exotel adapter (India): connect a number to a call flow built in Exotel's App Bazaar.

    POST https://<api host>/v1/Accounts/<sid>/Calls/connect.json   (HTTP Basic: API key, API token)
      From=<recipient, E.164>  CallerId=<ExoPhone>  Url=http://my.exotel.com/<sid>/exoml/start_voice/<app id>
      CallType=trans  TimeOut=<ring seconds>  TimeLimit=300  CustomField=<signed call token>
      StatusCallback=<API>/voice/exotel/status?k=..&c=..  StatusCallbackEvents[0]=terminal  [1]=answered

The flow (docs/VOICE.md, "The Exotel flow"):
    Greeting  dynamic URL  GET /voice/exotel/flow?k=..&part=greeting   -> the alert MP3 URL (text/plain)
    Gather    dynamic URL  GET /voice/exotel/flow?k=..&part=menu       -> the "press 1, 2 or 3" menu (JSON)
    Passthru               GET /voice/exotel/gather?k=..               -> 200: end the call, 302: play again
Exotel sends CallSid, CustomField and, after a Gather, digits ("\\"1\\"", in double quotes).

Plain httpx, no SDK. Credentials from SSM SecureString: exotel_sid, exotel_token, exotel_caller_id,
exotel_app_id, and exotel_api_key (optional: older accounts sign in with the SID itself).
Exotel does not sign its webhooks, so they are checked by the URL key and the signed CustomField.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from Pukaar.core.config import get_settings
from Pukaar.core.secrets import get_secret
from Pukaar.delivery.voice import CallAttempt, VoiceError, VoiceUnavailable, callback_url, http_client, mask
from Pukaar.store.models import Alert, Recipient

CALL_TIME_LIMIT_SECONDS = 300


@dataclass(frozen=True)
class ExotelCredentials:
    sid: str
    api_key: str
    token: str
    caller_id: str
    app_id: str


def credentials() -> ExotelCredentials | None:
    values = {n: get_secret(f"exotel_{n}") or "" for n in ("sid", "token", "caller_id", "app_id")}
    if not all(values.values()):
        return None
    return ExotelCredentials(api_key=get_secret("exotel_api_key") or values["sid"], **values)


def from_secrets(client: httpx.Client | None = None) -> "Exotel":
    creds = credentials()
    if creds is None:
        raise VoiceUnavailable("Exotel credentials unavailable (SSM /pukaar/exotel_sid, exotel_token, "
                               "exotel_caller_id, exotel_app_id not all set, or SSM could not be read)")
    return Exotel(creds, client=client)


def flow_url(sid: str, app_id: str) -> str:
    return f"http://my.exotel.com/{sid}/exoml/start_voice/{app_id}"


class Exotel:
    name = "exotel"

    def __init__(self, creds: ExotelCredentials, *, client: httpx.Client | None = None, host: str | None = None) -> None:
        self.creds = creds
        self.client = client
        self.host = host or get_settings().exotel_api_host

    def request(self, recipient: Recipient, token: str) -> tuple[str, dict[str, Any]]:
        """The URL and form fields of the Calls/connect request (no secret in either)."""
        s = get_settings()
        data = {
            "From": recipient.phone,
            "CallerId": self.creds.caller_id,
            "Url": flow_url(self.creds.sid, self.creds.app_id),
            "CallType": "trans",
            "TimeOut": str(s.voice_ring_timeout_seconds),
            "TimeLimit": str(CALL_TIME_LIMIT_SECONDS),
            "CustomField": token,
            "StatusCallback": callback_url("/voice/exotel/status", token),
            "StatusCallbackEvents[0]": "terminal",
            "StatusCallbackEvents[1]": "answered",
        }
        return f"https://{self.host}/v1/Accounts/{self.creds.sid}/Calls/connect.json", data

    def place_call(self, recipient: Recipient, alert: Alert, audio_url: str | None, token: str,
                   attempt: int) -> CallAttempt:
        """audio_url is not sent: the flow's Greeting fetches the alert audio from /voice/exotel/flow."""
        url, data = self.request(recipient, token)
        client, owned = (self.client, False) if self.client is not None else http_client()
        try:
            r = client.post(url, data=data, auth=(self.creds.api_key, self.creds.token))
        except httpx.HTTPError as exc:
            raise VoiceError(f"Exotel unreachable: {type(exc).__name__}", "provider_error") from exc
        finally:
            if owned:
                client.close()
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 400:
            raise _error(r.status_code, body)
        call = body.get("Call") or {}
        sid = call.get("Sid")
        if not sid:
            raise VoiceError(f"Exotel answered {r.status_code} without a call Sid", "provider_error")
        return CallAttempt("exotel", str(sid), "queued", attempt)


def _error(status: int, body: dict) -> VoiceError:
    exc = body.get("RestException") or {}
    message = mask(str(exc.get("Message") or exc.get("message") or body or status))[:160]
    text = message.lower()
    if status in {400, 404} and ("number" in text or "invalid" in text or "not a valid" in text):
        return VoiceError(f"Exotel {status}: {message}", "invalid_number")
    if status == 403 and ("verif" in text or "trial" in text or "dnd" in text):
        # Trial accounts call verified numbers only; NDNC-registered numbers refuse promotional calls.
        return VoiceError(f"Exotel {status}: {message}", "blocked")
    return VoiceError(f"Exotel {status}: {message}", "provider_error")
