"""River-gauge helpers: per-device keys, request signatures, and the village detail view.

A gauge (docs/hardware/README.md) signs the raw JSON body it POSTs to
/sensors/{village_id}/readings with HMAC-SHA256. Its key is derived from the
link secret, so no per-device secret has to be stored server side:

    device_key = hex(HMAC-SHA256(link_secret, "gauge:" + device_id))
    X-Pukaar-Signature = hex(HMAC-SHA256(device_key as ASCII bytes, raw body))
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta
from typing import Any

from Pukaar.core import clock
from Pukaar.services import risk_rules
from Pukaar.store.models import Village
from Pukaar.store.repo import Repo

SIGNATURE_HEADER = "X-Pukaar-Signature"
MAX_AGE_SECONDS = 300  # older timestamps are rejected (replay protection)
MAX_SKEW_SECONDS = 120  # a device clock this far ahead is tolerated
SERIES_HOURS = 24
SERIES_POINTS = 96


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
