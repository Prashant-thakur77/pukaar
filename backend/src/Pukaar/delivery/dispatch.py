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

Relays first: the village's relays (pradhan, gauge reader, task-force volunteers; Recipient.role)
are contacted before everyone else, and their Telegram message asks them to sound the siren and
the megaphone. A relay's acknowledgement is recorded as "relay done: siren and megaphone" on the
alert timeline. This is the "cascade" of Practical Action's community early-warning work in Nepal:
the alert reaches a few trusted people first, and they carry it the last mile by siren and voice.

At scale (docs/CONTRACT.md, "Delivery at scale"): the recipients, relays first, are cut into batches
of PUKAAR_DELIVERY_BATCH_SIZE. The deliver step sends the first batch itself (the relays one by one,
and the single upload of the alert audio to Telegram); the Map state in infra/approval.asl.json sends
the other batches, PUKAAR_DELIVERY_CONCURRENCY at a time, each worker at 1/n of the overall rate
(delivery/ratelimit.py) with PUKAAR_DELIVERY_THREADS sends in flight. Every send is claimed first by a
conditional write on its row (Repo.claim_delivery: a compare-and-set on attempts, once per round), so a
retried or overlapping batch never sends twice. A Telegram 429 pauses the worker for retry_after and
the message is tried again; past the step's time budget it is put back unsent (deferred) and the next
pass sends it. A deferred send is never recorded as sent.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from boto3.dynamodb.conditions import Attr

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log, metric
from Pukaar.delivery import telegram, voice
from Pukaar.delivery.ratelimit import RateLimiter
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
ROUND_DELIVER = 0  # Delivery.send_round of the first delivery; re-sends count 1, 2, ...; the failsafe -1
ROUND_FAILSAFE = -1
RATE_LIMIT_TRIES = 3  # 429 answers waited out for one message before it is put back for the next pass


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


def _slot(channel: str) -> str:
    return "voice" if channel == "voice" else "other"


def _send_telegram(alert: Alert, recipient: Recipient, audio: bytes | str | None) -> Any:
    if not telegram.configured():
        raise telegram.TelegramError("Telegram token unavailable (not configured, or SSM could not be read)")
    text = f"{hi.RELAY_LINE_HI}\n\n{alert.text_hi}" if recipient.is_relay else alert.text_hi
    return telegram.send_alert(recipient.id, alert.id, text, audio)


def _same_world(alert: Alert, r: Recipient) -> bool:
    """A person of the alert's own village, and on the same side of the live jury demo: a demo alert reaches only
    the demo's consented people, any other alert never reaches one of them (services/demo.py)."""
    demo_alert = bool((alert.decision_trace or {}).get("demo"))
    return r.village_id == alert.village_id and demo_alert == (r.enrolled_via == "demo")


def relays_first(recipients: list[Recipient]) -> list[Recipient]:
    """The Practical Action cascade: relays (pradhan, gauge reader, task force) before everyone else.
    Stable, so the order within each group is the stored order."""
    return sorted(recipients, key=lambda r: 0 if r.is_relay else 1)


def ordered_recipients(repo: Repo, alert: Alert) -> list[Recipient]:
    """Everyone the alert goes to, in sending order; batch n is the n-th slice of this list."""
    return relays_first([r for r in repo.list_recipients(alert.village_id) if _same_world(alert, r)])


