"""Telegram webhook: /start <village id> registers a recipient; /start link_<code>
links an officer's chat using a one-time code from the signed-in console
(POST /me/telegram-link); the "मिल गया" button records an acknowledgement;
the roll-call buttons (safe:<id>, help:<id>) record "I am safe" or "I need help",
and the next plain message after "need help" is kept as a short note."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException, Request

from Pukaar.core.log import get_logger, log
from Pukaar.core.secrets import get_secret
from Pukaar.delivery import dispatch, telegram
from Pukaar.services import rollcall
from Pukaar.store.models import Recipient
from Pukaar.store.repo import Repo, get_repo
from Pukaar.templates import hi

router = APIRouter()
_LOG = get_logger("telegram")


def _send(chat_id: str, text: str) -> None:
    try:
        telegram.send_text(chat_id, text)
    except Exception as exc:  # the answer is already stored; a failed reply must not make Telegram retry
        log(_LOG, "reply failed", 30, error=str(exc)[:200])


def _rollcall_answer(repo: Repo, callback_id: str, chat_id: str, data: str) -> None:
    """"✅ मैं सुरक्षित हूँ" (safe:<id>) or "🆘 मदद चाहिए" (help:<id>). Idempotent; the last answer wins."""
    status = "safe" if data.startswith("safe:") else "need_help"
    res = rollcall.answer(repo, data[5:], chat_id, status)
    toast = {
        "recorded": hi.ROLLCALL_SAFE_THANKS_HI if status == "safe" else hi.ROLLCALL_HELP_THANKS_HI,
        "same": hi.ROLLCALL_SAME_HI,
        "closed": hi.ROLLCALL_CLOSED_HI,
    }.get(res.outcome, hi.ROLLCALL_NOT_ASKED_HI)
    try:
        telegram.answer_callback(callback_id, toast)
    except Exception as exc:
        log(_LOG, "callback answer failed", 30, error=str(exc)[:200])
    if res.outcome != "recorded":
        return
    if status == "safe" and res.share_link:
        _send(chat_id, hi.rollcall_safe_reply(res.share_link))
    elif status == "need_help" and res.rollcall is not None:
        repo.put_help_note_wait(chat_id, res.rollcall.id)
        _send(chat_id, hi.ROLLCALL_HELP_REPLY)


@router.post("/telegram/webhook")
async def webhook(request: Request, x_telegram_bot_api_secret_token: str = Header("")) -> dict:
    secret = get_secret("telegram_webhook_secret")
    if not secret or not hmac.compare_digest(secret, x_telegram_bot_api_secret_token):
        raise HTTPException(403, "bad secret")
    update = await request.json()
    repo = get_repo()

    if "callback_query" in update:
        cq = update["callback_query"]
        data = str(cq.get("data", ""))
        chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
        if data.startswith("ack:") and chat_id:
            d = dispatch.acknowledge(repo, data[4:], chat_id)
            telegram.answer_callback(cq["id"], "धन्यवाद, दर्ज हो गया।" if d else "पहले ही दर्ज है।")
        elif data.startswith(("safe:", "help:")) and chat_id:
            _rollcall_answer(repo, cq["id"], chat_id, data)
        return {"ok": True}

    msg = update.get("message") or {}
    text = str(msg.get("text", "")).strip()
    chat = msg.get("chat", {})
    chat_id = str(chat.get("id", ""))
    if text and not text.startswith("/") and chat_id and rollcall.add_note(repo, chat_id, text):
        _send(chat_id, hi.ROLLCALL_NOTE_THANKS)
        return {"ok": True}
    if not text.startswith("/start") or not chat_id:
        return {"ok": True}
    arg = text.split(maxsplit=1)[1].strip().lower() if " " in text else ""
    if arg.startswith("link_"):
        username = repo.consume_link_code(arg[len("link_"):].upper())
        if username is None:
            telegram.send_text(chat_id, "Pukaar: this link code is unknown or expired. Make a new one in the console.")
        else:
            repo.put_officer_chat(username, chat_id)
            log(_LOG, "officer chat linked", officer=username)
            telegram.send_text(chat_id, f"Pukaar: approval links for {username} will come to this chat.")
        return {"ok": True}
    village = repo.get_village(arg) if arg else None
    if village is None:
        ids = ", ".join(v.id for v in repo.list_villages())
        telegram.send_text(chat_id, f"पुकार: गाँव का कोड भेजें, जैसे /start thunag\nCodes: {ids}")
        return {"ok": True}
    name = " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or "Telegram user"
    repo.put_recipient(Recipient(id=chat_id, village_id=village.id, name=name, channel="telegram"))
    log(_LOG, "recipient registered", village_id=village.id)
    telegram.send_text(chat_id, f"पुकार: आप {village.name_hi} की बाढ़ चेतावनियों के लिए जुड़ गए हैं। आपात स्थिति में 112 पर कॉल करें।")
    return {"ok": True}
