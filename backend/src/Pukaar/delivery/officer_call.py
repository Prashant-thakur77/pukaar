"""Wake the duty officer: a voice call when an approval waits and the officer has not opened it.

Web Push and Telegram stay silent on a phone in silent mode at 3 am. So at the nudge
(workflow/steps.step_nudge_officer, PUKAAR_OFFICER_WAKE_SECONDS into the officer's window, 3
minutes by default) the officer who has not opened the one-tap link is also called, through the
same voice provider as the villagers (delivery/voice.py):

    "पुकार: <village> को अभी आपकी मंज़ूरी चाहिए, <level>। Pukaar: <village> needs your approval now, <level>."
    "Press 1 to get your approval link on Telegram."

Pressing 1 sends the one-tap approval link again to the officer's Telegram and Web Push and says so.
It never approves, declines or changes the alert: for liability the decision stays a deliberate tap
in the app, by the officer, with the alert in front of them. No key, a wrong key or silence ends
the call.

Honest records (OfficerCall, one per officer per alert, on the alert's timeline too):
- not_possible, with the reason: the voice provider is off, no phone is on file for the officer
  (make officer-phone), or the alert is a replay (a replay never rings a real phone). The
  nudge goes on by Web Push and Telegram either way.
- failed: the provider refused the call (the reason, with any number masked).
- placed, then answered / completed / not_connected from the provider's status callback, and
  link_sent after "1".

Webhooks reuse /voice/* (api/routers/voice.py): the call token is signed for the person
"o_<username>" and attempt voice.OFFICER_WAKE_ATTEMPT, and the call id must be the one placed.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log, metric
from Pukaar.delivery import voice
from Pukaar.store.models import Alert, OfficerCall, Recipient
from Pukaar.store.repo import ConflictError, Repo
from Pukaar.templates import hi

_LOG = get_logger("officer_call")
PREFIX = "o_"


def token_id(username: str) -> str:
    """The person id in the call token: base64url has no '.', which the token uses as its separator."""
    return PREFIX + base64.urlsafe_b64encode(username.encode()).rstrip(b"=").decode()


def username_from(token_recipient: str) -> str | None:
    if not token_recipient.startswith(PREFIX):
        return None
    raw = token_recipient[len(PREFIX):]
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return None


def opened(alert: Alert, officer: str) -> bool:
    """Has this officer opened the approval link for the current token version?"""
    return alert.approval_opened_by == officer and alert.approval_opened_version == alert.token_version


def wake(repo: Repo, alert: Alert, officer: str, index: int) -> OfficerCall:
    """Call the officer, once per alert, or record why no call was possible. Never raises."""
    try:
        return _wake(repo, alert, officer, index)
    except Exception as exc:  # the nudge by push and Telegram goes on whatever happens here
        log(_LOG, "wake-up call error", 40, alert_id=alert.id, error=voice.mask(str(exc))[:200])
        return OfficerCall(alert_id=alert.id, officer=officer, officer_index=index, level=alert.level,
                           status="failed", reason=f"error: {type(exc).__name__}")


def _wake(repo: Repo, alert: Alert, officer: str, index: int) -> OfficerCall:
    existing = repo.get_officer_call(alert.id, officer)
    if existing is not None:
        return existing  # a retried nudge never calls twice
    now = clock.iso(clock.now())
    call = OfficerCall(alert_id=alert.id, officer=officer, officer_index=index, level=alert.level, placed_at=now)
    phone = repo.get_officer_phone(officer)
    reason = None
    if alert.replay:
        reason = "replay: no real phone is called"
    elif get_settings().voice_provider == "off":
        reason = "voice provider is off (PUKAAR_VOICE_PROVIDER=off)"
    elif not phone:
        reason = f"no phone number on file for {officer} (make officer-phone)"
    if reason is not None:
        call.status, call.reason = "not_possible", reason
        _store(repo, call)
        metric("OfficerWakeCall", 1, Status="not_possible")
        return call
    try:
        repo.put_officer_call(call)  # claim first: one call per officer per alert, even if the step is retried
    except ConflictError:
        return repo.get_officer_call(alert.id, officer) or call
    person = Recipient(id=token_id(officer), village_id=alert.village_id, name=officer, role="officer",
                       channel="voice", phone=phone)
    try:
        attempt = voice.place_call(person, alert, None, attempt=voice.OFFICER_WAKE_ATTEMPT)
    except (voice.VoiceError, voice.TokenError) as exc:
        category = getattr(exc, "category", "provider_error")
        status = "not_possible" if category == "provider_off" else "failed"
        call = repo.update_officer_call(alert.id, officer, status=status, reason=voice.mask(str(exc))[:200])
        metric("OfficerWakeCall", 1, Status=status)
        log(_LOG, "wake-up call not placed", 30, alert_id=alert.id, officer=officer, category=category)
        return call
    call = repo.update_officer_call(alert.id, officer, status="placed", provider=attempt.provider,
                                   call_id=attempt.call_id, call_status=attempt.status)
    metric("OfficerWakeCall", 1, Status="placed")
    log(_LOG, "wake-up call placed", alert_id=alert.id, officer=officer, provider=attempt.provider)
    return call


def _store(repo: Repo, call: OfficerCall) -> None:
    try:
        repo.put_officer_call(call)
    except ConflictError:
        pass


def describe(call: OfficerCall) -> str:
    """For the alert timeline."""
    if call.status in {"placed", "answered", "completed", "link_sent"}:
        return f"call=placed ({call.provider})"
    return f"call={call.status.replace('_', ' ')} ({call.reason or 'no reason given'})"


# -- webhooks (api/routers/voice.py) ----------------------------------------------------------------
class Forged(Exception):
    """The call id is not the wake-up call Pukaar placed for this officer and alert."""


@dataclass(frozen=True)
class WakeContext:
    alert: Alert
    call: OfficerCall
    call_id: str


def is_wake(tok: voice.CallToken) -> bool:
    return tok.attempt == voice.OFFICER_WAKE_ATTEMPT


def load(repo: Repo, tok: voice.CallToken, *call_ids: str | None) -> WakeContext:
    officer = username_from(tok.recipient_id)
    alert = repo.get_alert(tok.alert_id)
    call = repo.get_officer_call(tok.alert_id, officer) if officer else None
    match = next((c for c in call_ids if c and call and c == call.call_id), None)
    if alert is None or call is None or match is None:
        raise Forged("unknown wake-up call for this alert and officer")
    return WakeContext(alert, call, match)


def greeting(ctx: WakeContext) -> str:
    """What the call says first; on Exotel's second pass (after "1"), the confirmation instead."""
    if ctx.call.status == "link_sent":
        return hi.OFFICER_LINK_SENT_HI if ctx.call.link_channels else hi.OFFICER_LINK_NONE_HI
    a = ctx.alert
    return hi.officer_wake_voice(a.village_name_hi, a.village_name, a.level, bool(a.decision_trace.get("drill")))


