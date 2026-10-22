"""Send an alert to every recipient of its village and record each delivery.

Before any send: the Cedar guard (approved, or critical auto-send, or failsafe;
replay never reaches a real phone) and the action guard (rate limit per
village). Replays, and demo recipients whose channel is "stub", get a recorded
stub delivery so the demo and tests see the same records. A real recipient is
never sent to the stub: a missing token or a Telegram error, or a voice
provider that is off or unconfigured, is a failed delivery with its reason,
counted in DeliveryFailed (alarmed).

Channels: a recipient takes Telegram, voice calls (delivery/voice.py) or both;
a "both" person has one delivery row per channel, and every counter counts
people, not rows. A voice row is "pending" while the call rings, "sent" once
answered, "acknowledged" after a key press, "failed" when not connected.

Re-sends (workflow recall): Telegram once, after AckWaitSeconds. Voice up to
PUKAAR_VOICE_MAX_ATTEMPTS calls in all, with two counters (docs/VOICE.md):
not_connected (busy, no answer, failed) and no_key (answered, no key).
"""

from __future__ import annotations

from datetime import timedelta

from boto3.dynamodb.conditions import Attr

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log, metric
from Pukaar.delivery import telegram, voice
from Pukaar.policy.guard import SYSTEM, authorize
from Pukaar.services import storage
from Pukaar.services.action_guard import check_send
from Pukaar.store.models import Alert, Delivery, Recipient
from Pukaar.store.repo import ConflictError, Repo
from Pukaar.templates import hi
from Pukaar.workflow import tokens

_LOG = get_logger("dispatch")
TELEGRAM_MAX_ATTEMPTS = 2  # the first send and one re-send
REACHED = {"sent", "acknowledged"}


def _channels(recipient: Recipient, alert: Alert) -> list[str]:
    """The stub channel is only for replays and for demo recipients that are explicitly stub.

    A telegram or voice recipient of a live alert always goes through that channel: if the token
    or the call provider is unavailable, the delivery is recorded as failed with the reason, never
    as a "sent" stub. A drill started with CHANNEL=voice (or telegram) uses that channel only.
    """
    if alert.replay or recipient.channel == "stub":
        return ["stub"]
    only = alert.decision_trace.get("drill_channel") if alert.decision_trace.get("drill") else None
    out = []
    if recipient.takes_telegram and only in (None, "telegram"):
        out.append("telegram")
    if recipient.takes_voice and only in (None, "voice"):
        out.append("voice")
    return out


def _send_telegram(alert: Alert, recipient: Recipient, audio: bytes | None) -> None:
    if not telegram.configured():
        raise telegram.TelegramError("Telegram token unavailable (not configured, or SSM could not be read)")
    telegram.send_alert(recipient.id, alert.id, alert.text_hi, audio)


def _call_audio(repo: Repo, alert: Alert) -> Alert:
    """Make the 8 kHz call audio and the menu once per alert. Never raises: without audio the call speaks the text."""
    if alert.replay or alert.call_audio_key:
        return alert
    from Pukaar.voice import polly

    try:
        key = polly.synthesize_call_audio(alert.id, alert.text_hi)
        polly.menu_audio_key()
        if key:
            return repo.update_alert(alert.id, call_audio_key=key)
    except Exception as exc:
        log(_LOG, "call audio unavailable; the call speaks the text", 30, alert_id=alert.id, error=str(exc)[:200])
    return alert


def _person_acked(rows: dict[tuple[str, str], Delivery], recipient_id: str) -> bool:
    return any(d.acknowledged_at for (rid, _), d in rows.items() if rid == recipient_id)


def _voice_due(prior: Delivery, now) -> tuple[bool, dict]:
    """May this voice row be called again now? Returns (due, counter updates for a call with no result)."""
    s = get_settings()
    if prior.unreachable or prior.attempts >= s.voice_max_attempts or prior.error_category in voice.TERMINAL:
        return False, {}
    if prior.call_status in voice.FINAL_CALL_STATUSES or prior.status == "failed":
        return True, {}
    # Placed, but the provider never said how it ended: still ringing, or the callback was lost.
    placed = clock.parse(prior.last_attempt_at) if prior.last_attempt_at else now
    if (now - placed) < timedelta(seconds=voice.IN_PROGRESS_GRACE_SECONDS):
        return False, {}
    if prior.call_status == "answered":  # answered, then nothing: no key pressed
        return True, {"no_key": prior.no_key + 1, "error_category": "no_key"}
    return True, {"not_connected": prior.not_connected + 1, "error_category": "no_status"}


