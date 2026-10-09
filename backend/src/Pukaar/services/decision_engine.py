"""The sweep: reading -> risk rules -> hysteresis -> alert -> approval workflow.

recompute_village() is called by the 15-minute sweep, by each new report and
by the replay. Code decides the level; the model is never consulted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Protocol

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.core.log import get_logger, log
from Pukaar.services import risk_rules
from Pukaar.services.nowcast import nowcast
from Pukaar.store.models import OPEN_ALERT_STATUSES, Alert, Reading, Village, level_rank
from Pukaar.store.repo import Repo

_LOG = get_logger("sweep")
SWEEP_MINUTES = 15


class WorkflowStarter(Protocol):
    def start(self, alert: Alert) -> str | None: ...


@dataclass
class SweepResult:
    village_id: str
    skipped: bool = False
    level: str = "normal"
    raw_level: str = "normal"
    rose: bool = False
    alert_id: str | None = None
    note: str = ""


def sweep_window(at: datetime, prefix: str = "live") -> str:
    slot = at.replace(minute=(at.minute // SWEEP_MINUTES) * SWEEP_MINUTES, second=0, microsecond=0)
    return f"{prefix}:{clock.iso(slot)}"


def _recent_reports(repo: Repo, village_id: str, now: datetime, include_replay: bool):
    out = []
    for r in repo.list_reports(village_id, limit=50):
        created = clock.parse(r.created_at)
        if created > now or now - created > timedelta(hours=risk_rules.REPORT_ZERO_WEIGHT_HOURS):
            continue
        if r.state in {"duplicate", "false"}:
            continue
        if r.replay and not include_replay:
            continue
        out.append((r, created))
    return out


def build_trace(village: Village, reading: Reading | None, assessment: risk_rules.Assessment,
                previous: str, new_level: str, calm: int, now: datetime) -> dict:
    return {
        "schema": risk_rules.RULES_VERSION,
        "generated_at": clock.iso(now),
        "village_id": village.id,
        "previous_level": previous,
        "raw_level": assessment.level,
        "level": new_level,
        "rain_level": assessment.rain_level,
        "river_level": assessment.river_level,
        "report_level": assessment.report_level,
        "rules_fired": assessment.rules_fired,
        "contradictions": assessment.contradictions,
        "data_disagrees": bool(assessment.contradictions),
        "hysteresis": {"calm_sweeps": calm, "needed_to_drop": risk_rules.HYSTERESIS_SWEEPS},
        "evidence": assessment.evidence,
        "forecast_snapshot": {
            "rain_24h_mm": reading.rain_24h_mm if reading else None,
            "discharge_forecast": reading.discharge_forecast if reading else [],
        },
        "nowcast": nowcast(reading, village.thresholds, new_level),
        "replay": bool(reading.replay) if reading else False,
    }


def _escalate(repo: Repo, alert: Alert, village: Village, new_level: str, trace: dict) -> None:
    """Raise an alert that is still awaiting approval instead of stacking a second one.

    The text becomes the fixed template for the new level (no model call in the
    sweep), and the officer sees the change in the timeline.
    """
    from Pukaar.store.models import DraftCheck
    from Pukaar.templates import hi
    from Pukaar.voice import polly

    text_hi, text_en = hi.fallback_alert(new_level, village.name_hi, village.name)
    # token_version moves on: a link for the old level can no longer approve the new text.
    repo.update_alert(alert.id, level=new_level, decision_trace=trace, text_hi=text_hi, text_en=text_en,
                      token_version=alert.token_version + 1,
                      reasoning_model="rule-fallback", audio_key=None,
                      reason_en=f"Escalated from {alert.level} before approval. Rules: {', '.join(trace['rules_fired'][:4])}.",
                      draft_check=DraftCheck(passed=False, reason="escalated before approval; fixed template for the new level"))
    audio_key = polly.synthesize_alert(alert.id, text_hi)
    if audio_key:
        repo.update_alert(alert.id, audio_key=audio_key)
    repo.add_timeline(alert.id, "escalated", f"{alert.level} -> {new_level} while awaiting approval")


def recompute_village(
    repo: Repo,
    village: Village,
    *,
    now: datetime | None = None,
    reading: Reading | None = None,
    fetch: Callable[[Village, datetime], Reading | None] | None = None,
    workflow: WorkflowStarter | None = None,
    window_prefix: str | None = None,
    replay: bool = False,
) -> SweepResult:
    """One evaluation for one village.

    window_prefix set: a scheduled sweep, deduplicated per 15-minute window.
    fetch set: a new reading is fetched and stored; otherwise the latest stored
    reading is reused (a new report triggered this).
    """
    now = now or clock.now()
    if window_prefix is not None and not repo.claim_sweep(village.id, sweep_window(now, window_prefix)):
        return SweepResult(village.id, skipped=True, level=village.level, note="window already swept")

    if reading is None and fetch is not None:
        reading = fetch(village, now)
        if reading is not None:
            repo.put_reading(reading)
    if reading is None:
        latest = repo.list_readings(village.id, limit=1)
        reading = latest[0] if latest and (latest[0].replay == replay) else None

    reports = _recent_reports(repo, village.id, now, include_replay=replay)
    assessment = risk_rules.assess(reading, village.thresholds, reports, now)
    previous = village.level
    new_level, calm, rose = risk_rules.apply_hysteresis(previous, village.calm_sweeps, assessment.level)
    trace = build_trace(village, reading, assessment, previous, new_level, calm, now)

    fields: dict = {"level": new_level, "calm_sweeps": calm}
    if new_level != previous:
        fields["level_since"] = clock.iso(now)
    village = repo.update_village(village.id, **fields)
    result = SweepResult(village.id, level=new_level, raw_level=assessment.level, rose=rose)
    log(_LOG, "village evaluated", village_id=village.id, previous=previous, raw=assessment.level,
        level=new_level, rose=rose, rules=assessment.rules_fired, replay=replay)

    if not rose or new_level == "normal":
        return result

    # Quiet rules: no new alert while an open one already covers this level; daily cap.
    if village.open_alert_id:
        open_alert = repo.get_alert(village.open_alert_id)
        if open_alert and open_alert.status in OPEN_ALERT_STATUSES:
            if level_rank(open_alert.level) >= level_rank(new_level):
                result.note = "open alert already covers this level"
                return result
            if open_alert.status in {"drafting", "pending"}:
                _escalate(repo, open_alert, village, new_level, trace)
                result.alert_id, result.note = open_alert.id, "escalated the alert awaiting approval"
                return result
    cap = get_settings().alerts_per_village_per_day
    if repo.alerts_on_day(village.id, clock.iso(now)[:10]) >= cap:
        result.note = f"daily cap of {cap} alerts reached"
        log(_LOG, "alert suppressed by daily cap", 30, village_id=village.id)
        return result

    stamp = clock.iso(clock.now())
    alert = Alert(
        id=new_id("alr"), village_id=village.id, village_name=village.name, village_name_hi=village.name_hi,
        level=new_level, previous_level=previous, status="drafting", created_at=stamp, updated_at=stamp,
        decision_trace=trace, replay=replay,
    )
    repo.put_alert(alert)
    repo.update_village(village.id, open_alert_id=alert.id)
    repo.add_timeline(alert.id, "created", f"level {previous} -> {new_level}; rules: {', '.join(assessment.rules_fired)}")
    result.alert_id = alert.id
    if workflow is not None:
        start_workflow(repo, workflow, alert)
    return result


def start_workflow(repo: Repo, workflow: WorkflowStarter, alert: Alert) -> bool:
    """Start the approval execution; on failure the next sweep retries (restart_stuck)."""
    try:
        arn = workflow.start(alert)
    except Exception as exc:
        if "ExecutionAlreadyExists" in type(exc).__name__ or "ExecutionAlreadyExists" in str(exc):
            return True
        log(_LOG, "workflow start failed; will retry next sweep", 40, alert_id=alert.id, error=str(exc)[:300])
        repo.add_timeline(alert.id, "start_failed", f"{type(exc).__name__}; retried by the next sweep")
        return False
    if arn:
        repo.update_alert(alert.id, execution_arn=arn)
    return True


def restart_stuck(repo: Repo, workflow: WorkflowStarter, now: datetime, min_age_seconds: int = 120) -> list[str]:
    """Alerts still drafting with no execution (start failed) get another start."""
    restarted = []
    for alert in repo.open_alerts():
        if alert.status != "drafting" or alert.execution_arn:
            continue
        if (now - clock.parse(alert.created_at)).total_seconds() < min_age_seconds:
            continue
        if start_workflow(repo, workflow, alert):
            restarted.append(alert.id)
    return restarted


def sweep_all(repo: Repo, *, now: datetime | None = None, fetch=None, workflow: WorkflowStarter | None = None) -> list[SweepResult]:
    from Pukaar.services.external_data import fetch_live

    now = now or clock.now()
    results = []
    from Pukaar.services.replay import is_running

    replay_active = is_running(repo)
    if workflow is not None:
        restart_stuck(repo, workflow, now)
    for village in repo.list_villages():
        if replay_active:
            # Live data is still recorded, but the replay owns the levels until reset.
            try:
                reading = (fetch or (lambda v, t: fetch_live(v, t)))(village, now)
                if reading is not None:
                    repo.put_reading(reading)
                results.append(SweepResult(village.id, skipped=True, level=village.level, note="replay active; reading stored only"))
            except Exception as exc:
                log(_LOG, "village fetch failed", 40, village_id=village.id, error=str(exc)[:300])
                results.append(SweepResult(village.id, skipped=True, note=f"error: {type(exc).__name__}"))
            continue
        try:
            results.append(recompute_village(repo, village, now=now, fetch=fetch or (lambda v, t: fetch_live(v, t)),
                                             workflow=workflow, window_prefix="live"))
        except Exception as exc:  # one bad village never stops the sweep
            log(_LOG, "village sweep failed", 40, village_id=village.id, error=str(exc)[:300])
            results.append(SweepResult(village.id, skipped=True, note=f"error: {type(exc).__name__}"))
    return results
