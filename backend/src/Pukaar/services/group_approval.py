"""Grouped approval for valley-wide events (the July 2023 replay raised 4 of 5 villages at once).

When several villages of one district wait for approval at once from the same cause, the officer reviews
them as one group: the evidence they share first, then each village's level and message. One hold-to-approve
decides them all: approve every one, or approve some and decline the rest.

Nothing is merged underneath. Each alert keeps its own Step Functions execution and task token, and each
decision goes through the same path as a single approval (workflow/client.decide: single use, late replies
refused), after its own Cedar check (approve or decline, with the district scope read from that alert's
village). So a group can never carry a village the officer may not act on: that village's row comes back
"denied" and the others go ahead. Each village gets its own audited decision; one more audit row
("group_decision") records the group as the officer saw it.

A group is: pending alerts of the same district and stream (live or replay), from the same main cause (the
driver at the highest level: rain, river, gauge, reports or official data), each created within
Settings.group_window_minutes of the first. A group has two or more villages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.store.models import Alert, AuditRow, level_rank
from Pukaar.store.repo import ConflictError, Repo

DRIVERS = ("rain", "river", "gauge", "reports", "official")
DRIVER_EN = {"rain": "rain (forecast or measured)", "river": "river forecast", "gauge": "river gauge",
             "reports": "verified reports", "official": "official data (IMD, CWC, SACHET)"}
DRIVER_HI = {"rain": "बारिश (पूर्वानुमान या मापी गई)", "river": "नदी का पूर्वानुमान", "gauge": "नदी का गेज",
             "reports": "पुष्ट रिपोर्टें", "official": "सरकारी आँकड़े (IMD, CWC, SACHET)"}


def drivers(a: Alert) -> dict[str, str]:
    """Each driver at watch or above, with its level, from the alert's decision trace."""
    t = a.decision_trace or {}

    def lvl(*keys: str) -> str:
        return max((str(t.get(k) or "normal") for k in keys), key=level_rank)

    out = {"rain": lvl("rain_level", "rain_obs_level"), "river": lvl("river_level"),
           "gauge": lvl("gauge_level", "staff_level"), "reports": lvl("report_level")}
    official = "normal"
    for rule in t.get("rules_fired") or []:
        r = str(rule)
        if r.startswith(("official:", "official_corroborates:")):
            official = max(official, r.rsplit(":", 1)[-1], key=level_rank)
    out["official"] = official
    return {k: v for k, v in out.items() if level_rank(v) >= level_rank("watch")}


def main_cause(a: Alert) -> str:
    d = drivers(a)
    if not d:
        return "other"
    return max(DRIVERS, key=lambda k: (level_rank(d.get(k, "normal")), -DRIVERS.index(k)))


def _stream(a: Alert) -> str:
    if a.decision_trace.get("drill"):
        return "drill"
    return "replay" if a.replay else "live"


def key_of(a: Alert) -> str:
    return f"{a.district or '-'}|{_stream(a)}|{main_cause(a)}"


@dataclass
class Group:
    key: str
    district: str
    stream: str
    cause: str
    alerts: list[Alert]

    @property
    def id(self) -> str:
        return f"{self.key}|{self.alerts[0].id}"

    def shared(self) -> dict[str, Any]:
        """What every village of the group has in common: the drivers and the official items of the first."""
        sets = [drivers(a) for a in self.alerts]
        common = [k for k in DRIVERS if all(k in s for s in sets)]
        rules = [set(map(str, a.decision_trace.get("rules_fired") or [])) for a in self.alerts]
        shared_rules = sorted(set.intersection(*rules)) if rules else []
        official: list[dict[str, Any]] = []
        for ev in self.alerts[0].decision_trace.get("evidence") or []:
            if ev.get("kind") == "official":
                official = [{k: i.get(k) for k in ("source", "name", "status", "level", "detail")}
                            for i in ev.get("items") or [] if i.get("status") == "ok"]
        levels: dict[str, int] = {}
        for a in self.alerts:
            levels[a.level] = levels.get(a.level, 0) + 1
        return {"drivers": common, "drivers_en": [DRIVER_EN[k] for k in common],
                "drivers_hi": [DRIVER_HI[k] for k in common], "rules": shared_rules[:12], "official": official,
                "levels": levels, "first_at": self.alerts[0].created_at, "last_at": self.alerts[-1].created_at}

    def view(self) -> dict[str, Any]:
        return {
            "id": self.id, "key": self.key, "district": self.district, "stream": self.stream,
            "replay": self.stream == "replay", "cause": self.cause, "cause_en": DRIVER_EN.get(self.cause, self.cause),
            "cause_hi": DRIVER_HI.get(self.cause, self.cause), "count": len(self.alerts), "shared": self.shared(),
            "villages": [{
                "alert_id": a.id, "village_id": a.village_id, "village_name": a.village_name,
                "village_name_hi": a.village_name_hi, "level": a.level, "previous_level": a.previous_level,
                "text_hi": a.text_hi, "text_en": a.text_en, "reason_en": a.reason_en, "created_at": a.created_at,
                "recipients_count": a.recipients_count, "drivers": drivers(a), "status": a.status,
            } for a in sorted(self.alerts, key=lambda x: (-level_rank(x.level), x.village_name))],
        }


