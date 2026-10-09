"""Routes that need no sign-in (CONTRACT.md "Public routes")."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from Pukaar.api import views
from Pukaar.api.auth import DEV_USERS, dev_token
from Pukaar.core.config import get_settings
from Pukaar.delivery import dispatch, telegram
from Pukaar.llm.bedrock import BedrockLLM
from Pukaar.services import replay as replay_svc
from Pukaar.services import storage
from Pukaar.services.reports import track_steps
from Pukaar.store.repo import ConflictError, get_repo
from Pukaar.templates import hi
from Pukaar.workflow import tokens
from Pukaar.workflow.client import decide, get_workflow

router = APIRouter()


@router.get("/health")
def health() -> dict:
    s = get_settings()
    repo = get_repo()
    try:
        repo.get_replay()
        db = "ok"
    except Exception as exc:
        db = f"unreachable: {type(exc).__name__}"
    llm = BedrockLLM().health() if s.llm_enabled else None
    return {
        "status": "ok" if db == "ok" else "degraded",
        "mode": s.mode,
        "services": {
            "dynamodb": db if not s.is_local else "local mock",
            "bedrock": ("ok" if llm.reachable else f"unreachable ({llm.detail})") if llm else "disabled: rule fallback in use",
            "polly": "aws" if not s.is_local else "unavailable locally: text only",
            "transcribe": "aws" if not s.is_local else "unavailable locally: audio kept, text needed",
            "telegram": "configured" if telegram.configured() else "not configured: stub channel",
        },
        "model": s.bedrock_model_id,
        "replay_active": repo.get_replay().active if db == "ok" else False,
    }


class DevLogin(BaseModel):
    username: str


@router.post("/auth/dev-login")
def dev_login(body: DevLogin) -> dict:
    if not get_settings().is_local:
        raise HTTPException(404, "Not found")
    if body.username not in DEV_USERS:
        raise HTTPException(400, f"Unknown demo user. Use one of: {', '.join(DEV_USERS)}")
    return {"token": dev_token(body.username), "username": body.username, "role": DEV_USERS[body.username][0]}


@router.get("/villages")
def villages() -> list[dict]:
    repo = get_repo()
    return [views.village(repo, v) for v in repo.list_villages()]


@router.get("/villages/{village_id}")
def village(village_id: str) -> dict:
    repo = get_repo()
    v = repo.get_village(village_id)
    if v is None:
        raise HTTPException(404, "Village not found")
    return views.village_detail(repo, v)


@router.get("/public/overview")
def overview() -> dict:
    repo = get_repo()
    alerts = repo.list_alerts(limit=12)
    return {
        "counters": views.counters(repo),
        "villages": [{"id": v.id, "name": v.name, "name_hi": v.name_hi, "lat": v.lat, "lon": v.lon, "level": v.level,
                      "coords_verified": v.coords_verified, "replay": v.replay} for v in repo.list_villages()],
        "recent_alerts": [{"id": a.id, "village_name": a.village_name, "village_name_hi": a.village_name_hi,
                           "level": a.level, "status": a.status, "created_at": a.created_at, "approved": a.approved,
                           "delivered_count": a.delivered_count, "acknowledged_count": a.acknowledged_count,
                           "replay": a.replay} for a in alerts],
        "replay": {"active": repo.get_replay().active},
    }


@router.get("/track/{code}")
def track(code: str) -> dict:
    repo = get_repo()
    r = repo.report_by_track(code.upper())
    if r is None:
        raise HTTPException(404, "Tracking code not found")
    v = repo.get_village(r.village_id)
    return {"code": r.track_code, "village_name": v.name if v else r.village_id, "village_name_hi": v.name_hi if v else "",
            "created_at": r.created_at, "report_type": r.report_type, "state": r.state, "steps": track_steps(r),
            "replay": r.replay}


@router.get("/replay/status")
def replay_status() -> dict:
    return replay_svc.status(get_repo())


@router.get("/alerts/{alert_id}/audio")
def alert_audio(alert_id: str) -> dict:
    a = get_repo().get_alert(alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    return {"url": storage.url_for(a.audio_key), "text_hi": a.text_hi}


@router.get("/media/{key:path}")
def media(key: str) -> Response:
    if not get_settings().is_local:
        raise HTTPException(404, "Not found")
    try:
        data, ctype = storage.get_bytes(key)
    except Exception:
        raise HTTPException(404, "Not found") from None
    return Response(content=data, media_type=ctype)


def _late(detail: str) -> HTTPException:
    return HTTPException(409, {"code": "late", "message_en": hi.LATE_REPLY_EN, "message_hi": hi.LATE_REPLY_HI,
                               "reason": detail})


@router.get("/approval/{token}")
def approval_view(token: str) -> dict:
    try:
        t = tokens.verify(token, "approve")
    except tokens.TokenError as exc:
        raise _late(str(exc)) from exc
    a = get_repo().get_alert(t.alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    valid = a.status == "pending" and a.token_version == t.version
    return {"alert": views.alert(a), "expires_at": t.expires, "valid": valid, "officer": t.subject}


class LinkDecision(BaseModel):
    decision: str  # approve | decline


@router.post("/approval/{token}")
def approval_decide(token: str, body: LinkDecision) -> dict:
    from Pukaar.policy.guard import Principal, authorize

    try:
        t = tokens.verify(token, "approve")
    except tokens.TokenError as exc:
        raise _late(str(exc)) from exc
    if body.decision not in {"approve", "decline"}:
        raise HTTPException(400, "decision must be approve or decline")
    repo = get_repo()
    officer = Principal(t.subject, "officer")
    d = authorize(officer, body.decision, "alert", t.alert_id, repo=repo)
    if not d.allowed:
        raise HTTPException(403, {"code": "denied", "reason": d.reason})
    try:
        a = decide(repo, get_workflow(), t.alert_id, "approved" if body.decision == "approve" else "declined",
                   f"{t.subject} (link)", token_version=t.version)
    except ConflictError as exc:
        raise _late(str(exc)) from exc
    except KeyError:
        raise HTTPException(404, "Alert not found") from None
    return views.alert(a)


class Ack(BaseModel):
    token: str


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: str, body: Ack) -> dict:
    try:
        t = tokens.verify(body.token, "ack")
    except tokens.TokenError as exc:
        raise HTTPException(400, f"Invalid acknowledgement link: {exc}") from exc
    if t.alert_id != alert_id:
        raise HTTPException(400, "Link does not match this alert")
    d = dispatch.acknowledge(get_repo(), alert_id, t.subject)
    if d is None:
        return {"ok": True, "already": True}
    return {"ok": True, "acknowledged_at": d.acknowledged_at}
