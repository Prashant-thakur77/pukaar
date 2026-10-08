from __future__ import annotations

from fastapi import APIRouter

from Pukaar.api import deps
from Pukaar.core.settings import get_settings
from Pukaar.schemas.api import ConnectivityStatus, RuntimeStatus


router = APIRouter(tags=["runtime"])


@router.get("/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "llm_enabled": settings.llm_enabled,
        "hydromet_enabled": settings.hydromet_enabled,
    }


@router.get("/settings/runtime", response_model=RuntimeStatus)
async def get_runtime_status() -> RuntimeStatus:
    llm_status = deps.llm_client.health()
    hydromet_status = deps.external_data_service.health()
    return RuntimeStatus(
        is_online=deps.is_online,
        llm={
            "enabled": llm_status.enabled,
            "reachable": llm_status.reachable,
            "base_url": llm_status.base_url,
            "model": llm_status.model,
            "detail": llm_status.detail,
        },
        hydromet={
            "enabled": hydromet_status.enabled,
            "reachable": hydromet_status.reachable,
            "detail": hydromet_status.detail,
        },
    )


@router.get("/settings/connectivity")
async def get_connectivity() -> ConnectivityStatus:
    return ConnectivityStatus(is_online=deps.is_online)


@router.post("/settings/connectivity")
async def set_connectivity(payload: ConnectivityStatus) -> ConnectivityStatus:
    deps.is_online = payload.is_online
    return ConnectivityStatus(is_online=deps.is_online)
