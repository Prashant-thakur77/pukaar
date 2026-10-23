"""Enrolling households by hand, from a vetted list, and by phone (EWS1294's lesson: enrolment is the binding
constraint, and 79% of non-users said nobody had told them).

Three paths besides Telegram's /start, all with the same notice and an audited consent record:

- the officer and pradhan form (POST /villages/{id}/households): add or edit one household: name (optional),
  phone, channel, role, the assisted flag, and how consent was given and by whom. Cedar "enrol_household":
  an officer in their district, a pradhan in their own village.
- the vetted bulk import (POST /villages/{id}/households/import): a panchayat or patwari list as CSV. The
  first call is a preview: each row checked, duplicates found (in the file and in the village), errors
  shown per row. Nothing is stored until the officer commits with a consent attestation for each row
  (attested_rows); a row without one is skipped, never stored.
- the IVR (delivery/inbound.py): the caller hears the notice, presses 1 to agree and keys in the village
  code. Enrolled as "ivr", by "self", with the caller id as the number.

The notice read to a household (NOTICE_VERSION) says what is kept (the number, a name if given, the
village), why (flood alerts, the all-clear and "are you safe?"), how long (while enrolled; erased within
Settings.unlinked_retention_days after leaving) and how to leave (tell the pradhan, call the number and
press 9, or an officer removes them). Phone numbers are never written to a log or the audit trail: only
masked (delivery/voice.mask_phone).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from Pukaar.core import clock
from Pukaar.core.ids import new_id
from Pukaar.delivery.voice import mask_phone
from Pukaar.services import recipients
from Pukaar.store.models import E164, AuditRow, Recipient, Village
from Pukaar.store.repo import Repo

NOTICE_VERSION = "household-notice-v1"
CONSENT_METHODS = {
    "in_person": "spoken consent in person, after the notice was read out",
    "signed_form": "signed or thumb-printed form",
    "phone_call": "spoken consent on a phone call, after the notice was read out",
}
GIVEN_BY = {"self": "the person", "family": "a family member of the household", "guardian": "a guardian or carer"}
CHANNELS = ("voice", "both", "telegram")
MAX_CSV_BYTES = 512 * 1024
MAX_ROWS = 2000
CONSENT_MAX_AGE_DAYS = 366
DEFAULT_NAME = "Household"
_INDIAN_MOBILE = re.compile(r"^[6-9]\d{9}$")


class EnrolError(ValueError):
    """The household cannot be saved; the message says why (no phone number in it)."""


def normalise_phone(raw: str | None) -> str | None:
    """+91XXXXXXXXXX from the forms a list holds: 98123 45678, 09812345678, 919812345678, +91 98123-45678."""
    if raw is None:
        return None
    v = re.sub(r"[\s\-().]", "", str(raw))
    if not v:
        return None
    if v.startswith("00"):
        v = "+" + v[2:]
    if v.startswith("+"):
        pass
    elif v.startswith("0") and _INDIAN_MOBILE.match(v[1:]):
        v = "+91" + v[1:]
    elif _INDIAN_MOBILE.match(v):
        v = "+91" + v
    elif v.startswith("91") and _INDIAN_MOBILE.match(v[2:]):
        v = "+" + v
    if not E164.match(v):
        raise EnrolError("phone must be a mobile number: ten numerals (98xxxxxxxx), or +91 and the ten")
    if v.startswith("+91") and not _INDIAN_MOBILE.match(v[3:]):
        raise EnrolError("an Indian mobile number has 10 digits starting with 6, 7, 8 or 9")
    return v


@dataclass
class Consent:
    method: str
    given_by: str
    taken_by: str
    on: str  # YYYY-MM-DD

    def record(self, actor: str, via: str) -> str:
        return (f"{self.method} ({CONSENT_METHODS.get(self.method, self.method)}), given by {self.given_by}, "
                f"taken by {self.taken_by} on {self.on}, {NOTICE_VERSION}; entered by {actor} ({via})")


def check_consent(raw: dict[str, Any] | None, actor: str, today: date | None = None) -> Consent:
    raw = raw or {}
    method = str(raw.get("method") or "").strip().lower()
    if method not in CONSENT_METHODS:
        raise EnrolError(f"consent method must be one of {', '.join(CONSENT_METHODS)}")
    given = str(raw.get("given_by") or "self").strip().lower()
    if given not in GIVEN_BY:
        raise EnrolError(f"consent given by must be one of {', '.join(GIVEN_BY)}")
    taken = re.sub(r"\s+", " ", str(raw.get("taken_by") or actor)).strip()[:80]
    if not taken:
        raise EnrolError("say who took the consent")
    today = today or clock.now().date()
    try:
        on = date.fromisoformat(str(raw.get("date") or today.isoformat()).strip()[:10])
    except ValueError:
        raise EnrolError("consent date must be YYYY-MM-DD") from None
    if on > today or on < today - timedelta(days=CONSENT_MAX_AGE_DAYS):
        raise EnrolError("consent date must be in the last year and not in the future")
    return Consent(method, given, taken, on.isoformat())


def _bool(v: Any) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y", "haan", "हाँ", "हां"} if v is not None else False


def _audit(repo: Repo, actor: str, role: str, action: str, village_id: str, rid: str, reason: str) -> None:
    repo.append_audit(AuditRow(at=clock.iso(clock.now()), id=new_id("aud"), actor=actor, role=role, action=action,
                               resource=f"recipient:{village_id}/{rid}", decision="allow", reason=reason[:600]))


def view(r: Recipient) -> dict[str, Any]:
    """The console's household row: the number masked, the consent record, never a chat id for voice-only."""
    return {**recipients.view(r), "phone_masked": mask_phone(r.phone) if r.phone else None,
            "assisted": bool(getattr(r, "assisted", False)), "consent": r.consent,
            "enrolled_via": getattr(r, "enrolled_via", None), "enrolled_by": getattr(r, "enrolled_by", None)}


