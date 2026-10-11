"""Bake named safe places and slope-aware walking routes for each village.

Offline, run once; the outputs are committed so nothing calls OpenStreetMap or
the terrain tiles at run time:

    uv run --with httpx --with pillow --with networkx python scripts/build_safe_places.py

For each village in data/villages.json (coordinates approximate):

1. One Overpass API query (OpenStreetMap, ODbL) within RADIUS_M of the village
   point for candidate shelters (amenity=school|college|hospital|clinic|
   community_centre|townhall|place_of_worship|shelter, building=school|public;
   government rest houses, which Himachal uses as relief camps; and untagged
   features whose name says what they are, such as a node named "PHC, Pandoh"),
   walkable ways (footway, path, steps, track, roads) and waterways
   (river, stream, canal, drain). Bus shelters are dropped; unnamed candidates
   are counted but never used, because an alert has to name the place.
2. Elevation for every point from Mapzen Terrain Tiles (terrarium PNG, AWS Open
   Data, z13, bilinear). The river level is the lowest terrain cell within
   500 m of the village point. A candidate's headroom is its height above that
   level, and also above the nearest mapped stream within 1 km of the
   candidate; the smaller of the two counts. Candidates need at least
   MIN_HEADROOM_M (15 m) of headroom.
3. A walking graph from the OSM ways. Each edge costs length x slope penalty:
   grade over 35 % is impassable, 20-35 % costs x3, under 20 % costs x1
   ("slope-aware, avoids steep chutes"). Edges within 30 m of a mapped
   waterway cost x4 more, so routes leave the water as early as they can but
   may still cross a bridge. Grades come from the terrain model, which is
   about 30 m across, so a short steep stretch can hide inside a cell.
4. Dijkstra (networkx) from the village point to every eligible candidate.
   Ranking: walking minutes at 3 km/h (hill pace) minus one minute for every
   10 m of headroom (headroom counted up to 100 m). The top MAX_PLACES are kept.

Outputs: data/safe_places/<village>.geojson and data/safe_places/summary.json.
If a village has no usable candidate, the summary says so; no place is ever
invented. Every place needs checking on the ground by the pradhan before it is
relied on.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import networkx as nx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "safe_places"
OVERPASS = "https://overpass-api.de/api/interpreter"
TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
USER_AGENT = "Pukaar-safe-places-bake/1.0 (flood early warning research; prashant101007@gmail.com)"
CACHE = Path(os.environ.get("PUKAAR_BAKE_CACHE", Path(tempfile.gettempdir()) / "pukaar-bake"))

ATTRIBUTION = "© OpenStreetMap contributors (ODbL)"
TERRAIN_ATTRIBUTION = "Terrain: Mapzen Terrain Tiles on AWS Open Data (SRTM and others)"
RADIUS_M = 3000  # candidates within this straight-line distance of the village point
GRAPH_PAD_M = 800  # the walking graph reaches a little past the candidate radius
ZOOM = 13
RIVER_SEARCH_M = 500
LOCAL_STREAM_M = 1000
MIN_HEADROOM_M = 15.0
MAX_PLACES = 3
WALK_M_PER_MIN = 50.0  # 3 km/h, a hill walking pace for families with children and elders
STEEP_GRADE = 0.20
IMPASSABLE_GRADE = 0.35
STEEP_FACTOR = 3.0
WATER_BUFFER_M = 30.0
WATER_FACTOR = 4.0
SNAP_MAX_M = 400.0
SAMPLE_M = 10.0
SMOOTH_M = 45.0
GRADE_BASE_M = 60.0

AMENITIES = ("school", "college", "hospital", "clinic", "community_centre", "townhall", "place_of_worship", "shelter")
HIGHWAYS = ("footway", "path", "steps", "track", "pedestrian", "bridleway", "living_street", "residential",
            "unclassified", "service", "tertiary", "secondary", "primary", "trunk", "road", "tertiary_link",
            "secondary_link", "primary_link", "trunk_link")
FOOT_WAYS = ("footway", "path", "steps", "track", "pedestrian", "bridleway")
BUILT_ROADS = tuple(h for h in HIGHWAYS if h not in FOOT_WAYS)
WATERWAYS = ("river", "stream", "canal", "drain")
KIND_LABELS = {
    "school": ("School", "विद्यालय"),
    "college": ("College", "महाविद्यालय"),
    "hospital": ("Hospital", "अस्पताल"),
    "clinic": ("Health centre", "स्वास्थ्य केंद्र"),
    "community_centre": ("Community hall", "सामुदायिक भवन"),
    "townhall": ("Panchayat hall", "पंचायत भवन"),
    "place_of_worship": ("Temple or place of worship", "मंदिर / पूजा स्थल"),
    "shelter": ("Shelter", "आश्रय"),
    "public": ("Public building", "सरकारी भवन"),
    "rest_house": ("Government rest house", "सरकारी विश्राम गृह"),
}
# Government rest houses (PWD, forest, circuit house) are used as relief camps in Himachal.
GOVT_REST_RE = r"(PWD|rest house|circuit house|dak bungalow|forest rest|guest house pwd|govt|government)"
# Untagged features whose name says what they are, e.g. a node named "PHC, Pandoh" with no amenity tag.
NAME_KINDS = (
    ("hospital", r"\b(hospital|CHC)\b"),
    ("clinic", r"\b(PHC|health (centre|center|sub ?centre)|dispensary)\b"),
    ("college", r"\b(college|mahavidyalaya)\b"),
    ("school", r"\b(school|vidyalaya|vidhyalaya|pathshala|GSSS|GHS|GMS|GPS)\b"),
    ("townhall", r"\b(panchayat( bhawan| ghar)?|gram panchayat)\b"),
    ("community_centre", r"\b(community (hall|centre|center)|mahila mandal)\b"),
    ("place_of_worship", r"\b(mandir|temple|devta|gurudwara|mosque|masjid|church)\b"),
)
NAME_HI_KINDS = {
    "hospital": r"अस्पताल|चिकित्सालय",
    "clinic": r"स्वास्थ्य केंद्र|स्वास्थ्य केन्द्र|औषधालय",
    "college": r"महाविद्यालय",
    "school": r"विद्यालय|पाठशाला",
    "townhall": r"पंचायत",
    "community_centre": r"सामुदायिक भवन|महिला मंडल",
    "place_of_worship": r"मंदिर|मन्दिर|देवता|गुरुद्वारा",
}
NAME_RE = r"(hospital|CHC|PHC|health cent|dispensary|college|school|vidyalaya|vidhyalaya|pathshala|panchayat|" \
          r"community hall|community cent|mahila mandal|mandir|temple|devta|gurudwara|masjid|church)"
NAME_HI_RE = r"(अस्पताल|चिकित्सालय|स्वास्थ्य|औषधालय|विद्यालय|पाठशाला|पंचायत|सामुदायिक|मंदिर|मन्दिर|देवता|गुरुद्वारा)"
# Order of preference when a candidate's tags fit more than one kind.
KIND_ORDER = ("hospital", "clinic", "school", "college", "townhall", "community_centre", "shelter", "public",
              "rest_house", "place_of_worship")


# --- geometry ---------------------------------------------------------------
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Proj:
    """Local equirectangular projection in metres, accurate enough over a few km."""

    def __init__(self, lat0: float, lon0: float) -> None:
        self.lat0, self.lon0 = lat0, lon0
        self.kx = 111320.0 * math.cos(math.radians(lat0))
        self.ky = 110540.0

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky

    def latlon(self, x: float, y: float) -> tuple[float, float]:
        return self.lat0 + y / self.ky, self.lon0 + x / self.kx


def seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> tuple[float, float]:
    """Distance from P to segment AB and the parameter t of the closest point."""
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy), t


class SegIndex:
    """Bucket grid of line segments (projected metres) for nearest-segment queries."""

    def __init__(self, cell: float = 100.0) -> None:
        self.cell = cell
        self.grid: dict[tuple[int, int], list[int]] = {}
        self.segs: list[tuple[float, float, float, float, dict]] = []

    def add(self, ax: float, ay: float, bx: float, by: float, meta: dict) -> None:
        i = len(self.segs)
        self.segs.append((ax, ay, bx, by, meta))
        c = self.cell
        for gx in range(int(math.floor(min(ax, bx) / c)), int(math.floor(max(ax, bx) / c)) + 1):
            for gy in range(int(math.floor(min(ay, by) / c)), int(math.floor(max(ay, by) / c)) + 1):
                self.grid.setdefault((gx, gy), []).append(i)

    def nearest(self, x: float, y: float, max_d: float) -> tuple[float, tuple | None]:
        c = self.cell
        r = int(math.ceil(max_d / c))
        gx, gy = int(math.floor(x / c)), int(math.floor(y / c))
        best, hit = math.inf, None
        seen: set[int] = set()
        for i in range(gx - r, gx + r + 1):
            for j in range(gy - r, gy + r + 1):
                for k in self.grid.get((i, j), ()):
                    if k in seen:
                        continue
                    seen.add(k)
                    ax, ay, bx, by, meta = self.segs[k]
                    d, t = seg_dist(x, y, ax, ay, bx, by)
                    if d < best:
                        best, hit = d, (ax + t * (bx - ax), ay + t * (by - ay), meta)
        return (best, hit) if best <= max_d else (math.inf, None)


# --- terrain ------------------------------------------------------------------
class Terrain:
    """Terrarium tiles, decoded to metres, with bilinear sampling."""

    def __init__(self, client: httpx.Client, zoom: int = ZOOM) -> None:
        self.client, self.z = client, zoom
        self.tiles: dict[tuple[int, int], list[float]] = {}
        self.fetched = 0

    def _tile(self, x: int, y: int) -> list[float]:
        key = (x, y)
        if key not in self.tiles:
            path = CACHE / "terrarium" / f"{self.z}-{x}-{y}.png"
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                for attempt in range(4):
                    try:
                        resp = self.client.get(TILE_URL.format(z=self.z, x=x, y=y))
                        resp.raise_for_status()
                        break
                    except httpx.HTTPError:
                        if attempt == 3:
                            raise
                        time.sleep(5 * (attempt + 1))
                path.write_bytes(resp.content)
                self.fetched += 1
            img = Image.open(io.BytesIO(path.read_bytes())).convert("RGB")
            self.tiles[key] = [r * 256 + g + b / 256 - 32768 for r, g, b in img.getdata()]
        return self.tiles[key]

    def _pixel(self, lat: float, lon: float) -> tuple[float, float]:
        n = 2 ** self.z * 256
        px = (lon + 180.0) / 360.0 * n
        py = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
        return px, py

    def _cell(self, gx: int, gy: int) -> float:
        tile = self._tile(gx // 256, gy // 256)
        return tile[(gy % 256) * 256 + (gx % 256)]

    def elev(self, lat: float, lon: float) -> float:
        px, py = self._pixel(lat, lon)
        px, py = px - 0.5, py - 0.5  # pixel centres
        x0, y0 = int(math.floor(px)), int(math.floor(py))
        fx, fy = px - x0, py - y0
        v00, v10 = self._cell(x0, y0), self._cell(x0 + 1, y0)
        v01, v11 = self._cell(x0, y0 + 1), self._cell(x0 + 1, y0 + 1)
        return (v00 * (1 - fx) + v10 * fx) * (1 - fy) + (v01 * (1 - fx) + v11 * fx) * fy

    def lowest_within(self, lat: float, lon: float, radius_m: float) -> tuple[float, float, float]:
        """Lowest terrain cell centre within radius_m: (elevation, lat, lon)."""
        proj = Proj(lat, lon)
        best = (math.inf, lat, lon)
        step = 10.0
        n = int(radius_m / step)
        for i in range(-n, n + 1):
            for j in range(-n, n + 1):
                x, y = i * step, j * step
                if x * x + y * y > radius_m * radius_m:
                    continue
                la, lo = proj.latlon(x, y)
                px, py = self._pixel(la, lo)
                e = self._cell(int(px), int(py))
                if e < best[0]:
                    best = (e, la, lo)
        return best


# --- OpenStreetMap ------------------------------------------------------------
def overpass(client: httpx.Client, village_id: str, lat: float, lon: float) -> dict[str, Any]:
    path = CACHE / "overpass" / f"{village_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    r_graph = RADIUS_M + GRAPH_PAD_M
    am = "|".join(AMENITIES)
    hw = "|".join(HIGHWAYS)
    ww = "|".join(WATERWAYS)
    # Name regexes run on the small set of named features near the village, not the whole database
    # (a bare name regex inside "around" times out on the public server).
    query = f"""[out:json][timeout:180];
