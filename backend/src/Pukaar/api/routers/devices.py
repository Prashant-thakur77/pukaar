"""Devices and sirens in the console (docs/CONTRACT.md, "Devices and sirens"). Cognito on every route.

Every route passes Cedar (policy/base.cedar) and every decision is on the audit trail:
  view_devices    officers (every village); pradhans (their own villages)
  test_siren      officers: silent at any time, audible only 09:00-18:00 IST; one test per 10 minutes a siren
  sound_siren     officers (a Critical needs a second, different officer within 120 s); pradhans (own village)
  stop_siren      officers; a pradhan only what they started
  manage_device   officers (settings, the SMS fallback); turning on edge autonomy needs a second officer
  pour_test       officers; pradhans (own village)
The public demo accounts (judge, judge_pradhan) see the devices and never act on one. No route returns a
key; the SIM number appears only in the SMS fallback, to an officer, audited.
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from Pukaar.api.auth import require_user
from Pukaar.core import clock
from Pukaar.policy.guard import Principal, authorize, evaluate
from Pukaar.services import sirens
from Pukaar.services.devices import registry, shadow
from Pukaar.store.models import Device, Village
from Pukaar.store.repo import Repo, get_repo

router = APIRouter()
FUNNEL_DIAMETER_MM = 200.0
POUR_WINDOW_MINUTES = 10


def _deny(action: str, reason: str, role: str) -> HTTPException:
    return HTTPException(403, {"code": "denied", "reason": reason, "action": action, "role": role})


def _allow(repo: Repo, principal: Principal, action: str, resource_type: str, resource_id: str,
           context: dict[str, Any]) -> None:
    decision = authorize(principal, action, resource_type, resource_id, context, repo=repo)
    if not decision.allowed:
        raise _deny(action, decision.reason, principal.role)


def _village(repo: Repo, village_id: str) -> Village:
    v = repo.get_village(village_id)
    if v is None:
        raise HTTPException(404, "Village not found")
    return v


def _device(repo: Repo, device_id: str) -> Device:
    d = repo.get_device(device_id)
    if d is None:
        raise HTTPException(404, "Device not found")
    return d


def _request_error(exc: sirens.RequestError) -> HTTPException:
    return HTTPException(exc.status, {"code": exc.code, "reason": exc.reason})


@router.get("/devices")
def list_devices(principal: Principal = Depends(require_user)) -> dict:
    repo = get_repo()
    # An officer is asked once; a pradhan once for each of their own villages (no policy matches an empty one).
    villages = [""] if principal.role == "officer" else ([v for v in principal.village_ids if v] or [""])
    allowed = [v for v in villages
               if authorize(principal, "view_devices", "app", "pukaar", {"village_id": v}, repo=repo).allowed]
    if not allowed:
        raise _deny("view_devices", "You can only see the devices of your own villages.", principal.role)
    now = clock.now()
    devices = repo.list_devices()
    if principal.role != "officer":
        devices = [d for d in devices if d.village_id in allowed]
    return {"devices": [registry.view(d, now) for d in devices]}


def _can(principal: Principal, v: Village, devices: list[Device]) -> dict[str, bool]:
    """What the console may offer this person (Cedar's answer; the action itself is checked again)."""
    first = next((d for d in devices if d.kind == "siren"), None)
    hour = sirens.hour_ist()
    mine = any(sirens._starter(d) == principal.username for d in devices)
    test = first is not None and evaluate(principal, "test_siren", "device", first.device_id,
                                          {"kind": "silent", "hour_ist": hour, "village_id": v.id,
                                           "device_simulated": first.simulated}).allowed
    return {"test_siren": test,
            "sound_siren": first is not None and evaluate(principal, "sound_siren", "village", v.id,
                                                          {"village_id": v.id, "level": "warning",
                                                           "pattern": "W1"}).allowed,
            "stop_siren": first is not None and evaluate(principal, "stop_siren", "village", v.id,
                                                         {"village_id": v.id, "started_by_self": mine}).allowed}


@router.get("/villages/{village_id}/devices")
def village_devices(village_id: str, principal: Principal = Depends(require_user)) -> dict:
    repo = get_repo()
    v = _village(repo, village_id)
    _allow(repo, principal, "view_devices", "village", v.id, {"village_id": v.id})
    now = clock.now()
    devices = repo.list_devices(v.id)
    requests = [r.model_dump() | {"request_id": r.id} for r in repo.list_siren_requests(v.id)
                if r.status == "open" and clock.parse(r.expires_at) > now]
    return {"village_id": v.id, "devices": [registry.view(d, now) for d in devices], "can": _can(principal, v, devices),
            "requests": requests}


@router.get("/devices/{device_id}/events")
def device_events(device_id: str, since: str = "", type: str = "", limit: int = 100,
                  principal: Principal = Depends(require_user)) -> dict:
    repo = get_repo()
    d = _device(repo, device_id)
    _allow(repo, principal, "view_devices", "device", d.device_id, {"village_id": d.village_id})
    events = repo.list_device_events(d.device_id, since or None, limit=max(1, min(limit, 500)))
    if type:
        events = [e for e in events if e.get("type") == type]
    return {"device_id": d.device_id, "events": events}


class TestBody(BaseModel):
    kind: Literal["silent", "audible"] = "silent"
    reason: str = Field(default="", max_length=200)


@router.post("/devices/{device_id}/test")
def test_device(device_id: str, body: TestBody, principal: Principal = Depends(require_user)) -> dict:
    repo = get_repo()
    d = _device(repo, device_id)
    if d.kind != "siren":
        raise HTTPException(400, {"code": "not_a_siren", "reason": "Only a siren can be tested from here"})
    try:
        cmd = sirens.test(repo, d, body.kind, principal, reason=body.reason)
    except PermissionError as exc:
        raise _deny("test_siren", str(exc), principal.role) from None
    except sirens.RequestError as exc:
        raise _request_error(exc) from None
    return {"cmd_id": cmd.id, "pattern": cmd.pattern, "kind": body.kind}


class SoundBody(BaseModel):
    level: Literal["warning", "critical"]
    reason: str = Field(default="", max_length=200)


@router.post("/villages/{village_id}/sirens/sound")
def sound(village_id: str, body: SoundBody, principal: Principal = Depends(require_user)):
    repo = get_repo()
    v = _village(repo, village_id)
    if body.level == "critical" and principal.role == "officer":
        # The two-person rule: is this officer allowed to start one at all? (a judge is not)
        probe = evaluate(principal, "sound_siren", "village", v.id,
                         {"village_id": v.id, "level": "critical", "second_officer_distinct": True, "pattern": "C1"})
        if not probe.allowed:
            _allow(repo, principal, "sound_siren", "village", v.id,
                   {"village_id": v.id, "level": "critical", "pattern": "C1"})  # the audited deny
        req = sirens.request_critical(repo, v, principal, body.reason)
        return JSONResponse({"request_id": req.id, "needs_second_officer": True, "expires_at": req.expires_at},
                            status_code=202)
    try:
        res = sirens.manual_sound(repo, v, body.level, principal, reason=body.reason)
    except PermissionError as exc:
        raise _deny("sound_siren", str(exc), principal.role) from None
    if res.reason == "rate_limited":
        raise HTTPException(429, {"code": "rate_limited", "reason": "Too many siren commands for this village this hour"})
    return {"commanded": res.commanded, "cmd_ids": res.cmd_ids, "pattern": res.pattern}


@router.post("/siren-requests/{request_id}/confirm")
def confirm(request_id: str, principal: Principal = Depends(require_user)) -> dict:
    repo = get_repo()
    req = repo.get_siren_request(request_id)
    if req is None:
        raise HTTPException(404, "Siren request not found")
    probe = evaluate(principal, "sound_siren", "village", req.village_id,
                     {"village_id": req.village_id, "level": "critical", "second_officer_distinct": True,
                      "pattern": "C1"})
    if not probe.allowed or principal.role != "officer":
        _allow(repo, principal, "sound_siren", "village", req.village_id,
               {"village_id": req.village_id, "level": "critical", "pattern": "C1"})
        raise _deny("sound_siren", "Only a second district officer can confirm", principal.role)
    try:
        res = sirens.confirm_request(repo, request_id, principal)
    except sirens.RequestError as exc:
        raise _request_error(exc) from None
    except PermissionError as exc:
        raise _deny("sound_siren", str(exc), principal.role) from None
    return {"commanded": res.commanded, "cmd_ids": res.cmd_ids, "pattern": res.pattern}


class StopBody(BaseModel):
    reason: str = Field(default="", max_length=200)
    cmd_id: str | None = Field(default=None, max_length=64)


@router.post("/villages/{village_id}/sirens/stop")
def stop(village_id: str, body: StopBody, principal: Principal = Depends(require_user)) -> dict:
    repo = get_repo()
    v = _village(repo, village_id)
    try:
        return sirens.stop(repo, v, principal, reason=body.reason, cmd_id=body.cmd_id)
    except PermissionError as exc:
        raise _deny("stop_siren", str(exc), principal.role) from None


@router.get("/alerts/{alert_id}/sirens")
def alert_sirens(alert_id: str, principal: Principal = Depends(require_user)) -> dict:
    repo = get_repo()
    a = repo.get_alert(alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    _allow(repo, principal, "view_console", "alert", a.id, {"village_id": a.village_id, "replay": a.replay,
                                                            "level": a.level})
    return sirens.tier(repo, a)


class SmsBody(BaseModel):
    cmd_id: str = Field(min_length=3, max_length=64)


@router.post("/devices/{device_id}/sms-fallback")
def sms_fallback(device_id: str, body: SmsBody, principal: Principal = Depends(require_user)) -> dict:
    repo = get_repo()
    d = _device(repo, device_id)
    if principal.role != "officer":
        raise _deny("manage_device", "Only a district officer can send a siren command by SMS", principal.role)
    _allow(repo, principal, "manage_device", "device", d.device_id, {"village_id": d.village_id, "change": "sms_fallback"})
    try:
        return sirens.sms_fallback(repo, d, body.cmd_id, principal)
    except sirens.RequestError as exc:
        raise _request_error(exc) from None


class ConfigBody(BaseModel):
    installed: bool | None = None
    coverage_m: float | None = Field(default=None, ge=0, le=5000)
    voice_slot: int | None = Field(default=None, ge=0, le=1)
    sim_number: str | None = Field(default=None, pattern=r"^\+[1-9]\d{7,14}$")
    amp_a_ref: float | None = Field(default=None, gt=0, le=20)
    siren_a_ref: float | None = Field(default=None, gt=0, le=20)
    spl_rise_min_db: float | None = Field(default=None, ge=3, le=60)
    test_schedule: str | None = Field(default=None, max_length=24)
    autonomy_enabled: bool | None = None
    reason: str = Field(default="", max_length=200)


@router.patch("/devices/{device_id}/config")
def set_config(device_id: str, body: ConfigBody, principal: Principal = Depends(require_user)) -> dict:
    repo = get_repo()
    d = _device(repo, device_id)
    change = "autonomy_enable" if body.autonomy_enabled else "settings"
    _allow(repo, principal, "manage_device", "device", d.device_id, {"village_id": d.village_id, "change": change})
    fields = body.model_dump(exclude_none=True, exclude={"reason", "autonomy_enabled"})
    if body.autonomy_enabled is False:
        fields["autonomy"] = {**d.autonomy, "enabled": False}
    if not fields:
        raise HTTPException(400, {"code": "empty", "reason": "Nothing to change"})
    d = repo.update_device(d.village_id, d.device_id, **fields)
    if d.kind == "siren":  # the device's config shadow (never a key, never a number)
        try:
            shadow.get_client(repo).update_desired(d.device_id, "config", {
                "voice_slot": d.voice_slot, "amp_a_ref": d.amp_a_ref, "siren_a_ref": d.siren_a_ref,
                "spl_rise_min_db": d.spl_rise_min_db, "tests": {"silent": d.test_schedule}, "autonomy": d.autonomy})
        except Exception:
            pass  # the registry holds it; the next change writes the shadow again
    sirens._audit(repo, principal.username, principal.role, "manage_device", f"device:{d.device_id}", "allow",
                  f"changed {', '.join(sorted(fields))}: {body.reason or 'no reason given'}")
    return {"device": registry.view(d)}


class PourBody(BaseModel):
    ml: float = Field(gt=0, le=5000)


@router.post("/devices/{device_id}/pour-test")
def pour_test(device_id: str, body: PourBody, principal: Principal = Depends(require_user)) -> dict:
    """A measured cup into the funnel during a drill: 200 ml into a 200 mm funnel is 6.37 mm (32 tips at 0.2 mm)."""
    repo = get_repo()
    d = _device(repo, device_id)
    if d.kind not in {"rain", "gauge"}:
        raise HTTPException(400, {"code": "no_bucket", "reason": "Only a gauge or a rain node has a bucket"})
    _allow(repo, principal, "pour_test", "device", d.device_id, {"village_id": d.village_id})
    v = _village(repo, d.village_id)
    per_tip = (v.gauge.rain.mm_per_tip if v.gauge and v.gauge.rain else 0.2)
    mm = body.ml * 1000 / (math.pi * (FUNNEL_DIAMETER_MM / 2) ** 2)
    until = clock.iso(clock.now() + timedelta(minutes=POUR_WINDOW_MINUTES))
    repo.update_device(d.village_id, d.device_id, pour_test_until=until)
    sirens._audit(repo, principal.username, principal.role, "pour_test", f"device:{d.device_id}", "allow",
                  f"{body.ml:g} ml: expect {mm:.2f} mm ({mm / per_tip:.0f} tips) by {until}")
    return {"window_until": until, "expected_mm": round(mm, 2), "expected_tips": round(mm / per_tip)}
