""""Surakshit Hoon" (मैं सुरक्षित हूँ): a one-tap safety roll-call after a flood alert.

After a flood, calls from relatives jam the towers that still stand. One tap,
"I am safe" or "I need help", frees those lines and tells the officer who has
not checked in and who needs help (the idea of Facebook's Safety Check).

- Opens by itself when a live warning or critical alert closes after reaching
  phones (delivered, auto-sent or failsafe). Never for a replay (Cedar forbids
  it as well); a drill opens an exercise roll-call, labelled as one.
- An officer, or the pradhan of the village, can open one by hand.
- Stays open 48 hours; the records expire after 30 days.
- Each person's last answer wins; tapping the same button twice changes nothing.
- "Safe" gives a family link (signed, 7 days) that shows only a first name,
  the time and the village. The link carries an opaque share id, never the
  Telegram chat id.
- Stub (demo) recipients have no phone: nothing is sent to them, and only
  simulate_stub_answer() (tests and demo tooling) can answer for them, marked
  simulated=True so it is never shown as a real tap.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from boto3.dynamodb.conditions import Attr

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.core.log import get_logger, log, metric
from Pukaar.delivery import telegram
from Pukaar.policy.guard import SYSTEM, Principal, authorize
from Pukaar.services import events
from Pukaar.store.models import Alert, AuditRow, Recipient, RollCall, RollCallAsked, RollCallResponse, Village
from Pukaar.store.repo import ConflictError, Repo
from Pukaar.templates import hi
from Pukaar.workflow import tokens

_LOG = get_logger("rollcall")

OPEN_HOURS = 48
REMIND_EVERY_SECONDS = 30 * 60
SHARE_TTL_SECONDS = 7 * 24 * 3600
NOTE_MAX = 140
ROLLCALL_LEVELS = {"warning", "critical"}
OPEN_AFTER_STATUSES = {"delivered", "auto_sent_unapproved", "failsafe"}


class RollCallError(Exception):
    """code: denied | already_open | closed | rate_limited | missing."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.extra = extra


@dataclass
class AnswerResult:
    outcome: str  # recorded | same | closed | not_asked | missing
    rollcall: RollCall | None = None
    response: RollCallResponse | None = None
    share_link: str | None = None


# -- reading -------------------------------------------------------------------
def is_open(rc: RollCall, now: Any = None) -> bool:
    return (now or clock.now()) < clock.parse(rc.closes_at)


def current_open(repo: Repo, village_id: str) -> RollCall | None:
    latest = repo.list_rollcalls(village_id, limit=1)
    return latest[0] if latest and is_open(latest[0]) else None


def _channel(r: Recipient) -> str:
    return "telegram" if r.channel == "telegram" and telegram.configured() else "stub"


def _first_name(name: str) -> str | None:
    word = (name or "").strip().split(" ")[0][:40] if name else ""
    return word if word and name != "Telegram user" else None


def share_link(rollcall_id: str, share_id: str) -> str:
    token = tokens.sign(rollcall_id, share_id, 0, "safe", ttl=SHARE_TTL_SECONDS)
    return f"{get_settings().web_url}/safe/{token}"


# -- asking ----------------------------------------------------------------------
def _ask(repo: Repo, rc: RollCall, recipients: list[Recipient], *, reminder: bool = False,
         previous: dict[str, RollCallAsked] | None = None) -> int:
    """Send the question; record who was asked. Returns how many Telegram messages went out."""
    text = hi.rollcall_question(rc.village_name_hi, rc.village_name, rc.exercise)
    now = clock.iso(clock.now())
    sent = 0
    for r in recipients:
        channel = _channel(r)
        error = None
        if channel == "telegram":
            try:
                telegram.send_rollcall(r.id, rc.id, text)
                sent += 1
            except Exception as exc:
                error = str(exc)[:200]
                log(_LOG, "roll-call send failed", 30, rollcall_id=rc.id, error=error)
        prior = (previous or {}).get(r.id)
        repo.put_rollcall_asked(RollCallAsked(
            rollcall_id=rc.id, recipient_id=r.id, name=r.name, channel=channel,  # type: ignore[arg-type]
            asked_at=prior.asked_at if prior else now, reminded_at=now if reminder else None, error=error))
    return sent


