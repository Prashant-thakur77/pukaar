"""Last check before anything is sent: known level, inside Himachal Pradesh,
and a per-village rate limit on distinct alerts."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from Pukaar.core import clock

# Himachal Pradesh bounding box (approximate, generous by about 0.2 degrees).
HP_BOUNDS = {"min_lat": 30.2, "max_lat": 33.4, "min_lon": 75.4, "max_lon": 79.2}
MAX_ALERTS_PER_HOUR = 6
_SENT: dict[str, deque[tuple[datetime, str]]] = defaultdict(deque)


@dataclass(frozen=True)
class GuardResult:
    accepted: bool
    reason: str


def inside_operational_area(lat: float, lon: float) -> bool:
    b = HP_BOUNDS
    return b["min_lat"] <= lat <= b["max_lat"] and b["min_lon"] <= lon <= b["max_lon"]


def check_send(village_id: str, level: str, alert_id: str, now: datetime | None = None) -> GuardResult:
    if level not in {"watch", "warning", "critical"}:
        return GuardResult(False, f"no send at level {level}")
    now = now or clock.now()
    bucket = _SENT[village_id]
    while bucket and bucket[0][0] < now - timedelta(hours=1):
        bucket.popleft()
    if any(a == alert_id for _, a in bucket):
        return GuardResult(True, "accepted")
    if len(bucket) >= MAX_ALERTS_PER_HOUR:
        return GuardResult(False, f"rate limit: {MAX_ALERTS_PER_HOUR} alerts per hour for {village_id}")
    bucket.append((now, alert_id))
    return GuardResult(True, "accepted")


def reset() -> None:
    _SENT.clear()
