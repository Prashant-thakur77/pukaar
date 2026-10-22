"""Seed villages, thresholds, officers, past events and demo stub recipients.

Idempotent: re-running keeps each village's current level and each device's live health. Stub recipients
("Demo phone, stub channel") let the delivery records show without Telegram;
they never reach a real phone. Real recipients join through the bot (/start).

    python -m Pukaar.scripts.seed
"""

from __future__ import annotations

import json

from Pukaar.core.config import get_settings
from Pukaar.services import checklist
from Pukaar.services.devices import registry
from Pukaar.services.risk_rules import river_level
from Pukaar.store.models import GaugeConfig, PastEvent, Recipient, SoilRange, Thresholds, Village
from Pukaar.store.repo import Repo, get_repo

STUB_RECIPIENTS_PER_VILLAGE = 2


def seed(repo: Repo) -> list[str]:
    s = get_settings()
    cfg = json.loads((s.data_dir / "villages.json").read_text(encoding="utf-8"))
    th_path = s.data_dir / "thresholds.json"
    thresholds = json.loads(th_path.read_text(encoding="utf-8")) if th_path.exists() else {}
    officers = [o["username"] for o in cfg.get("officers", [])]
    seeded = []
    for raw in cfg["villages"]:
        existing = repo.get_village(raw["id"])
        th = thresholds.get(raw["id"])
        village = Village(
            id=raw["id"], name=raw["name"], name_hi=raw["name_hi"], district=raw["district"], lat=raw["lat"],
            lon=raw["lon"], coords_verified=False, coords_source=raw.get("coords_source"), population=None,
            officers=officers,
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
        for i in range(1, STUB_RECIPIENTS_PER_VILLAGE + 1):
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
    return seeded


def main() -> None:
    print("seeded:", ", ".join(seed(get_repo())))


if __name__ == "__main__":
    main()
