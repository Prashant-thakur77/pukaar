"""Watch agent: a deterministic check of every river gauge's own readings.

It looks for the four ways a gauge goes wrong in the field and says so in plain
words. It never changes a level and never sends anything: the rules already
ignore a stale reading (risk_rules.GAUGE_FRESH_MINUTES); this makes the fault
visible to officers and the public before it matters.

Checks (each threshold is a constant below, shown on /agents and /sensors):
  stale     newest reading older than the freshness window, or none in 24 h
  flatline  the last FLAT_MIN_READINGS readings, spanning at least
            FLAT_MIN_MINUTES, all within FLAT_TOLERANCE_CM (a stuck sensor or
            a frozen firmware loop; a real river is never that still)
  jump      two consecutive readings that differ faster than JUMP_CM_PER_MIN
            (an echo off debris, a bird, a loose mount; no river rises that fast)
  battery   newest battery voltage under LOW_BATTERY_V (one 18650 cell)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

from Pukaar.core import clock
from Pukaar.services import risk_rules
from Pukaar.store.models import SensorReading, Village
from Pukaar.store.repo import Repo

STALE_MINUTES = risk_rules.GAUGE_FRESH_MINUTES
FLAT_MIN_READINGS = 15
FLAT_MIN_MINUTES = 14
FLAT_TOLERANCE_CM = 0.05
JUMP_CM_PER_MIN = 30.0
LOW_BATTERY_V = 3.5
WINDOW_HOURS = 24

CHECKS: list[dict[str, Any]] = [
    {"kind": "stale", "en": f"Newest reading older than {STALE_MINUTES} min (the rules then ignore the gauge)",
     "hi": f"सबसे नई रीडिंग {STALE_MINUTES} मिनट से पुरानी (तब नियम गेज को नहीं गिनते)"},
    {"kind": "flatline", "en": f"Last {FLAT_MIN_READINGS} readings identical (stuck sensor)",
     "hi": f"आख़िरी {FLAT_MIN_READINGS} रीडिंग बिल्कुल एक जैसी (सेंसर अटका)"},
    {"kind": "jump", "en": f"A change faster than {JUMP_CM_PER_MIN:g} cm per minute (impossible for a river)",
     "hi": f"{JUMP_CM_PER_MIN:g} सेमी प्रति मिनट से तेज़ बदलाव (नदी में असंभव)"},
    {"kind": "battery", "en": f"Battery under {LOW_BATTERY_V:g} V", "hi": f"बैटरी {LOW_BATTERY_V:g} V से कम"},
]


@dataclass
class Finding:
    village_id: str
    kind: str  # stale | no_data | flatline | jump | battery
    severity: str  # warn | info
    at: str | None
    value: float | None
    message_en: str
    message_hi: str


def _minutes(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 60


def check(village: Village, readings: list[SensorReading], now: datetime,
          latest: SensorReading | None = None) -> list[Finding]:
    """Findings for one gauge. readings: the last 24 h, oldest first."""
    if village.gauge is None:
        return []
    vid = village.id
    latest = readings[-1] if readings else latest
    out: list[Finding] = []
    if latest is None:
        return [Finding(vid, "no_data", "info", None, None, "No reading has ever arrived from this gauge.",
                        "इस गेज से अब तक कोई रीडिंग नहीं आई।")]

    age = _minutes(clock.parse(latest.at), now)
    if age > STALE_MINUTES:
        hours = age / 60
        span_en = f"{round(age)} min" if age < 120 else f"{hours:.0f} h"
        span_hi = f"{round(age)} मिनट" if age < 120 else f"{hours:.0f} घंटे"
        out.append(Finding(vid, "stale", "warn", latest.at, round(age, 1),
                           f"Stale: the last reading was {span_en} ago, so the rules ignore this gauge.",
                           f"पुरानी रीडिंग: आख़िरी रीडिंग {span_hi} पहले आई, इसलिए नियम इस गेज को नहीं गिनते।"))

    tail = readings[-FLAT_MIN_READINGS:]
    if len(tail) >= FLAT_MIN_READINGS:
        values = [r.water_level_cm for r in tail]
        span = _minutes(clock.parse(tail[0].at), clock.parse(tail[-1].at))
        if max(values) - min(values) <= FLAT_TOLERANCE_CM and span >= FLAT_MIN_MINUTES:
            out.append(Finding(vid, "flatline", "warn", tail[-1].at, values[-1],
                               f"Flat-lined: {len(tail)} readings over {round(span)} min all read {values[-1]:g} cm. "
                               "The sensor may be stuck.",
                               f"एक जैसी रीडिंग: {round(span)} मिनट में {len(tail)} रीडिंग, सब {values[-1]:g} सेमी। "
                               "सेंसर अटका हो सकता है।"))

    worst: tuple[float, SensorReading, float] | None = None
    for a, b in pairwise(readings):
        minutes = max(1.0, _minutes(clock.parse(a.at), clock.parse(b.at)))
        rate = abs(b.water_level_cm - a.water_level_cm) / minutes
        if rate > JUMP_CM_PER_MIN and (worst is None or rate > worst[0]):
            worst = (rate, b, b.water_level_cm - a.water_level_cm)
    if worst is not None:
        rate, b, delta = worst
        out.append(Finding(vid, "jump", "warn", b.at, round(delta, 1),
                           f"Impossible jump: {delta:+g} cm at {b.at[11:16]} UTC ({rate:.0f} cm/min). "
                           "Likely an echo off debris; check the mount.",
                           f"असंभव उछाल: {b.at[11:16]} UTC पर {delta:+g} सेमी ({rate:.0f} सेमी/मिनट)। "
                           "शायद मलबे से गूँज; माउंट जाँचें।"))

    if latest.battery_v is not None and latest.battery_v < LOW_BATTERY_V:
        out.append(Finding(vid, "battery", "warn", latest.at, latest.battery_v,
                           f"Low battery: {latest.battery_v:g} V. Check the solar panel.",
                           f"बैटरी कम: {latest.battery_v:g} V। सोलर पैनल जाँचें।"))
    return out


def scan(repo: Repo, now: datetime | None = None) -> dict[str, tuple[list[SensorReading], SensorReading | None, list[Finding]]]:
    """village_id -> (last 24 h of readings oldest first, newest reading ever, findings), for gauged villages."""
    now = now or clock.now()
    since = clock.iso(now - timedelta(hours=WINDOW_HOURS))
    out = {}
    for v in repo.list_villages():
        if v.gauge is None:
            continue
        readings = repo.list_sensor_readings(v.id, since)
        latest = readings[-1] if readings else repo.latest_sensor_reading(v.id, max_age_minutes=None)
        out[v.id] = (readings, latest, check(v, readings, now, latest))
    return out


def as_dict(f: Finding) -> dict[str, Any]:
    return asdict(f)
