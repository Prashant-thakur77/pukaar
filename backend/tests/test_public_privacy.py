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
                      "photo_key", "audio_url", "media", "masked_text", "officers",
                      # officer usernames on an alert (views.public_alert)
                      "decided_by", "officer_chain", "officers_asked", "all_clear_by", "outcome_by", "issued_by"}
# Usernames that did something on the seeded records; none may appear on a public page (views.scrub_people).
STAFF_USERNAMES = ("dso_privacy_primary", "dso_privacy_backup", "pradhan_privacy")
# Inside anything that describes a villager's report.
FORBIDDEN_IN_REPORT = {"lat", "lon", "photo_url", "audio_url", "photo", "text", "transcript", "summary_en",
                       "reply_hi", "track_code", "photo_description", "verified_by"}
CHAT_ID = "4242424242"
VOICE_PHONE = "+919812300077"  # a voice-call recipient's number (delivery/voice.py)
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
    repo.put_recipient(Recipient(id=CHAT_ID, village_id="sujanpur", name="Ramesh Kumar", channel="both",
                                 phone=VOICE_PHONE, consent="test"))
    repo.put_recipient(Recipient(id="v_privacytest", village_id="sujanpur", name="Ramesh Voice", channel="voice",
                                 phone="+919812300088", consent="test"))
    stamp = clock.iso(clock.now())
    primary, backup, pradhan = STAFF_USERNAMES
    alert = Alert(id=new_id("alr"), village_id="sujanpur", village_name="Sujanpur", village_name_hi="सुजानपुर",
                  level="warning", status="delivered", approved=True, created_at=stamp, updated_at=stamp,
                  decided_by=primary, decided_at=stamp, officer_chain=[primary, backup],
                  officer_chain_roles=["primary", "backup"], officers_asked=[primary, backup],
                  all_clear_by=backup, outcome="real_flood", outcome_by=primary, outcome_at=stamp,
                  decision_trace={"rules_fired": ["verified_reports:warning"],
                                  "evidence": [{"kind": "report", "report_id": report["id"], "type": "water_rising",
                                                "severity": "high", "state": "verified", "at": stamp}]})
    repo.put_alert(alert)
    # Everything else a person can do to a village, done by named staff.
    from Pukaar.services import checklist, safe_places
    from Pukaar.store.models import Directive, RoadBlock, ShelterStatus

    repo.put_directive(Directive(id=new_id("dir"), village_id="sujanpur", type="evacuate", text_hi="x", text_en="x",
                                 issued_by=primary, issued_at=stamp))
    checklist.set_done(repo, "sujanpur", sorted(checklist.ITEM_IDS)[0], True, pradhan, "pradhan")
    place = safe_places.baked_places("sujanpur")[0]
    repo.put_shelter(ShelterStatus(village_id="sujanpur", place_id=place["id"], status="OPEN", updated_by=pradhan,
                                   updated_at=stamp))
    repo.put_roadblock(RoadBlock(id=new_id("rb"), village_id="sujanpur", lat=place["lat"], lon=place["lon"],
                                 note="bridge down", created_by=backup, created_at=stamp, renewed_by=primary,
                                 renewed_at=stamp, expires_at="2099-01-01T00:00:00Z"))
    v = repo.get_village("sujanpur")
    if v.gauge is not None:
        repo.update_village("sujanpur", gauge={**v.gauge.model_dump(), "thresholds_set_by": primary})
    repo.put_delivery(Delivery(alert_id=alert.id, recipient_id=CHAT_ID, name="Ramesh Kumar", channel="telegram",
                               status="sent", sent_at=stamp))
    repo.put_delivery(Delivery(alert_id=alert.id, recipient_id=CHAT_ID, name="Ramesh Kumar", channel="voice",
                               status="acknowledged", sent_at=stamp, acknowledged_at=stamp, provider="exotel",
                               call_ids=["exo-privacy-call"], digit="1"))
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
        assert "9812300077" not in text and "9812300088" not in text and "v_privacytest" not in text, url
        assert "exo-privacy-call" not in text, url
        assert "Ramesh" not in text and "9876543210" not in text, url
        assert str(REPORT_GPS[0]) not in text and str(REPORT_GPS[1]) not in text, url
        for username in STAFF_USERNAMES:
            assert username not in text, (url, username)
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


def _bearer(client, username: str) -> dict:
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": username}).json()["token"]}


