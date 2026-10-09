"""Send an alert to every recipient of its village and record each delivery.

Before any send: the Cedar guard (approved, or critical auto-send, or failsafe;
replay never reaches a real phone) and the action guard (rate limit per
village). Recipients without a live channel get a recorded stub delivery so
the demo and tests see the same records.
"""

from __future__ import annotations

from Pukaar.core import clock
from Pukaar.core.log import get_logger, log, metric
from Pukaar.delivery import telegram
from Pukaar.policy.guard import SYSTEM, authorize
from Pukaar.services import storage
from Pukaar.services.action_guard import check_send
from Pukaar.store.models import Alert, Delivery, Recipient
from Pukaar.store.repo import Repo
from Pukaar.templates import hi
from Pukaar.workflow import tokens

_LOG = get_logger("dispatch")


def _channel(recipient: Recipient, alert: Alert) -> str:
    if alert.replay or recipient.channel != "telegram" or not telegram.configured():
        return "stub"
    return "telegram"


def _send_one(alert: Alert, recipient: Recipient, channel: str, audio: bytes | None) -> None:
    if channel == "telegram":
        telegram.send_alert(recipient.id, alert.id, alert.text_hi, audio)
    else:
        log(_LOG, "stub delivery", alert_id=alert.id, recipient=recipient.id, replay=alert.replay)


def deliver(repo: Repo, alert: Alert, *, action: str = "deliver", recall: bool = False) -> tuple[int, int]:
    """Returns (sent, failed). action is deliver, auto_send or failsafe."""
    recipients = repo.list_recipients(alert.village_id)
    existing = {d.recipient_id: d for d in repo.list_deliveries(alert.id)}
    audio = None
    if alert.audio_key:
        try:
            audio, _ = storage.get_bytes(alert.audio_key)
        except Exception as exc:
            log(_LOG, "audio unavailable; sending text", 30, alert_id=alert.id, error=str(exc)[:200])

    sent = failed = 0
    for r in recipients:
        prior = existing.get(r.id)
        if recall:
            if prior is None or prior.acknowledged_at or prior.attempts >= 2:
                continue
        elif prior is not None and prior.status in {"sent", "acknowledged"}:
            continue  # idempotent: never send the same alert twice to one person
        channel = _channel(r, alert)
        ctx = {"approved": alert.approved, "level": alert.level, "replay": alert.replay, "channel": channel,
               "all_officers_timed_out": alert.status == "auto_sent_unapproved"}
        decision = authorize(SYSTEM, action, "alert", alert.id, ctx, repo=repo)
        guard = check_send(alert.village_id, alert.level, alert.id) if decision.allowed else None
        attempts = (prior.attempts if prior else 0) + 1
        if not decision.allowed or (guard is not None and not guard.accepted):
            reason = decision.reason if not decision.allowed else guard.reason  # type: ignore[union-attr]
            repo.put_delivery(Delivery(alert_id=alert.id, recipient_id=r.id, name=r.name, channel=channel,
                                       status="failed", attempts=attempts, error=f"blocked: {reason}"))
            failed += 1
            continue
        try:
            _send_one(alert, r, channel, audio)
            repo.put_delivery(Delivery(alert_id=alert.id, recipient_id=r.id, name=r.name, channel=channel,
                                       status="sent", sent_at=clock.iso(clock.now()), attempts=attempts))
            sent += 1
            metric("DeliverySent", 1, Channel=channel)
        except Exception as exc:
            repo.put_delivery(Delivery(alert_id=alert.id, recipient_id=r.id, name=r.name, channel=channel,
                                       status="failed", attempts=attempts, error=str(exc)[:200]))
            failed += 1
            metric("DeliveryFailed", 1, Channel=channel)
    log(_LOG, "delivery round", alert_id=alert.id, sent=sent, failed=failed, recall=recall)
    return sent, failed


def acknowledge(repo: Repo, alert_id: str, recipient_id: str) -> Delivery | None:
    """Record an acknowledgement once; a repeated tap changes nothing."""
    from boto3.dynamodb.conditions import Attr

    from Pukaar.store.repo import ConflictError

    try:
        d = repo.update_delivery(alert_id, recipient_id, condition=Attr("acknowledged_at").not_exists(),
                                 acknowledged_at=clock.iso(clock.now()), status="acknowledged")
    except ConflictError:
        return None
    alert = repo.get_alert(alert_id)
    if alert is not None:
        acked = sum(1 for x in repo.list_deliveries(alert_id) if x.acknowledged_at)
        repo.update_alert(alert_id, acknowledged_count=acked)
    return d


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
