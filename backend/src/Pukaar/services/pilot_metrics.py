"""The ten pilot metrics (docs/PILOT_PROTOCOL.md section 3), per alert and pooled, from stored records only.

Nobody else publishes confirmed reach, the time from first signal to first call, or proof that a siren sounded; these
are the numbers Pukaar exists to measure. Every value is counted from stored rows; a value with nothing behind it is
None ("not measured"), never 0 and never estimated. Replays, drills and live alerts are kept apart: a replay reaches
only the demo stub, a drill is a labelled test to real phones, and only live alerts can have an outcome.

  1 coverage            registered phones (people on a real phone, not officers or demo stubs) / the village's
                        household list (Village.households, from the pradhan; None until received), and per 1,000
                        people where the population is known
  2 confirmed reach     of the people an alert targeted on a real phone, the share who pressed "मिल गया" (or 1)
                        within 15, 30 and 60 minutes of the alert's first send
  3 assisted reach      the same for assisted households, and how many their named neighbour checked on
  4 time chain          first signal -> rule (alert made) -> officer asked -> approved -> first delivery -> first
                        confirmation, minutes between each
  5 lead time achieved  minutes from the first delivery (and the first confirmation) to when harm began, where an
                        officer recorded a real flood and its onset
  6 hit / false alarm   the officer's "was this real?"; the hit rate needs the DDMA's list of floods, misses
                        included, so it stays None until that ground truth exists
  7 siren proof         sirens verified (current and microphone) / commanded
  8 data health         the forecast data status at alert time, stale minutes, the gauge (fresh, silent, none) and
                        any "unknown" or "carried forward" rule; and forecast checks made / expected, last 24 h
  9 protective action   the "are you safe?" roll-call after the alert: asked, safe, need help (an answer, not
                        proof of a move; the protocol's phone survey is the measure, and is not built)
 10 readiness           the pilot checklist (data/pilot_readiness.json) and the village's observers and gaps

The public route (/public/pilot-metrics, key "ten") gets the pooled numbers only: no alert ids, names or numbers.
The console gets one alert's metrics (GET /alerts/{id}/metrics).
"""

from __future__ import annotations

import json
from statistics import median
from typing import Any

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.store.models import RELAY_ROLES, Alert, Delivery
from Pukaar.store.repo import Repo

WINDOWS = (15, 30, 60)
REACHED = {"sent", "acknowledged"}
CHAIN = ("first_signal", "rule", "asked", "approved", "first_delivery", "first_ack")
SIGNAL_KINDS = {"reading", "gauge", "rain_obs", "staff_gauge", "report", "official", "gauge_silent"}


def kind_of(a: Alert) -> str:
    if a.decision_trace.get("demo"):  # the live jury demo: shown on its presenter screen only, never pooled
        return "demo"
    if a.replay or a.decision_trace.get("replay"):
        return "replay"
    return "drill" if a.decision_trace.get("drill") else "live"