nwr(around:{RADIUS_M},{lat},{lon})[name]->.named;
(
  nwr(around:{RADIUS_M},{lat},{lon})["amenity"~"^({am})$"];
  nwr(around:{RADIUS_M},{lat},{lon})["building"~"^(school|public)$"];
  nwr.named["tourism"~"^(guest_house|hotel)$"]["name"~"{GOVT_REST_RE}",i];
  nwr.named["name"~"{NAME_RE}",i][!highway][!waterway][!place][!amenity][!shop];
  nwr.named["name:hi"~"{NAME_HI_RE}"][!highway][!waterway][!place][!amenity][!shop];
)->.cand;
.cand out center tags;
way(around:{r_graph},{lat},{lon})["highway"~"^({hw})$"]["access"!~"^(private|no)$"];
out geom;
way(around:{r_graph},{lat},{lon})["waterway"~"^({ww})$"];
out geom;
"""
    for attempt in range(4):
        resp = client.post(OVERPASS, data={"data": query}, timeout=180)
        busy = resp.status_code in (429, 504) or "json" not in resp.headers.get("content-type", "")
        if busy:  # rate limited or overloaded: Overpass answers with an HTML page
            time.sleep(60 * (attempt + 1))
            continue
        resp.raise_for_status()
        data = resp.json()
        if "runtime error" in str(data.get("remark", "")):  # a timed-out query answers 200 with no elements
            print(f"{village_id}: Overpass said {data['remark']!r}; retrying", file=sys.stderr)
            time.sleep(60 * (attempt + 1))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return data
    raise RuntimeError(f"Overpass kept refusing the query for {village_id}")


def candidate_kind(tags: dict[str, str]) -> str | None:
    """Kind from the OSM tags; for untagged features, from the words in the name (e.g. "PHC, Pandoh")."""
    found = set()
    if tags.get("amenity") in AMENITIES:
        found.add(tags["amenity"])
    if tags.get("building") == "school":
        found.add("school")
    if tags.get("building") == "public":
        found.add("public")
    if tags.get("tourism") in {"guest_house", "hotel"} and re.search(GOVT_REST_RE, tags.get("name", ""), re.I):
        found.add("rest_house")
    if not found and not tags.get("amenity") and not tags.get("shop"):
        name = f"{tags.get('name', '')} {tags.get('name:en', '')}"
        for kind, pattern in NAME_KINDS:
            if re.search(pattern, name, re.I) or re.search(NAME_HI_KINDS.get(kind, "^$"), tags.get("name:hi", "")):
                found.add(kind)
                break
    for k in KIND_ORDER:
        if k in found:
            return k
    return None


def element_point(el: dict[str, Any]) -> tuple[float, float] | None:
    if el["type"] == "node":
        return el["lat"], el["lon"]
    c = el.get("center")
    return (c["lat"], c["lon"]) if c else None


# --- the bake for one village ---------------------------------------------------
def bake_village(v: dict[str, Any], client: httpx.Client, terrain: Terrain) -> tuple[dict, dict]:
    vid, vlat, vlon = v["id"], v["lat"], v["lon"]
    proj = Proj(vlat, vlon)
    data = overpass(client, vid, vlat, vlon)
    els = data["elements"]
    notes: list[str] = []

    # Waterways -> segment index for distances and the nearest mapped stream.
    water = SegIndex()
    river_names: set[str] = set()
    for el in els:
        if el["type"] == "way" and "waterway" in el.get("tags", {}) and el.get("geometry"):
            tags = el["tags"]
            if tags.get("name"):
                river_names.add(tags["name"])
            g = el["geometry"]
            for a, b in zip(g, g[1:]):
                ax, ay = proj.xy(a["lat"], a["lon"])
                bx, by = proj.xy(b["lat"], b["lon"])
                water.add(ax, ay, bx, by, {"name": tags.get("name"), "kind": tags.get("waterway")})

    # The river level near the village: the lowest terrain cell within 500 m.
    river_m, rlat, rlon = terrain.lowest_within(vlat, vlon, RIVER_SEARCH_M)
    d_w, hit = water.nearest(0.0, 0.0, RIVER_SEARCH_M * 2)
    nearest_water = None
    if hit:
        wlat, wlon = proj.latlon(hit[0], hit[1])
        nearest_water = {"name": hit[2]["name"], "kind": hit[2]["kind"], "distance_m": round(d_w),
                         "elevation_m": round(terrain.elev(wlat, wlon), 1)}
    village_elev = terrain.elev(vlat, vlon)

    # Candidates.
    seen_names: list[tuple[str, float, float]] = []
    counts = {"tagged": 0, "unnamed": 0, "bus_shelters": 0, "duplicates": 0, "too_far": 0, "low": 0}
    cands: list[dict[str, Any]] = []
    for el in els:
        tags = el.get("tags", {})
        if "highway" in tags or "waterway" in tags:
            continue
        kind = candidate_kind(tags)
        pt = element_point(el)
        if kind is None or pt is None:
            continue
        counts["tagged"] += 1
        if kind == "shelter" and tags.get("shelter_type") in {"public_transport", "picnic_shelter"}:
            counts["bus_shelters"] += 1
            continue
        name_en = tags.get("name:en") or tags.get("name")
        name_hi = tags.get("name:hi")
        if not (name_en or name_hi):
            counts["unnamed"] += 1
            continue
        lat, lon = pt
        dist = haversine(vlat, vlon, lat, lon)
        if dist > RADIUS_M:
            counts["too_far"] += 1
            continue
        label = (name_en or name_hi or "").strip().lower()
        if any(n == label and haversine(lat, lon, a, b) < 250 for n, a, b in seen_names):
            counts["duplicates"] += 1
            continue
        seen_names.append((label, lat, lon))
        elev = terrain.elev(lat, lon)
        x, y = proj.xy(lat, lon)
        sd, shit = water.nearest(x, y, LOCAL_STREAM_M)
        stream_m = None
        if shit:
            slat, slon = proj.latlon(shit[0], shit[1])
            stream_m = terrain.elev(slat, slon)
        above_river = elev - river_m
        above_stream = elev - stream_m if stream_m is not None else None
        headroom = min(above_river, above_stream) if above_stream is not None else above_river
        cand = {
            "id": f"osm-{el['type']}-{el['id']}",
            "osm_url": f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
            "name": name_en or name_hi,
            "name_hi": name_hi or name_en,
            "kind": kind,
            "kind_en": KIND_LABELS[kind][0],
            "kind_hi": KIND_LABELS[kind][1],
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "elevation_m": round(elev, 1),
            "headroom_m": round(headroom, 1),
            "above_village_river_m": round(above_river, 1),
            "above_nearest_stream_m": round(above_stream, 1) if above_stream is not None else None,
            "nearest_stream_m": round(sd) if shit else None,
            "straight_m": round(dist),
        }
        if headroom < MIN_HEADROOM_M:
            counts["low"] += 1
            continue
        cands.append(cand)

    # Walking graph.
    G = nx.Graph()
    coords: dict[int, tuple[float, float]] = {}
    for el in els:
        if el["type"] != "way" or "highway" not in el.get("tags", {}) or not el.get("geometry"):
            continue
        nodes, geom = el.get("nodes") or [], el["geometry"]
        if len(nodes) != len(geom):
            continue
        hw = el["tags"]["highway"]
        for nid, g in zip(nodes, geom):
            coords[nid] = (g["lat"], g["lon"])
        edges = way_edges([(g["lat"], g["lon"]) for g in geom], proj, terrain, water, hw in BUILT_ROADS)
        for a, b, edge in zip(nodes, nodes[1:], edges):
            if a == b or edge is None:  # edge None: steeper than IMPASSABLE_GRADE somewhere along it
                continue
            edge["highway"] = hw
            if G.has_edge(a, b) and G[a][b]["cost"] <= edge["cost"]:
                continue
            G.add_edge(a, b, **edge, a=a)

    places_out: list[dict[str, Any]] = []
    route_feats: list[dict[str, Any]] = []
    start_info: dict[str, Any] = {}
    if G.number_of_nodes() == 0:
        notes.append("No walkable OpenStreetMap ways found near the village point.")
    else:
        comps = sorted(nx.connected_components(G), key=len, reverse=True)
        comp_of = {n: i for i, c in enumerate(comps) for n in c}
        near = [(haversine(vlat, vlon, *coords[n]), n) for n in G.nodes]
        near_ok = [(d, n) for d, n in near if d <= SNAP_MAX_M]
        if not near_ok:
            notes.append(f"No walkable way within {int(SNAP_MAX_M)} m of the village point.")
        else:
            # Prefer the biggest network close to the village, then the nearest node in it.
            d0, start = min(near_ok, key=lambda dn: (comp_of[dn[1]], dn[0]))
            comp = comps[comp_of[start]]
            start_info = {"lat": coords[start][0], "lon": coords[start][1], "snap_m": round(d0)}
            dist, paths = nx.single_source_dijkstra(G.subgraph(comp), start, weight="cost")
            routed = []
            for c in cands:
                snaps = [(haversine(c["lat"], c["lon"], *coords[n]), n) for n in comp]
                sd, target = min(snaps)
                if sd > SNAP_MAX_M or target not in dist:
                    c["unreachable"] = "no mapped way reaches it" if sd > SNAP_MAX_M else "steep or cut off"
                    continue
                path = paths[target]
                stats = route_stats(G, path, coords, d0, sd)
                c.update(stats)
                c["score"] = round(c["walk_min"] - 0.1 * min(c["headroom_m"], 100.0), 2)
                c["_path"] = path
                routed.append(c)
            routed.sort(key=lambda c: (c["score"], -c["headroom_m"]))
            for rank, c in enumerate(routed[:MAX_PLACES], start=1):
                c["rank"] = rank
                route_feats += route_features(G, c.pop("_path"), coords, (vlat, vlon), (c["lat"], c["lon"]), rank,
                                              c["id"])
                places_out.append(c)
            unreached = [c for c in cands if "unreachable" in c]
            if unreached:
                notes.append(f"{len(unreached)} high candidate(s) not reachable on mapped ways.")

    if not cands:
        notes.append("No named OpenStreetMap candidate at least 15 m above the river within 3 km; "
                     "the pradhan needs to add places by hand.")
    elif len(places_out) < 2:
        notes.append("Fewer than two routed safe places: OpenStreetMap coverage here is thin.")

    for c in places_out:
        c.pop("score", None)

    features: list[dict[str, Any]] = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [vlon, vlat]},
        "properties": {"feature": "start", "name": v["name"], "name_hi": v["name_hi"],
                       "elevation_m": round(village_elev, 1)},
    }]
    for c in places_out:
        props = {k: val for k, val in c.items() if k not in {"lat", "lon"}}
        props["feature"] = "place"
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
                         "properties": props})
    features += route_feats

    meta = {
        "village_id": vid,
        "village": {"name": v["name"], "name_hi": v["name_hi"], "lat": vlat, "lon": vlon,
                    "coords_verified": v.get("coords_verified", False)},
        "river_level_m": round(river_m, 1),
        "river_level_method": f"lowest terrain cell within {RIVER_SEARCH_M} m of the village point",
        "river_level_point": [round(rlon, 5), round(rlat, 5)],
        "nearest_mapped_waterway": nearest_water,
        "mapped_waterway_names": sorted(river_names)[:8],
        "village_point_elevation_m": round(village_elev, 1),
        "start": start_info or None,
        "candidates": {**counts, "eligible": len(cands)},
        "places": [{k: c.get(k) for k in ("id", "name", "name_hi", "kind", "headroom_m", "route_length_m",
                                          "climb_m", "max_grade", "walk_min", "rank")} for c in places_out],
        "notes": notes,
    }
    geo = {
        "type": "FeatureCollection",
        "attribution": ATTRIBUTION,
        "terrain_attribution": TERRAIN_ATTRIBUTION,
        "license": "ODbL 1.0 (https://opendatacommons.org/licenses/odbl/); derived database of OpenStreetMap data",
        "metadata": meta,
        "features": features,
    }
    return geo, meta


def way_edges(geom: list[tuple[float, float]], proj: Proj, terrain: Terrain,
              water: SegIndex, built_road: bool = False) -> list[dict[str, Any] | None]:
    """Length, climb, worst grade and cost of each segment of one OSM way.

    The way is sampled every SAMPLE_M along its length; the terrain profile is
    smoothed over SMOOTH_M either side and grades are measured over GRADE_BASE_M,
    because a 30 m terrain model read along a road cut into a hillside reports
    the hillside, not the road. None marks a footpath segment steeper than
    IMPASSABLE_GRADE. A built road (built_road) is never cut: its builders kept it
    drivable, so a steep reading there is terrain-model noise and only costs x3.
    """
    seg_len = [haversine(*a, *b) for a, b in zip(geom, geom[1:])]
    cum = [0.0]
    for L in seg_len:
        cum.append(cum[-1] + L)
    total = cum[-1]
    n = max(1, int(math.ceil(total / SAMPLE_M)))
    ss = [total * i / n for i in range(n + 1)]
    pts = []
    k = 0
    for s in ss:
        while k < len(seg_len) - 1 and cum[k + 1] < s:
            k += 1
        L = seg_len[k] or 1.0
        f = min(1.0, max(0.0, (s - cum[k]) / L))
        a, b = geom[k], geom[k + 1]
        pts.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    raw = [terrain.elev(*p) for p in pts]
    w = max(0, int(round(SMOOTH_M / (total / n)))) if total > 0 else 0
    z = [sum(raw[max(0, i - w):i + w + 1]) / len(raw[max(0, i - w):i + w + 1]) for i in range(n + 1)]

    def z_at(s: float) -> float:
        x = min(n, max(0.0, s / total * n)) if total > 0 else 0.0
        i = min(n - 1, int(x))
        f = x - i
        return z[i] * (1 - f) + z[i + 1] * f

    half = min(GRADE_BASE_M, total) / 2
    out: list[dict[str, Any] | None] = []
    for i, L in enumerate(seg_len):
        if L == 0:
            out.append(None)
            continue
        m = max(1, int(math.ceil(L / SAMPLE_M)))
        grades, near_water = [], 0.0
        for j in range(m):
            s = cum[i] + L * (j + 0.5) / m
            lo, hi = max(0.0, s - half), min(total, s + half)
            if hi - lo < 2 * half:  # near a way end: keep the full baseline
                lo, hi = (0.0, 2 * half) if lo == 0.0 else (total - 2 * half, total)
            grades.append(abs(z_at(hi) - z_at(lo)) / max(1.0, hi - lo))
            la, lo_ = geom[i][0] + (geom[i + 1][0] - geom[i][0]) * (j + 0.5) / m, \
                geom[i][1] + (geom[i + 1][1] - geom[i][1]) * (j + 0.5) / m
            d, _ = water.nearest(*proj.xy(la, lo_), WATER_BUFFER_M)
            if d <= WATER_BUFFER_M:
                near_water += L / m
        max_grade = max(grades)
        if max_grade > IMPASSABLE_GRADE and not built_road:
            out.append(None)
            continue
        steep_len = sum(L / m for g in grades if g > STEEP_GRADE)
        dz = z_at(cum[i + 1]) - z_at(cum[i])
        cost = (L - steep_len) + STEEP_FACTOR * steep_len
        cost += (WATER_FACTOR - 1.0) * near_water * (cost / L)
        out.append({"length": L, "cost": cost, "climb": max(0.0, dz), "descent": max(0.0, -dz),
                    "max_grade": max_grade, "steep_len": steep_len, "near_water": near_water})
    return out


def route_stats(G: nx.Graph, path: list[int], coords: dict, start_snap: float, end_snap: float) -> dict[str, Any]:
    length = climb = steep = water = 0.0
    max_grade = 0.0
    for u, w in zip(path, path[1:]):
        e = G[u][w]
        up = e["climb"] if e["a"] == u else e["descent"]
        length += e["length"]
        climb += up
        steep += e["steep_len"]
        water += e["near_water"]
        max_grade = max(max_grade, e["max_grade"])
    total = round(length + start_snap + end_snap)  # walking time is worked out from the length people see
    return {
        "route_length_m": round(total),
        "off_network_m": round(start_snap + end_snap),
        "climb_m": round(climb),
        "max_grade": round(max_grade, 2),
        "steep_m": round(steep),
        "near_water_m": round(water),
        "walk_min": int(math.ceil(total / WALK_M_PER_MIN)),
    }


def route_features(G: nx.Graph, path: list[int], coords: dict, start: tuple[float, float],
                   end: tuple[float, float], rank: int, place_id: str) -> list[dict[str, Any]]:
    """The route as runs of steep and not-steep stretches (the map dashes the steep ones)."""
    runs: list[tuple[bool, list[tuple[float, float]]]] = []

    def push(steep: bool, a: tuple[float, float], b: tuple[float, float]) -> None:
        if runs and runs[-1][0] == steep:
            runs[-1][1].append(b)
        else:
            runs.append((steep, [a, b]))

    if path:
        push(False, start, coords[path[0]])  # the walk from the village point to the first mapped way
    for u, w in zip(path, path[1:]):
        e = G[u][w]
        push(e["max_grade"] > STEEP_GRADE, coords[u], coords[w])
    if path:
        push(False, coords[path[-1]], end)
    feats = []
    for steep, pts in runs:
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[round(lo, 6), round(la, 6)] for la, lo in pts]},
            "properties": {"feature": "route", "rank": rank, "place_id": place_id, "steep": steep},
        })
    return feats


def main() -> None:
    villages = json.loads((ROOT / "data" / "villages.json").read_text(encoding="utf-8"))["villages"]
    only = set(sys.argv[1:])
    OUT.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "attribution": ATTRIBUTION,
        "terrain_attribution": TERRAIN_ATTRIBUTION,
        "method": {
            "candidates": "OpenStreetMap amenity=school|college|hospital|clinic|community_centre|townhall|"
                          "place_of_worship|shelter and building=school|public, within 3 km of the village point; "
                          "named only; bus shelters dropped",
            "headroom": "terrain height above the lowest cell within 500 m of the village point, and above the "
                        "nearest mapped stream within 1 km of the place; the smaller counts; at least 15 m",
            "routes": "Dijkstra on OpenStreetMap footways, paths, tracks and roads; cost = length x slope penalty "
                      "(grade over 35 % impassable, 20-35 % x3, under 20 % x1), x4 within 30 m of a mapped "
                      "waterway; slope-aware, avoids steep chutes",
            "walking_pace": "3 km/h (hill pace)",
            "ranking": "walking minutes minus one minute per 10 m of headroom (capped at 100 m); top 3 kept",
            "terrain": "Mapzen Terrain Tiles (terrarium), zoom 13, bilinear; about 30 m source resolution",
            "limits": "OpenStreetMap coverage in rural Himachal is incomplete and village points are approximate; "
                      "every place and route needs checking on the ground by the pradhan before an event.",
        },
        "villages": {},
    }
    with httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT}) as client:
        terrain = Terrain(client)
        first = True
        for v in villages:
            if only and v["id"] not in only:
                continue
            if not first and not (CACHE / "overpass" / f"{v['id']}.json").exists():
                time.sleep(20)  # one query per village, spaced out
            first = False
            geo, meta = bake_village(v, client, terrain)
            (OUT / f"{v['id']}.geojson").write_text(json.dumps(geo, ensure_ascii=False, indent=1) + "\n",
                                                   encoding="utf-8")
            summary["villages"][v["id"]] = meta
            print(f"{v['id']}: river {meta['river_level_m']} m, candidates {meta['candidates']}, "
                  f"places {[(p['name'], p['headroom_m'], p['route_length_m']) for p in meta['places']]}, "
                  f"notes {meta['notes']}")
        print(f"terrain tiles fetched: {terrain.fetched}")
    if only and (OUT / "summary.json").exists():
        old = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
        old["villages"].update(summary["villages"])
        summary["villages"] = old["villages"]
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