def deliver(repo: Repo, alert: Alert, *, action: str = "deliver", recall: bool = False) -> tuple[int, int]:
    """Returns (sent, failed), counted in people. action is deliver, auto_send or failsafe.

    A voice call counts as sent here once the provider accepted it; the delivery row says "sent"
    only when the call is answered (delivery/ivr.py).
    """
    recipients = repo.list_recipients(alert.village_id)
    existing = {(d.recipient_id, "voice" if d.channel == "voice" else "other"): d for d in repo.list_deliveries(alert.id)}
    audio = None
    if alert.audio_key:
        try:
            audio, _ = storage.get_bytes(alert.audio_key)
        except Exception as exc:
            log(_LOG, "audio unavailable; sending text", 30, alert_id=alert.id, error=str(exc)[:200])

    now = clock.now()
    if any("voice" in _channels(r, alert) for r in recipients):
        alert = _call_audio(repo, alert)  # once per round, before the first call
    reached: set[str] = set()
    failed_people: set[str] = set()
    decisions: dict[str, object] = {}  # one policy decision (and audit row) per channel per round
    for r in recipients:
        for channel in _channels(r, alert):
            slot = (r.id, "voice" if channel == "voice" else "other")
            prior = existing.get(slot)
            carry: dict = {}
            if recall:
                if prior is None or _person_acked(existing, r.id):
                    continue
                if channel == "voice":
                    due, carry = _voice_due(prior, now)
                    if not due:
                        continue
                elif prior.attempts >= TELEGRAM_MAX_ATTEMPTS:
                    continue
            elif prior is not None and prior.status in REACHED | {"pending"}:
                continue  # idempotent: never send the same alert twice to one person
            ctx = {"approved": alert.approved, "level": alert.level, "replay": alert.replay, "channel": channel,
                   "all_officers_timed_out": alert.status == "auto_sent_unapproved"}
            if channel not in decisions:
                decisions[channel] = authorize(SYSTEM, action, "alert", alert.id, ctx, repo=repo)
            decision = decisions[channel]
            guard = check_send(alert.village_id, alert.level, alert.id) if decision.allowed else None
            attempts = (prior.attempts if prior else 0) + 1
            if not decision.allowed or (guard is not None and not guard.accepted):
                reason = decision.reason if not decision.allowed else guard.reason  # type: ignore[union-attr]
                repo.put_delivery(Delivery(alert_id=alert.id, recipient_id=r.id, name=r.name, channel=channel,
                                           status="failed", attempts=attempts, error=f"blocked: {reason}",
                                           error_category="blocked" if channel == "voice" else None))
                failed_people.add(r.id)
                metric("DeliveryFailed", 1, Channel=channel)
                continue
            if channel == "voice":
                ok = _place_call(repo, alert, r, prior, attempts, carry)
            else:
                ok = _send_other(repo, alert, r, channel, prior, attempts, audio)
            (reached if ok else failed_people).add(r.id)
    failed_people -= reached
    log(_LOG, "delivery round", alert_id=alert.id, sent=len(reached), failed=len(failed_people), recall=recall)
    return len(reached), len(failed_people)


def _send_other(repo: Repo, alert: Alert, r: Recipient, channel: str, prior: Delivery | None, attempts: int,
                audio: bytes | None) -> bool:
    """Telegram, or the stub. A replay's voice recipient goes through the stub voice provider, which says so."""
    try:
        provider = None
        if channel == "telegram":
            _send_telegram(alert, r, audio)
        else:
            if r.takes_voice:
                provider = voice.place_call(r, alert, None, attempt=attempts).provider  # replay: the stub, no dialling
            log(_LOG, "stub delivery", alert_id=alert.id, recipient=r.id, replay=alert.replay)
        # a re-send keeps the first send time: "when did the voice first reach this phone" must not move
        first = prior.sent_at if prior is not None and prior.sent_at else clock.iso(clock.now())
        repo.put_delivery(Delivery(alert_id=alert.id, recipient_id=r.id, name=r.name, channel=channel,
                                   status="sent", sent_at=first, attempts=attempts, provider=provider,
                                   call_status="simulated" if provider == "stub" else None))
        metric("DeliverySent", 1, Channel=channel)
        return True
    except Exception as exc:
        repo.put_delivery(Delivery(alert_id=alert.id, recipient_id=r.id, name=r.name, channel=channel,
                                   status="failed", attempts=attempts, error=voice.mask(str(exc))[:200]))
        metric("DeliveryFailed", 1, Channel=channel)
        return False


def _place_call(repo: Repo, alert: Alert, r: Recipient, prior: Delivery | None, attempts: int, carry: dict) -> bool:
    base = prior.model_dump() if prior else {"alert_id": alert.id, "recipient_id": r.id, "channel": "voice"}
    base.update(name=r.name, attempts=attempts, last_attempt_at=clock.iso(clock.now()), digit=None, repeats=0,
                reprompts=0, **carry)
    try:
        attempt = voice.place_call(r, alert, None, attempt=attempts)
    except voice.VoiceError as exc:
        base.update(status="failed", error=str(exc)[:200], error_category=exc.category, call_status=None)
        d = Delivery.model_validate(base)
        repo.put_delivery(d)
        log(_LOG, "call not placed", 30, alert_id=alert.id, recipient=r.id, category=exc.category, error=str(exc)[:200])
        if exc.category in voice.NOT_CONNECTED:
            metric("VoiceNotConnected", 1, Category=exc.category)
        else:
            metric("DeliveryFailed", 1, Channel="voice")
        if exc.category == "invalid_number":
            flag_unreachable(repo, alert, d)
        return False
    # Answered on an earlier attempt (no key pressed): still reached; otherwise ringing.
    base.update(status="sent" if base.get("sent_at") or attempt.simulated else "pending", provider=attempt.provider,
                call_ids=list(base.get("call_ids") or []) + ([attempt.call_id] if attempt.call_id else []),
                call_status=attempt.status, error=None)  # error_category keeps the last call's outcome
    repo.put_delivery(Delivery.model_validate(base))
    log(_LOG, "call placed", alert_id=alert.id, recipient=r.id, provider=attempt.provider, attempt=attempts)
    metric("VoiceCallPlaced", 1, Provider=attempt.provider)
    return True