def _dupe(repo: Repo, village_id: str, phone: str | None, own_id: str | None) -> Recipient | None:
    if not phone:
        return None
    return next((x for x in repo.list_recipients(village_id) if x.phone == phone and x.id != own_id), None)


def save(repo: Repo, village: Village, data: dict[str, Any], *, actor: str, actor_role: str,
         via: str = "form") -> tuple[Recipient, bool]:
    """Add (no recipient_id) or edit one household. Returns (recipient, created). Audited."""
    rid = str(data.get("recipient_id") or "").strip() or None
    existing = repo.get_recipient(village.id, rid) if rid else None
    if rid and existing is None:
        raise KeyError(rid)
    if existing is not None and existing.role == "officer":
        raise EnrolError("an officer's entry is not changed here")
    phone = normalise_phone(data.get("phone")) if data.get("phone") not in (None, "") else (
        existing.phone if existing else None)
    channel = str(data.get("channel") or (existing.channel if existing else "voice")).strip().lower()
    if channel not in CHANNELS:
        raise EnrolError(f"channel must be one of {', '.join(CHANNELS)}")
    if channel in {"telegram", "both"} and (existing is None or not existing.takes_telegram):
        raise EnrolError("Telegram is joined by the person themselves (/start and “I agree”); add a phone "
                         "for calls here, or edit someone already on Telegram")
    if channel in {"voice", "both"} and not phone:
        raise EnrolError("a phone number is needed for calls")
    role = recipients.check_role(str(data.get("role") or (existing.role if existing else "villager")))
    name = re.sub(r"\s+", " ", str(data.get("name") or "")).strip()[:80] or (existing.name if existing else DEFAULT_NAME)
    assisted = _bool(data["assisted"]) if "assisted" in data else bool(getattr(existing, "assisted", False))
    dup = _dupe(repo, village.id, phone, existing.id if existing else None)
    if dup is not None:
        raise EnrolError(f"this number is already enrolled in {village.name} ({dup.name}, {dup.id})")
    phone_changed = existing is None or phone != existing.phone
    consent_text = existing.consent if existing else None
    if phone_changed and channel in {"voice", "both"} or existing is None or data.get("consent"):
        consent_text = check_consent(data.get("consent"), actor).record(actor, via)
    fields = {"id": existing.id if existing else new_id("v"), "village_id": village.id, "name": name, "role": role,
              "channel": channel, "phone": phone if channel in {"voice", "both"} else None, "consent": consent_text,
              "language": existing.language if existing else "hi", "assisted": assisted,
              "enrolled_via": getattr(existing, "enrolled_via", None) or via if existing else via,
              "enrolled_by": getattr(existing, "enrolled_by", None) or actor if existing else actor}
    try:
        person = Recipient.model_validate(fields)
    except ValueError as exc:
        raise EnrolError(str(exc).splitlines()[-1][:200]) from None
    repo.put_recipient(person)
    if existing is None:
        _audit(repo, actor, actor_role, "household_enrolled", village.id, person.id,
               f"{via}: {person.channel} {mask_phone(person.phone)}, role {person.role}, "
               f"assisted {'yes' if person.assisted else 'no'}; consent: {person.consent}")
    else:
        changes = [f"{k} {getattr(existing, k, None)} -> {getattr(person, k, None)}"
                   for k in ("name", "role", "channel", "assisted") if getattr(existing, k, None) != getattr(person, k, None)]
        if phone_changed:
            changes.append(f"phone {mask_phone(existing.phone)} -> {mask_phone(person.phone)}")
        if consent_text != existing.consent:
            changes.append(f"consent: {consent_text}")
        _audit(repo, actor, actor_role, "household_updated", village.id, person.id,
               f"{via}: " + ("; ".join(changes) or "no change"))
    return person, existing is None


