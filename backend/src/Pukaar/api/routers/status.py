"""The small public answer for one village: its level, what to do, where to go and when it was checked.

GET /public/villages/{id}/now is what the village page paints first (about 2 kB gzipped, against about 8 kB
gzipped and 235 kB raw for /villages/{id}). The page shows it at once, keeps it on the phone for the next
visit and for no signal, then loads the full detail. No personal data: no officer names, no reports.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response

from Pukaar.core import clock
from Pukaar.services import replay as replay_svc
from Pukaar.services import safe_places
from Pukaar.store.repo import get_repo
from Pukaar.templates import actions

router = APIRouter()

# Long enough to absorb a crowd opening the same SMS link, short against a 15-minute sweep.
NOW_CACHE = {"Cache-Control": "public, max-age=30, stale-while-revalidate=60"}
MAX_POINTS = 96


def _level_known(level: str, data_status: str) -> bool:
    """Normal with late or missing forecast data means "no data says otherwise", never "safe"."""
    return not (level == "normal" and data_status in {"stale", "unavailable"})


def _decimate(points: list[list[Any]], n: int = MAX_POINTS) -> list[list[Any]]:
    """At most n points, evenly spaced, always keeping the newest."""
    if len(points) <= n:
        return points
    step = (len(points) - 1) / (n - 1)
    return [points[round(i * step)] for i in range(n)]


def _safe_place(village_id: str) -> dict[str, Any] | None:
    """The first-ranked place whose route no active road block crosses (the map's "best open route")."""
    view = safe_places.view(get_repo(), village_id)
    if not view.get("available"):
        return None
    places = view["places"]
    p = next((x for x in places if x.get("best_open_route")), None) or (places[0] if places else None)
    if p is None:
        return None
    return {
        "id": p["id"], "name": p.get("name"), "name_hi": p.get("name_hi"), "kind_en": p.get("kind_en"),
        "kind_hi": p.get("kind_hi"), "walk_min": p.get("walk_min"), "route_length_m": p.get("route_length_m"),
        "headroom_m": p.get("headroom_m"), "status": p["ledger"]["status"], "route_blocked": p["route_blocked"],
    }


def now_view(village_id: str) -> dict[str, Any]:
    repo = get_repo()
    v = repo.get_village(village_id)
    if v is None:
        raise HTTPException(404, "Village not found")
    shown = replay_svc.display(repo, [v])[v.id]
    level = shown["level"]
    known = _level_known(level, v.data_status)
    # One time axis: the replay's readings while a replay is shown, the live ones otherwise.
    readings = [r for r in repo.list_readings(v.id, limit=MAX_POINTS) if bool(r.replay) == bool(shown["replay"])]
    readings.sort(key=lambda r: r.at)
    latest = readings[-1] if readings else None
    series = [[r.at, r.discharge] for r in readings if r.discharge is not None]
    return {
        "id": v.id, "name": v.name, "name_hi": v.name_hi, "district": v.district,
        "level": level, "level_since": shown["level_since"], "live_level": v.level, "replay": shown["replay"],
        "level_known": known,
        "data_status": v.data_status, "data_ok_at": v.data_ok_at,
        "checked_at": latest.at if latest else None,
        "means": actions.MEANS[level],
        "actions": actions.ACTIONS[level] if known else actions.NO_DATA,
        "safe_place": _safe_place(v.id),
        "river": {
            "unit": "m3/s",
            "thresholds": ({k: getattr(v.thresholds, k) for k in ("watch", "warning", "critical")}
                           if v.thresholds else None),
            "points": _decimate(series),
        },
        "generated_at": clock.iso(clock.now()),
    }


@router.get("/public/villages/{village_id}/now")
def village_now(village_id: str, response: Response) -> dict[str, Any]:
    body = now_view(village_id)
    response.headers.update(NOW_CACHE)
    return body
