"""The small village answer (GET /public/villages/{id}/now) and gzip on every larger response."""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def client():
    from Pukaar.main import app

    return TestClient(app)


def test_now_is_small_public_and_cached(client):
    r = client.get("/public/villages/gohar/now", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["cache-control"].startswith("public, max-age=30")
    body = r.json()
    assert body["id"] == "gohar" and body["name_hi"] == "गोहर"
    assert body["level"] in {"normal", "watch", "warning", "critical"}
    assert body["means"]["hi"] and body["means"]["en"]
    assert 1 <= len(body["actions"]) <= 3
    assert all(a["hi"] and a["en"] for a in body["actions"])
    assert len(body["river"]["points"]) <= 96
    # Gohar has baked safe places: the first open route's place, with its walking time.
    place = body["safe_place"]
    assert place and place["name"] and isinstance(place["walk_min"], int)
    assert set(body) >= {"level_since", "checked_at", "data_status", "generated_at", "level_known"}
    # About 2 kB on the wire, a long way under the full detail.
    raw = json.dumps(body, ensure_ascii=False).encode()
    assert len(gzip.compress(raw)) < 3000


def test_now_unknown_village_is_404(client):
    assert client.get("/public/villages/atlantis/now").status_code == 404


def test_now_never_says_normal_without_data(client):
    from Pukaar.store.repo import get_repo

    repo = get_repo()
    before = repo.get_village("thunag")
    try:
        repo.update_village("thunag", level="normal", data_status="unavailable")
        body = client.get("/public/villages/thunag/now").json()
        assert body["level"] == "normal" and body["level_known"] is False
        assert "भरोसा न करें" in body["actions"][0]["hi"]
    finally:
        repo.update_village("thunag", level=before.level, data_status=before.data_status)


@pytest.mark.parametrize("level", ["watch", "warning", "critical"])
def test_now_actions_follow_the_level(client, level):
    from Pukaar.store.repo import get_repo
    from Pukaar.templates import actions

    repo = get_repo()
    before = repo.get_village("pandoh")
    try:
        repo.update_village("pandoh", level=level, data_status="ok")
        body = client.get("/public/villages/pandoh/now").json()
        assert body["level"] == level and body["level_known"] is True
        assert body["actions"] == actions.ACTIONS[level]
    finally:
        repo.update_village("pandoh", level=before.level, data_status=before.data_status)


def test_decimate_keeps_ends_and_caps_points():
    from Pukaar.api.routers.status import _decimate

    pts = [[str(i), float(i)] for i in range(300)]
    out = _decimate(pts, 96)
    assert len(out) == 96 and out[0] == pts[0] and out[-1] == pts[-1]
    assert _decimate(pts[:10], 96) == pts[:10]


def test_large_responses_are_gzipped_only_when_asked(client):
    zipped = client.get("/villages/gohar", headers={"Accept-Encoding": "gzip"})
    assert zipped.headers.get("content-encoding") == "gzip"
    assert zipped.json()["village"]["id"] == "gohar"  # the client decodes it
    plain = client.get("/villages/gohar", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers
    # Small bodies are not worth a gzip header.
    small = client.get("/replay/status", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in small.headers


def test_event_streams_are_never_buffered_for_gzip():
    """Server-sent events must reach the browser as they are written: GZipMiddleware leaves them alone."""
    from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES

    from Pukaar.main import app

    assert any(m.cls.__name__ == "GZipMiddleware" for m in app.user_middleware)
    assert "text/event-stream" in DEFAULT_EXCLUDED_CONTENT_TYPES


def test_now_route_is_public_in_the_stack():
    """Without its own route the HTTP API sends it to the Cognito authorizer and a villager gets 401."""
    template = (ROOT / "infra" / "template.yaml").read_text(encoding="utf-8")
    assert re.search(r'Path: "/public/villages/\{id\}/now", Method: GET, Auth: \{ Authorizer: NONE \}', template)


def test_web_app_keeps_the_same_action_lines():
    """The web app's offline copy (frontend/src/lib/actions.ts) says exactly what the API says."""
    from Pukaar.templates import actions

    ts = (ROOT / "frontend" / "src" / "lib" / "actions.ts").read_text(encoding="utf-8")
    for line in actions.all_lines():
        assert json.dumps(line["hi"], ensure_ascii=False) in ts, line["hi"]
        assert json.dumps(line["en"], ensure_ascii=False) in ts, line["en"]
