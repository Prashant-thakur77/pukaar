from __future__ import annotations

import json
from datetime import datetime

from sqlmodel import SQLModel, Session, select

from Pukaar.adapters.asr import FasterWhisperASRAdapter
from Pukaar.adapters.image_assessment import PukaarAIImageAssessmentAdapter
from Pukaar.adapters.litert_node import LiteRTNodeRuntime
from Pukaar.adapters.llm import OpenAICompatibleLLM
from Pukaar.adapters.text_structuring_fewshot import FewShotTextStructurer
from Pukaar.adapters.video_assessment import LiteRTPukaarAIRunner, OllamaPukaarAIRunner
from Pukaar.core.settings import get_settings
from Pukaar.models.domain import SyncQueueItem
from Pukaar.services.pukaar_assessment import PukaarAssessmentEngine, TemporalEvidenceBuilder
from Pukaar.services.external_data import ExternalDataService


def _build_pukaar_runtime_components() -> tuple[object, PukaarAIImageAssessmentAdapter]:
    settings = get_settings()
    provider = settings.pukaar_node_provider
    if provider == "litert":
        return (
            LiteRTPukaarAIRunner(pukaar_node_runtime),
            PukaarAIImageAssessmentAdapter(runtime=pukaar_node_runtime, force_embedded=True),
        )
    if provider == "ollama":
        return (
            OllamaPukaarAIRunner(llm_client),
            PukaarAIImageAssessmentAdapter(),
        )
    raise ValueError(
        f"Unsupported PUKAAR_NODE_PROVIDER={provider!r}. Expected 'litert' or 'ollama'."
    )


llm_client = OpenAICompatibleLLM()
pukaar_node_runtime = LiteRTNodeRuntime()
text_structurer = FewShotTextStructurer(llm_client)
pukaar_runner, pukaar_image_assessor = _build_pukaar_runtime_components()
image_assessor = PukaarAIImageAssessmentAdapter()
asr_client = FasterWhisperASRAdapter()
external_data_service = ExternalDataService()
pukaar_engine = PukaarAssessmentEngine(
    builder=TemporalEvidenceBuilder(),
    runner=pukaar_runner,
)

is_online = True


def get_decision_runtime() -> OpenAICompatibleLLM | LiteRTNodeRuntime:
    """Central reasoning + actuator runtime.

    Topology: Pukaar (fixed-cam Pi) runs the LiteRT vision engine; the central
    backend runs the larger Pukaar AI model via Ollama for fusion reasoning and
    actuator JSON tool selection. Vision and central reasoning are split engines.
    """
    return llm_client


def enqueue_entity(session: Session, entity_type: str, entity: SQLModel) -> None:
    entity_id = getattr(entity, "id", None)
    if entity_id is None:
        return
    existing = session.exec(
        select(SyncQueueItem)
        .where(SyncQueueItem.entity_type == entity_type)
        .where(SyncQueueItem.entity_id == entity_id)
        .where(SyncQueueItem.status == "pending")
    ).first()
    if existing is not None:
        existing.payload = json.dumps(entity.model_dump(mode="json"), ensure_ascii=True)
        existing.updated_at = datetime.utcnow()
        existing.last_error = None
        session.add(existing)
        return
    queue_item = SyncQueueItem(
        entity_type=entity_type,
        entity_id=entity_id,
        payload=json.dumps(entity.model_dump(mode="json"), ensure_ascii=True),
    )
    session.add(queue_item)

