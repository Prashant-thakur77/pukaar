"""Report-abuse protection (services/report_guard.py).

Before this, two forged reports with made-up GPS 300 m apart auto-verified each other and set the
village to Warning on the public site, and one script could use up the shared 5/s report throttle.
Now: corroboration needs an independent source and plausible GPS, rate limits hold (never drop)
the excess, and officers see a flag for a possible duplicate or flood of reports.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from Pukaar.api import views
from Pukaar.core import config
from Pukaar.services import report_guard as guard
from Pukaar.services import reports as svc
from Pukaar.store.models import ReportSource

from conftest import source_for

THUNAG = (31.5600, 77.1650)  # ~80 m from the published village point
PARTNER = (31.5630, 77.1650)  # ~330 m from THUNAG: close enough to corroborate


def _report(repo, *, at=THUNAG, name="a", source=None, text="log fanse hain, bachao"):
    return svc.intake(repo, repo.get_village("thunag"), text=text, lat=at[0], lon=at[1], reporter_name=name,
                      source=source)


def _both(repo, workflow, a, b):
    svc.process(repo, a.id, None, workflow=workflow)
    svc.process(repo, b.id, None, workflow=workflow)
    return repo.get_report(a.id), repo.get_report(b.id)


# -- forged pairs never raise a level -----------------------------------------------------------
def test_forged_pair_from_one_ip_does_not_verify_or_raise_the_level(repo, frozen, workflow):
    # One script, one IP; it even invents a new device and session id for each post.
    a = _report(repo, name="ram", source=source_for("ram", ip="203.0.113.9"))
    b = _report(repo, at=PARTNER, name="shyam", source=source_for("shyam", ip="203.0.113.9"))
    a, b = _both(repo, workflow, a, b)
    assert a.state == b.state == "unverified"
    assert "corroboration_rejected:same_ip" in b.flags
    assert guard.FLAG_SAME_SOURCE in b.flags and f"same_source_as:{a.id}" in b.flags
    assert repo.get_village("thunag").level == "normal" and not workflow.started


def test_forged_pair_from_one_network_range_does_not_verify(repo, frozen, workflow):
    a = _report(repo, name="a", source=source_for("a", ip="198.51.100.10"))
    b = _report(repo, at=PARTNER, name="b", source=source_for("b", ip="198.51.100.77"))  # same /24
    _, b = _both(repo, workflow, a, b)
    assert b.state == "unverified" and "corroboration_rejected:same_network" in b.flags
    assert repo.get_village("thunag").level == "normal"


def test_one_phone_on_two_networks_does_not_verify(repo, frozen, workflow):
    a = _report(repo, name="a", source=source_for("a", ip="198.51.100.10", device="phone-1"))
    b = _report(repo, at=PARTNER, name="b", source=source_for("b", ip="192.0.2.50", device="phone-1"))
    _, b = _both(repo, workflow, a, b)
    assert b.state == "unverified" and "corroboration_rejected:same_device" in b.flags


def test_unknown_source_never_corroborates(repo, frozen, workflow):
    a = _report(repo, name="a", source=None)
    b = _report(repo, at=PARTNER, name="b", source=source_for("b"))
    a, b = _both(repo, workflow, a, b)
    assert guard.FLAG_SOURCE_UNKNOWN in a.flags
    assert a.state == b.state == "unverified" and "corroboration_rejected:source_unknown" in b.flags


def test_missing_salt_fails_closed(repo, frozen, workflow, monkeypatch):
    monkeypatch.setattr(guard, "_salt", lambda: None)
    src = guard.make_source("203.0.113.1", "dev", "ses")
    assert src == ReportSource()  # nothing hashed without the salt, and certainly no raw IP
    a = _report(repo, name="a", source=src)
    b = _report(repo, at=PARTNER, name="b", source=guard.make_source("192.0.2.1", "dev2", "ses2"))
    a, b = _both(repo, workflow, a, b)
    assert a.state == b.state == "unverified"


def test_gps_copied_from_the_published_village_point_does_not_verify(repo, frozen, workflow):
    v = repo.get_village("thunag")
    a = _report(repo, at=(v.lat, v.lon), name="a", source=source_for("a"))
    b = _report(repo, at=(v.lat + 0.003, v.lon), name="b", source=source_for("b"))
    a, b = _both(repo, workflow, a, b)
    assert a.state == b.state == "unverified"
    assert "gps_implausible:published_centre" in a.flags
    assert "corroboration_rejected:published_centre" in b.flags


def test_a_matching_photo_alone_no_longer_verifies(repo, frozen, workflow):
    r = _report(repo, name="a", source=source_for("a"))
    assert svc.auto_verify(repo, r, repo.get_village("thunag"), photo_agrees=True) == []
    stored = repo.get_report(r.id)
    assert stored.state == "unverified" and "photo_agrees" in stored.flags


# -- genuine independent reports still raise as before ------------------------------------------
def test_genuine_independent_reports_still_verify_and_raise(repo, frozen, workflow):
    a = _report(repo, name="a", source=source_for("a", ip="198.51.100.10"))
    b = _report(repo, at=PARTNER, name="b", source=source_for("b", ip="192.0.2.50"))
    a, b = _both(repo, workflow, a, b)
    assert a.state == b.state == "verified_auto" and "corroborated" in b.flags
    assert not any(f.startswith("corroboration_rejected") for f in a.flags + b.flags)
    assert repo.get_village("thunag").level == "warning" and workflow.started


def test_a_rejected_pair_still_verifies_once_an_independent_report_arrives(repo, frozen, workflow):
    a = _report(repo, name="a", source=source_for("a", ip="203.0.113.9"))
    b = _report(repo, at=PARTNER, name="b", source=source_for("b", ip="203.0.113.9"))
    _both(repo, workflow, a, b)
    c = _report(repo, at=(31.5615, 77.1660), name="c", source=source_for("c", ip="192.0.2.50"))
    c = svc.process(repo, c.id, None, workflow=workflow)
    assert c.state == "verified_auto" and repo.get_village("thunag").level == "warning"


# -- rate limits hold, never drop --------------------------------------------------------------
def test_source_rate_limit_holds_the_excess_and_keeps_every_report(repo, frozen, workflow):
    limit = config.get_settings().report_limit_per_source
    src = source_for("spam", ip="203.0.113.66")
    made = [_report(repo, at=(31.5600 + i * 0.0004, 77.1650), name=f"n{i}", source=src) for i in range(limit + 3)]
    held = [r for r in made if r.held]
    assert len(held) == 3 and all(r.hold_reason == guard.HOLD_SOURCE for r in held)
    assert all(guard.FLAG_SOURCE_FLOOD in r.flags for r in held)
    stored = {r.id for r in repo.list_reports("thunag")}
    assert {r.id for r in made} <= stored  # nothing discarded
    # A held report is never auto-verified, even with an independent partner.
    partner = _report(repo, at=PARTNER, name="b", source=source_for("b", ip="192.0.2.50"))
    svc.process(repo, held[0].id, None, workflow=workflow)
    svc.process(repo, partner.id, None, workflow=workflow)
    assert repo.get_report(held[0].id).state == "unverified"
    # The next window starts afresh.
    frozen["now"] += timedelta(minutes=config.get_settings().report_window_minutes)
    assert not _report(repo, name="later", source=src).held


def test_village_surge_holds_reports_from_many_sources(repo, frozen):
    limit = config.get_settings().report_limit_per_village
    made = [_report(repo, name=f"p{i}", source=source_for(f"p{i}", ip=f"10.{i}.0.1")) for i in range(limit + 2)]
    assert [r.hold_reason for r in made[limit:]] == [guard.HOLD_VILLAGE] * 2
    assert all(guard.FLAG_SURGE in r.flags for r in made[limit:]) and not any(r.held for r in made[:limit])


def test_rate_held_report_never_reaches_the_model(repo, frozen):
    class Model:
        texts: list[str] = []

        def structure_report(self, text, village):
            self.texts.append(text)
            return None

    src = source_for("spam", ip="203.0.113.66")
    made = [_report(repo, name=f"n{i}", source=src) for i in range(config.get_settings().report_limit_per_source + 1)]
    model = Model()
    out = svc.process(repo, made[-1].id, model)
    assert out.held and model.texts == []


def test_officer_verifies_a_held_report_and_it_counts(repo, frozen, workflow):
    from Pukaar.services.decision_engine import recompute_village

    src = source_for("spam", ip="203.0.113.66")
    made = [_report(repo, name=f"n{i}", source=src) for i in range(config.get_settings().report_limit_per_source + 1)]
    held = svc.process(repo, made[-1].id, None, workflow=workflow)
    assert held.held and repo.get_village("thunag").level == "normal"
    repo.update_report(held.id, state="verified", previous_state=held.state, verified_by="officer1")
    recompute_village(repo, repo.get_village("thunag"), workflow=workflow)
    assert repo.get_village("thunag").level != "normal"


def test_views_never_show_the_source_hashes(repo, frozen):
    r = _report(repo, name="a", source=source_for("a"))
    assert "source" not in views.report(r) and "source" not in views.report(r, public=True)
    assert views.report(r)["held"] is False


# -- the API end to end -----------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from Pukaar.main import app

    return TestClient(app)


def _ctx(ip: str) -> dict:
    return {"x-amzn-request-context": json.dumps({"http": {"sourceIp": ip}})}


def _post(client, ip, *, device, lat=31.5185, lon=77.2240, text="pul toot gaya"):
    return client.post("/reports", headers=_ctx(ip), data={
        "village_id": "janjehli", "text": text, "lat": str(lat), "lon": str(lon),
        "device_id": device, "session_id": f"s-{device}"})


def test_api_holds_a_flood_from_one_ip_keeps_it_for_officers_and_never_stores_the_ip(client):
    from Pukaar.store.repo import get_repo

    ip = "203.0.113.201"
    limit = config.get_settings().report_limit_per_source
    bodies = [_post(client, ip, device=f"d{i}", lat=31.5185 + i * 0.0003) for i in range(limit + 2)]
    assert all(b.status_code == 200 for b in bodies)  # never a silent drop: every one gets a tracking code
    held = [b.json() for b in bodies if b.json()["report"]["held"]]
    assert len(held) == 2 and all(h["report"]["hold_reason"] == "source_rate_limit" for h in held)
    assert all("source" not in b.json()["report"] for b in bodies)
    # The villager's tracking page says it is held; the officer sees it in the feed with its flags.
    assert client.get(f"/track/{held[0]['track_code']}").json()["held"] is True
    login = client.post("/auth/dev-login", json={"username": "officer1"}).json()["token"]
    feed = client.get("/reports?village_id=janjehli", headers={"Authorization": f"Bearer {login}"}).json()
    by_id = {r["id"]: r for r in feed}
    for h in held:
        row = by_id[h["report"]["id"]]
        assert row["held"] is True and "source_flood" in row["flags"] and "same_source" in row["flags"]
    # No raw IP anywhere in the table.
    table = get_repo().t
    items = table.scan()["Items"]
    assert ip not in json.dumps(items, default=str)


def test_api_reports_from_two_phones_on_different_networks_verify(client):
    import time

    from Pukaar.store.repo import get_repo

    a = _post(client, "192.0.2.10", device="phone-a", text="pani badh raha hai", lat=31.5210, lon=77.2200).json()
    b = _post(client, "198.18.0.20", device="phone-b", text="pani badh raha hai", lat=31.5235, lon=77.2200).json()
    assert not a["report"]["held"] and not b["report"]["held"]
    ids = [a["report"]["id"], b["report"]["id"]]
    deadline = time.monotonic() + 10  # the local worker processes each report on a thread
    while time.monotonic() < deadline:
        states = {get_repo().get_report(rid).state for rid in ids}
        if states == {"verified_auto"}:
            break
        time.sleep(0.1)
    assert states == {"verified_auto"}


def test_client_ip_prefers_the_gateway_context_then_the_last_forwarded_entry(monkeypatch):
    assert guard.client_ip({"x-amzn-request-context": json.dumps({"http": {"sourceIp": "1.2.3.4"}})}, "peer") == "1.2.3.4"
    assert guard.client_ip({}, "peer") == "peer"
    monkeypatch.setenv("PUKAAR_MODE", "aws")
    config.get_settings.cache_clear()
    try:
        assert guard.client_ip({"x-forwarded-for": "6.6.6.6, 5.6.7.8"}, None) == "5.6.7.8"
        # On AWS the socket peer is the Lambda Web Adapter: never every villager's "IP".
        assert guard.client_ip({}, "127.0.0.1") is None
    finally:
        monkeypatch.setenv("PUKAAR_MODE", "local")
        config.get_settings.cache_clear()
    assert guard.network_of("203.0.113.9") == "203.0.113.0/24"
    assert guard.network_of("2001:db8:1:2:3:4:5:6") == "2001:db8:1:2::/64"
    assert guard.network_of("testclient") is None
