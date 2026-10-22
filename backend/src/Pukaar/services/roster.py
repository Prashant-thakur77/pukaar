"""The district duty roster: who approves alerts right now, and who is next.

A district control room (DEOC) runs around the clock in shifts. Each shift of each district has a
primary duty officer, a backup, and an escalation officer above them (the ADM or the DM). The
approval workflow asks them in that order (workflow/steps.py), so a Warning at 02:00 reaches the
officer actually on the night desk, and when the chain runs out someone senior has been asked.

Shifts are in IST (UTC+05:30, no daylight saving), two a day:

    day     08:00 to 20:00, dated the day it starts
    night   20:00 to 08:00 the next morning, dated the evening it starts

So at 02:00 IST on 23 October the night shift of 22 October is on duty.

When a district has no roster row for the current shift, the village's own fallback list
(Village.officers, from data/villages.json) is used, and the sweep emits NobodyOnDuty for that
district (alarmed): an empty shift is a gap the control room must fill, not something to hide.

Handover: an officer taking over a shift ("taking over") becomes its primary; the previous primary
is kept on the row and the change is written to the audit trail.

Who may edit is decided by Cedar (policy/base.cedar, "officer-roster"): officers only; a pradhan
cannot, and the public demo accounts can read the roster but never change it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.core.log import get_logger, log, metric
from Pukaar.store.models import AuditRow, RosterShift, Village
from Pukaar.store.repo import Repo

_LOG = get_logger("roster")
IST = timezone(timedelta(hours=5, minutes=30), "IST")
# (id, start hour, length in hours), in the order they run each day.
SHIFTS: tuple[tuple[str, int, int], ...] = (("day", 8, 12), ("night", 20, 12))
SHIFT_IDS = tuple(s[0] for s in SHIFTS)
ESCALATION_TITLES = ("ADM", "DM")
USERNAME = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")
DDMA_LABEL = "needs DDMA sign-off"
MAX_DAYS_AHEAD = 60
MAX_DAYS_BACK = 14


class RosterError(ValueError):
    """A roster edit that cannot be saved; the message says why."""


@dataclass(frozen=True)
class ShiftSlot:
    date: str  # YYYY-MM-DD, IST
    shift: str
    starts_at: datetime  # UTC
    ends_at: datetime  # UTC

    def label(self) -> str:
        start = self.starts_at.astimezone(IST)
        end = self.ends_at.astimezone(IST)
        return f"{self.shift} shift {self.date}, {start:%H:%M}–{end:%H:%M} IST"


@dataclass
class Duty:
    """Who is on duty for a district in one shift, and the order they are asked in."""

    district: str
    slot: ShiftSlot
    source: str  # "roster" | "fallback" | "none"
    chain: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    entry: RosterShift | None = None

    @property
    def rostered(self) -> bool:
        return self.source == "roster"

    def view(self) -> dict[str, Any]:
        e = self.entry
        return {
            "district": self.district, "date": self.slot.date, "shift": self.slot.shift,
            "starts_at": clock.iso(self.slot.starts_at), "ends_at": clock.iso(self.slot.ends_at),
            "source": self.source, "chain": list(self.chain), "roles": list(self.roles),
            "primary": e.primary if e else None, "backup": e.backup if e else None,
            "escalation": e.escalation if e else None, "escalation_title": e.escalation_title if e else None,
            "taken_over_from": e.taken_over_from if e else None, "taken_over_at": e.taken_over_at if e else None,
        }


# -- time ---------------------------------------------------------------------------------------
def _slot(day: date, shift: str) -> ShiftSlot:
    _, hour, hours = next(s for s in SHIFTS if s[0] == shift)
    start = datetime.combine(day, time(hour), IST)
    return ShiftSlot(day.isoformat(), shift, start.astimezone(timezone.utc),
                     (start + timedelta(hours=hours)).astimezone(timezone.utc))


def slot_at(now: datetime) -> ShiftSlot:
    """The shift running at this moment (IST)."""
    local = now.astimezone(IST)
    for day in (local.date(), local.date() - timedelta(days=1)):
        for shift in reversed(SHIFT_IDS):
            s = _slot(day, shift)
            if s.starts_at <= now < s.ends_at:
                return s
    raise AssertionError("shifts must cover the whole day")  # pragma: no cover


def today_ist(now: datetime | None = None) -> date:
    return (now or clock.now()).astimezone(IST).date()


def parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise RosterError("date must be YYYY-MM-DD") from None


# -- resolution ---------------------------------------------------------------------------------
def _chain(entry: RosterShift) -> tuple[list[str], list[str]]:
    people, roles = [], []
    for who, role in ((entry.primary, "primary"), (entry.backup, "backup"),
                      (entry.escalation, f"escalation ({entry.escalation_title})")):
        if who and who not in people:
            people.append(who)
            roles.append(role)
    return people, roles


def on_duty(repo: Repo, district: str, now: datetime | None = None, fallback: list[str] | None = None) -> Duty:
    """Who is on duty for the district now (IST). Without a roster row: the fallback list, if any."""
    now = now or clock.now()
    slot = slot_at(now)
    entry = repo.get_roster_shift(district, slot.date, slot.shift)
    if entry is not None and entry.primary:
        people, roles = _chain(entry)
        return Duty(district, slot, "roster", people, roles, entry)
    people = list(dict.fromkeys(fallback or []))
    return Duty(district, slot, "fallback" if people else "none", people,
                [f"fallback #{i + 1}" for i in range(len(people))])


def chain_for(repo: Repo, village: Village, now: datetime | None = None) -> Duty:
    """The approval chain for a village's alert: its district's duty roster now, else village.officers."""
    return on_duty(repo, village.district, now, fallback=list(village.officers))


def districts(repo: Repo) -> list[str]:
    return sorted({v.district for v in repo.list_villages()})


def nobody_on_duty(repo: Repo, now: datetime | None = None) -> list[str]:
    """Districts with villages but no rostered officer for the current shift. Emits NobodyOnDuty for
    each (dimension District; alarmed in infra/template.yaml). Never raises."""
    now = now or clock.now()
    empty: list[str] = []
    try:
        slot = slot_at(now)
        for d in districts(repo):
            entry = repo.get_roster_shift(d, slot.date, slot.shift)
            if entry is None or not entry.primary:
                empty.append(d)
                metric("NobodyOnDuty", 1, District=d)
        if empty:
            log(_LOG, "nobody rostered for the current shift", 30, shift=slot.label(), districts=empty)
    except Exception as exc:
        log(_LOG, "on-duty check failed", 40, error=str(exc)[:300])
    return empty


# -- the week -----------------------------------------------------------------------------------
def week(repo: Repo, district: str, start: date, days: int = 7) -> list[dict[str, Any]]:
    end = start + timedelta(days=days - 1)
    rows = {(r.date, r.shift): r for r in repo.list_roster(district, start.isoformat(), end.isoformat())}
    out = []
    for i in range(days):
        d = start + timedelta(days=i)
        shifts = {}
        for sid in SHIFT_IDS:
            slot = _slot(d, sid)
            r = rows.get((d.isoformat(), sid))
            shifts[sid] = {"starts_at": clock.iso(slot.starts_at), "ends_at": clock.iso(slot.ends_at),
                           "entry": r.model_dump() if r else None}
        out.append({"date": d.isoformat(), "weekday": d.strftime("%a"), "shifts": shifts})
    return out


def view(repo: Repo, district: str | None, start: date | None, now: datetime | None = None) -> dict[str, Any]:
    now = now or clock.now()
    names = districts(repo)
    if district and district not in names:
        raise RosterError(f"unknown district {district!r}")
    villages = repo.list_villages()
    # Default to the district with the most villages: the desk most alerts come to.
    chosen = district or (max(names, key=lambda d: (sum(v.district == d for v in villages), d)) if names else "")
    start = start or today_ist(now)
    fallback = {d: next((list(v.officers) for v in villages if v.district == d and v.officers), []) for d in names}
    s = get_settings()
    return {
        "district": chosen, "districts": names, "timezone": "Asia/Kolkata (IST, UTC+05:30)",
        "shifts": [{"id": sid, "start": f"{h:02d}:00", "end": f"{(h + n) % 24:02d}:00"} for sid, h, n in SHIFTS],
        "start": start.isoformat(),
        "days": week(repo, chosen, start) if chosen else [],
        "now": [on_duty(repo, d, now, fallback[d]).view() for d in names],
        "officers": sorted({o for v in villages for o in v.officers}),
        "critical_auto_send": s.critical_auto_send, "critical_auto_send_label": DDMA_LABEL,
        "approval_timeout_seconds": s.approval_timeout_seconds,
    }


# -- edits --------------------------------------------------------------------------------------
def _username(value: str | None, what: str, required: bool = False) -> str | None:
    v = (value or "").strip()
    if not v:
        if required:
            raise RosterError(f"{what} is required")
        return None
    if not USERNAME.match(v):
        raise RosterError(f"{what} must be a sign-in name (letters, digits, . _ @ -)")
    return v


def _check_slot(repo: Repo, district: str, day: str, shift: str, now: datetime) -> date:
    if district not in districts(repo):
        raise RosterError(f"unknown district {district!r}")
    if shift not in SHIFT_IDS:
        raise RosterError(f"shift must be one of {', '.join(SHIFT_IDS)}")
    d = parse_day(day)
    today = today_ist(now)
    if not today - timedelta(days=MAX_DAYS_BACK) <= d <= today + timedelta(days=MAX_DAYS_AHEAD):
        raise RosterError(f"date must be within {MAX_DAYS_BACK} days back and {MAX_DAYS_AHEAD} days ahead")
    return d


def _audit(repo: Repo, actor: str, role: str, action: str, district: str, day: str, shift: str, reason: str) -> None:
    repo.append_audit(AuditRow(at=clock.iso(clock.now()), id=new_id("aud"), actor=actor, role=role, action=action,
                               resource=f"roster:{district}/{day}/{shift}", decision="allow", reason=reason))


def _describe(r: RosterShift | None) -> str:
    if r is None:
        return "empty"
    return (f"primary {r.primary}, backup {r.backup or '-'}, "
            f"{r.escalation_title} {r.escalation or '-'}")


def set_shift(repo: Repo, actor: str, role: str, district: str, day: str, shift: str, *, primary: str,
              backup: str | None = None, escalation: str | None = None, escalation_title: str = "ADM",
              note: str = "", now: datetime | None = None) -> RosterShift:
    now = now or clock.now()
    _check_slot(repo, district, day, shift, now)
    p = _username(primary, "primary", required=True)
    b = _username(backup, "backup")
    e = _username(escalation, "escalation officer")
    if escalation_title not in ESCALATION_TITLES:
        raise RosterError("escalation officer must be the ADM or the DM")
    if b and b == p:
        raise RosterError("the backup must be someone other than the primary")
    old = repo.get_roster_shift(district, day, shift)
    row = RosterShift(district=district, date=day, shift=shift, primary=p, backup=b, escalation=e,  # type: ignore[arg-type]
                      escalation_title=escalation_title, note=(note or "").strip()[:200],  # type: ignore[arg-type]
                      updated_by=actor, updated_at=clock.iso(now),
                      taken_over_from=old.taken_over_from if old and old.primary == p else None,
                      taken_over_at=old.taken_over_at if old and old.primary == p else None)
    repo.put_roster_shift(row)
    _audit(repo, actor, role, "roster_changed", district, day, shift, f"{_describe(old)} -> {_describe(row)}")
    return row


def clear_shift(repo: Repo, actor: str, role: str, district: str, day: str, shift: str,
                now: datetime | None = None) -> bool:
    now = now or clock.now()
    _check_slot(repo, district, day, shift, now)
    old = repo.get_roster_shift(district, day, shift)
    if old is None:
        return False
    repo.delete_roster_shift(district, day, shift)
    _audit(repo, actor, role, "roster_cleared", district, day, shift, f"{_describe(old)} -> empty")
    return True


def take_over(repo: Repo, actor: str, role: str, district: str, now: datetime | None = None) -> RosterShift:
    """"Taking over": the signed-in officer becomes the primary of the shift running now.

    The previous primary moves to the backup slot when it is empty (or when the backup is the one
    taking over), so the chain stays three deep at handover. The escalation officer is kept.
    Written to the audit trail as duty_taken_over.
    """
    now = now or clock.now()
    if district not in districts(repo):
        raise RosterError(f"unknown district {district!r}")
    slot = slot_at(now)
    old = repo.get_roster_shift(district, slot.date, slot.shift)
    if old is not None and old.primary == actor:
        raise RosterError("you are already the primary for this shift")
    previous = old.primary if old else None
    backup = old.backup if old else None
    if backup == actor:
        backup = previous
    elif not backup:
        backup = previous
    row = RosterShift(district=district, date=slot.date, shift=slot.shift, primary=actor,  # type: ignore[arg-type]
                      backup=backup if backup != actor else None,
                      escalation=old.escalation if old else None,
                      escalation_title=old.escalation_title if old else "ADM",
                      note=old.note if old else "", updated_by=actor, updated_at=clock.iso(now),
                      taken_over_from=previous, taken_over_at=clock.iso(now))
    repo.put_roster_shift(row)
    _audit(repo, actor, role, "duty_taken_over", district, slot.date, slot.shift,
           f"{actor} takes over the {slot.label()} from {previous or 'nobody (the shift was empty)'}")
    log(_LOG, "duty taken over", district=district, shift=slot.label(), by=actor, previous=previous)
    return row
