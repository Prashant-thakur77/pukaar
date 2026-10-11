"""A synthetic gauge record for tests only (never seeded into a real table).

`series()` builds an N-day stage record with a daily melt cycle, small noise and optional
injected faults and rain events, deterministic for a seed. `store()` writes it to a test table
with the same keys as Repo.put_sensor_reading, in one batch (the per-reading rate limit is for
devices, not for fixtures).
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

from Pukaar.core import clock
from Pukaar.store.models import SensorReading
from Pukaar.store.repo import _to_dynamo


def series(
    end: datetime,
    *,
    days: float = 14,
    step_min: int = 5,
    base_cm: float = 60.0,
    diurnal_cm: float = 8.0,
    noise_cm: float = 1.0,
    events: tuple[tuple[float, float, float], ...] = (),  # (day offset, peak rise cm, duration h)
    flat: tuple[int, int] | None = None,  # (start index, count): a stuck sensor repeats one value
    spikes: tuple[int, ...] = (),  # indices with a one-reading +400 cm echo
    clock_drift_s_per_day: float = 0.0,
    clock_offset_s: float = 2.0,
    battery_start_v: float = 4.1,
    battery_drop_v_per_day: float = 0.0,
    village_id: str = "thunag",
    device_id: str = "gauge-thunag-sim",
    simulated: bool = True,
    seed: int = 7,
) -> list[SensorReading]:
    rng = random.Random(seed)
    n = int(days * 24 * 60 / step_min)
    start = end - timedelta(minutes=step_min * (n - 1))
    out: list[SensorReading] = []
    stuck: float | None = None
    for i in range(n):
        at = start + timedelta(minutes=step_min * i)
        day = (at - start).total_seconds() / 86400
        hour = at.hour + at.minute / 60
        cm = base_cm + diurnal_cm * math.sin((hour - 9) / 24 * 2 * math.pi) + rng.gauss(0, noise_cm)
        for (d0, rise, hours) in events:
            dt_h = (day - d0) * 24
            if 0 <= dt_h <= hours:
                cm += rise * math.sin(math.pi * dt_h / hours)
        if flat and flat[0] <= i < flat[0] + flat[1]:
            stuck = stuck if stuck is not None else round(cm, 1)
            cm = stuck
        if i in spikes:
            cm += 400
        solar = 0.15 * max(0.0, math.sin((hour - 6) / 12 * math.pi))
        battery = battery_start_v - battery_drop_v_per_day * day + solar - 0.1
        offset = clock_offset_s + clock_drift_s_per_day * day
        out.append(SensorReading(
            village_id=village_id, device_id=device_id, at=clock.iso(at), water_level_cm=round(cm, 2),
            battery_v=round(battery, 3), simulated=simulated,
            received_at=clock.iso(at + timedelta(seconds=offset)),
        ))
    return out


def store(repo, readings: list[SensorReading]) -> None:
    with repo.t.batch_writer() as batch:
        for r in readings:
            item = {"pk": f"VILLAGE#{r.village_id}", "sk": f"SENSOR#{r.at}#{r.device_id}", **r.model_dump()}
            batch.put_item(Item=_to_dynamo(item))
