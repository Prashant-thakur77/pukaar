"""Reads that must not grow with the state (docs/CONTRACT.md, "At scale"): the alert inbox finds every pending
alert however many newer alerts exist (status index gsi2, district filter); a village page reads its own
alert history; /public/overview at 1,000 villages is a fixed handful of table calls, well inside the API's
29-second limit."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest

from Pukaar.core import clock
from Pukaar.store.models import Alert, RollCall, Village

from conftest import NOW


def _alert(repo, n: int, *, status: str, village: str = "gohar", minutes_ago: int | None = None) -> Alert:
    stamp = clock.iso(NOW - timedelta(minutes=minutes_ago if minutes_ago is not None else n))
    a = Alert(id=f"alr_idx_{n:04d}", village_id=village, village_name=village, village_name_hi="गाँव",
              level="watch", status=status, created_at=stamp, updated_at=stamp)
    repo.put_alert(a)
    return a


def test_an_old_pending_alert_is_never_lost_behind_600_newer_ones(repo, frozen):
    old = _alert(repo, 0, status="pending", minutes_ago=10_000, village="sujanpur")  # Hamirpur
    for n in range(1, 601):
        _alert(repo, n, status="delivered", village="gohar" if n % 2 else "thunag")
    pending = repo.list_alerts(status="pending")
    assert [a.id for a in pending] == [old.id]
    assert [a.id for a in repo.list_alerts(status="pending", district="Hamirpur")] == [old.id]
    assert repo.list_alerts(status="pending", district="Mandi") == []
    # Several statuses at once, newest first, cut at the limit.
    both = repo.list_alerts(status="pending,delivered", limit=700)
    assert len(both) == 601 and both[-1].id == old.id
    # A village's own history is read from its own pointers, not filtered from the newest 500 of the state.
    assert [a.id for a in repo.list_alerts(village_id="sujanpur")] == [old.id]
    # The index follows a status change.
    repo.update_alert(old.id, status="declined")
    assert repo.list_alerts(status="pending") == []
    assert [a.id for a in repo.list_alerts(status="declined")] == [old.id]


def test_the_inbox_route_filters_by_district(repo, frozen, monkeypatch):
    from fastapi.testclient import TestClient

    from Pukaar.api import auth
    from Pukaar.api.routers import officer
    from Pukaar.main import app

    for mod in (auth, officer):
        monkeypatch.setattr(mod, "get_repo", lambda: repo)
    _alert(repo, 1, status="pending", village="gohar")
    _alert(repo, 2, status="pending", village="sujanpur")
    client = TestClient(app)
    h = {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": "officer1"}).json()["token"]}
    r = client.get("/alerts?status=pending&district=Hamirpur", headers=h)
    assert r.status_code == 200 and [a["village_id"] for a in r.json()] == ["sujanpur"]


@pytest.fixture()
def counted(repo):
    calls: list[str] = []
    client = repo.t.meta.client
    original = client._make_api_call

    def counting(op, params):
        calls.append(op)
        return original(op, params)

    client._make_api_call = counting
    yield calls
    client._make_api_call = original


def test_public_overview_at_1000_villages(repo, frozen, monkeypatch, counted, request):
    from Pukaar.api import views
    from Pukaar.api.routers import public
    from Pukaar.core.config import get_settings
    from Pukaar.store.repo import _to_dynamo

    monkeypatch.setattr(public, "get_repo", lambda: repo)
    monkeypatch.setenv("PUKAAR_COUNTERS_MAX_AGE_SECONDS", "1200")  # as on AWS: the sweep's stored counters
    get_settings.cache_clear()
    request.addfinalizer(get_settings.cache_clear)
    with repo.t.batch_writer() as batch:
        for i in range(1000):
            v = Village(id=f"v{i:04d}", name=f"Village {i:04d}", name_hi=f"गाँव {i}", district=f"District {i % 12}",
                        lat=31 + i / 10_000, lon=77 + i / 10_000)
            batch.put_item(Item=_to_dynamo({"pk": f"VILLAGE#{v.id}", "sk": "META", "kind": "village", **v.model_dump()}))
            batch.put_item(Item={"pk": "VILLAGES", "sk": v.id})
    # One open roll-call somewhere: found by the index, not by a query per village.
    repo.put_rollcall(RollCall(id="rc_scale", village_id="v0007", village_name="Village 0007", village_name_hi="गाँव 7",
                               opened_at=clock.iso(frozen["now"]), asked=10, safe=3,
                               closes_at=clock.iso(frozen["now"] + timedelta(hours=2))))
    views.refresh_counters(repo)  # what the sweep does once a run
    counted.clear()
    started = time.monotonic()
    body = public.overview()
    seconds = time.monotonic() - started
    assert len(body["villages"]) == 1005 and body["counters"]["villages_watched"] == 1005
    assert next(v for v in body["villages"] if v["id"] == "v0007")["rollcall"]["safe"] == 3
    # A fixed number of calls: the registry query, 11 BatchGetItem (100 keys each), the stored counters,
    # the open roll-calls, the newest alerts, the replay copies and state. Never one call per village.
    assert len(counted) <= 25, counted
    assert counted.count("BatchGetItem") <= 12
    assert seconds < 10, seconds  # in-process moto on a laptop; DynamoDB is faster per call
