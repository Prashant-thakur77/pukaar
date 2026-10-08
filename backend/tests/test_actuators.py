from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, SQLModel

from Pukaar.api import deps
from Pukaar.core import settings as settings_module
from Pukaar.db.database import central_engine, edge_engine, init_db
from Pukaar.models.domain import FusedAlert, Site
from Pukaar.services import actuators as actuators_module
from Pukaar.services.actuators import (
    RECORDED_CALLS,
    dispatch_actuators,
    reset_recorded_calls,
)
from Pukaar.services.storage import get_upload_dir


init_db()


@pytest.fixture(autouse=True)
def _reset_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PUKAAR_UPLOAD_DIR", str(tmp_path / "uploads"))
    settings_module.get_settings.cache_clear()
    deps.is_online = True
    for engine in (edge_engine, central_engine):
        with Session(engine) as session:
            for table in reversed(SQLModel.metadata.sorted_tables):
                session.exec(table.delete())
            session.commit()
    upload_dir = get_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    with Session(edge_engine) as session:
        session.add(
            Site(
                id="test-site",
                name="Test Site",
                region="Demo",
                lat=-32.95,
                lng=-60.64,
                description="for tests",
                is_active=True,
            )
        )
        session.commit()
    reset_recorded_calls()
    yield
    settings_module.get_settings.cache_clear()


def _make_alert(level: str = "red") -> FusedAlert:
    return FusedAlert(
        site_id="test-site",
        level=level,
        score=0.95,
        trigger_source="volunteer",
        summary="agua paso la marca, ruta cortada",
        decision_trace="[]",
        local_alarm_triggered=True,
        reasoning_summary="...",
        reasoning_chain="[]",
        reasoning_model="pukaar-model:2b",
    )


class _FakeResponse:
    def __init__(self, json_body: dict[str, Any], status_code: int = 200):
        self._json = json_body
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """Drop-in replacement for httpx.Client that returns a pre-baked response."""

    def __init__(self, response: _FakeResponse | None = None, raise_on_post: Exception | None = None):
        self._response = response
        self._raise = raise_on_post
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc) -> None:  # noqa: ANN001
        return None

    def post(self, url: str, json: dict[str, Any] | None = None) -> _FakeResponse:
        self.posts.append((url, json or {}))
        if self._raise:
            raise self._raise
        assert self._response is not None
        return self._response


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, fake: _FakeClient) -> None:
    monkeypatch.setattr(actuators_module.httpx, "Client", lambda **_kw: fake)


def test_dispatch_disabled_returns_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PUKAAR_ACTUATORS_ENABLED", "false")
    settings_module.get_settings.cache_clear()

    _install_fake_client(
        monkeypatch,
        _FakeClient(response=_FakeResponse({"message": {"tool_calls": []}})),
    )

    fired = dispatch_actuators(_make_alert(), deps.llm_client)
    assert fired == []
    assert RECORDED_CALLS == []


def test_dispatch_fires_single_tool_call(monkeypatch: pytest.MonkeyPatch):
    response = _FakeResponse(
        {
            "message": {
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "trigger_alarm",
                            "arguments": {"reason": "agua sobre la calle"},
                        },
                    }
                ]
            }
        }
    )
    _install_fake_client(monkeypatch, _FakeClient(response=response))

    fired = dispatch_actuators(_make_alert(), deps.llm_client)
    assert fired == ["trigger_alarm"]
    assert RECORDED_CALLS == [("trigger_alarm", {"reason": "agua sobre la calle"})]


def test_dispatch_fires_multiple_tool_calls(monkeypatch: pytest.MonkeyPatch):
    response = _FakeResponse(
        {
            "message": {
                "tool_calls": [
                    {"function": {"name": "trigger_alarm", "arguments": {"reason": "rojo"}}},
                    {"function": {"name": "notify_app", "arguments": {"text": "evacuar zona baja"}}},
                ]
            }
        }
    )
    _install_fake_client(monkeypatch, _FakeClient(response=response))

    fired = dispatch_actuators(_make_alert(), deps.llm_client)
    assert fired == ["trigger_alarm", "notify_app"]
    assert len(RECORDED_CALLS) == 2
    names = [name for name, _ in RECORDED_CALLS]
    assert names == ["trigger_alarm", "notify_app"]


def test_dispatch_no_tool_calls_returns_empty(monkeypatch: pytest.MonkeyPatch):
    response = _FakeResponse({"message": {"content": "no tools needed", "tool_calls": []}})
    _install_fake_client(monkeypatch, _FakeClient(response=response))

    fired = dispatch_actuators(_make_alert(), deps.llm_client)
    assert fired == []
    assert RECORDED_CALLS == []


def test_dispatch_transport_error_returns_empty(monkeypatch: pytest.MonkeyPatch):
    _install_fake_client(monkeypatch, _FakeClient(raise_on_post=RuntimeError("boom")))

    fired = dispatch_actuators(_make_alert(), deps.llm_client)
    assert fired == []
    assert RECORDED_CALLS == []


def test_dispatch_unknown_tool_name_ignored(monkeypatch: pytest.MonkeyPatch):
    response = _FakeResponse(
        {
            "message": {
                "tool_calls": [
                    {"function": {"name": "trigger_alarm", "arguments": {"reason": "ok"}}},
                    {"function": {"name": "launch_nukes", "arguments": {}}},
                ]
            }
        }
    )
    _install_fake_client(monkeypatch, _FakeClient(response=response))

    fired = dispatch_actuators(_make_alert(), deps.llm_client)
    assert fired == ["trigger_alarm"]