def remove(repo: Repo, village: Village, recipient_id: str, *, actor: str, actor_role: str, reason: str = "") -> bool:
    from Pukaar.services import privacy

    person = repo.get_recipient(village.id, recipient_id)
    if person is None:
        return False
    if person.role == "officer":
        raise EnrolError("an officer's entry is not changed here")
    why = (reason or "removed from the enrolment list").strip()[:160]
    done = privacy.remove_recipient(repo, village.id, recipient_id, f"{why} (by {actor})")
    if done:
        _audit(repo, actor, actor_role, "household_removed", village.id, recipient_id,
               f"{person.channel} {mask_phone(person.phone)}: {why}")
    return done


# -- the vetted bulk import ------------------------------------------------------------------------------
COLUMNS = {
    "name": ("name", "naam", "नाम", "household", "head of household"),
    "phone": ("phone", "mobile", "mobile number", "phone number", "number", "मोबाइल", "फ़ोन"),
    "channel": ("channel",),
    "role": ("role",),
    "assisted": ("assisted", "needs help", "help"),
    "village": ("village", "village_id", "गाँव"),
    "consent_method": ("consent_method", "consent method", "consent"),
    "consent_given_by": ("consent_given_by", "given by", "consent given by"),
    "consent_date": ("consent_date", "consent date", "date"),
}


@dataclass
class Row:
    n: int  # 1-based data row (the header is row 0)
    data: dict[str, str]
    phone: str | None = None
    status: str = "ok"  # ok | duplicate | exists | error
    errors: list[str] = field(default_factory=list)
    duplicate_of: int | None = None
    existing_id: str | None = None

    def view(self) -> dict[str, Any]:
        return {"row": self.n, "name": self.data.get("name") or "", "phone_masked": mask_phone(self.phone),
                "channel": (self.data.get("channel") or "voice").lower(), "role": (self.data.get("role") or "villager").lower(),
                "assisted": _bool(self.data.get("assisted")), "status": self.status, "errors": self.errors,
                "duplicate_of": self.duplicate_of, "existing_id": self.existing_id,
                "consent_method": self.data.get("consent_method") or "", "consent_given_by": self.data.get("consent_given_by") or "",
                "consent_date": self.data.get("consent_date") or ""}


def _header_map(header: list[str]) -> dict[int, str]:
    out: dict[int, str] = {}
    for i, h in enumerate(header):
        key = h.strip().lower().lstrip("﻿")
        for name, aliases in COLUMNS.items():
            if key in aliases and name not in out.values():
                out[i] = name
                break
    return out


def parse_csv(text: str) -> list[Row]:
    if len(text.encode("utf-8")) > MAX_CSV_BYTES:
        raise EnrolError(f"the file is over {MAX_CSV_BYTES // 1024} KB; split it")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise EnrolError("the file is empty") from None
    cols = _header_map(header)
    if "phone" not in cols.values():
        raise EnrolError("no phone column: the first row must name the columns (name, phone, ...)")
    rows = []
    for n, cells in enumerate(reader, 1):
        if not any(c.strip() for c in cells):
            continue
        if len(rows) >= MAX_ROWS:
            raise EnrolError(f"more than {MAX_ROWS} rows; split the file")
        rows.append(Row(n, {name: (cells[i].strip() if i < len(cells) else "") for i, name in cols.items()}))
    return rows


