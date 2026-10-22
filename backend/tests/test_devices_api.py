"""The device and siren routes (api/routers/devices.py) and the public siren line: Cedar on every route,
judges see but never act, and no public answer carries an id, a number or a key."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from Pukaar.core import clock
from Pukaar.services import cap
from Pukaar.services.devices import shadow
from test_sirens import FakeShadow, add_real_siren, approved


@pytest.fixture()
def api(repo, monkeypatch):
    from Pukaar.api import auth
    from Pukaar.api.routers import agents, devices, officer, public
    from Pukaar.main import app

    for mod in (auth, devices, officer, public):
        monkeypatch.setattr(mod, "get_repo", lambda: repo)
    monkeypatch.setattr(agents, "get_repo", lambda: repo)
    agents._CACHE.clear()
    s = FakeShadow()
    shadow.set_client(s)
    client = TestClient(app)
    client.shadow = s  # type: ignore[attr-defined]
    yield client
    shadow.set_client(None)


def bearer(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_officer_sees_devices_and_may_act_a_judge_may_only_look(api, repo, frozen):
    o = api.get("/villages/thunag/devices", headers=bearer(api, "officer1")).json()
    assert {d["device_id"] for d in o["devices"]} >= {"siren-thunag-sim", "box-thunag-sim", "gauge-thunag-sim"}
    assert o["can"] == {"test_siren": True, "sound_siren": True, "stop_siren": True}
    assert all("sim_number" not in d for d in o["devices"])
    j = bearer(api, "judge")
    seen = api.get("/villages/thunag/devices", headers=j).json()
    assert seen["can"] == {"test_siren": False, "sound_siren": False, "stop_siren": False}
    for method, path, body in (("post", "/villages/thunag/sirens/sound", {"level": "warning"}),
                               ("post", "/villages/thunag/sirens/sound", {"level": "critical"}),
                               ("post", "/villages/thunag/sirens/stop", {}),
                               ("post", "/devices/siren-thunag-sim/test", {"kind": "silent"})):
        r = getattr(api, method)(path, json=body, headers=j)
        assert r.status_code == 403, (path, body, r.json())
    assert api.shadow.cmds() == []
    assert api.get("/devices", headers=j).status_code == 200


def test_a_pradhan_sees_and_sounds_only_their_own_village(api, repo, frozen):
    h = bearer(api, "pradhan_thunag")
    assert api.get("/villages/thunag/devices", headers=h).status_code == 200
    assert api.get("/villages/gohar/devices", headers=h).status_code == 403
    assert {d["village_id"] for d in api.get("/devices", headers=h).json()["devices"]} == {"thunag"}
    r = api.post("/villages/thunag/sirens/sound", json={"level": "warning", "reason": "water at the bridge"}, headers=h)
    assert r.status_code == 200 and r.json()["pattern"] == "W1"
    assert api.post("/villages/gohar/sirens/sound", json={"level": "warning"}, headers=h).status_code == 403
    # the pradhan may stop what they started
    assert api.post("/villages/thunag/sirens/stop", json={"reason": "false alarm"}, headers=h).json()["stopped"] == 1


def test_the_two_person_rule_over_the_api(api, repo, frozen):
    r = api.post("/villages/thunag/sirens/sound", json={"level": "critical", "reason": "evacuate"},
                 headers=bearer(api, "officer1"))
    assert r.status_code == 202 and r.json()["needs_second_officer"] is True
    rid = r.json()["request_id"]
    listed = api.get("/villages/thunag/devices", headers=bearer(api, "officer2")).json()["requests"]
    assert [q["request_id"] for q in listed] == [rid]
    same = api.post(f"/siren-requests/{rid}/confirm", headers=bearer(api, "officer1"))
    assert same.status_code == 409 and same.json()["detail"]["code"] == "same_officer"
    assert api.post(f"/siren-requests/{rid}/confirm", headers=bearer(api, "judge")).status_code == 403
    ok = api.post(f"/siren-requests/{rid}/confirm", headers=bearer(api, "officer2"))
    assert ok.status_code == 200 and ok.json()["pattern"] == "C1"
    audit = repo.list_audit(clock.iso(clock.now())[:10])
    assert any(a.action == "sound_siren_manual" and a.actor == "officer1" and "second officer officer2" in a.reason
               for a in audit)


def test_tests_audible_at_night_refused_and_the_sms_fallback_is_officer_only(api, repo, frozen):
    o = bearer(api, "officer1")
    night = api.post("/devices/siren-thunag-sim/test", json={"kind": "audible"}, headers=o)
    assert night.status_code == 403
    silent = api.post("/devices/siren-thunag-sim/test", json={"kind": "silent"}, headers=o)
    assert silent.status_code == 200 and silent.json()["pattern"] == "T1"
    assert api.post("/devices/siren-thunag-sim/test", json={"kind": "silent"}, headers=o).status_code == 429
    cmd_id = silent.json()["cmd_id"]
    sms = api.post("/devices/siren-thunag-sim/sms-fallback", json={"cmd_id": cmd_id}, headers=o)
    assert sms.status_code == 200 and sms.json()["text"].startswith("PKR1 siren-thunag-sim TT ")
    assert api.post("/devices/siren-thunag-sim/sms-fallback", json={"cmd_id": cmd_id},
                    headers=bearer(api, "pradhan_thunag")).status_code == 403
    assert api.post("/devices/siren-thunag-sim/sms-fallback", json={"cmd_id": cmd_id},
                    headers=bearer(api, "judge")).status_code == 403


def test_alert_detail_carries_the_siren_tier(api, repo, frozen):
    a = approved(repo)
    from Pukaar.services import sirens

    sirens.sound_for_alert(repo, a)
    detail = api.get(f"/alerts/{a.id}", headers=bearer(api, "officer1")).json()
    assert detail["sirens"]["total"] == 1 and detail["sirens"]["rows"][0]["status"] == "commanded"
    assert api.get(f"/alerts/{a.id}/sirens", headers=bearer(api, "officer1")).json()["pattern"] == "W1"


def test_public_pages_show_the_siren_line_and_devices_without_ids_numbers_or_keys(api, repo, frozen):
    add_real_siren(repo, sim_number="+919800000099",
                   last_test_silent={"at": clock.iso(clock.now() - timedelta(days=2)), "ok": True})
    line = api.get("/villages/thunag").json()["sirens"]
    assert line == {"count": 2, "sounding": 0, "last_test_at": clock.iso(clock.now() - timedelta(days=2)),
                    "last_test_ok": True, "overdue": True, "simulated": False}
    assert api.get("/villages/gohar").json()["sirens"] is None
    board = api.get("/sensors").json()
    devices = {d["device_id"]: d for d in board["devices"]}
    assert "siren-thunag-01" in devices and devices["box-thunag-sim"]["health"] == "unknown"
    text = json.dumps(board) + json.dumps(api.get("/villages/thunag").json())
    for secret in ("+919800000099", "lora_addr", "owner_recipient_id", "pending_cmd", "sim_number"):
        assert secret not in text, secret


def test_cap_names_the_siren_pattern_only_for_installed_sirens(repo, frozen, tmp_path, monkeypatch):
    from Pukaar.core.config import get_settings

    a = repo.update_alert(approved(repo).id, siren_pattern="W1", status="delivered")
    v = repo.get_village("thunag")
    plain = cap.render(a, v, sender="s", web_url="https://x").decode()
    assert "PukaarSirenPattern" not in plain  # only a simulator is registered: nothing installed
    xml = cap.render(a, v, sender="s", web_url="https://x", installed_sirens=1).decode()
    assert "<valueName>PukaarSirenPattern</valueName>" in xml and "<value>W1</value>" in xml
    assert "तीन लंबी आवाज़ें = चेतावनी" in xml and "three long blasts = warning" in xml
    assert "<resource>" not in xml  # no clip catalog yet
    catalog = tmp_path / "siren_clips"
    catalog.mkdir()
    (catalog / "catalog.json").write_text(json.dumps({"clips": [
        {"clip_id": "thunag.warning.hi.v1", "bytes": 312345, "sha1": "a" * 40, "sha256": "b" * 64,
         "uri": "https://example.org/audio/sirens/thunag.warning.hi.v1.mp3"}]}), encoding="utf-8")
    monkeypatch.setenv("PUKAAR_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        with_clip = cap.render(a, v, sender="s", web_url="https://x", installed_sirens=1).decode()
    finally:
        monkeypatch.delenv("PUKAAR_DATA_DIR")
        get_settings.cache_clear()
    assert "<mimeType>audio/mpeg</mimeType>" in with_clip and "<size>312345</size>" in with_clip
    assert f"<digest>{'a' * 40}</digest>" in with_clip
    watch = repo.update_alert(approved(repo, "watch").id, siren_pattern=None, status="delivered")
    assert "PukaarSirenPattern" not in cap.render(watch, v, sender="s", web_url="https://x", installed_sirens=1).decode()
    drill = repo.update_alert(approved(repo, trace={"drill": True}).id, siren_pattern="D1", status="delivered")
    drill_xml = cap.render(drill, v, sender="s", web_url="https://x", installed_sirens=1).decode()
    assert "<status>Exercise</status>" in drill_xml and "<note>" in drill_xml  # the Exercise note is kept
