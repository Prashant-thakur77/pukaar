from __future__ import annotations

from Pukaar.adapters.asr import FasterWhisperASRAdapter
from Pukaar.adapters.image_assessment import PukaarAIImageAssessmentAdapter
from Pukaar.adapters.llm import OpenAICompatibleLLM
from Pukaar.adapters.text_structuring_fewshot import FewShotTextStructurer
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
