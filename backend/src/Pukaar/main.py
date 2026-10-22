"""FastAPI app. In AWS it runs in the api Lambda behind the Lambda Web Adapter."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from Pukaar.core.config import get_settings

settings = get_settings()
if settings.is_local:
    from Pukaar.core.local import start_local_aws

    start_local_aws()

from Pukaar.api.routers import (  # noqa: E402  (after the local mock starts)
    agents, devices, gauges, officer, public, push, reports, rollcall, sensors, telegram, voice,
)

app = FastAPI(title="Pukaar API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins) + (["http://localhost:4173", "http://127.0.0.1:5173"] if settings.is_local else []),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["authorization", "content-type"],
)


@app.middleware("http")
async def edge_only(request, call_next):
    """Prod behind CloudFront and AWS WAF: refuse requests that did not come through CloudFront (api/edge.py)."""
    from fastapi.responses import JSONResponse

    from Pukaar.api import edge

    if not edge.allowed(request.url.path, request.headers):
        return JSONResponse({"detail": {"code": "edge_only", "reason": "use the API's public address"}},
                            status_code=403)
    return await call_next(request)


for r in (public.router, reports.router, officer.router, telegram.router, sensors.router, rollcall.router, agents.router,
          gauges.router, push.router, voice.router, devices.router):
    app.include_router(r)