def open_rollcall(repo: Repo, village: Village, *, principal: Principal = SYSTEM, alert: Alert | None = None,
                  exercise: bool = False) -> RollCall:
    """Cedar decides (open_rollcall); an open roll-call for the village is reused, not doubled."""
    level = alert.level if alert else village.level
    replay = bool(village.replay or (alert.replay if alert else False))
    decision = authorize(principal, "open_rollcall", "village", village.id,
                         {"village_id": village.id, "level": level, "replay": replay}, repo=repo)
    if not decision.allowed:
        raise RollCallError("denied", decision.reason)
    existing = current_open(repo, village.id)
    if existing is not None:
        raise RollCallError("already_open", "A roll-call is already open for this village.", rollcall_id=existing.id)
    now = clock.now()
    officer = principal.role in {"officer", "pradhan"}
    rc = RollCall(id=new_id("rc"), village_id=village.id, village_name=village.name, village_name_hi=village.name_hi,
                  alert_id=alert.id if alert else None, level=level, opened_at=clock.iso(now),
                  closes_at=clock.iso(now + timedelta(hours=OPEN_HOURS)),
                  opened_by="officer" if officer else "system", opened_by_user=principal.username if officer else None,
                  exercise=exercise)
    repo.put_rollcall(rc)
    recipients = repo.list_recipients(village.id)
    sent = _ask(repo, rc, recipients)
    rc = repo.update_rollcall(rc.id, asked=len(recipients))
    events.rollcall_changed(rc)
    if alert is not None:
        repo.add_timeline(alert.id, "rollcall_opened",
                          f"{'exercise ' if exercise else ''}roll-call {rc.id}: asked {len(recipients)}, "
                          f"telegram messages {sent}")
    log(_LOG, "roll-call opened", rollcall_id=rc.id, village_id=village.id, asked=len(recipients), sent=sent,
        exercise=exercise, by=principal.username)
    return rc


def open_after_alert(repo: Repo, alert: Alert, status: str) -> RollCall | None:
    """Called by the workflow's close step. Live alerts only; a drill opens an exercise roll-call."""
    if alert.replay or alert.level not in ROLLCALL_LEVELS or status not in OPEN_AFTER_STATUSES:
        return None
    if alert.delivered_count <= 0:
        return None
    village = repo.get_village(alert.village_id)
    if village is None:
        return None
    try:
        return open_rollcall(repo, village, alert=alert, exercise=bool(alert.decision_trace.get("drill")))
    except RollCallError as exc:
        log(_LOG, "roll-call not opened", alert_id=alert.id, reason=str(exc), code=exc.code)
        return None


def remind(repo: Repo, rc: RollCall) -> dict[str, Any]:
    """Ask again everyone who has not answered. At most once per 30 minutes per roll-call (conditional write).
    The caller has already passed Cedar (remind_rollcall)."""
    now = clock.now()
    if not is_open(rc, now):
        raise RollCallError("closed", "This roll-call has closed.")
    cutoff = clock.iso(now - timedelta(seconds=REMIND_EVERY_SECONDS))
    try:
        rc = repo.update_rollcall(rc.id, condition=Attr("last_reminded_at").not_exists() | Attr("last_reminded_at").lte(cutoff),
                                  last_reminded_at=clock.iso(now), reminders=rc.reminders + 1)
    except ConflictError:
        current = repo.get_rollcall(rc.id) or rc
        last = clock.parse(current.last_reminded_at) if current.last_reminded_at else now
        wait = max(1, int((last + timedelta(seconds=REMIND_EVERY_SECONDS) - now).total_seconds()))
        raise RollCallError("rate_limited", "A reminder was sent less than 30 minutes ago.",
                            retry_after_seconds=wait) from None
    answered = {r.recipient_id for r in repo.list_rollcall_responses(rc.id)}
    asked = {a.recipient_id: a for a in repo.list_rollcall_asked(rc.id)}
    by_id = {r.id: r for r in repo.list_recipients(rc.village_id)}
    waiting = [by_id[i] for i in asked if i not in answered and i in by_id]
    sent = _ask(repo, rc, waiting, reminder=True, previous=asked)
    log(_LOG, "roll-call reminder", rollcall_id=rc.id, waiting=len(waiting), sent=sent)
    no_phone = sum(1 for r in waiting if _channel(r) != "telegram")
    return {"reminded": sent, "waiting": len(waiting), "demo_without_phone": no_phone,
            "last_reminded_at": rc.last_reminded_at}


