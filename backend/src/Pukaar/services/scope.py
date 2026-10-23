"""District scope of staff accounts: which villages an officer may act on (policy/base.cedar, "staff-own-district").

An officer, or a state operator, acts on a village only when one of these holds:

- assigned to its district: the account's SCOPE row (Repo.put_staff_scope; `make staff-assign`), the data a
  DDMA keeps, not code;
- assigned to the village itself: the village's officer list (Village.officers, from data/villages.json or
  data/districts.json at seed time), or the villages on the account's sign-in (Cognito custom:village_ids);
- rostered: primary, backup or escalation officer of a shift of that district yesterday, today or tomorrow
  (IST; services/roster.py), so whoever is on the desk tonight can act tonight.

A DDMA head is held to the districts of their SCOPE row (principal.district_ids, filled at sign-in).

The facts go to Cedar as context.district (the village's district, from the record, never from the request),
context.scoped (the request names a village or a district) and context.in_scope. Replays are not scoped:
a replay never reaches a phone or a siren (policy "no-replay-to-phones", "no-replay-sirens").
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from Pukaar.core import clock

SCOPED_ROLES = {"officer", "state_operator", "ddma_head"}


def _village_of(repo: Any, resource_type: str, resource_id: str, context: dict[str, Any]) -> str:
    """The village a decision is about: the context's, or the record's own (an alert, a report, a device)."""
    vid = str(context.get("village_id") or "")
    if vid:
        return vid
    try:
        if resource_type == "alert":
            a = repo.get_alert(resource_id)
            return a.village_id if a else ""
        if resource_type == "report":
            r = repo.get_report(resource_id)
            return r.village_id if r else ""
        if resource_type == "rollcall":
            rc = repo.get_rollcall(resource_id)
            return rc.village_id if rc else ""
        if resource_type == "device":
            d = repo.get_device(resource_id)
            return d.village_id if d else ""
    except Exception:
        return ""
    return ""


def staff_districts(repo: Any, principal: Any) -> set[str]:
    out = {d for d in getattr(principal, "district_ids", []) or [] if d}
    try:
        out |= set(repo.get_staff_scope(principal.username))
    except Exception:
        pass
    return out


def rostered(repo: Any, username: str, district: str, now: datetime | None = None) -> bool:
    """On a shift of the district from yesterday to tomorrow (IST), in any of the three seats."""
    from Pukaar.services.roster import today_ist

    today = today_ist(now or clock.now())
    try:
        shifts = repo.list_roster(district, (today - timedelta(days=1)).isoformat(),
                                  (today + timedelta(days=1)).isoformat())
    except Exception:
        return False
    return any(username in {s.primary, s.backup, s.escalation} for s in shifts)


def facts(repo: Any, principal: Any, resource_type: str, resource_id: str, context: dict[str, Any],
          now: datetime | None = None) -> dict[str, Any]:
    """context.district, context.scoped and context.in_scope for a staff principal (empty for anyone else)."""
    if getattr(principal, "role", "") not in SCOPED_ROLES or repo is None:
        return {}
    vid = _village_of(repo, resource_type, resource_id, context)
    district = str(context.get("district") or "")
    village = None
    if vid:
        try:
            village = repo.get_village(vid)
        except Exception:
            village = None
        if village is None:
            # No such village: nothing there to act on, and the route answers 404 (a stray id never reveals
            # whether a district exists behind it). Not scoped, so the decision is the role's alone.
            return {"district": "", "scoped": False, "in_scope": False}
        district = village.district
    scoped = bool(vid or district)
    if not scoped:
        return {"district": "", "scoped": False, "in_scope": False}
    username = principal.username
    in_scope = bool(
        (district and district in staff_districts(repo, principal))
        or (village is not None and (username in village.officers or village.id in (principal.village_ids or [])))
        or (district and rostered(repo, username, district, now))
    )
    return {"district": district, "scoped": True, "in_scope": in_scope}


def districts_of(repo: Any, principal: Any) -> list[str]:
    """A DDMA head's districts (sign-in, and the SCOPE row)."""
    return sorted(staff_districts(repo, principal))
