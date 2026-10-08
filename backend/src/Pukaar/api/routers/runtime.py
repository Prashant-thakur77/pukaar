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
        "pukaar_node_profile": settings.pukaar_node_profile,
        "llm_enabled": settings.llm_enabled,
        "hydromet_enabled": settings.hydromet_enabled,
    }


@router.get("/settings/runtime", response_model=RuntimeStatus)
async def get_runtime_status() -> RuntimeStatus:
    settings = get_settings()
    llm_status = deps.llm_client.health()
    pukaar_node_status = deps.pukaar_node_runtime.health()
    hydromet_status = deps.external_data_service.health()
    pukaar_engine_ready = pukaar_node_status.reachable
    pukaar_engine_detail = pukaar_node_status.detail
    if settings.pukaar_node_provider == "ollama":
        pukaar_engine_ready = llm_status.reachable
        pukaar_engine_detail = (
            f"Ollama development runtime for Pukaar. "
            f"LLM detail: {llm_status.detail}"
        )
    p1_runtime_ready = settings.pukaar_node_provider == "litert" and pukaar_engine_ready
    return RuntimeStatus(
        is_online=deps.is_online,
        llm={
            "enabled": llm_status.enabled,
            "reachable": llm_status.reachable,
            "base_url": llm_status.base_url,
            "model": llm_status.model,
            "detail": llm_status.detail,
        },
        pukaar={
            "node_profile": settings.pukaar_node_profile,
            "provider": pukaar_node_status.provider,
            "backend": pukaar_node_status.backend,
            "vision_backend": settings.pukaar_node_vision_backend,
            "multimodal_backend": settings.pukaar_node_multimodal_backend,
            "multimodal_vision_backend": settings.pukaar_node_multimodal_vision_backend,
            "speculative_decoding": settings.pukaar_node_enable_speculative_decoding,
            "max_output_tokens": settings.pukaar_node_max_output_tokens,
            "multimodal_max_output_tokens": settings.pukaar_node_multimodal_max_output_tokens,
            "engine_ready": pukaar_engine_ready,
            "engine_detail": pukaar_engine_detail,
            "counts_for_p1": p1_runtime_ready,
            "p1_runtime_ready": p1_runtime_ready,
            "p1_evidence_required": (
                "Runtime readiness only. Jury-facing P1 evidence requires a completed "
                "Pukaar analysis with runner.mode=litert-multimodal-temporal."
            ),
            "model_path": pukaar_node_status.model_path,
            "cache_dir": str(settings.pukaar_node_cache_dir),
            "data_dir": str(settings.data_dir),
            "ffmpeg_bin": settings.ffmpeg_bin,
            "multimodal_enabled": settings.pukaar_multimodal_enabled,
            "multimodal_verifier_enabled": settings.pukaar_multimodal_verifier_enabled,
            "multimodal_base_url": settings.pukaar_multimodal_base_url,
            "multimodal_model": settings.pukaar_multimodal_model,
            "multimodal_min_interval_seconds": settings.pukaar_multimodal_min_interval_seconds,
            "multimodal_score_threshold": settings.pukaar_multimodal_score_threshold,
            "multimodal_confidence_threshold": settings.pukaar_multimodal_confidence_threshold,
            "multimodal_image_max_side": settings.pukaar_multimodal_image_max_side,
            "multimodal_max_frames": settings.pukaar_multimodal_max_frames,
            "multimodal_frame_sample_seconds": settings.pukaar_multimodal_frame_sample_seconds,
            "multimodal_num_ctx": settings.pukaar_multimodal_num_ctx,
            "multimodal_timeout_seconds": settings.pukaar_multimodal_timeout_seconds,
            "max_curated_frames": settings.pukaar_max_curated_frames,
            "artifact_retention_days": settings.pukaar_artifact_retention_days,
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