# -- answering -------------------------------------------------------------------
def _recount(repo: Repo, rollcall_id: str) -> RollCall:
    responses = repo.list_rollcall_responses(rollcall_id)
    return repo.update_rollcall(rollcall_id, safe=sum(1 for r in responses if r.status == "safe"),
                                need_help=sum(1 for r in responses if r.status == "need_help"))


def _tell_officers(repo: Repo, rc: RollCall, response: RollCallResponse) -> None:
    if response.simulated or not telegram.configured():
        return
    village = repo.get_village(rc.village_id)
    note = f"\nसंदेश / note: {response.note}" if response.note else ""
    drill = " [DRILL]" if rc.exercise else ""
    text = (f"पुकार रोल-कॉल{drill}: {rc.village_name_hi} में {response.name} को मदद चाहिए।{note}\n"
            f"Roll-call{drill}: {response.name} in {rc.village_name} needs help.\n"
            f"{get_settings().web_url}/console#rollcall")
    for officer in (village.officers if village else []):
        chat = repo.get_officer_chat(officer)
        if not chat:
            continue
        try:
            telegram.send_text(chat, text)
        except Exception as exc:
            log(_LOG, "officer help notice failed", 30, rollcall_id=rc.id, error=str(exc)[:200])


def answer(repo: Repo, rollcall_id: str, recipient_id: str, status: str, *, simulated: bool = False) -> AnswerResult:
    if status not in {"safe", "need_help"}:
        raise ValueError(f"unknown answer {status!r}")
    rc = repo.get_rollcall(rollcall_id)
    if rc is None:
        return AnswerResult("missing")
    asked = repo.get_rollcall_asked(rollcall_id, recipient_id)
    if asked is None:
        return AnswerResult("not_asked", rc)
    if simulated and asked.channel != "stub":
        raise ValueError("only a stub (demo) recipient can have a simulated answer")
    if not is_open(rc):
        return AnswerResult("closed", rc)
    prior = repo.get_rollcall_response(rollcall_id, recipient_id)
    share_id = None
    if status == "safe":
        share_id = (prior.share_id if prior and prior.share_id else None) or secrets.token_urlsafe(12)
    response = RollCallResponse(rollcall_id=rollcall_id, recipient_id=recipient_id, name=asked.name,
                                status=status, at=clock.iso(clock.now()), share_id=share_id,  # type: ignore[arg-type]
                                simulated=simulated)
    if not repo.put_rollcall_response(response):
        current = repo.get_rollcall_response(rollcall_id, recipient_id)
        return AnswerResult("same", rc, current)
    if share_id:
        repo.put_safe_share(share_id, rollcall_id, recipient_id, SHARE_TTL_SECONDS)
    rc = _recount(repo, rollcall_id)
    link = share_link(rollcall_id, share_id) if share_id else None
    if status == "need_help":
        metric("RollCallNeedHelp", 1, Village=rc.village_id)
        repo.append_audit(AuditRow(
            at=clock.iso(clock.now()), id=new_id("aud"), actor="villager" + (" (simulated)" if simulated else ""),
            role="villager", action="rollcall_need_help", resource=f"rollcall:{rc.id}", decision="allow",
            reason=f"{asked.name} pressed 'मदद चाहिए' (need help) in {rc.village_name}; officers told on the "
                   "roll-call board" + (" (exercise)" if rc.exercise else "")))
        _tell_officers(repo, rc, response)
    events.rollcall_changed(rc, need_help=status == "need_help")
    log(_LOG, "roll-call answer", rollcall_id=rc.id, status=status, simulated=simulated)
    return AnswerResult("recorded", rc, response, link)


