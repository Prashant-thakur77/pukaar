"""Voice-call webhooks (docs/VOICE.md). Public routes, no Cognito: providers carry no token.

Every request must pass, before anything is read or written:
  1. the static key ?k= (SSM voice_webhook_key; with no key set, every request is refused);
  2. the signed call token: Exotel's CustomField, or ?c= on our own callback URLs, naming the
     alert, the person and the attempt (delivery/voice.sign_call);
  3. Plivo only: X-Plivo-Signature-V3 over the URL, the POST body and the nonce;
  4. the call id must be one Pukaar placed for that person and alert (delivery/ivr.load).
A forged or unauthenticated key press is a 403 and changes nothing.

The duty officer's wake-up call (delivery/officer_call.py, token attempt -1) uses the same routes:
it says which village needs an approval, and "1" only sends the one-tap approval link again to the
officer's Telegram and Web Push. No key press approves anything.

    GET|HEAD /voice/exotel/flow?part=greeting   the Greeting applet: the alert MP3 URL (text/plain)
    GET      /voice/exotel/flow?part=menu       the Gather applet: the "press 1, 2 or 3" menu (JSON)
    GET      /voice/exotel/gather               the Passthru applet: 200 ends the call, 302 plays again
    POST     /voice/exotel/status               Exotel's StatusCallback
    POST     /voice/plivo/answer                Plivo answer XML (GetDigits)
    POST     /voice/plivo/digits                the key pressed
    POST     /voice/plivo/hangup                Plivo's hangup callback

No answer here carries a phone number, a name or a chat id.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from Pukaar.core.log import get_logger, log
from Pukaar.delivery import ivr, officer_call, plivo, voice
from Pukaar.services import storage
from Pukaar.store.repo import get_repo
from Pukaar.templates import hi

router = APIRouter()
_LOG = get_logger("voice-webhook")
AUDIO_URL_SECONDS = 2 * 3600
XML = "application/xml"


def _refuse(reason: str, **ctx: Any) -> HTTPException:
    log(_LOG, "voice webhook refused", 30, reason=reason, **ctx)
    return HTTPException(403, "forbidden")


def _token(raw: str | None) -> voice.CallToken:
    try:
        return voice.verify_call(raw or "")
    except voice.TokenError as exc:
        raise _refuse(f"call token: {exc}") from None


def _context(tok: voice.CallToken, *call_ids: str | None) -> ivr.CallContext:
    try:
        return ivr.load(get_repo(), tok, *call_ids)
    except ivr.Forged:
        raise _refuse("call id not ours", alert_id=tok.alert_id) from None


def _wake(tok: voice.CallToken, *call_ids: str | None) -> officer_call.WakeContext:
    try:
        return officer_call.load(get_repo(), tok, *call_ids)
    except officer_call.Forged:
        raise _refuse("wake-up call id not ours", alert_id=tok.alert_id) from None


def _check_key(k: str | None) -> None:
    if not voice.webhook_key_ok(k):
        raise _refuse("webhook key")


async def _params(request: Request) -> dict[str, str]:
    """A provider callback body: form (default) or JSON (StatusCallbackContentType=application/json)."""
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = await request.json()
        except ValueError:
            return {}
        return {str(k): str(v) for k, v in (body or {}).items() if not isinstance(v, (dict, list))}
    form = await request.form()
    return {k: str(v) for k, v in form.items()}


def _audio(ctx: ivr.CallContext) -> str | None:
    return storage.url_for(ctx.alert.call_audio_key, expires=AUDIO_URL_SECONDS) if ctx.alert.call_audio_key else None


def _all_clear_text(ctx: ivr.CallContext) -> str:
    return hi.all_clear_voice(ctx.alert.village_name_hi, bool(ctx.alert.decision_trace.get("drill")))


def _menu_audio() -> str | None:
    from Pukaar.voice import polly

    try:
        key = polly.menu_audio_key()
    except Exception:
        key = None
    return storage.url_for(key, expires=AUDIO_URL_SECONDS) if key else None


# -- Exotel -------------------------------------------------------------------------------------
@router.api_route("/voice/exotel/flow", methods=["GET", "HEAD"])
def exotel_flow(request: Request, k: str = "", part: str = "greeting", CustomField: str = "",  # noqa: N803
                CallSid: str = "") -> Response:  # noqa: N803
    _check_key(k)
    tok = _token(CustomField)
    if officer_call.is_wake(tok):
        w = _wake(tok, CallSid)
        if part == "menu":
            return JSONResponse(officer_call.exotel_menu(w))
        if request.method == "GET":
            officer_call.answered(get_repo(), w)
        return PlainTextResponse(officer_call.greeting(w), media_type="text/plain")
    ctx = _context(tok, CallSid)
    if ivr.is_all_clear(ctx):  # the all-clear: spoken once; the flow's Gather ends at once, no key acts
        if part == "menu":
            return JSONResponse({"gather_prompt": {"text": hi.VOICE_GOODBYE_HI}, "max_input_digits": 1,
                                 "finish_on_key": "", "input_timeout": 1, "repeat_menu": 0})
        return PlainTextResponse(_all_clear_text(ctx), media_type="text/plain")
    if part == "menu":
        menu = _menu_audio()
        prompt = {"audio_url": menu} if menu else {"text": hi.VOICE_MENU_HI}
        return JSONResponse({"gather_prompt": prompt, "max_input_digits": 1, "finish_on_key": "",
                             "input_timeout": 8, "repeat_menu": 1, "repeat_gather_prompt": prompt})
    if request.method == "GET":
        ivr.answered(get_repo(), ctx)  # the flow starts when the call is picked up: the voice reaches the ear
    audio = _audio(ctx)
    # One audio URL per line (8 kHz mono MP3), or words for Exotel's own speech when Polly was unavailable.
    return PlainTextResponse(audio or ctx.alert.text_hi, media_type="text/plain")


@router.get("/voice/exotel/gather")
def exotel_gather(k: str = "", CustomField: str = "", CallSid: str = "", digits: str = "") -> Response:  # noqa: N803
    _check_key(k)
    tok = _token(CustomField)
    if officer_call.is_wake(tok):
        outcome, _ = officer_call.press(get_repo(), _wake(tok, CallSid), digits)
        log(_LOG, "exotel wake-up key", alert_id=tok.alert_id, outcome=outcome)
        # 302 back to the Greeting, which now says the link went out; 200 ends the call.
        return PlainTextResponse(outcome, status_code=302 if outcome == "link_sent" else 200)
    ctx = _context(tok, CallSid)
    result = ivr.press(get_repo(), ctx, digits)
    log(_LOG, "exotel key", alert_id=ctx.alert.id, outcome=result.outcome)
    # Passthru branches on the status code: 200 goes on to the closing Greeting, 302 back to the alert.
    return PlainTextResponse(result.outcome, status_code=302 if result.action == "repeat" else 200)


@router.post("/voice/exotel/status")
async def exotel_status(request: Request, k: str = "", c: str = "") -> dict:
    _check_key(k)
    p = await _params(request)
    tok = _token(c or p.get("CustomField"))
    st = voice.exotel_status(p.get("Status") or p.get("CallStatus") or "")
    if officer_call.is_wake(tok):
        return {"ok": True, "outcome": officer_call.call_status(get_repo(), _wake(tok, p.get("CallSid")), st)}
    ctx = _context(tok, p.get("CallSid"))
    outcome = ivr.call_status(get_repo(), ctx, st)
    return {"ok": True, "outcome": outcome}


# -- Plivo --------------------------------------------------------------------------------------
def _public_url(request: Request, path: str | None = None) -> str:
    """The URL the provider called (behind API Gateway the app sees http and the API host)."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("host", request.url.netloc)
    query = request.url.query
    return f"{proto}://{host}{path or request.url.path}" + (f"?{query}" if query else "")


