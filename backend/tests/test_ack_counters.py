"""Acknowledgement counting at scale (delivery/dispatch.py): each "मिल गया" is O(1), never a re-read of
every delivery row; concurrent taps never lose a count (a per-person marker created only if absent, and an
atomic ADD by whoever created it); a repeated tap or a "both" person counts once; the full recount stays, for repair and audit,
and never overwrites an ADD that lands while it runs."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from Pukaar.core import clock
from Pukaar.delivery import dispatch
from Pukaar.store.models import Alert, Delivery


@pytest.fixture()
def serial_calls(repo):
    """moto's in-process table is not safe for threads (DynamoDB is): one table call at a time, so the
    threads interleave between calls exactly as concurrent Lambdas do."""
    client = repo.t.meta.client
    original, lock = client._make_api_call, threading.Lock()
    calls: list[str] = []

    def one_at_a_time(op, params):
        with lock:
            calls.append(op)
            return original(op, params)

    client._make_api_call = one_at_a_time
    yield calls
    client._make_api_call = original


def _alert_with_rows(repo, n: int, alert_id: str = "alr_ack_1") -> Alert:
    now = clock.iso(clock.now())
    a = Alert(id=alert_id, village_id="gohar", village_name="Gohar", village_name_hi="गोहर", level="warning",
              status="delivered", approved=True, created_at=now, updated_at=now)
    repo.put_alert(a)
    for i in range(n):
        repo.put_delivery(Delivery(alert_id=a.id, recipient_id=f"{1000 + i}", name=f"p{i}", channel="telegram",
                                   status="sent", sent_at=now, attempts=1))
    dispatch.repair_counts(repo, a.id, emit=False)  # the end of the delivery round
    return repo.get_alert(a.id)


def test_concurrent_acks_count_every_person_exactly_once(repo, frozen, serial_calls):
    n = 60
    a = _alert_with_rows(repo, n)
    assert (a.delivered_count, a.phones_reached_count, a.acknowledged_count) == (n, n, 0)
    # Every person taps, most of them twice, from 16 workers at once.
    taps = [f"{1000 + i}" for i in range(n)] * 2
    with ThreadPoolExecutor(16) as pool:
        results = list(pool.map(lambda rid: dispatch.acknowledge(repo, a.id, rid), taps))
    assert sum(r is not None for r in results) == n  # one recorded acknowledgement per person
    a = repo.get_alert(a.id)
    assert (a.delivered_count, a.acknowledged_count) == (n, n)
    assert dispatch.repair_counts(repo, a.id, emit=False).acknowledged_count == n  # the audit agrees


def test_one_ack_reads_a_fixed_number_of_items_whatever_the_alert_size(repo, frozen, serial_calls):
    small = _alert_with_rows(repo, 5, "alr_small")
    big = _alert_with_rows(repo, 400, "alr_big")
    serial_calls.clear()
    dispatch.acknowledge(repo, small.id, "1001")
    few = list(serial_calls)
    serial_calls.clear()
    dispatch.acknowledge(repo, big.id, "1001")
    assert len(serial_calls) == len(few) <= 8, serial_calls
    assert "Query" not in serial_calls  # no listing of the alert's rows on a tap


def test_a_both_person_counts_once_and_a_stub_is_not_a_phone(repo, frozen):
    now = clock.iso(clock.now())
    a = Alert(id="alr_both", village_id="gohar", village_name="Gohar", village_name_hi="गोहर", level="warning",
              status="delivered", approved=True, created_at=now, updated_at=now)
    repo.put_alert(a)
    for rid, ch in (("777", "telegram"), ("777", "voice"), ("stub-gohar-1", "stub")):
        repo.put_delivery(Delivery(alert_id=a.id, recipient_id=rid, name=rid, channel=ch, status="sent",
                                   sent_at=now, attempts=1))
        dispatch.count_reached(repo, a.id, rid, ch)
    dispatch.acknowledge(repo, a.id, "777")
    dispatch.acknowledge(repo, a.id, "777", channel="voice")
    got = repo.get_alert(a.id)
    assert (got.delivered_count, got.phones_reached_count, got.acknowledged_count) == (2, 1, 1)


def test_repair_fixes_a_drifted_counter_and_never_double_counts(repo, frozen):
    a = _alert_with_rows(repo, 10)
    dispatch.acknowledge(repo, a.id, "1003")
    repo.update_alert(a.id, delivered_count=99, acknowledged_count=7)  # drift: a hand edit, a lost write
    fixed = dispatch.repair_counts(repo, a.id, emit=False)
    assert (fixed.delivered_count, fixed.acknowledged_count) == (10, 1)
    dispatch.acknowledge(repo, a.id, "1003")  # a repeat after the repair adds nothing
    dispatch.acknowledge(repo, a.id, "1004")
    assert repo.get_alert(a.id).acknowledged_count == 2


def test_repair_never_overwrites_an_add_that_lands_while_it_runs(repo, frozen):
    a = _alert_with_rows(repo, 10)
    real = repo.set_counts_if_unchanged
    raced = {"done": False}

    def racing(alert_id, seen, new):
        if not raced["done"]:
            raced["done"] = True
            dispatch.acknowledge(repo, alert_id, "1005")  # lands between the repair's read and its write
        return real(alert_id, seen, new)

    repo.set_counts_if_unchanged = racing
    repo.update_alert(a.id, acknowledged_count=5)  # drift, so the repair has something to write
    try:
        out = dispatch.repair_counts(repo, a.id, emit=False)
    finally:
        repo.set_counts_if_unchanged = real
    assert out.acknowledged_count == 1 and repo.get_alert(a.id).acknowledged_count == 1


def test_legacy_alert_without_markers_is_repaired_by_the_migration(repo, frozen):
    from Pukaar.scripts.seed import migrate_alerts

    now = clock.iso(clock.now())
    a = Alert(id="alr_legacy", village_id="gohar", village_name="Gohar", village_name_hi="गोहर", level="watch",
              status="delivered", approved=True, created_at=now, updated_at=now, delivered_count=3)
    repo.put_alert(a)
    repo.t.update_item(Key={"pk": f"ALERT#{a.id}", "sk": "META"}, UpdateExpression="REMOVE gsi2pk, gsi2sk")
    for rid, ch in (("42", "telegram"), ("stub-gohar-1", "stub"), ("stub-gohar-2", "stub")):
        repo.put_delivery(Delivery(alert_id=a.id, recipient_id=rid, name=rid, channel=ch, status="sent",
                                   sent_at=now, attempts=1))
    assert migrate_alerts(repo) == 1 and migrate_alerts(repo) == 0
    got = repo.get_alert(a.id)
    assert (got.delivered_count, got.phones_reached_count) == (3, 1)
    assert [x.id for x in repo.list_alerts(status="delivered")] == [a.id]
