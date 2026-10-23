"""District settings a DDMA head may change in the app (policy/base.cedar, "ddma-head-district-settings").

critical_auto_send: send a critical alert with the fixed template when every officer in the chain timed out.
Sending without a human decision is the DDMA's call, so it is the DDMA head's signed-in, audited decision
for their district. Unset (None), the deployment's default holds (template parameter CriticalAutoSend,
PUKAAR_CRITICAL_AUTO_SEND). The value is read when the auto-send step runs (workflow/steps.py) and when the
siren tier decides (services/sirens.py).
"""

from __future__ import annotations

from typing import Any

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.store.models import AuditRow
from Pukaar.store.repo import Repo


def critical_auto_send(repo: Repo, district: str | None) -> bool:
    """The district's own decision when it has made one, else the deployment's default. Never raises."""
    default = get_settings().critical_auto_send
    if not district:
        return default
    try:
        value = repo.get_district_settings(district).get("critical_auto_send")
    except Exception:
        return default
    return default if value is None else bool(value)


def view(repo: Repo, district: str) -> dict[str, Any]:
    stored = repo.get_district_settings(district)
    return {"district": district, "critical_auto_send": critical_auto_send(repo, district),
            "critical_auto_send_set": stored.get("critical_auto_send"),
            "deployment_default": get_settings().critical_auto_send,
            "updated_by": stored.get("updated_by"), "updated_at": stored.get("updated_at")}


def set_critical_auto_send(repo: Repo, district: str, value: bool | None, principal: Any) -> dict[str, Any]:
    from Pukaar.services import roster

    if district not in roster.districts(repo):
        raise ValueError(f"unknown district {district!r}")
    before = repo.get_district_settings(district).get("critical_auto_send")
    now = clock.iso(clock.now())
    fields: dict[str, Any] = {"updated_by": principal.username, "updated_at": now}
    if value is None:
        repo.put_district_settings(district, fields)
        repo._update(f"DISTRICT#{district}", "SETTINGS", {}, remove=["critical_auto_send"])
    else:
        repo.put_district_settings(district, {**fields, "critical_auto_send": bool(value)})
    repo.append_audit(AuditRow(at=now, id=new_id("aud"), actor=principal.username, role=principal.role,
                               action="change_settings", resource=f"district:{district}", decision="allow",
                               reason=f"critical_auto_send {before!r} -> {value!r}"))
    return view(repo, district)
