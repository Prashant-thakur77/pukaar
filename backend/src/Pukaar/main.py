"""FastAPI app. In AWS it runs in the api Lambda behind the Lambda Web Adapter."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from Pukaar.core.config import get_settings

settings = get_settings()
if settings.is_local:
    from Pukaar.core.local import start_local_aws

    start_local_aws()

from Pukaar.api.routers import officer, public, reports, telegram  # noqa: E402  (after the local mock starts)

app = FastAPI(title="Pukaar API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins) + (["http://localhost:4173", "http://127.0.0.1:5173"] if settings.is_local else []),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["authorization", "content-type"],
)
for r in (public.router, reports.router, officer.router, telegram.router):
    app.include_router(r)
