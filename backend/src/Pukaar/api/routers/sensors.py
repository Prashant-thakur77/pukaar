"""River-gauge ingestion over HTTPS. Public routes (devices have no Cognito account); every body
is signed with a per-device HMAC key (services/gauge.py) and must come from the device registered
for the village. The MQTT path (handlers/gauge_ingest.py) shares everything after authentication.

  POST /sensors/{village_id}/readings  one live reading (payload v1 or v2), a timestamp no older
                                       than five minutes (replay protection)
  POST /sensors/{village_id}/backfill  {"device_id", "readings": [...]}: readings buffered while
                                       the link was down, up to gauge.BACKFILL_MAX_AGE_HOURS old,
                                       each stored once per (device, boot, seq); never alerts
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from Pukaar.core import clock
from Pukaar.core.log import get_logger, log
from Pukaar.core.secrets import get_secret
from Pukaar.services import gauge
from Pukaar.store.repo import get_repo

router = APIRouter()
_LOG = get_logger("sensors")
MAX_BODY_BYTES = 2048
MAX_BACKFILL_BYTES = 32768

DEVICE_ID = Field(min_length=3, max_length=64, pattern=gauge.DEVICE_ID_PATTERN)


class ReadingIn(gauge.ReadingFields):
    device_id: str = DEVICE_ID


class BackfillIn(BaseModel):
    device_id: str = DEVICE_ID
    readings: list[gauge.ReadingFields] = Field(min_length=1, max_length=gauge.BACKFILL_MAX_ITEMS)


async def _signed(request: Request, village_id: str, limit: int, model: type[BaseModel]) -> Any:
    raw = await request.body()
    if len(raw) > limit:
        raise HTTPException(413, "Body too large")
    try:
        body = model.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(400, f"Invalid reading: {str(exc)[:200]}") from None
    secret = get_secret("link_secret", generate_locally=True)
    if not secret:
        raise HTTPException(503, "Signing key unavailable; retry later")
    if not gauge.signature_ok(secret, body.device_id, raw, request.headers.get(gauge.SIGNATURE_HEADER, "")):
        log(_LOG, "gauge signature rejected", 30, village_id=village_id, device_id=body.device_id)
        raise HTTPException(401, {"code": "bad_signature", "reason": f"Missing or wrong {gauge.SIGNATURE_HEADER}"})
    return body


def _error(exc: gauge.IngestError) -> HTTPException:
    detail = exc.reason if exc.status == 404 else {"code": exc.code, "reason": exc.reason}
    return HTTPException(exc.status, detail)


@router.post("/sensors/{village_id}/readings", status_code=202)
async def post_reading(village_id: str, request: Request) -> JSONResponse:
    body: ReadingIn = await _signed(request, village_id, MAX_BODY_BYTES, ReadingIn)
    try:
        at = clock.parse(body.at)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid reading: {str(exc)[:200]}") from None
    now = clock.now()
    if body.buffered:  # a buffered reading is history: the backfill rules apply, never an alert
        try:
            res = gauge.ingest_backfill(get_repo(), village_id, body.device_id, [body], now=now, transport="https")
        except gauge.IngestError as exc:
            raise _error(exc) from None
        return JSONResponse(res.as_dict(), status_code=202)
    age = (now - at).total_seconds()
    if age > gauge.MAX_AGE_SECONDS or age < -gauge.MAX_SKEW_SECONDS:
        raise HTTPException(401, {"code": "stale", "reason": "Timestamp outside the five-minute window"})
    try:
        result = gauge.ingest(get_repo(), village_id, body.device_id, body, at, now=now, transport="https")
    except gauge.IngestError as exc:
        raise _error(exc) from None
    return JSONResponse(result.as_dict(), status_code=202)


@router.post("/sensors/{village_id}/backfill", status_code=202)
async def post_backfill(village_id: str, request: Request) -> JSONResponse:
    body: BackfillIn = await _signed(request, village_id, MAX_BACKFILL_BYTES, BackfillIn)
    try:
        res = gauge.ingest_backfill(get_repo(), village_id, body.device_id, body.readings, now=clock.now(),
                                    transport="https")
    except gauge.IngestError as exc:
        raise _error(exc) from None
    return JSONResponse(res.as_dict(), status_code=202)
