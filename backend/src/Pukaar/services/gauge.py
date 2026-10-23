"""River-gauge helpers: per-device keys, request signatures, ingestion, quality, health, and the village view.

Readings arrive two ways and meet in `ingest()` (live) or `ingest_backfill()` (buffered):

- HTTPS (api/routers/sensors.py): the gauge signs the raw JSON body it POSTs to
  /sensors/{village_id}/readings (or /backfill) with HMAC-SHA256. Its key is derived from the
  link secret, so no per-device secret has to be stored server side:

      device_key = hex(HMAC-SHA256(link_secret, "gauge:" + device_id))
      X-Pukaar-Signature = hex(HMAC-SHA256(device_key as ASCII bytes, raw body))

- MQTT over AWS IoT Core (handlers/gauge_ingest.py): the device's X.509 certificate
  authenticates it, and the IoT policy lets it publish only to
  pukaar/gauge/<village>/<its own thing name>/reading and .../backfill.

The false-alarm guard (every threshold is a GaugeConfig field, so it can be set per gauge):

- quality: each reading is classified and kept, whatever its quality, for officers:
    out_of_range  the distance (raw, or implied by the stage and the datum) is at or inside the
                  sensor's blind zone, or at or beyond its maximum range: a blocked face, a bird,
                  a lost echo (the blind-zone guard follows tepmachcha, MIT, DAI Maker Lab);
    spike         a change faster than max_rise_cm_per_min against the last good reading (an
                  echo off debris; no river moves that fast). Two readings in a row that agree
                  with each other are a real step: the second one is good;
    suspect       the device said so: its error bits, too few good samples, a wide spread
                  (iqr_mm) or a low self-reported quality;
    good          everything else. Only good readings count toward a level.
- confirmation: a stage counts only when 2 of the last 3 good live readings (all fresh) are at or
  above it (`confirmed_level`). One reading at warning changes nothing on its own.
- rate of rise: at least rise_cm over rise_minutes, across 3 or more good live readings, with no
  step down by more than SUSTAIN_TOLERANCE_CM, is "rising fast" and raises the gauge level by
  one step (`effective_level`). It is named in the decision trace.

Payload v2 adds the raw distance and the device's own diagnostics. The datum (the sensor face's
height above the gauge zero, GaugeConfig.mount_height_cm) lives on the server: when a reading
carries distance_mm and the gauge has a datum, the server computes the stage itself.

Speed of sound. An ultrasonic sensor times an echo; the firmware turns time into distance with
the speed of sound at 20 C (343.2 m/s). Sound travels faster in warm air, about 0.17 % per
degree, so at 40 C a 3 m distance reads about 10 cm short. When a v2 reading from an ultrasonic
gauge carries temp_c, the server corrects the distance:

    c(T) = 331.3 * sqrt(1 + T / 273.15) m/s,   d_true = d_reported * c(T) / c(20)

temp_c is the enclosure's air temperature, a proxy for the air along the beam (the beam in shade
under a deck is usually cooler than a box in the sun, so the correction may slightly over-correct
at midday). A radar sensor (DFRobot SEN0676) needs no correction and gets none.

Backfill. A gauge that lost its link keeps readings in a ring buffer and sends them later to
.../backfill. They are stored (idempotent on device, boot and seq) and shown, and they NEVER
trigger anything: no re-evaluation, no audit of a level change, never counted by the rules
(risk_rules.gauge_counted_level), and never the "latest" reading the sweep reads.
"""

from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from Pukaar.core import clock
from Pukaar.core.ids import new_id
from Pukaar.core.log import get_logger, log, metric
from Pukaar.services import risk_rules
from Pukaar.store.models import (
    LEVELS,
    AuditRow,
    GaugeConfig,
    SensorReading,
    Village,
    level_rank,
)
from Pukaar.store.repo import Repo

SIGNATURE_HEADER = "X-Pukaar-Signature"
MAX_AGE_SECONDS = 300  # older live timestamps are rejected (replay protection); backfill has its own window
MAX_SKEW_SECONDS = 120  # a device clock this far ahead is tolerated
SERIES_HOURS = 24
SERIES_POINTS = 96
DEVICE_ID_PATTERN = r"^[A-Za-z0-9_.-]+$"

