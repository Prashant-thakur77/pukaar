"""Delivery at scale (scorecard gap 8): batches, no double sends, Telegram's limits, and a load test.

A fake Telegram server (FakeTelegramServer) stands in for api.telegram.org through an httpx transport.
It enforces Telegram's published limits, about 30 messages a second from one bot and about one a
second to one chat, and answers 429 with retry_after when a sender goes over, as Telegram does.

The load test sends one alert to 5,000 recipients through the same steps the state machine runs
(deliver, then the Map of deliver_batch, then deliver_done; workflow/steps.drive_delivery), the batch
workers in threads standing in for the Map's concurrent Lambdas. By default its clock is 10 times
faster (every rate 10 times higher, every wait 10 times shorter) and the delivery rows live in memory
with 8 ms a call, under the same conditional writes; the measured time times 10 is what the real
limits take, overstated by the interpreter's own work, which is not sped up.

    PUKAAR_LOADTEST_MOTO=1    the delivery rows in moto, at Telegram's real limits (about 4 minutes)
    PUKAAR_LOADTEST_SPEED=k   another speed-up; PUKAAR_LOADTEST_N=n another number of recipients
    PUKAAR_LOADTEST_TRACEMALLOC=1, PUKAAR_LOADTEST_REPORT=<file>   peak Python memory; the numbers as JSON
"""

from __future__ import annotations

import json
import os
import re
import resource
import threading
import time
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from Pukaar.core.config import get_settings
from Pukaar.delivery import dispatch, telegram
from Pukaar.delivery.ratelimit import RateLimiter
from Pukaar.services import storage
from Pukaar.store.models import Recipient
from Pukaar.store.repo import ConflictError
from Pukaar.workflow.steps import drive_delivery
from test_workflow_steps import make_alert, steps

TOKEN = "123456:TEST"


class FakeTelegramServer:
    """api.telegram.org's limits, in-process. Counts what it accepted, per chat, and every 429."""

    def __init__(self, *, rate: float = 30.0, chat_interval: float = 1.0, latency: float = 0.0,
                 force_429: int = 0, retry_after: float = 1.0) -> None:
        self.rate, self.chat_interval, self.latency = rate, chat_interval, latency
        self.force_429, self.retry_after = force_429, retry_after
        self.lock = threading.Lock()
        self.window: deque[float] = deque()
        self.last_by_chat: dict[str, float] = {}
        self.accepted: Counter[str] = Counter()
        self.uploads = 0
        self.by_reference = 0
        self.too_many = 0
        self.first_at: float | None = None
        self.last_at: float | None = None

    @staticmethod
    def _fields(request: httpx.Request) -> dict:
        body = request.read()
        if request.headers.get("content-type", "").startswith("multipart/"):
            m = re.search(rb'name="chat_id"\r\n\r\n([^\r]*)\r\n', body)
            return {"chat_id": m.group(1).decode() if m else "", "_upload": True}
        try:
            return json.loads(body or b"{}")
        except ValueError:
            return {}

    def _too_many(self, after: float) -> httpx.Response:
        self.too_many += 1
        return httpx.Response(429, json={"ok": False, "error_code": 429,
                                         "description": f"Too Many Requests: retry after {after}",
                                         "parameters": {"retry_after": after}})

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.latency:
            time.sleep(self.latency)
        fields = self._fields(request)
        chat = str(fields.get("chat_id", ""))
        now = time.monotonic()
        with self.lock:
            if self.force_429 > 0:
                self.force_429 -= 1
                return self._too_many(self.retry_after)
            while self.window and now - self.window[0] >= 1.0:
                self.window.popleft()
            if len(self.window) >= self.rate:
                return self._too_many(round(1.0 - (now - self.window[0]), 3) or 0.01)
            if chat and now - self.last_by_chat.get(chat, -1e9) < self.chat_interval:
                return self._too_many(self.chat_interval)
            self.window.append(now)
            self.last_by_chat[chat] = now
            self.accepted[chat] += 1
            self.first_at = self.first_at or now
            self.last_at = now
            if fields.get("_upload"):
                self.uploads += 1
            elif "audio" in fields:
                self.by_reference += 1
        result = {"message_id": 1, "chat": {"id": chat}}
        if fields.get("_upload") or "audio" in fields:
            result["audio"] = {"file_id": "FILE-ID-1"}
        return httpx.Response(200, json={"ok": True, "result": result})


