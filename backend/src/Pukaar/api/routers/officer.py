"""Officer console routes. Each one passes policy.guard.authorize() first."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from Pukaar.api import views
from Pukaar.api.auth import Allowed, current_principal, require_user
from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.handlers import worker
from Pukaar.llm.bedrock import BedrockLLM
from Pukaar.policy.guard import READS_EVERYTHING, Principal, authorize
from Pukaar.services import after_action, analyst, checklist, district_settings, roster, safe_places
from Pukaar.services import replay as replay_svc
from Pukaar.store.models import (
    ALERT_OUTCOMES, OPEN_ALERT_STATUSES, RELAY_ROLES, SHELTER_STATES, AuditRow, Directive, ShelterStatus,
)
from Pukaar.store.repo import ConflictError, get_repo
from Pukaar.templates import hi
from Pukaar.workflow.client import RetryLater, decide, get_workflow

router = APIRouter()


def _llm() -> BedrockLLM | None:
    return BedrockLLM() if get_settings().llm_enabled else None


@router.get("/me")
def me(principal: Principal = Depends(require_user)) -> dict:
    return {"username": principal.username, "role": principal.role, "village_ids": principal.village_ids,
            "district_ids": principal.district_ids}


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
    officers = a.officer_chain
    if not officers:  # drafted before chains were stored: the fallback list
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
def list_alerts(status: str = "", village_id: str = "", district: str = "",
                principal: Principal = Depends(Allowed("view_console"))) -> list[dict]:
    """status=pending (and district=...) reads the status index: every pending alert, however old
    (Repo.list_alerts), never only those among the newest few hundred."""
    alerts = get_repo().list_alerts(status=status or None, village_id=village_id or None, district=district or None)
    if principal.role not in READS_EVERYTHING:
        alerts = [a for a in alerts if a.village_id in principal.village_ids]
    return [views.alert(a) for a in alerts]


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: str, principal: Principal = Depends(Allowed("view_console", "alert", "alert_id"))) -> dict:
    repo = get_repo()
    a = repo.get_alert(alert_id)
    if a is None or (principal.role not in READS_EVERYTHING and a.village_id not in principal.village_ids):
        raise HTTPException(404, "Alert not found")
    audit = [r for day in {a.created_at[:10], clock.iso(clock.now())[:10]} for r in repo.list_audit(day, f"alert:{a.id}")]
    # Each row says whether the person is a village relay (pradhan, gauge reader, task force).
    roles = {r.id: r.role for r in repo.list_recipients(a.village_id)}
    deliveries = [{**d.model_dump(exclude={"all_clear_call_id"}),
                   "relay_role": roles.get(d.recipient_id) if roles.get(d.recipient_id) in RELAY_ROLES else None}
                  for d in repo.list_deliveries(a.id)]
    # Who it reached (names, chat ids, call ids) is villagers' data: a public demo account sees it
    # for replay alerts only, and otherwise the same rows with the person left out.
    people = authorize(principal, "view_recipients", "alert", a.id,
                       {"village_id": a.village_id, "replay": a.replay, "level": a.level}, repo=repo)
    if not people.allowed:
        deliveries = [views.masked_delivery(d, i) for i, d in enumerate(deliveries, 1)]
    from Pukaar.services import sirens

    return {"alert": views.alert(a), "deliveries": deliveries, "sirens": sirens.tier(repo, a),
            "timeline": [t.model_dump() for t in repo.list_timeline(a.id)],
            "audit": [r.model_dump() for r in sorted(audit, key=lambda r: r.at)]}


@router.get("/alerts/{alert_id}/metrics")
def alert_metrics(alert_id: str, principal: Principal = Depends(Allowed("view_console", "alert", "alert_id"))) -> dict:
    """The ten pilot metrics for this alert (services/pilot_metrics.py): counts and times, no names or numbers."""
    from Pukaar.services import pilot_metrics

    repo = get_repo()
    a = repo.get_alert(alert_id)
    if a is None or (principal.role not in READS_EVERYTHING and a.village_id not in principal.village_ids):
        raise HTTPException(404, "Alert not found")
    return {"alert_id": a.id, **pilot_metrics.alert_metrics(repo, a)}


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


class OutcomeBody(BaseModel):
    outcome: str
    # When harm began, if known (ISO 8601): lead time achieved, pilot metric 5. Optional; "" clears it.
    onset_at: str | None = None


@router.post("/alerts/{alert_id}/outcome")
def set_outcome(alert_id: str, body: OutcomeBody,
                principal: Principal = Depends(Allowed("set_alert_outcome", "alert", "alert_id"))) -> dict:
    """"Was this real?": real_flood, no_flood or unknown, set by an officer after a live alert closed.
    It can be corrected later (a flood found next morning); each change is on the alert's timeline and
    in the Cedar audit trail. The stored after-action report is rebuilt so it shows the answer."""
    if body.outcome not in ALERT_OUTCOMES:
        raise HTTPException(400, f"outcome must be one of {', '.join(ALERT_OUTCOMES)}")
    repo = get_repo()
    a = repo.get_alert(alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    if views.is_replay(a) or views.is_drill(a) or views.is_demo(a):
        raise HTTPException(409, {"code": "not_live", "message_en": "Replays and drills are not real events.",
                                  "message_hi": "रीप्ले और अभ्यास असली घटनाएँ नहीं हैं।"})
    if a.status in OPEN_ALERT_STATUSES:
        raise HTTPException(409, {"code": "open", "message_en": "Record this after the alert closes.",
                                  "message_hi": "चेतावनी बंद होने के बाद दर्ज करें।"})
    now = clock.iso(clock.now())
    fields: dict = {"outcome": body.outcome, "outcome_by": principal.username, "outcome_at": now}
    if body.onset_at is not None:
        try:
            fields["outcome_onset_at"] = clock.iso(clock.parse(body.onset_at)) if body.onset_at.strip() else None
        except (ValueError, TypeError):
            raise HTTPException(400, "onset_at must be an ISO 8601 time, e.g. 2026-07-01T02:30:00Z") from None
    updated = repo.update_alert(a.id, **fields)
    repo.add_timeline(a.id, "outcome", f"{body.outcome} by {principal.username}"
                      + (f" (was {a.outcome})" if a.outcome and a.outcome != body.outcome else "")
                      + (f"; harm began {fields['outcome_onset_at']}" if fields.get("outcome_onset_at") else ""))
    # The "why we warned" note, once per alert: the outcome is what it reports (services/followup.py; never raises).
    from Pukaar.services import followup

    if followup.send(repo, updated, "outcome") is not None:
        updated = repo.get_alert(a.id) or updated
    try:
        after_action.store(after_action.build(repo, updated))
    except Exception as exc:  # the answer is stored either way; a fresh report shows it too
        from Pukaar.core.log import get_logger, log

        log(get_logger("officer"), "after-action rebuild failed", 30, alert_id=a.id, error=str(exc)[:200])
    return views.alert(updated)


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


class EditBody(BaseModel):
    text_hi: str
    text_en: str = ""


def _pending(alert_id: str):
    a = get_repo().get_alert(alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    if a.status != "pending":
        raise HTTPException(409, {"code": "late", "message_en": hi.LATE_REPLY_EN, "message_hi": hi.LATE_REPLY_HI,
                                  "reason": f"the alert is {a.status}, not pending"})
    return a


@router.post("/alerts/{alert_id}/edit")
def edit_alert(alert_id: str, body: EditBody,
               principal: Principal = Depends(Allowed("edit_alert", "alert", "alert_id"))) -> dict:
    """An officer changes what a pending alert will say, before approving it. Held to the same rules as a model
    draft (services/drafting.check_officer_edit); the spoken copy is made again from the new Hindi."""
    import re

    from Pukaar.services import drafting
    from Pukaar.store.models import DraftCheck
    from Pukaar.voice import polly

    repo = get_repo()
    a = _pending(alert_id)
    new_hi = re.sub(r"\s+", " ", body.text_hi).strip()
    new_en = re.sub(r"\s+", " ", body.text_en).strip() or a.text_en
    if new_hi == a.text_hi and new_en == a.text_en:
        return views.alert(a)
    village = repo.get_village(a.village_id)
    if village is None:
        raise HTTPException(404, "Village not found")
    villages = repo.list_villages()
    others = [v.name for v in villages if v.id != village.id] + [v.name_hi for v in villages if v.id != village.id]
    others += sorted(safe_places.all_place_names())
    check = drafting.check_officer_edit(new_hi, new_en, a.text_hi, a.text_en, village, a.level, others)
    if not check.passed:
        raise HTTPException(422, {"code": "edit_rejected", "reason": check.reason,
                                  "message_en": f"Not saved: {check.reason}.",
                                  "message_hi": f"बदलाव नहीं हुआ: {check.reason}।"})
    updated = repo.update_alert(a.id, text_hi=new_hi, text_en=new_en,
                                draft_check=DraftCheck(passed=True, reason=f"edited by {principal.username}; {check.reason}"))
    repo.add_timeline(a.id, "edited", f"message edited by {principal.username}")
    from Pukaar.templates import script

    script.note_voice_length(repo, a.id, new_hi)  # a long edit: said on the timeline (voice is billed per minute)
    # The spoken copies follow the words: the alert MP3 now, the call audio again at delivery.
    try:
        audio_key = polly.synthesize_alert(a.id, new_hi)
    except Exception:  # without audio the page and the call speak the text
        audio_key = None
    updated = repo.update_alert(a.id, audio_key=audio_key, call_audio_key=None)
    from Pukaar.services import events

    events.alert_changed(updated)
    return views.alert(updated)


class SnoozeBody(BaseModel):
    minutes: int = 10


@router.post("/alerts/{alert_id}/snooze")
def snooze_alert(alert_id: str, body: SnoozeBody | None = None,
                 principal: Principal = Depends(Allowed("snooze_alert", "alert", "alert_id"))) -> dict:
    """"In 10 minutes": the console sets this alert aside for the officer who asked, and the audit trail says so.
    Nothing else changes: the alert stays pending, and the escalation to the next officer runs on its own clock."""
    from datetime import timedelta

    a = _pending(alert_id)
    minutes = max(1, min(60, body.minutes if body else 10))
    until = clock.iso(clock.now() + timedelta(minutes=minutes))
    get_repo().add_timeline(a.id, "snoozed", f"set aside for {minutes} min by {principal.username}; escalation continues")
    return {"alert_id": a.id, "snoozed_until": until, "minutes": minutes}


@router.get("/directives")
def list_directives(request: Request, village_id: str = "") -> list[dict]:
    """Public. Who issued a directive (an officer's username) is shown to a signed-in caller only."""
    repo = get_repo()
    ids = [village_id] if village_id else [v.id for v in repo.list_villages()]
    signed_in = current_principal(request) is not None
    return [d.model_dump() if signed_in else views.public_directive(d)
            for vid in ids for d in repo.list_directives(vid)]


class DirectiveBody(BaseModel):
    village_id: str
    type: str
    note_en: str = ""


@router.post("/directives")
def create_directive(body: DirectiveBody, principal: Principal = Depends(require_user)) -> dict:
    repo = get_repo()
    if repo.get_village(body.village_id) is None:
        raise HTTPException(404, "Village not found")
    # Against the village in the body, the one the directive is for (its district scope included).
    decision = authorize(principal, "issue_directive", "village", body.village_id, {"village_id": body.village_id},
                         repo=repo)
    if not decision.allowed:
        raise HTTPException(403, {"code": "denied", "reason": decision.reason, "action": "issue_directive",
                                  "role": principal.role})
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
    out = d.model_dump()
    if body.type == "all_clear":
        # The officer stands the village down: everyone contacted for its recent alerts hears so.
        from Pukaar.workflow.steps import stand_down_village

        out["stood_down"] = stand_down_village(repo, body.village_id, replay=False, by=principal.username,
                                               reason="an officer issued the all-clear")
    return out


# -- duty roster (services/roster.py; Cedar "officer-roster") ------------------------------------
def _roster_error(exc: roster.RosterError) -> HTTPException:
    return HTTPException(400, {"code": "roster", "reason": str(exc)})


@router.get("/roster")
def get_roster(district: str = "", start: str = "",
               _: Principal = Depends(Allowed("view_roster", district_param="district"))) -> dict:
    """The week from `start` (IST date; default today) for one district, and who is on duty now in each."""
    try:
        return roster.view(get_repo(), district or None, roster.parse_day(start) if start else None)
    except roster.RosterError as exc:
        raise _roster_error(exc) from None


class RosterShiftBody(BaseModel):
    primary: str
    backup: str | None = None
    escalation: str | None = None
    escalation_title: str = "ADM"
    note: str = ""


@router.post("/roster/{district}/{day}/{shift}")
def put_roster_shift(district: str, day: str, shift: str, body: RosterShiftBody,
                     principal: Principal = Depends(Allowed("edit_roster", district_param="district"))) -> dict:
    repo = get_repo()
    try:
        row = roster.set_shift(repo, principal.username, principal.role, district, day, shift, primary=body.primary,
                               backup=body.backup, escalation=body.escalation,
                               escalation_title=body.escalation_title, note=body.note)
    except roster.RosterError as exc:
        raise _roster_error(exc) from None
    return row.model_dump()


@router.delete("/roster/{district}/{day}/{shift}")
def delete_roster_shift(district: str, day: str, shift: str,
                        principal: Principal = Depends(Allowed("edit_roster", district_param="district"))) -> dict:
    try:
        cleared = roster.clear_shift(get_repo(), principal.username, principal.role, district, day, shift)
    except roster.RosterError as exc:
        raise _roster_error(exc) from None
    return {"cleared": cleared}


@router.post("/roster/{district}/take-over")
def take_over_duty(district: str, principal: Principal = Depends(Allowed("take_over_duty", district_param="district"))) -> dict:
    """"Taking over": the signed-in officer becomes the primary of the shift running now (audited)."""
    try:
        row = roster.take_over(get_repo(), principal.username, principal.role, district)
    except roster.RosterError as exc:
        raise _roster_error(exc) from None
    return row.model_dump()


# -- district settings (Cedar "ddma-head-district-settings"): a signed, audited in-app decision ----------
class DistrictSettingsBody(BaseModel):
    # None: back to the deployment's default (template parameter CriticalAutoSend).
    critical_auto_send: bool | None = None


@router.get("/districts/{district}/settings")
def get_district_settings(district: str,
                          _: Principal = Depends(Allowed("view_roster", district_param="district"))) -> dict:
    return district_settings.view(get_repo(), district)


@router.patch("/districts/{district}/settings")
def patch_district_settings(district: str, body: DistrictSettingsBody,
                            principal: Principal = Depends(Allowed("change_settings", district_param="district"))) -> dict:
    """Only the district's DDMA head (Cedar); the change, who made it and when go to the audit trail."""
    try:
        return district_settings.set_critical_auto_send(get_repo(), district, body.critical_auto_send, principal)
    except ValueError as exc:
        raise HTTPException(400, {"code": "settings", "reason": str(exc)}) from None


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


class RecipientRoleBody(BaseModel):
    role: str


@router.post("/villages/{village_id}/recipients/{recipient_id}/role")
def set_recipient_role(village_id: str, recipient_id: str, body: RecipientRoleBody,
                       principal: Principal = Depends(Allowed("set_recipient_role", "village", "village_id",
                                                              village_from_path=True))) -> dict:
    """Make a registered person a relay (pradhan, gauge_reader, task_force) or a villager again. Officers: any
    village; a pradhan: their own. A Telegram recipient's id is their chat id. Audited ("recipient_role_changed")."""
    from Pukaar.services import recipients

    repo = get_repo()
    if repo.get_village(village_id) is None:
        raise HTTPException(404, "Village not found")
    try:
        r = recipients.set_role(repo, village_id, recipient_id, body.role, actor=principal.username,
                                actor_role=principal.role)
    except recipients.RoleError as exc:
        raise HTTPException(400, str(exc)) from None
    except KeyError:
        raise HTTPException(404, "Recipient not found in this village") from None
    return recipients.view(r)


class RecipientCareBody(BaseModel):
    assisted: bool | None = None
    assisted_reason: str | None = None  # elderly | disabled | alone | pregnant | other; "" clears
    escalate_to: str | None = None  # a recipient id of the same village; "" clears
    gender: str | None = None  # female | male | other; "" clears. Optional, only to report coverage


@router.post("/villages/{village_id}/recipients/{recipient_id}/care")
def set_recipient_care(village_id: str, recipient_id: str, body: RecipientCareBody,
                       principal: Principal = Depends(Allowed("set_recipient_role", "village", "village_id",
                                                              village_from_path=True))) -> dict:
    """Mark a household as assisted (older, disabled, alone, pregnant) and name the neighbour or relay who checks on
    them when they do not confirm (services/assisted.py), and the optional gender. Same rule as naming relays: an
    officer, or the village's own pradhan. Audited ("recipient_care_changed")."""
    from Pukaar.services import assisted, recipients

    repo = get_repo()
    if repo.get_village(village_id) is None:
        raise HTTPException(404, "Village not found")
    try:
        r = assisted.set_care(repo, village_id, recipient_id, assisted=body.assisted, reason=body.assisted_reason,
                              escalate_to=body.escalate_to, gender=body.gender, actor=principal.username,
                              actor_role=principal.role)
    except assisted.CareError as exc:
        raise HTTPException(400, str(exc)) from None
    except KeyError:
        raise HTTPException(404, "Recipient not found in this village") from None
    return {**recipients.view(r), **assisted.view(r)}


@router.get("/care/villages")
def village_care(principal: Principal = Depends(Allowed("view_recipients"))) -> dict:
    """Each village's observers (two wanted, half women encouraged), assisted households without a named neighbour,
    and coverage against the household list: the gaps the roster page shows. Counts and first names only."""
    from Pukaar.services import assisted

    repo = get_repo()
    villages = repo.list_villages()
    if principal.role not in READS_EVERYTHING:
        villages = [v for v in villages if v.id in principal.village_ids]
    return {"villages": [{**assisted.village_care(repo, v.id), "name": v.name, "name_hi": v.name_hi,
                          "district": v.district} for v in villages],
            "min_observers": assisted.MIN_OBSERVERS, "women_share_goal": assisted.WOMEN_SHARE_GOAL}


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