# False-alarm guard
CONFIRM_NEEDED = 2  # readings at or above a stage ...
CONFIRM_WINDOW = 3  # ... among the last this many good live readings
SUSTAIN_TOLERANCE_CM = 5.0  # a "sustained" rise may dip this much between readings
RISE_MIN_READINGS = 3
MIN_SAMPLE_SHARE = 0.5  # samples_ok / samples_n under this is suspect
# A spread of the burst wider than this is suspect. Generous on purpose: a flood surface is rough,
# and a guard that hides a real flood is worse than the false alarm it prevents.
MAX_IQR_MM = 150.0
MIN_DEVICE_QUALITY = 50  # the device's own 0-100 score under this is suspect

# Backfill
BACKFILL_MAX_AGE_HOURS = 72  # the device buffer holds about three days; readings live 14 days
BACKFILL_MAX_ITEMS = 60

# Health
SILENT_MINUTES = 30
BAD_SHARE_UNHEALTHY = 0.5
BAD_SHARE_MIN_READINGS = 6

# Device error bits (payload v2 `err`), as the reference firmware sets them (docs/hardware/README.md).
ERR_BITS: dict[int, str] = {
    1: "no_echo",            # no echo / no Modbus reply on any sample
    2: "few_samples",        # under half the burst survived rejection
    4: "high_spread",        # the burst's IQR above the firmware limit
    8: "clock_unsynced",     # no NTP or network time; `at` is the RTC's estimate
    16: "low_voltage",       # battery under the firmware's warning level
    32: "buffer_overflow",   # the ring buffer dropped its oldest readings
    64: "watchdog_reset",    # the last reset was the watchdog or a brownout
    128: "sensor_range",     # the sensor itself reported out of range
}
BAD_ERR_MASK = 1 | 2 | 4 | 128  # these make a reading suspect; the others are informational

SOUND_C_AT_20 = 331.3 * math.sqrt(1 + 20 / 273.15)

_LOG = get_logger("gauge")


class ReadingFields(BaseModel):
    """What every transport carries, v1 and v2, with the same physical bounds.

    v1: at, water_level_cm, rain_mm_1h?, battery_v?, rssi?, simulated?
    v2 adds the raw distance and diagnostics; water_level_cm becomes optional when distance_mm
    is sent and the gauge has a datum on the server.
    """

    at: str = Field(max_length=40)
    water_level_cm: float | None = Field(default=None, ge=-200, le=5000)
    rain_mm_1h: float | None = Field(default=None, ge=0, le=500)
    battery_v: float | None = Field(default=None, ge=0, le=20)
    rssi: int | None = Field(default=None, ge=-150, le=0)
    simulated: bool = False
    # payload v2 (v3 adds the tipping bucket, below)
    v: int | None = Field(default=None, ge=1, le=3)
    seq: int | None = Field(default=None, ge=0, le=4_294_967_295)
    boot: int | None = Field(default=None, ge=0, le=4_294_967_295)
    distance_mm: float | None = Field(default=None, ge=0, le=60_000)
    samples_ok: int | None = Field(default=None, ge=0, le=64)
    samples_n: int | None = Field(default=None, ge=0, le=64)
    iqr_mm: float | None = Field(default=None, ge=0, le=60_000)
    quality: int | None = Field(default=None, ge=0, le=100)
    err: int | None = Field(default=None, ge=0, le=65_535)
    temp_c: float | None = Field(default=None, ge=-50, le=90)
    battery_mv: float | None = Field(default=None, ge=0, le=20_000)
    solar_mv: float | None = Field(default=None, ge=0, le=30_000)
    fw: str | None = Field(default=None, max_length=32, pattern=r"^[A-Za-z0-9_.+-]+$")
    reset_cause: str | None = Field(default=None, max_length=24, pattern=r"^[A-Za-z0-9_]+$")
    buffered: bool = False
    # payload v3: the tipping bucket (gauge v3 and rain nodes; services/rain_obs.py)
    rain_tips_total: int | None = Field(default=None, ge=0, le=4_294_967_295)
    rain_tips_window: int | None = Field(default=None, ge=0, le=100_000)
    rain_mm_per_tip: float | None = Field(default=None, gt=0, le=2)
    rain_max_tips_1min: int | None = Field(default=None, ge=0, le=10_000)
    rain_min_tip_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    rain_bounce: int | None = Field(default=None, ge=0, le=100_000)
    rain_err: int | None = Field(default=None, ge=0, le=65_535)

    @model_validator(mode="after")
    def _one_measurement(self) -> ReadingFields:
        if self.water_level_cm is None and self.distance_mm is None:
            raise ValueError("send water_level_cm, or distance_mm (payload v2)")
        if self.samples_ok is not None and self.samples_n is not None and self.samples_ok > self.samples_n:
            raise ValueError("samples_ok is more than samples_n")
        return self

    @property
    def schema_version(self) -> int:
        v2 = ("seq", "boot", "distance_mm", "samples_ok", "samples_n", "iqr_mm", "quality", "err", "temp_c",
              "battery_mv", "solar_mv", "fw", "reset_cause")
        if self.v:
            return self.v
        if self.rain_tips_total is not None or self.rain_tips_window is not None:
            return 3
        return 2 if any(getattr(self, k) is not None for k in v2) else 1


