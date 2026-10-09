"""Telegram Bot API calls (sendMessage, sendAudio with an inline acknowledge button)."""

from __future__ import annotations

from typing import Any

import httpx

from Pukaar.core.secrets import get_secret
from Pukaar.templates import hi

API = "https://api.telegram.org"


class TelegramError(RuntimeError):
    pass


def configured() -> bool:
    return bool(get_secret("telegram_token"))


def _call(method: str, payload: dict[str, Any] | None = None, files: dict | None = None) -> dict:
    token = get_secret("telegram_token")
    if not token:
        raise TelegramError("telegram token not configured")
    with httpx.Client(timeout=15) as client:
        if files:
            r = client.post(f"{API}/bot{token}/{method}", data=payload, files=files)
        else:
            r = client.post(f"{API}/bot{token}/{method}", json=payload)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not body.get("ok"):
        raise TelegramError(f"{method} failed: {body.get('description', r.status_code)}")
    return body["result"]


def ack_keyboard(alert_id: str) -> dict:
    return {"inline_keyboard": [[{"text": f"✅ {hi.ACK_BUTTON_HI}", "callback_data": f"ack:{alert_id}"}]]}


def send_alert(chat_id: str, alert_id: str, text_hi: str, audio: bytes | None) -> None:
    markup = ack_keyboard(alert_id)
    if audio:
        import json

        _call("sendAudio", {"chat_id": chat_id, "caption": text_hi[:1000], "reply_markup": json.dumps(markup),
                            "title": "पुकार"}, files={"audio": ("pukaar.mp3", audio, "audio/mpeg")})
    else:
        _call("sendMessage", {"chat_id": chat_id, "text": text_hi, "reply_markup": markup})


def send_text(chat_id: str, text: str) -> None:
    _call("sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True})


def answer_callback(callback_id: str, text: str) -> None:
    _call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
