"""Add a village, and its district when it is new, to data/ without a code edit (docs/DEPLOY.md,
"Adding a village or a district").

    backend/.venv/bin/python scripts/add_village.py --name Bali --name-hi "बाली" --district Mandi \
        --lat 31.61 --lon 77.12 [--district-hi मंडी --lgd-district 22 --lgd-village 012345] [--id bali] [--offline]

or `make add-village NAME=... NAME_HI=... DISTRICT=... LAT=... LON=...`.

What it writes:
- data/villages.json: the village (coordinates marked unverified, no gauge, no devices), with its LGD village
  code when given;
- data/districts.json: the district when it is new (Hindi name, LGD code, an empty officer list);
- data/official_sources.json: the IMD district and empty CWC stations, to fill in;
- data/river_cells.json: the GloFAS cells within 7 km and the cell the existing rule suggests (largest mean
  flow; scripts/calibrate.py --cells), unless --offline or the flood API cannot be reached. It never sets the
  chosen cell: that is checked by hand against OpenStreetMap and the model's routing;
- data/onboarding/<id>.md: the checklist of what is still to be verified by people, also printed.

Nothing is sent to AWS. `make seed` then puts the village (and its district's codes) into the table.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

INDIA = {"lat": (6.0, 37.5), "lon": (68.0, 97.5)}


def slug(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_cells(lat: float, lon: float) -> dict[str, Any]:
    """The existing --cells logic (scripts/calibrate.py) for one point: candidates and the rule's suggestion."""
    import time

    import httpx

    from Pukaar.scripts import calibrate

    rows = []
    with httpx.Client(timeout=60) as client:
        for clat, clon, d in calibrate.cell_centres(lat, lon):
            pairs, cell = calibrate.fetch_series(client, clat, clon, *calibrate.RANK_WINDOW)
            qs = [q for _, q in pairs]
            rows.append({"lat": cell["lat"], "lon": cell["lon"], "km": d,
                         "mean": round(sum(qs) / len(qs), 3) if qs else None,
                         "max": round(max(qs), 2) if qs else None, "days": len(qs)})
            time.sleep(1)
    rows.sort(key=lambda r: -(r["mean"] or 0))
    best = calibrate.suggest_cell(rows)
    return {"candidates": rows, "rule_suggests": {k: best[k] for k in ("lat", "lon", "mean")} if best else None}


def checklist(v: dict, district_new: bool, cells: dict | None, cells_note: str) -> str:
    vid = v["id"]
    lines = [f"# Onboarding {v['name']} ({v['name_hi']}), {v['district']}: what people still have to check",
             "",
             f"Written by scripts/add_village.py. The village id (its Telegram code) is `{vid}`: "
             f"`/start {vid}` in the bot.",
             "",
             "- [ ] Coordinates checked on the ground or against the revenue map (`coords_verified` is false until then).",
             "- [ ] LGD village code verified on lgdirectory.gov.in and set as `lgd_code` in data/villages.json"
             + (" (given, still to check)." if v.get("lgd_code") else " (none given).")]
    if district_new:
        lines += ["- [ ] New district: its Hindi name and LGD district code checked in data/districts.json.",
                  "- [ ] New district: its fallback officers named in data/districts.json, its DDMA head and officers "
                  "assigned (`make staff-assign`), its duty roster filled for the coming weeks."]
    if cells and cells.get("candidates"):
        s = cells.get("rule_suggests") or {}
        lines.append(f"- [ ] River cell chosen by hand in data/river_cells.json (`chosen`): {len(cells['candidates'])} "
                     f"candidates within 7 km; the rule suggests {s.get('lat')}, {s.get('lon')} (mean {s.get('mean')} "
                     "m³/s). Check it is the stream that floods the village (OpenStreetMap, the model's routing); a "
                     "cell no larger than one 0.05° cell of flow is a weak signal: plan a gauge or rain node.")
    else:
        lines.append(f"- [ ] River cells not searched ({cells_note}): run `python -m Pukaar.scripts.calibrate --cells` "
                     "from backend/ with PYTHONPATH=src, then choose the cell by hand.")
    lines += [
        "- [ ] Return-period thresholds: `python -m Pukaar.scripts.calibrate` (and `--soil`) once the cell is chosen.",
        "- [ ] Official sources in data/official_sources.json: IMD district checked; CWC station codes on its river, if any.",
        "- [ ] Safe places and walking routes: `scripts/build_safe_places.py`, then the pradhan walks each route.",
        "- [ ] Gauge, siren or rain node, if any: added under `gauge` / `devices` in data/villages.json and provisioned.",
        "- [ ] Village card printed with the bot name and the code above; the pradhan's consent to the pilot recorded.",
        "- [ ] `make seed` (the village and its district's codes into the table), and a Lambda image rebuild "
        "(`make deploy`) for the files read at run time (safe places, official sources).",
        "- [ ] One drill (`make drill VILLAGE=" + vid + "`) reached a registered phone.",
    ]
    return "\n".join(lines) + "\n"


