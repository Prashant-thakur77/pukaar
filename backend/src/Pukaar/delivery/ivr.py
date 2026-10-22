"""What a key press or a call status means, the same for Exotel and Plivo (api/routers/voice.py).

The router has already checked the URL key, the provider signature (Plivo) and the signed call
token. Here the call id must also be one Pukaar placed for that person and alert, or the request is
refused as forged. Then:

    1   acknowledged: dispatch.acknowledge, exactly as the Telegram "मिल गया" button
    2   acknowledged (they heard it) and a need-help item: the roll-call answer when the person was
        asked in an open roll-call, otherwise an SOS report for the officers' queue
    3   play again, at most voice.MAX_REPEATS times
    other   asked again once, then the call ends; silence ends the call (the menu itself re-prompts)

Side effects are idempotent on (call id, digit): a provider retrying the same webhook acts once.

The all-clear call (token attempt 0, delivery.all_clear_call_id) only speaks the all-clear: no key
acts on it and no status moves the alert call's counters.
"""

from __future__ import annotations

from dataclasses import dataclass

from Pukaar.core import clock
from Pukaar.core.ids import new_id, track_code
from Pukaar.core.log import get_logger, log, metric
from Pukaar.delivery import dispatch, telegram, voice
from Pukaar.store.models import Alert, AuditRow, Delivery, Report
from Pukaar.store.repo import ConflictError, Repo

_LOG = get_logger("ivr")


class Forged(Exception):
    """The call id does not belong to the person and alert the token names."""


@dataclass(frozen=True)
class KeyResult:
    action: str  # "end" or "repeat"
    outcome: str  # acknowledged | already | need_help | repeat | reprompt | no_key | ended
    say: str = ""  # the closing words, for providers that speak them (Plivo)


@dataclass(frozen=True)
class CallContext:
    alert: Alert
    delivery: Delivery
    call_id: str


def load(repo: Repo, tok: voice.CallToken, *call_ids: str | None) -> CallContext:
    """call_ids: the ids the webhook names (Plivo sends both RequestUUID and CallUUID); one must be ours."""
    d = repo.get_delivery(tok.alert_id, tok.recipient_id, "voice")
    alert = repo.get_alert(tok.alert_id)
    # A token signed for the all-clear call names that call only; an alert-call token, the alert calls.
    ours = ([d.all_clear_call_id] if tok.attempt == voice.ALL_CLEAR_ATTEMPT else d.call_ids) if d else []
    match = next((c for c in call_ids if c and c in ours), None)
    if d is None or alert is None or match is None:
        raise Forged("unknown call for this alert and person")
    return CallContext(alert, d, match)


def is_all_clear(ctx: CallContext) -> bool:
    """The all-clear call (workflow/steps.stand_down): spoken once, no menu, no counter moves."""
    return bool(ctx.delivery.all_clear_call_id) and ctx.call_id == ctx.delivery.all_clear_call_id


def answered(repo: Repo, ctx: CallContext) -> Delivery:
    """The voice reached the ear: sent_at is the first answer, kept across re-calls."""
    d = ctx.delivery
    if is_all_clear(ctx):
        return d
    fields: dict = {}
    if not d.sent_at:
        fields["sent_at"] = clock.iso(clock.now())
    if d.status in {"pending", "failed"}:
        fields["status"] = "sent"
    if ctx.call_id == d.call_ids[-1] and d.call_status not in voice.FINAL_CALL_STATUSES:
        fields["call_status"] = "answered"
    if not fields:
        return d
    d = repo.update_delivery(d.alert_id, d.recipient_id, channel="voice", **fields)
    if "status" in fields:
        dispatch.recount(repo, d.alert_id)
    return d


def press(repo: Repo, ctx: CallContext, raw_digits: str | None) -> KeyResult:
    from Pukaar.templates import hi

    call_id = ctx.call_id
    if is_all_clear(ctx):
        return KeyResult("end", "all_clear", hi.VOICE_GOODBYE_HI)
    d = answered(repo, ctx)
    digit = voice.clean_digit(raw_digits)
    if digit == "1":
        repo.claim_voice_key(call_id, "1")
        acked = dispatch.acknowledge(repo, d.alert_id, d.recipient_id, channel="voice")
        repo.update_delivery(d.alert_id, d.recipient_id, channel="voice", digit="1")
        log(_LOG, "key 1: heard", alert_id=d.alert_id, recipient=d.recipient_id, first=acked is not None)
        return KeyResult("end", "acknowledged" if acked else "already", hi.VOICE_ACK_HI)
    if digit == "2":
        first = repo.claim_voice_key(call_id, "2")
        dispatch.acknowledge(repo, d.alert_id, d.recipient_id, channel="voice")
        repo.update_delivery(d.alert_id, d.recipient_id, channel="voice", digit="2")
        if first:
            need_help(repo, ctx.alert, d)
        return KeyResult("end", "need_help" if first else "already", hi.VOICE_HELP_HI)
    if digit == "3":
        n = d.repeats + 1
        repo.update_delivery(d.alert_id, d.recipient_id, channel="voice", repeats=n, digit="3")
        return KeyResult("repeat", "repeat") if n <= voice.MAX_REPEATS else KeyResult("end", "ended", hi.VOICE_GOODBYE_HI)
    if not digit:  # silence after the menu's own re-prompt
        return KeyResult("end", "no_key", hi.VOICE_GOODBYE_HI)
    n = d.reprompts + 1
    repo.update_delivery(d.alert_id, d.recipient_id, channel="voice", reprompts=n)
    return KeyResult("repeat", "reprompt") if n <= voice.MAX_REPROMPTS else KeyResult("end", "ended", hi.VOICE_GOODBYE_HI)