class IngestError(Exception):
    """A reading the server will not store: HTTP status, a stable code and a reason."""

    def __init__(self, status: int, code: str, reason: str) -> None:
        super().__init__(reason)
        self.status, self.code, self.reason = status, code, reason


@dataclass
class IngestResult:
    status: Literal["accepted", "ignored"]
    gauge_level: str | None = None  # this reading's own stage band
    rain_level: str | None = None  # observed rain at this reading, as evaluated (services/rain_obs.py)
    simulated: bool = False
    village_level: str | None = None
    alert_id: str | None = None
    quality: str | None = None
    confirmed_level: str | None = None
    effective_level: str | None = None
    rising_fast: bool = False
    kind: str = "live"

    def as_dict(self) -> dict[str, Any]:
        if self.status == "ignored":
            return {"status": "ignored", "reason": "more than one reading per minute, out of order, or already stored"}
        return {"status": "accepted", "kind": self.kind, "gauge_level": self.gauge_level, "rain_level": self.rain_level,
                "simulated": self.simulated,
                "quality": self.quality, "confirmed_level": self.confirmed_level,
                "effective_level": self.effective_level, "rising_fast": self.rising_fast,
                "village_level": self.village_level, "alert_id": self.alert_id}


@dataclass
class BackfillResult:
    stored: int = 0
    duplicate: int = 0
    rejected: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"status": "accepted", "kind": "backfill", "stored": self.stored, "duplicate": self.duplicate,
                "rejected": self.rejected, "alerts": "never: backfilled readings are history, not triggers"}


def device_key(link_secret: str, device_id: str) -> str:
    return hmac.new(link_secret.encode(), f"gauge:{device_id}".encode(), hashlib.sha256).hexdigest()


def sign(key: str, body: bytes) -> str:
    return hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


def signature_ok(link_secret: str, device_id: str, body: bytes, signature: str) -> bool:
    expected = sign(device_key(link_secret, device_id), body)
    return hmac.compare_digest(expected, (signature or "").strip().lower())


# -- measurement ----------------------------------------------------------
def speed_of_sound(temp_c: float) -> float:
    """m/s in dry air (the usual linearised-free form; humidity adds well under 0.5 %)."""
    return 331.3 * math.sqrt(1 + temp_c / 273.15)


def corrected_distance_mm(distance_mm: float, temp_c: float | None, sensor: str) -> float:
    if sensor != "ultrasonic" or temp_c is None:
        return distance_mm
    return distance_mm * speed_of_sound(temp_c) / SOUND_C_AT_20


def stage(fields: ReadingFields, g: GaugeConfig) -> tuple[float, float | None]:
    """(stage cm, distance mm used or implied, or None without a datum). The server's datum wins
    over the device's own arithmetic whenever a raw distance is sent."""
    if fields.distance_mm is not None and g.mount_height_cm is not None:
        d = corrected_distance_mm(fields.distance_mm, fields.temp_c, g.sensor)
        return round(g.mount_height_cm - d / 10.0, 1), d
    if fields.water_level_cm is None:
        raise IngestError(400, "no_datum", "distance_mm needs the gauge's mount height on the server; "
                                           "send water_level_cm as well until it is set")
    implied = (g.mount_height_cm - fields.water_level_cm) * 10.0 if g.mount_height_cm is not None else None
    return float(fields.water_level_cm), implied


def err_names(err: int | None) -> list[str]:
    return [name for bit, name in ERR_BITS.items() if err and err & bit]


def device_quality_reasons(fields: ReadingFields) -> list[str]:
    reasons = [f"err:{n}" for n in err_names((fields.err or 0) & BAD_ERR_MASK)]
    if fields.samples_n and fields.samples_ok is not None and fields.samples_ok / fields.samples_n < MIN_SAMPLE_SHARE:
        reasons.append(f"samples:{fields.samples_ok}/{fields.samples_n}")
    if fields.iqr_mm is not None and fields.iqr_mm > MAX_IQR_MM:
        reasons.append(f"iqr:{fields.iqr_mm:g}mm")
    if fields.quality is not None and fields.quality < MIN_DEVICE_QUALITY:
        reasons.append(f"device_quality:{fields.quality}")
    return reasons