def add_village(data_dir: Path, *, name: str, name_hi: str, district: str, lat: float, lon: float,
                district_hi: str | None = None, lgd_district: str | None = None, lgd_village: str | None = None,
                village_id: str | None = None, offline: bool = False,
                cells_fn: Callable[[float, float], dict] | None = None) -> dict[str, Any]:
    if not (INDIA["lat"][0] <= lat <= INDIA["lat"][1] and INDIA["lon"][0] <= lon <= INDIA["lon"][1]):
        raise ValueError(f"{lat}, {lon} is not in India: check the order (lat first) and the sign")
    for label, code in (("LGD district", lgd_district), ("LGD village", lgd_village)):
        if code and not code.isdigit():
            raise ValueError(f"{label} code must be digits, got {code!r}")
    vid = village_id or slug(name)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,39}", vid):
        raise ValueError(f"village id {vid!r}: lower-case letters, digits and '-', 2-40 characters")

    vpath, dpath = data_dir / "villages.json", data_dir / "districts.json"
    villages, districts = _load(vpath), _load(dpath)
    villages.setdefault("villages", [])
    if any(v["id"] == vid for v in villages["villages"]):
        raise ValueError(f"village id {vid!r} exists already; give another with --id (e.g. {vid}-{slug(district)})")
    if any(v["name"].lower() == name.lower() and v["district"] == district for v in villages["villages"]):
        raise ValueError(f"{name} is already a village of {district}")

    table = districts.setdefault("districts", {})
    district_new = district not in table
    if district_new:
        if not district_hi:
            raise ValueError(f"{district} is a new district: give its Hindi name (--district-hi) and, if known, "
                             "its LGD code (--lgd-district)")
        table[district] = {"name_hi": district_hi, "state": "Himachal Pradesh", "lgd_state_code": "2",
                           "lgd_code": lgd_district or None, "officers": []}
    elif lgd_district and table[district].get("lgd_code") not in (None, lgd_district):
        raise ValueError(f"{district} has LGD code {table[district]['lgd_code']} in districts.json, not {lgd_district}")

    entry: dict[str, Any] = {"id": vid, "name": name, "name_hi": name_hi, "district": district,
                             "lat": round(lat, 5), "lon": round(lon, 5),
                             "coords_source": "scripts/add_village.py: entered by hand, not verified on the ground"}
    if lgd_village:
        entry["lgd_code"] = lgd_village
    entry["devices"] = []

    cells, cells_note = None, "--offline"
    if not offline:
        try:
            cells = (cells_fn or find_cells)(lat, lon)
            cells_note = ""
        except Exception as exc:  # no network, a rate limit: the checklist says to run it later
            cells_note = f"the flood API could not be reached: {type(exc).__name__}"

    villages["villages"].append(entry)
    _write(vpath, villages)
    _write(dpath, districts)
    spath = data_dir / "official_sources.json"
    sources = _load(spath)
    sources.setdefault("villages", {})[vid] = {"imd_district": district, "cwc_rivers": [], "cwc_stations": [],
                                               "flood_hub_radius_km": 25, "bipad_stations": []}
    _write(spath, sources)
    if cells is not None:
        cpath = data_dir / "river_cells.json"
        current = _load(cpath)
        current.setdefault("villages", {})[vid] = {"village": {"lat": entry["lat"], "lon": entry["lon"]}, **cells}
        _write(cpath, current)
    text = checklist(entry, district_new, cells, cells_note)
    (data_dir / "onboarding").mkdir(exist_ok=True)
    (data_dir / "onboarding" / f"{vid}.md").write_text(text, encoding="utf-8")
    return {"id": vid, "district_new": district_new, "cells": bool(cells and cells.get("candidates")), "checklist": text}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--name", required=True)
    p.add_argument("--name-hi", required=True)
    p.add_argument("--district", required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--district-hi")
    p.add_argument("--lgd-district")
    p.add_argument("--lgd-village")
    p.add_argument("--id", dest="village_id")
    p.add_argument("--offline", action="store_true", help="do not search river cells (no network)")
    p.add_argument("--data-dir", type=Path, default=ROOT / "data")
    a = p.parse_args(argv)
    try:
        out = add_village(a.data_dir, name=a.name.strip(), name_hi=a.name_hi.strip(), district=a.district.strip(),
                          lat=a.lat, lon=a.lon, district_hi=a.district_hi, lgd_district=a.lgd_district,
                          lgd_village=a.lgd_village, village_id=a.village_id, offline=a.offline)
    except ValueError as exc:
        print(f"add_village: {exc}", file=sys.stderr)
        return 2
    print(out["checklist"])
    print(f"Written to data/: villages.json, districts.json, official_sources.json"
          f"{', river_cells.json' if out['cells'] else ''}, onboarding/{out['id']}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