def need_help(repo: Repo, alert: Alert, d: Delivery) -> str:
    """"2" on the call: the roll-call's need-help when the person was asked in one, else an SOS report."""
    from Pukaar.services import rollcall

    metric("VoiceNeedHelp", 1, Village=alert.village_id)
    rc = rollcall.current_open(repo, alert.village_id)
    if rc is not None and repo.get_rollcall_asked(rc.id, d.recipient_id) is not None:
        rollcall.answer(repo, rc.id, d.recipient_id, "need_help")
        repo.add_timeline(alert.id, "voice_need_help", f"{_first(d.name)} pressed 2 on the call: roll-call {rc.id}")
        return "rollcall"
    drill = bool(alert.decision_trace.get("drill"))
    label = "अभ्यास (DRILL): " if drill else ""
    now = clock.iso(clock.now())
    report = Report(
        id=new_id("rpt"), village_id=alert.village_id, created_at=now,
        text=f"{label}चेतावनी की फ़ोन कॉल पर 2 दबाया: मदद चाहिए।",
        report_type="other", severity="high",
        summary_en=f"{'DRILL: ' if drill else ''}{_first(d.name)} pressed 2 (need help) on the voice call for "
                   f"alert {alert.id}. No location: call back or visit.",
        state="unverified", parser_source="voice-ivr",
        flags=["voice_need_help", "no_gps"] + (["drill"] if drill else []),
        track_code=track_code(), reporter_name=d.name, replay=alert.replay,
    )
    repo.put_report(report)
    repo.append_audit(AuditRow(
        at=now, id=new_id("aud"), actor="villager", role="villager", action="voice_need_help",
        resource=f"report:{report.id}", decision="allow",
        reason=f"{_first(d.name)} pressed 2 (मदद चाहिए) on the alert call in {alert.village_name}"))
    repo.add_timeline(alert.id, "voice_need_help", f"{_first(d.name)} pressed 2 on the call: report {report.id}")
    _tell_officers(repo, alert, d, report)
    return "report"


def _tell_officers(repo: Repo, alert: Alert, d: Delivery, report: Report) -> None:
    if not telegram.configured():
        return
    village = repo.get_village(alert.village_id)
    drill = " [DRILL]" if alert.decision_trace.get("drill") else ""
    text = (f"पुकार{drill}: {alert.village_name_hi} में {_first(d.name)} ने चेतावनी की कॉल पर 2 दबाया: मदद चाहिए।\n"
            f"{_first(d.name)} in {alert.village_name} pressed 2 (need help) on the alert call. Report {report.id}.")
    for officer in (village.officers if village else []):
        chat = repo.get_officer_chat(officer)
        if chat:
            try:
                telegram.send_text(chat, text)
            except Exception as exc:
                log(_LOG, "officer need-help notice failed", 30, alert_id=alert.id, error=str(exc)[:200])


def call_status(repo: Repo, ctx: CallContext, st: voice.CallStatus) -> str:
    """A provider's status callback. Updates the two retry counters; flags a number no call can reach.
    Only the newest call of the person counts; a repeated final status changes nothing."""
    d = ctx.delivery
    if is_all_clear(ctx):
        return "all_clear"
    if ctx.call_id != d.call_ids[-1]:
        return "stale"
    if st.answered:
        d = answered(repo, ctx)
    if not st.final:
        return "progress"
    if d.call_status in voice.FINAL_CALL_STATUSES:
        return "already"
    s_max = _max()
    fields: dict = {"call_status": st.call_status}
    if st.answered:
        if not d.acknowledged_at:
            fields.update(no_key=d.no_key + 1, error_category="no_key")
            metric("VoiceNoKey", 1)
        outcome = "answered"
    else:
        fields.update(not_connected=d.not_connected + 1, error_category=st.category,
                      error=f"{st.category} (attempt {d.attempts} of {s_max})")
        if not d.sent_at and not d.acknowledged_at:
            fields["status"] = "failed"
        metric("VoiceNotConnected", 1, Category=st.category or "failed")
        outcome = "not_connected"
    try:
        d = repo.update_delivery(d.alert_id, d.recipient_id, channel="voice", **fields)
    except ConflictError:
        return "missing"
    if "status" in fields:
        dispatch.recount(repo, d.alert_id)
    if outcome == "not_connected" and not d.sent_at and (st.category == "invalid_number" or d.attempts >= s_max):
        dispatch.flag_unreachable(repo, ctx.alert, d)
    log(_LOG, "call ended", alert_id=d.alert_id, recipient=d.recipient_id, status=st.call_status,
        category=st.category, attempt=d.attempts)
    return outcome


def _max() -> int:
    from Pukaar.core.config import get_settings

    return get_settings().voice_max_attempts


def _first(name: str) -> str:
    return (name or "").split(" ")[0] or "?"
