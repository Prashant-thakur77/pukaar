"""Injectable clock. All times are timezone-aware UTC."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


def now() -> datetime:
    return _now()


def set_clock(fn: Callable[[], datetime] | None) -> None:
    """Replace the clock (tests). Pass None to restore the real clock."""
    global _now
    _now = fn or (lambda: datetime.now(timezone.utc))


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
