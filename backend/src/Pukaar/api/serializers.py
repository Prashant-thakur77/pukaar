from __future__ import annotations

import json
from typing import Any

from Pukaar.models.domain import HydrometSnapshot, Site
from Pukaar.schemas.api import ExternalSnapshotResponse


def site_payload(site: Site) -> dict[str, Any]:
    return site.model_dump()


def parse_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def serialize_external_snapshot(snapshot: HydrometSnapshot) -> ExternalSnapshotResponse:
    return ExternalSnapshotResponse(
        site_id=snapshot.site_id,
        signal_score=snapshot.signal_score,
        summary=snapshot.summary,
        precipitation_mm=snapshot.precipitation_mm,
        precipitation_probability=snapshot.precipitation_probability,
        river_discharge=snapshot.river_discharge,
        river_discharge_max=snapshot.river_discharge_max,
        river_discharge_trend=snapshot.river_discharge_trend,
    )

