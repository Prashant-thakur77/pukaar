"""FloodNet-style device health: the maintenance playbook's visit reasons as automatic checks.

FloodNet NYC runs 350+ low-cost depth sensors and sends a technician when the dashboard shows a falling battery
profile, high packet loss (more than 20%) or wrong readings (github.com/floodnet-nyc/flood-sensor, maintenance).
Pukaar computes the same three from what its devices already send, per device:

  battery      a least-squares slope of the battery over the last BATTERY_WINDOW_HOURS (mV, or SoC % where the
               device reports it), and the days until it reaches empty at that slope. "battery_empty_in_<n>d"
               when that is BATTERY_WARN_DAYS or less. A solar device charges by day and drains by night: three
               days of samples average the cycle out; fewer than BATTERY_MIN_SAMPLES over BATTERY_MIN_SPAN_HOURS
               say nothing.
  packet loss  readings missing from the device's own sequence numbers (seq, per boot) over the last 24 hours:
               1 - received / expected. "packet_loss_<pct>pct" over PACKET_LOSS_LIMIT (20%), once at least
               PACKET_MIN_EXPECTED readings were expected. Only devices that number their readings (gauges, rain
               nodes) have it; a siren's heartbeats carry no sequence number.
  stuck        the same value STUCK_READINGS times running while rain falls: a sensor locked on a fixed echo
               (a branch, the bridge pier) reads steady while the river moves. "stuck_<n>_readings". In dry
               weather a steady river is normal, so it is not flagged.

Each adds a reason and makes an otherwise healthy device "degraded" (services/devices/registry.health), and a
gauge "gauge_unhealthy" (services/gauge.health). Missing data is never a reason: no samples, no claim.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

from Pukaar.core import clock

BATTERY_WINDOW_HOURS = 72
BATTERY_MIN_SAMPLES = 6
BATTERY_MIN_SPAN_HOURS = 12.0
BATTERY_WARN_DAYS = 7.0
EMPTY_MV = 3300.0  # one Li-ion cell at cut-off; a gauge uses its own low_battery_mv
EMPTY_SOC = 10.0
PACKET_WINDOW_HOURS = 24
PACKET_LOSS_LIMIT = 0.20
PACKET_MIN_EXPECTED = 10
STUCK_READINGS = 6
HISTORY_KEEP_HOURS = 7 * 24  # Device.batt_hist: one point an hour at most, a week kept
HISTORY_EVERY_MINUTES = 60


def battery_trend(points: Iterable[tuple[datetime, float]], empty: float, now: datetime,
                  unit: str = "mv") -> dict[str, Any] | None:
    """Slope per day and days to empty from (time, value) points within BATTERY_WINDOW_HOURS of now."""
    since = now - timedelta(hours=BATTERY_WINDOW_HOURS)
    pts = sorted((t, float(v)) for t, v in points if v is not None and since <= t <= now)
    if len(pts) < BATTERY_MIN_SAMPLES:
        return None
    t0 = pts[0][0]
    xs = [(t - t0).total_seconds() / 86400 for t, _ in pts]
    span_h = xs[-1] * 24
    if span_h < BATTERY_MIN_SPAN_HOURS:
        return None
    ys = [v for _, v in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx  # per day
    latest = ys[-1]
    days = round((latest - empty) / -slope, 1) if slope < 0 and latest > empty else (0.0 if latest <= empty else None)
    return {"unit": unit, "latest": round(latest, 1), "slope_per_day": round(slope, 1), "days_to_empty": days,
            "empty": empty, "samples": len(pts), "span_hours": round(span_h, 1)}


def packet_loss(pairs: Iterable[tuple[int | None, int | None]]) -> dict[str, Any] | None:
    """1 - received / expected from (boot, seq) pairs; a reboot starts a new count."""
    by_boot: dict[int, set[int]] = {}
    for boot, seq in pairs:
        if seq is None:
            continue
        by_boot.setdefault(int(boot or 0), set()).add(int(seq))
    if not by_boot:
        return None
    expected = sum(max(s) - min(s) + 1 for s in by_boot.values())
    received = sum(len(s) for s in by_boot.values())
    if expected < PACKET_MIN_EXPECTED:
        return {"expected": expected, "received": received, "loss": None}
    return {"expected": expected, "received": received, "loss": round(1 - received / expected, 3)}


def stuck_run(values: Iterable[float | None]) -> int:
    """How many of the newest values (oldest first in) are the same, to 0.1."""
    vals = [round(float(v), 1) for v in values if v is not None]
    if not vals:
        return 0
    run, last = 1, vals[-1]
    for v in reversed(vals[:-1]):
        if v != last:
            break
        run += 1
    return run


def signals(*, now: datetime, battery: list[tuple[datetime, float]] | None = None, empty: float = EMPTY_MV,
            unit: str = "mv", seqs: list[tuple[int | None, int | None]] | None = None,
            values: list[float | None] | None = None, raining: bool = False) -> dict[str, Any]:
    """The three checks and their reasons. Every input is optional; a missing one is "not measured"."""
    out: dict[str, Any] = {"battery": None, "packet_loss": None, "stuck": None, "raining": raining, "reasons": []}
    if battery:
        out["battery"] = trend = battery_trend(battery, empty, now, unit)
        if trend and trend["days_to_empty"] is not None and trend["days_to_empty"] <= BATTERY_WARN_DAYS:
            out["reasons"].append(f"battery_empty_in_{max(0, int(trend['days_to_empty']))}d")
    if seqs:
        out["packet_loss"] = loss = packet_loss(seqs)
        if loss and loss["loss"] is not None and loss["loss"] > PACKET_LOSS_LIMIT:
            out["reasons"].append(f"packet_loss_{int(round(loss['loss'] * 100))}pct")
    if values:
        run = stuck_run(values)
        out["stuck"] = {"run": run, "limit": STUCK_READINGS, "raining": raining}
        if raining and run >= STUCK_READINGS:
            out["reasons"].append(f"stuck_{run}_readings")
    return out


def append_history(hist: list[dict[str, Any]] | None, at: str, mv: float | None, soc: float | None) -> list[dict[str, Any]]:
    """Device.batt_hist with one more point: at most one an hour, a week kept, oldest first."""
    hist = [h for h in (hist or []) if isinstance(h, dict) and h.get("at")]
    if mv is None and soc is None:
        return hist
    t = clock.parse(at)
    if hist and t - clock.parse(str(hist[-1]["at"])) < timedelta(minutes=HISTORY_EVERY_MINUTES):
        return hist
    keep = t - timedelta(hours=HISTORY_KEEP_HOURS)
    hist = [h for h in hist if clock.parse(str(h["at"])) >= keep]
    point: dict[str, Any] = {"at": at}
    if mv is not None:
        point["mv"] = int(mv)
    if soc is not None:
        point["soc"] = int(soc)
    return [*hist, point]