@pytest.fixture(autouse=True)
def one_moto_call_at_a_time(request):
    """moto's in-process table is not safe for threads (it counts a table by walking it while another
    thread writes); DynamoDB is. So the tests that run threads take one table call at a time, and what
    the threads exist for (the sends, the fetches, their waits) stays concurrent."""
    if "repo" not in request.fixturenames:
        yield
        return
    client = request.getfixturevalue("repo").t.meta.client
    original, lock = client._make_api_call, threading.Lock()

    def one_at_a_time(*args, **kwargs):
        with lock:
            return original(*args, **kwargs)

    client._make_api_call = one_at_a_time
    yield
    client._make_api_call = original


@pytest.fixture()
def settings(monkeypatch):
    """Set PUKAAR_* for one test; the cached settings follow, and are restored after."""

    def apply(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, str(v))
        get_settings.cache_clear()

    apply(PUKAAR_TELEGRAM_TOKEN=TOKEN)
    yield apply
    monkeypatch.undo()
    get_settings.cache_clear()
    telegram.set_transport(None)


def serve(server: FakeTelegramServer) -> FakeTelegramServer:
    telegram.set_transport(httpx.MockTransport(server.handler))
    return server


def seeded(repo, village: str = "thunag") -> int:
    """The village's demo stub recipients from the seed (a relay among them)."""
    return len(repo.list_recipients(village))


def people(repo, n: int, village: str = "thunag", start: int = 0) -> list[str]:
    ids = [str(7_000_000_000 + start + i) for i in range(n)]
    with repo.t.batch_writer() as w:  # put_recipient's item, written in bulk
        for i, rid in enumerate(ids):
            r = Recipient(id=rid, village_id=village, name=f"Villager {start + i}", channel="telegram")
            w.put_item(Item={"pk": f"VILLAGE#{village}", "sk": f"RECIPIENT#{rid}", **r.model_dump(exclude_none=True)})
    return ids


def approved(repo, *, audio: bool = False):
    a = make_alert(repo)
    fields = {"status": "approved", "approved": True, "text_hi": "पुकार: परीक्षण", "decided_by": "officer1"}
    if audio:
        fields["audio_key"] = storage.put_bytes(f"audio/alerts/{a.id}.mp3", b"ID3-fake-mp3", "audio/mpeg")
    return repo.update_alert(a.id, **fields)


def telegram_rows(repo, alert_id):
    return [d for d in repo.list_deliveries(alert_id) if d.channel == "telegram"]


# -- the batch fan-out and no double sends ------------------------------------------------------------
def test_deliver_sends_the_first_batch_and_hands_the_rest_to_the_map(repo, frozen, settings):
    settings(PUKAAR_DELIVERY_BATCH_SIZE=50, PUKAAR_DELIVERY_CONCURRENCY=4, PUKAAR_TELEGRAM_RATE_PER_SECOND=2000,
             PUKAAR_TELEGRAM_CHAT_INTERVAL_SECONDS=0)
    server = serve(FakeTelegramServer(rate=10_000, chat_interval=0))
    base = seeded(repo)
    ids = people(repo, 231 - base)
    a = approved(repo)
    s = steps(repo)
    first = s.handle({"step": "deliver", "alert_id": a.id})
    # 231 recipients (with the demo stubs): batch 0 here, batches 1-4 for the Map, 4 at once.
    assert first["more"] is True and first["mode"] == "deliver" and first["pass"] == 1
    assert [b["batch"] for b in first["batches"]] == [1, 2, 3, 4] and first["concurrency"] == 4
    assert all(b["share"] == 4 for b in first["batches"])
    head = dispatch.ordered_recipients(repo, a)[:50]  # the relay stub first, then Telegram people
    assert head[0].is_relay and head[0].channel == "stub"
    assert first["counts"]["sent"] == 50
    assert sum(server.accepted.values()) == sum(r.channel == "telegram" for r in head)
    assert repo.get_alert(a.id).status == "delivering"
    done = drive_delivery(s.handle, first, sleep=lambda _: None)
    assert done == {"alert_id": a.id, "sent": 231, "failed": 0, "mode": "deliver", "more": False}
    assert set(server.accepted) == set(ids) and set(server.accepted.values()) == {1}
    assert all(d.status == "sent" and d.send_round == 0 and d.attempts == 1 for d in telegram_rows(repo, a.id))
    alert = repo.get_alert(a.id)
    assert alert.status == "delivered" and alert.delivered_count == 231
    assert "sent=231 failed=0 (5 batches, 1 pass)" in [t.detail for t in repo.list_timeline(a.id)][-1]


