"""River-gauge ingestion. Public route (devices have no Cognito account); every body
is signed with a per-device HMAC key (services/gauge.py), carries a timestamp no older
than five minutes, and must come from the device registered for the village."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from Pukaar.core import clock
from Pukaar.core.ids import new_id
from Pukaar.core.log import get_logger, log
from Pukaar.core.secrets import get_secret
from Pukaar.services import gauge, risk_rules
from Pukaar.store.models import AuditRow, SensorReading
from Pukaar.store.repo import get_repo

router = APIRouter()
_LOG = get_logger("sensors")
MAX_BODY_BYTES = 2048


class ReadingIn(BaseModel):
    device_id: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    at: str = Field(max_length=40)
    water_level_cm: float = Field(ge=-200, le=5000)
    rain_mm_1h: float | None = Field(default=None, ge=0, le=500)
    battery_v: float | None = Field(default=None, ge=0, le=20)
    rssi: int | None = Field(default=None, ge=-150, le=0)
    simulated: bool = False


@router.post("/sensors/{village_id}/readings", status_code=202)
async def post_reading(village_id: str, request: Request) -> JSONResponse:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(413, "Body too large")
    try:
        body = ReadingIn.model_validate(json.loads(raw))
        at = clock.parse(body.at)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(400, f"Invalid reading: {str(exc)[:200]}") from None

    secret = get_secret("link_secret", generate_locally=True)
    if not secret:
        raise HTTPException(503, "Signing key unavailable; retry later")
    if not gauge.signature_ok(secret, body.device_id, raw, request.headers.get(gauge.SIGNATURE_HEADER, "")):
        log(_LOG, "gauge signature rejected", 30, village_id=village_id, device_id=body.device_id)
        raise HTTPException(401, {"code": "bad_signature", "reason": f"Missing or wrong {gauge.SIGNATURE_HEADER}"})

    now = clock.now()
    age = (now - at).total_seconds()
    if age > gauge.MAX_AGE_SECONDS or age < -gauge.MAX_SKEW_SECONDS:
        raise HTTPException(401, {"code": "stale", "reason": "Timestamp outside the five-minute window"})

    repo = get_repo()
    village = repo.get_village(village_id)
    if village is None:
        raise HTTPException(404, "Village not found")
    if village.gauge is None or village.gauge.device_id != body.device_id:
        raise HTTPException(403, {"code": "wrong_device", "reason": "This device is not the gauge for this village"})

    previous = repo.latest_sensor_reading(village.id, risk_rules.GAUGE_FRESH_MINUTES, now=now)
    reading = SensorReading(
        village_id=village.id, device_id=body.device_id, at=clock.iso(at), water_level_cm=body.water_level_cm,
        rain_mm_1h=body.rain_mm_1h, battery_v=body.battery_v, rssi=body.rssi,
        # A simulator labels itself; a "-sim" device id is always treated as simulated too.
        simulated=body.simulated or body.device_id.endswith("-sim"), received_at=clock.iso(now),
    )
    if not repo.put_sensor_reading(reading):
        return JSONResponse({"status": "ignored", "reason": "more than one reading per minute, or out of order"},
                            status_code=202)

    level = risk_rules.gauge_level(reading.water_level_cm, village.gauge)
    before = risk_rules.gauge_level(previous.water_level_cm, village.gauge) if previous else "normal"
    if level != before:
        try:
            repo.append_audit(AuditRow(
                at=clock.iso(now), id=new_id("aud"), actor=body.device_id, role="gauge", action="gauge_level",
                resource=f"village:{village.id}", decision="allow",
                reason=f"gauge {before} -> {level} at {reading.water_level_cm:g} cm"
                       + (" (simulated)" if reading.simulated else ""),
            ))
        except Exception as exc:  # the reading is stored; a missing audit row must not lose it
            log(_LOG, "gauge audit write failed", 40, error=str(exc)[:200])

    result = None
    if risk_rules.level_rank(level) >= risk_rules.level_rank("watch"):
        # Re-evaluate now rather than at the next 15-minute sweep, but only to raise a level.
        from Pukaar.services.decision_engine import recompute_village
        from Pukaar.services.replay import is_running
        from Pukaar.workflow.client import get_workflow

        if not is_running(repo):
            try:
                result = recompute_village(repo, village, now=now, workflow=get_workflow(), only_if_rising=True)
            except Exception as exc:  # the next sweep picks the reading up
                log(_LOG, "gauge recompute failed", 40, village_id=village.id, error=str(exc)[:200])
    return JSONResponse({"status": "accepted", "gauge_level": level, "simulated": reading.simulated,
                         "village_level": result.level if result else village.level,
                         "alert_id": result.alert_id if result else None}, status_code=202)
