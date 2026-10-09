"""Lambda: approval workflow steps, called by Step Functions with {"step": ...}."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from Pukaar.llm.bedrock import BedrockLLM
from Pukaar.store.repo import get_repo
from Pukaar.workflow.steps import Steps


@lru_cache(maxsize=1)
def _steps() -> Steps:
    llm = BedrockLLM()
    return Steps(get_repo(), llm if llm.settings.llm_enabled else None)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    return _steps().handle(event)
