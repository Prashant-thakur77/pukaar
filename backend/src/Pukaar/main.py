from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from Pukaar.api.routers import pukaar, alerts, cap, demo_inject, runtime, sites, sync, pukaar
from Pukaar.db.database import init_db
from Pukaar.services.storage import get_fixture_dir, get_upload_dir


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    get_upload_dir()
    get_fixture_dir().mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Pukaar API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

get_fixture_dir().mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(get_upload_dir())), name="uploads")
app.mount("/fixtures", StaticFiles(directory=str(get_fixture_dir())), name="fixtures")

for router in (
    runtime.router,
    sites.router,
    pukaar.router,
    pukaar.router,
    alerts.router,
    sync.router,
    cap.router,
):
    app.include_router(router, prefix="/api")

app.include_router(cap.router)

if demo_inject.demo_inject_enabled():
    app.include_router(demo_inject.router, prefix="/api")


# Backward-compatible aliases for older tests/scripts that import from main.py.
is_online = True