def build_groups(alerts: Iterable[Alert], window_minutes: int | None = None) -> list[Group]:
    """Pending alerts into groups of two or more (see the module docstring), the biggest first."""
    window = 60 * (window_minutes if window_minutes is not None else get_settings().group_window_minutes)
    by_key: dict[str, list[Alert]] = {}
    for a in sorted((a for a in alerts if a.status == "pending"), key=lambda a: a.created_at):
        by_key.setdefault(key_of(a), []).append(a)
    groups: list[Group] = []
    for key, items in by_key.items():
        run: list[Alert] = []
        for a in items:
            if run and (clock.parse(a.created_at) - clock.parse(run[0].created_at)).total_seconds() > window:
                if len(run) >= 2:
                    groups.append(_group(key, run))
                run = []
            run.append(a)
        if len(run) >= 2:
            groups.append(_group(key, run))
    return sorted(groups, key=lambda g: (-len(g.alerts), g.alerts[0].created_at))


def _group(key: str, alerts: list[Alert]) -> Group:
    district, stream, cause = key.split("|", 2)
    return Group(key, district, stream, cause, list(alerts))


def groups_for(repo: Repo, district: str | None = None, village_ids: list[str] | None = None) -> list[Group]:
    alerts = repo.list_alerts(status="pending", district=district or None)
    if village_ids is not None:
        alerts = [a for a in alerts if a.village_id in village_ids]
    return build_groups(alerts)


class GroupError(ValueError):
    """The group decision cannot be taken as asked; the message says why."""


def decide_group(repo: Repo, workflow: Any, principal: Any, decisions: list[dict[str, str]], reason: str = "",
                 group_id: str = "") -> list[dict[str, Any]]:
    """decisions: [{"alert_id", "decision": "approved" | "declined"}], at most one per alert, one district.

    Each alert: its own Cedar check (approve or decline, district scope from its village), then
    workflow/client.decide with its own task token. Returns one result per alert: decided, denied, late,
    retry or missing. One "group_decision" audit row records the group."""
    from Pukaar.policy.guard import authorize
    from Pukaar.workflow.client import RetryLater, decide

    if not decisions:
        raise GroupError("no decisions")
    ids = [str(d.get("alert_id") or "") for d in decisions]
    if len(set(ids)) != len(ids) or not all(ids):
        raise GroupError("each alert at most once")
    if any(d.get("decision") not in ("approved", "declined") for d in decisions):
        raise GroupError("decision must be approved or declined")
    alerts = {i: repo.get_alert(i) for i in ids}
    districts = {a.district for a in alerts.values() if a is not None}
    if len(districts) > 1:
        raise GroupError("a group is one district")
    results: list[dict[str, Any]] = []
    for d in decisions:
        a = alerts[d["alert_id"]]
        decision = d["decision"]
        if a is None:
            results.append({"alert_id": d["alert_id"], "decision": decision, "outcome": "missing"})
            continue
        action = "approve" if decision == "approved" else "decline"
        verdict = authorize(principal, action, "alert", a.id,
                            {"village_id": a.village_id, "replay": a.replay, "level": a.level}, repo=repo)
        row = {"alert_id": a.id, "village_id": a.village_id, "village_name": a.village_name, "decision": decision}
        if not verdict.allowed:
            results.append({**row, "outcome": "denied", "reason": verdict.reason})
            continue
        try:
            decide(repo, workflow, a.id, decision, principal.username,
                   reason=(reason or "")[:200] + (" (group decision)" if reason else "group decision"))
            results.append({**row, "outcome": "decided"})
        except ConflictError as exc:
            results.append({**row, "outcome": "late", "reason": str(exc)[:200]})
        except RetryLater as exc:
            results.append({**row, "outcome": "retry", "reason": str(exc)[:200]})
    done = [r for r in results if r["outcome"] == "decided"]
    approved = sum(1 for r in done if r["decision"] == "approved")
    repo.append_audit(AuditRow(
        at=clock.iso(clock.now()), id=new_id("aud"), actor=principal.username, role=principal.role,
        action="group_decision", resource=f"group:{group_id or '-'}", decision="allow",
        reason=(f"{len(decisions)} villages in {next(iter(districts), '-')}: {approved} approved, "
                f"{len(done) - approved} declined, {len(results) - len(done)} not taken; "
                + ", ".join(f"{r.get('village_name', r['alert_id'])}={r['decision'][:-1]}:{r['outcome']}"
                            for r in results))[:900]))
    return results
