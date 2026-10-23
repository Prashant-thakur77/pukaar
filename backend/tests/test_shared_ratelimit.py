"""One Telegram budget for every Lambda (delivery/ratelimit.SharedBucket): two delivery workers of two different
village alerts, each with its own full-rate local limiter, never send more than the bot's rate together, and a
429 seen by one makes the other wait too."""

from __future__ import annotations

import threading
from collections import Counter

import pytest

from Pukaar.delivery.ratelimit import RateLimiter, SharedBucket


class Clock:
    """A shared fake clock: sleeping moves time on for everyone."""

    def __init__(self) -> None:
        self.t = 1_000_000.0
        self.lock = threading.Lock()

    def now(self) -> float:
        with self.lock:
            return self.t

    def sleep(self, s: float) -> None:
        with self.lock:
            self.t += max(s, 1e-4)


@pytest.fixture()
def serial(repo):
    client = repo.t.meta.client
    original, lock = client._make_api_call, threading.Lock()

    def one_at_a_time(op, params):
        with lock:
            return original(op, params)

    client._make_api_call = one_at_a_time
    yield
    client._make_api_call = original


def _worker(repo, clock, rate=25.0):
    bucket = SharedBucket(repo, "telegram-test", rate, clock=clock.now, pause_check=0.0)
    # Each worker alone would allow the whole rate: only the shared budget holds the total.
    return RateLimiter(rate, burst=1, clock=clock.now, sleep=clock.sleep, shared=bucket), bucket


def test_two_alerts_share_one_budget(repo, serial):
    clock = Clock()
    a, _ = _worker(repo, clock)
    b, _ = _worker(repo, clock)
    sends: list[float] = []

    def run(limiter):
        for _ in range(60):
            assert limiter.acquire()
            sends.append(clock.now())

    threads = [threading.Thread(target=run, args=(w,)) for w in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(sends) == 120
    # The shared budget's own record: every half-second window gave out at most 12 slots (25 a second),
    # to both workers together, and all 120 sends took one.
    windows = Counter({int(str(i["sk"]).split("#")[1]): int(i["n"]) for i in repo._query("RATEBUCKET#telegram-test", "W#")})
    assert max(windows.values()) <= 12 and sum(windows.values()) == 120
    span = (max(windows) - min(windows) + 1) * 0.5
    assert span >= 120 / 25 - 0.5  # two workers at a full rate each would have taken half as long


def test_a_429_seen_by_one_worker_pauses_the_other(repo, serial):
    clock = Clock()
    a, _ = _worker(repo, clock)
    b, bucket_b = _worker(repo, clock)
    a.pause(7.0)  # Telegram said retry_after 7 to worker a
    start = clock.now()
    assert bucket_b.paused_for() > 6.0
    assert b.acquire()
    assert clock.now() - start >= 7.0 - 1e-6


def test_deadline_is_kept_and_nothing_is_taken(repo, serial):
    clock = Clock()
    a, bucket = _worker(repo, clock)
    bucket.pause(30.0)
    assert not a.acquire(deadline=clock.now() + 5.0)


def test_off_by_default_in_local_mode_and_on_aws(monkeypatch):
    from Pukaar.core.config import get_settings

    get_settings.cache_clear()
    try:
        assert get_settings().telegram_shared_limit is False
        monkeypatch.setenv("PUKAAR_MODE", "aws")
        get_settings.cache_clear()
        assert get_settings().telegram_shared_limit is True
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