def exotel_menu(ctx: WakeContext) -> dict:
    """Exotel's Gather: "press 1"; once the link went out, a short goodbye that waits for nothing."""
    if ctx.call.status == "link_sent":
        return {"gather_prompt": {"text": hi.VOICE_GOODBYE_HI}, "max_input_digits": 1, "finish_on_key": "",
                "input_timeout": 1, "repeat_menu": 0}
    prompt = {"text": hi.OFFICER_WAKE_MENU_HI}
    return {"gather_prompt": prompt, "max_input_digits": 1, "finish_on_key": "", "input_timeout": 8,
            "repeat_menu": 1, "repeat_gather_prompt": prompt}


def answered(repo: Repo, ctx: WakeContext) -> None:
    if ctx.call.answered_at:
        return
    try:
        repo.update_officer_call(ctx.alert.id, ctx.call.officer, answered_at=clock.iso(clock.now()),
                                 status="answered" if ctx.call.status == "placed" else ctx.call.status)
    except ConflictError:
        pass


def press(repo: Repo, ctx: WakeContext, raw_digits: str | None) -> tuple[str, str]:
    """(outcome, the words to say back). "1" sends the approval link again (Telegram and Web Push);
    nothing else acts. Never approves: the alert's status, approval and task token are not touched."""
    answered(repo, ctx)
    digit = voice.clean_digit(raw_digits)
    if digit != "1":
        return "ended", hi.VOICE_GOODBYE_HI
    alert = repo.get_alert(ctx.alert.id) or ctx.alert
    if alert.status != "pending":
        return "decided", hi.OFFICER_DECIDED_HI
    if not repo.claim_voice_key(ctx.call_id, "1"):  # a provider retrying the same webhook acts once
        return "already", hi.OFFICER_LINK_SENT_HI
    channels = send_link(repo, alert, ctx.call.officer)
    repo.update_officer_call(alert.id, ctx.call.officer, digit="1", status="link_sent",
                             link_sent_at=clock.iso(clock.now()), link_channels=channels)
    repo.add_timeline(alert.id, "officer_call_key",
                      f"{ctx.call.officer} pressed 1 on the wake-up call: approval link sent again "
                      f"({', '.join(channels) or 'no channel reached'}); the decision stays in the app")
    metric("OfficerWakeLinkSent", 1)
    return "link_sent", (hi.OFFICER_LINK_SENT_HI if channels else hi.OFFICER_LINK_NONE_HI)


def send_link(repo: Repo, alert: Alert, officer: str) -> list[str]:
    """The same one-tap link the officer was sent first (current token version). Never raises."""
    from Pukaar.delivery import dispatch
    from Pukaar.services import officer_push
    from Pukaar.workflow import tokens

    link = tokens.sign(alert.id, officer, alert.token_version, "approve")
    url = f"{get_settings().web_url}/a/{link}"
    out = []
    try:
        if dispatch.notify_officer(repo, alert, officer, url):
            out.append("telegram")
    except Exception as exc:
        log(_LOG, "link by telegram failed", 30, alert_id=alert.id, error=str(exc)[:200])
    try:
        if officer_push.notify_approval(repo, alert, officer, link, url).sent:
            out.append("push")
    except Exception as exc:
        log(_LOG, "link by push failed", 30, alert_id=alert.id, error=str(exc)[:200])
    return out


def call_status(repo: Repo, ctx: WakeContext, st: voice.CallStatus) -> str:
    if st.answered:
        answered(repo, ctx)
    if not st.final:
        return "progress"
    status = ctx.call.status
    if status in {"placed", "answered"}:
        status = "completed" if st.answered else "not_connected"
    try:
        repo.update_officer_call(ctx.alert.id, ctx.call.officer, call_status=st.call_status, status=status,
                                 reason=st.category or ctx.call.reason)
    except ConflictError:
        return "missing"
    if status == "not_connected":
        repo.add_timeline(ctx.alert.id, "officer_call_ended",
                          f"the wake-up call to {ctx.call.officer} was not answered ({st.category or st.call_status})")
    return status
