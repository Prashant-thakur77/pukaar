"""Pages the duty officer when a CloudWatch alarm fires: the worker Lambda is subscribed to the alarm topic
(infra/template.yaml) and hands SNS events here (handlers/worker.handler).

E-mail alone wakes nobody at 03:00. Every record on the topic (ALARM, and OK when it clears) goes to the
primary and backup officer on duty, on Telegram and Web Push (services/duty.page_alarm). Never raises:
a page that fails is logged, and the e-mail subscription still carries the alarm.
"""

from __future__ import annotations

from typing import Any

from Pukaar.core.log import get_logger, log
from Pukaar.services import duty
from Pukaar.store.repo import get_repo

_LOG = get_logger("handler.pager")


def handler(event: dict[str, Any] | None = None, context: Any = None) -> dict[str, Any]:
    results = []
    for record in (event or {}).get("Records") or []:
        message = ((record or {}).get("Sns") or {}).get("Message") or ""
        try:
            results.append(duty.page_alarm(get_repo(), message))
        except Exception as exc:
            log(_LOG, "page failed", 40, error=str(exc)[:300])
            results.append({"error": type(exc).__name__})
    return {"pages": results}
