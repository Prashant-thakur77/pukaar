from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from Pukaar.api.deps import enqueue_entity, external_data_service, get_decision_runtime
from Pukaar.api.serializers import serialize_external_snapshot, site_payload
from Pukaar.db.database import get_session
from Pukaar.models.domain import FusedAlert, HydrometSnapshot, Site, SiteExperimentalSettings
from Pukaar.schemas.api import ExternalSnapshotResponse, HistoricalContextUpsert, SiteExperimentalSettingsPayload
from Pukaar.services.decision_engine import recompute_site_alert
from Pukaar.services.historical_context import HistoricalContextDocument, retrieve_historical_context, upsert_historical_context


router = APIRouter(tags=["sites"])


def _get_or_create_experimental_settings(session: Session, site_id: str) -> SiteExperimentalSettings:
    settings = session.get(SiteExperimentalSettings, site_id)
    if settings is not None:
        return settings
    settings = SiteExperimentalSettings(site_id=site_id)
    session.add(settings)
    session.flush()
    return settings


@router.get("/sites")
async def get_sites(session: Session = Depends(get_session)) -> list[Site]:
    return session.exec(select(Site).order_by(Site.name)).all()


@router.post("/sites")
async def create_site(site: Site, session: Session = Depends(get_session)) -> Site:
    session.add(site)
    session.commit()
    session.refresh(site)
    return site


@router.get("/sites/{site_id}")
async def get_site(site_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    site = session.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site_payload(site)


@router.get("/sites/{site_id}/experimental-settings")
async def get_site_experimental_settings(
    site_id: str,
    session: Session = Depends(get_session),
) -> SiteExperimentalSettings:
    if not session.get(Site, site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    settings = _get_or_create_experimental_settings(session, site_id)
    session.commit()
    session.refresh(settings)
    return settings


@router.put("/sites/{site_id}/experimental-settings")
async def update_site_experimental_settings(
    site_id: str,
    payload: SiteExperimentalSettingsPayload,
    session: Session = Depends(get_session),
) -> SiteExperimentalSettings:
    if not session.get(Site, site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    settings = _get_or_create_experimental_settings(session, site_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(settings, key, value)
    settings.updated_at = datetime.utcnow()
    session.add(settings)
    session.commit()
    session.refresh(settings)
    return settings


@router.get("/sites/{site_id}/historical-context")
async def get_site_historical_context(
    site_id: str,
    water_level: float | None = None,
    query: str | None = None,
    limit: int = 3,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    if not session.get(Site, site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    limit = max(1, min(limit, 8))
    hits = retrieve_historical_context(site_id, current_level=water_level, query=query, limit=limit)
    return {
        "site_id": site_id,
        "enabled": _get_or_create_experimental_settings(session, site_id).historical_context_enabled,
        "mode": "edge-rag-sqlite-fts5",
        "query": query,
        "water_level": water_level,
        "hits": [hit.__dict__ for hit in hits],
    }


@router.post("/sites/{site_id}/historical-context")
async def create_site_historical_context(
    site_id: str,
    payload: HistoricalContextUpsert,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    if not session.get(Site, site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    hit = upsert_historical_context(
        HistoricalContextDocument(
            site_id=site_id,
            source=payload.source,
            title=payload.title,
            summary=payload.summary,
            threshold_level=payload.threshold_level,
            jurisdiction=payload.jurisdiction,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
            source_uri=payload.source_uri,
        )
    )
    return {"site_id": site_id, "stored": hit.__dict__}


@router.get("/sites/{site_id}/external-snapshot", response_model=ExternalSnapshotResponse)
async def get_latest_external_snapshot(site_id: str, session: Session = Depends(get_session)) -> ExternalSnapshotResponse:
    snapshot = session.exec(
        select(HydrometSnapshot)
        .where(HydrometSnapshot.site_id == site_id)
        .order_by(HydrometSnapshot.created_at.desc())
    ).first()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No hydromet snapshot stored for site")
    return serialize_external_snapshot(snapshot)


@router.post("/sites/{site_id}/external-snapshot/refresh", response_model=ExternalSnapshotResponse)
async def refresh_external_snapshot(site_id: str, session: Session = Depends(get_session)) -> ExternalSnapshotResponse:
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")

    try:
        snapshot = external_data_service.fetch_snapshot(site)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Hydromet refresh failed: {exc}") from exc

    session.add(snapshot)
    session.flush()
    enqueue_entity(session, "hydromet_snapshot", snapshot)
    alert: FusedAlert = recompute_site_alert(session, site_id, get_decision_runtime())
    session.flush()
    enqueue_entity(session, "fused_alert", alert)
    session.commit()
    session.refresh(snapshot)
    return serialize_external_snapshot(snapshot)

