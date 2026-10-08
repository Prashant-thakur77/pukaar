from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _as_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    pukaar_node_profile: str
    project_root: Path
    backend_root: Path
    data_dir: Path
    upload_dir: Path
    edge_db_path: Path
    central_db_path: Path
    ffmpeg_bin: str
    llm_enabled: bool
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout_seconds: float
    pukaar_node_provider: str
    pukaar_node_model_path: Path
    pukaar_node_backend: str
    pukaar_node_vision_backend: str
    pukaar_node_multimodal_backend: str
    pukaar_node_multimodal_vision_backend: str
    pukaar_node_enable_speculative_decoding: bool
    pukaar_node_cache_dir: Path
    pukaar_node_max_output_tokens: int
    pukaar_node_multimodal_max_output_tokens: int
    pukaar_multimodal_enabled: bool
    pukaar_multimodal_verifier_enabled: bool
    pukaar_multimodal_base_url: str
    pukaar_multimodal_model: str
    pukaar_multimodal_min_interval_seconds: int
    pukaar_multimodal_score_threshold: float
    pukaar_multimodal_confidence_threshold: float
    pukaar_multimodal_image_max_side: int
    pukaar_multimodal_max_frames: int
    pukaar_multimodal_frame_sample_seconds: int
    pukaar_multimodal_num_ctx: int
    pukaar_multimodal_num_predict: int
    pukaar_multimodal_timeout_seconds: float
    hydromet_enabled: bool
    hydromet_timeout_seconds: float
    pukaar_max_curated_frames: int
    pukaar_artifact_retention_days: int
    asr_enabled: bool
    asr_model_size: str
    asr_model_cache_dir: Path
    pukaar_image_enabled: bool
    image_max_tokens: int
    image_timeout_seconds: float
    actuators_enabled: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    backend_root = Path(__file__).resolve().parents[3]
    project_root = backend_root.parent
    data_dir = Path(os.environ.get("PUKAAR_DATA_DIR", str(backend_root / "data")))
    pukaar_node_profile = os.environ.get("PUKAAR_NODE_PROFILE", "raspberry-pi-8gb-multimodal-demo")
    normalized_profile = pukaar_node_profile.strip().lower()
    is_pi8_demo_profile = normalized_profile in {
        "raspberry-pi-8gb",
        "raspberry-pi-8gb-multimodal-demo",
        "raspberry-pi",
        "rpi8gb",
        "rpi",
    }
    is_pi16_prod_profile = normalized_profile in {
        "raspberry-pi-16gb",
        "raspberry-pi-16gb-multimodal-prod",
        "rpi16gb",
    }
    upload_dir = Path(os.environ.get("PUKAAR_UPLOAD_DIR", str(data_dir / "uploads")))

    edge_db_path = Path(os.environ.get("PUKAAR_EDGE_DB_PATH", str(data_dir / "edge.db")))
    central_db_path = Path(os.environ.get("PUKAAR_CENTRAL_DB_PATH", str(data_dir / "central.db")))
    asr_model_cache_dir = Path(
        os.environ.get("PUKAAR_ASR_MODEL_CACHE_DIR", str(data_dir / "whisper-models"))
    )
    pukaar_node_model_path = Path(
        os.environ.get(
            "PUKAAR_NODE_MODEL_PATH",
            str(data_dir / "models" / "pukaar-model-2b.litertlm"),
        )
    )
    pukaar_node_cache_dir = Path(
        os.environ.get(
            "PUKAAR_NODE_CACHE_DIR",
            str(data_dir / "litert-cache"),
        )
    )
    pukaar_multimodal_enabled_default = _as_bool("PUKAAR_MULTIMODAL_ENABLED", True)

    return Settings(
        pukaar_node_profile=pukaar_node_profile,
        project_root=project_root,
        backend_root=backend_root,
        data_dir=data_dir,
        upload_dir=upload_dir,
        edge_db_path=edge_db_path,
        central_db_path=central_db_path,
        ffmpeg_bin=os.environ.get("PUKAAR_FFMPEG_BIN", "ffmpeg"),
        llm_enabled=_as_bool("PUKAAR_LLM_ENABLED", True),
        llm_base_url=os.environ.get("PUKAAR_LLM_BASE_URL", "http://127.0.0.1:11434/v1"),
        llm_model=os.environ.get("PUKAAR_LLM_MODEL", "pukaar-model:2b"),
        llm_api_key=os.environ.get("PUKAAR_LLM_API_KEY", "ollama"),
        llm_timeout_seconds=float(os.environ.get("PUKAAR_LLM_TIMEOUT_SECONDS", "30")),
        pukaar_node_provider=os.environ.get("PUKAAR_NODE_PROVIDER", "litert").strip().lower(),
        pukaar_node_model_path=pukaar_node_model_path,
        pukaar_node_backend=os.environ.get("PUKAAR_NODE_BACKEND", "gpu").strip().lower(),
        pukaar_node_vision_backend=os.environ.get(
            "PUKAAR_NODE_VISION_BACKEND",
            os.environ.get("PUKAAR_NODE_BACKEND", "gpu"),
        ).strip().lower(),
        pukaar_node_multimodal_backend=os.environ.get(
            "PUKAAR_NODE_MULTIMODAL_BACKEND",
            "cpu",
        ).strip().lower(),
        pukaar_node_multimodal_vision_backend=os.environ.get(
            "PUKAAR_NODE_MULTIMODAL_VISION_BACKEND",
            os.environ.get("PUKAAR_NODE_MULTIMODAL_BACKEND", "cpu"),
        ).strip().lower(),
        pukaar_node_enable_speculative_decoding=_as_bool(
            "PUKAAR_NODE_ENABLE_SPECULATIVE_DECODING",
            True,
        ),
        pukaar_node_cache_dir=pukaar_node_cache_dir,
        pukaar_node_max_output_tokens=int(
            os.environ.get("PUKAAR_NODE_MAX_OUTPUT_TOKENS", "1024")
        ),
        pukaar_node_multimodal_max_output_tokens=int(
            os.environ.get("PUKAAR_NODE_MULTIMODAL_MAX_OUTPUT_TOKENS", "2048")
        ),
        pukaar_multimodal_enabled=pukaar_multimodal_enabled_default,
        pukaar_multimodal_verifier_enabled=_as_bool(
            "PUKAAR_MULTIMODAL_VERIFIER_ENABLED",
            False,
        ),
        pukaar_multimodal_base_url=os.environ.get(
            "PUKAAR_MULTIMODAL_BASE_URL",
            os.environ.get("PUKAAR_LLM_BASE_URL", "http://127.0.0.1:11434/v1"),
        ),
        pukaar_multimodal_model=os.environ.get(
            "PUKAAR_MULTIMODAL_MODEL",
            pukaar_node_model_path.name,
        ),
        pukaar_multimodal_min_interval_seconds=int(
            os.environ.get("PUKAAR_MULTIMODAL_MIN_INTERVAL_SECONDS", "300")
        ),
        pukaar_multimodal_score_threshold=float(
            os.environ.get("PUKAAR_MULTIMODAL_SCORE_THRESHOLD", "0.55")
        ),
        pukaar_multimodal_confidence_threshold=float(
            os.environ.get("PUKAAR_MULTIMODAL_CONFIDENCE_THRESHOLD", "0.62")
        ),
        pukaar_multimodal_image_max_side=int(
            os.environ.get(
                "PUKAAR_MULTIMODAL_IMAGE_MAX_SIDE",
                "512" if is_pi8_demo_profile else "960" if is_pi16_prod_profile else "1024",
            )
        ),
        pukaar_multimodal_max_frames=int(
            os.environ.get("PUKAAR_MULTIMODAL_MAX_FRAMES", "1" if is_pi8_demo_profile else "4")
        ),
        pukaar_multimodal_frame_sample_seconds=int(
            os.environ.get("PUKAAR_MULTIMODAL_FRAME_SAMPLE_SECONDS", "300" if is_pi8_demo_profile else "60")
        ),
        pukaar_multimodal_num_ctx=int(
            os.environ.get("PUKAAR_MULTIMODAL_NUM_CTX", "1024" if is_pi8_demo_profile else "4096")
        ),
        pukaar_multimodal_num_predict=int(
            os.environ.get("PUKAAR_MULTIMODAL_NUM_PREDICT", "512")
        ),
        pukaar_multimodal_timeout_seconds=float(
            os.environ.get("PUKAAR_MULTIMODAL_TIMEOUT_SECONDS", "300" if is_pi8_demo_profile else "180")
        ),
        hydromet_enabled=_as_bool("PUKAAR_HYDROMET_ENABLED", True),
        hydromet_timeout_seconds=float(os.environ.get("PUKAAR_HYDROMET_TIMEOUT_SECONDS", "12")),
        pukaar_max_curated_frames=int(
            os.environ.get("PUKAAR_MAX_CURATED_FRAMES", "1" if is_pi8_demo_profile else "4" if is_pi16_prod_profile else "6")
        ),
        pukaar_artifact_retention_days=int(
            os.environ.get(
                "PUKAAR_ARTIFACT_RETENTION_DAYS",
                "3" if is_pi8_demo_profile else "14",
            )
        ),
        asr_enabled=_as_bool("PUKAAR_ASR_ENABLED", True),
        asr_model_size=os.environ.get("PUKAAR_ASR_MODEL_SIZE", "tiny"),
        asr_model_cache_dir=asr_model_cache_dir,
        pukaar_image_enabled=_as_bool("Pukaar_IMAGE_ENABLED", pukaar_multimodal_enabled_default),
        image_max_tokens=int(os.environ.get("PUKAAR_IMAGE_MAX_TOKENS", "256")),
        image_timeout_seconds=float(os.environ.get("PUKAAR_IMAGE_TIMEOUT_SECONDS", "300")),
        actuators_enabled=_as_bool("PUKAAR_ACTUATORS_ENABLED", True),
    )
