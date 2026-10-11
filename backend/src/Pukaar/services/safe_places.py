"""Named safe places, walking routes and the shelter ledger.

Places and routes are baked offline from OpenStreetMap and the terrain tiles by
scripts/build_safe_places.py into data/safe_places/<village>.geojson (shipped in
the Lambda image with the rest of data/). Nothing here invents a place: an
unknown place id is refused, and a place is named in an alert only after a
pradhan or officer has marked it OPEN or STANDBY in the ledger.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.store.models import RoadBlock, ShelterStatus
from Pukaar.store.repo import Repo

USABLE = ("OPEN", "STANDBY")  # an alert may name a place in one of these states, OPEN first
LIMITS_EN = ("Places come from OpenStreetMap, which is incomplete in rural Himachal, and the village point is "
             "approximate. The pradhan must check each place and route on the ground before an event.")
LIMITS_HI = ("जगहें OpenStreetMap से ली गई हैं, जो ग्रामीण हिमाचल में अधूरा है, और गाँव का बिंदु अनुमानित है। "
             "आपदा से पहले प्रधान हर जगह और रास्ते को मौके पर जाँचें।")
ROUTE_LIMIT_EN = ("Routes are worked out in advance from OpenStreetMap. Marking a road blocked does not draw a new "
                  "route: Pukaar crosses out every baked route through that point and promotes the next baked route, "
                  "or says no open route is known.")
ROUTE_LIMIT_HI = ("रास्ते OpenStreetMap से पहले ही तय किए गए हैं। सड़क बंद बताने से नया रास्ता नहीं बनता: पुकार उस "
                  "जगह से गुज़रने वाला हर तय रास्ता काटता है और अगला तय रास्ता आगे करता है, या बताता है कि कोई खुला "
                  "रास्ता पता नहीं।")
# A block counts against every baked route that passes within this distance of its point.
ROADBLOCK_RADIUS_M = 30.0
# A new block must sit on (within this distance of) one of the village's baked routes.
ROADBLOCK_SNAP_M = 60.0
ROADBLOCK_DAYS = 7


@lru_cache(maxsize=16)
def load(village_id: str) -> dict[str, Any] | None:
    """The baked FeatureCollection for a village, or None when none was baked."""
    if not village_id.replace("-", "").replace("_", "").isalnum():
        return None
    path = get_settings().data_dir / "safe_places" / f"{village_id}.geojson"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def baked_places(village_id: str) -> list[dict[str, Any]]:
    """Places in route-rank order: properties plus lat/lon."""
    geo = load(village_id)
    if not geo:
        return []
    out = []
    for f in geo.get("features", []):
        props = f.get("properties", {})
        if props.get("feature") != "place":
            continue
        lon, lat = f["geometry"]["coordinates"]
        out.append({k: v for k, v in props.items() if k != "feature"} | {"lat": lat, "lon": lon})
    return sorted(out, key=lambda p: p.get("rank") or 99)


def place_ids(village_id: str) -> set[str]:
    return {p["id"] for p in baked_places(village_id)}


# -- road blocks ---------------------------------------------------------------------
def _xy(lon: float, lat: float, lat0: float) -> tuple[float, float]:
    """Metres on a local flat projection (good to well under a metre over a few km)."""
    k = 111_320.0
    return lon * k * math.cos(math.radians(lat0)), lat * k


def distance_to_line_m(lat: float, lon: float, coords: list) -> float:
    """Shortest distance in metres from a point to a [lon, lat] polyline."""
    if not coords:
        return math.inf
    px, py = _xy(lon, lat, lat)
    pts = [_xy(c[0], c[1], lat) for c in coords]
    if len(pts) == 1:
        return math.hypot(pts[0][0] - px, pts[0][1] - py)
    best = math.inf
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
        best = min(best, math.hypot(ax + t * dx - px, ay + t * dy - py))
    return best


def route_lines(village_id: str) -> dict[str, list[list]]:
    """place id -> the LineStrings of its baked route (a route is split where it turns steep)."""
    out: dict[str, list[list]] = {}
    for f in (load(village_id) or {}).get("features", []):
        props = f.get("properties", {})
        if props.get("feature") == "route" and f["geometry"]["type"] == "LineString":
            out.setdefault(props["place_id"], []).append(f["geometry"]["coordinates"])
    return out


def distance_to_routes_m(village_id: str, lat: float, lon: float) -> float:
    """How far a point is from the nearest of the village's baked routes."""
    return min((distance_to_line_m(lat, lon, line) for lines in route_lines(village_id).values() for line in lines),
               default=math.inf)


def blocked_routes(village_id: str, blocks: list[RoadBlock]) -> dict[str, list[RoadBlock]]:
    """place id -> the active blocks that cross its baked route."""
    out: dict[str, list[RoadBlock]] = {}
    if not blocks:
        return out
    for pid, lines in route_lines(village_id).items():
        hits = [b for b in blocks if any(distance_to_line_m(b.lat, b.lon, ln) <= ROADBLOCK_RADIUS_M for ln in lines)]
        if hits:
            out[pid] = hits
    return out