def simulate_stub_answer(repo: Repo, rollcall_id: str, recipient_id: str, status: str) -> AnswerResult:
    """Tests and demo tooling only: answer for a stub recipient, marked simulated."""
    return answer(repo, rollcall_id, recipient_id, status, simulated=True)


def add_note(repo: Repo, chat_id: str, text: str) -> bool:
    """The next plain message after "need help" (within an hour) becomes the note, 140 characters at most."""
    rollcall_id = repo.consume_help_note_wait(chat_id)
    if rollcall_id is None:
        return False
    prior = repo.get_rollcall_response(rollcall_id, chat_id)
    rc = repo.get_rollcall(rollcall_id)
    if prior is None or rc is None or prior.status != "need_help":
        return False
    note = " ".join(text.split())[:NOTE_MAX]
    updated = repo.update_rollcall_response(rollcall_id, chat_id, note=note)
    _tell_officers(repo, rc, updated)
    return True


# -- views -----------------------------------------------------------------------
def summary(rc: RollCall) -> dict[str, Any]:
    out = rc.model_dump()
    out["open"] = is_open(rc)
    out["not_answered"] = max(rc.asked - rc.safe - rc.need_help, 0)
    return out


def public_summary(rc: RollCall | None) -> dict[str, Any] | None:
    """Counts only: no names, no ids, no phone numbers."""
    if rc is None:
        return None
    return {"open": is_open(rc), "exercise": rc.exercise, "asked": rc.asked, "safe": rc.safe,
            "need_help": rc.need_help, "not_answered": max(rc.asked - rc.safe - rc.need_help, 0),
            "opened_at": rc.opened_at, "closes_at": rc.closes_at}


def public_for_village(repo: Repo, village_id: str) -> dict[str, Any] | None:
    return public_summary(current_open(repo, village_id))


def board(repo: Repo, rc: RollCall) -> dict[str, Any]:
    """The officer's board: need help first, then safe, then who has not answered. Names and times only."""
    responses = {r.recipient_id: r for r in repo.list_rollcall_responses(rc.id)}
    asked = repo.list_rollcall_asked(rc.id)
    help_rows = sorted((r for r in responses.values() if r.status == "need_help"), key=lambda r: r.at)
    safe_rows = sorted((r for r in responses.values() if r.status == "safe"), key=lambda r: r.at, reverse=True)
    waiting = sorted((a for a in asked if a.recipient_id not in responses), key=lambda a: a.name)
    return {
        "rollcall": summary(rc),
        "need_help": [{"name": r.name, "at": r.at, "note": r.note, "simulated": r.simulated} for r in help_rows],
        "safe": [{"name": r.name, "at": r.at, "simulated": r.simulated} for r in safe_rows],
        "not_answered": [{"name": a.name, "demo": a.channel == "stub", "asked_at": a.asked_at,
                          "reminded_at": a.reminded_at, "failed": bool(a.error)} for a in waiting],
        "remind_every_seconds": REMIND_EVERY_SECONDS,
    }


class NotCurrent(Exception):
    pass


def safe_view(repo: Repo, token: str) -> dict[str, Any]:
    """What a family link shows: a first name (or nothing), the time, the village. Raises tokens.TokenError
    for a forged or expired link and NotCurrent when the person no longer stands marked safe."""
    t = tokens.verify(token, "safe")
    pointer = repo.get_safe_share(t.subject)
    if pointer is None or pointer[0] != t.alert_id:
        raise NotCurrent("unknown share")
    rc = repo.get_rollcall(pointer[0])
    response = repo.get_rollcall_response(pointer[0], pointer[1])
    if rc is None or response is None or response.status != "safe" or response.share_id != t.subject:
        raise NotCurrent("no longer marked safe")
    return {"first_name": _first_name(response.name), "village_name": rc.village_name,
            "village_name_hi": rc.village_name_hi, "at": response.at, "status": "safe", "exercise": rc.exercise,
            "simulated": response.simulated}