def test_a_retried_or_doubled_batch_never_sends_twice(repo, frozen, settings):
    """Step Functions may run a batch again (a Lambda retry), and a slow worker may overlap its retry:
    each send is claimed by a conditional write first, so each person still gets one message."""
    settings(PUKAAR_DELIVERY_BATCH_SIZE=40, PUKAAR_TELEGRAM_RATE_PER_SECOND=2000,
             PUKAAR_TELEGRAM_CHAT_INTERVAL_SECONDS=0)
    server = serve(FakeTelegramServer(rate=10_000, chat_interval=0, latency=0.002))
    ids = people(repo, 120 - seeded(repo))
    a = approved(repo)
    s = steps(repo)
    first = s.handle({"step": "deliver", "alert_id": a.id})
    items = first["batches"]
    # Batch 0 (the relays first) went in the deliver step. The other 80 are ranges of ids, read alone, in
    # equal batches, as many as a multiple of the 4 workers: 4 of 20, so no worker idles at the end.
    assert [i["batch"] for i in items] == [1, 2, 3, 4] and all(i["first"] and i["last"] for i in items)
    batch = {"step": "deliver_batch", "alert_id": a.id, **items[0]}
    with ThreadPoolExecutor(4) as pool:  # the same batch four times at once
        results = list(pool.map(lambda _: s.handle(dict(batch)), range(4)))
    assert sum(r["sent"] for r in results) == 20
    again = s.handle(dict(batch))  # and once more after it finished
    assert again == {"spec": {"batch": 1, "first": items[0]["first"], "last": items[0]["last"]},
                     "sent": 0, "failed": 0, "deferred": 0, "retry_after": 0.0}
    for item in items[1:] * 2:
        s.handle({"step": "deliver_batch", "alert_id": a.id, **item})
    # By position too (a batch named without a range reads the whole list): still nobody twice.
    s.handle({"step": "deliver_batch", "alert_id": a.id, "batch": 2, "mode": "deliver", "share": 1})
    assert set(server.accepted.values()) == {1} and set(server.accepted) == set(ids)


def test_batches_are_even_id_ranges_or_positions_when_relays_overflow(settings):
    settings(PUKAAR_DELIVERY_BATCH_SIZE=10, PUKAAR_DELIVERY_CONCURRENCY=4)
    ppl = [Recipient(id=f"{i:03d}", village_id="thunag", name="x", channel="telegram") for i in range(57)]
    specs = dispatch.batch_specs(ppl)
    assert specs[0] == {"batch": 0}  # the deliver step's own: the first 10
    sizes = [int(sp["last"]) - int(sp["first"]) + 1 for sp in specs[1:]]
    assert sizes == [6] * 7 + [5] and sum(sizes) == 47  # 8 batches (a multiple of 4 workers), none over 10
    assert specs[1]["first"] == "010" and specs[-1]["last"] == "056"
    relays = [Recipient(id=f"r{i:02d}", village_id="thunag", name="p", channel="telegram", role="task_force")
              for i in range(15)]
    by_position = dispatch.batch_specs(dispatch.relays_first(ppl + relays))
    assert by_position == [{"batch": b} for b in range(8)]


def test_a_claim_is_taken_once(repo):
    """The compare-and-set itself: two workers claiming the same row for the same round, one wins."""
    a = make_alert(repo)
    won, lost = [], []

    def claim(_):
        try:
            won.append(repo.claim_delivery(a.id, "555", "telegram", name="X", expected_attempts=None, send_round=0))
        except ConflictError:
            lost.append(1)

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(claim, range(8)))
    assert len(won) == 1 and len(lost) == 7
    with pytest.raises(ConflictError):  # claimed in round 0 already
        repo.claim_delivery(a.id, "555", "telegram", name="X", expected_attempts=1, send_round=0)
    assert repo.claim_delivery(a.id, "555", "telegram", name="X", expected_attempts=1, send_round=1).attempts == 2


