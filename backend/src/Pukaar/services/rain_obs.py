"""Observed rain (`rain_obs`): the tipping bucket of a gauge v3 or a rain-only node, as a level source.

The forecast missed all three Mandi cloudbursts of 2025 (docs/SCORING.md); a bucket in the khad's upper
catchment sees the burst as it falls. This rule turns its counts into a level, carefully:

Series. Each reading's rain = (tips_total - the previous reading's tips_total) x mm_per_tip (the server's
calibration, one source of truth). A counter that went backwards (a reboot, a lost counter) falls back to
the reading's own tips_window. A gap is spread over the time it covers. The intensity correction for the
water lost while the bucket tips: mm = mm_raw x (1 + c x max(0, I - i0)), I the reading's rate in mm/h
(c = 0.0005: +5 % at 150 mm/h). Raw values are kept too.

Bands (RainGaugeConfig, ILLUSTRATIVE until calibrated per khad with IMD/HPSDMA): corrected totals over the
last 15 min, 1 h and 3 h from live, good readings only. A band counts only when it is reached in 2 of the
last 3 evaluations (the rain analogue of the gauge's 2 of 3).

Guarantees (risk_rules.assess):
- it enters through _max(): it raises a level and never lowers one;
- on its own it reaches Warning at most (windows at twice the Warning band are tagged
  rain_obs_capped:warning); Critical needs a second, independent source;
- forecast rain and observed rain are one hazard seen twice: never "two sources agree" between them;
- missing, suspect, stuck, simulated or backfilled observed rain counts as nothing, with a tag; it is never
  a calm sweep beyond what the hysteresis already does.

Quality. Chatter: the shortest tip interval under min_tip_ms with 3 or more bounces, a 5-minute rate above
max_plausible_mm_h, or bounces above 10 % of the tips; error bits 2 (counter reset) and 4 (ULP fault).
Stuck: no tip in 3 h while the forecast had >= 5 mm/h in each of those hours, or the same site's river
stage rose >= 30 cm (RainGaugeSuspect, "clean the funnel"). "Neighbours and the forecast are dry" is NOT a
guard: cloudbursts are local; the Warning cap and the officer's approval handle that case.

A reading at Watch or above re-runs the village's rules at once (only to raise), as a gauge reading does.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from Pukaar.core import clock
from Pukaar.core.log import get_logger, log, metric
from Pukaar.store.models import LEVELS, RainGaugeConfig, RainReading, Reading, Village, level_rank
from Pukaar.store.repo import Repo

_LOG = get_logger("rain_obs")
WINDOWS: tuple[tuple[str, int], ...] = (("15min", 15), ("1h", 60), ("3h", 180))
LOOKBACK_MINUTES = 200
FRESH_MINUTES = 30
CONFIRM_NEEDED, CONFIRM_WINDOW = 2, 3
CONFIRM_SPAN_MINUTES = 20  # the three evaluations must be this recent
DEFAULT_INTERVAL_MINUTES = 5.0
CRITICAL_FACTOR = 2.0  # windows at twice the Warning band: what observed rain alone would call Critical
STUCK_HOURS = 3
STUCK_FORECAST_MM_H = 5.0
STUCK_STAGE_RISE_CM = 30.0
CHATTER_MIN_BOUNCES = 3
ERR_COUNTER_RESET, ERR_ULP_FAULT = 2, 4


class RainFields(BaseModel):
    """A rain-only node's payload: payload v3 without a river measurement (same topic as a gauge)."""

    model_config = ConfigDict(extra="ignore")

    at: str = Field(max_length=40)
    simulated: bool = False
    v: int | None = Field(default=None, ge=1, le=3)
    seq: int | None = Field(default=None, ge=0, le=4_294_967_295)
    boot: int | None = Field(default=None, ge=0, le=4_294_967_295)
    rain_tips_total: int | None = Field(default=None, ge=0, le=4_294_967_295)
    rain_tips_window: int | None = Field(default=None, ge=0, le=100_000)
    rain_mm_per_tip: float | None = Field(default=None, gt=0, le=2)
    rain_max_tips_1min: int | None = Field(default=None, ge=0, le=10_000)
    rain_min_tip_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    rain_bounce: int | None = Field(default=None, ge=0, le=100_000)
    rain_err: int | None = Field(default=None, ge=0, le=65_535)
    battery_v: float | None = Field(default=None, ge=0, le=20)
    battery_mv: float | None = Field(default=None, ge=0, le=20_000)
    rssi: int | None = Field(default=None, ge=-150, le=0)
    fw: str | None = Field(default=None, max_length=32, pattern=r"^[A-Za-z0-9_.+-]+$")
    buffered: bool = False


