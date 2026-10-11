"""Officer console routes. Each one passes policy.guard.authorize() first."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from Pukaar.api import views
from Pukaar.api.auth import Allowed, require_user
from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.handlers import worker
from Pukaar.llm.bedrock import BedrockLLM
from Pukaar.policy.guard import Principal, authorize
from Pukaar.services import after_action, analyst, checklist, safe_places
from Pukaar.services import replay as replay_svc
from Pukaar.store.models import SHELTER_STATES, AuditRow, Directive, ShelterStatus
from Pukaar.store.repo import ConflictError, get_repo
from Pukaar.templates import hi
from Pukaar.workflow.client import RetryLater, decide, get_workflow

router = APIRouter()


def _llm() -> BedrockLLM | None:
    return BedrockLLM() if get_settings().llm_enabled else None


@router.get("/me")
def me(principal: Principal = Depends(require_user)) -> dict:
    return {"username": principal.username, "role": principal.role, "village_ids": principal.village_ids}


@router.post("/me/telegram-link")
def telegram_link(principal: Principal = Depends(Allowed("approve"))) -> dict:
    """One-time code (15 minutes) that links this officer's Telegram chat for approval links."""
    from Pukaar.core.ids import track_code

    code = track_code() + track_code()
    get_repo().put_link_code(code, principal.username)
    return {"code": code, "command": f"/start link_{code}", "expires_in_seconds": 900}


@router.get("/dev/approval-link/{alert_id}")
def dev_approval_link(alert_id: str, principal: Principal = Depends(Allowed("dev_link", "alert", "alert_id"))) -> dict:
    """Local mode only: the one-tap link the asked officer would get on Telegram (for demos)."""
    if not get_settings().is_local:
        raise HTTPException(404, "Not found")
    from Pukaar.workflow import tokens

    a = get_repo().get_alert(alert_id)
    if a is None or a.status != "pending":
        raise HTTPException(409, {"code": "late", "message_en": hi.LATE_REPLY_EN, "message_hi": hi.LATE_REPLY_HI,
                                  "reason": "not pending"})
    village = get_repo().get_village(a.village_id)
    officers = village.officers if village else []
    officer = officers[a.officer_index] if a.officer_index < len(officers) else principal.username
    token = tokens.sign(a.id, officer, a.token_version, "approve")
    return {"url": f"{get_settings().web_url}/a/{token}", "token": token, "officer": officer}


@router.get("/health/deep")
def health_deep(_: Principal = Depends(Allowed("health_deep"))) -> dict:
    """One 1-token model call, now; the answer also refreshes the cached flag the /agents page reads."""
    from Pukaar.services import model_probe

    s = get_settings()
    if not s.llm_enabled:
        return {"bedrock": "disabled", "model": s.bedrock_model_id}
    rec = model_probe.maybe_run(get_repo(), force=True) or {}
    state = rec.get("state")
    return {"bedrock": {"live": "ok", "pending": "pending model access"}.get(state or "", "failed"),
            "model": s.bedrock_model_id, "detail": rec.get("detail", "probe did not run")}


@router.get("/alerts")
def list_alerts(status: str = "", village_id: str = "", principal: Principal = Depends(Allowed("view_console"))) -> list[dict]:
    alerts = get_repo().list_alerts(status=status or None, village_id=village_id or None)
    if principal.role != "officer":
        alerts = [a for a in alerts if a.village_id in principal.village_ids]
    return [views.alert(a) for a in alerts]


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: str, principal: Principal = Depends(Allowed("view_console", "alert", "alert_id"))) -> dict:
    repo = get_repo()
    a = repo.get_alert(alert_id)
    if a is None or (principal.role != "officer" and a.village_id not in principal.village_ids):
        raise HTTPException(404, "Alert not found")
    audit = [r for day in {a.created_at[:10], clock.iso(clock.now())[:10]} for r in repo.list_audit(day, f"alert:{a.id}")]
    return {"alert": views.alert(a), "deliveries": [d.model_dump() for d in repo.list_deliveries(a.id)],
            "timeline": [t.model_dump() for t in repo.list_timeline(a.id)],
            "audit": [r.model_dump() for r in sorted(audit, key=lambda r: r.at)]}


