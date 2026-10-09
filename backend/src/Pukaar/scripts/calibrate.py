"""Compute per-village river-discharge thresholds from daily history.

Watch, warning and critical are the 90th, 97th and 99.5th percentiles of the
Open-Meteo flood API daily river discharge for the village's river cell,
1984-01-01 to 2024-12-31. Writes data/thresholds.json.

    python -m Pukaar.scripts.calibrate
"""

from __future__ import annotations

import json
import time
from datetime import date

import httpx

from Pukaar.core.config import get_settings
from Pukaar.services.external_data import FLOOD_URL

PERCENTILES = {"watch": 0.90, "warning": 0.97, "critical": 0.995}
HISTORY = ("1984-01-01", "2024-12-31")


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


def _get(client: httpx.Client, params: dict) -> dict:
    for attempt in range(5):
        r = client.get(FLOOD_URL, params=params)
        if r.status_code == 429:
            time.sleep(2 ** attempt * 5)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("rate limited by the flood API")


def main() -> None:
    s = get_settings()
    villages = json.loads((s.data_dir / "villages.json").read_text(encoding="utf-8"))["villages"]
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
            print(v["id"], out[v["id"]])
            time.sleep(1)
    (s.data_dir / "thresholds.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
