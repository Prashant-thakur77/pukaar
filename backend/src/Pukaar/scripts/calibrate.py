"""Calibrate the river trigger: pick each village's river cell, then fit return-period thresholds.

River cell (`--cells`). The Open-Meteo flood API (GloFAS v4, 0.05° cells) snaps a coordinate to
the nearest model cell, and the cell under a village is often a tiny hillside cell rather than
the stream that floods it. `--cells` lists every cell whose centre is within SEARCH_RADIUS_KM of
the village, with its mean and maximum daily discharge over RANK_WINDOW, into
data/river_cells.json (`candidates`). The rule for the choice is the largest long-term mean flow
within that radius; the choice itself (`chosen`: cell, river name, upstream reasoning,
cell_verified) is written by hand into the same file after reading the candidates against a map,
and `--cells` keeps it when it refreshes the candidates.

Thresholds (default run). For the chosen cell, the annual maxima of daily discharge for each
calendar year of the record (1984-2024 is requested; at these cells the archive has values from
1997, so n = 28 years; years with fewer than 330 days are dropped) are fitted with a Gumbel (EV1)
distribution by the method of L-moments (Hosking 1990), the method GloFAS uses for its own
return-period thresholds:

    l1 = mean,  l2 = 2*b1 - b0,  b1 = sum((i-1)/(n-1) * x_(i)) / n  (x ascending, i = 1..n)
    beta = l2 / ln 2,  mu = l1 - 0.5772 * beta
    Q_T = mu - beta * ln(-ln(1 - 1/T))

Watch = 2-year, Warning = 5-year, Critical = 20-year. The earlier percentile thresholds (90th,
97th and 99.5th of all daily flows at the village-point cell) are kept in `percentile` for
comparison. The 90th percentile at the chosen cell is also written as `early_cms`: the get-ready
line the readiness outlook reads (services/readiness.py), never a level. Writes data/thresholds.json.

Days at Watch (`--watch-days`): for 2019-2024, the days each year on which the sweep would have
held Watch or above with a perfect river forecast (the peak of today and the next
DISCHARGE_LOOKAHEAD_DAYS days at or above the Watch threshold), before (village-point cell,
percentile thresholds) and after (chosen cell, return-period thresholds). Written into
data/thresholds.json under `watch_days`.

Soil range (`soil: {dry, wet}`): the 5th and 95th percentiles of two years of hourly root-zone
soil moisture (mean of the 9-27 cm and 27-81 cm layers) from the Open-Meteo historical-forecast
API: the same layers and model family the live sweep reads.

    python -m Pukaar.scripts.calibrate --cells        # candidate river cells -> data/river_cells.json
    python -m Pukaar.scripts.calibrate                # return periods for the chosen cells (soil kept)
    python -m Pukaar.scripts.calibrate --watch-days   # days a year at Watch, before and after
    python -m Pukaar.scripts.calibrate --soil         # soil range only, river thresholds kept

The free Open-Meteo tier weights a request by its length (about one call per two weeks of data),
so a 41-year series costs on the order of a thousand calls: the script fetches one cell at a time
and waits out the per-minute limit.
"""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import date
from pathlib import Path

import httpx

from Pukaar.core.config import get_settings
from Pukaar.services import soil
from Pukaar.services.external_data import DISCHARGE_LOOKAHEAD_DAYS, FLOOD_URL

PERCENTILES = {"watch": 0.90, "warning": 0.97, "critical": 0.995}
EARLY_LINE = ("Get-ready line: the 90th percentile of daily discharge at the river cell (the statistic the earlier Watch line used). "
              "Only the readiness outlook reads it; it never sets a level, never creates an alert and never sends.")
RETURN_PERIODS = {"watch": 2, "warning": 5, "critical": 20}
HISTORY = ("1984-01-01", "2024-12-31")
RANK_WINDOW = ("2015-01-01", "2024-12-31")
WATCH_DAYS_WINDOW = ("2019-01-01", "2024-12-31")
SEARCH_RADIUS_KM = 7.0
CELL_DEG = 0.05
MIN_DAYS_PER_YEAR = 330
EULER_GAMMA = 0.5772156649
HIST_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
SOIL_HISTORY = ("2024-01-01", "2025-12-31")
SOIL_PERCENTILES = {"dry": 0.05, "wet": 0.95}
METHOD = ("Gumbel (EV1) fitted by L-moments to calendar-year maxima of daily river discharge, "
          "Open-Meteo flood API (GloFAS v4 reanalysis) {start}..{end}; watch/warning/critical = 2/5/20-year")