def out_of_range(distance_mm: float | None, g: GaugeConfig) -> str | None:
    if distance_mm is None:
        return None
    if distance_mm <= g.blind_zone_mm:
        return f"blind_zone:{distance_mm:.0f}<={g.blind_zone_mm:g}mm"
    if distance_mm >= g.max_range_mm:
        return f"max_range:{distance_mm:.0f}>={g.max_range_mm:g}mm"
    return None


def _minutes(a: str, b: str) -> float:
    return (clock.parse(b) - clock.parse(a)).total_seconds() / 60


def _rate(a: SensorReading, b: SensorReading) -> float:
    """cm per minute between two readings (at least a minute apart, as the server stores them)."""
    return abs(b.water_level_cm - a.water_level_cm) / max(1.0, _minutes(a.at, b.at))


def is_spike(reading: SensorReading, history: list[SensorReading], g: GaugeConfig) -> bool:
    """history: the same device's earlier readings, oldest first. A change faster than the gauge's
    physical limit against the last good reading is a spike, unless the reading just before was
    flagged a spike and this one agrees with it (two in a row: a real step, not an echo)."""
    good = [r for r in history if r.quality == "good"]
    if not good or _rate(good[-1], reading) <= g.max_rise_cm_per_min:
        return False
    prev = history[-1]
    return not (prev is not good[-1] and prev.quality == "spike" and _rate(prev, reading) <= g.max_rise_cm_per_min)


def confirmed(good_live: list[SensorReading], g: GaugeConfig) -> str:
    """The highest stage that CONFIRM_NEEDED of the last CONFIRM_WINDOW good live readings reach."""
    window = [risk_rules.gauge_level(r.water_level_cm, g) for r in good_live[-CONFIRM_WINDOW:]]
    for lvl in reversed(LEVELS[1:]):
        if sum(1 for w in window if level_rank(w) >= level_rank(lvl)) >= CONFIRM_NEEDED:
            return lvl
    return "normal"


def rise(good_live: list[SensorReading], now_at: str, g: GaugeConfig) -> float | None:
    """The rise (cm) when the river is rising fast: at least g.rise_cm across RISE_MIN_READINGS or
    more good readings in the last g.rise_minutes, with no step down of more than
    SUSTAIN_TOLERANCE_CM and the newest reading near the top. None otherwise."""
    pts = [r for r in good_live if 0 <= _minutes(r.at, now_at) <= g.rise_minutes]
    if len(pts) < RISE_MIN_READINGS:
        return None
    if any(b.water_level_cm < a.water_level_cm - SUSTAIN_TOLERANCE_CM for a, b in pairwise(pts)):
        return None
    total = pts[-1].water_level_cm - pts[0].water_level_cm
    top = max(r.water_level_cm for r in pts)
    if total >= g.rise_cm and pts[-1].water_level_cm >= top - SUSTAIN_TOLERANCE_CM:
        return round(total, 1)
    return None


def _up(level: str) -> str:
    return LEVELS[min(level_rank(level) + 1, len(LEVELS) - 1)]


def _history(repo: Repo, village_id: str, device_id: str, at: datetime, g: GaugeConfig) -> list[SensorReading]:
    """This device's live readings before `at`, inside the confirmation and rate-of-rise windows."""
    minutes = max(risk_rules.GAUGE_FRESH_MINUTES, g.rise_minutes)
    rows = repo.list_sensor_readings(village_id, clock.iso(at - timedelta(minutes=minutes)), limit=500)
    return sorted((r for r in rows if r.device_id == device_id and r.origin == "live" and clock.parse(r.at) < at),
                  key=lambda r: r.at)


