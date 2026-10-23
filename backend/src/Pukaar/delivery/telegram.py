"""Telegram Bot API calls (sendMessage, sendAudio with an inline acknowledge button).

Limits (delivery/ratelimit.py): every call waits for a slot under the overall rate
(PUKAAR_TELEGRAM_RATE_PER_SECOND, 25 by default, under Telegram's ~30) and one message per chat
per PUKAAR_TELEGRAM_CHAT_INTERVAL_SECONDS. On AWS the slot also comes from one budget shared by every
Lambda (SharedBucket in DynamoDB), so two villages alerting at once share the bot's rate instead of each
taking all of it. A 429 answer pauses every sender of this process, and through the shared budget every
other Lambda, for retry_after seconds and raises TelegramRateLimited: the caller tries again or puts the
send back unsent (dispatch.py). A 429 is never a sent message.

One HTTP client per process keeps the connection open: thousands of sends do not each pay a TLS
handshake. The alert audio is uploaded once; later sends pass the file id Telegram gave back.
"""

from __future__ import annotations

import contextvars
import json
import threading
from typing import Any

import httpx

from Pukaar.core.config import get_settings
from Pukaar.core.secrets import get_secret
from Pukaar.delivery.ratelimit import RateLimiter, SharedBucket
from Pukaar.templates import hi

API = "https://api.telegram.org"


class TelegramError(RuntimeError):
    pass


class TelegramRateLimited(TelegramError):
    """429 Too Many Requests: nothing was sent; wait retry_after seconds."""

    def __init__(self, method: str, retry_after: float) -> None:
        super().__init__(f"{method}: rate limited by Telegram (retry after {retry_after:g} s)")
        self.retry_after = retry_after


class TelegramDeferred(TelegramError):
    """No send slot before the caller's deadline: nothing was sent."""


_lock = threading.Lock()
_client: httpx.Client | None = None
_transport: httpx.BaseTransport | None = None  # tests: a fake Telegram server
_limiter: RateLimiter | None = None
# Set per thread by dispatch.py around a delivery round: the round's own limiter (its share of the overall
# rate, as one batch worker is one Lambda), and the time (time.monotonic) after which a send is put back
# instead of waiting for a slot. Anything else (officer messages, roll-calls) uses the process limiter.
send_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar("telegram_send_deadline", default=None)
send_limiter: contextvars.ContextVar[RateLimiter | None] = contextvars.ContextVar("telegram_send_limiter",
                                                                                   default=None)


