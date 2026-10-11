"""River-gauge helpers: per-device keys, request signatures, ingestion, and the village view.

Readings arrive two ways and meet in `ingest()`:

- HTTPS (api/routers/sensors.py): the gauge signs the raw JSON body it POSTs to
  /sensors/{village_id}/readings with HMAC-SHA256. Its key is derived from the
  link secret, so no per-device secret has to be stored server side:

      device_key = hex(HMAC-SHA256(link_secret, "gauge:" + device_id))
      X-Pukaar-Signature = hex(HMAC-SHA256(device_key as ASCII bytes, raw body))

- MQTT over AWS IoT Core (handlers/gauge_ingest.py): the device's X.509
  certificate authenticates it, and the IoT policy lets it publish only to
  pukaar/gauge/<village>/<its own thing name>/reading.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from Pukaar.core import clock
from Pukaar.core.ids import new_id
from Pukaar.core.log import get_logger, log
from Pukaar.services import risk_rules
from Pukaar.store.models import AuditRow, SensorReading, Village
from Pukaar.store.repo import Repo

SIGNATURE_HEADER = "X-Pukaar-Signature"
MAX_AGE_SECONDS = 300  # older timestamps are rejected (replay protection)
MAX_SKEW_SECONDS = 120  # a device clock this far ahead is tolerated
SERIES_HOURS = 24
SERIES_POINTS = 96
DEVICE_ID_PATTERN = r"^[A-Za-z0-9_.-]+$"

_LOG = get_logger("gauge")


class ReadingFields(BaseModel):
    """The measured values every transport carries, with the same physical bounds."""

    at: str = Field(max_length=40)
    water_level_cm: float = Field(ge=-200, le=5000)
    rain_mm_1h: float | None = Field(default=None, ge=0, le=500)
    battery_v: float | None = Field(default=None, ge=0, le=20)
    rssi: int | None = Field(default=None, ge=-150, le=0)
    simulated: bool = False


class IngestError(Exception):
    """A reading the server will not store: HTTP status, a stable code and a reason."""

    def __init__(self, status: int, code: str, reason: str) -> None:
        super().__init__(reason)
        self.status, self.code, self.reason = status, code, reason


@dataclass
class IngestResult:
    status: Literal["accepted", "ignored"]
    gauge_level: str | None = None
    simulated: bool = False
    village_level: str | None = None
    alert_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        if self.status == "ignored":
            return {"status": "ignored", "reason": "more than one reading per minute, or out of order"}
        return {"status": "accepted", "gauge_level": self.gauge_level, "simulated": self.simulated,
                "village_level": self.village_level, "alert_id": self.alert_id}


def device_key(link_secret: str, device_id: str) -> str:
    return hmac.new(link_secret.encode(), f"gauge:{device_id}".encode(), hashlib.sha256).hexdigest()


def sign(key: str, body: bytes) -> str:
    return hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


def signature_ok(link_secret: str, device_id: str, body: bytes, signature: str) -> bool:
    expected = sign(device_key(link_secret, device_id), body)
    return hmac.compare_digest(expected, (signature or "").strip().lower())


def view(repo: Repo, v: Village) -> dict[str, Any] | None:
    """Gauge block for the village page: config, newest reading, freshness, last 24 h (thinned)."""
    if v.gauge is None:
        return None
    now = clock.now()
    series = repo.list_sensor_readings(v.id, clock.iso(now - timedelta(hours=SERIES_HOURS)))
    latest = series[-1] if series else repo.latest_sensor_reading(v.id, max_age_minutes=None)
    fresh = risk_rules.gauge_is_fresh(latest, now)
    step = max(1, -(-len(series) // SERIES_POINTS))
    thin = series[::step]
    if series and thin[-1] is not series[-1]:
        thin.append(series[-1])
    return {
        "config": v.gauge.model_dump(),
        "latest": latest.model_dump() if latest else None,
        "fresh": fresh,
        "fresh_minutes": risk_rules.GAUGE_FRESH_MINUTES,
        "level": risk_rules.gauge_level(latest.water_level_cm, v.gauge) if latest and fresh else None,
        "series": [{"at": r.at, "cm": r.water_level_cm} for r in thin],
    }


def ingest(repo: Repo, village_id: str, device_id: str, fields: ReadingFields, at: datetime, *,
           now: datetime | None = None, transport: Literal["https", "mqtt"] = "https") -> IngestResult:
    """Store one authenticated reading for a village, audit a gauge level change, and re-run the
    village's rules at once when the stage is at watch or above (only ever to raise the level).

    The caller has already authenticated the device (HMAC signature or X.509 certificate) and
    checked the timestamp window. Raises IngestError for an unknown village (404) or a device that
    is not the village's registered gauge (403).
    """
    now = now or clock.now()
    village = repo.get_village(village_id)
    if village is None:
        raise IngestError(404, "not_found", "Village not found")
    if village.gauge is None or village.gauge.device_id != device_id:
        raise IngestError(403, "wrong_device", "This device is not the gauge for this village")

    previous = repo.latest_sensor_reading(village.id, risk_rules.GAUGE_FRESH_MINUTES, now=now)
    reading = SensorReading(
        village_id=village.id, device_id=device_id, at=clock.iso(at), water_level_cm=fields.water_level_cm,
        rain_mm_1h=fields.rain_mm_1h, battery_v=fields.battery_v, rssi=fields.rssi,
        # A simulator labels itself; a "-sim" device id is always treated as simulated too.
        simulated=fields.simulated or device_id.endswith("-sim"), received_at=clock.iso(now), transport=transport,
    )
    if not repo.put_sensor_reading(reading):
        return IngestResult("ignored")

    level = risk_rules.gauge_level(reading.water_level_cm, village.gauge)
    before = risk_rules.gauge_level(previous.water_level_cm, village.gauge) if previous else "normal"
    if level != before:
        try:
            repo.append_audit(AuditRow(
                at=clock.iso(now), id=new_id("aud"), actor=device_id, role="gauge", action="gauge_level",
                resource=f"village:{village.id}", decision="allow",
                reason=f"gauge {before} -> {level} at {reading.water_level_cm:g} cm via {transport}"
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
    return IngestResult("accepted", gauge_level=level, simulated=reading.simulated,
                        village_level=result.level if result else village.level,
                        alert_id=result.alert_id if result else None)