def test_the_alert_audio_is_uploaded_to_telegram_once(repo, frozen, settings):
    settings(PUKAAR_DELIVERY_BATCH_SIZE=20, PUKAAR_TELEGRAM_RATE_PER_SECOND=2000,
             PUKAAR_TELEGRAM_CHAT_INTERVAL_SECONDS=0)
    server = serve(FakeTelegramServer(rate=10_000, chat_interval=0))
    tg = 80 - seeded(repo)
    people(repo, tg)
    a = approved(repo, audio=True)
    s = steps(repo)
    drive_delivery(s.handle, s.handle({"step": "deliver", "alert_id": a.id}), sleep=lambda _: None)
    assert server.uploads == 1 and server.by_reference == tg - 1
    assert repo.get_telegram_file(a.id) == "FILE-ID-1"


def test_the_call_audio_is_made_once_per_alert(repo, frozen, settings, monkeypatch):
    """Voice: the 8 kHz call audio is synthesized once, before any batch, and reused by every batch and re-send."""
    from Pukaar.voice import polly

    made = []
    monkeypatch.setattr(polly, "synthesize_call_audio", lambda alert_id, text: made.append(alert_id) or "audio/c.mp3")
    monkeypatch.setattr(polly, "menu_audio_key", lambda: "audio/menu.mp3")
    settings(PUKAAR_DELIVERY_BATCH_SIZE=5)
    for i in range(12):
        repo.put_recipient(Recipient(id=f"v_{i}", village_id="thunag", name=f"V{i}", channel="voice",
                                     phone=f"+9198100000{i:02d}"))
    a = approved(repo)
    s = steps(repo)
    drive_delivery(s.handle, s.handle({"step": "deliver", "alert_id": a.id}), sleep=lambda _: None)
    drive_delivery(s.handle, s.handle({"step": "recall", "alert_id": a.id}), sleep=lambda _: None)
    assert made == [a.id] and repo.get_alert(a.id).call_audio_key == "audio/c.mp3"


# -- Telegram's limits: 429 ------------------------------------------------------------------------
def test_429_is_waited_out_and_never_recorded_as_sent(repo, frozen, settings):
    settings(PUKAAR_TELEGRAM_RATE_PER_SECOND=1000, PUKAAR_TELEGRAM_CHAT_INTERVAL_SECONDS=0)
    server = serve(FakeTelegramServer(rate=10_000, chat_interval=0, force_429=3, retry_after=0.05))
    base = seeded(repo)
    ids = people(repo, 10)
    a = approved(repo)
    started = time.monotonic()
    out = steps(repo).handle({"step": "deliver", "alert_id": a.id})
    assert out["more"] is False and out["sent"] == 10 + base and server.too_many == 3
    assert time.monotonic() - started >= 0.05  # the worker paused for retry_after
    assert set(server.accepted) == set(ids) and set(server.accepted.values()) == {1}
    assert all(d.status == "sent" and d.attempts == 1 and not d.deferred for d in telegram_rows(repo, a.id))


def test_429_past_the_time_budget_is_queued_unsent_then_sent_next_pass(repo, frozen, settings):
    """Telegram asks for a wait longer than the step has left: the sends are put back, marked queued
    (never sent), and deliver_done runs the batch again after retry_after."""
    settings(PUKAAR_TELEGRAM_RATE_PER_SECOND=1000, PUKAAR_TELEGRAM_CHAT_INTERVAL_SECONDS=0,
             PUKAAR_DELIVERY_BUDGET_SECONDS=1)
    server = serve(FakeTelegramServer(rate=10_000, chat_interval=0, force_429=1, retry_after=30))
    base = seeded(repo)
    ids = people(repo, 6)
    a = approved(repo)
    s = steps(repo)
    first = s.handle({"step": "deliver", "alert_id": a.id})
    assert first["more"] is True
    assert first["batches"] == [{"batch": 0, "first": None, "last": None, "mode": "deliver", "share": 1}]
    assert first["wait_seconds"] == 30 and sum(server.accepted.values()) == 0
    rows = telegram_rows(repo, a.id)
    assert rows and all(d.status == "failed" and d.deferred and d.attempts == 0 for d in rows)
    assert all(d.error.startswith("queued, not sent") for d in rows)
    assert repo.get_alert(a.id).delivered_count == 0
    # The state machine waits retry_after (WaitBeforeBatches), then the next pass sends everyone, once.
    waits = []
    done = drive_delivery(s.handle, first, sleep=waits.append)
    assert done["more"] is False and done["sent"] == 6 + base and waits == [30]  # stubs went in the first pass
    assert set(server.accepted) == set(ids) and set(server.accepted.values()) == {1}
    assert all(d.status == "sent" and d.attempts == 1 and not d.deferred for d in telegram_rows(repo, a.id))


