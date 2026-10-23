"""Consent, leaving, and erasure of villagers' personal data (DPDP Act 2023; docs/SECURITY.md, "DPDP").

Joining (Telegram): /start <village code> shows a notice in Hindi and English (what is kept, why, for how
long, how to leave) with an "I agree" button. Nothing about the person is stored before they press it; until
then only a one-day "waiting for consent" row holds the village they asked for. Pressing it stores the
recipient with a consent record (how, which notice version, when).

Leaving: /stop or "बंद करें" deletes the person's recipient record in every village at once, with their
chat-id rows (village pointers, a waiting consent or help note). No alert reaches them after that.

Erasure: what is left of a person once their last village link has gone is erased
Settings.unlinked_retention_days later (PUKAAR_UNLINKED_RETENTION_DAYS, 30 by default; 0 at the next sweep):

- their delivery rows of every alert of those villages are re-keyed under a random pseudonym, without name,
  chat id, call ids or key presses; channel, status, attempts and times stay, so the alert's counts and the
  authority's record of when it reached people are unchanged (the minimal audit data);
- their roll-call rows (asked, answered) are deleted;
- their phone number or chat id is replaced by "[removed]" wherever a villager report's words hold it;
- one audit row records the erasure under the pseudonym (the audit trail is append-only and never held a
  number; its rows name an officer's action, not a villager's chat id).

A person who joins again before their erasure runs keeps their records: the erasure is cancelled.

The sweep runs due erasures (run_due), at most MAX_PER_RUN a time, so a burst of leavers never eats the sweep.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.core.log import get_logger, log, metric
from Pukaar.store.models import AuditRow, Recipient, Village
from Pukaar.store.repo import Repo
from Pukaar.templates import hi

_LOG = get_logger("privacy")
MAX_PER_RUN = 50


def consent_record(now: datetime | None = None) -> str:
    """What Recipient.consent holds for a Telegram enrolment: how, which notice, when."""
    return f"telegram button, {hi.NOTICE_VERSION}, {clock.iso(now or clock.now())}"


def ask_consent(repo: Repo, chat_id: str, village: Village) -> str:
    """Remember which village the notice is for (one day), and return the notice. Stores nothing about the person."""
    repo.put_consent_wait(chat_id, village.id)
    return hi.enrol_notice(village.name_hi, village.name, village.district, get_settings().unlinked_retention_days)


def enrol(repo: Repo, chat_id: str, village: Village, name: str, now: datetime | None = None) -> Recipient:
    """After the button: the recipient, with the consent record. A pending erasure of this chat is cancelled."""
    existing = repo.get_recipient(village.id, chat_id)
    person = Recipient(id=chat_id, village_id=village.id, name=(name or "Telegram user")[:80], channel="telegram",
                       role=existing.role if existing else "villager", consent=consent_record(now))
    repo.put_recipient(person)
    for row in repo.list_erasures():
        if row.get("recipient_id") == chat_id:
            repo.delete_erasure(str(row["sk"]))
            log(_LOG, "erasure cancelled: the person joined again")
    return person


def _due(now: datetime) -> str:
    return clock.iso(now + timedelta(days=get_settings().unlinked_retention_days))


def stop(repo: Repo, chat_id: str, now: datetime | None = None, reason: str = "telegram /stop") -> list[Village]:
    """/stop or "बंद करें": the person leaves every village at once. Returns the villages they left."""
    now = now or clock.now()
    left: list[Village] = []
    needles = [chat_id]
    for vid in repo.chat_villages(chat_id):
        person = repo.get_recipient(vid, chat_id)
        if person is not None and person.phone:
            needles.append(person.phone)  # a "both" person: their number goes from the reports too
        if repo.delete_recipient(vid, chat_id):
            v = repo.get_village(vid)
            if v is not None:
                left.append(v)
    repo.delete_chat_rows(chat_id)
    if left:
        schedule(repo, chat_id, [v.id for v in left], reason, now, needles=sorted(set(needles)))
        log(_LOG, "recipient left", villages=len(left))
        metric("RecipientLeft", len(left))
    return left


def remove_recipient(repo: Repo, village_id: str, recipient_id: str, reason: str,
                     now: datetime | None = None) -> bool:
    """An officer or the CLI (scripts/voice.py remove) takes someone off one village. Their data is erased later
    when no village link is left."""
    now = now or clock.now()
    person = repo.get_recipient(village_id, recipient_id)
    if person is None or not repo.delete_recipient(village_id, recipient_id):
        return False
    if not repo.chat_villages(recipient_id):
        needles = [n for n in (person.phone, recipient_id if person.takes_telegram else None) if n]
        schedule(repo, recipient_id, [village_id], reason, now, needles=needles)
    return True


def schedule(repo: Repo, recipient_id: str, villages: list[str], reason: str, now: datetime,
             needles: list[str] | None = None) -> None:
    repo.put_erasure(recipient_id, villages, _due(now), reason, needles)


def _linked(repo: Repo, recipient_id: str, villages: list[str]) -> bool:
    """Registered again somewhere (the chat joined again, or the CLI added the number back)."""
    if repo.chat_villages(recipient_id):
        return True
    return any(repo.get_recipient(v, recipient_id) is not None for v in villages)


def _variants(needles: list[str]) -> list[str]:
    """A number as people write it: +919812345678, 919812345678, 9812345678 (longest first, so the whole
    number is replaced before a part of it)."""
    out: set[str] = set()
    for n in needles:
        out.add(n)
        if n.startswith("+"):
            out.add(n[1:])
            if len(n) > 11:
                out.add(n[-10:])
    return sorted(out, key=len, reverse=True)


def erase(repo: Repo, row: dict[str, Any], now: datetime | None = None) -> dict[str, int]:
    """Erase what is left of one person (see the module docstring). Idempotent: a re-run finds nothing to move."""
    now = now or clock.now()
    rid = str(row["recipient_id"])
    pseudonym = new_id("erased")
    moved = rollcalls = reports = 0
    for vid in row.get("villages") or []:
        for alert in repo.list_alerts(village_id=vid, limit=100_000):
            moved += repo.erase_alert_person(alert.id, rid, pseudonym)
        for rc in repo.list_rollcalls(vid, limit=1000):
            repo.delete_rollcall_person(rc.id, rid)
            rollcalls += 1
        reports += repo.redact_reports(vid, _variants([str(n) for n in (row.get("needles") or [])] + [rid]))
    repo.delete_chat_rows(rid)
    repo.append_audit(AuditRow(at=clock.iso(now), id=new_id("aud"), actor="pukaar-system", role="system",
                               action="erase_personal_data", resource=f"recipient:{pseudonym}", decision="allow",
                               reason=f"{row.get('reason') or 'unlinked'}; {moved} delivery rows pseudonymised, "
                                      f"{reports} reports redacted"))
    return {"rows": moved, "rollcalls": rollcalls, "reports": reports}


def run_due(repo: Repo, now: datetime | None = None) -> dict[str, int]:
    """The sweep's erasure pass: every erasure due by now (at most MAX_PER_RUN). Never raises."""
    now = now or clock.now()
    done = cancelled = failed = 0
    try:
        rows = repo.due_erasures(clock.iso(now))[:MAX_PER_RUN]
    except Exception as exc:
        log(_LOG, "erasure list failed", 40, error=str(exc)[:200])
        return {"erased": 0, "cancelled": 0, "failed": 1}
    for row in rows:
        try:
            if _linked(repo, str(row["recipient_id"]), list(row.get("villages") or [])):
                cancelled += 1
            else:
                erase(repo, row, now)
                done += 1
            repo.delete_erasure(str(row["sk"]))
        except Exception as exc:
            failed += 1
            log(_LOG, "erasure failed; tried again next sweep", 40, error=str(exc)[:200])
    if done:
        metric("PersonalDataErased", done)
    return {"erased": done, "cancelled": cancelled, "failed": failed}
