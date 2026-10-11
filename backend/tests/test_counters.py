"""The public counters (views.counters, GET /public/overview): each one counts real records only.

Replays never reach real phones and are never counted as sent; drills reach real phones but are
tests, so they have their own counter and never appear as a flood warning sent.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from Pukaar.api import views
from Pukaar.core import clock
from Pukaar.store.models import Alert, Delivery, Reading, Report, SensorReading

from conftest import NOW

STATUSES = ["drafting", "pending", "approved", "declined", "expired", "delivering", "delivered",
            "auto_sent_unapproved", "failsafe", "closed"]


def _alert(repo, n: int, *, status: str = "delivered", level: str = "warning", approved: bool = False,
           replay: bool = False, trace: dict | None = None, acked: int = 0, village: str = "gohar") -> Alert:
    stamp = clock.iso(NOW - timedelta(minutes=n))
    a = Alert(id=f"alr_test_{n:03d}", village_id=village, village_name=village.title(), village_name_hi="गाँव",
              level=level, status=status, created_at=stamp, updated_at=stamp, approved=approved, replay=replay,
              decision_trace=trace or {}, acknowledged_count=acked, delivered_count=3)
    repo.put_alert(a)
    return a


def _delivery(repo, alert: Alert, recipient: str, channel: str, status: str = "sent") -> None:
    repo.put_delivery(Delivery(alert_id=alert.id, recipient_id=recipient, name=recipient, channel=channel,
                               status=status, sent_at=alert.created_at, attempts=1))


def test_empty_store_gives_zeros(repo, frozen):
    import uuid

    import boto3

    from Pukaar.core.config import get_settings
    from Pukaar.store.repo import Repo, table_schema

    s = get_settings()
    name = f"pukaar-empty-{uuid.uuid4().hex[:8]}"
    boto3.client("dynamodb", region_name=s.aws_region).create_table(**table_schema(name))
    empty = Repo(boto3.resource("dynamodb", region_name=s.aws_region).Table(name))
    c = views.counters(empty)
    assert c == {k: 0 for k in c}
    assert set(c) == {"villages_watched", "alerts_sent", "phones_acknowledged", "reports_received",
                      "drills_delivered", "replay_alerts_approved", "forecast_checks_24h", "gauge_readings_24h",
                      "gauge_readings_24h_simulated"}


def test_seeded_store_counts_villages_and_nothing_else(repo, frozen):
    c = views.counters(repo)
    assert c["villages_watched"] == 5
    assert {k: v for k, v in c.items() if k != "villages_watched"} == {k: 0 for k in c if k != "villages_watched"}


@pytest.mark.parametrize(("status", "level", "approved", "counted"), [
    ("drafting", "warning", False, False),
    ("pending", "warning", False, False),
    ("approved", "warning", True, False),        # approved, not yet delivered
    ("delivering", "warning", True, False),      # on its way, counted once delivered
    ("declined", "warning", False, False),
    ("expired", "warning", False, False),        # no officer answered, not critical: nothing was sent
    ("delivered", "warning", True, True),
    ("auto_sent_unapproved", "critical", False, True),
    ("failsafe", "critical", False, True),       # the failsafe broadcasts critical alerts
    ("failsafe", "warning", True, True),         # ... and alerts already approved
    ("failsafe", "warning", False, False),       # ... and nothing else
    ("closed", "warning", True, True),
    ("closed", "warning", False, False),
])
def test_each_status_is_counted_only_when_the_alert_went_out(repo, frozen, status, level, approved, counted):
    _alert(repo, 1, status=status, level=level, approved=approved, acked=2)
    c = views.counters(repo)
    assert c["alerts_sent"] == (1 if counted else 0)
    assert c["phones_acknowledged"] == (2 if counted else 0)


def test_every_status_is_covered_by_the_table_above():
    from typing import get_args

    from Pukaar.store.models import AlertStatus

    assert sorted(get_args(AlertStatus)) == sorted(STATUSES)


def test_replays_are_never_counted_as_sent(repo, frozen):
    for i, status in enumerate(["delivered", "auto_sent_unapproved", "failsafe", "closed"]):
        _alert(repo, i, status=status, level="critical", approved=True, replay=True, acked=4)
    # replay marked only in the trace (older records) is a replay too
    _alert(repo, 10, status="delivered", approved=True, trace={"replay": True}, acked=1)
    c = views.counters(repo)
    assert c["alerts_sent"] == 0
    assert c["phones_acknowledged"] == 0
    assert c["drills_delivered"] == 0
    assert c["replay_alerts_approved"] == 5


def test_replay_alerts_approved_counts_only_officer_approvals(repo, frozen):
    _alert(repo, 1, status="delivered", approved=True, replay=True)
    _alert(repo, 2, status="auto_sent_unapproved", level="critical", approved=False, replay=True)  # nobody approved
    _alert(repo, 3, status="declined", approved=False, replay=True)
    _alert(repo, 4, status="pending", approved=False, replay=True)
    _alert(repo, 5, status="delivered", approved=True)  # live, not a replay
    assert views.counters(repo)["replay_alerts_approved"] == 1


def test_drills_count_only_in_drills_delivered(repo, frozen):
    drill = {"rules_fired": ["drill"], "drill": True}
    reached = _alert(repo, 1, status="delivered", level="watch", approved=True, trace=drill, acked=1)
    _delivery(repo, reached, "111", "telegram")
    _delivery(repo, reached, "stub-gohar-0", "stub")
    acked = _alert(repo, 2, status="closed", level="watch", approved=True, trace=drill)
    _delivery(repo, acked, "222", "telegram", status="acknowledged")
    stub_only = _alert(repo, 3, status="delivered", level="watch", approved=True, trace=drill)
    _delivery(repo, stub_only, "stub-gohar-0", "stub")  # no real phone reached
    failed = _alert(repo, 4, status="delivered", level="watch", approved=True, trace=drill)
    _delivery(repo, failed, "333", "telegram", status="failed")
    expired = _alert(repo, 5, status="expired", level="watch", trace=drill)  # nobody approved: nothing sent
    _delivery(repo, expired, "444", "telegram", status="pending")

    c = views.counters(repo)
    assert c["drills_delivered"] == 2
    assert c["alerts_sent"] == 0
    assert c["phones_acknowledged"] == 0
    assert c["replay_alerts_approved"] == 0


def test_a_live_alert_beside_a_drill(repo, frozen):
    drill = _alert(repo, 1, status="delivered", level="watch", approved=True, trace={"drill": True}, acked=5)
    _delivery(repo, drill, "111", "telegram")
    _alert(repo, 2, status="delivered", level="warning", approved=True, acked=3)
    c = views.counters(repo)
    assert (c["alerts_sent"], c["phones_acknowledged"], c["drills_delivered"]) == (1, 3, 1)


def _reading(repo, village: str, at, *, replay: bool = False) -> None:
    repo.put_reading(Reading(village_id=village, at=clock.iso(at), replay=replay))


def test_forecast_checks_cover_the_last_24_hours_of_live_readings(repo, frozen):
    for i in range(4):  # four sweeps for gohar in the window
        _reading(repo, "gohar", NOW - timedelta(minutes=15 * i))
    _reading(repo, "pandoh", NOW - timedelta(hours=24))                      # edge: exactly 24 h ago, counted
    _reading(repo, "pandoh", NOW - timedelta(hours=24, seconds=1))           # just outside
    _reading(repo, "thunag", NOW - timedelta(days=3))                        # old
    _reading(repo, "thunag", NOW + timedelta(minutes=5))                     # not yet (clock skew)
    _reading(repo, "sujanpur", NOW - timedelta(hours=1), replay=True)        # a replay row
    _reading(repo, "sujanpur", clock.parse("2023-07-10T06:00:00Z"), replay=True)
    assert views.counters(repo)["forecast_checks_24h"] == 5


def _sensor(repo, village: str, device: str, at, *, simulated: bool = False) -> None:
    assert repo.put_sensor_reading(SensorReading(village_id=village, device_id=device, at=clock.iso(at),
                                                 water_level_cm=40.0, simulated=simulated))


def test_gauge_readings_cover_the_last_24_hours_and_say_how_many_were_simulated(repo, frozen):
    gauged = [v.id for v in repo.list_villages() if v.gauge is not None]
    assert "gohar" in gauged
    other = next(v for v in gauged if v != "gohar")
    _sensor(repo, "gohar", "gauge-a", NOW - timedelta(hours=30))            # outside the window
    _sensor(repo, "gohar", "gauge-a", NOW - timedelta(hours=24))            # edge, counted
    _sensor(repo, "gohar", "gauge-a", NOW - timedelta(hours=2), simulated=True)
    _sensor(repo, "gohar", "gauge-a", NOW, simulated=True)                  # now, counted
    _sensor(repo, other, "gauge-b", NOW - timedelta(minutes=10))
    c = views.counters(repo)
    assert c["gauge_readings_24h"] == 4
    assert c["gauge_readings_24h_simulated"] == 2


def test_gauge_counter_matches_the_sensors_board(repo, frozen):
    from Pukaar.services import agents

    for i in (10, 5, 0):  # oldest first: the store refuses a reading older than the device's last one
        _sensor(repo, "gohar", "gauge-a", NOW - timedelta(minutes=i), simulated=True)
    assert views.counters(repo)["gauge_readings_24h"] == agents.sensors(repo)["readings_24h"] == 3


def test_reports_received_skips_replay_reports(repo, frozen):
    stamp = clock.iso(NOW)
    repo.put_report(Report(id="rep_live", village_id="gohar", created_at=stamp, track_code="PKLIVE"))
    repo.put_report(Report(id="rep_replay", village_id="gohar", created_at=stamp, track_code="PKREPL", replay=True))
    assert views.counters(repo)["reports_received"] == 1


def test_public_overview_serves_the_counters(repo, frozen, monkeypatch):
    from Pukaar.api.routers import public

    monkeypatch.setattr(public, "get_repo", lambda: repo)
    _alert(repo, 1, status="delivered", approved=True, trace={"drill": True})
    body = public.overview()
    assert body["counters"]["alerts_sent"] == 0
    assert body["counters"]["villages_watched"] == 5
