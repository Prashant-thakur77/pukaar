"""A small cache for slow-changing external data (the daily river ensemble, official feeds).

Two layers: this process's memory, and on AWS one DynamoDB item per key (repo.get_cache /
put_cache), so a cold Lambda start does not fetch again what another sweep fetched an hour
ago. Every value is a JSON-able dict with a "status": "ok" values are kept for ttl_seconds,
anything else ("unavailable") only for failure_ttl_seconds, so a provider that was down is
asked again soon but never on every sweep. Expiry follows core.clock, so tests can move time.
"""

from __future__ import annotations

from typing import Any, Callable

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log

_LOG = get_logger("fetch_cache")
_MEM: dict[str, tuple[float, dict[str, Any]]] = {}


def clear() -> None:
    _MEM.clear()


def _now() -> float:
    return clock.now().timestamp()


def _repo():
    if get_settings().mode != "aws":
        return None
    from Pukaar.store.repo import get_repo

    return get_repo()


def get(key: str) -> dict[str, Any] | None:
    hit = _MEM.get(key)
    if hit and hit[0] > _now():
        return hit[1]
    repo = _repo()
    if repo is None:
        return None
    try:
        stored = repo.get_cache(key, now=_now())
    except Exception as exc:  # the cache is an optimisation: a failed read means "fetch"
        log(_LOG, "cache read failed", 30, key=key, error=type(exc).__name__)
        return None
    if stored is not None:
        _MEM[key] = stored
        return stored[1]
    return None


def put(key: str, value: dict[str, Any], ttl_seconds: float) -> None:
    expires = _now() + ttl_seconds
    _MEM[key] = (expires, value)
    repo = _repo()
    if repo is None:
        return
    try:
        repo.put_cache(key, value, expires)
    except Exception as exc:
        log(_LOG, "cache write failed", 30, key=key, error=type(exc).__name__)


def get_or_fetch(key: str, ttl_seconds: float, fetch: Callable[[], dict[str, Any]],
                 *, failure_ttl_seconds: float = 900) -> dict[str, Any]:
    """The cached value for key, or fetch() stored for ttl_seconds (failure_ttl_seconds when not ok)."""
    cached = get(key)
    if cached is not None:
        return cached
    value = fetch()
    put(key, value, ttl_seconds if value.get("status") == "ok" else failure_ttl_seconds)
    return value