def has_rain(fields: Any) -> bool:
    return getattr(fields, "rain_tips_total", None) is not None or getattr(fields, "rain_tips_window", None) is not None


def config(village: Village) -> RainGaugeConfig:
    return (village.gauge.rain if village.gauge and village.gauge.rain else None) or RainGaugeConfig()


def band(windows: dict[str, float], cfg: RainGaugeConfig) -> tuple[str, dict[str, Any] | None, bool]:
    """(level, the window that set it, whether the windows reach twice the Warning band)."""
    level, hit = "normal", None
    for name, _ in WINDOWS:
        mm = windows.get(name)
        if mm is None:
            continue
        for lvl in ("warning", "watch"):
            threshold = getattr(cfg, f"{lvl}_{name}")
            if mm >= threshold and level_rank(lvl) > level_rank(level):
                level, hit = lvl, {"window": name, "mm": round(mm, 1), "threshold_mm": threshold}
    critical_like = any(windows.get(n) is not None and windows[n] >= CRITICAL_FACTOR * getattr(cfg, f"warning_{n}")
                        for n, _ in WINDOWS)
    return level, hit, critical_like


def window_totals(points: list[tuple[datetime, datetime, float]], end: datetime) -> dict[str, float]:
    """Corrected totals over each window ending at `end`; a reading's rain is spread over the time it covers."""
    out = {}
    for name, minutes in WINDOWS:
        start = end - timedelta(minutes=minutes)
        total = 0.0
        for a, b, mm in points:
            span = (b - a).total_seconds()
            if span <= 0 or mm <= 0:
                continue
            overlap = (min(b, end) - max(a, start)).total_seconds()
            if overlap > 0:
                total += mm * overlap / span
        out[name] = round(total, 2)
    return out


def _quality(fields: Any, tips: int, rate: float, cfg: RainGaugeConfig, reset: bool) -> list[str]:
    reasons = []
    bounce = getattr(fields, "rain_bounce", None) or 0
    min_tip = getattr(fields, "rain_min_tip_ms", None)
    if min_tip is not None and min_tip < cfg.min_tip_ms and bounce >= CHATTER_MIN_BOUNCES:
        reasons.append(f"chatter:min_tip_{min_tip}ms")
    if rate > cfg.max_plausible_mm_h:
        reasons.append(f"chatter:rate_{rate:.0f}mm_h")
    if tips > 0 and bounce > 0.1 * tips:
        reasons.append(f"chatter:bounce_{bounce}_of_{tips}")
    err = getattr(fields, "rain_err", None) or 0
    if err & ERR_ULP_FAULT:
        reasons.append("err:ulp_fault")
    if (err & ERR_COUNTER_RESET) and not reset:
        reasons.append("err:counter_reset")
    return reasons