def _reading(village: Village, device_id: str, fields: ReadingFields, at: datetime, now: datetime,
             transport: str, kind: str) -> SensorReading:
    g = village.gauge
    assert g is not None
    cm, distance = stage(fields, g)
    battery_v = fields.battery_v if fields.battery_v is not None else (
        round(fields.battery_mv / 1000, 3) if fields.battery_mv is not None else None)
    r = SensorReading(
        village_id=village.id, device_id=device_id, at=clock.iso(at), water_level_cm=cm,
        rain_mm_1h=fields.rain_mm_1h, battery_v=battery_v, rssi=fields.rssi,
        # A simulator labels itself; a "-sim" device id is always treated as simulated too.
        simulated=fields.simulated or device_id.endswith("-sim"), received_at=clock.iso(now), transport=transport,
        origin=kind, schema_version=fields.schema_version, seq=fields.seq, boot=fields.boot,
        distance_mm=fields.distance_mm, samples_ok=fields.samples_ok, samples_n=fields.samples_n,
        iqr_mm=fields.iqr_mm, device_quality=fields.quality, err=fields.err, temp_c=fields.temp_c,
        solar_mv=fields.solar_mv, fw=fields.fw, reset_cause=fields.reset_cause,
        buffered=fields.buffered or kind == "backfill",
        rain_tips_total=fields.rain_tips_total, rain_tips_window=fields.rain_tips_window,
        rain_mm_per_tip=fields.rain_mm_per_tip, rain_max_tips_1min=fields.rain_max_tips_1min,
        rain_min_tip_ms=fields.rain_min_tip_ms, rain_bounce=fields.rain_bounce, rain_err=fields.rain_err,
        measured_level=risk_rules.gauge_level(cm, g),
    )
    reasons = []
    rng = out_of_range(distance, g)
    if rng:
        r.quality, reasons = "out_of_range", [rng]
    else:
        reasons = device_quality_reasons(fields)
        if reasons:
            r.quality = "suspect"
    r.quality_reasons = reasons
    return r


def _village_and_gauge(repo: Repo, village_id: str, device_id: str) -> Village:
    village = repo.get_village(village_id)
    if village is None:
        raise IngestError(404, "not_found", "Village not found")
    if village.gauge is None or village.gauge.device_id != device_id:
        raise IngestError(403, "wrong_device", "This device is not the gauge for this village")
    return village


def ingest(repo: Repo, village_id: str, device_id: str, fields: ReadingFields, at: datetime, *,
           now: datetime | None = None, transport: Literal["https", "mqtt"] = "https") -> IngestResult:
    """Store one authenticated live reading with its quality and levels, audit a change of the
    level the rules count, and re-run the village's rules at once when that level is at watch or
    above (only ever to raise the level). A reading marked `buffered` is stored as backfill.

    The caller has already authenticated the device (HMAC signature or X.509 certificate) and
    checked the timestamp window. Raises IngestError for an unknown village (404), a device that
    is not the village's registered gauge (403), or a raw distance without a datum (400).
    """
    now = now or clock.now()
    village = _village_and_gauge(repo, village_id, device_id)
    g = village.gauge
    assert g is not None
    if fields.buffered:
        res = _store_backfill(repo, village, device_id, [fields], now=now, transport=transport)
        if res.rejected:
            raise IngestError(400, res.rejected[0]["code"], res.rejected[0]["reason"])
        r = "accepted" if res.stored else "ignored"
        return IngestResult(r, kind="backfill", village_level=village.level)  # type: ignore[arg-type]

    reading = _reading(village, device_id, fields, at, now, transport, "live")
    history = _history(repo, village.id, device_id, at, g)
    if reading.quality == "good" and is_spike(reading, history, g):
        reading.quality = "spike"
        reading.quality_reasons = [f"rate>{g.max_rise_cm_per_min:g}cm/min"]

    fresh_from = at - timedelta(minutes=risk_rules.GAUGE_FRESH_MINUTES)
    good = [r for r in history if r.quality == "good" and clock.parse(r.at) >= fresh_from]
    if reading.quality == "good":
        good.append(reading)
    reading.confirmed_level = confirmed(good, g)
    climb = rise([r for r in history if r.quality == "good"] + ([reading] if reading.quality == "good" else []),
                 reading.at, g)
    reading.rising_fast = climb is not None
    reading.rise_cm = climb
    reading.effective_level = _up(reading.confirmed_level) if climb is not None else reading.confirmed_level

    before = risk_rules.gauge_counted_level(history[-1], g) if history else "normal"
    if not repo.put_sensor_reading(reading):
        return IngestResult("ignored")
    if reading.quality != "good":
        metric("GaugeBadReading", 1, Quality=reading.quality)
    rain = _rain(repo, village, device_id, fields, at, now, transport, "live")
    from Pukaar.services.devices import registry

    registry.touch(repo, village.id, device_id, clock.iso(now), "cell", fw=fields.fw)

    level = reading.effective_level
    if level != before:
        why = (f"confirmed {reading.confirmed_level} (2 of the last 3 good readings)"
               + (f", rising fast +{climb:g} cm in {g.rise_minutes:g} min" if climb is not None else ""))
        try:
            repo.append_audit(AuditRow(
                at=clock.iso(now), id=new_id("aud"), actor=device_id, role="gauge", action="gauge_level",
                resource=f"village:{village.id}", decision="allow",
                reason=(f"gauge {before} -> {level} at {reading.water_level_cm:g} cm via {transport}; {why}"
                        + (" (simulated)" if reading.simulated else ""))[:500],
            ))
        except Exception as exc:  # the reading is stored; a missing audit row must not lose it
            log(_LOG, "gauge audit write failed", 40, error=str(exc)[:200])

    result = None
    # A simulated reading is stored and shown but never sets a live level (risk_rules.assess),
    # so it does not trigger a re-evaluation either. A running replay does not pause this:
    # the replay works on its own copy of the village.
    rain_level = rain.eval_level if rain is not None else None
    if not reading.simulated and (level_rank(level) >= level_rank("watch")
                                  or level_rank(rain_level or "normal") >= level_rank("watch")):
        # Re-evaluate now rather than at the next 15-minute sweep, but only to raise a level.
        from Pukaar.services.decision_engine import recompute_village
        from Pukaar.workflow.client import get_workflow

        try:
            result = recompute_village(repo, village, now=now, workflow=get_workflow(), only_if_rising=True)
        except Exception as exc:  # the next sweep picks the reading up
            log(_LOG, "gauge recompute failed", 40, village_id=village.id, error=str(exc)[:200])
    return IngestResult("accepted", gauge_level=reading.measured_level, rain_level=rain_level, simulated=reading.simulated,
                        village_level=result.level if result else village.level,
                        alert_id=result.alert_id if result else None, quality=reading.quality,
                        confirmed_level=reading.confirmed_level, effective_level=level,
                        rising_fast=reading.rising_fast)


