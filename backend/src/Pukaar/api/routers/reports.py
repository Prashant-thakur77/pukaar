"""Villager reports: anonymous upload, officer triage with undo."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from Pukaar.api import views
from Pukaar.api.auth import Allowed
from Pukaar.core import clock
from Pukaar.handlers import worker
from Pukaar.policy.guard import Principal
from Pukaar.services import reports as svc
from Pukaar.services.decision_engine import recompute_village
from Pukaar.services.storage import MAX_UPLOAD_BYTES
from Pukaar.store.models import VERIFIED_STATES
from Pukaar.store.repo import get_repo
from Pukaar.workflow.client import get_workflow

router = APIRouter()
STATES = {"reviewed", "verified", "actioned", "resolved", "duplicate", "false", "unverified"}


async def _read(upload: UploadFile | None) -> tuple[bytes, str] | None:
    if upload is None:
        return None
    data = await upload.read()
    if not data:
        return None
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, {"code": "too_large", "message_en": "File too large (4 MB max). Send a shorter voice note or a smaller photo.",
                                  "message_hi": "फ़ाइल बहुत बड़ी है (4 MB तक)। छोटा संदेश या छोटी फ़ोटो भेजें।"})
    return data, upload.content_type or "application/octet-stream"


@router.post("/reports")
async def create_report(
    request: Request,
    village_id: str = Form(...),
    text: str = Form(""),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    reporter_name: str = Form(""),
    offline_created: bool = Form(False),
    audio: UploadFile | None = File(None),
    photo: UploadFile | None = File(None),
) -> dict:
    repo = get_repo()
    village = repo.get_village(village_id)
    if village is None:
        raise HTTPException(404, "Village not found")
    audio_data, photo_data = await _read(audio), await _read(photo)
    if not text.strip() and audio_data is None and photo_data is None:
        raise HTTPException(400, "Send text, a voice note or a photo")
    r = svc.intake(repo, village, text=text, audio=audio_data, photo=photo_data, lat=lat, lon=lon,
                   reporter_name=reporter_name, offline_created=offline_created, replay=False)
    worker.dispatch({"task": "process_report", "report_id": r.id})
    return {"report": views.report(r), "track_code": r.track_code}


@router.get("/reports")
def list_reports(village_id: str = "", state: str = "",
                 principal: Principal = Depends(Allowed("view_reports", "village"))) -> list[dict]:
    repo = get_repo()
    villages = [village_id] if village_id else [v.id for v in repo.list_villages()]
    if principal.role == "pradhan":
        villages = [v for v in villages if v in principal.village_ids]
    out = [r for vid in villages for r in repo.list_reports(vid, limit=100)]
    if state:
        out = [r for r in out if r.state in set(state.split(","))]
    out.sort(key=lambda r: r.created_at, reverse=True)
    return [views.report(r) for r in out]


class StateChange(BaseModel):
    state: str


@router.patch("/reports/{report_id}/state")
def set_state(report_id: str, body: StateChange,
              principal: Principal = Depends(Allowed("set_report_state", "report", "report_id"))) -> dict:
    if body.state not in STATES:
        raise HTTPException(400, f"state must be one of {', '.join(sorted(STATES))}")
    repo = get_repo()
    r = repo.get_report(report_id)
    if r is None:
        raise HTTPException(404, "Report not found")
    fields = {"state": body.state, "previous_state": r.state, "verified_by": principal.username
              if body.state in VERIFIED_STATES and r.state not in VERIFIED_STATES else r.verified_by}
    if body.state in {"actioned", "resolved"} and not r.acted_at:
        fields["acted_at"] = clock.iso(clock.now())
    updated = repo.update_report(report_id, **fields)
    if (body.state in VERIFIED_STATES) != (r.state in VERIFIED_STATES):
        village = repo.get_village(r.village_id)
        if village is not None:
            recompute_village(repo, village, workflow=get_workflow(), replay=r.replay)
    return views.report(updated)