def new_roadblock(village_id: str, block_id: str, lat: float, lon: float, label: str, note: str, actor: str,
                  now: datetime) -> RoadBlock:
    """Validate and build a block. Raises ValueError with a reason a person can act on."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("lat and lon must be a real point")
    note = note.strip()[:200]
    if not note:
        raise ValueError("Say what is blocked (a note is required)")
    if distance_to_routes_m(village_id, lat, lon) > ROADBLOCK_SNAP_M:
        raise ValueError("A block must be on one of this village's walking routes; tap the route on the map")
    return RoadBlock(id=block_id, village_id=village_id, lat=round(lat, 6), lon=round(lon, 6),
                     label=label.strip()[:80], note=note, created_by=actor, created_at=clock.iso(now),
                     expires_at=clock.iso(now + timedelta(days=ROADBLOCK_DAYS)))


def renewed(b: RoadBlock, actor: str, now: datetime) -> RoadBlock:
    return b.model_copy(update={"renewed_by": actor, "renewed_at": clock.iso(now),
                                "expires_at": clock.iso(now + timedelta(days=ROADBLOCK_DAYS))})


def cleared(b: RoadBlock, actor: str, now: datetime) -> RoadBlock:
    return b.model_copy(update={"cleared_by": actor, "cleared_at": clock.iso(now)})


def _block_view(b: RoadBlock, place_ids: list[str]) -> dict[str, Any]:
    return {"id": b.id, "lat": b.lat, "lon": b.lon, "label": b.label, "note": b.note, "created_by": b.created_by,
            "created_at": b.created_at, "renewed_by": b.renewed_by, "renewed_at": b.renewed_at,
            "expires_at": b.expires_at, "place_ids": place_ids}


def _ledger_view(row: ShelterStatus | None) -> dict[str, Any]:
    if row is None:
        return {"status": "UNCONFIRMED", "capacity": None, "note": "", "updated_by": None, "updated_at": None}
    return {"status": row.status, "capacity": row.capacity, "note": row.note, "updated_by": row.updated_by,
            "updated_at": row.updated_at}


def view(repo: Repo, village_id: str) -> dict[str, Any]:
    """GET /villages/{id}/safe-places: places with their ledger state, routes, attribution and limits."""
    geo = load(village_id)
    ledger = repo.list_shelters(village_id)
    if not geo:
        return {"village_id": village_id, "available": False, "places": [], "routes": {"type": "FeatureCollection",
                "features": []}, "roadblocks": [], "notes": ["No safe places have been baked for this village."],
                "attribution": None, "limits_en": LIMITS_EN, "limits_hi": LIMITS_HI}
    meta = geo.get("metadata", {})
    blocks = repo.list_roadblocks(village_id)
    blocked = blocked_routes(village_id, blocks)
    baked = baked_places(village_id)
    # The best open route: the first baked route (by rank) that no active block crosses.
    best = next((p["id"] for p in baked if p["id"] not in blocked), None)
    places = []
    for p in baked:
        hits = blocked.get(p["id"], [])
        places.append(p | {"ledger": _ledger_view(ledger.get(p["id"])), "route_blocked": bool(hits),
                           "route_blocks": [{"id": b.id, "label": b.label, "note": b.note} for b in hits],
                           "best_open_route": p["id"] == best})
    routes = []
    for f in geo.get("features", []):
        props = f.get("properties", {})
        if props.get("feature") == "start":
            routes.append(f)
        elif props.get("feature") == "route":
            hits = blocked.get(props.get("place_id"), [])
            routes.append(f | {"properties": props | {"blocked": bool(hits), "best": props.get("place_id") == best,
                                                      "block_note": hits[0].note if hits else ""}})
    return {
        "village_id": village_id,
        "available": True,
        "places": places,
        "routes": {"type": "FeatureCollection", "features": routes},
        "roadblocks": [_block_view(b, sorted(pid for pid, bs in blocked.items() if b in bs)) for b in blocks],
        "route_limit_en": ROUTE_LIMIT_EN,
        "route_limit_hi": ROUTE_LIMIT_HI,
        "river_level_m": meta.get("river_level_m"),
        "river_level_method": meta.get("river_level_method"),
        "candidates": meta.get("candidates"),
        "notes": meta.get("notes", []),
        "attribution": geo.get("attribution"),
        "terrain_attribution": geo.get("terrain_attribution"),
        "license": geo.get("license"),
        "limits_en": LIMITS_EN,
        "limits_hi": LIMITS_HI,
    }


def usable(repo: Repo, village_id: str) -> list[dict[str, Any]]:
    """Places marked OPEN or STANDBY whose baked route no active block crosses; OPEN first, then by route rank.

    A place whose only known route is blocked is left out: an alert must not send
    people down a road someone has reported closed.
    """
    ledger = repo.list_shelters(village_id)
    blocked = blocked_routes(village_id, repo.list_roadblocks(village_id))
    out = []
    for p in baked_places(village_id):
        if p["id"] in blocked:
            continue
        row = ledger.get(p["id"])
        if row is not None and row.status in USABLE:
            out.append(p | {"status": row.status, "updated_by": row.updated_by, "updated_at": row.updated_at})
    return sorted(out, key=lambda p: (USABLE.index(p["status"]), p.get("rank") or 99))


def nearest_usable(repo: Repo, village_id: str) -> dict[str, Any] | None:
    """The place an alert may name, as recorded in the decision trace; None when no place is usable."""
    places = usable(repo, village_id)
    if not places:
        return None
    p = places[0]
    return {
        "id": p["id"],
        "name": p.get("name"),
        "name_hi": p.get("name_hi") or p.get("name"),
        "kind": p.get("kind"),
        "status": p["status"],
        "headroom_m": p.get("headroom_m"),
        "route_length_m": p.get("route_length_m"),
        "walk_min": p.get("walk_min"),
        "source": f"OpenStreetMap (ODbL), baked route; status {p['status']} set by {p['updated_by']} "
                  f"at {p['updated_at']}",
    }


def all_place_names() -> set[str]:
    """Every baked place name (English and Hindi) across the villages, for the draft checker."""
    names: set[str] = set()
    data_dir = get_settings().data_dir / "safe_places"
    if not data_dir.is_dir():
        return names
    for path in data_dir.glob("*.geojson"):
        for p in baked_places(path.stem):
            names |= {n for n in (p.get("name"), p.get("name_hi")) if n}
    return names
