"""Public, read-only views of the agents and the river gauges (no sign-in, no personal data).

GET /agents          the agent registry, read from code, with live status
GET /agents/traces   recent real alerts as round-by-round steps
GET /sensors         every gauge's latest reading, freshness and the Watch agent's findings

In AWS each answer is kept for a few seconds per Lambda container, so a busy
public page costs one set of DynamoDB reads, not one per visitor.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Query

from Pukaar.core.config import get_settings
from Pukaar.services import agents as agents_svc
from Pukaar.store.repo import get_repo

router = APIRouter()
CACHE_SECONDS = 15.0
_CACHE: dict[str, tuple[float, Any]] = {}


def _cached(key: str, build: Callable[[], Any]) -> Any:
    if get_settings().is_local:
        return build()
    hit = _CACHE.get(key)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]
    value = build()
    _CACHE[key] = (now + CACHE_SECONDS, value)
    return value


@router.get("/agents")
def agents() -> dict:
    return _cached("agents", lambda: agents_svc.registry(get_repo()))


@router.get("/agents/traces")
def agent_traces(limit: int = Query(5, ge=1, le=10)) -> list[dict]:
    return _cached(f"traces:{limit}", lambda: agents_svc.traces(get_repo(), limit))


@router.get("/sensors")
def sensors() -> dict:
    return _cached("sensors", lambda: agents_svc.sensors(get_repo()))
