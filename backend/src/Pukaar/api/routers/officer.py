"""Officer console routes. Each one passes policy.guard.authorize() first."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from Pukaar.api import views
from Pukaar.api.auth import Allowed, require_user
from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.handlers import worker
from Pukaar.llm.bedrock import BedrockLLM
from Pukaar.policy.guard import Principal
from Pukaar.services import analyst
from Pukaar.services import replay as replay_svc
from Pukaar.store.models import Directive
from Pukaar.store.repo import ConflictError, get_repo
from Pukaar.templates import hi
from Pukaar.workflow.client import decide, get_workflow

router = APIRouter()


def _llm() -> BedrockLLM | None:
    return BedrockLLM() if get_settings().llm_enabled else None


@router.get("/me")
def me(principal: Principal = Depends(require_user)) -> dict:
    return {"username": principal.username, "role": principal.role, "village_ids": principal.village_ids}


@router.get("/health/deep")
def health_deep(_: Principal = Depends(Allowed("health_deep"))) -> dict:
    llm = _llm()
    if llm is None:
        return {"bedrock": "disabled", "model": get_settings().bedrock_model_id}
    text = llm.generate_text("Reply with the single word OK.", "ping", max_tokens=5)
    return {"bedrock": "ok" if text else "failed", "model": llm.model_name}


@router.get("/alerts")
def list_alerts(status: str = "", village_id: str = "", _: Principal = Depends(Allowed("view_console"))) -> list[dict]:
    return [views.alert(a) for a in get_repo().list_alerts(status=status or None, village_id=village_id or None)]


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: str, _: Principal = Depends(Allowed("view_console", "alert", "alert_id"))) -> dict:
    repo = get_repo()
    a = repo.get_alert(alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    audit = [r for day in {a.created_at[:10], clock.iso(clock.now())[:10]} for r in repo.list_audit(day, f"alert:{a.id}")]
    return {"alert": views.alert(a), "deliveries": [d.model_dump() for d in repo.list_deliveries(a.id)],
            "timeline": [t.model_dump() for t in repo.list_timeline(a.id)],
            "audit": [r.model_dump() for r in sorted(audit, key=lambda r: r.at)]}


class DeclineBody(BaseModel):
    reason: str = ""


def _decide(alert_id: str, decision: str, principal: Principal, reason: str = "") -> dict:
    try:
        a = decide(get_repo(), get_workflow(), alert_id, decision, principal.username, reason=reason)
    except ConflictError as exc:
        raise HTTPException(409, {"code": "late", "message_en": hi.LATE_REPLY_EN, "message_hi": hi.LATE_REPLY_HI,
                                  "reason": str(exc)}) from exc
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


class ReplayBody(BaseModel):
    scenario: str = replay_svc.DEFAULT_SCENARIO
    speed_seconds_per_hour: float = 2.0


@router.post("/replay/start")
def replay_start(body: ReplayBody | None = None, _: Principal = Depends(Allowed("start_replay"))) -> dict:
    body = body or ReplayBody()
    try:
        replay_svc.start(get_repo(), body.scenario)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    worker.dispatch({"task": "replay", "speed_seconds_per_hour": max(0.0, min(body.speed_seconds_per_hour, 30.0))})
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
