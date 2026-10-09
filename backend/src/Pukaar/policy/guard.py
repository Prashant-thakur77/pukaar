"""One authorize() for every officer route, workflow step and agent tool call.

Fails closed (any error is a deny), and writes an audit row for every decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import cedarpy

from Pukaar.core import clock
from Pukaar.core.ids import new_id
from Pukaar.core.log import get_logger, log
from Pukaar.store.models import AuditRow

_LOG = get_logger("policy")
_POLICY_FILE = Path(__file__).with_name("base.cedar")
READ_ONLY_TOOLS = {
    "get_village_risk", "get_recent_reports", "get_past_events", "get_safe_places",
    "query_readings", "query_alerts", "query_reports", "query_deliveries", "village_stats", "rank_villages",
}
ROLE_TYPES = {"officer": "Officer", "pradhan": "Pradhan", "system": "System", "agent": "Agent"}
RESOURCE_TYPES = {"village": "Village", "alert": "Alert", "report": "Report", "tool": "Tool", "app": "App"}
DENY_HINTS = {
    "approve": "Only a district officer can approve an alert.",
    "decline": "Only a district officer can decline an alert.",
    "set_report_state": "Only a district officer can change a report's state.",
    "issue_directive": "Only a district officer can issue a directive.",
    "start_replay": "Only a district officer can start or reset a replay.",
    "read_audit": "Only a district officer can read the audit trail.",
    "ask_analyst": "Only a district officer can use Ask Pukaar.",
    "view_reports": "You can only see reports from your own villages.",
    "deliver": "An alert is delivered only after an officer approves it.",
    "auto_send": "Auto-send is allowed only for a critical alert after every officer timed out.",
    "use_tool": "That tool is not on the agent's read-only allowlist.",
    "dev_link": "Only a district officer can open the demo approval link.",
}


@dataclass
class Principal:
    username: str
    role: str  # officer | pradhan | system | agent
    village_ids: list[str] = field(default_factory=list)


SYSTEM = Principal("pukaar-system", "system")


@dataclass
class Decision:
    allowed: bool
    reason: str
    policy_ids: list[str]


@lru_cache(maxsize=1)
def _policies() -> tuple[str, list[tuple[str, str]]]:
    text = _POLICY_FILE.read_text(encoding="utf-8")
    meta = re.findall(r'@id\("([^"]+)"\)\s*@desc\("([^"]+)"\)', text)
    return text, meta


def _readable(policy_ids: list[str]) -> list[tuple[str, str]]:
    """cedarpy names policies policy0..N in file order; map to @id/@desc."""
    _, meta = _policies()
    out = []
    for pid in policy_ids:
        m = re.fullmatch(r"policy(\d+)", pid)
        if m and int(m.group(1)) < len(meta):
            out.append(meta[int(m.group(1))])
        else:
            out.append((pid, pid))
    return out


def _entities(p: Principal, resource_type: str, resource_id: str) -> list[dict[str, Any]]:
    ptype = ROLE_TYPES.get(p.role)
    ents: list[dict[str, Any]] = [
        {"uid": {"type": f"Pukaar::{ptype}", "id": p.username},
         "attrs": {"village_ids": list(p.village_ids)}, "parents": []},
        {"uid": {"type": "Pukaar::ToolGroup", "id": "read_only"}, "attrs": {}, "parents": []},
    ]
    parents = []
    if resource_type == "tool" and resource_id in READ_ONLY_TOOLS:
        parents = [{"type": "Pukaar::ToolGroup", "id": "read_only"}]
    ents.append({"uid": {"type": f"Pukaar::{RESOURCE_TYPES[resource_type]}", "id": resource_id},
                 "attrs": {}, "parents": parents})
    return ents


def _context(raw: dict[str, Any]) -> dict[str, Any]:
    ctx = {"level": "normal", "approved": False, "all_officers_timed_out": False, "replay": False,
           "channel": "", "village_id": ""}
    ctx.update({k: v for k, v in raw.items() if v is not None})
    return ctx


def evaluate(principal: Principal, action: str, resource_type: str, resource_id: str,
             context: dict[str, Any] | None = None) -> Decision:
    try:
        if principal.role not in ROLE_TYPES:
            return Decision(False, f"Unknown role '{principal.role}'.", [])
        policies, _ = _policies()
        request = {
            "principal": f'Pukaar::{ROLE_TYPES[principal.role]}::"{principal.username}"',
            "action": f'Pukaar::Action::"{action}"',
            "resource": f'Pukaar::{RESOURCE_TYPES[resource_type]}::"{resource_id}"',
            "context": _context(context or {}),
        }
        result = cedarpy.is_authorized(request, policies, _entities(principal, resource_type, resource_id))
        if result.diagnostics.errors:
            return Decision(False, "Policy evaluation error; denied.", [])
        matched = _readable(list(result.diagnostics.reasons))
        ids = [pid for pid, _ in matched]
        if result.allowed:
            return Decision(True, matched[0][1] if matched else "allowed", ids)
        if matched:  # a forbid matched
            return Decision(False, matched[0][1], ids)
        return Decision(False, DENY_HINTS.get(action, f"No policy lets a {principal.role} do '{action}'."), [])
    except Exception as exc:  # fail closed
        log(_LOG, "authorize error", 40, error=str(exc))
        return Decision(False, "Authorization failed; denied.", [])


def authorize(principal: Principal, action: str, resource_type: str, resource_id: str,
              context: dict[str, Any] | None = None, *, repo: Any = None) -> Decision:
    decision = evaluate(principal, action, resource_type, resource_id, context)
    row = AuditRow(
        at=clock.iso(clock.now()), id=new_id("aud"), actor=principal.username, role=principal.role,
        action=action, resource=f"{resource_type}:{resource_id}",
        decision="allow" if decision.allowed else "deny", reason=decision.reason,
    )
    try:
        if repo is None:
            from Pukaar.store.repo import get_repo

            repo = get_repo()
        repo.append_audit(row)
    except Exception as exc:
        # An unaudited decision is not allowed to stand.
        log(_LOG, "audit write failed", 40, error=str(exc), action=action)
        return Decision(False, "Audit log unavailable; denied.", decision.policy_ids)
    log(_LOG, "authorize", actor=principal.username, role=principal.role, action=action,
        resource=row.resource, decision=row.decision)
    return decision