def configured() -> bool:
    return bool(get_secret("telegram_token"))


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Tests: route every call to a fake server (None: the real one). Resets the client and the limiter."""
    global _client, _transport, _limiter, _shared
    with _lock:
        if _client is not None:
            _client.close()
        _client, _transport, _limiter, _shared = None, transport, None, None


_shared: SharedBucket | None = None


def shared_bucket() -> SharedBucket | None:
    """The bot's one budget across every Lambda (delivery/ratelimit.SharedBucket), or None when
    PUKAAR_TELEGRAM_SHARED_LIMIT is off (local mode, tests)."""
    global _shared
    s = get_settings()
    if not s.telegram_shared_limit:
        return None
    with _lock:
        if _shared is None:
            from Pukaar.store.repo import get_repo

            _shared = SharedBucket(get_repo(), "telegram", s.telegram_rate_per_second)
        return _shared


def limiter() -> RateLimiter:
    global _limiter
    bucket = shared_bucket()
    with _lock:
        if _limiter is None:
            s = get_settings()
            _limiter = RateLimiter(s.telegram_rate_per_second, per_key_interval=s.telegram_chat_interval_seconds,
                                   shared=bucket)
        return _limiter


def _http() -> httpx.Client:
    global _client
    with _lock:
        if _client is None:
            _client = httpx.Client(timeout=15, transport=_transport,
                                   limits=httpx.Limits(max_connections=64, max_keepalive_connections=64))
        return _client


def _call(method: str, payload: dict[str, Any] | None = None, files: dict | None = None) -> dict:
    token = get_secret("telegram_token")
    if not token:
        raise TelegramError("telegram token not configured")
    chat = str((payload or {}).get("chat_id") or "") or None
    slots = send_limiter.get() or limiter()
    if not slots.acquire(chat, deadline=send_deadline.get()):
        raise TelegramDeferred(f"{method}: no send slot before the deadline")
    url = f"{API}/bot{token}/{method}"
    try:
        r = _http().post(url, data=payload, files=files) if files else _http().post(url, json=payload)
    except httpx.HTTPError as exc:
        raise TelegramError(f"{method} failed: {type(exc).__name__}") from None
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code == 429 or body.get("error_code") == 429:
        retry_after = float((body.get("parameters") or {}).get("retry_after") or 1)
        slots.pause(retry_after)
        raise TelegramRateLimited(method, retry_after)
    if not body.get("ok"):
        raise TelegramError(f"{method} failed: {body.get('description', r.status_code)}")
    return body["result"]


def ack_keyboard(alert_id: str) -> dict:
    return {"inline_keyboard": [[{"text": f"✅ {hi.ACK_BUTTON_HI}", "callback_data": f"ack:{alert_id}"}]]}


def send_alert(chat_id: str, alert_id: str, text_hi: str, audio: bytes | str | None) -> dict | None:
    """audio: the MP3 bytes (uploaded) or the file id of an earlier upload (sent by reference).
    Returns Telegram's message; its audio.file_id serves every later send of this alert."""
    markup = ack_keyboard(alert_id)
    if audio:
        fields = {"chat_id": chat_id, "caption": text_hi[:1000], "title": "पुकार"}
        if isinstance(audio, str):  # by reference: no upload
            return _call("sendAudio", {**fields, "reply_markup": markup, "audio": audio})
        return _call("sendAudio", {**fields, "reply_markup": json.dumps(markup)},
                     files={"audio": ("pukaar.mp3", audio, "audio/mpeg")})
    return _call("sendMessage", {"chat_id": chat_id, "text": text_hi, "reply_markup": markup})


def audio_file_id(message: Any) -> str | None:
    audio = message.get("audio") if isinstance(message, dict) else None
    return str(audio["file_id"]) if isinstance(audio, dict) and audio.get("file_id") else None


def send_text(chat_id: str, text: str) -> None:
    _call("sendMessage", {"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": True})


def consent_keyboard(village_id: str) -> dict:
    """"I agree" / "No" under the enrolment notice; callback data stays under Telegram's 64 bytes."""
    return {"inline_keyboard": [[
        {"text": hi.CONSENT_BUTTON, "callback_data": f"consent:{village_id}"[:64]},
        {"text": hi.DECLINE_BUTTON, "callback_data": "noconsent"},
    ]]}


def demo_consent_keyboard(code: str) -> dict:
    """The live jury demo's "I agree" / "No" (services/demo.py): the button names the join code, not a village."""
    return {"inline_keyboard": [[
        {"text": hi.CONSENT_BUTTON, "callback_data": f"dconsent:{code}"[:64]},
        {"text": hi.DECLINE_BUTTON, "callback_data": "noconsent"},
    ]]}


def send_demo_consent(chat_id: str, code: str, text: str) -> None:
    _call("sendMessage", {"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": True,
                          "reply_markup": demo_consent_keyboard(code)})


def send_consent(chat_id: str, village_id: str, text: str) -> None:
    _call("sendMessage", {"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": True,
                          "reply_markup": consent_keyboard(village_id)})


def answer_callback(callback_id: str, text: str) -> None:
    _call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def rollcall_keyboard(rollcall_id: str) -> dict:
    """Two buttons; callback data stays far under Telegram's 64-byte limit."""
    return {"inline_keyboard": [[
        {"text": f"✅ {hi.ROLLCALL_SAFE_BUTTON_HI}", "callback_data": f"safe:{rollcall_id}"},
        {"text": f"🆘 {hi.ROLLCALL_HELP_BUTTON_HI}", "callback_data": f"help:{rollcall_id}"},
    ]]}


def send_rollcall(chat_id: str, rollcall_id: str, text: str) -> None:
    _call("sendMessage", {"chat_id": chat_id, "text": text, "reply_markup": rollcall_keyboard(rollcall_id)})
