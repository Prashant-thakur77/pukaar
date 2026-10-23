"""GET /public/pilot-metrics (api/pilot.py): measured numbers only, null where nothing is measured yet.

Drills and live alerts are kept apart, replays are never counted, the stub channel is not a phone,
and the medians come from the delivery records' own send and acknowledgement times.
Also checks data/pilot_readiness.json, the checklist the /pilot page shows.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from Pukaar.api import pilot
from Pukaar.core import clock
from Pukaar.store.models import Alert, Delivery

from conftest import NOW

DATA = Path(__file__).resolve().parents[2] / "data"


def _alert(repo, n: int, *, status: str = "delivered", drill: bool = False, replay: bool = False) -> Alert:
    stamp = clock.iso(NOW - timedelta(hours=n))
    a = Alert(id=f"alr_pm_{n:03d}", village_id="gohar", village_name="Gohar", village_name_hi="गोहर", level="watch",
              status=status, approved=True, created_at=stamp, updated_at=stamp, replay=replay,
              decision_trace={"drill": True} if drill else {})
    repo.put_alert(a)
    return a


def _delivery(repo, a: Alert, who: str, *, sent_min: float = 0, ack_min: float | None = None,
              channel: str = "telegram", status: str | None = None) -> None:
    base = clock.parse(a.created_at)
    sent = clock.iso(base + timedelta(minutes=sent_min))
    acked = clock.iso(base + timedelta(minutes=ack_min)) if ack_min is not None else None
    repo.put_delivery(Delivery(alert_id=a.id, recipient_id=who, name=who, channel=channel,
                               status=status or ("acknowledged" if acked else "sent"), sent_at=sent, attempts=1,
                               acknowledged_at=acked))


def test_nothing_measured_is_null_never_zero_minutes(repo, frozen):
    m = pilot.metrics(repo)
    for group in ("drills", "live"):
        g = m[group]
        assert g["alerts"] == 0 and g["reached"] == 0 and g["acknowledged"] == 0
        assert g["ack_share"] is None
        assert g["median_minutes_first_ack"] is None and g["median_minutes_to_ack"] is None


def test_drills_count_real_phones_and_time_the_first_acknowledgement(repo, frozen):
    d1 = _alert(repo, 1, drill=True)
    _delivery(repo, d1, "a", sent_min=0, ack_min=4)
    _delivery(repo, d1, "b", sent_min=1, ack_min=11)
    _delivery(repo, d1, "c", sent_min=1)
    _delivery(repo, d1, "demo", sent_min=0, ack_min=1, channel="stub")  # not a phone
    _delivery(repo, d1, "x", sent_min=0, status="failed")  # never reached
    d2 = _alert(repo, 2, drill=True)
    _delivery(repo, d2, "a", sent_min=2, ack_min=8)
    _delivery(repo, d2, "b", sent_min=2)
    stub_only = _alert(repo, 3, drill=True)
    _delivery(repo, stub_only, "demo", channel="stub", ack_min=1)

    g = pilot.metrics(repo)["drills"]
    assert g["alerts"] == 2  # the stub-only drill reached no phone
    assert g["reached"] == 5 and g["acknowledged"] == 3
    assert g["ack_share"] == 0.6
    # per alert: d1 first send 0 -> first ack 4 = 4; d2 first send 2 -> first ack 8 = 6; median 5
    assert g["median_minutes_first_ack"] == 5.0
    # per person: 4, 10, 6 -> 6
    assert g["median_minutes_to_ack"] == 6.0


def test_live_alerts_are_apart_from_drills_and_replays_never_count(repo, frozen):
    live = _alert(repo, 1)
    _delivery(repo, live, "a", ack_min=3)
    _delivery(repo, live, "b")
    pending = _alert(repo, 2, status="pending")
    _delivery(repo, pending, "a", ack_min=1)
    rp = _alert(repo, 3, replay=True)
    _delivery(repo, rp, "a", ack_min=1)
    drill = _alert(repo, 4, drill=True)
    _delivery(repo, drill, "a", ack_min=9)

    m = pilot.metrics(repo)
    assert m["live"] == {"alerts": 1, "delivered": 2, "reached": 2, "demo_recipients": 0, "acknowledged": 1,
                         "ack_share": 0.5, "median_minutes_first_ack": 3.0, "median_minutes_to_ack": 3.0}
    assert m["drills"]["alerts"] == 1 and m["drills"]["median_minutes_first_ack"] == 9.0
    assert m["counters"]["alerts_sent"] == 1 and m["counters"]["drills_delivered"] == 1


def test_a_drill_reads_the_same_on_the_overview_and_the_pilot_page(repo, frozen, monkeypatch):
    """The live drill: one real Telegram phone and the two demo recipients (stub channel). The overview's
    delivered_count (3: everyone, the demo stub included) and the pilot page's numbers now say the same thing:
    delivered 3, of which reached on a real phone 1 (phones_reached_count), demo recipients 2."""
    from Pukaar.api.routers import public
    from Pukaar.delivery import dispatch

    monkeypatch.setattr(public, "get_repo", lambda: repo)
    d = _alert(repo, 1, drill=True)
    _delivery(repo, d, "4242424242", channel="telegram")
    _delivery(repo, d, "stub-gohar-1", channel="stub")
    _delivery(repo, d, "stub-gohar-2", channel="stub")
    dispatch.repair_counts(repo, d.id, emit=False)  # what the end of the delivery round does

    row = next(a for a in public.overview()["recent_alerts"] if a["id"] == d.id)
    g = pilot.metrics(repo)["drills"]
    assert (row["delivered_count"], row["phones_reached_count"]) == (3, 1)
    assert (g["delivered"], g["reached"], g["demo_recipients"]) == (3, 1, 2)
    assert g["delivered"] == row["delivered_count"] and g["reached"] == row["phones_reached_count"]


def test_a_both_channel_person_is_one_person_reached(repo, frozen):
    d = _alert(repo, 1, drill=True)
    _delivery(repo, d, "777", channel="telegram", ack_min=2)
    _delivery(repo, d, "777", channel="voice")
    g = pilot.metrics(repo)["drills"]
    assert (g["reached"], g["acknowledged"]) == (1, 1)


def test_backtest_lead_times_come_from_the_file(repo, frozen):
    bt = json.loads((DATA / "backtest.json").read_text(encoding="utf-8"))
    out = pilot.metrics(repo)["backtest"]
    assert out["rules"] == bt["rules"]
    assert [s["name"] for s in out["scenarios"]] == [s["name"] for s in bt["scenarios"]]
    for sc, src in zip(out["scenarios"], bt["scenarios"]):
        leads = sorted(v["lead_hours_watch_to_peak_day"] for v in src["villages"]
                       if v["lead_hours_watch_to_peak_day"] is not None)
        assert sc["villages_scored"] == len(src["villages"]) and sc["villages_alerted"] == len(leads)
        assert sc["max_lead_hours"] == (max(leads) if leads else None)
        assert [v["lead_hours"] for v in sc["villages"]] == [v["lead_hours_watch_to_peak_day"] for v in src["villages"]]


@pytest.fixture()
def client(repo, monkeypatch):
    from Pukaar.api.routers import public
    from Pukaar.main import app

    monkeypatch.setattr(public, "get_repo", lambda: repo)
    return TestClient(app)


def test_route_is_public_and_carries_no_names(client, repo, frozen):
    d = _alert(repo, 1, drill=True)
    _delivery(repo, d, "4242424242", ack_min=2)
    r = client.get("/public/pilot-metrics")
    assert r.status_code == 200
    assert "4242424242" not in r.text
    assert r.json()["drills"]["reached"] == 1


def test_readiness_file_is_complete_and_honest():
    doc = json.loads((DATA / "pilot_readiness.json").read_text(encoding="utf-8"))
    items = doc["items"]
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids)) == 12
    for i in items:
        assert i["status"] in {"done", "in_progress", "not_started"}, i["id"]
        for k in ("title", "why", "owner"):
            assert i[k]["en"].strip() and i[k]["hi"].strip(), (i["id"], k)
    assert doc["updated"][:2] == "20"
