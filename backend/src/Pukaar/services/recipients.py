"""A recipient's relay role: pradhan, gauge reader or task-force volunteer, or back to villager.

Relays are contacted first in a delivery (delivery/dispatch.py, the Practical Action "cascade"), and a
pradhan registered on Telegram gets the list of households nobody reached (docs/VOICE.md). A villager who
registers with /start <village> is an ordinary villager; an officer (any village) or the village's own
pradhan makes them a relay through POST /villages/{id}/recipients/{rid}/role (Cedar set_recipient_role;
the public demo accounts are refused), and the operator through `make recipient-role` or `make voice-add
ROLE=... CHAT=...`. Every change is written to the audit trail.
"""

from __future__ import annotations

from typing import Any

from Pukaar.core import clock
from Pukaar.core.ids import new_id
from Pukaar.store.models import AuditRow, Recipient
from Pukaar.store.repo import Repo

# The roles a person can be given here. "officer" is not one: officers are Cognito accounts on the roster.
SETTABLE_ROLES = ("villager", "pradhan", "gauge_reader", "task_force")


class RoleError(ValueError):
    """The role cannot be set; the message says why."""


def check_role(role: str) -> str:
    value = (role or "").strip().lower()
    if value not in SETTABLE_ROLES:
        raise RoleError(f"role must be one of {', '.join(SETTABLE_ROLES)}")
    return value


def set_role(repo: Repo, village_id: str, recipient_id: str, role: str, *, actor: str, actor_role: str) -> Recipient:
    """Set the recipient's role and audit it ("recipient_role_changed"). KeyError for an unknown recipient."""
    value = check_role(role)
    r = repo.get_recipient(village_id, recipient_id)
    if r is None:
        raise KeyError(recipient_id)
    old = r.role
    if old == "officer":
        raise RoleError("an officer's entry is not changed here")
    if old != value:
        r = r.model_copy(update={"role": value})
        repo.put_recipient(r)
    repo.append_audit(AuditRow(at=clock.iso(clock.now()), id=new_id("aud"), actor=actor, role=actor_role,
                               action="recipient_role_changed", resource=f"recipient:{village_id}/{recipient_id}",
                               decision="allow", reason=f"{old} -> {value}"))
    return r


def view(r: Recipient) -> dict[str, Any]:
    """What the console gets back: no phone number, no consent text."""
    return {"id": r.id, "village_id": r.village_id, "name": r.name, "role": r.role, "channel": r.channel,
            "relay": r.is_relay}
