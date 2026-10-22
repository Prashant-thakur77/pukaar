"""Lambda: river-gauge readings over MQTT, from the AWS IoT Core topic rule.

A gauge publishes with its own X.509 certificate to

    pukaar/gauge/<village_id>/<device_id>/reading    one live reading (payload v1 or v2)
    pukaar/gauge/<village_id>/<device_id>/backfill   {"readings": [...]} buffered while offline

The IoT policy only lets a certificate connect as its own thing name and publish to those two
topics ending in its own name, so the device id in the topic is authenticated: no HMAC signature
is needed on this path. The rule

    SELECT *, topic(3) AS village_id, topic(4) AS device_id, topic(5) AS topic_kind
    FROM 'pukaar/gauge/+/+/+' WHERE topic(5) = 'reading' OR topic(5) = 'backfill'

hands this function the payload with the topic parts added, for example

    {"at": "2026-10-11T09:30:00Z", "water_level_cm": 182.4, "battery_v": 3.98, "rssi": -67,
     "village_id": "gohar", "device_id": "gauge-gohar-sim", "topic_kind": "reading"}

A live reading goes through the same gauge.ingest() as the HTTPS route: the device must be the
village's registered gauge, at most one reading per device per minute, a timestamp within
WINDOW_SECONDS (replay protection), quality and the 2-of-3 confirmation, an audit row on a level
change, and an immediate re-evaluation at watch or above. A backfill message goes to
gauge.ingest_backfill(): older timestamps are fine (up to gauge.BACKFILL_MAX_AGE_HOURS), each
reading is stored once per (device, boot, seq), and nothing is ever re-evaluated or alerted.

A message that can never be stored (bad payload, stale timestamp, unknown village, wrong device)
is logged and returned as "rejected" without raising, so it is not retried. Anything else
(DynamoDB unavailable) raises: the asynchronous invocation then lands in the DLQ.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from Pukaar.core import clock
from Pukaar.core.log import get_logger, log, metric
from Pukaar.services import gauge
from Pukaar.store.repo import Repo, get_repo

_LOG = get_logger("handler.gauge_ingest")

# Wider than the HTTPS path's five minutes: an MQTT message passes through the broker and an
# asynchronous rule action before it reaches here. Replays are still refused by the one-per-minute,
# never-earlier conditional write in repo.put_sensor_reading. Backfill has its own window.
WINDOW_SECONDS = 600
NUMERIC_FIELDS = ("water_level_cm", "distance_mm", "rain_mm_1h", "battery_v", "rssi", "seq", "boot", "samples_ok",
                  "samples_n", "iqr_mm", "quality", "err", "temp_c", "battery_mv", "solar_mv", "rain_tips_total",
                  "rain_tips_window", "rain_mm_per_tip", "rain_max_tips_1min", "rain_min_tip_ms", "rain_bounce",
                  "rain_err")
TOPIC_PART = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class TopicIds(BaseModel):
    """The two topic parts the rule adds; the IoT policy pins the device id to the certificate."""

    model_config = ConfigDict(extra="ignore")

    village_id: str = TOPIC_PART
    device_id: str = Field(min_length=3, max_length=128, pattern=gauge.DEVICE_ID_PATTERN)


class MqttReading(gauge.ReadingFields, TopicIds):
    model_config = ConfigDict(extra="ignore")


def _reject(code: str, reason: str, event: dict[str, Any]) -> dict[str, Any]:
    log(_LOG, "gauge mqtt reading rejected", 30, code=code, reason=reason[:300],
        village_id=str(event.get("village_id", ""))[:64], device_id=str(event.get("device_id", ""))[:128])
    metric("GaugeRejected", 1, Transport="mqtt", Code=code)
    return {"status": "rejected", "code": code, "reason": reason}


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def number_problem(item: Any) -> str | None:
    """JSON numbers only: pydantic would quietly turn "80" or true into a number."""
    if not isinstance(item, dict):
        return "payload is not a JSON object"
    if not (_is_number(item.get("water_level_cm")) or _is_number(item.get("distance_mm"))):
        return "water_level_cm (or distance_mm) must be a number"
    for name in NUMERIC_FIELDS:
        if item.get(name) is not None and not _is_number(item[name]):
            return f"{name} must be a number"
    return None


def _backfill(event: dict[str, Any], repo: Repo | None, now: datetime) -> dict[str, Any]:
    items = event.get("readings")
    if not isinstance(items, list) or not items:
        return _reject("bad_payload", "backfill needs a non-empty readings list", event)
    if len(items) > gauge.BACKFILL_MAX_ITEMS:
        return _reject("too_many", f"at most {gauge.BACKFILL_MAX_ITEMS} readings per backfill message", event)
    try:
        ids = TopicIds.model_validate(event)
    except ValidationError as exc:
        return _reject("bad_payload", str(exc)[:200], event)
    fields, rejected = [], []
    for item in items:
        problem = number_problem(item)
        try:
            if problem:
                raise ValueError(problem)
            fields.append(gauge.ReadingFields.model_validate({**item, "buffered": True}))
        except (ValueError, ValidationError) as exc:
            seq = item.get("seq") if isinstance(item, dict) else None
            rejected.append({"seq": seq, "code": "bad_payload", "reason": str(exc)[:200]})
    try:
        result = gauge.ingest_backfill(repo or get_repo(), ids.village_id, ids.device_id, fields, now=now,
                                       transport="mqtt")
    except gauge.IngestError as exc:
        return _reject(exc.code, exc.reason, event)
    result.rejected = rejected + result.rejected
    out = result.as_dict()
    log(_LOG, "gauge mqtt backfill", village_id=ids.village_id, device_id=ids.device_id,
        stored=result.stored, duplicate=result.duplicate, rejected=len(result.rejected))
    return out


def handle(event: Any, repo: Repo | None = None, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(event, dict):
        return _reject("bad_payload", "payload is not a JSON object", {})
    now = now or clock.now()
    # One function for every device (infra/template.yaml): sirens, boxes, relays, presence and the siren
    # shadow go to handlers/device_ingest.py; a registered rain-only node's readings to observed rain.
    from Pukaar.handlers import device_ingest

    if device_ingest.is_device_message(event):
        return device_ingest.handle(event, repo, now)
    if str(event.get("device_id", "")).startswith("rain-"):
        repo = repo or get_repo()
        node = device_ingest.is_rain_node(repo, event)
        if node is None:
            return _reject("wrong_device", "not a registered rain node of this village", event)
        return device_ingest.rain_node(repo, node, event, now)
    kind = event.get("topic_kind", "reading")
    if kind == "backfill":
        return _backfill(event, repo, now)
    if kind != "reading":
        return _reject("bad_topic", "topic must end in /reading or /backfill", event)
    problem = number_problem(event)
    if problem:
        return _reject("bad_payload", problem, event)
    try:
        body = MqttReading.model_validate(event)
        at = clock.parse(body.at)
    except (ValueError, ValidationError) as exc:
        return _reject("bad_payload", str(exc)[:200], event)

    if body.buffered:  # a buffered reading on the live topic is history: the backfill rules apply
        return _backfill({**event, "readings": [{k: v for k, v in event.items()
                                                  if k not in ("village_id", "device_id", "topic_kind")}]},
                         repo, now)
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