def _minutes(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    m = (clock.parse(end) - clock.parse(start)).total_seconds() / 60
    return round(m, 1)


def _share(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


def _med(xs: list[float]) -> float | None:
    return round(median(xs), 1) if xs else None


# -- 10. the pilot checklist ------------------------------------------------------------------------
def readiness_items() -> dict[str, Any]:
    """data/pilot_readiness.json: items done, in progress and not started (the /pilot checklist)."""
    path = get_settings().data_dir / "pilot_readiness.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"items": 0, "done": None, "in_progress": None, "not_started": None, "updated": None}
    items = doc.get("items") or []
    count = {s: sum(1 for i in items if i.get("status") == s) for s in ("done", "in_progress", "not_started")}
    return {"items": len(items), **count, "updated": doc.get("updated")}


# -- 1. coverage --------------------------------------------------------------------------------------
def coverage(repo: Repo, village_id: str) -> dict[str, Any]:
    v = repo.get_village(village_id)
    phones = [r for r in repo.list_recipients(village_id) if r.channel != "stub" and r.role != "officer"]
    households = v.households if v else None
    population = v.population if v else None
    return {"registered": len(phones), "households": households,
            "share": round(min(1.0, len(phones) / households), 3) if households else None,
            "per_1000_people": round(len(phones) * 1000 / population, 1) if population else None,
            "observers": sum(1 for r in phones if r.role in RELAY_ROLES)}


# -- per alert ----------------------------------------------------------------------------------------
def _first_signal(trace: dict[str, Any], created_at: str) -> str | None:
    """The earliest time on the evidence that fired (a reading, gauge, observed rain, report...), never after the
    alert was made."""
    times = []
    for e in trace.get("evidence") or []:
        if isinstance(e, dict) and e.get("kind") in SIGNAL_KINDS and isinstance(e.get("at"), str):
            try:
                t = clock.iso(clock.parse(e["at"]))
            except ValueError:
                continue
            if t <= created_at:
                times.append(t)
    return min(times) if times else None


def _person_rows(rows: list[Delivery]) -> dict[str, list[Delivery]]:
    out: dict[str, list[Delivery]] = {}
    for d in rows:
        out.setdefault(d.recipient_id, []).append(d)
    return out


def _reach(people: dict[str, list[Delivery]], first_send: str | None) -> dict[str, Any]:
    targeted = len(people)
    acks = {pid: min(d.acknowledged_at for d in ds if d.acknowledged_at)
            for pid, ds in people.items() if any(d.acknowledged_at for d in ds)}
    within = {}
    for m in WINDOWS:
        n = sum(1 for t in acks.values() if first_send and (_minutes(first_send, t) or 0) <= m)
        within[f"within_{m}"] = n
        within[f"share_{m}"] = _share(n, targeted) if first_send else None
    reached = sum(1 for ds in people.values() if any(d.status in REACHED or d.acknowledged_at for d in ds))
    return {"targeted": targeted, "reached": reached, "confirmed": len(acks),
            "confirmed_share": _share(len(acks), targeted), **within}


class _Village:
    """Per-village reads made once however many alerts a village has (coverage, recipients, care, roll-calls)."""

    def __init__(self, repo: Repo) -> None:
        self.repo, self._c = repo, {}

    def get(self, village_id: str) -> dict[str, Any]:
        if village_id not in self._c:
            from Pukaar.services import assisted

            self._c[village_id] = {
                "coverage": coverage(self.repo, village_id),
                "recipients": {r.id: r for r in self.repo.list_recipients(village_id)},
                "care": assisted.village_care(self.repo, village_id),
                "village": self.repo.get_village(village_id),
                "rollcalls": self.repo.list_rollcalls(village_id, limit=50),
            }
        return self._c[village_id]


def alert_metrics(repo: Repo, a: Alert, *, rows: list[Delivery] | None = None,
                  checklist: dict[str, Any] | None = None, cache: _Village | None = None) -> dict[str, Any]:
    """The ten metrics for one alert. Personal data stays out: counts and times only."""
    vc = (cache or _Village(repo)).get(a.village_id)
    rows = rows if rows is not None else repo.list_deliveries(a.id)
    phones = [d for d in rows if d.channel != "stub"]
    stubs = [d for d in rows if d.channel == "stub"]
    sent = [d.sent_at for d in phones if d.sent_at]
    first_send = min(sent) if sent else None
    first_stub = min((d.sent_at for d in stubs if d.sent_at), default=None)
    people = _person_rows(phones)
    reach = _reach(people, first_send)

    recipients = vc["recipients"]
    assisted_people = {pid: ds for pid, ds in people.items() if recipients.get(pid) and recipients[pid].assisted}
    a_reach = _reach(assisted_people, first_send)
    escalated = sum(1 for ds in assisted_people.values() if any(d.escalated_at for d in ds))
    checked = sum(1 for ds in assisted_people.values() if any(d.checked_at for d in ds))
    looked_after = sum(1 for ds in assisted_people.values() if any(d.acknowledged_at or d.checked_at for d in ds))

    timeline = repo.list_timeline(a.id)
    asked = next((t.at for t in timeline if t.step == "asked_officer"), None)
    approved = a.decided_at if a.approved else None
    acks = [d.acknowledged_at for d in phones if d.acknowledged_at]
    first_ack = min(acks) if acks else None
    first_delivery = first_send or (first_stub if kind_of(a) == "replay" else None)
    # A replay's evidence is stamped in the scenario's own time (July 2023): its chain starts at the rule.
    signal = None if kind_of(a) == "replay" else _first_signal(a.decision_trace, a.created_at)
    times = {"first_signal": signal, "rule": a.created_at, "asked": asked,
             "approved": approved, "first_delivery": first_delivery, "first_ack": first_ack}
    steps = {f"{x}_to_{y}": _minutes(times[x], times[y]) for x, y in zip(CHAIN, CHAIN[1:])}
    steps["signal_to_first_delivery"] = _minutes(times["first_signal"] or times["rule"], first_delivery)
    steps["signal_to_first_ack"] = _minutes(times["first_signal"] or times["rule"], first_ack)

    onset = a.outcome_onset_at if a.outcome == "real_flood" else None
    lead = {"onset_at": onset, "from_first_delivery": _minutes(first_delivery, onset) if onset else None,
            "from_first_ack": _minutes(first_ack, onset) if onset else None}

    data = a.decision_trace.get("data") or {}
    rules = [str(r) for r in a.decision_trace.get("rules_fired") or []]
    gauge_ev = next((e for e in a.decision_trace.get("evidence") or [] if isinstance(e, dict)
                     and e.get("kind") == "gauge"), None)
    silent = any(r.startswith("gauge_silent_in_rain") for r in rules) or any(
        isinstance(e, dict) and e.get("kind") == "gauge_silent" for e in a.decision_trace.get("evidence") or [])
    village = vc["village"]
    gauge_state = ("silent" if silent else "fresh" if gauge_ev else
                   "none" if village is None or village.gauge is None else "not_fresh")
    health = {"forecast": data.get("status") or ("ok" if kind_of(a) == "replay" else None),
              "stale_minutes": data.get("stale_minutes"), "gauge": gauge_state,
              "unknown": sorted({r for r in rules if r.endswith(("_unknown", "_carried_forward")) or r == "no_reading"})}

    rc = next((r for r in vc["rollcalls"] if r.alert_id == a.id), None)
    protective = ({"asked": rc.asked, "safe": rc.safe, "need_help": rc.need_help,
                   "answered_share": _share(rc.safe + rc.need_help, rc.asked), "exercise": rc.exercise}
                  if rc else None)

    care = vc["care"]
    return {
        "kind": kind_of(a), "level": a.level, "status": a.status, "created_at": a.created_at,
        "coverage": vc["coverage"] | {"targeted": a.recipients_count},
        "confirmed_reach": reach,
        "assisted_reach": {**a_reach, "escalated": escalated, "checked_by_neighbour": checked,
                           "confirmed_or_checked": looked_after,
                           "confirmed_or_checked_share": _share(looked_after, len(assisted_people))},
        "time_chain": {"at": times, "minutes": steps},
        "lead_time": lead,
        "outcome": {"outcome": a.outcome, "recorded_at": a.outcome_at},
        "siren": {"commanded": a.sirens_total, "started": a.sirens_started, "verified": a.sirens_verified,
                  "verified_share": _share(a.sirens_verified, a.sirens_total)},
        "data_health": health,
        "protective_action": protective,
        "readiness": {"checklist": checklist if checklist is not None else readiness_items(),
                      "observers": care["observers"], "observers_needed": care["observers_needed"],
                      "gaps": care["gaps"]},
        "followup": {"at": a.followup_at, "trigger": a.followup_trigger, "sent": a.followup_sent},
    }


# -- pooled, for the public page ------------------------------------------------------------------------
def _pool(ms: list[dict[str, Any]]) -> dict[str, Any]:
    def total(path: str, key: str) -> int:
        return sum(int(m[path].get(key) or 0) for m in ms if m.get(path))

    targeted = total("confirmed_reach", "targeted")
    reach = {"targeted": targeted, "confirmed": total("confirmed_reach", "confirmed"),
             **{f"share_{w}": _share(total("confirmed_reach", f"within_{w}"), targeted) if targeted else None
                for w in WINDOWS}}
    a_targeted = total("assisted_reach", "targeted")
    assisted_ = {"targeted": a_targeted, "confirmed": total("assisted_reach", "confirmed"),
                 "share_30": _share(total("assisted_reach", "within_30"), a_targeted) if a_targeted else None,
                 "checked_by_neighbour": total("assisted_reach", "checked_by_neighbour"),
                 "confirmed_or_checked_share": _share(total("assisted_reach", "confirmed_or_checked"), a_targeted)
                 if a_targeted else None}
    chain = {k: _med([m["time_chain"]["minutes"][k] for m in ms if m["time_chain"]["minutes"].get(k) is not None])
             for k in (ms[0]["time_chain"]["minutes"] if ms else {})}
    leads = [m["lead_time"]["from_first_delivery"] for m in ms if m["lead_time"]["from_first_delivery"] is not None]
    outcomes = {k: sum(1 for m in ms if m["outcome"]["outcome"] == k) for k in ("real_flood", "no_flood", "unknown")}
    judged = outcomes["real_flood"] + outcomes["no_flood"]
    commanded, verified = total("siren", "commanded"), total("siren", "verified")
    data_known = [m for m in ms if m["data_health"]["forecast"]]
    rcs = [m["protective_action"] for m in ms if m.get("protective_action")]
    asked = sum(r["asked"] for r in rcs)
    return {
        "alerts": len(ms),
        "confirmed_reach": reach,
        "assisted_reach": assisted_,
        "time_chain_median_minutes": chain,
        "lead_time": {"measured": len(leads), "median_minutes": _med(leads)},
        "outcomes": {**outcomes, "not_set": len(ms) - sum(outcomes.values()),
                     "false_alarm_rate": _share(outcomes["no_flood"], judged), "hit_rate": None},
        "siren": {"commanded": commanded, "verified": verified, "verified_share": _share(verified, commanded)},
        "data_health": {"alerts_with_data_ok": sum(1 for m in data_known if m["data_health"]["forecast"] == "ok"),
                        "alerts_with_status": len(data_known),
                        "alerts_with_gauge_silent": sum(1 for m in ms if m["data_health"]["gauge"] == "silent")},
        "protective_action": {"rollcalls": len(rcs), "asked": asked, "safe": sum(r["safe"] for r in rcs),
                              "need_help": sum(r["need_help"] for r in rcs),
                              "answered_share": _share(sum(r["safe"] + r["need_help"] for r in rcs), asked)},
    }


def ten(repo: Repo, alerts: list[Alert] | None = None, *, counters: dict[str, Any] | None = None) -> dict[str, Any]:
    """The pooled ten metrics: live, drill and replay alerts apart, plus coverage and readiness now."""
    alerts = alerts if alerts is not None else repo.list_alerts(limit=500)
    checklist = readiness_items()
    cache = _Village(repo)
    groups: dict[str, list[dict[str, Any]]] = {"live": [], "drill": [], "replay": []}
    for a in alerts:
        k = kind_of(a)
        if k not in groups:  # a live demo alert is never pooled with live alerts, drills or replays
            continue
        # An alert counts once it went out (a delivery row exists); a declined or expired one reached nobody.
        rows = repo.list_deliveries(a.id) if (a.delivered_count > 0 or a.approved
                                               or a.status in {"auto_sent_unapproved", "failsafe"}) else []
        if not rows:
            continue
        groups[k].append(alert_metrics(repo, a, rows=rows, checklist=checklist, cache=cache))
    villages = repo.list_villages()
    covs = [cache.get(v.id)["coverage"] for v in villages]
    with_list = [c for c in covs if c["households"]]
    cares = [cache.get(v.id)["care"] for v in villages]
    counters = counters or {}
    expected = len(villages) * 96
    checks = counters.get("forecast_checks_24h")
    return {
        "coverage": {"villages": len(villages), "villages_with_household_list": len(with_list),
                     "registered_phones": sum(c["registered"] for c in covs),
                     "households_listed": sum(c["households"] for c in with_list) if with_list else None,
                     "share": _share(sum(c["registered"] for c in with_list), sum(c["households"] for c in with_list))
                     if with_list else None},
        "readiness": {"checklist": checklist,
                      "villages_with_two_observers": sum(1 for c in cares if c["observers"] >= c["observers_needed"]),
                      "assisted_households": sum(c["assisted"] for c in cares),
                      "assisted_without_neighbour": sum(len(c["assisted_without_neighbour"]) for c in cares)},
        "data_health_now": {"forecast_checks_24h": checks, "expected_24h": expected,
                            "share": _share(int(checks), expected) if isinstance(checks, int) and expected else None},
        "live": _pool(groups["live"]),
        "drill": _pool(groups["drill"]),
        "replay": _pool(groups["replay"]),
        "as_of": clock.iso(clock.now()),
    }

