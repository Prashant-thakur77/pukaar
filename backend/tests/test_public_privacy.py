"""No personal data on any route that needs no sign-in.

Walks every GET route of the app, calls it signed out, and fails if a public answer carries a
villager's exact GPS, words, voice or photo link, name, tracking code, phone number or chat id.
Officer routes (401/403 signed out) keep the full detail under Cedar.
"""

from __future__ import annotations

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

# Anywhere in a public answer.
FORBIDDEN_ANYWHERE = {"phone", "phone_number", "mobile", "chat_id", "recipient_id", "reporter_name", "audio_key",
                      "photo_key", "audio_url", "media", "masked_text", "officers"}
# Inside anything that describes a villager's report.
FORBIDDEN_IN_REPORT = {"lat", "lon", "photo_url", "audio_url", "photo", "text", "transcript", "summary_en",
                       "reply_hi", "track_code", "photo_description", "verified_by"}
CHAT_ID = "4242424242"
REPORT_GPS = (31.71135, 76.52491)


def _walk(value, path="$"):
    if isinstance(value, dict):
        report_like = "report_type" in value or "report_id" in value and "severity" in value
        for k, v in value.items():
            yield path, k, report_like
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk(v, f"{path}[{i}]")


@pytest.fixture(scope="module")
def seeded():
    from Pukaar.core import clock
    from Pukaar.core.ids import new_id
    from Pukaar.main import app
    from Pukaar.store.models import Alert, Delivery, Recipient
    from Pukaar.store.repo import get_repo

    client = TestClient(app)
    r = client.post("/reports", data={"village_id": "sujanpur", "text": "pani ghar mein, Ramesh 9876543210",
                                      "lat": str(REPORT_GPS[0]), "lon": str(REPORT_GPS[1]),
                                      "reporter_name": "Ramesh Kumar"},
                    files={"photo": ("p.jpg", b"\xff\xd8\xff", "image/jpeg"),
                           "audio": ("a.webm", b"\x1a\x45\xdf\xa3", "audio/webm")})
    assert r.status_code == 200, r.text
    report, code = r.json()["report"], r.json()["track_code"]
    repo = get_repo()
    repo.put_recipient(Recipient(id=CHAT_ID, village_id="sujanpur", name="Ramesh Kumar", channel="telegram"))
    stamp = clock.iso(clock.now())
    alert = Alert(id=new_id("alr"), village_id="sujanpur", village_name="Sujanpur", village_name_hi="सुजानपुर",
                  level="warning", status="delivered", approved=True, created_at=stamp, updated_at=stamp,
                  decision_trace={"rules_fired": ["verified_reports:warning"],
                                  "evidence": [{"kind": "report", "report_id": report["id"], "type": "water_rising",
                                                "severity": "high", "state": "verified", "at": stamp}]})
    repo.put_alert(alert)
    repo.put_delivery(Delivery(alert_id=alert.id, recipient_id=CHAT_ID, name="Ramesh Kumar", channel="telegram",
                               status="sent", sent_at=stamp))
    return {"client": client, "app": app, "report_id": report["id"], "code": code, "alert_id": alert.id}


def _fill(path: str, seeded: dict) -> str | None:
    values = {"village_id": "sujanpur", "alert_id": seeded["alert_id"], "code": seeded["code"],
              "report_id": seeded["report_id"]}
    missing = [p for p in re.findall(r"{([^}:]+)(?::[^}]*)?}", path) if p not in values]
    if missing:
        return None  # signed-token or opaque-id routes (/approval/{token}, /safe/{token}, /media/{key})
    return re.sub(r"{([^}:]+)(?::[^}]*)?}", lambda m: str(values[m.group(1)]), path)


def test_every_public_route_is_free_of_personal_data(seeded):
    client, checked = seeded["client"], []
    for route in seeded["app"].routes:
        if not isinstance(route, APIRoute) or "GET" not in route.methods:
            continue
        url = _fill(route.path, seeded)
        if url is None:
            continue
        r = client.get(url)
        if r.status_code in {401, 403, 404} or not r.headers.get("content-type", "").startswith("application/json"):
            continue  # officer route, or not JSON (CAP XML has no report data)
        assert r.status_code == 200, (url, r.status_code, r.text[:200])
        body = r.json()
        checked.append(route.path)
        text = r.text
        assert CHAT_ID not in text, url
        assert "Ramesh" not in text and "9876543210" not in text, url
        assert str(REPORT_GPS[0]) not in text and str(REPORT_GPS[1]) not in text, url
        for where, key, report_like in _walk(body):
            assert key not in FORBIDDEN_ANYWHERE, f"{url}: {where}.{key}"
            if report_like:
                assert key not in FORBIDDEN_IN_REPORT, f"{url}: {where}.{key} inside a report"
    # the walk really covered the public pages
    for p in ("/villages", "/villages/{village_id}", "/public/overview", "/public/pilot-metrics", "/track/{code}",
              "/agents/traces",
              "/sensors", "/villages/{village_id}/safe-places", "/directives"):
        assert p in checked, p


def test_public_village_page_keeps_the_coarse_facts(seeded):
    detail = seeded["client"].get("/villages/sujanpur").json()
    rep = next(x for x in detail["reports"] if x["id"] == seeded["report_id"])
    assert {"report_type", "severity", "created_at", "state", "held"} <= set(rep)
    assert rep["has_location"] is True and rep["has_photo"] is True and rep["has_audio"] is True
    assert "officers" not in detail["village"] and "data_status" in detail["village"]


def test_officers_still_see_full_report_detail_under_cedar(seeded):
    client = seeded["client"]
    h = {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": "officer1"}).json()["token"]}
    full = next(x for x in client.get("/reports?village_id=sujanpur", headers=h).json() if x["id"] == seeded["report_id"])
    assert full["lat"] == REPORT_GPS[0] and full["photo_url"] and full["audio_url"]
    assert client.get("/reports?village_id=sujanpur").status_code == 401