def test_the_rate_limiter_keeps_a_worker_under_its_share():
    clock = {"t": 0.0}

    def sleep(s):
        clock["t"] += s

    lim = RateLimiter(10, per_key_interval=1.0, clock=lambda: clock["t"], sleep=sleep)
    for i in range(50):
        assert lim.acquire(f"chat{i}")
    assert 4.4 <= clock["t"] <= 4.6  # 50 messages at 10 a second, after a burst of 5
    lim.acquire("same")
    t = clock["t"]
    lim.acquire("same")
    assert clock["t"] - t >= 1.0  # one a second to one chat
    lim.pause(3)
    t = clock["t"]
    lim.acquire("other")
    assert clock["t"] - t >= 3.0  # a 429 holds every sender
    lim.pause(10)
    assert lim.acquire("x", deadline=clock["t"] + 1) is False  # no slot before the deadline: nothing taken


# -- the load test --------------------------------------------------------------------------------------
LOAD_N = int(os.environ.get("PUKAAR_LOADTEST_N", "5000"))
# The default run: the clock 10 times faster, the delivery rows in memory with 8 ms a call (DynamoDB's
# latency, I/O that does not hold the interpreter). PUKAAR_LOADTEST_MOTO=1 keeps the rows in moto, whose
# in-process work does hold it; with PUKAAR_LOADTEST_SPEED=1 that is the real-time run in docs/CONTRACT.md.
MOTO = os.environ.get("PUKAAR_LOADTEST_MOTO") == "1"
SPEED = float(os.environ.get("PUKAAR_LOADTEST_SPEED", "1" if MOTO else "10"))
TABLE_LATENCY = 0.008
TARGET_SECONDS = 300  # 5,000 recipients within 5 minutes


def _holds(cond, row: dict) -> bool:
    """Evaluate the boto3 conditions Repo uses on the delivery rows against an in-memory row."""
    if cond is None:
        return True
    e = cond.get_expression()
    op, vals = e["operator"], e["values"]
    if op == "AND":
        return _holds(vals[0], row) and _holds(vals[1], row)
    if op == "OR":
        return _holds(vals[0], row) or _holds(vals[1], row)
    name = vals[0].name
    if op == "attribute_exists":
        return name in row
    if op == "attribute_not_exists":
        return name not in row
    if op == "=":
        return name in row and row[name] == vals[1]
    if op == "<>":
        return name not in row or row[name] != vals[1]
    raise AssertionError(f"condition {op} not supported by the load-test table")


def in_memory_rows(repo, latency: float):
    """The same Repo, but delivery rows and the Telegram file id live in memory, under the same
    conditional-write rules (_put/_update with conditions), with a fixed latency per call."""
    from Pukaar.store.repo import Repo

    rows: dict[tuple[str, str], dict] = {}
    lock = threading.Lock()
    mine = lambda sk: sk.startswith("DELIVERY#") or sk == "TGFILE"  # noqa: E731

    class LoadRepo(Repo):
        def _put(self, item, condition=None):
            if not mine(item["sk"]):
                return super()._put(item, condition)
            time.sleep(latency)
            with lock:
                old = rows.get((item["pk"], item["sk"]), {})
                if not _holds(condition, old):
                    raise ConflictError("condition failed")
                rows[(item["pk"], item["sk"])] = {k: v for k, v in item.items() if v is not None}

        def _get(self, pk, sk):
            if not mine(sk):
                return super()._get(pk, sk)
            time.sleep(latency)
            with lock:
                row = rows.get((pk, sk))
                return dict(row) if row else None

        def _update(self, pk, sk, fields, *, remove=(), condition=None, add=None):
            if not mine(sk):
                return super()._update(pk, sk, fields, remove=remove, condition=condition, add=add)
            time.sleep(latency)
            with lock:
                row = dict(rows.get((pk, sk), {}))
                if not _holds(condition, row):
                    raise ConflictError("condition failed")
                row.update({"pk": pk, "sk": sk, **fields})
                for k in remove:
                    row.pop(k, None)
                rows[(pk, sk)] = {k: v for k, v in row.items() if v is not None}
                return dict(rows[(pk, sk)])

        def _query(self, pk, prefix="", *, newest_first=False, limit=None):
            if prefix != "DELIVERY#":
                return super()._query(pk, prefix, newest_first=newest_first, limit=limit)
            time.sleep(latency)
            with lock:
                return [dict(v) for (p, s), v in sorted(rows.items()) if p == pk and s.startswith(prefix)]

        def get_deliveries(self, alert_id, recipient_ids):
            time.sleep(latency)
            from Pukaar.store.models import delivery_key

            with lock:
                found = [rows.get((f"ALERT#{alert_id}", f"DELIVERY#{delivery_key(rid, ch)}"))
                         for rid in dict.fromkeys(recipient_ids) for ch in ("", "voice")]
            from Pukaar.store.models import Delivery
            from Pukaar.store.repo import _model

            return [_model(Delivery, dict(r)) for r in found if r]

    return LoadRepo(repo.t)


