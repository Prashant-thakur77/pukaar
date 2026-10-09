"""Lambda: slow work invoked asynchronously by the API (DLQ, no retries).

{"task": "process_report", "report_id"}       transcribe, structure, describe, verify
{"task": "replay", "speed_seconds_per_hour"}  walk the active replay scenario
"""

from __future__ import annotations

from typing import Any

from Pukaar.core.config import get_settings
from Pukaar.llm.bedrock import BedrockLLM
from Pukaar.services import replay, reports
from Pukaar.store.repo import get_repo
from Pukaar.workflow.client import get_workflow


def _llm() -> BedrockLLM | None:
    return BedrockLLM() if get_settings().llm_enabled else None


def run_task(event: dict[str, Any]) -> dict[str, Any]:
    task = event.get("task")
    if task == "process_report":
        r = reports.process(get_repo(), event["report_id"], _llm(), workflow=get_workflow())
        return {"report_id": r.id, "state": r.state}
    if task == "replay":
        st = replay.run(get_repo(), speed_seconds_per_hour=float(event.get("speed_seconds_per_hour", 2.0)),
                        workflow=get_workflow())
        return st.model_dump()
    raise ValueError(f"unknown task {task!r}")


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    return run_task(event)


def dispatch(event: dict[str, Any]) -> None:
    """Run a task in the background: async Lambda invoke in AWS, a thread locally."""
    s = get_settings()
    if s.is_local or not s.worker_function:
        import threading

        threading.Thread(target=run_task, args=(event,), daemon=True).start()
        return
    import json

    import boto3

    boto3.client("lambda", region_name=s.aws_region).invoke(
        FunctionName=s.worker_function, InvocationType="Event", Payload=json.dumps(event).encode())
