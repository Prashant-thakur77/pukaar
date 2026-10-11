"""JSON shapes returned by the API (docs/CONTRACT.md)."""

from __future__ import annotations

from typing import Any

from Pukaar.services import gauge, storage
from Pukaar.services.nowcast import nowcast
from Pukaar.store.models import Alert, Report, Village
from Pukaar.store.repo import Repo

_ALERT_HIDDEN = {"task_token", "token_version", "execution_arn", "audio_key"}


def village(repo: Repo, v: Village) -> dict[str, Any]:
    latest = repo.list_readings(v.id, limit=1)
    out = v.model_dump()
    out["latest_reading"] = latest[0].model_dump() if latest else None
    return out


def alert(a: Alert) -> dict[str, Any]:
    out = a.model_dump(exclude=_ALERT_HIDDEN)
    out["has_audio"] = bool(a.audio_key)
    return out


def report(r: Report, *, public: bool = False) -> dict[str, Any]:
    out = r.model_dump(exclude={"photo_key", "audio_key", "masked_text"})
    out["photo_url"] = storage.url_for(r.photo_key)
    out["audio_url"] = storage.url_for(r.audio_key)
    out["held"] = r.held
    if r.masked_text and r.screen is not None:
        # Show the guardrail's copy: phone numbers and e-mails masked. The original stays in the table.
        out[r.screen.field] = r.masked_text
    if public and r.held:
        # Words held for review are not published; officers read them in the console.
        out.update(text="", transcript="", summary_en="", reply_hi="")
    return out


def village_detail(repo: Repo, v: Village) -> dict[str, Any]:
    readings = repo.list_readings(v.id, limit=96)
    return {
        "village": village(repo, v),
        "readings": [r.model_dump() for r in readings],
        "alerts": [alert(a) for a in repo.list_alerts(village_id=v.id, limit=20)],
        "reports": [report(r, public=True) for r in repo.list_reports(v.id, limit=30)],
        "past_events": [e.model_dump() for e in repo.list_past_events(v.id)],
        "directives": [d.model_dump() for d in repo.list_directives(v.id)[:5]],
        "nowcast": nowcast(readings[0] if readings else None, v.thresholds, v.level),
        "gauge": gauge.view(repo, v),
    }


def counters(repo: Repo) -> dict[str, int]:
    villages = repo.list_villages()
    alerts = repo.list_alerts(limit=500)
    sent = [a for a in alerts if a.status in {"delivered", "auto_sent_unapproved", "failsafe"} and not a.replay]
    return {
        "villages_watched": len(villages),
        "alerts_sent": len(sent),
        "phones_acknowledged": sum(a.acknowledged_count for a in sent),
        "reports_received": sum(1 for v in villages for r in repo.list_reports(v.id, limit=500) if not r.replay),
    }