def test_a_public_alert_says_what_happened_not_which_officer(seeded):
    client = seeded["client"]
    detail = client.get("/villages/sujanpur").json()
    a = next(x for x in detail["alerts"] if x["id"] == seeded["alert_id"])
    assert a["approved"] is True and a["decided_by_role"] == "officer" and a["outcome"] == "real_flood"
    assert not {"decided_by", "officer_chain", "officers_asked", "all_clear_by", "outcome_by"} & set(a)
    assert all("issued_by" not in d for d in detail["directives"])
    # who ticked, set or marked something shows as "staff", so the page still reads naturally
    assert {i["done_by"] for i in detail["checklist"]["items"] if i["done"]} == {"staff"}
    places = client.get("/villages/sujanpur/safe-places").json()
    assert {p["ledger"]["updated_by"] for p in places["places"] if p["ledger"]["updated_by"]} == {"staff"}
    assert places["roadblocks"] and {(b["created_by"], b["renewed_by"]) for b in places["roadblocks"]} == {("staff", "staff")}
    # signed in, the console keeps who did what
    full = client.get(f"/alerts/{seeded['alert_id']}", headers=_bearer(client, "officer1")).json()["alert"]
    assert full["decided_by"] == STAFF_USERNAMES[0] and full["officer_chain"] == list(STAFF_USERNAMES[:2])


# -- the published demo password (README: judge, judge_pradhan) -----------------------------------
def _replay_report(village_id: str):
    from Pukaar.core import clock
    from Pukaar.core.ids import new_id
    from Pukaar.store.models import Report
    from Pukaar.store.repo import get_repo

    r = Report(id=new_id("rpt"), village_id=village_id, created_at=clock.iso(clock.now()), text="replay: water on road",
               lat=31.5, lon=76.9, replay=True)
    get_repo().put_report(r)
    return r


def test_demo_accounts_get_replay_reports_only_never_a_villagers_live_report(seeded):
    client = seeded["client"]
    replay_sujanpur, replay_thunag = _replay_report("sujanpur"), _replay_report("thunag")
    # a live report in judge_pradhan's own village
    live = client.post("/reports", data={"village_id": "thunag", "text": "Sita ka ghar doob raha", "lat": "31.6",
                                         "lon": "77.1", "reporter_name": "Sita Devi"}).json()["report"]
    judge = client.get("/reports", headers=_bearer(client, "judge"))
    assert judge.status_code == 200
    ids = {x["id"] for x in judge.json()}
    assert replay_sujanpur.id in ids and replay_thunag.id in ids
    assert seeded["report_id"] not in ids and live["id"] not in ids and all(x["replay"] for x in judge.json())
    assert "Ramesh" not in judge.text and str(REPORT_GPS[0]) not in judge.text and "Sita" not in judge.text
    one_village = client.get("/reports?village_id=sujanpur", headers=_bearer(client, "judge")).json()
    assert [x["id"] for x in one_village] == [replay_sujanpur.id]

    jp = client.get("/reports", headers=_bearer(client, "judge_pradhan"))
    assert jp.status_code == 200 and [x["id"] for x in jp.json()] == [replay_thunag.id]
    # another village is still refused outright
    assert client.get("/reports?village_id=sujanpur", headers=_bearer(client, "judge_pradhan")).status_code == 403

    # real staff are not affected: the officer and Thunag's pradhan see the live reports
    officer = {x["id"] for x in client.get("/reports", headers=_bearer(client, "officer1")).json()}
    assert {seeded["report_id"], live["id"], replay_sujanpur.id} <= officer
    pradhan = {x["id"] for x in client.get("/reports", headers=_bearer(client, "pradhan_thunag")).json()}
    assert live["id"] in pradhan and seeded["report_id"] not in pradhan


def test_demo_accounts_see_a_live_alert_but_not_who_it_reached(seeded):
    client, alert_id = seeded["client"], seeded["alert_id"]
    r = client.get(f"/alerts/{alert_id}", headers=_bearer(client, "judge"))
    assert r.status_code == 200
    rows = r.json()["deliveries"]
    assert rows and all(x["masked"] for x in rows)
    assert {x["status"] for x in rows} == {"sent", "acknowledged"}  # what happened stays
    assert "Ramesh" not in r.text and CHAT_ID not in r.text and "exo-privacy-call" not in r.text
    officer = client.get(f"/alerts/{alert_id}", headers=_bearer(client, "officer1")).json()["deliveries"]
    assert {x["name"] for x in officer} == {"Ramesh Kumar"} and not any(x.get("masked") for x in officer)
    # the after-action report names first names: live ones are refused to the demo account
    assert client.get(f"/alerts/{alert_id}/after-action", headers=_bearer(client, "judge")).status_code == 403
    assert client.get(f"/alerts/{alert_id}/after-action", headers=_bearer(client, "officer1")).status_code == 200
    # roll-call boards name villagers: the demo account's list holds replay ones only (there are none)
    rc = client.get("/rollcalls", headers=_bearer(client, "judge"))
    assert rc.status_code == 200 and rc.json() == []


def test_ask_pukaar_never_quotes_a_report_gps_or_a_recipient_name(seeded):
    client = seeded["client"]
    for question in ("How many reports came in?", "Which deliveries were never acknowledged?"):
        r = client.post("/ask/officer", json={"question": question}, headers=_bearer(client, "judge"))
        assert r.status_code == 200, r.text
        assert str(REPORT_GPS[0]) not in r.text and "Ramesh" not in r.text and CHAT_ID not in r.text
