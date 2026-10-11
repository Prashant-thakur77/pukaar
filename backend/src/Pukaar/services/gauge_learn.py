"""Learning a gauge's stage thresholds from its own record, and finding sensor faults in it.

The seeded watch/warning/critical stages are illustrative. Once a gauge has enough of its own
readings (MIN_DAYS of record or MIN_READINGS readings, both configurable), this proposes stage
thresholds the same way the river thresholds come from each village's discharge record: high
percentiles of what this gauge has actually measured. It is a transparent statistical rule, not a
model, and it never applies itself: an officer reads the proposal and accepts it (or not), and the
change is audited old -> new (api/routers/gauges.py).

The proposal, step by step:
  1. drop readings that are clearly faults: the far end of an impossible jump (faster than
     watch.JUMP_CM_PER_MIN) and the repeats inside a long flat line (a stuck sensor);
  2. baseline = median of the daily minimum stages: the river's low flow in this record;
  3. raw thresholds = the p90 / p97 / p99.5 stages of the cleaned record (PERCENTILES);
  4. floors: watch >= baseline + BASELINE_MARGIN_CM, warning >= watch + MIN_SEPARATION_CM,
     critical >= warning + MIN_SEPARATION_CM; each value rounded up to a whole cm.
Every floor that moved a value is listed in `adjustments`.

What it cannot know: a record of a week or two outside the monsoon has not seen a flood, so its
p99.5 marks unusual water, not dangerous water. The proposal says so and shows the current values
beside it; the officer decides.

Faults are looked for across the whole record (watch.py checks only the last 24 hours):
  flatline  runs of identical readings lasting FLAT_LONG_MINUTES or more
  jump      changes faster than watch.JUMP_CM_PER_MIN
  clock     device clock offset (reading time vs. server receive time) above CLOCK_OFFSET_S, or
            drifting faster than CLOCK_DRIFT_S_PER_DAY
  battery   the daily peak voltage (after the solar charge) falling faster than
            BATTERY_DROP_V_PER_DAY, or the newest voltage under watch.LOW_BATTERY_V
  gaps      silences longer than GAP_MINUTES (power, coverage)
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import pairwise
from statistics import median
from typing import Any

from Pukaar.core import clock
from Pukaar.services import watch
from Pukaar.store.models import GaugeConfig, SensorReading

MIN_DAYS = 7.0
MIN_READINGS = 2000
WINDOW_DAYS = 14  # gauge readings live 14 days in the table (repo TTL)
MAX_READINGS = 25000
PERCENTILES = {"watch": 90.0, "warning": 97.0, "critical": 99.5}
BASELINE_MARGIN_CM = 30.0
MIN_SEPARATION_CM = 15.0
FLAT_LONG_MINUTES = 60
CLOCK_OFFSET_S = 90.0
CLOCK_DRIFT_S_PER_DAY = 20.0
BATTERY_DROP_V_PER_DAY = 0.03
GAP_MINUTES = 30
CURVE_POINTS = (0, 5, 10, 20, 30, 40, 50, 60, 70, 80, 85, 90, 93, 95, 97, 98, 99, 99.5, 100)
LEVEL_NAMES = ("watch", "warning", "critical")


@dataclass
class Fault:
    kind: str  # flatline | jump | clock_offset | clock_drift | battery_trend | battery_low | gaps
    severity: str  # warn | info
    count: int
    first_at: str | None
    last_at: str | None
    value: float | None
    message_en: str
    message_hi: str


def percentile(sorted_values: list[float], p: float) -> float:
    """Linear interpolation between closest ranks (numpy's default)."""
    if not sorted_values:
        raise ValueError("no values")
    k = (len(sorted_values) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def _t(r: SensorReading) -> datetime:
    return clock.parse(r.at)


def _minutes(a: SensorReading, b: SensorReading) -> float:
    return (_t(b) - _t(a)).total_seconds() / 60


def _slope_per_day(points: list[tuple[float, float]]) -> float | None:
    """Least-squares slope of (seconds, value) points, in value per day."""
    if len(points) < 3:
        return None
    n = len(points)
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points)
    if sxx == 0:
        return None
    return sum((p[0] - mx) * (p[1] - my) for p in points) / sxx * 86400


def _flat_runs(readings: list[SensorReading]) -> list[tuple[int, int]]:
    """(start, end) index pairs of runs within watch.FLAT_TOLERANCE_CM lasting FLAT_LONG_MINUTES."""
    runs, start = [], 0
    for i in range(1, len(readings) + 1):
        if i < len(readings) and abs(readings[i].water_level_cm - readings[start].water_level_cm) <= watch.FLAT_TOLERANCE_CM:
            continue
        if i - start >= 2 and _minutes(readings[start], readings[i - 1]) >= FLAT_LONG_MINUTES:
            runs.append((start, i - 1))
        start = i
    return runs


def _jumps(readings: list[SensorReading]) -> list[tuple[int, float, float]]:
    """(index of the reading after the jump, change cm, rate cm/min)."""
    out = []
    for i, (a, b) in enumerate(pairwise(readings), start=1):
        minutes = max(1.0, _minutes(a, b))
        rate = abs(b.water_level_cm - a.water_level_cm) / minutes
        if rate > watch.JUMP_CM_PER_MIN:
            out.append((i, b.water_level_cm - a.water_level_cm, rate))
    return out


def detect_faults(readings: list[SensorReading]) -> list[Fault]:
    """Faults across the whole record. readings: oldest first."""
    faults: list[Fault] = []
    if len(readings) < 2:
        return faults

    runs = _flat_runs(readings)
    if runs:
        longest = max(runs, key=lambda r: _minutes(readings[r[0]], readings[r[1]]))
        mins = _minutes(readings[longest[0]], readings[longest[1]])
        val = readings[longest[0]].water_level_cm
        faults.append(Fault("flatline", "warn", len(runs), readings[runs[0][0]].at, readings[runs[-1][1]].at, val,
                            f"Flat line: {len(runs)} stretch(es) of identical readings; the longest lasted "
                            f"{_span_en(mins)} at {val:g} cm. A stuck sensor; those repeats are left out of the proposal.",
                            f"एक जैसी रीडिंग: {len(runs)} बार; सबसे लंबी {_span_hi(mins)} तक {val:g} सेमी पर। "
                            "सेंसर अटका था; ये रीडिंग प्रस्ताव में नहीं गिनी गईं।"))

    jumps = _jumps(readings)
    if jumps:
        worst = max(jumps, key=lambda j: (j[2], j[1]))
        faults.append(Fault("jump", "warn", len(jumps), readings[jumps[0][0]].at, readings[jumps[-1][0]].at,
                            round(worst[1], 1),
                            f"Impossible jumps: {len(jumps)}; the worst was {worst[1]:+.0f} cm ({worst[2]:.0f} cm/min) "
                            f"at {readings[worst[0]].at[:16].replace('T', ' ')} UTC. Likely echoes off debris; "
                            "the readings after a jump are left out of the proposal.",
                            f"असंभव उछाल: {len(jumps)} बार; सबसे बड़ा {worst[1]:+.0f} सेमी ({worst[2]:.0f} सेमी/मिनट)। "
                            "शायद मलबे से गूँज; ये रीडिंग प्रस्ताव में नहीं गिनी गईं।"))

    offsets = [((_t(r) - clock.parse(readings[0].at)).total_seconds(),
                (clock.parse(r.received_at) - _t(r)).total_seconds()) for r in readings if r.received_at]
    if len(offsets) >= 10:
        med = median(o[1] for o in offsets)
        drift = _slope_per_day(offsets)
        if abs(med) > CLOCK_OFFSET_S:
            ahead = med < 0
            faults.append(Fault("clock_offset", "warn", len(offsets), readings[0].at, readings[-1].at, round(med, 1),
                                f"Device clock {'ahead of' if ahead else 'behind'} the server by about {abs(med):.0f} s "
                                "(median). Readings may be rejected as stale; set the clock from NTP.",
                                f"डिवाइस की घड़ी सर्वर से लगभग {abs(med):.0f} सेकंड {'आगे' if ahead else 'पीछे'}। "
                                "NTP से घड़ी ठीक करें।"))
        if drift is not None and abs(drift) > CLOCK_DRIFT_S_PER_DAY:
            faults.append(Fault("clock_drift", "warn", len(offsets), readings[0].at, readings[-1].at, round(drift, 1),
                                f"Device clock drifting about {abs(drift):.0f} s a day. It will soon fall outside the "
                                "five-minute window; resync it regularly.",
                                f"डिवाइस की घड़ी रोज़ लगभग {abs(drift):.0f} सेकंड खिसक रही है। नियमित रूप से ठीक करें।"))

    by_day: dict[str, list[SensorReading]] = {}
    for r in readings:
        if r.battery_v is not None:
            by_day.setdefault(r.at[:10], []).append(r)
    peaks = []
    fullest = max((len(rows) for rows in by_day.values()), default=0)
    for _day, rows in sorted(by_day.items()):
        if len(rows) < fullest / 2:
            continue  # a part day (the first or the last) may miss the midday charge
        top = max(rows, key=lambda r: r.battery_v or 0)
        peaks.append(((_t(top) - _t(readings[0])).total_seconds(), float(top.battery_v or 0)))
    slope = _slope_per_day(peaks) if len(peaks) >= 3 else None
    last_v = next((r.battery_v for r in reversed(readings) if r.battery_v is not None), None)
    if slope is not None and slope < -BATTERY_DROP_V_PER_DAY:
        low = watch.LOW_BATTERY_V
        if peaks[-1][1] > low:
            days_left = (peaks[-1][1] - low) / -slope
            when_en, when_hi = f"about {days_left:.0f} days to {low:g} V", f"लगभग {days_left:.0f} दिन में {low:g} V"
        else:
            when_en, when_hi = f"even its peak is already under {low:g} V", f"सबसे ऊँची वोल्टेज भी {low:g} V से कम"
        faults.append(Fault("battery_trend", "warn", len(peaks), readings[0].at, readings[-1].at, round(slope, 3),
                            f"Battery falling {abs(slope):.2f} V a day at its daily peak; {when_en}. "
                            "The solar panel may be dirty or shaded.",
                            f"बैटरी रोज़ {abs(slope):.2f} V घट रही है; {when_hi}। सोलर पैनल गंदा या छाया में हो सकता है।"))
    if last_v is not None and last_v < watch.LOW_BATTERY_V:
        faults.append(Fault("battery_low", "warn", 1, readings[-1].at, readings[-1].at, last_v,
                            f"Low battery now: {last_v:g} V.", f"बैटरी अभी कम: {last_v:g} V।"))

    gaps = [(a, b, _minutes(a, b)) for a, b in pairwise(readings) if _minutes(a, b) > GAP_MINUTES]
    if gaps:
        longest_gap = max(gaps, key=lambda g: g[2])
        total_h = sum(g[2] for g in gaps) / 60
        faults.append(Fault("gaps", "info", len(gaps), gaps[0][0].at, gaps[-1][1].at, round(longest_gap[2], 1),
                            f"Silences: {len(gaps)} longer than {GAP_MINUTES} min, {total_h:.1f} h in all; the longest "
                            f"{_span_en(longest_gap[2])} from {longest_gap[0].at[:16].replace('T', ' ')} UTC.",
                            f"चुप्पी: {GAP_MINUTES} मिनट से लंबी {len(gaps)} बार, कुल {total_h:.1f} घंटे; सबसे लंबी "
                            f"{_span_hi(longest_gap[2])}।"))
    return faults


def _span_en(minutes: float) -> str:
    return f"{minutes:.0f} min" if minutes < 120 else f"{minutes / 60:.1f} h"


def _span_hi(minutes: float) -> str:
    return f"{minutes:.0f} मिनट" if minutes < 120 else f"{minutes / 60:.1f} घंटे"


def clean(readings: list[SensorReading]) -> tuple[list[SensorReading], int]:
    """Readings without the obvious faults, and how many were left out."""
    drop: set[int] = set()
    for start, end in _flat_runs(readings):
        drop.update(range(start + 1, end + 1))  # keep one reading of a stuck stretch
    previous: tuple[int, float] | None = None
    for i, delta, _ in _jumps(readings):
        # The far side of a jump is suspect. A jump straight back the other way is the return
        # from a one-reading spike: that reading is good and stays.
        if previous is not None and previous[0] == i - 1 and previous[1] * delta < 0:
            previous = None
            continue
        drop.add(i)
        previous = (i, delta)
    kept = [r for i, r in enumerate(readings) if i not in drop]
    return kept, len(readings) - len(kept)


def _ceil_cm(v: float) -> float:
    return float(math.ceil(round(v, 6)))


def propose(readings: list[SensorReading], current: GaugeConfig | None, *, min_days: float = MIN_DAYS,
            min_readings: int = MIN_READINGS, percentiles: dict[str, float] | None = None,
            baseline_margin_cm: float = BASELINE_MARGIN_CM, min_separation_cm: float = MIN_SEPARATION_CM) -> dict[str, Any]:
    """A threshold proposal and the faults, from a gauge's readings (oldest first). Never applied here."""
    pct = {**PERCENTILES, **(percentiles or {})}
    readings = sorted(readings, key=lambda r: r.at)
    n = len(readings)
    days = (_t(readings[-1]) - _t(readings[0])).total_seconds() / 86400 if n >= 2 else 0.0
    cur = ({"watch_cm": current.watch_cm, "warning_cm": current.warning_cm, "critical_cm": current.critical_cm,
            "source": current.thresholds_source, "set_by": current.thresholds_set_by,
            "set_at": current.thresholds_set_at} if current else None)
    basis: dict[str, Any] = {
        "readings": n, "days": round(days, 2), "from": readings[0].at if n else None, "to": readings[-1].at if n else None,
        "min_days": min_days, "min_readings": min_readings, "simulated": any(r.simulated for r in readings),
    }
    faults = [asdict(f) for f in detect_faults(readings)]
    out: dict[str, Any] = {"status": "insufficient", "basis": basis, "current": cur, "faults": faults,
                           "percentiles": pct, "never_auto_applied": True}
    if days < min_days and n < min_readings:
        out["note_en"] = (f"Not enough of this gauge's own record yet: {days:.1f} of {min_days:g} days and {n} of "
                          f"{min_readings} readings. Thresholds stay as they are.")
        out["note_hi"] = (f"अभी इस गेज का अपना रिकॉर्ड काफ़ी नहीं: {min_days:g} में से {days:.1f} दिन और {min_readings} में "
                          f"से {n} रीडिंग। सीमाएँ जैसी हैं वैसी रहेंगी।")
        return out

    kept, excluded = clean(readings)
    values = sorted(r.water_level_cm for r in kept)
    daily_min: dict[str, float] = {}
    daily: dict[str, list[float]] = {}
    for r in kept:
        d = r.at[:10]
        daily.setdefault(d, []).append(r.water_level_cm)
        daily_min[d] = min(daily_min.get(d, r.water_level_cm), r.water_level_cm)
    baseline = median(daily_min.values())
    raw = {name: percentile(values, pct[name]) for name in LEVEL_NAMES}
    proposed: dict[str, float] = {}
    adjustments: list[dict[str, Any]] = []
    floor = baseline + baseline_margin_cm
    for name in LEVEL_NAMES:
        value = _ceil_cm(raw[name])
        if value < floor:
            why = ("baseline + margin" if name == "watch" else f"{LEVEL_NAMES[LEVEL_NAMES.index(name) - 1]} + separation")
            adjustments.append({"level": name, "from": value, "to": _ceil_cm(floor), "rule": why})
            value = _ceil_cm(floor)
        proposed[name] = value
        floor = value + min_separation_cm
    basis.update(used=len(kept), excluded=excluded)
    out.update(
        status="ready",
        baseline_cm=round(baseline, 1),
        baseline_rule=f"median of daily minimum stages + {baseline_margin_cm:g} cm margin",
        min_separation_cm=min_separation_cm,
        raw={k: round(v, 1) for k, v in raw.items()},
        proposed={f"{k}_cm": v for k, v in proposed.items()},
        adjustments=adjustments,
        curve=[{"p": p, "cm": round(percentile(values, p), 1)} for p in CURVE_POINTS],
        daily=[{"date": d, "min": round(min(v), 1), "median": round(median(v), 1), "max": round(max(v), 1)}
               for d, v in sorted(daily.items())],
        note_en=(f"Proposed from {days:.1f} days ({len(kept)} readings) of this gauge's own record. A record this short "
                 "may not include a flood: p99.5 marks unusual water, not necessarily dangerous water. Compare with "
                 "known flood marks at the bridge before accepting. Nothing changes until an officer accepts."),
        note_hi=(f"इस गेज के अपने {days:.1f} दिन ({len(kept)} रीडिंग) के रिकॉर्ड से प्रस्ताव। इतने छोटे रिकॉर्ड में बाढ़ शायद "
                 "न हो: p99.5 असामान्य पानी बताता है, ज़रूरी नहीं कि ख़तरनाक। स्वीकार करने से पहले पुल पर बाढ़ के पुराने निशान "
                 "देखें। अधिकारी के स्वीकार करने तक कुछ नहीं बदलता।"),
    )
    return out


def matches(proposal: dict[str, Any], watch_cm: float, warning_cm: float, critical_cm: float,
            tolerance_cm: float = 5.0) -> bool:
    """Values a client sent as "accept the proposal" are the proposal (readings move it a little)."""
    if proposal.get("status") != "ready":
        return False
    p = proposal["proposed"]
    return all(abs(p[f"{k}_cm"] - v) <= tolerance_cm
               for k, v in (("watch", watch_cm), ("warning", warning_cm), ("critical", critical_cm)))


def basis_text(proposal: dict[str, Any]) -> str:
    b = proposal["basis"]
    pct = proposal["percentiles"]
    return (f"learned from {b['days']:.1f} days ({b.get('used', b['readings'])} readings) of the gauge's own record, "
            f"p{pct['watch']:g}/p{pct['warning']:g}/p{pct['critical']:g}, baseline {proposal['baseline_cm']:g} cm"
            + (" (simulated readings)" if b.get("simulated") else ""))
