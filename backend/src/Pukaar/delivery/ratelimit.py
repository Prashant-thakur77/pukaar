"""Send-rate limits: a token bucket for all chats together, a minimum gap per chat, a pause that every
thread honours after the far side says "too many requests", and (SharedBucket) one budget for every
process.

Telegram allows about 30 messages a second from one bot, and about one a second to one chat. A
delivery fans out over n batch workers (the Map state in infra/approval.asl.json), each its own Lambda;
two villages alerting at once are two such fan-outs, and an officer's message or a roll-call goes from
yet another Lambda. Splitting the rate 1/n per worker cannot see the other alerts, so on AWS every
Telegram send also takes a slot from one shared budget in DynamoDB (SharedBucket, PUKAAR_TELEGRAM_SHARED_LIMIT,
on by default there): fixed windows of half a second, each with rate/2 slots taken by one conditional
ADD, so all Lambdas together never send more than PUKAAR_TELEGRAM_RATE_PER_SECOND, however many alerts run.
A 429 still happens (Telegram's limits are approximate): retry_after pauses this process, and is written to
the shared budget too, so every other Lambda waits it out instead of meeting the same 429. The message is
tried again or put back unsent, never marked sent.

The clocks and sleep are injectable so tests run without waiting.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable

_EPSILON = 1e-6


class SharedBucket:
    """One send budget for every process: `rate` per second in fixed windows of `window` seconds, kept in
    DynamoDB (Repo.take_rate_slots: a conditional ADD, so two Lambdas never take the same last slot), and a
    shared pause after a 429 (read at most every `pause_check` seconds). Uses wall-clock time, the one
    clock every Lambda shares."""

    def __init__(self, repo: Any, name: str, rate_per_second: float, *, window: float = 0.5,
                 pause_check: float = 1.0, clock: Callable[[], float] = time.time) -> None:
        self.repo, self.name, self.window = repo, name, window
        self.limit = max(1, math.floor(rate_per_second * window))
        self.pause_check = pause_check
        self._clock = clock
        self._lock = threading.Lock()
        self._pause_until, self._pause_read_at = 0.0, -math.inf

    def paused_for(self) -> float:
        now = self._clock()
        with self._lock:
            if now - self._pause_read_at >= self.pause_check:
                self._pause_read_at = now
                try:
                    self._pause_until = max(self._pause_until, self.repo.get_rate_pause(self.name))
                except Exception:
                    pass  # a read that fails never stops sending: the local limiter still holds
            return max(0.0, self._pause_until - now)

    def pause(self, seconds: float) -> None:
        until = self._clock() + max(0.0, seconds)
        with self._lock:
            self._pause_until = max(self._pause_until, until)
        try:
            self.repo.set_rate_pause(self.name, until)
        except Exception:
            pass

    def try_take(self) -> float:
        """0 when a slot was taken now; otherwise seconds to wait before trying again."""
        paused = self.paused_for()
        if paused > 0:
            return paused
        now = self._clock()
        window = int(now // self.window)
        try:
            if self.repo.take_rate_slots(self.name, window, self.limit):
                return 0.0
        except Exception:
            return 0.0  # DynamoDB unreachable: fall back to this process's own limit rather than stop alerts
        return max(_EPSILON, (window + 1) * self.window - now)


class RateLimiter:
    def __init__(self, rate_per_second: float, *, burst: float | None = None, per_key_interval: float = 0.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 shared: SharedBucket | None = None) -> None:
        self._lock = threading.Lock()
        self._clock, self._sleep = clock, sleep
        self.per_key_interval = per_key_interval
        self._next_for_key: dict[str, float] = {}
        self._paused_until = 0.0
        self.shared = shared
        self.set_rate(rate_per_second, burst=burst)

    def set_rate(self, rate_per_second: float, *, burst: float | None = None) -> None:
        with self._lock:
            self.rate = max(0.01, float(rate_per_second))
            # A burst of one second's worth at most: a fresh worker never fires a volley over the limit.
            self.burst = max(1.0, burst if burst is not None else min(self.rate, 5.0))
            self._tokens = min(getattr(self, "_tokens", self.burst), self.burst)
            self._stamp = self._clock()

    def pause(self, seconds: float) -> None:
        """The far side asked us to wait: nobody in this process sends until then (nor, with a shared
        bucket, in any other)."""
        with self._lock:
            self._paused_until = max(self._paused_until, self._clock() + max(0.0, seconds))
            self._tokens = 0.0
        if self.shared is not None:
            self.shared.pause(seconds)

    def paused_for(self) -> float:
        with self._lock:
            return max(0.0, self._paused_until - self._clock())

    def acquire(self, key: str | None = None, *, deadline: float | None = None) -> bool:
        """Wait for a slot. False (nothing taken) if the slot would come after deadline (a monotonic time).
        With a shared bucket, the slot is also taken from every process's common budget."""
        if not self._acquire_local(key, deadline):
            return False
        if self.shared is None:
            return True
        while True:
            wait = self.shared.try_take()
            if wait <= 0:
                return True
            if deadline is not None and self._clock() + wait > deadline:
                return False
            self._sleep(min(wait, 1.0))

    def _acquire_local(self, key: str | None, deadline: float | None) -> bool:
        while True:
            with self._lock:
                now = self._clock()
                self._tokens = min(self.burst, self._tokens + (now - self._stamp) * self.rate)
                self._stamp = now
                wait = max(0.0, self._paused_until - now)
                if wait < _EPSILON and self._tokens < 1.0 - _EPSILON:
                    wait = (1.0 - self._tokens) / self.rate
                if wait < _EPSILON and key is not None and self.per_key_interval:
                    wait = max(0.0, self._next_for_key.get(key, 0.0) - now)
                if wait < _EPSILON:  # rounding: never spin on a wait too small to move the clock
                    wait = 0.0
                if deadline is not None and now + wait > deadline:
                    return False
                if not wait:
                    self._tokens = max(0.0, self._tokens - 1.0)
                    if key is not None and self.per_key_interval:
                        self._next_for_key[key] = now + self.per_key_interval
                        if len(self._next_for_key) > 20000:  # old chats drop out; only the last second matters
                            self._next_for_key = {k: t for k, t in self._next_for_key.items() if t > now}
                    return True
            self._sleep(min(wait, 1.0))
