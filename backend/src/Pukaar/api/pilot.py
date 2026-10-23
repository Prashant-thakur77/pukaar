"""GET /public/pilot-metrics: what has been measured so far, for the /pilot page.

Every number is counted from stored records or read from data/backtest.json; nothing is estimated.
A number with nothing behind it yet is null, and the page says "not measured yet".
No names, phone numbers or chat ids: deliveries are only counted and timed.

drills      hand-started test alerts (scripts/drill.py) that reached at least one real phone
live        live flood alerts that went out (views.went_out); never replays, never drills
  alerts                    alerts in the group
  delivered                 people the alerts reached, the demo stub channel included: the sum of the alerts'
                            delivered_count, the number /public/overview shows for each alert
  reached                   of them, people reached on a real phone (Telegram, or a call answered; the stub
                            channel for demo recipients is not a phone and is left out), each person once per
                            alert however many channels: the sum of the alerts' phones_reached_count
  demo_recipients           delivered - reached: the demo recipients without a phone
  acknowledged              of the people reached on a phone, how many pressed "मिल गया"
  ack_share                 acknowledged / reached, 0..1 (null when nothing was reached)
  median_minutes_first_ack  per alert: first send to the first acknowledgement; the median over alerts
  median_minutes_to_ack     per person: their send to their acknowledgement; the median over people
backtest    lead times from data/backtest.json (scripts/backtest.py), per scenario and village
false_alarms  "was this real?" (an officer's answer after a live alert closed), counted per rule that fired
  closed_alerts             live alerts the workflow has finished with (never replays, never drills)
  real_flood / no_flood / unknown / not_set   how many of them got each answer
  false_alarm_rate          no_flood / (real_flood + no_flood), 0..1 (null until one of the two is recorded)
  by_rule                   the same counts per rule family ("rain_24h", "discharge", "gauge", ...); an alert
                            counts once under each rule that fired for it. Rule names only: no ids, no people.
"""

from __future__ import annotations

import json
import re
from statistics import median
from typing import Any

from Pukaar.api import views
from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.store.models import ALERT_OUTCOMES, OPEN_ALERT_STATUSES, Alert, Delivery
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
    reached = acked = delivered = 0
    per_alert: list[float] = []
    per_person: list[float] = []
    for alert, ds in pairs:
        people = {d.recipient_id for d in ds}  # a "both" person counts once, as in phones_reached_count
        reached += len(people)
        delivered += max(alert.delivered_count, len(people))
        acks = [d for d in ds if d.acknowledged_at]
        acked += len({d.recipient_id for d in acks})
        if acks:
            first_sent = min(d.sent_at for d in ds if d.sent_at)
            first_ack = min(d.acknowledged_at for d in acks if d.acknowledged_at)
            m = _minutes(first_sent, first_ack)
            if m is not None:
                per_alert.append(m)
        per_person += [m for m in (_minutes(d.sent_at, d.acknowledged_at) for d in acks) if m is not None]
    return {
        "alerts": len(pairs),
        "delivered": delivered,
        "reached": reached,
        "demo_recipients": delivered - reached,
        "acknowledged": acked,
        "ack_share": round(acked / reached, 3) if reached else None,
        "median_minutes_first_ack": _median(per_alert),
        "median_minutes_to_ack": _median(per_person),
    }


_RULE_FAMILY = re.compile(r"[a-z][a-z0-9_]*")


def rule_family(rule: str) -> str | None:
    """"rain_24h>=115.6mm:warning" -> "rain_24h"; "auto_verified_capped:rpt_1" -> "auto_verified_capped"."""
    m = _RULE_FAMILY.match(str(rule).strip().lower())
    return m.group(0) if m and m.group(0) != "drill" else None


def _outcome_counts(alerts: list[Alert]) -> dict[str, Any]:
    out: dict[str, Any] = {k: 0 for k in (*ALERT_OUTCOMES, "not_set")}
    for a in alerts:
        out[a.outcome or "not_set"] += 1
    judged = out["real_flood"] + out["no_flood"]
    out["false_alarm_rate"] = round(out["no_flood"] / judged, 3) if judged else None
    return out


def false_alarms(alerts: list[Alert]) -> dict[str, Any]:
    """Counts of "was this real?" over closed live alerts, overall and per rule family."""
    closed = [a for a in alerts if not views.is_replay(a) and not views.is_drill(a)
              and a.status not in OPEN_ALERT_STATUSES]
    by_rule: dict[str, list[Alert]] = {}
    for a in closed:
        for fam in sorted({f for f in (rule_family(r) for r in a.decision_trace.get("rules_fired") or []) if f}):
            by_rule.setdefault(fam, []).append(a)
    return {
        "closed_alerts": len(closed),
        **_outcome_counts(closed),
        "by_rule": [{"rule": fam, "alerts": len(xs), **_outcome_counts(xs)} for fam, xs in sorted(by_rule.items())],
    }


def backtest_lead_times() -> dict[str, Any] | None:
    path = get_settings().data_dir / "backtest.json"
    try:
        bt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    scenarios = []
    for sc in bt.get("scenarios", []):
        # lead_hours: the alert (first Watch) to the river's peak day. get_ready_lead_hours: the get-ready
        # outlook (never an alert) to the same day. *_lower_bound: already on at the first archived hour.
        rows = [{"village_id": v.get("village_id"), "village": v.get("village"), "outcome": v.get("outcome"),
                 "lead_hours": v.get("lead_hours_watch_to_peak_day"),
                 "lead_is_lower_bound": bool(v.get("watch_from_first_hour")),
                 "get_ready_lead_hours": v.get("lead_hours_get_ready_to_peak_day"),
                 "get_ready_is_lower_bound": bool(v.get("get_ready_from_first_hour"))} for v in sc.get("villages", [])]
        leads = [r["lead_hours"] for r in rows if isinstance(r["lead_hours"], (int, float))]
        ready = [r["get_ready_lead_hours"] for r in rows if isinstance(r["get_ready_lead_hours"], (int, float))]
        scenarios.append({"name": sc.get("name"), "title": sc.get("title"), "title_hi": sc.get("title_hi"),
                          "villages_scored": len(rows), "villages_alerted": len(leads),
                          "median_lead_hours": _median(leads), "max_lead_hours": max(leads) if leads else None,
                          "villages_get_ready": len(ready), "median_get_ready_lead_hours": _median(ready),
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
        "counters": views.public_counters(repo)[0],
        "drills": _group(drills),
        "live": _group(live),
        "backtest": backtest_lead_times(),
        "false_alarms": false_alarms(alerts),
        "as_of": clock.iso(clock.now()),
    }