def ingest(repo: Repo, village: Village, device_id: str, fields: Any, at: datetime, *, now: datetime,
           transport: str, origin: str = "live", source: str = "gauge") -> RainReading | None:
    """Work out and store one rain reading. Returns it, or None when it was already stored."""
    cfg = config(village)
    at_iso = clock.iso(at)
    history = [r for r in repo.list_rain_readings(village.id, clock.iso(at - timedelta(minutes=LOOKBACK_MINUTES)))
               if r.device_id == device_id and r.origin == "live" and r.at < at_iso]
    prev = history[-1] if history else None
    total, window = getattr(fields, "rain_tips_total", None), getattr(fields, "rain_tips_window", None)
    reset = False
    if prev is not None and prev.tips_total is not None and total is not None and origin == "live":
        tips = total - prev.tips_total
        if tips < 0:  # a reboot or a lost counter: the reading's own window count
            tips, reset = int(window or 0), True
    else:
        tips = int(window or 0)
    minutes = DEFAULT_INTERVAL_MINUTES
    if prev is not None and origin == "live":
        minutes = max(1.0, (at - clock.parse(prev.at)).total_seconds() / 60)
    mm_raw = tips * cfg.mm_per_tip
    rate = mm_raw / minutes * 60
    mm = mm_raw * (1 + cfg.correction_c * max(0.0, rate - cfg.i0_mm_h))
    reasons = _quality(fields, tips, rate, cfg, reset)
    battery = getattr(fields, "battery_v", None)
    if battery is None and getattr(fields, "battery_mv", None) is not None:
        battery = round(fields.battery_mv / 1000, 3)
    r = RainReading(
        village_id=village.id, device_id=device_id, at=at_iso, source=source, origin=origin,  # type: ignore[arg-type]
        simulated=bool(getattr(fields, "simulated", False)) or device_id.endswith("-sim"), received_at=clock.iso(now),
        transport=transport, seq=getattr(fields, "seq", None), boot=getattr(fields, "boot", None),  # type: ignore[arg-type]
        tips_total=total, tips_window=window, device_mm_per_tip=getattr(fields, "rain_mm_per_tip", None),
        max_tips_1min=getattr(fields, "rain_max_tips_1min", None), min_tip_ms=getattr(fields, "rain_min_tip_ms", None),
        bounce=getattr(fields, "rain_bounce", None), err=getattr(fields, "rain_err", None), battery_v=battery,
        rssi=getattr(fields, "rssi", None), fw=getattr(fields, "fw", None), tips=tips, minutes=round(minutes, 2),
        mm_raw=round(mm_raw, 3), mm=round(mm, 3), rate_mm_h=round(rate, 1),
        quality="suspect" if reasons else "good", quality_reasons=reasons)
    if origin == "live":
        good = [h for h in history if h.quality == "good"]
        points = [(clock.parse(h.at) - timedelta(minutes=h.minutes), clock.parse(h.at), h.mm) for h in good]
        if r.quality == "good":
            points.append((at - timedelta(minutes=minutes), at, r.mm))
        r.windows = window_totals(points, at)
        r.eval_level, _, _ = band(r.windows, cfg) if r.quality == "good" else ("normal", None, False)
        recent = [h for h in history if (at - clock.parse(h.at)).total_seconds() <= CONFIRM_SPAN_MINUTES * 60]
        evals = [h.eval_level for h in recent[-(CONFIRM_WINDOW - 1):]] + [r.eval_level]
        r.confirmed_level = "normal"
        for lvl in reversed(LEVELS[1:]):
            if sum(1 for e in evals if level_rank(e) >= level_rank(lvl)) >= CONFIRM_NEEDED:
                r.confirmed_level = lvl
                break
    if not repo.put_rain_reading(r):
        return None
    if r.quality != "good":
        metric("RainBadReading", 1)
    return r


