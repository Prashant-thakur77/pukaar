"""Send-rate limits for one process: a token bucket for all chats together, a minimum gap per chat,
and a pause that every thread honours after the far side says "too many requests".

Telegram allows about 30 messages a second from one bot, and about one a second to one chat. A
delivery that fans out over n batch workers (the Map state in infra/approval.asl.json) gives each
worker 1/n of the overall rate (dispatch.py sets it), so the workers together stay under the limit
without talking to each other. When they do not (two villages alerting at once, a provider that is
slower than usual), Telegram answers 429 with retry_after; pause() stops every thread of this
process for that long, and the message is tried again or put back unsent, never marked sent.

The clock and sleep are injectable so tests run without waiting.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

_EPSILON = 1e-6


class RateLimiter:
    def __init__(self, rate_per_second: float, *, burst: float | None = None, per_key_interval: float = 0.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self._lock = threading.Lock()
        self._clock, self._sleep = clock, sleep
        self.per_key_interval = per_key_interval
        self._next_for_key: dict[str, float] = {}
        self._paused_until = 0.0
        self.set_rate(rate_per_second, burst=burst)

    def set_rate(self, rate_per_second: float, *, burst: float | None = None) -> None:
        with self._lock:
            self.rate = max(0.01, float(rate_per_second))
            # A burst of one second's worth at most: a fresh worker never fires a volley over the limit.
            self.burst = max(1.0, burst if burst is not None else min(self.rate, 5.0))
            self._tokens = min(getattr(self, "_tokens", self.burst), self.burst)
            self._stamp = self._clock()

    def pause(self, seconds: float) -> None:
        """The far side asked us to wait: nobody in this process sends until then."""
        with self._lock:
            self._paused_until = max(self._paused_until, self._clock() + max(0.0, seconds))
            self._tokens = 0.0

    def paused_for(self) -> float:
        with self._lock:
            return max(0.0, self._paused_until - self._clock())

    def acquire(self, key: str | None = None, *, deadline: float | None = None) -> bool:
        """Wait for a slot. False (nothing taken) if the slot would come after deadline (a monotonic time)."""
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
