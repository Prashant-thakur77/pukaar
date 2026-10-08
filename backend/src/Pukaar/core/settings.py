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
    data_dir: Path
    upload_dir: Path
    edge_db_path: Path
    llm_enabled: bool
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout_seconds: float
    pukaar_multimodal_enabled: bool
    pukaar_multimodal_verifier_enabled: bool
    pukaar_multimodal_base_url: str
    pukaar_multimodal_model: str
    pukaar_multimodal_image_max_side: int
    pukaar_multimodal_num_ctx: int
    pukaar_multimodal_num_predict: int
    pukaar_multimodal_timeout_seconds: float
    hydromet_enabled: bool
    hydromet_timeout_seconds: float
    asr_enabled: bool
    asr_model_size: str
    asr_model_cache_dir: Path
    pukaar_image_enabled: bool
    actuators_enabled: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    backend_root = Path(__file__).resolve().parents[3]
    data_dir = Path(os.environ.get("PUKAAR_DATA_DIR", str(backend_root / "data")))
    upload_dir = Path(os.environ.get("PUKAAR_UPLOAD_DIR", str(data_dir / "uploads")))

    edge_db_path = Path(os.environ.get("PUKAAR_EDGE_DB_PATH", str(data_dir / "edge.db")))
    asr_model_cache_dir = Path(
        os.environ.get("PUKAAR_ASR_MODEL_CACHE_DIR", str(data_dir / "whisper-models"))
    )
    pukaar_multimodal_enabled_default = _as_bool("PUKAAR_MULTIMODAL_ENABLED", True)

    return Settings(
        data_dir=data_dir,
        upload_dir=upload_dir,
        edge_db_path=edge_db_path,
        llm_enabled=_as_bool("PUKAAR_LLM_ENABLED", True),
        llm_base_url=os.environ.get("PUKAAR_LLM_BASE_URL", "http://127.0.0.1:11434/v1"),
        llm_model=os.environ.get("PUKAAR_LLM_MODEL", "pukaar-model:2b"),
        llm_api_key=os.environ.get("PUKAAR_LLM_API_KEY", "ollama"),
        llm_timeout_seconds=float(os.environ.get("PUKAAR_LLM_TIMEOUT_SECONDS", "30")),
        pukaar_multimodal_enabled=pukaar_multimodal_enabled_default,
        pukaar_multimodal_verifier_enabled=_as_bool(
            "PUKAAR_MULTIMODAL_VERIFIER_ENABLED",
            False,
        ),
        pukaar_multimodal_base_url=os.environ.get(
            "PUKAAR_MULTIMODAL_BASE_URL",
            os.environ.get("PUKAAR_LLM_BASE_URL", "http://127.0.0.1:11434/v1"),
        ),
        pukaar_multimodal_model=os.environ.get("PUKAAR_MULTIMODAL_MODEL", "pukaar-model:2b"),
        pukaar_multimodal_image_max_side=int(
            os.environ.get("PUKAAR_MULTIMODAL_IMAGE_MAX_SIDE", "512")
        ),
        pukaar_multimodal_num_ctx=int(
            os.environ.get("PUKAAR_MULTIMODAL_NUM_CTX", "1024")
        ),
        pukaar_multimodal_num_predict=int(
            os.environ.get("PUKAAR_MULTIMODAL_NUM_PREDICT", "512")
        ),
        pukaar_multimodal_timeout_seconds=float(
            os.environ.get("PUKAAR_MULTIMODAL_TIMEOUT_SECONDS", "300")
        ),
        hydromet_enabled=_as_bool("PUKAAR_HYDROMET_ENABLED", True),
        hydromet_timeout_seconds=float(os.environ.get("PUKAAR_HYDROMET_TIMEOUT_SECONDS", "12")),
        asr_enabled=_as_bool("PUKAAR_ASR_ENABLED", True),
        asr_model_size=os.environ.get("PUKAAR_ASR_MODEL_SIZE", "tiny"),
        asr_model_cache_dir=asr_model_cache_dir,
        pukaar_image_enabled=_as_bool("Pukaar_IMAGE_ENABLED", pukaar_multimodal_enabled_default),
        actuators_enabled=_as_bool("PUKAAR_ACTUATORS_ENABLED", True),
    )
