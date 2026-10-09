"""Structured JSON logs and CloudWatch embedded-metric-format (EMF) metrics."""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        root = logging.getLogger("Pukaar")
        root.handlers = [handler]
        root.setLevel(logging.INFO)
        root.propagate = False
        _CONFIGURED = True
    return logging.getLogger(name if name.startswith("Pukaar") else f"Pukaar.{name}")


def log(logger: logging.Logger, msg: str, severity: int = logging.INFO, /, **fields: Any) -> None:
    logger.log(severity, msg, extra={"fields": fields})


def metric(name: str, value: float = 1.0, unit: str = "Count", **dimensions: str) -> None:
    """Emit one EMF metric line; CloudWatch turns it into a metric in namespace Pukaar."""
    record = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": "Pukaar",
                    "Dimensions": [sorted(dimensions)] if dimensions else [[]],
                    "Metrics": [{"Name": name, "Unit": unit}],
                }
            ],
        },
        name: value,
        **dimensions,
    }
    print(json.dumps(record), flush=True)