# -- statistics -----------------------------------------------------------------
def percentile(sorted_values: list[float], p: float) -> float:
    """Linear-interpolated percentile of an ascending list."""
    if not sorted_values:
        raise ValueError("empty series")
    k = (len(sorted_values) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def thresholds_for(values: list[float]) -> dict[str, float]:
    """The earlier method, kept for comparison: percentiles of all daily flows."""
    ordered = sorted(values)
    return {name: round(percentile(ordered, p), 3) for name, p in PERCENTILES.items()}


def annual_maxima(pairs: list[tuple[str, float]], min_days: int = MIN_DAYS_PER_YEAR) -> list[tuple[int, float]]:
    """(year, highest daily discharge) for each calendar year with at least min_days values."""
    by_year: dict[int, list[float]] = {}
    for day, q in pairs:
        by_year.setdefault(int(day[:4]), []).append(q)
    return [(y, max(qs)) for y, qs in sorted(by_year.items()) if len(qs) >= min_days]


def gumbel_fit(maxima: list[float]) -> tuple[float, float]:
    """(mu, beta) of a Gumbel distribution by the method of L-moments."""
    x = sorted(maxima)
    n = len(x)
    if n < 10:
        raise ValueError(f"need at least 10 annual maxima, got {n}")
    b0 = sum(x) / n
    b1 = sum(i / (n - 1) * v for i, v in enumerate(x)) / n
    l2 = 2 * b1 - b0
    beta = l2 / math.log(2)
    if beta <= 0:
        raise ValueError("flat series: no spread to fit")
    return b0 - EULER_GAMMA * beta, beta


def return_level(mu: float, beta: float, years: float) -> float:
    """The discharge exceeded on average once every `years` years (annual-maximum series)."""
    return mu - beta * math.log(-math.log(1 - 1 / years))


def return_period_thresholds(maxima: list[float]) -> dict:
    mu, beta = gumbel_fit(maxima)
    levels = {name: round(return_level(mu, beta, t), 3) for name, t in RETURN_PERIODS.items()}
    return {**levels, "gumbel": {"mu": round(mu, 4), "beta": round(beta, 4), "n_years": len(maxima)},
            "return_period_years": dict(RETURN_PERIODS)}


def top_events(pairs: list[tuple[str, float]], n: int = 3, gap_days: int = 10) -> list[dict]:
    """The n highest daily discharges, at least gap_days apart (one per flood)."""
    chosen: list[tuple[str, float]] = []
    for day, q in sorted(pairs, key=lambda x: -x[1]):
        if all(abs((date.fromisoformat(day) - date.fromisoformat(c)).days) > gap_days for c, _ in chosen):
            chosen.append((day, q))
        if len(chosen) == n:
            break
    return [{"date": d, "discharge": round(q, 2)} for d, q in chosen]


def days_at_or_above(pairs: list[tuple[str, float]], threshold: float,
                     lookahead: int = DISCHARGE_LOOKAHEAD_DAYS) -> dict[str, dict[str, int]]:
    """Per calendar year: the days on which max(today .. today+lookahead) >= threshold (the days a
    sweep with a perfect forecast of this series would hold the level), and the episodes (runs of
    such days, counted in the year they start: each is one rise, so one alert to approve)."""
    values = [q for _, q in pairs]
    days: dict[str, int] = {}
    episodes: dict[str, int] = {}
    previous = False
    for i, (day, _) in enumerate(pairs):
        year = day[:4]
        days.setdefault(year, 0)
        episodes.setdefault(year, 0)
        flagged = max(values[i:i + lookahead + 1]) >= threshold
        if flagged:
            days[year] += 1
            if not previous:
                episodes[year] += 1
        previous = flagged
    return {"days": days, "episodes": episodes}


def soil_range(hourly: dict) -> dict | None:
    """dry/wet = p5/p95 of the hourly root-zone mean; None when there is too little data."""
    values = [v for v in (soil.root_zone(hourly, i) for i in range(len(hourly.get("time", [])))) if v is not None]
    if len(values) < 24 * 90:
        return None
    ordered = sorted(values)
    rng = {name: round(percentile(ordered, p), 3) for name, p in SOIL_PERCENTILES.items()}
    if rng["wet"] - rng["dry"] < 0.02:
        return None  # a flat series cannot say what "wet" means here
    return {**rng, "hours": len(values),
            "source": f"open-meteo historical-forecast hourly {'+'.join(soil.LAYERS)} mean, "
                      f"{SOIL_HISTORY[0]}..{SOIL_HISTORY[1]}, percentiles 5/95"}


# -- cells ----------------------------------------------------------------------
def km_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Equirectangular distance; good to a few metres over a few km."""
    dy = (lat1 - lat2) * 111.2
    dx = (lon1 - lon2) * 111.2 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def cell_centres(lat: float, lon: float, radius_km: float = SEARCH_RADIUS_KM) -> list[tuple[float, float, float]]:
    """(lat, lon, km) of every 0.05° cell centre within radius_km, nearest first."""
    out = []
    reach = int(radius_km / (CELL_DEG * 90)) + 2
    base_lat = math.floor(lat / CELL_DEG) * CELL_DEG + CELL_DEG / 2
    base_lon = math.floor(lon / CELL_DEG) * CELL_DEG + CELL_DEG / 2
    for i in range(-reach, reach + 1):
        for j in range(-reach, reach + 1):
            clat, clon = round(base_lat + i * CELL_DEG, 3), round(base_lon + j * CELL_DEG, 3)
            d = km_between(lat, lon, clat, clon)
            if d <= radius_km:
                out.append((clat, clon, round(d, 2)))
    return sorted(out, key=lambda c: c[2])


def suggest_cell(candidates: list[dict]) -> dict | None:
    """The rule: the candidate with the largest long-term mean flow."""
    usable = [c for c in candidates if c.get("mean") is not None]
    return max(usable, key=lambda c: c["mean"]) if usable else None


# -- fetching -------------------------------------------------------------------
def _get(client: httpx.Client, params: dict, url: str = FLOOD_URL) -> dict:
    for attempt in range(8):
        r = client.get(url, params=params)
        if r.status_code == 429:
            time.sleep(min(70, 10 * 2 ** attempt))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("rate limited by the flood API")


def fetch_series(client: httpx.Client, lat: float, lon: float, start: str, end: str) -> tuple[list[tuple[str, float]], dict]:
    data = _get(client, {"latitude": lat, "longitude": lon, "daily": "river_discharge", "start_date": start,
                         "end_date": end})
    pairs = [(d, float(q)) for d, q in zip(data["daily"]["time"], data["daily"]["river_discharge"]) if q is not None]
    return pairs, {"lat": data.get("latitude"), "lon": data.get("longitude")}


def fetch_soil(client: httpx.Client, v: dict) -> dict | None:
    data = _get(client, {"latitude": v["lat"], "longitude": v["lon"], "hourly": ",".join(soil.LAYERS),
                         "start_date": SOIL_HISTORY[0], "end_date": SOIL_HISTORY[1], "timezone": "GMT"},
                HIST_FORECAST_URL)
    return soil_range(data.get("hourly", {}))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def search_cells(client: httpx.Client, villages: list[dict], cells_path: Path) -> None:
    current = _load(cells_path)
    current.setdefault("_note", "")
    for v in villages:
        rows = []
        for clat, clon, d in cell_centres(v["lat"], v["lon"]):
            pairs, cell = fetch_series(client, clat, clon, *RANK_WINDOW)
            qs = [q for _, q in pairs]
            rows.append({"lat": cell["lat"], "lon": cell["lon"], "km": d,
                         "mean": round(sum(qs) / len(qs), 3) if qs else None, "max": round(max(qs), 2) if qs else None,
                         "days": len(qs)})
            time.sleep(2)
        rows.sort(key=lambda r: -(r["mean"] or 0))
        entry = current.setdefault("villages", {}).setdefault(v["id"], {})
        entry["village"] = {"lat": v["lat"], "lon": v["lon"]}
        entry["candidates"] = rows
        entry["rule_suggests"] = {k: suggest_cell(rows)[k] for k in ("lat", "lon", "mean")} if suggest_cell(rows) else None
        print(v["id"], "suggested", entry["rule_suggests"])
        _write(cells_path, current)  # after each village: a rate limit later loses nothing
    current["search"] = {"radius_km": SEARCH_RADIUS_KM, "window": list(RANK_WINDOW), "rule": "largest mean daily flow"}
    _write(cells_path, current)


def chosen_cell(cells: dict, village_id: str) -> dict | None:
    return (cells.get("villages", {}).get(village_id) or {}).get("chosen")


def calibrate_rivers(client: httpx.Client, villages: list[dict], cells: dict, path: Path) -> None:
    current = _load(path)
    for v in villages:
        chosen = chosen_cell(cells, v["id"])
        if chosen is None:
            print(v["id"], "no chosen river cell in data/river_cells.json; run --cells and choose one")
            continue
        pairs, cell = fetch_series(client, chosen["lat"], chosen["lon"], *HISTORY)
        maxima = annual_maxima(pairs)
        rp = return_period_thresholds([q for _, q in maxima])
        at_cell = thresholds_for([q for _, q in pairs])
        old = current.get(v["id"], {})
        percentile_old = old.get("percentile") or {
            **{k: old[k] for k in ("watch", "warning", "critical") if k in old},
            "river_cell": old.get("river_cell"), "source": old.get("source")}
        current[v["id"]] = {
            "watch": rp["watch"], "warning": rp["warning"], "critical": rp["critical"],
            "early_cms": at_cell["watch"], "early_line": EARLY_LINE,
            "method": "return_period",
            "return_period_years": rp["return_period_years"],
            "gumbel": rp["gumbel"],
            "annual_maxima": {str(y): round(q, 2) for y, q in maxima},
            "mean_daily_discharge": round(sum(q for _, q in pairs) / len(pairs), 3),
            "percentile": percentile_old,
            "percentile_at_river_cell": at_cell,
            "river_cell": cell,
            "river": chosen.get("river"),
            "cell_verified": bool(chosen.get("cell_verified", False)),
            "cell_reasoning": chosen.get("reasoning"),
            "past_events": top_events(pairs),
            "days": len(pairs),
            "record_years": [maxima[0][0], maxima[-1][0]],
            "source": METHOD.format(start=maxima[0][0], end=maxima[-1][0]),
            **({"soil": old["soil"]} if old.get("soil") else {}),
            **({"watch_days": old["watch_days"]} if old.get("watch_days") else {}),
        }
        print(v["id"], {k: current[v["id"]][k] for k in ("watch", "warning", "critical", "river_cell")})
        _write(path, current)
        time.sleep(2)


def watch_days(client: httpx.Client, villages: list[dict], path: Path) -> None:
    current = _load(path)
    for v in villages:
        th = current.get(v["id"])
        if not th or "percentile" not in th:
            continue
        old = th["percentile"]
        old_cell = old.get("river_cell") or {"lat": v["lat"], "lon": v["lon"]}
        before_pairs, _ = fetch_series(client, old_cell["lat"], old_cell["lon"], *WATCH_DAYS_WINDOW)
        time.sleep(2)
        after_pairs, _ = fetch_series(client, th["river_cell"]["lat"], th["river_cell"]["lon"], *WATCH_DAYS_WINDOW)
        row: dict = {"window": list(WATCH_DAYS_WINDOW), "lookahead_days": DISCHARGE_LOOKAHEAD_DAYS,
                     "method": "days with max(today..today+3) >= threshold, reanalysis as a perfect forecast"}
        for label, pairs, t in (("before", before_pairs, old), ("after", after_pairs, th)):
            per_level = {}
            for lvl in ("watch", "warning", "critical"):
                counts = days_at_or_above(pairs, t[lvl])
                per_level[lvl] = {"per_year": counts["days"], "mean": round(sum(counts["days"].values()) / len(counts["days"]), 1),
                                  "episodes_per_year": counts["episodes"],
                                  "episodes_mean": round(sum(counts["episodes"].values()) / len(counts["episodes"]), 1)}
            row[label] = {"threshold": {k: t[k] for k in ("watch", "warning", "critical")}, **per_level}
        th["watch_days"] = row
        print(v["id"], "watch days/yr before", row["before"]["watch"]["per_year"], "after", row["after"]["watch"]["per_year"],
              "episodes before", row["before"]["watch"]["episodes_per_year"], "after", row["after"]["watch"]["episodes_per_year"])
        _write(path, current)
        time.sleep(2)


def main() -> None:
    s = get_settings()
    villages = json.loads((s.data_dir / "villages.json").read_text(encoding="utf-8"))["villages"]
    path = s.data_dir / "thresholds.json"
    cells_path = s.data_dir / "river_cells.json"
    args = sys.argv[1:]
    with httpx.Client(timeout=180) as client:
        if "--cells" in args:
            search_cells(client, villages, cells_path)
            return
        if "--watch-days" in args:
            watch_days(client, villages, path)
            return
        if "--soil" not in args:
            calibrate_rivers(client, villages, _load(cells_path), path)
            return
        current = _load(path)
        for v in villages:
            rng = fetch_soil(client, v)
            if rng is None:
                current.get(v["id"], {}).pop("soil", None)
                print(v["id"], "soil: not enough data; the default range is used")
            else:
                current.setdefault(v["id"], {})["soil"] = rng
                print(v["id"], "soil", rng)
            time.sleep(1)
        _write(path, current)


if __name__ == "__main__":
    main()