# The report is static HTML from the alert's own records; it runs no script and loads nothing.
_REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'"


@router.get("/alerts/{alert_id}/after-action")
def get_after_action(alert_id: str, fresh: bool = False, format: str = "html",
                     principal: Principal = Depends(require_user)) -> Response:
    """The after-action report (services/after_action.py): the copy stored when the alert closed,
    or one built now if none was stored (or fresh=true). format=json returns the small summary."""
    repo = get_repo()
    a = repo.get_alert(alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    decision = authorize(principal, "view_after_action", "alert", a.id,
                         {"village_id": a.village_id, "replay": a.replay, "level": a.level}, repo=repo)
    if not decision.allowed:
        raise HTTPException(403, {"code": "denied", "reason": decision.reason, "action": "view_after_action",
                                  "role": principal.role})
    if format == "json":
        return JSONResponse(after_action.build(repo, a).summary)
    body = None if fresh else after_action.load_stored(a.id)
    if body is None:
        body = after_action.build(repo, a).html
    return Response(body, media_type="text/html; charset=utf-8", headers={
        "Content-Disposition": f'inline; filename="pukaar-after-action-{a.id}.html"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": _REPORT_CSP})


class DeclineBody(BaseModel):
    reason: str = ""


def _decide(alert_id: str, decision: str, principal: Principal, reason: str = "") -> dict:
    try:
        a = decide(get_repo(), get_workflow(), alert_id, decision, principal.username, reason=reason)
    except ConflictError as exc:
        raise HTTPException(409, {"code": "late", "message_en": hi.LATE_REPLY_EN, "message_hi": hi.LATE_REPLY_HI,
                                  "reason": str(exc)}) from exc
    except RetryLater as exc:
        raise HTTPException(503, {"code": "retry", "reason": str(exc)}) from exc
    except KeyError:
        raise HTTPException(404, "Alert not found") from None
    return views.alert(a)


@router.post("/alerts/{alert_id}/approve")
def approve(alert_id: str, principal: Principal = Depends(Allowed("approve", "alert", "alert_id"))) -> dict:
    return _decide(alert_id, "approved", principal)


@router.post("/alerts/{alert_id}/decline")
def decline(alert_id: str, body: DeclineBody | None = None,
            principal: Principal = Depends(Allowed("decline", "alert", "alert_id"))) -> dict:
    return _decide(alert_id, "declined", principal, (body.reason if body else "")[:200])


@router.get("/directives")
def list_directives(village_id: str = "") -> list[dict]:
    repo = get_repo()
    ids = [village_id] if village_id else [v.id for v in repo.list_villages()]
    return [d.model_dump() for vid in ids for d in repo.list_directives(vid)]


class DirectiveBody(BaseModel):
    village_id: str
    type: str
    note_en: str = ""


@router.post("/directives")
def create_directive(body: DirectiveBody, principal: Principal = Depends(Allowed("issue_directive", "village"))) -> dict:
    repo = get_repo()
    if repo.get_village(body.village_id) is None:
        raise HTTPException(404, "Village not found")
    if body.type not in hi.DIRECTIVE_HI:
        raise HTTPException(400, f"type must be one of {', '.join(hi.DIRECTIVE_HI)}")
    for old in repo.list_directives(body.village_id):
        if old.active:
            repo.put_directive(old.model_copy(update={"active": False}))
    note = body.note_en.strip()[:200]
    d = Directive(id=new_id("dir"), village_id=body.village_id, type=body.type, text_hi=hi.DIRECTIVE_HI[body.type],  # type: ignore[arg-type]
                  text_en=hi.DIRECTIVE_EN[body.type] + (f" Note: {note}" if note else ""),
                  issued_by=principal.username, issued_at=clock.iso(clock.now()))
    repo.put_directive(d)
    return d.model_dump()


class ChecklistBody(BaseModel):
    done: bool = True


@router.post("/villages/{village_id}/checklist/{item}")
def tick_checklist(village_id: str, item: str, body: ChecklistBody | None = None,
                   principal: Principal = Depends(require_user)) -> dict:
    """Tick or untick one early-action task. Officers: any village; a pradhan: only their own."""
    repo = get_repo()
    decision = authorize(principal, "tick_checklist", "village", village_id, {"village_id": village_id}, repo=repo)
    if not decision.allowed:
        raise HTTPException(403, {"code": "denied", "reason": decision.reason, "action": "tick_checklist",
                                  "role": principal.role})
    if repo.get_village(village_id) is None:
        raise HTTPException(404, "Village not found")
    try:
        checklist.set_done(repo, village_id, item, (body or ChecklistBody()).done, principal.username, principal.role)
    except KeyError:
        raise HTTPException(404, "Checklist item not found") from None
    return checklist.view(repo, village_id)


class ShelterBody(BaseModel):
    status: str
    capacity: int | None = None
    note: str = ""


@router.post("/villages/{village_id}/shelters/{place_id}")
def set_shelter(village_id: str, place_id: str, body: ShelterBody,
                principal: Principal = Depends(Allowed("set_shelter_status", "village", "village_id",
                                                       village_from_path=True))) -> dict:
    """Shelter ledger: a pradhan (own village) or an officer marks a baked safe place OPEN, STANDBY, FULL or CLOSED."""
    repo = get_repo()
    if repo.get_village(village_id) is None:
        raise HTTPException(404, "Village not found")
    if place_id not in safe_places.place_ids(village_id):
        raise HTTPException(404, "Safe place not found for this village")
    status = body.status.strip().upper()
    if status not in SHELTER_STATES:
        raise HTTPException(400, f"status must be one of {', '.join(SHELTER_STATES)}")
    if body.capacity is not None and not 0 <= body.capacity <= 100000:
        raise HTTPException(400, "capacity must be between 0 and 100000")
    old = repo.list_shelters(village_id).get(place_id)
    now = clock.iso(clock.now())
    row = ShelterStatus(village_id=village_id, place_id=place_id, status=status,  # type: ignore[arg-type]
                        capacity=body.capacity, note=body.note.strip()[:200], updated_by=principal.username,
                        updated_at=now)
    repo.put_shelter(row)
    # The authorize() row records the permission; this one records what changed.
    repo.append_audit(AuditRow(
        at=now, id=new_id("aud"), actor=principal.username, role=principal.role, action="shelter_changed",
        resource=f"shelter:{village_id}/{place_id}", decision="allow",
        reason=f"{old.status if old else 'UNCONFIRMED'} -> {status}"
               + (f"; capacity {body.capacity}" if body.capacity is not None else "")))
    return safe_places.view(repo, village_id)


class RoadBlockBody(BaseModel):
    lat: float
    lon: float
    note: str
    label: str = ""


def _roadblock_audit(principal: Principal, action: str, village_id: str, block_id: str, reason: str) -> None:
    get_repo().append_audit(AuditRow(
        at=clock.iso(clock.now()), id=new_id("aud"), actor=principal.username, role=principal.role, action=action,
        resource=f"roadblock:{village_id}/{block_id}", decision="allow", reason=reason))


@router.post("/villages/{village_id}/roadblocks")
def add_roadblock(village_id: str, body: RoadBlockBody,
                  principal: Principal = Depends(Allowed("block_road", "village", "village_id",
                                                         village_from_path=True))) -> dict:
    """Mark a point on a baked evacuation route blocked (7 days unless renewed). Routes are not recomputed."""
    repo = get_repo()
    if repo.get_village(village_id) is None:
        raise HTTPException(404, "Village not found")
    try:
        block = safe_places.new_roadblock(village_id, new_id("rb"), body.lat, body.lon, body.label, body.note,
                                          principal.username, clock.now())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    repo.put_roadblock(block)
    hit = sorted(safe_places.blocked_routes(village_id, [block]))
    _roadblock_audit(principal, "road_blocked", village_id, block.id,
                     f"open -> BLOCKED at {block.lat},{block.lon}"
                     + (f" ({block.label})" if block.label else "") + f"; routes to {', '.join(hit) or 'none'}")
    return safe_places.view(repo, village_id)


def _existing_block(village_id: str, block_id: str):
    block = get_repo().get_roadblock(village_id, block_id)
    if block is None or block.cleared_at is not None or block.expires_at <= clock.iso(clock.now()):
        raise HTTPException(404, "Road block not found (it may have been cleared or expired)")
    return block


@router.post("/villages/{village_id}/roadblocks/{block_id}/renew")
def renew_roadblock(village_id: str, block_id: str,
                    principal: Principal = Depends(Allowed("block_road", "village", "village_id",
                                                           village_from_path=True))) -> dict:
    """Keep a block for another 7 days from now."""
    repo = get_repo()
    old = _existing_block(village_id, block_id)
    block = safe_places.renewed(old, principal.username, clock.now())
    repo.put_roadblock(block)
    _roadblock_audit(principal, "road_block_renewed", village_id, block_id,
                     f"expires {old.expires_at} -> {block.expires_at}")
    return safe_places.view(repo, village_id)


@router.post("/villages/{village_id}/roadblocks/{block_id}/clear")
def clear_roadblock(village_id: str, block_id: str,
                    principal: Principal = Depends(Allowed("block_road", "village", "village_id",
                                                           village_from_path=True))) -> dict:
    """The road is open again: the routes through it count once more."""
    repo = get_repo()
    block = safe_places.cleared(_existing_block(village_id, block_id), principal.username, clock.now())
    repo.put_roadblock(block)
    _roadblock_audit(principal, "road_block_cleared", village_id, block_id, "BLOCKED -> open")
    return safe_places.view(repo, village_id)


class ReplayBody(BaseModel):
    scenario: str = replay_svc.DEFAULT_SCENARIO
    speed_seconds_per_hour: float = 4.0  # narratable pace; capped to fit one worker run


@router.post("/replay/start")
def replay_start(body: ReplayBody | None = None, _: Principal = Depends(Allowed("start_replay"))) -> dict:
    body = body or ReplayBody()
    try:
        st = replay_svc.start(get_repo(), body.scenario)
    except PermissionError as exc:
        raise HTTPException(403, {"code": "disabled", "reason": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    speed = max(0.0, min(body.speed_seconds_per_hour, replay_svc.max_speed(st.hours_total)))
    worker.dispatch({"task": "replay", "speed_seconds_per_hour": speed})
    return replay_svc.status(get_repo())


@router.post("/replay/reset")
def replay_reset(_: Principal = Depends(Allowed("start_replay"))) -> dict:
    replay_svc.reset(get_repo())
    return replay_svc.status(get_repo())


@router.get("/audit")
def audit(date: str = "", resource: str = "", _: Principal = Depends(Allowed("read_audit"))) -> list[dict]:
    day = date or clock.iso(clock.now())[:10]
    return [r.model_dump() for r in get_repo().list_audit(day, resource or None)]


@router.get("/stats")
def stats(_: Principal = Depends(Allowed("view_console"))) -> dict:
    repo = get_repo()
    alerts = repo.list_alerts(limit=500)
    by_status: dict[str, int] = {}
    for a in alerts:
        by_status[a.status] = by_status.get(a.status, 0) + 1
    levels: dict[str, int] = {}
    for v in repo.list_villages():
        levels[v.level] = levels.get(v.level, 0) + 1
    return {**views.counters(repo), "alerts_by_status": by_status, "levels": levels}


class AskBody(BaseModel):
    question: str


@router.post("/ask/officer")
def ask_officer(body: AskBody, _: Principal = Depends(Allowed("ask_analyst"))) -> dict:
    if not body.question.strip():
        raise HTTPException(400, "Ask a question")
    return analyst.ask(get_repo(), body.question, _llm())