def ingest_backfill(repo: Repo, village_id: str, device_id: str, items: list[ReadingFields], *,
                    now: datetime | None = None, transport: Literal["https", "mqtt"] = "https") -> BackfillResult:
    """Store buffered readings. Idempotent on (device, boot, seq); never re-evaluates, never alerts.

    Each item needs a seq and a timestamp within BACKFILL_MAX_AGE_HOURS (and not ahead of the
    server clock by more than MAX_SKEW_SECONDS); items that fail are listed in `rejected`, the
    rest are stored. Raises IngestError only for the village and device checks.
    """
    now = now or clock.now()
    village = _village_and_gauge(repo, village_id, device_id)
    if len(items) > BACKFILL_MAX_ITEMS:
        raise IngestError(413, "too_many", f"at most {BACKFILL_MAX_ITEMS} readings per backfill message")
    return _store_backfill(repo, village, device_id, items, now=now, transport=transport)


def _store_backfill(repo: Repo, village: Village, device_id: str, items: list[ReadingFields], *, now: datetime,
                    transport: str) -> BackfillResult:
    g = village.gauge
    assert g is not None
    out = BackfillResult()
    parsed: list[tuple[datetime, ReadingFields]] = []
    for f in items:
        try:
            parsed.append((clock.parse(f.at), f))
        except ValueError:
            out.rejected.append({"seq": f.seq, "code": "bad_payload", "reason": f"bad timestamp {f.at[:40]}"})
    history: list[SensorReading] = []
    for at, f in sorted(parsed, key=lambda p: p[0]):
        age = (now - at).total_seconds()
        if f.seq is None:
            out.rejected.append({"seq": None, "at": f.at, "code": "no_seq", "reason": "a backfilled reading needs seq"})
            continue
        if age > BACKFILL_MAX_AGE_HOURS * 3600 or age < -MAX_SKEW_SECONDS:
            out.rejected.append({"seq": f.seq, "at": f.at, "code": "stale",
                                 "reason": f"outside the {BACKFILL_MAX_AGE_HOURS} h backfill window"})
            continue
        try:
            r = _reading(village, device_id, f, at, now, transport, "backfill")
        except IngestError as exc:
            out.rejected.append({"seq": f.seq, "at": f.at, "code": exc.code, "reason": exc.reason})
            continue
        if r.quality == "good" and is_spike(r, history, g):
            r.quality, r.quality_reasons = "spike", [f"rate>{g.max_rise_cm_per_min:g}cm/min"]
        history.append(r)
        if repo.put_sensor_backfill(r):
            out.stored += 1
            _rain(repo, village, device_id, f, at, now, transport, "backfill")
        else:
            out.duplicate += 1
    if out.stored:
        metric("GaugeBackfill", out.stored, Transport=transport)
    log(_LOG, "gauge backfill", village_id=village.id, device_id=device_id, stored=out.stored,
        duplicate=out.duplicate, rejected=len(out.rejected))
    return out


