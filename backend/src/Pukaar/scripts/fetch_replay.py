"""Download archived rain and river data for the replay scenarios.

Rain: Open-Meteo historical-forecast API, hourly precipitation (what the
forecast models said at the time). River: Open-Meteo flood API, archived daily
river discharge (used as a stand-in for a perfect discharge forecast). Soil:
the same historical-forecast API, hourly root-zone soil moisture (9-27 and
27-81 cm, averaged), written to soil.json beside scenario.json.

River discharge is read at each village's calibrated river cell (data/thresholds.json,
river_cell; scripts/calibrate.py), the same cell the live sweep asks about. The series at the
village's own coordinates is kept beside it as daily_village_point, for comparison with earlier
scores.

    python -m Pukaar.scripts.fetch_replay           # everything
    python -m Pukaar.scripts.fetch_replay --soil    # soil.json only; scenario.json untouched
    python -m Pukaar.scripts.fetch_replay --river   # river series only; archived rain untouched
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta

import httpx

from Pukaar.core.config import get_settings
from Pukaar.services import soil
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


def river_cell(v: dict) -> tuple[float, float]:
    th = json.loads((get_settings().data_dir / "thresholds.json").read_text(encoding="utf-8")).get(v["id"], {})
    cell = th.get("river_cell") or {}
    return (cell["lat"], cell["lon"]) if cell.get("lat") is not None else (v["lat"], v["lon"])


def fetch_river(spec: dict, v: dict, client: httpx.Client) -> dict:
    """{daily, daily_village_point, river_cell} for one village over the scenario window."""
    start = date.fromisoformat(spec["start"][:10]) - timedelta(days=2)
    end = date.fromisoformat(spec["end"][:10]) + timedelta(days=4)
    out: dict = {}
    lat, lon = river_cell(v)
    for key, (qlat, qlon) in (("daily", (lat, lon)), ("daily_village_point", (v["lat"], v["lon"]))):
        flood = _get(client, FLOOD_URL, {"latitude": qlat, "longitude": qlon, "daily": "river_discharge",
                                         "start_date": start.isoformat(), "end_date": end.isoformat()})
        out[key] = {"time": flood["daily"]["time"], "river_discharge": flood["daily"]["river_discharge"]}
        if key == "daily":
            out["river_cell"] = {"lat": flood.get("latitude"), "lon": flood.get("longitude")}
        time.sleep(1)
    return out


def fetch(name: str, spec: dict, villages: list[dict], client: httpx.Client) -> dict:
    start = date.fromisoformat(spec["start"][:10])
    end = date.fromisoformat(spec["end"][:10])
    rain_end = end + timedelta(days=1)  # 24 h of look-ahead after the last replay hour
    out = {**spec, "name": name, "villages": {},
           "sources": {"rain": HIST_FORECAST_URL + " (hourly precipitation, best_match)",
                       "river": FLOOD_URL + " (daily river_discharge, archived, at the village's river cell)"}}
    for v in villages:
        rain = _get(client, HIST_FORECAST_URL, {"latitude": v["lat"], "longitude": v["lon"], "hourly": "precipitation",
                                                "start_date": start.isoformat(), "end_date": rain_end.isoformat(),
                                                "timezone": "GMT"})
        river = fetch_river(spec, v, client)
        out["villages"][v["id"]] = {
            "hourly": {"time": rain["hourly"]["time"], "precipitation": rain["hourly"]["precipitation"]},
            **river,
        }
        print(name, v["id"], "hours", len(rain["hourly"]["time"]), "days", len(river["daily"]["time"]))
        time.sleep(1)
    return out


def fetch_soil(name: str, spec: dict, villages: list[dict], client: httpx.Client) -> dict:
    """Hourly root-zone soil moisture over the replay window, one rounded value per hour (small file)."""
    start = date.fromisoformat(spec["start"][:10])
    end = date.fromisoformat(spec["end"][:10]) + timedelta(days=1)
    out: dict = {"name": name, "start": f"{start.isoformat()}T00:00:00Z", "step_hours": 1, "unit": "m³/m³",
                 "layers": list(soil.LAYERS), "value": "mean of the layers",
                 "source": HIST_FORECAST_URL + " (hourly " + ", ".join(soil.LAYERS) + ", best_match)", "villages": {}}
    for v in villages:
        data = _get(client, HIST_FORECAST_URL, {"latitude": v["lat"], "longitude": v["lon"], "hourly": ",".join(soil.LAYERS),
                                                "start_date": start.isoformat(), "end_date": end.isoformat(),
                                                "timezone": "GMT"})
        h = data["hourly"]
        out["villages"][v["id"]] = [soil.root_zone(h, i) for i in range(len(h["time"]))]
        print(name, v["id"], "soil hours", len(h["time"]))
        time.sleep(1)
    return out


def main() -> None:
    s = get_settings()
    villages = json.loads((s.data_dir / "villages.json").read_text(encoding="utf-8"))["villages"]
    soil_only = "--soil" in sys.argv[1:]
    with httpx.Client(timeout=60) as client:
        for name, spec in SCENARIOS.items():
            folder = s.data_dir / "replay" / name
            folder.mkdir(parents=True, exist_ok=True)
            if "--river" in sys.argv[1:]:
                data = json.loads((folder / "scenario.json").read_text(encoding="utf-8"))
                for v in villages:
                    data["villages"][v["id"]].update(fetch_river(spec, v, client))
                    print(name, v["id"], "river cell", data["villages"][v["id"]]["river_cell"])
                data["sources"]["river"] = FLOOD_URL + " (daily river_discharge, archived, at the village's river cell)"
                (folder / "scenario.json").write_text(json.dumps(data) + "\n", encoding="utf-8")
                continue
            if not soil_only:
                data = fetch(name, spec, villages, client)
                (folder / "scenario.json").write_text(json.dumps(data) + "\n", encoding="utf-8")
            soil_data = fetch_soil(name, spec, villages, client)
            (folder / "soil.json").write_text(json.dumps(soil_data, ensure_ascii=False, separators=(",", ":")) + "\n",
                                              encoding="utf-8")


if __name__ == "__main__":
    main()
