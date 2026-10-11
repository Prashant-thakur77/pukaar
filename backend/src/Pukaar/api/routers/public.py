"""Routes that need no sign-in (CONTRACT.md "Public routes")."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from Pukaar.api import views
from Pukaar.api.auth import DEV_USERS, dev_token
from Pukaar.core.config import get_settings
from Pukaar.delivery import dispatch, telegram
from Pukaar.services import cap
from Pukaar.services import replay as replay_svc
from Pukaar.services import rollcall, safe_places, storage
from Pukaar.services.reports import track_steps
from Pukaar.store.repo import ConflictError, get_repo
from Pukaar.templates import hi
from Pukaar.workflow import tokens
from Pukaar.workflow.client import RetryLater, decide, get_workflow

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
    return {
        "status": "ok" if db == "ok" else "degraded",
        "mode": s.mode,
        "services": {
            "dynamodb": db if not s.is_local else "local mock",
            # No model call on a public route; officers can run /health/deep.
            "bedrock": "configured (checked by /health/deep)" if s.llm_enabled else "disabled: rule fallback in use",
            "polly": "aws" if not s.is_local else "unavailable locally: text only",
            "transcribe": "aws" if not s.is_local else "unavailable locally: audio kept, text needed",
            "telegram": "configured" if telegram.configured() else "not configured: stub channel",
            "guardrail": (f"bedrock guardrail {s.guardrail_id} v{s.guardrail_version} screens report text"
                          if s.guardrail_enabled else "not configured: local heuristic screens report text"),
        },
        "workflow": "local runner (same states as Step Functions)" if s.is_local else "AWS Step Functions",
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


@router.get("/villages/{village_id}/safe-places")
def village_safe_places(village_id: str) -> dict:
    """Baked safe places and walking routes (OpenStreetMap, ODbL) with each place's ledger status."""
    repo = get_repo()
    if repo.get_village(village_id) is None:
        raise HTTPException(404, "Village not found")
    return safe_places.view(repo, village_id)


@router.get("/public/overview")
def overview() -> dict:
    repo = get_repo()
    alerts = repo.list_alerts(limit=12)
    return {
        "counters": views.counters(repo),
        "villages": [{"id": v.id, "name": v.name, "name_hi": v.name_hi, "lat": v.lat, "lon": v.lon, "level": v.level,
                      "coords_verified": v.coords_verified, "replay": v.replay,
                      "rollcall": rollcall.public_for_village(repo, v.id)} for v in repo.list_villages()],
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
            "held": r.held, "replay": r.replay}


@router.get("/replay/status")
def replay_status() -> dict:
    return replay_svc.status(get_repo())


@router.get("/alerts/{alert_id}/audio")
def alert_audio(alert_id: str) -> dict:
    a = get_repo().get_alert(alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    return {"url": storage.url_for(a.audio_key), "text_hi": a.text_hi}


def _api_base(request: Request) -> str:
    """Absolute base of this API, for links inside the feed (behind API Gateway: forwarded proto + host)."""
    s = get_settings()
    if s.api_url and not s.is_local:
        return s.api_url
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


_CAP_CACHE = {"Cache-Control": "public, max-age=60"}


@router.get("/cap/alerts.atom")
def cap_feed(request: Request) -> Response:
    """ATOM index of the latest published alerts, each linking to its CAP 1.2 XML."""
    s = get_settings()
    alerts = [a for a in get_repo().list_alerts(limit=200) if cap.is_published(a)]
    body = cap.atom(alerts, api_base=_api_base(request), web_url=s.web_url)
    return Response(content=body, media_type=cap.ATOM_CONTENT_TYPE, headers=_CAP_CACHE)


@router.get("/cap/alerts/{alert_id}.xml")
def cap_alert(alert_id: str) -> Response:
    """One published alert as a CAP 1.2 <alert>. Unpublished alerts (pending, declined, expired) are 404."""
    s = get_settings()
    repo = get_repo()
    a = repo.get_alert(alert_id)
    if a is None or not cap.is_published(a):
        raise HTTPException(404, "No published alert with this id")
    previous = None
    if a.previous_level != "normal":
        previous = cap.previous_published(a, repo.list_alerts(village_id=a.village_id, limit=100))
    body = cap.render(a, repo.get_village(a.village_id), sender=s.cap_sender, web_url=s.web_url, previous=previous)
    return Response(content=body, media_type=cap.CAP_CONTENT_TYPE, headers=_CAP_CACHE)


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


def _bad_link(exc: tokens.TokenError) -> HTTPException:
    """Expired links are 'late'; forged or broken links are 'invalid', not 'already decided'."""
    if str(exc) == "expired":
        return _late("expired")
    return HTTPException(400, {"code": "invalid", "message_en": hi.INVALID_LINK_EN, "message_hi": hi.INVALID_LINK_HI,
                               "reason": str(exc)})


@router.get("/approval/{token}")
def approval_view(token: str) -> dict:
    try:
        t = tokens.verify(token, "approve")
    except tokens.TokenError as exc:
        raise _bad_link(exc) from exc
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
        raise _bad_link(exc) from exc
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
    except RetryLater as exc:
        raise HTTPException(503, {"code": "retry", "reason": str(exc)}) from exc
    except KeyError:
        raise HTTPException(404, "Alert not found") from None
    return views.alert(a)


@router.get("/safe/{token}")
def safe_share(token: str) -> dict:
    """A family link from the roll-call: first name (or none), time, village. Nothing else."""
    try:
        return rollcall.safe_view(get_repo(), token)
    except tokens.TokenError as exc:
        if str(exc) == "expired":
            raise HTTPException(410, {"code": "expired", "message_en": "This link has expired (links last 7 days).",
                                      "message_hi": "यह लिंक पुराना हो गया है (लिंक 7 दिन चलता है)।"}) from exc
        raise HTTPException(400, {"code": "invalid", "message_en": "This link is not valid. Open the full link from the message.",
                                  "message_hi": "यह लिंक सही नहीं है। संदेश में आया पूरा लिंक खोलें।"}) from exc
    except rollcall.NotCurrent as exc:
        raise HTTPException(410, {"code": "not_current",
                                  "message_en": "This update is no longer current. Please contact your family member directly.",
                                  "message_hi": "यह जानकारी अब ताज़ा नहीं है। कृपया अपने परिजन से सीधे संपर्क करें।"}) from exc


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
