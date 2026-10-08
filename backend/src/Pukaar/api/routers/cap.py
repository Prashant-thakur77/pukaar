from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from Pukaar.services.cap import build_cap_xml


router = APIRouter(tags=["cap"])


class CapEmitRequest(BaseModel):
    site_id: str = "demo-site"
    lat: float = Field(default=-34.6037, ge=-90, le=90)
    lon: float = Field(default=-58.3816, ge=-180, le=180)
    severity: str = "minor"
    headline: str = "Alerta preventiva por posible inundacion"
    instruction: str = "Monitorear el area y validar con Defensa Civil antes de difusion publica."
    summary: str = "Senales locales indican riesgo hidrometeorologico."
    areaDesc: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


@router.post("/cap/emit")
async def emit_cap(payload: CapEmitRequest) -> Response:
    event = payload.model_dump(exclude={"extra"})
    event.update(payload.extra)
    xml = build_cap_xml(event)
    return Response(content=xml, media_type="application/cap+xml")
