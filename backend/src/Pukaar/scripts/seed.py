"""Seed villages, thresholds, officers, past events and demo stub recipients.

Idempotent: re-running keeps each village's current level. Stub recipients
("Demo phone, stub channel") let the delivery records show without Telegram;
they never reach a real phone. Real recipients join through the bot (/start).

    python -m Pukaar.scripts.seed
"""

from __future__ import annotations

import json

from Pukaar.core.config import get_settings
from Pukaar.store.models import PastEvent, Recipient, Thresholds, Village
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
            thresholds=Thresholds(watch=th["watch"], warning=th["warning"], critical=th["critical"], source=th["source"])
            if th else None,
        )
        if existing is not None:
            village.level, village.level_since, village.calm_sweeps = existing.level, existing.level_since, existing.calm_sweeps
            village.open_alert_id, village.replay = existing.open_alert_id, existing.replay
        repo.put_village(village)
        for i in range(1, STUB_RECIPIENTS_PER_VILLAGE + 1):
            repo.put_recipient(Recipient(id=f"stub-{raw['id']}-{i}", village_id=raw["id"],
                                         name=f"Demo phone {i} (stub channel)", channel="stub"))
        for ev in (th or {}).get("past_events", []):
            level = "critical" if th and ev["discharge"] >= th["critical"] else "warning"
            repo.put_past_event(PastEvent(
                village_id=raw["id"], date=ev["date"], level=level,
                note_en=f"River discharge reached {ev['discharge']} m³/s on {ev['date']}, one of the highest days in "
                        f"the 1984-2024 record for this river cell.",
                note_hi=f"{ev['date']} को नदी का बहाव {ev['discharge']} m³/s तक पहुँचा था।",
                source="Open-Meteo flood API (GloFAS reanalysis), daily river discharge",
            ))
        seeded.append(raw["id"])
    return seeded


def main() -> None:
    print("seeded:", ", ".join(seed(get_repo())))


if __name__ == "__main__":
    main()
