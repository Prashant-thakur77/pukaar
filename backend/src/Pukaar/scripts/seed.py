"""Seed villages, thresholds, officers, past events and demo stub recipients.

Idempotent: re-running keeps each village's current level and each device's live health. Stub recipients
("Demo phone, stub channel") let the delivery records show without Telegram;
they never reach a real phone. Real recipients join through the bot (/start).

    python -m Pukaar.scripts.seed
"""

from __future__ import annotations

import json
import os

from Pukaar.core.config import get_settings
from Pukaar.services import checklist
from Pukaar.services.devices import registry
from Pukaar.services.risk_rules import river_level
from Pukaar.store.models import GaugeConfig, PastEvent, Recipient, SoilRange, Thresholds, Village
from Pukaar.store.repo import Repo, get_repo

STUB_RECIPIENTS_PER_VILLAGE = 2


def is_production(stage: str | None = None) -> bool:
    """A production stage (PUKAAR_STAGE=prod, or a stack named *-prod): no demo officers on every village."""
    stage = get_settings().stage if stage is None else stage
    return stage == "prod" or os.environ.get("PUKAAR_STACK", "").endswith("-prod")


def village_officers(raw: dict, district: dict, demo_officers: list[str], production: bool) -> list[str]:
    """A village's fallback approval chain (Village.officers; used when no roster row covers the shift).
    The village's own list in villages.json wins; then, on a dev stage, the demo officers on every village
    (officer1, officer2: the demo's behaviour); on production, the district's own list in districts.json,
    which is empty until the DDMA names it: never the same two people for every village of the state."""
    if raw.get("officers"):
        return [str(o) for o in raw["officers"]]
    if not production:
        return list(demo_officers)
    return [str(o) for o in district.get("officers") or []]


def migrate_alerts(repo: Repo) -> int:
    """Idempotent: alerts written before the status index (gsi2) and the per-village alert pointers get them,
    and their counters are repaired into the per-person markers (delivery/dispatch.repair_counts)."""
    from Pukaar.delivery import dispatch

    moved = 0
    for alert_id in repo.all_alert_ids():
        if repo.index_alert(alert_id):
            dispatch.repair_counts(repo, alert_id, emit=False)
            moved += 1
    return moved


def seed(repo: Repo) -> list[str]:
    s = get_settings()
    production = is_production()
    cfg = json.loads((s.data_dir / "villages.json").read_text(encoding="utf-8"))
    dpath = s.data_dir / "districts.json"
    districts = json.loads(dpath.read_text(encoding="utf-8")).get("districts", {}) if dpath.exists() else {}
    th_path = s.data_dir / "thresholds.json"
    thresholds = json.loads(th_path.read_text(encoding="utf-8")) if th_path.exists() else {}
    officers = [o["username"] for o in cfg.get("officers", [])]
    seeded = []
    for raw in cfg["villages"]:
        existing = repo.get_village(raw["id"])
        th = thresholds.get(raw["id"])
        district = districts.get(raw["district"]) or {}
        village = Village(
            id=raw["id"], name=raw["name"], name_hi=raw["name_hi"], district=raw["district"], lat=raw["lat"],
            lon=raw["lon"], coords_verified=False, coords_source=raw.get("coords_source"), population=None,
            officers=village_officers(raw, district, officers, production),
            district_hi=district.get("name_hi"), lgd_district_code=district.get("lgd_code") or None,
            lgd_village_code=raw.get("lgd_code") or None,
            # The keypad code a caller keys in on the enrolment IVR (delivery/inbound.py), on the village card.
            ivr_code=str(raw["ivr_code"]) if raw.get("ivr_code") else None,
            thresholds=Thresholds.from_file(th) if th else None,
            # Illustrative thresholds, to be set from the gauge's own record after installation.
            gauge=GaugeConfig.model_validate(raw["gauge"]) if raw.get("gauge") else None,
            soil=SoilRange.model_validate(th["soil"]) if th and th.get("soil") else None,
        )
        if existing is not None:
            village.level, village.level_since, village.calm_sweeps = existing.level, existing.level_since, existing.calm_sweeps
            village.open_alert_id, village.last_alert_id = existing.open_alert_id, existing.last_alert_id
            village.data_status, village.data_ok_at = existing.data_status, existing.data_ok_at
            village.data_missing_sweeps, village.data_note = existing.data_missing_sweeps, existing.data_note
            village.replay = False  # live records never carry the replay flag (services/replay.py)
        repo.put_village(village)
        for i in range(1, 0 if production else STUB_RECIPIENTS_PER_VILLAGE + 1):  # demo phones: dev only
            # The first demo phone stands for the pradhan: a relay, contacted first (delivery/dispatch.py).
            repo.put_recipient(Recipient(id=f"stub-{raw['id']}-{i}", village_id=raw["id"],
                                         name=f"Demo phone {i} (stub channel)", channel="stub",
                                         role="pradhan" if i == 1 else "villager"))
        for ev in (th or {}).get("past_events", []):
            # The level the river rule gives that day's discharge (at least Watch: these are the record's top days).
            level = river_level(ev["discharge"], village.thresholds)
            level = level if level != "normal" else "watch"
            record = "-".join(str(y) for y in th.get("record_years", [])) if th else ""
            repo.put_past_event(PastEvent(
                village_id=raw["id"], date=ev["date"], level=level,
                note_en=f"River discharge reached {ev['discharge']} m³/s on {ev['date']}, one of the highest days in "
                        f"the {record or 'archived'} record for this river cell.",
                note_hi=f"{ev['date']} को नदी का बहाव {ev['discharge']} m³/s तक पहुँचा था।",
                source="Open-Meteo flood API (GloFAS reanalysis), daily river discharge",
            ))
        checklist.seed(repo, raw["id"])
        # The device registry: the village's sirens and boxes (labelled simulators today) and its gauge.
        registry.seed_village(repo, village, raw.get("devices") or [])
        seeded.append(raw["id"])
    if not production:
        # The demo officers act on every district (services/scope.py); on production the DDMA assigns each
        # officer to their districts (make staff-assign) or rosters them.
        names = sorted({str(raw["district"]) for raw in cfg["villages"]})
        for o in officers:
            repo.put_staff_scope(o, names)
        if "Mandi" in names:
            repo.put_staff_scope("ddma_mandi", ["Mandi"])  # the local demo DDMA head (api/auth.DEV_USERS)
    migrate_alerts(repo)
    return seeded


def main() -> None:
    print("seeded:", ", ".join(seed(get_repo())))


if __name__ == "__main__":
    main()
