from __future__ import annotations

from io import BytesIO
from pathlib import Path

import anyio
import httpx
import pytest
from fastapi import BackgroundTasks, UploadFile
from sqlmodel import Session, SQLModel, select

from Pukaar.api import deps
from Pukaar.api.routers.pukaar import create_report
from Pukaar.core import settings as settings_module
from Pukaar.db.database import edge_engine, init_db
from Pukaar.main import app
from Pukaar.models.domain import FusedAlert, Site, VolunteerReport
from Pukaar.models.domain import HydrometSnapshot
from Pukaar.services.storage import get_upload_dir

init_db()


async def api_request(method: str, url: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, **kwargs)



def request(method: str, url: str, **kwargs) -> httpx.Response:
    async def _call() -> httpx.Response:
        return await api_request(method, url, **kwargs)

    return anyio.run(_call)


@pytest.fixture(autouse=True)
def reset_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PUKAAR_UPLOAD_DIR", str(tmp_path / "uploads"))
    settings_module.get_settings.cache_clear()
    deps.is_online = True
    monkeypatch.setattr(deps.llm_client, "structure_observation", lambda *_args, **_kwargs: None)

    with Session(edge_engine) as session:
        for table in reversed(SQLModel.metadata.sorted_tables):
            session.exec(table.delete())
        session.commit()

    upload_dir = get_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    for file_path in upload_dir.iterdir():
        if file_path.is_file():
            file_path.unlink()

    with Session(edge_engine) as session:
        session.add(
            Site(
                id="test-site",
                name="Puente Test",
                region="Zona Demo",
                lat=-32.95,
                lng=-60.64,
                description="Sitio usado para pruebas",
                is_active=True,
            )
        )
        session.commit()

    yield

    for file_path in upload_dir.iterdir():
        if file_path.is_file():
            file_path.unlink()




def test_health():
    response = request("GET", "/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"



def test_connectivity():
    response = request("POST", "/api/settings/connectivity", json={"is_online": False})
    assert response.status_code == 200
    assert response.json() == {"is_online": False}

    response = request("POST", "/api/settings/connectivity", json={"is_online": True})
    assert response.status_code == 200
    assert response.json() == {"is_online": True}



def test_report_creates_alert():
    async def run_flow():
        with Session(edge_engine) as edge_session:
            payload = await create_report(
                background_tasks=BackgroundTasks(),
                site_id="test-site",
                reporter_name="Test User",
                reporter_role="Tester",
                transcript_text="El agua paso la marca critica y la calle esta cortada",
                offline_created=True,
                photo=None,
                audio=None,
                session=edge_session,
            )
            report_id = payload["report"].id
            assert payload["parsed"].parser_source == "rules"
            assert payload["alert"].level in {"orange", "red"}
            return report_id

    report_id = anyio.run(run_flow)

    with Session(edge_engine) as session:
        report = session.get(VolunteerReport, report_id)
        assert report is not None
        assert report.offline_created is True
        alert = session.exec(select(FusedAlert)).first()
        assert alert is not None
        assert alert.site_id == "test-site"



def test_report_uploads_are_persisted():
    async def run_flow():
        photo = UploadFile(filename="river.jpg", file=BytesIO(b"fake-image-bytes"))
        audio = UploadFile(filename="note.wav", file=BytesIO(b"fake-audio-bytes"))
        with Session(edge_engine) as edge_session:
            return await create_report(
                background_tasks=BackgroundTasks(),
                site_id="test-site",
                reporter_name="Upload User",
                reporter_role="Tester",
                transcript_text="Foto y audio cargados",
                offline_created=False,
                photo=photo,
                audio=audio,
                session=edge_session,
            )

    payload = anyio.run(run_flow)["report"]
    photo_path = Path(payload.photo_path)
    audio_path = Path(payload.audio_path)
    assert photo_path.exists()
    assert audio_path.exists()
    assert photo_path.parent == get_upload_dir()
    assert audio_path.parent == get_upload_dir()



def test_external_snapshot_refresh_serializes_response(monkeypatch: pytest.MonkeyPatch):
    snapshot = HydrometSnapshot(
        site_id="test-site",
        signal_score=0.42,
        summary="rain now 2.0 mm, 12h precip prob 60%",
        precipitation_mm=2.0,
        precipitation_probability=60.0,
        river_discharge=12.0,
        river_discharge_max=18.0,
        river_discharge_trend=1.5,
    )

    monkeypatch.setattr(deps.external_data_service, "fetch_snapshot", lambda _site: snapshot)

    response = request("POST", "/api/sites/test-site/external-snapshot/refresh")
    assert response.status_code == 200
    payload = response.json()
    assert payload["site_id"] == "test-site"
    assert payload["signal_score"] == 0.42
    assert payload["summary"] == "rain now 2.0 mm, 12h precip prob 60%"


def test_site_experimental_settings_and_historical_context():
    response = request("PUT", "/api/sites/test-site/experimental-settings", json={
        "historical_context_enabled": True,
        "forecast_enabled": True,
        "forecast_critical_threshold": 0.7,
    })
    assert response.status_code == 200
    assert response.json()["historical_context_enabled"] is True

    response = request("POST", "/api/sites/test-site/historical-context", json={
        "source": "manual",
        "title": "Bridge access road",
        "summary": "At 0.69 the bridge access road floods before the main crossing.",
        "threshold_level": 0.69,
        "jurisdiction": "municipal",
        "source_uri": "manual://bridge-access",
    })
    assert response.status_code == 200
    stored = response.json()["stored"]
    assert stored["source_uri"] == "manual://bridge-access"

    response = request("GET", "/api/sites/test-site/historical-context?water_level=0.68&query=bridge")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["hits"]
    assert payload["hits"][0]["id"] == stored["id"]
