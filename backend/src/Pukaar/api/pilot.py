"""GET /public/pilot-metrics: what has been measured so far, for the /pilot page.

Every number is counted from stored records or read from data/backtest.json; nothing is estimated.
A number with nothing behind it yet is null, and the page says "not measured yet".
No names, phone numbers or chat ids: deliveries are only counted and timed.

drills      hand-started test alerts (scripts/drill.py) that reached at least one real phone
live        live flood alerts that went out (views.went_out); never replays, never drills
  alerts                    alerts in the group
  reached                   deliveries that reached a real phone (sent or acknowledged; the stub channel
                            for demo recipients is not a phone and is left out), summed over the alerts
  acknowledged              of those, how many pressed "मिल गया"
  ack_share                 acknowledged / reached, 0..1 (null when nothing was reached)
  median_minutes_first_ack  per alert: first send to the first acknowledgement; the median over alerts
  median_minutes_to_ack     per person: their send to their acknowledgement; the median over people
backtest    lead times from data/backtest.json (scripts/backtest.py), per scenario and village
"""

from __future__ import annotations

import json
from statistics import median
from typing import Any

from Pukaar.api import views
from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.store.models import Alert, Delivery
from Pukaar.store.repo import Repo

_REACHED = {"sent", "acknowledged"}


def _minutes(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    m = (clock.parse(end) - clock.parse(start)).total_seconds() / 60
    return m if m >= 0 else None


def _median(xs: list[float]) -> float | None:
    return round(median(xs), 1) if xs else None


def _real(deliveries: list[Delivery]) -> list[Delivery]:
    """Deliveries that reached a phone: never the stub channel, never a failure."""
    return [d for d in deliveries if d.channel != "stub" and d.status in _REACHED and d.sent_at]


def _group(pairs: list[tuple[Alert, list[Delivery]]]) -> dict[str, Any]:
    reached = acked = 0
    per_alert: list[float] = []
    per_person: list[float] = []
    for _, ds in pairs:
        reached += len(ds)
        acks = [d for d in ds if d.acknowledged_at]
        acked += len(acks)
        if acks:
            first_sent = min(d.sent_at for d in ds if d.sent_at)
            first_ack = min(d.acknowledged_at for d in acks if d.acknowledged_at)
            m = _minutes(first_sent, first_ack)
            if m is not None:
                per_alert.append(m)
        per_person += [m for m in (_minutes(d.sent_at, d.acknowledged_at) for d in acks) if m is not None]
    return {
        "alerts": len(pairs),
        "reached": reached,
        "acknowledged": acked,
        "ack_share": round(acked / reached, 3) if reached else None,
        "median_minutes_first_ack": _median(per_alert),
        "median_minutes_to_ack": _median(per_person),
    }


def backtest_lead_times() -> dict[str, Any] | None:
    path = get_settings().data_dir / "backtest.json"
    try:
        bt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    scenarios = []
    for sc in bt.get("scenarios", []):
        rows = [{"village_id": v.get("village_id"), "village": v.get("village"), "outcome": v.get("outcome"),
                 "lead_hours": v.get("lead_hours_watch_to_peak_day")} for v in sc.get("villages", [])]
        leads = [r["lead_hours"] for r in rows if isinstance(r["lead_hours"], (int, float))]
        scenarios.append({"name": sc.get("name"), "title": sc.get("title"), "title_hi": sc.get("title_hi"),
                          "villages_scored": len(rows), "villages_alerted": len(leads),
                          "median_lead_hours": _median(leads), "max_lead_hours": max(leads) if leads else None,
                          "villages": rows})
    return {"rules": bt.get("rules"), "scenarios": scenarios}


def metrics(repo: Repo) -> dict[str, Any]:
    alerts = repo.list_alerts(limit=500)
    drills: list[tuple[Alert, list[Delivery]]] = []
    live: list[tuple[Alert, list[Delivery]]] = []
    for a in alerts:
        if views.is_replay(a):
            continue
        if views.is_drill(a):
            ds = _real(repo.list_deliveries(a.id))
            if ds:
                drills.append((a, ds))
        elif views.went_out(a):
            live.append((a, _real(repo.list_deliveries(a.id))))
    return {
        "counters": views.counters(repo),
        "drills": _group(drills),
        "live": _group(live),
        "backtest": backtest_lead_times(),
        "as_of": clock.iso(clock.now()),
    }