def _forecast_wet(repo: Repo, village_id: str, now: datetime) -> bool:
    """The forecast had >= 5 mm/h at the village cell in each of the last 3 hours (the newest forecast of each hour)."""
    hours: dict[int, float] = {}
    first = int((now - timedelta(hours=STUCK_HOURS)).timestamp() // 3600)
    last = int(now.timestamp() // 3600)
    for reading in reversed(repo.list_readings(village_id, limit=16)):  # oldest first: newer forecasts overwrite
        if reading.replay:
            continue
        for p in reading.rain_hourly or []:
            try:
                key = int(clock.parse(str(p.get("t"))).timestamp() // 3600)
            except (ValueError, TypeError):
                continue
            if first <= key < last and p.get("mm") is not None:
                hours[key] = float(p["mm"])
    return len(hours) >= STUCK_HOURS and all(v >= STUCK_FORECAST_MM_H for v in hours.values())


def _stage_rose(repo: Repo, village: Village, now: datetime) -> bool:
    if village.gauge is None:
        return False
    rows = [r for r in repo.list_sensor_readings(village.id, clock.iso(now - timedelta(hours=STUCK_HOURS)))
            if r.device_id == village.gauge.device_id and r.origin == "live" and r.quality == "good"]
    if len(rows) < 2:
        return False
    low = min(r.water_level_cm for r in rows)
    return rows[-1].water_level_cm - low >= STUCK_STAGE_RISE_CM


def village_info(repo: Repo, village: Village, now: datetime, *, forecast: Reading | None = None) -> dict[str, Any] | None:
    """What the rules read: per device its newest fresh live reading, and whether its bucket looks stuck.
    None when the village has no rain reading at all in the look-back."""
    rows = [r for r in repo.list_rain_readings(village.id, clock.iso(now - timedelta(minutes=LOOKBACK_MINUTES)))
            if r.origin == "live" and clock.parse(r.at) <= now + timedelta(minutes=5)]
    if not rows:
        return None
    cfg = config(village)
    by_device: dict[str, list[RainReading]] = {}
    for r in rows:
        by_device.setdefault(r.device_id, []).append(r)
    devices = []
    wet = None
    for device_id, series in by_device.items():
        latest = series[-1]
        fresh = (now - clock.parse(latest.at)).total_seconds() <= FRESH_MINUTES * 60
        covers = (now - clock.parse(series[0].at)).total_seconds() >= (STUCK_HOURS * 60 - 15) * 60
        stuck = False
        if covers and sum(r.tips for r in series if (now - clock.parse(r.at)).total_seconds() <= STUCK_HOURS * 3600) == 0:
            if wet is None:
                wet = _forecast_wet(repo, village.id, now)
            stuck = wet or (latest.source == "gauge" and _stage_rose(repo, village, now))
        _, hit, critical_like = band(latest.windows, cfg)
        devices.append({"device_id": device_id, "source": latest.source, "at": latest.at, "fresh": fresh,
                        "simulated": latest.simulated, "quality": latest.quality,
                        "quality_reasons": latest.quality_reasons, "stuck": stuck, "windows": latest.windows,
                        "eval_level": latest.eval_level if fresh else "normal",
                        "confirmed_level": latest.confirmed_level if fresh else "normal", "hit": hit,
                        "critical_like": critical_like and fresh, "rate_mm_h": latest.rate_mm_h})
        if stuck:
            metric("RainGaugeSuspect", 1, Reason="stuck")
            log(_LOG, "rain gauge looks stuck: clean the funnel", 30, village_id=village.id, device_id=device_id)
    return {"devices": devices, "bands": cfg.model_dump(include={f"{lvl}_{n}" for lvl in ("watch", "warning")
                                                                 for n, _ in WINDOWS}),
            "thresholds_source": cfg.thresholds_source}


def view(repo: Repo, village: Village, now: datetime | None = None) -> dict[str, Any] | None:
    """The village page and /sensors: each device's windows and bands, quality, and 24 h of readings."""
    now = now or clock.now()
    info = village_info(repo, village, now)
    if info is None:
        return None
    series = repo.list_rain_readings(village.id, clock.iso(now - timedelta(hours=24)))
    step = max(1, -(-len(series) // 288))
    info["series"] = [{"at": r.at, "device_id": r.device_id, "mm": r.mm, "mm_raw": r.mm_raw,
                       "q": r.quality if r.quality != "good" else None, "backfill": r.origin == "backfill" or None}
                      for r in series[::step]]
    level = "normal"
    for d in info["devices"]:
        if not d["simulated"] and d["quality"] == "good" and not d["stuck"]:
            level = max(level, d["confirmed_level"], key=level_rank)
    info["level"] = level
    info["simulated_level"] = max((d["confirmed_level"] for d in info["devices"] if d["simulated"]),
                                  key=level_rank, default="normal")
    return info


def safe_view(repo: Repo, village: Village) -> dict[str, Any] | None:
    try:
        return view(repo, village)
    except Exception as exc:
        log(_LOG, "rain view failed", 30, village_id=village.id, error=str(exc)[:200])
        return None
