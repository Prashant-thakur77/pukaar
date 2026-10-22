"""Lambda: the 15-minute sweep (EventBridge Scheduler, no retries, DLQ)."""

from __future__ import annotations

import time
from typing import Any

from Pukaar.core.log import get_logger, log, metric
from Pukaar.raahat import indexer as raahat_indexer
from Pukaar.services import gauge, model_probe, roster
from Pukaar.services.decision_engine import sweep_all
from Pukaar.store.repo import get_repo
from Pukaar.workflow.client import get_workflow

_LOG = get_logger("handler.sweep")


def handler(event: dict[str, Any] | None = None, context: Any = None) -> dict[str, Any]:
    started = time.monotonic()
    repo = get_repo()
    # Villages are evaluated concurrently (PUKAAR_SWEEP_CONCURRENCY at once); one village's error stays its own.
    results = sweep_all(repo, workflow=get_workflow())
    seconds = round(time.monotonic() - started, 1)
    # At most once every 6 hours: does this account have Bedrock model access yet? (never raises)
    model_probe.maybe_run(repo)
    # A district with no officer rostered for the current shift (IST): NobodyOnDuty, alarmed. Never raises.
    empty = roster.nobody_on_duty(repo)
    # Gauge health: silent, low battery or mostly bad readings -> GaugeUnhealthy (never raises).
    unhealthy = [h["village_id"] for h in gauge.health_scan(repo) if h["unhealthy"]]
    # Pukaar Raahat: copy the relief contracts' new events into the table (off without RAAHAT_*; never raises).
    raahat_index = raahat_indexer.run(repo)
    summary = {r.village_id: {"level": r.level, "raw": r.raw_level, "rose": r.rose, "alert_id": r.alert_id,
                              "skipped": r.skipped, "note": r.note} for r in results}
    errors = sum(1 for r in results if r.note.startswith("error"))
    log(_LOG, "sweep done", villages=len(results), errors=errors, seconds=seconds)
    metric("SweepSeconds", seconds)
    if errors < len(results):
        metric("SweepCompleted", 1)
    return {"villages": summary, "errors": errors, "nobody_on_duty": empty, "gauges_unhealthy": unhealthy,
            "raahat_index": raahat_index}