async def _plivo_params(request: Request, k: str) -> dict[str, str]:
    _check_key(k)
    p = await _params(request)
    creds = plivo.credentials()
    if creds is None or not plivo.validate_v3(creds.auth_token, request.method, _public_url(request), p,
                                              request.headers.get("x-plivo-signature-v3-nonce", ""),
                                              request.headers.get("x-plivo-signature-v3", "")):
        raise _refuse("plivo signature")
    return p


async def _plivo_wake(request: Request, k: str, c: str) -> tuple[officer_call.WakeContext | None, dict[str, str]]:
    """The wake-up call's context when the token is one, else None (the caller reads the alert call)."""
    p = await _plivo_params(request, k)
    tok = _token(c)
    return (_wake(tok, p.get("RequestUUID"), p.get("CallUUID")) if officer_call.is_wake(tok) else None), p


@router.post("/voice/plivo/answer")
async def plivo_answer(request: Request, k: str = "", c: str = "") -> Response:
    w, p = await _plivo_wake(request, k, c)
    if w is not None:
        officer_call.answered(get_repo(), w)
        xml = plivo.answer_xml(audio_url=None, text_hi=officer_call.greeting(w), menu_url=None,
                               digits_url=_public_url(request, "/voice/plivo/digits"),
                               menu_text=hi.OFFICER_WAKE_MENU_HI, valid_digits="1")
        return Response(xml, media_type=XML)
    ctx = _context(_token(c), p.get("RequestUUID"), p.get("CallUUID"))
    if ivr.is_all_clear(ctx):
        return Response(plivo.end_xml(_all_clear_text(ctx)), media_type=XML)
    ivr.answered(get_repo(), ctx)
    xml = plivo.answer_xml(audio_url=_audio(ctx), text_hi=ctx.alert.text_hi, menu_url=_menu_audio(),
                           digits_url=_public_url(request, "/voice/plivo/digits"))
    return Response(xml, media_type=XML)


@router.post("/voice/plivo/digits")
async def plivo_digits(request: Request, k: str = "", c: str = "") -> Response:
    w, p = await _plivo_wake(request, k, c)
    if w is not None:
        outcome, say = officer_call.press(get_repo(), w, p.get("Digits"))
        log(_LOG, "plivo wake-up key", alert_id=w.alert.id, outcome=outcome)
        return Response(plivo.end_xml(say), media_type=XML)
    ctx = _context(_token(c), p.get("RequestUUID"), p.get("CallUUID"))
    result = ivr.press(get_repo(), ctx, p.get("Digits"))
    log(_LOG, "plivo key", alert_id=ctx.alert.id, outcome=result.outcome)
    if result.action == "repeat":
        return Response(plivo.redirect_xml(_public_url(request, "/voice/plivo/answer")), media_type=XML)
    return Response(plivo.end_xml(result.say or hi.VOICE_GOODBYE_HI), media_type=XML)


@router.post("/voice/plivo/hangup")
async def plivo_hangup(request: Request, k: str = "", c: str = "") -> dict:
    w, p = await _plivo_wake(request, k, c)
    st = voice.plivo_status(p.get("CallStatus", ""), p.get("HangupCause", ""), p.get("Machine", ""))
    if w is not None:
        return {"ok": True, "outcome": officer_call.call_status(get_repo(), w, st)}
    ctx = _context(_token(c), p.get("RequestUUID"), p.get("CallUUID"))
    return {"ok": True, "outcome": ivr.call_status(get_repo(), ctx, st)}
