"""Telegram webhook: /start <village id> registers a recipient; /start officer_<username>
links an officer's chat; the "मिल गया" button records an acknowledgement."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException, Request

from Pukaar.core.log import get_logger, log
from Pukaar.core.secrets import get_secret
from Pukaar.delivery import dispatch, telegram
from Pukaar.store.models import Recipient
from Pukaar.store.repo import get_repo

router = APIRouter()
_LOG = get_logger("telegram")


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
        return {"ok": True}

    msg = update.get("message") or {}
    text = str(msg.get("text", "")).strip()
    chat = msg.get("chat", {})
    chat_id = str(chat.get("id", ""))
    if not text.startswith("/start") or not chat_id:
        return {"ok": True}
    arg = text.split(maxsplit=1)[1].strip().lower() if " " in text else ""
    if arg.startswith("officer_"):
        username = arg[len("officer_"):]
        if any(username in (v.officers or []) for v in repo.list_villages()):
            repo.put_officer_chat(username, chat_id)
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