def voice_retry_due(repo: Repo, alert: Alert) -> bool:
    """Is any voice call still worth another round? (the workflow loops on this, bounded by recall_rounds)"""
    if alert.replay:
        return False
    rows = {(d.recipient_id, "voice" if d.channel == "voice" else "other"): d for d in repo.list_deliveries(alert.id)}
    s = get_settings()
    return any(d.channel == "voice" and not _person_acked(rows, d.recipient_id) and not d.unreachable
               and d.attempts < s.voice_max_attempts and d.error_category not in voice.TERMINAL
               for d in rows.values())


def recount(repo: Repo, alert_id: str) -> Alert | None:
    """delivered_count and acknowledged_count, in people: a "both" recipient counts once."""
    rows = repo.list_deliveries(alert_id)
    if repo.get_alert(alert_id) is None:
        return None
    from Pukaar.services import events

    alert = repo.update_alert(alert_id, delivered_count=len({d.recipient_id for d in rows if d.status in REACHED}),
                              acknowledged_count=len({d.recipient_id for d in rows if d.acknowledged_at}))
    events.counts_changed(alert)
    return alert


def acknowledge(repo: Repo, alert_id: str, recipient_id: str, channel: str = "") -> Delivery | None:
    """Record an acknowledgement once; a repeated tap (or key press) changes nothing.

    channel "voice" acknowledges the person's call row (delivery/ivr.py); anything else their
    Telegram (or stub) row. Either stops further re-sends to that person on every channel.
    """
    try:
        d = repo.update_delivery(alert_id, recipient_id, channel=channel, condition=Attr("acknowledged_at").not_exists(),
                                 acknowledged_at=clock.iso(clock.now()), status="acknowledged")
    except ConflictError:
        return None
    recount(repo, alert_id)
    return d


def flag_unreachable(repo: Repo, alert: Alert, d: Delivery) -> None:
    """A number no call could reach: on the alert timeline, and to the village pradhan by Telegram.
    Names a first name only; the number never leaves the table."""
    if alert.replay or d.unreachable:
        return
    try:
        repo.update_delivery(alert.id, d.recipient_id, channel="voice", unreachable=True)
    except ConflictError:
        return
    first = (d.name or "").split(" ")[0] or "?"
    reason = d.error_category or "failed"
    metric("VoiceUnreachable", 1, Category=reason)
    repo.add_timeline(alert.id, "voice_unreachable", f"{first}: not reached by call after {d.attempts} attempt(s) "
                                                     f"({reason}); flagged to the pradhan")
    pradhans = [r for r in repo.list_recipients(alert.village_id) if r.role == "pradhan" and r.takes_telegram]
    if not pradhans or not telegram.configured():
        log(_LOG, "unreachable number: no pradhan on Telegram to tell", 30, alert_id=alert.id, recipient=d.recipient_id)
        return
    text = hi.voice_unreachable_pradhan(first, alert.village_name_hi, d.attempts, reason,
                                        bool(alert.decision_trace.get("drill")))
    for p in pradhans:
        try:
            telegram.send_text(p.id, text)
        except Exception as exc:
            log(_LOG, "pradhan unreachable notice failed", 30, alert_id=alert.id, error=str(exc)[:200])


def ack_link(alert: Alert, recipient_id: str, web_url: str) -> str:
    return f"{web_url}/ack/{tokens.sign(alert.id, recipient_id, 0, 'ack')}"


def notify_officer(repo: Repo, alert: Alert, officer_username: str, approve_url: str) -> bool:
    """Send the one-tap approval link to the officer's Telegram, if registered."""
    chat_id = repo.get_officer_chat(officer_username)
    if not chat_id or not telegram.configured():
        log(_LOG, "officer notified in console only", alert_id=alert.id, officer=officer_username)
        return False
    try:
        flag = " [REPLAY]" if alert.replay else ""
        telegram.send_text(chat_id, f"पुकार{flag}: {alert.village_name_hi} – {hi.LEVEL_HI[alert.level]}\n"
                                    f"{alert.text_hi}\n\nApprove / decline: {approve_url}")
        return True
    except Exception as exc:
        log(_LOG, "officer notify failed", 30, alert_id=alert.id, error=str(exc)[:200])
        return False
