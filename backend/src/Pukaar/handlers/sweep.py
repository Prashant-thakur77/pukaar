"""Lambda: the 15-minute sweep (EventBridge Scheduler, no retries, DLQ)."""

from __future__ import annotations

from typing import Any

from Pukaar.core.log import get_logger, log, metric
from Pukaar.services.decision_engine import sweep_all
from Pukaar.store.repo import get_repo
from Pukaar.workflow.client import get_workflow

_LOG = get_logger("handler.sweep")


def handler(event: dict[str, Any] | None = None, context: Any = None) -> dict[str, Any]:
    results = sweep_all(get_repo(), workflow=get_workflow())
    summary = {r.village_id: {"level": r.level, "raw": r.raw_level, "rose": r.rose, "alert_id": r.alert_id,
                              "skipped": r.skipped, "note": r.note} for r in results}
    errors = sum(1 for r in results if r.note.startswith("error"))
    log(_LOG, "sweep done", villages=len(results), errors=errors)
    if errors < len(results):
        metric("SweepCompleted", 1)
    return {"villages": summary, "errors": errors}
