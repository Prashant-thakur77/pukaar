"""Download archived rain and river data for the replay scenarios.

Rain: Open-Meteo historical-forecast API, hourly precipitation (what the
forecast models said at the time). River: Open-Meteo flood API, archived daily
river discharge (used as a stand-in for a perfect discharge forecast).

    python -m Pukaar.scripts.fetch_replay
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta

import httpx

from Pukaar.core.config import get_settings
from Pukaar.services.external_data import FLOOD_URL

HIST_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"

SCENARIOS = {
    "himachal_2023_07": {
        "title": "Himachal Pradesh, 7-11 July 2023",
        "title_hi": "हिमाचल प्रदेश, 7-11 जुलाई 2023",
        "start": "2023-07-07T00:00:00Z",
        "end": "2023-07-11T00:00:00Z",
    },
    "mandi_2025": {
        "title": "Mandi, night of 30 June to 1 July 2025",
        "title_hi": "मंडी, 30 जून से 1 जुलाई 2025 की रात",
        "start": "2025-06-29T00:00:00Z",
        "end": "2025-07-02T00:00:00Z",
    },
}


def _get(client: httpx.Client, url: str, params: dict) -> dict:
    for attempt in range(6):
        r = client.get(url, params=params)
        if r.status_code == 429:
            time.sleep(2 ** attempt * 5)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"rate limited: {url}")


def fetch(name: str, spec: dict, villages: list[dict], client: httpx.Client) -> dict:
    start = date.fromisoformat(spec["start"][:10])
    end = date.fromisoformat(spec["end"][:10])
    rain_end = end + timedelta(days=1)  # 24 h of look-ahead after the last replay hour
    flood_end = end + timedelta(days=4)
    out = {**spec, "name": name, "villages": {},
           "sources": {"rain": HIST_FORECAST_URL + " (hourly precipitation, best_match)",
                       "river": FLOOD_URL + " (daily river_discharge, archived)"}}
    for v in villages:
        rain = _get(client, HIST_FORECAST_URL, {"latitude": v["lat"], "longitude": v["lon"], "hourly": "precipitation",
                                                "start_date": start.isoformat(), "end_date": rain_end.isoformat(),
                                                "timezone": "GMT"})
        flood = _get(client, FLOOD_URL, {"latitude": v["lat"], "longitude": v["lon"], "daily": "river_discharge",
                                         "start_date": (start - timedelta(days=2)).isoformat(),
                                         "end_date": flood_end.isoformat()})
        out["villages"][v["id"]] = {
            "hourly": {"time": rain["hourly"]["time"], "precipitation": rain["hourly"]["precipitation"]},
            "daily": {"time": flood["daily"]["time"], "river_discharge": flood["daily"]["river_discharge"]},
        }
        print(name, v["id"], "hours", len(rain["hourly"]["time"]), "days", len(flood["daily"]["time"]))
        time.sleep(1)
    return out


def main() -> None:
    s = get_settings()
    villages = json.loads((s.data_dir / "villages.json").read_text(encoding="utf-8"))["villages"]
    with httpx.Client(timeout=60) as client:
        for name, spec in SCENARIOS.items():
            folder = s.data_dir / "replay" / name
            folder.mkdir(parents=True, exist_ok=True)
            data = fetch(name, spec, villages, client)
            (folder / "scenario.json").write_text(json.dumps(data) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