def _rain(repo: Repo, village: Village, device_id: str, fields: ReadingFields, at: datetime, now: datetime,
          transport: str, origin: str):
    """A v3 reading's tipping bucket, as observed rain (services/rain_obs.py). Never raises: the river
    reading is stored whatever happens to its rain."""
    from Pukaar.services import rain_obs

    if not rain_obs.has_rain(fields):
        return None
    try:
        return rain_obs.ingest(repo, village, device_id, fields, at, now=now, transport=transport, origin=origin)
    except Exception as exc:
        log(_LOG, "rain reading failed", 40, village_id=village.id, device_id=device_id, error=str(exc)[:200])
        return None


# -- health ---------------------------------------------------------------
def health(g: GaugeConfig, readings: list[SensorReading], now: datetime,
           latest: SensorReading | None = None, raining: bool = False) -> dict[str, Any]:
    """Health of one gauge from its last 24 h (oldest first; live and backfill) and, if that is
    empty, its newest reading of any age. gauge_unhealthy when silent for over SILENT_MINUTES,
    the battery is low, or at least half of the last day's readings were bad; and the FloodNet checks
    (services/devices/floodnet.py): the battery empty within a week at its slope, more than 20% of readings
    missing from the sequence numbers, or the same level 6 times running while it rains (raining)."""
    seen = [clock.parse(r.received_at or r.at) for r in readings]
    if latest is not None:
        seen.append(clock.parse(latest.received_at or latest.at))
    last_seen = max(seen) if seen else None
    minutes = round((now - last_seen).total_seconds() / 60, 1) if last_seen else None
    newest = [r for r in readings if r.battery_v is not None] or ([latest] if latest and latest.battery_v else [])
    newest = sorted(newest, key=lambda r: r.at)
    battery_v = newest[-1].battery_v if newest else None
    battery_low = battery_v is not None and battery_v * 1000 < g.low_battery_mv
    by_quality: dict[str, int] = {}
    for r in readings:
        by_quality[r.quality] = by_quality.get(r.quality, 0) + 1
    bad = len(readings) - by_quality.get("good", 0)
    share = round(bad / len(readings), 3) if readings else None
    reasons = []
    if minutes is None or minutes > SILENT_MINUTES:
        reasons.append("silent")
    if battery_low:
        reasons.append("low_battery")
    if share is not None and len(readings) >= BAD_SHARE_MIN_READINGS and share >= BAD_SHARE_UNHEALTHY:
        reasons.append("bad_quality")
    from Pukaar.services.devices import floodnet

    signals = floodnet.signals(
        now=now, battery=[(clock.parse(r.at), r.battery_v * 1000) for r in readings if r.battery_v is not None],
        empty=float(g.low_battery_mv), seqs=[(r.boot, r.seq) for r in readings],
        values=[r.water_level_cm for r in readings if r.origin == "live" and r.quality == "good"], raining=raining)
    reasons += signals["reasons"]
    last = readings[-1] if readings else latest
    return {
        "status": "gauge_unhealthy" if reasons else "ok",
        "unhealthy": bool(reasons),
        "reasons": reasons,
        "last_seen": clock.iso(last_seen) if last_seen else None,
        "minutes_since": minutes,
        "silent_after_minutes": SILENT_MINUTES,
        "battery_v": battery_v,
        "battery_low": battery_low,
        "low_battery_mv": g.low_battery_mv,
        "solar_mv": last.solar_mv if last else None,
        "fw": last.fw if last else None,
        "readings_24h": len(readings),
        "bad_24h": bad,
        "bad_share_24h": share,
        "by_quality": by_quality,
        "backfilled_24h": sum(1 for r in readings if r.origin == "backfill"),
        "signals": {k: signals[k] for k in ("battery", "packet_loss", "stuck")},
    }


def raining_now(repo: Repo, village_id: str) -> bool:
    """Forecast rain at or over IMD "moderate" (or a band) in the village's newest live reading: the stuck-value
    check counts only then (a steady river in dry weather is normal). Never raises."""
    try:
        latest = repo.list_readings(village_id, limit=1)
        reading = latest[0] if latest and not latest[0].replay else None
        if reading is None:
            return False
        return risk_rules.raining(reading, risk_rules.rain_level(reading.rain_24h_mm), None) is not None
    except Exception:
        return False


