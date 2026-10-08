from __future__ import annotations

import json
from datetime import datetime

from sqlmodel import SQLModel, Session, select

from Pukaar.adapters.asr import FasterWhisperASRAdapter
from Pukaar.adapters.image_assessment import PukaarAIImageAssessmentAdapter
from Pukaar.adapters.llm import OpenAICompatibleLLM
from Pukaar.adapters.text_structuring_fewshot import FewShotTextStructurer
from Pukaar.models.domain import SyncQueueItem
from Pukaar.services.external_data import ExternalDataService


llm_client = OpenAICompatibleLLM()
text_structurer = FewShotTextStructurer(llm_client)
image_assessor = PukaarAIImageAssessmentAdapter()
asr_client = FasterWhisperASRAdapter()
external_data_service = ExternalDataService()

is_online = True


def get_decision_runtime() -> OpenAICompatibleLLM:
    """Runtime used for alert reasoning and actuator tool selection."""
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