def batch_count(total: int, size: int | None = None) -> int:
    size = size or get_settings().delivery_batch_size
    return max(1, -(-total // size))


def batch_specs(people: list[Recipient], size: int | None = None) -> list[dict[str, Any]]:
    """What each batch covers, small enough for the state machine to carry: batch 0 is the relays and the
    first others (sent by the deliver step itself); every later batch is a range of ids (first..last) of
    people who are not relays, at most `size` of them, so its worker reads only those rows. With more
    relays than one batch holds, every batch is named by its position instead."""
    s = get_settings()
    size = size or s.delivery_batch_size
    rest = people[size:]
    if any(r.is_relay for r in rest):  # more relays than one batch: every batch by position
        return [{"batch": b} for b in range(batch_count(len(people), size))]
    specs: list[dict[str, Any]] = [{"batch": 0}]
    if not rest:
        return specs
    # The others in equal batches, a multiple of the workers running at once, so no worker idles at the
    # end while one finishes a full batch alone (each worker sends at 1/n of the rate).
    n = batch_count(len(rest), size)
    n = min(len(rest), -(-n // s.delivery_concurrency) * s.delivery_concurrency)
    per = -(-len(rest) // n)
    for b in range(1, -(-len(rest) // per) + 1):
        chunk = rest[(b - 1) * per:b * per]
        specs.append({"batch": b, "first": chunk[0].id, "last": chunk[-1].id})
    return specs


def batch_people(repo: Repo, alert: Alert, spec: dict[str, Any]) -> list[Recipient]:
    """The recipients of one batch: a range read (relays skipped: they went first, in batch 0), or the
    slice of the whole ordered list when the batch is named by position."""
    if spec.get("first") and spec.get("last"):
        return [r for r in repo.list_recipients_between(alert.village_id, spec["first"], spec["last"])
                if not r.is_relay and _same_world(alert, r)]
    size = get_settings().delivery_batch_size
    b = int(spec.get("batch") or 0)
    return ordered_recipients(repo, alert)[b * size:(b + 1) * size]


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


def prepare(repo: Repo, alert: Alert, people: list[Recipient]) -> Alert:
    """Once per alert, before any batch: the call audio, if anyone takes calls. Batch workers reuse it."""
    if any("voice" in _channels(r, alert) for r in people):
        return _call_audio(repo, alert)
    return alert


def _telegram_audio(repo: Repo, alert: Alert) -> bytes | str | None:
    """The alert audio for Telegram: the file id of the first upload when there is one, else the MP3."""
    if not alert.audio_key:
        return None
    file_id = repo.get_telegram_file(alert.id)
    if file_id:
        return file_id
    try:
        data, _ = storage.get_bytes(alert.audio_key)
        return data
    except Exception as exc:
        log(_LOG, "audio unavailable; sending text", 30, alert_id=alert.id, error=str(exc)[:200])
        return None


class _Audio:
    """The MP3 until Telegram has it once, then the file id it gave back: one upload per alert."""

    def __init__(self, repo: Repo, alert_id: str, value: bytes | str | None) -> None:
        self.repo, self.alert_id, self.value = repo, alert_id, value
        self._lock = threading.Lock()

    @property
    def needs_upload(self) -> bool:
        return isinstance(self.value, (bytes, bytearray))

    def learn(self, message: Any) -> None:
        file_id = telegram.audio_file_id(message)
        if file_id and self.needs_upload:
            with self._lock:
                if self.needs_upload:
                    self.value = self.repo.put_telegram_file(self.alert_id, file_id)


def round_limiters(share: int) -> tuple[RateLimiter, RateLimiter]:
    """(Telegram, voice) limiters for one round: 1/share of the overall rates, share being the number of
    batches running at once. Each batch worker is its own Lambda, so the shares add up to the limit."""
    s = get_settings()
    share = max(1, share)
    # No burst: n workers starting together must not send n bursts in the same second. On AWS each Telegram
    # slot is also taken from the bot's budget shared by every Lambda (telegram.shared_bucket), so another
    # village's alert running at the same time never adds its own full rate on top of this one's.
    return (RateLimiter(s.telegram_rate_per_second / share, burst=1,
                        per_key_interval=s.telegram_chat_interval_seconds, shared=telegram.shared_bucket()),
            RateLimiter(s.voice_calls_per_second / share, burst=1))


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


@dataclass
class RoundResult:
    """One delivery round over some recipients, in people (a voice call counts once the provider took it)."""

    sent: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    deferred: int = 0  # sends put back unsent: Telegram said 429, or the step ran out of time
    retry_after: float = 0.0  # the longest wait Telegram asked for

    def as_dict(self) -> dict[str, Any]:
        return {"sent": len(self.sent), "failed": len(self.failed - self.sent), "deferred": self.deferred,
                "retry_after": self.retry_after}


@dataclass
class _Item:
    recipient: Recipient
    channel: str
    prior: Delivery | None
    carry: dict


@dataclass
class _Round:
    repo: Repo
    alert: Alert
    send_round: int
    deadline: float | None
    audio: _Audio | None
    result: RoundResult
    tg_slots: RateLimiter
    voice_slots: RateLimiter
    lock: threading.Lock = field(default_factory=threading.Lock)

    def out_of_time(self, wait: float = 0.0) -> bool:
        return self.deadline is not None and time.monotonic() + wait > self.deadline

    def record(self, person: str, outcome: str, retry_after: float) -> None:
        with self.lock:
            if outcome == "sent":
                self.result.sent.add(person)
            elif outcome == "failed":
                self.result.failed.add(person)
            elif outcome == "deferred":
                self.result.deferred += 1
            self.result.retry_after = max(self.result.retry_after, retry_after)


def round_for(alert: Alert, action: str, recall: bool) -> int:
    if recall:
        return max(1, alert.recall_rounds)
    return ROUND_FAILSAFE if action == "failsafe" else ROUND_DELIVER


def deliver(repo: Repo, alert: Alert, *, action: str = "deliver", recall: bool = False) -> tuple[int, int]:
    """Everyone, in this process (a small village, the tests, the local runner). Returns (sent, failed),
    counted in people. action is deliver, auto_send or failsafe.

    A voice call counts as sent here once the provider accepted it; the delivery row says "sent"
    only when the call is answered (delivery/ivr.py).
    """
    res = deliver_round(repo, alert, action=action, recall=recall)
    return len(res.sent), len(res.failed - res.sent)


def deliver_round(repo: Repo, alert: Alert, *, action: str = "deliver", recall: bool = False,
                  batch: int | None = None, recipients: list[Recipient] | None = None,
                  spec: dict[str, Any] | None = None, deadline: float | None = None, share: int = 1) -> RoundResult:
    """One round of sends over everyone (batch None) or one batch: spec (batch_specs) names it, or batch
    is its position in the ordered recipients (given, or read).

    deadline (time.monotonic): sends not started by then are put back unsent, for the next pass.
    share: how many batch workers run at once; this one takes 1/share of the overall rates.
    """
    s = get_settings()
    send_round = round_for(alert, action, recall)
    if spec is not None:
        batch = int(spec.get("batch") or 0)
        people = batch_people(repo, alert, spec)
    else:
        people = recipients if recipients is not None else ordered_recipients(repo, alert)
        if batch is not None:
            people = people[batch * s.delivery_batch_size:(batch + 1) * s.delivery_batch_size]
    result = RoundResult()
    if not people:
        return result
    if batch is None:
        alert = prepare(repo, alert, people)
    rows_list = repo.get_deliveries(alert.id, [r.id for r in people]) if batch is not None \
        else repo.list_deliveries(alert.id)
    rows = {(d.recipient_id, _slot(d.channel)): d for d in rows_list}
    acked = {d.recipient_id for d in rows_list if d.acknowledged_at}

    now = clock.now()
    work: list[_Item] = []
    for r in people:
        for channel in _channels(r, alert):
            prior = rows.get((r.id, _slot(channel)))
            if prior is not None and prior.send_round == send_round and not prior.deferred:
                continue  # done in this round already (an earlier pass, or a retried batch)
            carry: dict = {}
            if recall:
                if prior is None or r.id in acked:
                    continue
                if channel == "voice":
                    due, carry = _voice_due(prior, now)
                    if not due:
                        continue
                elif prior.attempts >= TELEGRAM_MAX_ATTEMPTS:
                    continue
            elif prior is not None and prior.status in REACHED | {"pending"}:
                continue  # idempotent: never send the same alert twice to one person
            work.append(_Item(r, channel, prior, carry))
    if not work:
        return result

    # One policy decision (and audit row) per channel per round; the per-village guard once per round.
    decisions: dict[str, Any] = {}
    guard = None
    ready: list[_Item] = []
    village = repo.get_village(alert.village_id, include_demo=True)
    demo = {"demo": bool((alert.decision_trace or {}).get("demo")), "village_demo": bool(village and village.demo)}
    for item in work:
        ch = item.channel
        if ch not in decisions:
            ctx = {"approved": alert.approved, "level": alert.level, "replay": alert.replay, "channel": ch,
                   "all_officers_timed_out": alert.status == "auto_sent_unapproved", **demo}
            decisions[ch] = authorize(SYSTEM, action, "alert", alert.id, ctx, repo=repo)
        decision = decisions[ch]
        if decision.allowed and guard is None:
            guard = check_send(alert.village_id, alert.level, alert.id)
        if decision.allowed and guard is not None and guard.accepted:
            ready.append(item)
            continue
        reason = decision.reason if not decision.allowed else guard.reason  # type: ignore[union-attr]
        repo.put_delivery(Delivery(alert_id=alert.id, recipient_id=item.recipient.id, name=item.recipient.name,
                                   channel=ch, status="failed", attempts=(item.prior.attempts if item.prior else 0) + 1,
                                   error=f"blocked: {reason}", send_round=send_round,
                                   error_category="blocked" if ch == "voice" else None))
        result.failed.add(item.recipient.id)
        metric("DeliveryFailed", 1, Channel=ch)

    audio = None
    if any(i.channel == "telegram" for i in ready):
        telegram.configured()  # read the token once here, before any thread needs it
        audio = _Audio(repo, alert.id, _telegram_audio(repo, alert))
    rd = _Round(repo, alert, send_round, deadline, audio, result, *round_limiters(share))
    relays = [i for i in ready if i.recipient.is_relay]
    rest = [i for i in ready if not i.recipient.is_relay]
    for item in relays:  # the cascade: the relays first, in order
        _attempt(rd, item)
    uploads = 0  # until Telegram has the audio once, one Telegram send at a time
    while audio is not None and audio.needs_upload and uploads < 3:
        nxt = next((i for i in rest if i.channel == "telegram"), None)
        if nxt is None:
            break
        rest.remove(nxt)
        _attempt(rd, nxt)
        uploads += 1
    threads = min(s.delivery_threads, len(rest))
    if threads > 1:
        with ThreadPoolExecutor(max_workers=threads, thread_name_prefix=f"send-{alert.id[-6:]}") as pool:
            list(pool.map(lambda i: _attempt(rd, i), rest))
    else:
        for item in rest:
            _attempt(rd, item)
    log(_LOG, "delivery round", alert_id=alert.id, batch=batch, round=send_round, sent=len(result.sent),
        failed=len(result.failed - result.sent), deferred=result.deferred, recall=recall)
    return result


def _attempt(rd: _Round, item: _Item) -> None:
    token = telegram.send_deadline.set(rd.deadline)
    slots = telegram.send_limiter.set(rd.tg_slots)
    try:
        if item.channel == "voice":
            outcome, retry = _place_call(rd, item)
        else:
            outcome, retry = _send_other(rd, item)
    except Exception as exc:  # never lose the rest of the batch to one row
        log(_LOG, "send error", 40, alert_id=rd.alert.id, channel=item.channel, error=voice.mask(str(exc))[:200])
        outcome, retry = "failed", 0.0
    finally:
        telegram.send_deadline.reset(token)
        telegram.send_limiter.reset(slots)
    rd.record(item.recipient.id, outcome, retry)


def _claim(rd: _Round, item: _Item) -> Delivery | None:
    try:
        return rd.repo.claim_delivery(rd.alert.id, item.recipient.id, item.channel, name=item.recipient.name,
                                      expected_attempts=item.prior.attempts if item.prior else None,
                                      send_round=rd.send_round)
    except ConflictError:
        log(_LOG, "send already claimed", alert_id=rd.alert.id, channel=item.channel)
        return None


def _write(rd: _Round, item: _Item, **fields: Any) -> Delivery:
    """Record the outcome without undoing an acknowledgement that arrived while the send was in flight.
    A row that now says "sent" counts its person as reached, once (count_reached)."""
    repo, alert_id, rid, ch = rd.repo, rd.alert.id, item.recipient.id, item.channel
    try:
        d = repo.update_delivery(alert_id, rid, channel=ch, condition=Attr("acknowledged_at").not_exists(), **fields)
    except ConflictError:
        fields.pop("status", None)
        d = repo.update_delivery(alert_id, rid, channel=ch, **fields)
    if d.status in REACHED:
        count_reached(repo, alert_id, rid, ch)
    return d


def _defer(rd: _Round, item: _Item, claimed: Delivery, reason: str) -> str:
    """Put the send back unsent: the next pass sends it. Never "sent"."""
    status = "failed" if claimed.status == "pending" and item.prior is None else claimed.status
    rd.repo.release_delivery(rd.alert.id, item.recipient.id, item.channel, claimed_attempts=claimed.attempts,
                             status=status, error=f"queued, not sent: {reason}"[:200])
    metric("DeliveryDeferred", 1, Channel=item.channel)
    return "deferred"


def _send_other(rd: _Round, item: _Item) -> tuple[str, float]:
    """Telegram, or the stub. A replay's voice recipient goes through the stub voice provider, which says so."""
    alert, r, channel = rd.alert, item.recipient, item.channel
    claimed = _claim(rd, item)
    if claimed is None:
        return "skipped", 0.0
    if rd.out_of_time():
        return _defer(rd, item, claimed, "out of time in this step"), 0.0
    provider, retry = None, 0.0
    for tries in range(1, RATE_LIMIT_TRIES + 1):
        try:
            if channel == "telegram":
                message = _send_telegram(alert, r, rd.audio.value if rd.audio else None)
                if rd.audio is not None:
                    rd.audio.learn(message)
            else:
                if r.takes_voice:
                    provider = voice.place_call(r, alert, None, attempt=claimed.attempts).provider  # replay: the stub
                log(_LOG, "stub delivery", alert_id=alert.id, recipient=r.id, replay=alert.replay)
            break
        except telegram.TelegramRateLimited as exc:
            retry = max(retry, exc.retry_after)
            if tries < RATE_LIMIT_TRIES and not rd.out_of_time(exc.retry_after):
                continue  # the limiter holds every sender of this process for retry_after, then this one tries again
            return _defer(rd, item, claimed, str(exc)), retry
        except telegram.TelegramDeferred:
            return _defer(rd, item, claimed, "out of time in this step"), retry
        except Exception as exc:
            # A person reached by an earlier send stays reached; the error is kept on the row.
            _write(rd, item, status="failed" if not claimed.sent_at else claimed.status,
                   error=voice.mask(str(exc))[:200], deferred=False)
            metric("DeliveryFailed", 1, Channel=channel)
            return "failed", retry
    # a re-send keeps the first send time: "when did the alert first reach this phone" must not move
    _write(rd, item, status="sent", sent_at=claimed.sent_at or clock.iso(clock.now()), provider=provider,
           call_status="simulated" if provider == "stub" else claimed.call_status, error=None, deferred=False)
    metric("DeliverySent", 1, Channel=channel)
    return "sent", retry


def _place_call(rd: _Round, item: _Item) -> tuple[str, float]:
    alert, r = rd.alert, item.recipient
    claimed = _claim(rd, item)
    if claimed is None:
        return "skipped", 0.0
    if not alert.replay and not rd.voice_slots.acquire(deadline=rd.deadline):
        return _defer(rd, item, claimed, "out of time in this step"), 0.0
    fields: dict[str, Any] = dict(last_attempt_at=clock.iso(clock.now()), digit=None, repeats=0, reprompts=0,
                                  **item.carry)
    try:
        attempt = voice.place_call(r, alert, None, attempt=claimed.attempts)
    except voice.VoiceError as exc:
        d = _write(rd, item, **{**fields, "status": "failed", "error": str(exc)[:200], "error_category": exc.category,
                                "call_status": None, "deferred": False})
        log(_LOG, "call not placed", 30, alert_id=alert.id, recipient=r.id, category=exc.category, error=str(exc)[:200])
        if exc.category in voice.NOT_CONNECTED:
            metric("VoiceNotConnected", 1, Category=exc.category)
        else:
            metric("DeliveryFailed", 1, Channel="voice")
        if exc.category == "invalid_number":
            flag_unreachable(rd.repo, alert, d)
        return "failed", 0.0
    # Answered on an earlier attempt (no key pressed): still reached; otherwise ringing.
    _write(rd, item, status="sent" if claimed.sent_at or attempt.simulated else "pending", provider=attempt.provider,
           call_ids=list(claimed.call_ids) + ([attempt.call_id] if attempt.call_id else []),
           call_status=attempt.status, error=None, deferred=False, **fields)  # error_category keeps the last outcome
    log(_LOG, "call placed", alert_id=alert.id, recipient=r.id, provider=attempt.provider, attempt=claimed.attempts)
    metric("VoiceCallPlaced", 1, Provider=attempt.provider)
    return "sent", 0.0


def voice_retry_due(repo: Repo, alert: Alert) -> bool:
    """Is any voice call still worth another round? (the workflow loops on this, bounded by recall_rounds)"""
    if alert.replay:
        return False
    rows = repo.list_deliveries(alert.id)
    acked = {d.recipient_id for d in rows if d.acknowledged_at}
    s = get_settings()
    return any(d.channel == "voice" and d.recipient_id not in acked and not d.unreachable
               and d.attempts < s.voice_max_attempts and d.error_category not in voice.TERMINAL
               for d in rows)


PHONE_CHANNELS = {"telegram", "voice"}  # a real phone; the "stub" channel of demo recipients is not one


def count_reached(repo: Repo, alert_id: str, recipient_id: str, channel: str) -> bool:
    """Count a person reached, once however many rows, rounds or workers report it: an idempotent marker, and
    an atomic ADD by whoever created it (Repo.mark_person). A real phone also counts in phones_reached_count.
    O(1) per send: nothing reads the alert's other rows. True when a counter moved."""
    return repo.mark_person(alert_id, recipient_id, "reached", phone=channel in PHONE_CHANNELS)


def repair_counts(repo: Repo, alert_id: str, *, emit: bool = True) -> Alert | None:
    """The full recount, for repair and audit: delivered_count, phones_reached_count and acknowledged_count
    from the delivery rows themselves, in people (a "both" recipient counts once).

    It never races an acknowledgement: the person markers missing for a reached or acknowledged row are
    written first (without moving a counter), then each counter is set to its number of markers only if the
    counter still holds the value read (a conditional write, tried again when an ADD landed in between).
    Run once at the end of each delivery round (workflow/steps.py), and by hand: it reads every row of the
    alert, so it is never on the path of a single tap."""
    alert = repo.get_alert(alert_id)
    if alert is None:
        return None
    rows = repo.list_deliveries(alert_id)
    truth = {"reached": {d.recipient_id for d in rows if d.status in REACHED},
             "phone": {d.recipient_id for d in rows if d.status in REACHED and d.channel in PHONE_CHANNELS},
             "acked": {d.recipient_id for d in rows if d.acknowledged_at}}
    for kind, people in truth.items():
        for rid in people - repo.list_markers(alert_id, kind):
            repo.put_marker(alert_id, rid, kind, phone=rid in truth["phone"])
    for _ in range(5):
        current = repo.get_alert(alert_id)
        if current is None:
            return None
        seen = {f: int(getattr(current, f) or 0) for f in Repo.COUNTER_FIELDS.values()}
        new = {f: len(repo.list_markers(alert_id, kind)) for kind, f in Repo.COUNTER_FIELDS.items()}
        if new == seen:
            alert = current
            break
        updated = repo.set_counts_if_unchanged(alert_id, seen, new)
        if updated is not None:
            alert = updated
            log(_LOG, "counts repaired", 30, alert_id=alert_id, before=seen, after=new)
            metric("CountsRepaired", 1)
            break
    if emit:
        from Pukaar.services import events

        events.counts_changed(alert)
    return alert


recount = repair_counts  # the earlier name; callers on the hot path use count_reached and acknowledge


def acknowledge(repo: Repo, alert_id: str, recipient_id: str, channel: str = "") -> Delivery | None:
    """Record an acknowledgement once; a repeated tap (or key press) changes nothing.

    channel "voice" acknowledges the person's call row (delivery/ivr.py); anything else their
    Telegram (or stub) row. Either stops further re-sends to that person on every channel.

    O(1) whatever the size of the alert: the row's own conditional write (acknowledged_at not yet set) is
    the idempotent transition, and the person is counted by an atomic ADD with a marker (Repo.mark_person),
    so concurrent taps never overwrite each other's count and a "both" person counts once.
    """
    try:
        d = repo.update_delivery(alert_id, recipient_id, channel=channel, condition=Attr("acknowledged_at").not_exists(),
                                 acknowledged_at=clock.iso(clock.now()), status="acknowledged")
    except ConflictError:
        return None
    moved = repo.mark_person(alert_id, recipient_id, "acked")
    moved = count_reached(repo, alert_id, recipient_id, d.channel) or moved  # an ack means it reached them
    if moved:
        from Pukaar.services import events

        alert = repo.get_alert(alert_id)
        if alert is not None:
            events.counts_changed(alert)
    _relay_done(repo, alert_id, d)
    return d


def _relay_done(repo: Repo, alert_id: str, d: Delivery) -> None:
    """A relay's acknowledgement means the village has been told by siren and megaphone. Never raises."""
    try:
        alert = repo.get_alert(alert_id)
        person = repo.get_recipient(alert.village_id, d.recipient_id) if alert else None
        if person is None or not person.is_relay:
            return
        if any(x.recipient_id == d.recipient_id and x.channel != d.channel and x.acknowledged_at
               for x in repo.get_deliveries(alert_id, [d.recipient_id])):
            return  # a "both" relay already acknowledged on the other channel: recorded once
        repo.add_timeline(alert_id, "relay_done", hi.relay_done_detail(person.name, person.role, d.channel))
        metric("RelayDone", 1)
    except Exception as exc:
        log(_LOG, "relay-done record failed", 30, alert_id=alert_id, error=str(exc)[:200])


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
        flag = " [REPLAY]" if alert.replay else " [DEMO]" if alert.decision_trace.get("demo") else ""
        telegram.send_text(chat_id, f"पुकार{flag}: {alert.village_name_hi} – {hi.LEVEL_HI[alert.level]}\n"
                                    f"{alert.text_hi}\n\nApprove / decline: {approve_url}")
        return True
    except Exception as exc:
        log(_LOG, "officer notify failed", 30, alert_id=alert.id, error=str(exc)[:200])
        return False
