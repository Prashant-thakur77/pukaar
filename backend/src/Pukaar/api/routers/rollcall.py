"""Safety roll-call ("Surakshit Hoon") routes for officers and pradhans. Each passes Cedar first:
view_rollcall, open_rollcall and remind_rollcall, with the roll-call's own village as context.
No phone number or chat id leaves these routes: the board has names and times only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from Pukaar.api.auth import Allowed, require_user
from Pukaar.policy.guard import Principal, authorize
from Pukaar.services import rollcall as svc
from Pukaar.store.models import RollCall
from Pukaar.store.repo import get_repo

router = APIRouter()


def _load(rollcall_id: str, principal: Principal, action: str) -> RollCall:
    repo = get_repo()
    rc = repo.get_rollcall(rollcall_id)
    if rc is None:
        raise HTTPException(404, "Roll-call not found")
    village = repo.get_village(rc.village_id)
    decision = authorize(principal, action, "rollcall", rc.id,
                         {"village_id": rc.village_id, "replay": bool(village and village.replay)}, repo=repo)
    if not decision.allowed:
        # A pradhan of another village learns nothing about this roll-call beyond "not yours".
        raise HTTPException(403, {"code": "denied", "reason": decision.reason, "action": action, "role": principal.role})
    return rc


@router.get("/rollcalls")
def list_rollcalls(village_id: str = "", principal: Principal = Depends(Allowed("view_rollcall"))) -> list[dict]:
    repo = get_repo()
    ids = [village_id] if village_id else [v.id for v in repo.list_villages()]
    if principal.role != "officer":
        ids = [i for i in ids if i in principal.village_ids]
    out = [svc.summary(rc) for vid in ids for rc in repo.list_rollcalls(vid, limit=10)]
    return sorted(out, key=lambda r: r["opened_at"], reverse=True)


@router.get("/rollcalls/{rollcall_id}")
def get_rollcall(rollcall_id: str, principal: Principal = Depends(require_user)) -> dict:
    return svc.board(get_repo(), _load(rollcall_id, principal, "view_rollcall"))


class OpenBody(BaseModel):
    village_id: str
    exercise: bool = False


@router.post("/rollcalls")
def open_rollcall(body: OpenBody, principal: Principal = Depends(require_user)) -> dict:
    repo = get_repo()
    village = repo.get_village(body.village_id)
    if village is None:
        raise HTTPException(404, "Village not found")
    try:
        rc = svc.open_rollcall(repo, village, principal=principal, exercise=body.exercise)
    except svc.RollCallError as exc:
        if exc.code == "denied":
            raise HTTPException(403, {"code": "denied", "reason": str(exc), "action": "open_rollcall",
                                      "role": principal.role}) from exc
        raise HTTPException(409, {"code": exc.code, "reason": str(exc), **exc.extra}) from exc
    return svc.board(repo, rc)


@router.post("/rollcalls/{rollcall_id}/remind")
def remind(rollcall_id: str, principal: Principal = Depends(require_user)) -> dict:
    repo = get_repo()
    rc = _load(rollcall_id, principal, "remind_rollcall")
    try:
        result = svc.remind(repo, rc)
    except svc.RollCallError as exc:
        if exc.code == "rate_limited":
            wait = int(exc.extra.get("retry_after_seconds", svc.REMIND_EVERY_SECONDS))
            raise HTTPException(429, {"code": "rate_limited", "retry_after_seconds": wait,
                                      "message_en": f"A reminder went out less than 30 minutes ago. Try again in {max(1, wait // 60)} min.",
                                      "message_hi": f"पिछला रिमाइंडर 30 मिनट से कम पहले गया था। {max(1, wait // 60)} मिनट बाद फिर कोशिश करें।"},
                                headers={"Retry-After": str(wait)}) from exc
        raise HTTPException(409, {"code": exc.code, "reason": str(exc)}) from exc
    return {**result, "board": svc.board(repo, repo.get_rollcall(rc.id) or rc)}
