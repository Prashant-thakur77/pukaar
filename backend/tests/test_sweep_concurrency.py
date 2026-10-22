"""The concurrent sweep (scorecard gap 8): villages evaluated at once on a bounded pool, each one's
error its own, and the "never a false normal" rules unchanged (services/decision_engine.sweep_all).

Forecast I/O is mocked with a fixed wait per village, as the real fetch spends its time waiting on
Open-Meteo and the official feeds; the table is moto.
"""

from __future__ import annotations

import threading
import time

from Pukaar.core.config import get_settings
from Pukaar.services import decision_engine as de
from Pukaar.store.models import Reading
from test_delivery_scale import one_moto_call_at_a_time  # noqa: F401  (autouse fixture: moto is not thread-safe)
from test_sweep import make_reading

FETCH_SECONDS = 0.6  # one village's forecast calls; 200 of them one at a time would take 120 s


def villages(repo, n: int) -> list[str]:
    """The seeded villages, and copies of them under new ids up to n."""
    base = repo.list_villages()
    for i in range(n - len(base)):
        src = base[i % len(base)]
        repo.put_village(src.model_copy(update={"id": f"z{i:03d}", "name": f"{src.name} {i}", "open_alert_id": None,
                                                "last_alert_id": None}))
    return [v.id for v in repo.list_villages()]


def test_200_villages_in_under_60_seconds(repo, frozen, workflow):
    ids = villages(repo, 200)
    assert len(ids) == 200
    busy, peak, lock = [0], [0], threading.Lock()

    def fetch(village, at):
        with lock:
            busy[0] += 1
            peak[0] = max(peak[0], busy[0])
        time.sleep(FETCH_SECONDS)
        with lock:
            busy[0] -= 1
        return make_reading(village, at, 0.0)

    started = time.monotonic()
    results = de.sweep_all(repo, now=frozen["now"], fetch=fetch, workflow=workflow)
    elapsed = time.monotonic() - started
    print(f"\nSWEEP villages=200 elapsed_s={elapsed:.1f} serial_would_be_s={200 * FETCH_SECONDS:.0f} "
          f"concurrency={peak[0]}")
    assert [r.village_id for r in results] == ids  # in village order
    bad = [(r.village_id, r.note) for r in results if r.note.startswith("error") or r.skipped]
    assert bad == []
    assert elapsed < 60
    assert peak[0] == get_settings().sweep_concurrency  # bounded: never more fetches at once than the pool
    assert elapsed < 200 * FETCH_SECONDS / 4  # and far below one at a time


def test_one_village_error_stays_its_own_and_never_a_false_normal(repo, frozen, workflow):
    villages(repo, 40)
    for vid in ("thunag", "gohar", "z003"):
        repo.update_village(vid, level="warning", calm_sweeps=0)

    def fetch(village, at):
        time.sleep(0.05)
        if village.id in {"thunag", "z007"}:
            raise RuntimeError("upstream down")
        if village.id == "gohar":  # a forecast with both parts missing: unknown, never 0
            return Reading(village_id=village.id, at=at.isoformat(), missing=["rain", "discharge"])
        return make_reading(village, at, 0.0)

    results = {r.village_id: r for r in de.sweep_all(repo, now=frozen["now"], fetch=fetch, workflow=workflow)}
    assert len(results) == 40
    errors = {vid for vid, r in results.items() if r.note.startswith("error")}
    assert errors == {"thunag", "z007"}
    # The failed village holds its level and says its data is not fresh; nobody else is touched by it.
    thunag = repo.get_village("thunag")
    assert thunag.level == "warning" and thunag.data_status in {"stale", "unavailable"}
    assert "level held, not lowered" in thunag.data_note
    # Missing data is not a calm sweep: gohar stays at warning.
    gohar = repo.get_village("gohar")
    assert gohar.level == "warning" and gohar.data_status != "ok"
    # A village with good data and no rain is evaluated normally (one calm sweep, hysteresis still holds it).
    z003 = repo.get_village("z003")
    assert z003.data_status == "ok" and z003.level == "warning" and z003.calm_sweeps == 1
    assert all(repo.get_village(v).data_status == "ok" for v in results if v not in errors | {"gohar"})


def test_a_second_sweep_in_the_same_window_claims_nothing_twice(repo, frozen, workflow):
    """Each village claims its own 15-minute window (a conditional write), so two sweeps that overlap
    (a slow one and the next) evaluate each village once."""
    villages(repo, 30)
    fetched: list[str] = []
    lock = threading.Lock()

    def fetch(village, at):
        with lock:
            fetched.append(village.id)
        time.sleep(0.05)
        return make_reading(village, at, 0.0)

    first: list = []
    t = threading.Thread(target=lambda: first.extend(de.sweep_all(repo, now=frozen["now"], fetch=fetch,
                                                                  workflow=workflow)))
    t.start()
    second = de.sweep_all(repo, now=frozen["now"], fetch=fetch, workflow=workflow)
    t.join()
    assert sorted(fetched) == sorted(set(fetched)) and len(fetched) == 30
    evaluated = [r.village_id for r in first + second if not r.skipped]
    assert sorted(evaluated) == sorted(set(evaluated)) and len(evaluated) == 30
    assert all(r.note == "window already swept" for r in first + second if r.skipped)
