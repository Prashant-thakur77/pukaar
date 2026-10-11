"""River-gauge thresholds learned from the gauge's own record, and virtual staff gauges.

Every route here passes Cedar first with the village as context:
  view_gauge_proposal    officers (any village), pradhans (own village)
  set_gauge_thresholds   officers only; audited old -> new; never automatic
  manage_staff_gauge     officers (any village), pradhans (own village)
  confirm_staff_reading  officers only; audited old -> new
The staff gauge list is public (GET): the anonymous report page shows the reference photo.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from Pukaar.api import views
from Pukaar.api.auth import require_user
from Pukaar.core import clock
from Pukaar.core.ids import new_id
from Pukaar.policy.guard import Principal, authorize
from Pukaar.services import gauge_learn
from Pukaar.services import staff_gauge as staff
from Pukaar.services.decision_engine import recompute_village
from Pukaar.services.storage import MAX_UPLOAD_BYTES
from Pukaar.store.models import AuditRow, GaugeConfig, Village
from Pukaar.store.repo import Repo, get_repo
from Pukaar.workflow.client import get_workflow

router = APIRouter()


def _allow(principal: Principal, action: str, resource_type: str, resource_id: str, village_id: str, repo: Repo) -> None:
    decision = authorize(principal, action, resource_type, resource_id, {"village_id": village_id}, repo=repo)
    if not decision.allowed:
        raise HTTPException(403, {"code": "denied", "reason": decision.reason, "action": action, "role": principal.role})


def _village(repo: Repo, village_id: str) -> Village:
    v = repo.get_village(village_id)
    if v is None:
        raise HTTPException(404, "Village not found")
    return v


def _bad(exc: staff.StaffGaugeError) -> HTTPException:
    return HTTPException(400, {"code": "invalid", "message_en": exc.en, "message_hi": exc.hi})


# -- learned thresholds (feature 12) ---------------------------------------
def _proposal(repo: Repo, v: Village) -> dict[str, Any]:
    since = clock.iso(clock.now() - timedelta(days=gauge_learn.WINDOW_DAYS))
    readings = repo.list_sensor_readings(v.id, since, limit=gauge_learn.MAX_READINGS)
    return gauge_learn.propose(readings, v.gauge)


def _current(g: GaugeConfig | None) -> dict[str, Any] | None:
    if g is None:
        return None
    return {"watch_cm": g.watch_cm, "warning_cm": g.warning_cm, "critical_cm": g.critical_cm,
            "source": g.thresholds_source, "set_by": g.thresholds_set_by, "set_at": g.thresholds_set_at}


@router.get("/villages/{village_id}/gauge/proposal")
def gauge_proposal(village_id: str, principal: Principal = Depends(require_user)) -> dict:
    repo = get_repo()
    _allow(principal, "view_gauge_proposal", "village", village_id, village_id, repo)
    v = _village(repo, village_id)
    if v.gauge is None:
        raise HTTPException(404, "This village has no river gauge")
    return {"village_id": v.id, "device_id": v.gauge.device_id, **_proposal(repo, v)}


class ThresholdsBody(BaseModel):
    watch_cm: float = Field(ge=-200, le=5000)
    warning_cm: float = Field(ge=-200, le=5000)
    critical_cm: float = Field(ge=-200, le=5000)
    from_proposal: bool = True
    note: str = Field(default="", max_length=200)


@router.post("/villages/{village_id}/gauge/thresholds")
def set_gauge_thresholds(village_id: str, body: ThresholdsBody, principal: Principal = Depends(require_user)) -> dict:
    """Accept a proposal (or set values by hand). Never called by the system on its own."""
    repo = get_repo()
    _allow(principal, "set_gauge_thresholds", "village", village_id, village_id, repo)
    v = _village(repo, village_id)
    if v.gauge is None:
        raise HTTPException(404, "This village has no river gauge")
    if not body.watch_cm < body.warning_cm < body.critical_cm:
        raise HTTPException(400, {"code": "invalid", "message_en": "Thresholds must rise: watch < warning < critical.",
                                  "message_hi": "सीमाएँ बढ़ते क्रम में हों: Watch < Warning < Critical।"})
    if body.from_proposal:
        proposal = _proposal(repo, v)
        if not gauge_learn.matches(proposal, body.watch_cm, body.warning_cm, body.critical_cm):
            raise HTTPException(409, {"code": "proposal_changed",
                                      "message_en": "The proposal has changed or is not ready. Reload it and check again.",
                                      "message_hi": "प्रस्ताव बदल गया है या तैयार नहीं। दोबारा खोलकर जाँचें।"})
        source = gauge_learn.basis_text(proposal)
    else:
        source = "set by hand" + (f": {body.note.strip()}" if body.note.strip() else "")
    old = v.gauge
    now = clock.iso(clock.now())
    new = old.model_copy(update={"watch_cm": body.watch_cm, "warning_cm": body.warning_cm,
                                 "critical_cm": body.critical_cm, "thresholds_source": source[:300],
                                 "thresholds_set_by": principal.username, "thresholds_set_at": now})
    repo.update_village(v.id, gauge=new)
    repo.append_audit(AuditRow(
        at=now, id=new_id("aud"), actor=principal.username, role=principal.role, action="set_gauge_thresholds",
        resource=f"village:{v.id}", decision="allow",
        reason=(f"gauge {old.device_id}: watch {old.watch_cm:g} -> {new.watch_cm:g} cm, warning {old.warning_cm:g} -> "
                f"{new.warning_cm:g} cm, critical {old.critical_cm:g} -> {new.critical_cm:g} cm; {source}")[:500],
    ))
    return {"village_id": v.id, "current": _current(new), "previous": _current(old)}


# -- virtual staff gauges (feature 18) -------------------------------------
@router.get("/villages/{village_id}/staff-gauges")
def list_staff_gauges(village_id: str) -> list[dict]:
    repo = get_repo()
    _village(repo, village_id)
    return [staff.view(g) for g in staff.active(repo, village_id)]


@router.post("/villages/{village_id}/staff-gauges")
async def create_staff_gauge(village_id: str, meta: str = Form(...), photo: UploadFile = File(...),
                             principal: Principal = Depends(require_user)) -> dict:
    """meta: JSON with name, name_hi, where, scale_top, scale_bottom, unit, marks, watch_at/warning_at/critical_at."""
    repo = get_repo()
    _allow(principal, "manage_staff_gauge", "village", village_id, village_id, repo)
    v = _village(repo, village_id)
    data = await photo.read()
    if not data:
        raise HTTPException(400, "Send the reference photo")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, {"code": "too_large", "message_en": "Photo too large (4 MB max).",
                                  "message_hi": "फ़ोटो बहुत बड़ी है (4 MB तक)।"})
    try:
        fields = json.loads(meta)
        if not isinstance(fields, dict):
            raise TypeError("meta must be an object")
    except (TypeError, ValueError):
        raise HTTPException(400, "meta must be a JSON object") from None
    try:
        g = staff.create(repo, v, photo=(data, photo.content_type or ""), fields=fields, actor=principal.username,
                         role=principal.role)
    except staff.StaffGaugeError as exc:
        raise _bad(exc) from None
    return staff.view(g)


class StaffGaugeUpdate(BaseModel):
    name: str | None = None
    name_hi: str | None = None
    where: str | None = None
    watch_at: float | None = None
    warning_at: float | None = None
    critical_at: float | None = None
    active: bool | None = None


@router.patch("/villages/{village_id}/staff-gauges/{gauge_id}")
def update_staff_gauge(village_id: str, gauge_id: str, body: StaffGaugeUpdate,
                       principal: Principal = Depends(require_user)) -> dict:
    """Rename, change the threshold marks (send null to clear one), or retire (active=false)."""
    repo = get_repo()
    _allow(principal, "manage_staff_gauge", "village", village_id, village_id, repo)
    g = repo.get_staff_gauge(village_id, gauge_id)
    if g is None:
        raise HTTPException(404, "Staff gauge not found")
    fields = body.model_dump(exclude_unset=True)
    for key in ("name", "name_hi", "where", "active"):
        if key in fields and fields[key] is None:
            fields.pop(key)
    try:
        g = staff.update(repo, g, fields, actor=principal.username, role=principal.role)
    except staff.StaffGaugeError as exc:
        raise _bad(exc) from None
    return staff.view(g)


class StaffConfirm(BaseModel):
    value: float | None = None  # the mark's value; the villager's own mark to confirm it as is
    unreadable: bool = False


@router.post("/reports/{report_id}/staff-reading")
def confirm_staff_reading(report_id: str, body: StaffConfirm, principal: Principal = Depends(require_user)) -> dict:
    repo = get_repo()
    r = repo.get_report(report_id)
    if r is None:
        raise HTTPException(404, "Report not found")
    _allow(principal, "confirm_staff_reading", "report", report_id, r.village_id, repo)
    try:
        updated = staff.confirm(repo, r, value=body.value, unreadable=body.unreadable, actor=principal.username,
                                role=principal.role)
    except staff.StaffGaugeError as exc:
        raise _bad(exc) from None
    village = repo.get_village(r.village_id)
    if village is not None:
        # A confirmed reading is evidence now; re-run the village's rules (raise or hold, as rules say).
        recompute_village(repo, village, workflow=get_workflow(), replay=r.replay)
    return views.report(repo.get_report(report_id) or updated)
