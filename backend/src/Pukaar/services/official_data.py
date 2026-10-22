"""Official flood data, shown to officers as corroboration beside Pukaar's own level.

Sources (each optional, each cached, each with a timeout):

- CWC, India: the Central Water Commission's flood forecasting site lists the stations whose
  water level is above warning level right now (`station-water-level-above-warning`, public JSON).
  A station counts for a village when its code is listed for the village in
  data/official_sources.json, or when the response names a river the village is on. The public
  response carries only codes today, and no Himachal code could be confirmed, so in practice this
  shows "N stations above warning in India, none mapped here" until codes are added.
- IMD, India: the district warning colour from the IMD GeoServer layer
  `imd:Warnings_StateDistrict_Merged` (WMS GetFeatureInfo at the village point). The colour covers
  every weather hazard (heavy rain, thunderstorms, snow), not floods alone.
- Google Flood Hub: the latest flood status of gauges near the river cell
  (`floodStatus:searchLatestFloodStatusByArea`). Needs an API key (secret flood_hub_api_key);
  off by default (PUKAAR_FLOOD_HUB).
- BIPAD, Nepal: river stations from the BIPAD portal (DHM data). Off by default (PUKAAR_BIPAD);
  none of the five villages is in Nepal. The request is adapted from CascadeWatch
  (github.com/Cassius-stack/cascadewatch, src/cascadewatch/adapters/bipad.py, Apache-2.0).

Every item has a status: "ok" (with the level it implies), "unavailable" (the call failed or
the response was not what we expected) or "off". Unavailable never becomes "normal": the rules
read only "ok" items (risk_rules.official_level), never lower a level on them, and raise one
only when PUKAAR_OFFICIAL_RAISES_LEVEL is on.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from functools import lru_cache
from typing import Any

import httpx

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log
from Pukaar.services import fetch_cache
from Pukaar.store.models import Village

_LOG = get_logger("official_data")

CWC_URL = "https://ffs.india-water.gov.in/ffm/api/station-water-level-above-warning/"
IMD_WMS_URL = "https://reactjs.imd.gov.in/geoserver/wms"
IMD_LAYER = "imd:Warnings_StateDistrict_Merged"
FLOOD_HUB_URL = "https://floodforecasting.googleapis.com/v1/floodStatus:searchLatestFloodStatusByArea"
BIPAD_RIVER_URL = "https://bipadportal.gov.np/api/v1/river/"

CWC_CACHE_S, IMD_CACHE_S, FLOOD_HUB_CACHE_S, BIPAD_CACHE_S = 900, 3600, 3600, 900
FAILURE_CACHE_S = 600
# The area Flood Hub is asked about: Himachal Pradesh and its edges (one call serves every village).
FLOOD_HUB_BOX = (75.5, 30.3, 79.1, 33.3)  # min lon, min lat, max lon, max lat
USER_AGENT = "Pukaar flood early warning (corroboration; contact via the project README)"

# CWC: the endpoint lists stations above warning level; its status says how far above.
CWC_STATUS_LEVEL = {"WARNING": "watch", "DANGER": "warning", "SEVERE": "warning", "HFL": "critical",
                    "EXTREME": "critical"}
# IMD district colour codes, from the layer's own style: 1 red, 2 orange, 3 yellow, 4 green.
IMD_COLOUR = {1: ("red", "critical"), 2: ("orange", "warning"), 3: ("yellow", "watch"), 4: ("green", "normal")}
FLOOD_HUB_SEVERITY = {"EXTREME": "critical", "SEVERE": "warning", "ABOVE_NORMAL": "watch", "NO_FLOODING": "normal"}
# BIPAD river status strings.
BIPAD_STATUS = {"BELOW WARNING LEVEL": "normal", "ABOVE WARNING LEVEL": "watch", "ABOVE DANGER LEVEL": "warning"}


def _item(source: str, name: str, status: str, **extra: Any) -> dict[str, Any]:
    return {"source": source, "name": name, "status": status, "level": extra.pop("level", None), **extra}


def unavailable(source: str, name: str, error: str) -> dict[str, Any]:
    return _item(source, name, "unavailable", error=error[:200], fetched_at=clock.iso(clock.now()))


@lru_cache(maxsize=1)
def config() -> dict[str, Any]:
    path = get_settings().data_dir / "official_sources.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"villages": {}}


def village_config(village_id: str) -> dict[str, Any]:
    return config().get("villages", {}).get(village_id, {})


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dy = (lat1 - lat2) * 111.2
    dx = (lon1 - lon2) * 111.2 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def _max_level(levels: list[str]) -> str:
    order = ("normal", "watch", "warning", "critical")
    return max(levels, key=order.index) if levels else "normal"


# -- CWC --------------------------------------------------------------------------
def parse_cwc(body: Any) -> list[dict[str, Any]]:
    """The stations in a station-water-level-above-warning response. Raises ValueError on any
    other shape, so a changed API reads as unavailable, not as "no station above warning"."""
    if not isinstance(body, list):
        raise ValueError("expected a JSON list of stations")
    stations = []
    for row in body:
        if not isinstance(row, dict) or not row.get("stationCode"):
            raise ValueError("station without a stationCode")
        stations.append({
            "station_code": str(row["stationCode"]),
            "status": str(row.get("status") or "WARNING").upper(),
            "trend": row.get("trend"),
            "value_m": row.get("value"),
            # Not in today's response; read if CWC adds them.
            "name": row.get("stationName") or row.get("name"),
            "river": row.get("riverName") or row.get("river"),
            "state": row.get("stateName") or row.get("state"),
        })
    return stations


def cwc_for_village(stations: list[dict[str, Any]], cfg: dict[str, Any], state: str = "Himachal Pradesh") -> dict[str, Any]:
    """Which stations speak for this village, and the level they imply.

    A station counts when its code is listed for the village or its river is one of the village's
    rivers. A station elsewhere in the same state is listed as regional context and implies nothing.
    """
    codes = {c.upper() for c in cfg.get("cwc_stations", [])}
    rivers = {r.lower() for r in cfg.get("cwc_rivers", [])}
    matched, regional = [], []
    for st in stations:
        on_river = bool(st.get("river")) and str(st["river"]).lower() in rivers
        if st["station_code"].upper() in codes or on_river:
            matched.append({**st, "implies": CWC_STATUS_LEVEL.get(st["status"], "watch")})
        elif st.get("state") and state.lower() in str(st["state"]).lower():
            regional.append(st)
    level = _max_level([m["implies"] for m in matched])
    return {"level": level, "matched": matched, "regional": regional, "stations_above_warning": len(stations)}


def fetch_cwc(client: httpx.Client) -> dict[str, Any]:
    """All stations above warning in India (one call, cached CWC_CACHE_S for every village)."""
    def _fetch() -> dict[str, Any]:
        try:
            r = client.get(CWC_URL, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            r.raise_for_status()
            stations = parse_cwc(r.json())
        except Exception as exc:
            log(_LOG, "cwc fetch failed", 30, error=f"{type(exc).__name__}: {exc}"[:200])
            return {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"[:200]}
        return {"status": "ok", "stations": stations, "fetched_at": clock.iso(clock.now())}

    return fetch_cache.get_or_fetch("official:cwc", CWC_CACHE_S, _fetch, failure_ttl_seconds=FAILURE_CACHE_S)


def cwc_item(feed: dict[str, Any], village: Village) -> dict[str, Any]:
    name = "CWC flood forecasting: stations above warning level"
    if feed.get("status") != "ok":
        return unavailable("cwc", name, feed.get("error", "unavailable"))
    result = cwc_for_village(feed["stations"], village_config(village.id), config().get("cwc_state", "Himachal Pradesh"))
    n, m = result["stations_above_warning"], len(result["matched"])
    detail = (f"{n} CWC station(s) above warning level in India; {m} on this village's river"
              + ("" if village_config(village.id).get("cwc_stations") else " (no station codes mapped to this village yet)"))
    return _item("cwc", name, "ok", level=result["level"], detail=detail, fetched_at=feed.get("fetched_at"),
                 matched=result["matched"], regional=result["regional"], url=CWC_URL)


# -- IMD --------------------------------------------------------------------------
def parse_imd(body: Any, today: date, district: str | None = None) -> dict[str, Any]:
    """The district warning colours in a GetFeatureInfo response (JSON). Raises ValueError when no
    district warning feature is found."""
    if not isinstance(body, dict) or not isinstance(body.get("features"), list):
        raise ValueError("expected a GeoJSON FeatureCollection")
    feats = [f.get("properties") or {} for f in body["features"]]
    warn = [p for p in feats if "Day1_Color" in p and p.get("District")]
    if district:
        named = [p for p in warn if str(p["District"]).strip().lower() == district.strip().lower()]
        warn = named or warn
    if not warn:
        raise ValueError("no district warning feature at this point")
    p = warn[0]
    issued = date.fromisoformat(str(p["Date"])[:10])
    days = []
    for n in range(1, 6):
        code = p.get(f"Day{n}_Color")
        colour, level = IMD_COLOUR.get(int(code), ("none", None)) if code is not None else ("none", None)
        days.append({"day": n, "date": date.fromordinal(issued.toordinal() + n - 1).isoformat(), "colour": colour,
                     "level": level})
    # Today and tomorrow from the issue date (Day 1 is the issue date).
    ahead = (today - issued).days
    window = [d for d in days if ahead <= d["day"] - 1 <= ahead + 1]
    levels = [d["level"] for d in window if d["level"]]
    if not window:
        raise ValueError(f"warning issued {issued} does not cover {today}")
    return {"district": p["District"], "issued": issued.isoformat(), "updated_at": p.get("updated_at"),
            "days": days, "window": window, "level": _max_level(levels) if levels else "normal",
            "colour": max(window, key=lambda d: ("none", "green", "yellow", "orange", "red").index(d["colour"]))["colour"]}


def fetch_imd(client: httpx.Client, village: Village, today: date) -> dict[str, Any]:
    name = "IMD district warning colour (all weather hazards)"
    district = village_config(village.id).get("imd_district") or village.district

    def _fetch() -> dict[str, Any]:
        d = 0.05
        params = {"service": "WMS", "version": "1.1.1", "request": "GetFeatureInfo", "layers": IMD_LAYER,
                  "query_layers": IMD_LAYER, "styles": "", "srs": "EPSG:4326",
                  "bbox": f"{village.lon - d},{village.lat - d},{village.lon + d},{village.lat + d}",
                  "width": 101, "height": 101, "x": 50, "y": 50, "info_format": "application/json", "feature_count": 5}
        try:
            r = client.get(IMD_WMS_URL, params=params, headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            parsed = parse_imd(r.json(), today, district)
        except Exception as exc:
            log(_LOG, "imd fetch failed", 30, village_id=village.id, error=f"{type(exc).__name__}: {exc}"[:200])
            return {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"[:200]}
        return {"status": "ok", **parsed, "fetched_at": clock.iso(clock.now())}

    # One call per district and day: the colour is per district, so villages in Mandi share it.
    got = fetch_cache.get_or_fetch(f"official:imd:{district.lower()}:{today.isoformat()}", IMD_CACHE_S, _fetch,
                                   failure_ttl_seconds=FAILURE_CACHE_S)
    if got.get("status") != "ok":
        return unavailable("imd", name, got.get("error", "unavailable"))
    detail = f"{got['district']}: {got['colour']} for today and tomorrow (issued {got['issued']})"
    return _item("imd", name, "ok", level=got["level"], detail=detail, colour=got["colour"], days=got["days"],
                 issued=got["issued"], fetched_at=got.get("fetched_at"), url=IMD_WMS_URL)


# -- Google Flood Hub -------------------------------------------------------------
def parse_flood_hub(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ValueError("expected a JSON object")
    out = []
    for s in body.get("floodStatuses", []):
        loc = s.get("gaugeLocation") or {}
        if loc.get("latitude") is None or loc.get("longitude") is None:
            continue
        out.append({"gauge_id": s.get("gaugeId"), "severity": s.get("severity", "SEVERITY_UNSPECIFIED"),
                    "trend": s.get("forecastTrend"), "issued": s.get("issuedTime"),
                    "quality_verified": s.get("qualityVerified"),
                    "lat": float(loc["latitude"]), "lon": float(loc["longitude"])})
    return out


def flood_hub_for_point(gauges: list[dict[str, Any]], lat: float, lon: float, radius_km: float) -> dict[str, Any]:
    near = [{**g, "km": round(_km(lat, lon, g["lat"], g["lon"]), 1)} for g in gauges]
    near = sorted((g for g in near if g["km"] <= radius_km), key=lambda g: g["km"])
    levels = [FLOOD_HUB_SEVERITY[g["severity"]] for g in near if g["severity"] in FLOOD_HUB_SEVERITY]
    return {"level": _max_level(levels), "gauges": near, "counted": len(levels)}


def fetch_flood_hub(client: httpx.Client) -> dict[str, Any]:
    from Pukaar.core.secrets import get_secret

    key = get_secret("flood_hub_api_key")
    if not key:
        return {"status": "unavailable", "error": "flood_hub_api_key is not set"}

    def _fetch() -> dict[str, Any]:
        x0, y0, x1, y1 = FLOOD_HUB_BOX
        loop = {"vertices": [{"longitude": x, "latitude": y} for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]}
        try:
            r = client.post(FLOOD_HUB_URL, params={"key": key}, json={"loop": loop, "pageSize": 1000})
            r.raise_for_status()
            gauges = parse_flood_hub(r.json())
        except Exception as exc:
            log(_LOG, "flood hub fetch failed", 30, error=type(exc).__name__)
            return {"status": "unavailable", "error": type(exc).__name__}  # never echo the URL: it holds the key
        return {"status": "ok", "gauges": gauges, "fetched_at": clock.iso(clock.now())}

    return fetch_cache.get_or_fetch("official:floodhub", FLOOD_HUB_CACHE_S, _fetch, failure_ttl_seconds=FAILURE_CACHE_S)


def flood_hub_item(feed: dict[str, Any], village: Village) -> dict[str, Any]:
    name = "Google Flood Hub gauges near the river cell"
    if feed.get("status") != "ok":
        return unavailable("flood_hub", name, feed.get("error", "unavailable"))
    th = village.thresholds
    lat = th.cell_lat if th and th.cell_lat is not None else village.lat
    lon = th.cell_lon if th and th.cell_lon is not None else village.lon
    radius = float(village_config(village.id).get("flood_hub_radius_km", 25))
    res = flood_hub_for_point(feed["gauges"], lat, lon, radius)
    detail = f"{len(res['gauges'])} Flood Hub gauge(s) within {radius:g} km"
    return _item("flood_hub", name, "ok", level=res["level"], detail=detail, gauges=res["gauges"][:5],
                 fetched_at=feed.get("fetched_at"))


# -- BIPAD (Nepal) ----------------------------------------------------------------
def bipad_url_params(station_id: int, start_at: datetime, end_at: datetime) -> dict[str, Any]:
    """Query for one station's recent river readings (after CascadeWatch's bipad.river_history_url)."""
    return {"station": station_id, "water_level_on__gt": start_at.isoformat(), "water_level_on__lt": end_at.isoformat(),
            "ordering": "-water_level_on", "limit": 1}


def parse_bipad(body: Any) -> dict[str, Any] | None:
    """The newest reading in a BIPAD /river/ response, or None when there is none."""
    if not isinstance(body, dict) or not isinstance(body.get("results"), list):
        raise ValueError("expected {results: [...]}")
    if not body["results"]:
        return None
    r = body["results"][0]
    status = str(r.get("status") or "").upper()
    return {"title": r.get("title"), "basin": r.get("basin"), "water_level_m": r.get("waterLevel"),
            "warning_level_m": r.get("warningLevel"), "danger_level_m": r.get("dangerLevel"),
            "status": status, "at": r.get("waterLevelOn"), "implies": BIPAD_STATUS.get(status)}


def fetch_bipad(client: httpx.Client, village: Village, now: datetime) -> dict[str, Any]:
    name = "BIPAD river stations (DHM Nepal)"
    stations = village_config(village.id).get("bipad_stations", [])
    if not stations:
        return _item("bipad", name, "off", detail="no BIPAD station mapped to this village")
    readings = []
    for sid in stations:
        def _fetch(sid=sid) -> dict[str, Any]:
            start = datetime.fromtimestamp(now.timestamp() - 6 * 3600, tz=now.tzinfo)
            try:
                r = client.get(BIPAD_RIVER_URL, params=bipad_url_params(int(sid), start, now),
                               headers={"User-Agent": USER_AGENT})
                r.raise_for_status()
                reading = parse_bipad(r.json())
            except Exception as exc:
                return {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"[:200]}
            return {"status": "ok", "reading": reading}

        got = fetch_cache.get_or_fetch(f"official:bipad:{sid}", BIPAD_CACHE_S, _fetch, failure_ttl_seconds=FAILURE_CACHE_S)
        if got.get("status") != "ok":
            return unavailable("bipad", name, got.get("error", "unavailable"))
        if got.get("reading"):
            readings.append({"station": sid, **got["reading"]})
    levels = [r["implies"] for r in readings if r.get("implies")]
    if not levels:
        return unavailable("bipad", name, "no recent reading with a known status")
    return _item("bipad", name, "ok", level=_max_level(levels), readings=readings,
                 detail=f"{len(readings)} BIPAD station reading(s) in the last 6 hours")


# -- all sources for one village --------------------------------------------------
NAMES = {
    "cwc": "CWC flood forecasting: stations above warning level",
    "imd": "IMD district warning colour (all weather hazards)",
    "flood_hub": "Google Flood Hub gauges near the river cell",
    "bipad": "BIPAD river stations (DHM Nepal)",
}


def _collect(client: httpx.Client, village: Village, at: datetime) -> list[dict[str, Any]]:
    s = get_settings()
    calls = {
        "cwc": lambda: cwc_item(fetch_cwc(client), village),
        "imd": lambda: fetch_imd(client, village, at.date()),
        "flood_hub": lambda: flood_hub_item(fetch_flood_hub(client), village) if s.flood_hub_enabled
        else _item("flood_hub", NAMES["flood_hub"], "off", detail="needs an API key; PUKAAR_FLOOD_HUB=true to use it"),
        "bipad": lambda: fetch_bipad(client, village, at) if s.bipad_enabled
        else _item("bipad", NAMES["bipad"], "off", detail="Nepal only; PUKAAR_BIPAD=true"),
    }
    items: list[dict[str, Any]] = []
    for source, call in calls.items():
        try:
            items.append(call())
        except Exception as exc:  # a bug in one adapter never stops the sweep or the others
            log(_LOG, "official source failed", 40, source=source, error=f"{type(exc).__name__}: {exc}"[:200])
            items.append(unavailable(source, NAMES[source], f"{type(exc).__name__}: {exc}"))
    return items


def for_village(village: Village, at: datetime | None = None, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """One item per source for this village. Never raises: a failure is an "unavailable" item."""
    s = get_settings()
    if not s.official_data_enabled:
        return []
    at = at or clock.now()
    if client is not None:
        return _collect(client, village, at)
    try:
        with httpx.Client(timeout=s.official_timeout_seconds) as own:
            return _collect(own, village, at)
    except Exception as exc:
        log(_LOG, "official data client failed", 40, error=f"{type(exc).__name__}: {exc}"[:200])
        return [unavailable(src, name, f"{type(exc).__name__}: {exc}") for src, name in NAMES.items()]
