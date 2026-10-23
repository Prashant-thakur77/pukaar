"""Reach, enrolment and the duty officer's routes (docs/CONTRACT.md). Each passes policy.guard.authorize() first.

    GET  /alert-groups                         pending alerts of a district from one cause, as groups
    POST /alert-groups/decide                  one hold-to-approve: approve some, decline the rest (each alert
                                               checked by Cedar and decided with its own task token)
    POST /alerts/{id}/sachet-request           the SACHET / cell-broadcast package for HPSDMA (audited; never sent)
    GET  /villages/{id}/households             enrolled households (numbers masked)
    POST /villages/{id}/households             add or edit one household (the form)
    DELETE /villages/{id}/households/{rid}     take a household off (erased later, privacy.py)
    POST /villages/{id}/households/import      the vetted CSV import: preview, then commit attested rows
    GET  /duty/digest?district=                the morning digest, as the duty officer gets it
    GET  /duty/handover?district=              this shift's note, the previous shift's, the last week's
    POST /duty/handover/{district}             the outgoing officer writes the note
    POST /duty/handover/{district}/{date}/{shift}/ack   the incoming officer acknowledges it
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from Pukaar.api.auth import Allowed, require_user
from Pukaar.policy.guard import READS_EVERYTHING, Principal
from Pukaar.services import duty, enrolment, group_approval, roster, sachet_request
from Pukaar.store.repo import get_repo
from Pukaar.workflow.client import get_workflow

router = APIRouter()


# -- grouped approval ------------------------------------------------------------------------------
@router.get("/alert-groups")
def alert_groups(district: str = "", principal: Principal = Depends(Allowed("view_console"))) -> list[dict]:
    villages = None if principal.role in READS_EVERYTHING else list(principal.village_ids)
    return [g.view() for g in group_approval.groups_for(get_repo(), district or None, villages)]


class GroupItem(BaseModel):
    alert_id: str
    decision: str


class GroupBody(BaseModel):
    decisions: list[GroupItem] = Field(min_length=1, max_length=200)
    reason: str = ""
    group_id: str = ""


@router.post("/alert-groups/decide")
def decide_group(body: GroupBody, principal: Principal = Depends(require_user)) -> dict:
    """Each alert is authorised on its own (approve or decline, its village's district); see group_approval."""
    try:
        results = group_approval.decide_group(get_repo(), get_workflow(), principal,
                                              [i.model_dump() for i in body.decisions], body.reason, body.group_id)
    except group_approval.GroupError as exc:
        raise HTTPException(400, {"code": "group", "reason": str(exc)}) from None
    return {"results": results, "decided": sum(1 for r in results if r["outcome"] == "decided")}


# -- SACHET out -------------------------------------------------------------------------------------
class SachetBody(BaseModel):
    radius_km: float | None = None
    via: str = "view"


@router.post("/alerts/{alert_id}/sachet-request")
def sachet_request_package(alert_id: str, body: SachetBody | None = None,
                           principal: Principal = Depends(Allowed("request_sachet", "alert", "alert_id"))) -> dict:
    repo = get_repo()
    a = repo.get_alert(alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    body = body or SachetBody()
    try:
        pkg = sachet_request.prepare(repo, a, principal.username, principal.role, body.radius_km, body.via)
    except sachet_request.NotRequestable as exc:
        raise HTTPException(409, {"code": "not_requestable", "reason": str(exc)}) from None
    return pkg.view()


# -- enrolment --------------------------------------------------------------------------------------
def _village(village_id: str):
    v = get_repo().get_village(village_id)
    if v is None:
        raise HTTPException(404, "Village not found")
    return v


@router.get("/villages/{village_id}/households")
def list_households(village_id: str, principal: Principal = Depends(Allowed("view_recipients", "village", "village_id",
                                                                             village_from_path=True))) -> dict:
    v = _village(village_id)
    people = [p for p in get_repo().list_recipients(v.id) if p.channel != "stub" and p.role != "officer"]
    rows = [enrolment.view(p) for p in sorted(people, key=lambda p: (p.name.lower(), p.id))]
    return {"village_id": v.id, "village_name": v.name, "village_name_hi": v.name_hi, "ivr_code": v.ivr_code,
            "households": rows, "consent_methods": enrolment.CONSENT_METHODS, "given_by": enrolment.GIVEN_BY,
            "notice_version": enrolment.NOTICE_VERSION}


class HouseholdBody(BaseModel):
    recipient_id: str | None = None
    name: str = ""
    phone: str | None = None
    channel: str | None = None
    role: str | None = None
    assisted: bool | None = None
    consent: dict[str, Any] | None = None


@router.post("/villages/{village_id}/households")
def save_household(village_id: str, body: HouseholdBody,
                   principal: Principal = Depends(Allowed("enrol_household", "village", "village_id",
                                                          village_from_path=True))) -> dict:
    v = _village(village_id)
    data = {k: val for k, val in body.model_dump().items() if val is not None}
    try:
        person, created = enrolment.save(get_repo(), v, data, actor=principal.username, actor_role=principal.role)
    except enrolment.EnrolError as exc:
        raise HTTPException(400, {"code": "enrol", "reason": str(exc)}) from None
    except KeyError:
        raise HTTPException(404, "Household not found in this village") from None
    return {"household": enrolment.view(person), "created": created}


@router.delete("/villages/{village_id}/households/{recipient_id}")
def remove_household(village_id: str, recipient_id: str, reason: str = "",
                     principal: Principal = Depends(Allowed("enrol_household", "village", "village_id",
                                                            village_from_path=True))) -> dict:
    v = _village(village_id)
    try:
        done = enrolment.remove(get_repo(), v, recipient_id, actor=principal.username, actor_role=principal.role,
                                reason=reason)
    except enrolment.EnrolError as exc:
        raise HTTPException(400, {"code": "enrol", "reason": str(exc)}) from None
    if not done:
        raise HTTPException(404, "Household not found in this village")
    return {"removed": True}


class ImportBody(BaseModel):
    csv: str = Field(max_length=enrolment.MAX_CSV_BYTES)
    commit: bool = False
    source: str = ""
    attested_rows: list[int] = Field(default_factory=list)
    attestation: dict[str, Any] = Field(default_factory=dict)


@router.post("/villages/{village_id}/households/import")
def import_households(village_id: str, body: ImportBody,
                      principal: Principal = Depends(Allowed("enrol_household", "village", "village_id",
                                                             village_from_path=True))) -> dict:
    """commit=false: the preview (nothing stored). commit=true: the rows that are ok and attested."""
    v = _village(village_id)
    repo = get_repo()
    try:
        rows = enrolment.preview(repo, v, body.csv, body.attestation, principal.username)
        out: dict[str, Any] = {"rows": [r.view() for r in rows],
                               "counts": {s: sum(1 for r in rows if r.status == s)
                                          for s in ("ok", "duplicate", "exists", "error")}}
        if body.commit:
            out["result"] = enrolment.commit(repo, v, body.csv, attested_rows=body.attested_rows,
                                             attestation={**body.attestation,
                                                          "taken_by": body.attestation.get("taken_by") or principal.username},
                                             source=body.source, actor=principal.username, actor_role=principal.role)
    except enrolment.EnrolError as exc:
        raise HTTPException(400, {"code": "enrol", "reason": str(exc)}) from None
    return out


# -- the duty officer -----------------------------------------------------------------------------------
def _district(district: str) -> str:
    names = roster.districts(get_repo())
    if district and district not in names:
        raise HTTPException(400, {"code": "duty", "reason": f"unknown district {district!r}"})
    return district or (names[0] if names else "")


@router.get("/duty/digest")
def duty_digest(district: str = "", _: Principal = Depends(Allowed("view_roster", district_param="district"))) -> dict:
    d = duty.digest(get_repo(), _district(district))
    return {**d, "text": duty.text(d)}


@router.get("/duty/handover")
def get_handover(district: str = "", _: Principal = Depends(Allowed("view_roster", district_param="district"))) -> dict:
    return duty.handover_view(get_repo(), _district(district))


class HandoverBody(BaseModel):
    text: str = Field(max_length=duty.HANDOVER_MAX * 2)


@router.post("/duty/handover/{district}")
def write_handover(district: str, body: HandoverBody,
                   principal: Principal = Depends(Allowed("write_handover", district_param="district"))) -> dict:
    try:
        duty.write_handover(get_repo(), principal.username, principal.role, district, body.text)
    except duty.DutyError as exc:
        raise HTTPException(400, {"code": "handover", "reason": str(exc)}) from None
    return duty.handover_view(get_repo(), district)


@router.post("/duty/handover/{district}/{day}/{shift}/ack")
def ack_handover(district: str, day: str, shift: str,
                 principal: Principal = Depends(Allowed("ack_handover", district_param="district"))) -> dict:
    try:
        duty.acknowledge_handover(get_repo(), principal.username, principal.role, district, day, shift)
    except duty.DutyError as exc:
        raise HTTPException(400, {"code": "handover", "reason": str(exc)}) from None
    return duty.handover_view(get_repo(), district)