def silence(repo: Repo, village: Village, now: datetime) -> dict[str, Any] | None:
    """Is the village gauge silent (nothing received, live or backfill, for over SILENT_MINUTES)? For the
    rules (risk_rules.assess gauge_silence): a gauge that stops reporting while it rains is itself a signal
    (Lachen 2023, Babai 2014). None when the village has no gauge. Never raises: a failed read is unknown,
    reported as not silent so it never raises a level on its own."""
    g = village.gauge
    if g is None:
        return None
    try:
        latest = repo.latest_sensor_reading(village.id, None, include_backfill=True)
    except Exception as exc:
        log(_LOG, "gauge silence check failed", 30, village_id=village.id, error=str(exc)[:200])
        return None
    last = clock.parse(latest.received_at or latest.at) if latest else None
    minutes = round((now - last).total_seconds() / 60, 1) if last else None
    return {"device_id": g.device_id, "installed": g.installed,
            "simulated": bool(latest.simulated) if latest else g.device_id.endswith("-sim"),
            "last_seen": clock.iso(last) if last else None, "minutes_silent": minutes,
            "silent_after_minutes": SILENT_MINUTES, "silent": minutes is None or minutes > SILENT_MINUTES}


def health_scan(repo: Repo, now: datetime | None = None) -> list[dict[str, Any]]:
    """Health of every gauge; emits GaugeUnhealthy (installed gauges only: the seeded simulators
    are often silent by design) and logs each unhealthy gauge. Called by the sweep; never raises."""
    now = now or clock.now()
    out = []
    try:
        since = clock.iso(now - timedelta(hours=SERIES_HOURS))
        for v in repo.list_villages():
            if v.gauge is None:
                continue
            readings = repo.list_sensor_readings(v.id, since)
            latest = None if readings else repo.latest_sensor_reading(v.id, None, include_backfill=True)
            h = health(v.gauge, readings, now, latest, raining=raining_now(repo, v.id))
            out.append({"village_id": v.id, "device_id": v.gauge.device_id, "installed": v.gauge.installed, **h})
            if h["unhealthy"]:
                log(_LOG, "gauge_unhealthy", 30 if v.gauge.installed else 20, village_id=v.id,
                    device_id=v.gauge.device_id, reasons=",".join(h["reasons"]), installed=v.gauge.installed)
        metric("GaugeUnhealthy", sum(1 for h in out if h["unhealthy"] and h["installed"]))
    except Exception as exc:
        log(_LOG, "gauge health scan failed", 40, error=str(exc)[:200])
    return out


# -- village page ---------------------------------------------------------
def view(repo: Repo, v: Village) -> dict[str, Any] | None:
    """Gauge block for the village page: config, newest live reading, freshness, the level the
    rules count, health, and the last 24 h (thinned; bad and backfilled points marked)."""
    if v.gauge is None:
        return None
    now = clock.now()
    series = repo.list_sensor_readings(v.id, clock.iso(now - timedelta(hours=SERIES_HOURS)))
    live = [r for r in series if r.origin == "live"]
    latest = live[-1] if live else repo.latest_sensor_reading(v.id, max_age_minutes=None)
    fresh = risk_rules.gauge_is_fresh(latest, now)
    step = max(1, -(-len(series) // SERIES_POINTS))
    thin = series[::step]
    if series and thin[-1] is not series[-1]:
        thin.append(series[-1])
    points = []
    for r in thin:
        p: dict[str, Any] = {"at": r.at, "cm": r.water_level_cm}
        if r.quality != "good":
            p["q"] = r.quality
        if r.origin == "backfill":
            p["backfill"] = True
        points.append(p)
    return {
        "config": v.gauge.model_dump(),
        "latest": latest.model_dump() if latest else None,
        "fresh": fresh,
        "fresh_minutes": risk_rules.GAUGE_FRESH_MINUTES,
        # What the rules count: 2 of the last 3 good readings, one step up when rising fast.
        "level": risk_rules.gauge_counted_level(latest, v.gauge) if latest and fresh else None,
        "measured_level": risk_rules.gauge_level(latest.water_level_cm, v.gauge) if latest and fresh else None,
        "rising_fast": bool(latest and fresh and latest.rising_fast),
        "health": health(v.gauge, series, now, None if series else latest, raining=raining_now(repo, v.id)),
        "series": points,
    }
