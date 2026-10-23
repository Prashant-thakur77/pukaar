"""Telegram webhook.

/start <village code> shows the enrolment notice (what is kept, why, for how long, how to leave; Hindi and
English) with an "I agree" button, and only the button (consent:<village>) registers the person
(services/privacy.py). /stop, or the words "बंद करें", removes them from every village at once. /start with
no code, an unknown code, a district's name or the first letters of a village gets one short answer that
fits Telegram's 4,096 characters at any number of villages. /start link_<code> links an officer's chat
using a one-time code from the signed-in console (POST /me/telegram-link); the "मिल गया" button records an
acknowledgement; the roll-call buttons (safe:<id>, help:<id>) record "I am safe" or "I need help", and the
next plain message after "need help" is kept as a short note. A failed reply never makes the webhook fail
(Telegram would send the update again)."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException, Request

from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log
from Pukaar.core.secrets import get_secret
from Pukaar.delivery import dispatch, telegram
from Pukaar.services import privacy, rollcall
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
            _toast(cq["id"], "धन्यवाद, दर्ज हो गया।" if d else "पहले ही दर्ज है।")
        elif data.startswith(("safe:", "help:")) and chat_id:
            _rollcall_answer(repo, cq["id"], chat_id, data)
        elif data.startswith("consent:") and chat_id:
            _consent(repo, cq, chat_id, data[len("consent:"):])
        elif data == "noconsent" and chat_id:
            repo.drop_consent_wait(chat_id)
            _toast(cq["id"], hi.DECLINED[:190])
            _send(chat_id, hi.DECLINED)
        return {"ok": True}

    msg = update.get("message") or {}
    text = str(msg.get("text", "")).strip()
    chat = msg.get("chat", {})
    chat_id = str(chat.get("id", ""))
    if not chat_id or not text:
        return {"ok": True}
    if text.lower() in hi.STOP_WORDS or text.lower().startswith("/stop"):
        left = privacy.stop(repo, chat_id)
        _send(chat_id, hi.stopped([v.name_hi for v in left], get_settings().unlinked_retention_days) if left
              else hi.NOT_REGISTERED)
        return {"ok": True}
    if not text.startswith("/") and rollcall.add_note(repo, chat_id, text):
        _send(chat_id, hi.ROLLCALL_NOTE_THANKS)
        return {"ok": True}
    if not text.startswith("/start"):
        return {"ok": True}
    raw_arg = text.split(maxsplit=1)[1].strip() if " " in text else ""
    arg = raw_arg.lower()
    if arg.startswith("link_"):
        username = repo.consume_link_code(arg[len("link_"):].upper())
        if username is None:
            _send(chat_id, "Pukaar: this link code is unknown or expired. Make a new one in the console.")
        else:
            repo.put_officer_chat(username, chat_id)
            log(_LOG, "officer chat linked", officer=username)
            _send(chat_id, f"Pukaar: approval links for {username} will come to this chat.")
        return {"ok": True}
    village = repo.get_village(arg) if arg and len(arg) <= 64 else None
    if village is None:
        _send(chat_id, _find_village_reply(repo, raw_arg))
        return {"ok": True}
    if repo.get_recipient(village.id, chat_id) is not None:
        _send(chat_id, hi.ALREADY_ENROLLED)
        return {"ok": True}
    # Nothing about the person is stored until they press "I agree" under the notice (services/privacy.py).
    notice = privacy.ask_consent(repo, chat_id, village)
    try:
        telegram.send_consent(chat_id, village.id, notice)
    except Exception as exc:
        log(_LOG, "consent notice failed", 30, error=str(exc)[:200])
    return {"ok": True}


def _toast(callback_id: str, text: str) -> None:
    try:
        telegram.answer_callback(callback_id, text)
    except Exception as exc:
        log(_LOG, "callback answer failed", 30, error=str(exc)[:200])


def _consent(repo: Repo, cq: dict, chat_id: str, village_id: str) -> None:
    """"I agree" under the notice: only now is the person stored, with the consent record."""
    village = repo.get_village(village_id)
    if village is None or not repo.consume_consent_wait(chat_id, village_id):
        if village is not None and repo.get_recipient(village.id, chat_id) is not None:
            _toast(cq["id"], hi.CONSENT_THANKS)  # a double tap: already registered
            return
        _toast(cq["id"], hi.CONSENT_EXPIRED[:190])
        _send(chat_id, hi.CONSENT_EXPIRED)
        return
    who = cq.get("from") or {}
    name = " ".join(x for x in (who.get("first_name"), who.get("last_name")) if x) or "Telegram user"
    privacy.enrol(repo, chat_id, village, name)
    log(_LOG, "recipient registered with consent", village_id=village.id)
    _toast(cq["id"], hi.CONSENT_THANKS)
    _send(chat_id, hi.enrolled(village.name_hi, village.name))


def _find_village_reply(repo: Repo, raw_arg: str) -> str:
    """/start with no code, a district's name, the first letters of a village, or an unknown code. One short
    message whatever the number of villages (Telegram's limit is 4,096 characters), never every village id."""
    arg = raw_arg.strip().lower()
    villages = repo.list_villages() if arg else []
    districts = sorted({v.district for v in villages}) if villages else []
    if arg:
        in_district = [v for v in villages if v.district.lower() == arg]
        if in_district:
            return hi.village_codes(f"{in_district[0].district} ज़िले के गाँव · villages of {in_district[0].district}",
                                    [(v.id, v.name_hi, v.name) for v in sorted(in_district, key=lambda v: v.id)])
        starts = [v for v in villages if len(arg) >= 2 and (v.id.startswith(arg) or v.name.lower().startswith(arg)
                                                            or v.name_hi.startswith(raw_arg.strip()))]
        if starts:
            return hi.village_codes(f"“{raw_arg.strip()[:30]}” से शुरू होने वाले गाँव · villages starting with it",
                                    [(v.id, v.name_hi, f"{v.name}, {v.district}") for v in starts])
    else:
        districts = sorted({v.district for v in repo.list_villages()})
    return hi.start_help(districts, get_settings().web_url)
