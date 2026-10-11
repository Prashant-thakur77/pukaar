"""Lambda: river-gauge readings over MQTT, from the AWS IoT Core topic rule.

A gauge publishes to pukaar/gauge/<village_id>/<device_id>/reading with its own X.509
certificate. The IoT policy only lets a certificate connect as its own thing name and publish
to topics ending in /<that thing name>/reading, so the device id in the topic is authenticated:
no HMAC signature is needed on this path. The rule

    SELECT *, topic(3) AS village_id, topic(4) AS device_id FROM 'pukaar/gauge/+/+/reading'

hands this function the payload with the two topic parts added, for example

    {"at": "2026-10-11T09:30:00Z", "water_level_cm": 182.4, "battery_v": 3.98, "rssi": -67,
     "rain_mm_1h": 1.2, "village_id": "gohar", "device_id": "gauge-gohar-sim"}

The reading then goes through the same gauge.ingest() as the HTTPS route: the device must be
the village's registered gauge, at most one reading per device per minute, an audit row on a
level change, and an immediate re-evaluation at watch or above.

A reading that can never be stored (bad payload, stale timestamp, unknown village, wrong
device) is logged and returned as "rejected" without raising, so it is not retried. Anything
else (DynamoDB unavailable) raises: the asynchronous invocation then lands in the DLQ.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, ValidationError

from Pukaar.core import clock
from Pukaar.core.log import get_logger, log, metric
from Pukaar.services import gauge
from Pukaar.store.repo import Repo, get_repo

_LOG = get_logger("handler.gauge_ingest")

# Wider than the HTTPS path's five minutes: an MQTT message passes through the broker and an
# asynchronous rule action before it reaches here. Replays are still refused by the one-per-minute,
# never-earlier conditional write in repo.put_sensor_reading.
WINDOW_SECONDS = 600
NUMERIC_FIELDS = ("water_level_cm", "rain_mm_1h", "battery_v", "rssi")


class MqttReading(gauge.ReadingFields):
    model_config = ConfigDict(extra="ignore")

    village_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    device_id: str = Field(min_length=3, max_length=128, pattern=gauge.DEVICE_ID_PATTERN)


def _reject(code: str, reason: str, event: dict[str, Any]) -> dict[str, Any]:
    log(_LOG, "gauge mqtt reading rejected", 30, code=code, reason=reason[:300],
        village_id=str(event.get("village_id", ""))[:64], device_id=str(event.get("device_id", ""))[:128])
    metric("GaugeRejected", 1, Transport="mqtt", Code=code)
    return {"status": "rejected", "code": code, "reason": reason}


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def handle(event: Any, repo: Repo | None = None, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(event, dict):
        return _reject("bad_payload", "payload is not a JSON object", {})
    if not _is_number(event.get("water_level_cm")):
        return _reject("bad_payload", "water_level_cm must be a number", event)
    for name in NUMERIC_FIELDS[1:]:
        if event.get(name) is not None and not _is_number(event[name]):
            return _reject("bad_payload", f"{name} must be a number", event)
    try:
        body = MqttReading.model_validate(event)
        at = clock.parse(body.at)
    except (ValueError, ValidationError) as exc:
        return _reject("bad_payload", str(exc)[:200], event)

    now = now or clock.now()
    if abs((now - at).total_seconds()) > WINDOW_SECONDS:
        return _reject("stale", f"timestamp {body.at} is more than {WINDOW_SECONDS // 60} minutes from now", event)

    try:
        result = gauge.ingest(repo or get_repo(), body.village_id, body.device_id, body, at, now=now, transport="mqtt")
    except gauge.IngestError as exc:
        return _reject(exc.code, exc.reason, event)
    out = result.as_dict()
    log(_LOG, "gauge mqtt reading", village_id=body.village_id, device_id=body.device_id, **out)
    metric("GaugeReading", 1, Transport="mqtt")
    return out


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    return handle(event)