def test_load_5000_recipients_within_5_minutes(repo, frozen, settings):
    """5,000 Telegram recipients, one alert, through deliver -> Map(deliver_batch) -> deliver_done with the
    production settings (batches of 250, 4 at once, 25 messages a second overall, 1 a second per chat)
    against Telegram's limits (30 a second, 1 a second per chat), on a clock sped up SPEED times."""
    settings(PUKAAR_DELIVERY_BATCH_SIZE=250, PUKAAR_DELIVERY_CONCURRENCY=4, PUKAAR_DELIVERY_THREADS=8,
             PUKAAR_TELEGRAM_RATE_PER_SECOND=25 * SPEED, PUKAAR_TELEGRAM_CHAT_INTERVAL_SECONDS=1 / SPEED,
             PUKAAR_DELIVERY_BUDGET_SECONDS=200 / SPEED)
    server = serve(FakeTelegramServer(rate=30 * SPEED, chat_interval=1 / SPEED, latency=0.08 / SPEED))
    base = seeded(repo)
    ids = people(repo, LOAD_N)
    a = approved(repo, audio=True)
    table = repo if MOTO else in_memory_rows(repo, TABLE_LATENCY / SPEED)
    s = steps(table)
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    trace = os.environ.get("PUKAAR_LOADTEST_TRACEMALLOC") == "1"
    if trace:
        import tracemalloc

        tracemalloc.start()
    started = time.monotonic()
    done = drive_delivery(s.handle, s.handle({"step": "deliver", "alert_id": a.id}),
                          sleep=lambda secs: time.sleep(secs / SPEED))
    elapsed = time.monotonic() - started
    peak = None
    if trace:
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    # Every wait was SPEED times shorter, so elapsed * SPEED is the time at the real limits. The work the
    # interpreter does is multiplied too, so the projection overstates the real time.
    projected = elapsed * SPEED
    sending = (server.last_at - server.first_at) * SPEED
    report = {"recipients": LOAD_N, "table": "moto" if MOTO else f"in memory, {TABLE_LATENCY * 1000:g} ms a call",
              "speed": SPEED, "elapsed_s": round(elapsed, 1), "projected_real_s": round(projected, 1),
              "sending_window_real_s": round(sending, 1), "real_msgs_per_s": round(LOAD_N / projected, 1),
              "http_429": server.too_many, "uploads": server.uploads, "maxrss_mb": round(rss_after / 1024, 1),
              "maxrss_growth_mb": round((rss_after - rss_before) / 1024, 1),
              "python_peak_mb": round(peak / 2**20, 1) if peak else None}
    print("\nLOADTEST", json.dumps(report))
    if os.environ.get("PUKAAR_LOADTEST_REPORT"):
        with open(os.environ["PUKAAR_LOADTEST_REPORT"], "w", encoding="utf-8") as f:
            json.dump(report, f)

    # Everyone, exactly once; the audio uploaded once; every row honest.
    assert done["more"] is False and done["sent"] == LOAD_N + base and done["failed"] == 0
    assert len(server.accepted) == LOAD_N and set(server.accepted.values()) == {1}
    assert set(server.accepted) == set(ids)
    assert server.uploads == 1
    rows = [d for d in table.list_deliveries(a.id) if d.channel == "telegram"]
    assert len(rows) == LOAD_N and all(d.status == "sent" and d.attempts == 1 for d in rows)
    assert table.get_alert(a.id).delivered_count == LOAD_N + base
    assert projected < TARGET_SECONDS, report
    # The limiter keeps the workers under Telegram's limit: (almost) no 429s.
    assert server.too_many <= LOAD_N * 0.01, report
