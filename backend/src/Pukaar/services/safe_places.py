"""Named safe places, walking routes and the shelter ledger.

Places and routes are baked offline from OpenStreetMap and the terrain tiles by
scripts/build_safe_places.py into data/safe_places/<village>.geojson (shipped in
the Lambda image with the rest of data/). Nothing here invents a place: an
unknown place id is refused, and a place is named in an alert only after a
pradhan or officer has marked it OPEN or STANDBY in the ledger.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from Pukaar.core.config import get_settings
from Pukaar.store.models import ShelterStatus
from Pukaar.store.repo import Repo

USABLE = ("OPEN", "STANDBY")  # an alert may name a place in one of these states, OPEN first
LIMITS_EN = ("Places come from OpenStreetMap, which is incomplete in rural Himachal, and the village point is "
             "approximate. The pradhan must check each place and route on the ground before an event.")
LIMITS_HI = ("जगहें OpenStreetMap से ली गई हैं, जो ग्रामीण हिमाचल में अधूरा है, और गाँव का बिंदु अनुमानित है। "
             "आपदा से पहले प्रधान हर जगह और रास्ते को मौके पर जाँचें।")


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
                "features": []}, "notes": ["No safe places have been baked for this village."],
                "attribution": None, "limits_en": LIMITS_EN, "limits_hi": LIMITS_HI}
    meta = geo.get("metadata", {})
    places = [p | {"ledger": _ledger_view(ledger.get(p["id"]))} for p in baked_places(village_id)]
    routes = [f for f in geo.get("features", []) if f.get("properties", {}).get("feature") in {"route", "start"}]
    return {
        "village_id": village_id,
        "available": True,
        "places": places,
        "routes": {"type": "FeatureCollection", "features": routes},
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
    """Places marked OPEN or STANDBY, OPEN first, then by route rank."""
    ledger = repo.list_shelters(village_id)
    out = []
    for p in baked_places(village_id):
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
