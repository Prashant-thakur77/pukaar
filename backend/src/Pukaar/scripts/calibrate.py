"""Compute per-village river-discharge thresholds from daily history.

Watch, warning and critical are the 90th, 97th and 99.5th percentiles of the
Open-Meteo flood API daily river discharge for the village's river cell,
1984-01-01 to 2024-12-31. Writes data/thresholds.json.

Soil range (`soil: {dry, wet}`): the 5th and 95th percentiles of two years of
hourly root-zone soil moisture (mean of the 9-27 cm and 27-81 cm layers) from
the Open-Meteo historical-forecast API: the same layers and model family the
live sweep reads, so S means the same thing live and in calibration. (The
ERA5-Land archive API reports different layers, 7-28 and 28-100 cm.)

    python -m Pukaar.scripts.calibrate          # river thresholds and soil range
    python -m Pukaar.scripts.calibrate --soil   # soil range only, river thresholds kept
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date

import httpx

from Pukaar.core.config import get_settings
from Pukaar.services import soil
from Pukaar.services.external_data import FLOOD_URL

PERCENTILES = {"watch": 0.90, "warning": 0.97, "critical": 0.995}
HISTORY = ("1984-01-01", "2024-12-31")
HIST_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
SOIL_HISTORY = ("2024-01-01", "2025-12-31")
SOIL_PERCENTILES = {"dry": 0.05, "wet": 0.95}


def percentile(sorted_values: list[float], p: float) -> float:
    """Linear-interpolated percentile of an ascending list."""
    if not sorted_values:
        raise ValueError("empty series")
    k = (len(sorted_values) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def thresholds_for(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {name: round(percentile(ordered, p), 3) for name, p in PERCENTILES.items()}


def top_events(pairs: list[tuple[str, float]], n: int = 3, gap_days: int = 10) -> list[dict]:
    """The n highest daily discharges, at least gap_days apart (one per flood)."""
    chosen: list[tuple[str, float]] = []
    for day, q in sorted(pairs, key=lambda x: -x[1]):
        if all(abs((date.fromisoformat(day) - date.fromisoformat(c)).days) > gap_days for c, _ in chosen):
            chosen.append((day, q))
        if len(chosen) == n:
            break
    return [{"date": d, "discharge": round(q, 2)} for d, q in chosen]


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


def _get(client: httpx.Client, params: dict, url: str = FLOOD_URL) -> dict:
    for attempt in range(5):
        r = client.get(url, params=params)
        if r.status_code == 429:
            time.sleep(2 ** attempt * 5)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("rate limited by the flood API")


def fetch_soil(client: httpx.Client, v: dict) -> dict | None:
    data = _get(client, {"latitude": v["lat"], "longitude": v["lon"], "hourly": ",".join(soil.LAYERS),
                         "start_date": SOIL_HISTORY[0], "end_date": SOIL_HISTORY[1], "timezone": "GMT"},
                HIST_FORECAST_URL)
    return soil_range(data.get("hourly", {}))


def main() -> None:
    s = get_settings()
    villages = json.loads((s.data_dir / "villages.json").read_text(encoding="utf-8"))["villages"]
    path = s.data_dir / "thresholds.json"
    if "--soil" in sys.argv[1:]:
        current = json.loads(path.read_text(encoding="utf-8"))
        with httpx.Client(timeout=120) as client:
            for v in villages:
                rng = fetch_soil(client, v)
                if rng is None:
                    current.get(v["id"], {}).pop("soil", None)
                    print(v["id"], "soil: not enough data; the default range is used")
                else:
                    current.setdefault(v["id"], {})["soil"] = rng
                    print(v["id"], "soil", rng)
                time.sleep(1)
        path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        return
    out: dict[str, dict] = {}
    with httpx.Client(timeout=60) as client:
        for v in villages:
            data = _get(client, {"latitude": v["lat"], "longitude": v["lon"], "daily": "river_discharge",
                                 "start_date": HISTORY[0], "end_date": HISTORY[1]})
            pairs = [(d, float(q)) for d, q in zip(data["daily"]["time"], data["daily"]["river_discharge"]) if q is not None]
            values = [q for _, q in pairs]
            out[v["id"]] = {
                **thresholds_for(values),
                "past_events": top_events(pairs),
                "days": len(values),
                "river_cell": {"lat": data.get("latitude"), "lon": data.get("longitude")},
                "source": f"open-meteo flood API daily river_discharge {HISTORY[0]}..{HISTORY[1]}, "
                          "percentiles 90/97/99.5",
            }
            rng = fetch_soil(client, v)
            if rng is not None:
                out[v["id"]]["soil"] = rng
            print(v["id"], out[v["id"]])
            time.sleep(1)
    (s.data_dir / "thresholds.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
