"""River-gauge ingestion over HTTPS. Public route (devices have no Cognito account); every body
is signed with a per-device HMAC key (services/gauge.py), carries a timestamp no older than five
minutes, and must come from the device registered for the village. The MQTT path
(handlers/gauge_ingest.py) shares everything after authentication through gauge.ingest()."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError

from Pukaar.core import clock
from Pukaar.core.log import get_logger, log
from Pukaar.core.secrets import get_secret
from Pukaar.services import gauge
from Pukaar.store.repo import get_repo

router = APIRouter()
_LOG = get_logger("sensors")
MAX_BODY_BYTES = 2048


class ReadingIn(gauge.ReadingFields):
    device_id: str = Field(min_length=3, max_length=64, pattern=gauge.DEVICE_ID_PATTERN)


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

    try:
        result = gauge.ingest(get_repo(), village_id, body.device_id, body, at, now=now, transport="https")
    except gauge.IngestError as exc:
        detail = exc.reason if exc.status == 404 else {"code": exc.code, "reason": exc.reason}
        raise HTTPException(exc.status, detail) from None
    return JSONResponse(result.as_dict(), status_code=202)