def preview(repo: Repo, village: Village, text: str, defaults: dict[str, Any] | None = None,
            actor: str = "") -> list[Row]:
    """Each row checked: phone, channel, role, consent, duplicates in the file and in the village."""
    rows = parse_csv(text)
    existing = {r.phone: r for r in repo.list_recipients(village.id) if r.phone}
    seen: dict[str, int] = {}
    for row in rows:
        d = row.data
        v = (d.get("village") or "").strip().lower()
        if v and v not in {village.id, village.name.lower(), village.name_hi}:
            row.errors.append("belongs to another village: import it there")
        try:
            row.phone = normalise_phone(d.get("phone"))
            if not row.phone:
                row.errors.append("no phone number")
        except EnrolError as exc:
            row.errors.append(str(exc))
        channel = (d.get("channel") or "voice").strip().lower()
        if channel != "voice":
            row.errors.append("a list enrols phone calls only (channel voice); Telegram is joined by the person")
        try:
            recipients.check_role(d.get("role") or "villager")
        except recipients.RoleError as exc:
            row.errors.append(str(exc))
        try:
            check_consent(_row_consent(d, defaults), actor or "importer")
        except EnrolError as exc:
            row.errors.append(f"consent: {exc}")
        if row.errors:
            row.status = "error"
            continue
        if row.phone in seen:
            row.status, row.duplicate_of = "duplicate", seen[row.phone]
            row.errors.append(f"same number as row {seen[row.phone]}")
            continue
        seen[row.phone] = row.n  # type: ignore[index]
        if row.phone in existing:
            row.status, row.existing_id = "exists", existing[row.phone].id
            row.errors.append(f"already enrolled as {existing[row.phone].name}")
    return rows


def _row_consent(d: dict[str, str], defaults: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(defaults or {})
    if d.get("consent_method"):
        base["method"] = d["consent_method"].strip().lower().replace(" ", "_")
    if d.get("consent_given_by"):
        base["given_by"] = d["consent_given_by"].strip().lower()
    if d.get("consent_date"):
        base["date"] = d["consent_date"].strip()
    return base


def commit(repo: Repo, village: Village, text: str, *, attested_rows: list[int], attestation: dict[str, Any],
           source: str, actor: str, actor_role: str) -> dict[str, Any]:
    """Store the rows that are ok and attested, one audited enrolment each. Nothing else is stored."""
    source = re.sub(r"\s+", " ", source or "").strip()[:80]
    if not source:
        raise EnrolError("name the list (e.g. panchayat household list 2026, patwari list)")
    if not attested_rows:
        raise EnrolError("tick the rows whose consent you attest; nothing is stored without it")
    rows = preview(repo, village, text, attestation, actor)
    attested = set(int(n) for n in attested_rows)
    stored, skipped = [], []
    for row in rows:
        if row.status != "ok":
            skipped.append({"row": row.n, "reason": row.status})
            continue
        if row.n not in attested:
            skipped.append({"row": row.n, "reason": "not attested"})
            continue
        d = row.data
        person, _ = save(repo, village, {
            "name": d.get("name"), "phone": row.phone, "channel": "voice", "role": d.get("role") or "villager",
            "assisted": d.get("assisted"), "consent": {**_row_consent(d, attestation),
                                                       "taken_by": attestation.get("taken_by") or actor},
        }, actor=actor, actor_role=actor_role, via=f"csv: {source}")
        stored.append({"row": row.n, "recipient_id": person.id})
    repo.append_audit(AuditRow(
        at=clock.iso(clock.now()), id=new_id("aud"), actor=actor, role=actor_role, action="households_imported",
        resource=f"village:{village.id}", decision="allow",
        reason=f"{source}: {len(rows)} rows, {len(stored)} stored with attested consent, {len(skipped)} skipped"))
    return {"stored": stored, "skipped": skipped, "rows": len(rows)}
