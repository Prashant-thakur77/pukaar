"""The siren tier: signed commands to a village's siren nodes and pradhan boxes, and what came back.

Who sounds a siren (docs/hardware/ALARM.md, policy/base.cedar):
- an officer-approved Warning or Critical (or the flagged critical auto-send), from the approval
  workflow's SoundSirens step, which never blocks or fails delivery to people;
- the failsafe, under the same rule as its broadcast (critical, or already approved);
- an officer by hand (a Warning alone; a Critical needs a second, different officer within 120 s);
- the pradhan's box (key + 3 s hold), passed on to the village's other sirens by the cloud.
External CAP alerts never sound a siren. A replay commands only labelled simulators (a "-sim" device).
A drill plays the drill pattern D1 only, through test_siren.

Patterns: W1 Warning, C1 Critical, A1 all-clear, T1 test, D1 drill. Watch has no outdoor sound: the
pradhan's box only (its LED and chime). The Critical pattern needs machine evidence at Critical in the
decision trace (a confirmed gauge, the river, official data, or observed rain with a second source) or a
second officer; without either the alert sounds W1 at once (never silence) and asks a second officer.

Every command is signed per device (services/devices/protocol.py), written as CMD#<id>, put in the
device's named shadow "siren" (desired.cmd) and recorded as the alert's siren tier row
(ALERT#<id> / SIREN#<device>#<round>, idempotent on alert, device and round). The device reports
cmd_received, started and verified (current and microphone evidence) as events
(handlers/device_ingest.py). Siren rows are never people: they are not in delivered or acknowledged.

The check (check_unconfirmed): a command not verified PUKAAR_SIREN_CHECK_SECONDS (180 s) after it was
commanded is "not confirmed": SirenUnconfirmed is emitted (alarmed) for a real siren, the duty officer is
told on Telegram and Web Push (phone the pradhan; the console offers the signed SMS), and the alert's
timeline says so. The sweep runs it every 15 minutes and the workflow's Recall step runs it for its alert
(AckWaitSeconds after delivery) before re-issuing the command to the sirens that did not verify.

Rate limit: at most PUKAAR_SIREN_COMMANDS_PER_HOUR (6) sound commands per village per hour; the
re-issues of one alert count once. Every decision passes Cedar and is on the audit trail.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from boto3.dynamodb.conditions import Attr

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.core.log import get_logger, log, metric
from Pukaar.policy.guard import SYSTEM, Principal, authorize
from Pukaar.services import events
from Pukaar.services.devices import keys, protocol, registry, shadow
from Pukaar.services.devices.siren_model import PATTERN_DEFAULTS, is_verified
from Pukaar.store.models import (
    LEVELS,
    OPEN_ALERT_STATUSES,
    Alert,
    AuditRow,
    Device,
    Report,
    SirenCommand,
    SirenDelivery,
    SirenRequest,
    Village,
    level_rank,
)
from Pukaar.store.repo import ConflictError, Repo
from Pukaar.templates import hi

_LOG = get_logger("sirens")
IST = timezone(timedelta(hours=5, minutes=30))
CMD_LIFETIME_S = 1800  # exp = min(alert expiry, iat + 30 min); the cloud re-issues while the alert is active
REQUEST_SECONDS = 120
TEST_GAP_SECONDS = 600
BOX_PRESSES_PER_HOUR = 3
MANUAL_CAP_S = 600
PATTERN_FOR_LEVEL = {"warning": "W1", "critical": "C1"}
CLIP_NAME = {"W1": "warning", "C1": "critical", "A1": "allclear", "T1": "test", "D1": "drill"}
STARTED = {"started", "verified"}


@dataclass
class SoundResult:
    commanded: int = 0
    cmd_ids: list[str] = field(default_factory=list)
    devices: list[str] = field(default_factory=list)
    pattern: str | None = None
    reason: str | None = None
    skipped: list[dict[str, str]] = field(default_factory=list)
    request_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"commanded": self.commanded, "cmd_ids": self.cmd_ids, "devices": self.devices,
                "pattern": self.pattern, "reason": self.reason, "skipped": self.skipped,
                "request_id": self.request_id}


# -- helpers -------------------------------------------------------------------------------------
def hour_ist(now: datetime | None = None) -> int:
    return (now or clock.now()).astimezone(IST).hour


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def clip_for(village_id: str, pattern: str | None) -> str | None:
    """The clip id on the device's SD card (the catalog comes with scripts/siren_audio.py, slice M)."""
    if not pattern:
        return None
    name = CLIP_NAME.get(pattern, "test")
    return f"{village_id}.{name}.hi.v1" if pattern in {"W1", "C1", "A1", "D1"} else f"{name}.hi.v1"


def sirens_of(repo: Repo, village_id: str) -> list[Device]:
    return [d for d in repo.list_devices(village_id) if d.kind == "siren"]


def boxes_of(repo: Repo, village_id: str) -> list[Device]:
    return [d for d in repo.list_devices(village_id) if d.kind == "box"]


def machine_evidence_critical(trace: dict[str, Any] | None) -> bool:
    """A machine source at Critical in the decision trace: a confirmed gauge, the river, official data
    that raised the level, observed rain with a second machine source (two agree), or a gauge's
    edge-autonomous alarm (2 of 3 good readings at critical upstream)."""
    t = trace or {}
    if t.get("gauge_level") == "critical" or t.get("river_level") == "critical" or t.get("edge_autonomous"):
        return True
    rules = [str(r) for r in t.get("rules_fired") or []]
    if any(r.startswith("official:") and r.endswith(":critical") for r in rules):
        return True
    rain_obs = str(t.get("rain_obs_level") or "normal")
    others = [str(t.get(k) or "normal") for k in ("gauge_level", "river_level")]
    return (t.get("raw_level") == "critical" and level_rank(rain_obs) >= level_rank("watch")
            and "two_sources_agree:+1" in rules and any(level_rank(o) >= level_rank("watch") for o in others))


def _confirmed_request(repo: Repo, village_id: str, alert_id: str) -> SirenRequest | None:
    return next((r for r in repo.list_siren_requests(village_id, limit=20)
                 if r.alert_id == alert_id and r.status == "confirmed"), None)


def _rate_ok(repo: Repo, village_id: str, key: str, now: datetime) -> bool:
    """At most N sound commands per village per hour; one key (an alert, a request) counts once."""
    slot = now.strftime("%Y-%m-%dT%H")
    if not repo.claim_siren_rate(village_id, slot, key):
        return True  # a re-issue for the same alert or request
    return repo.bump_rate("siren", village_id, slot, ttl_seconds=7200) <= get_settings().siren_commands_per_village_per_hour


def _audit(repo: Repo, actor: str, role: str, action: str, resource: str, decision: str, reason: str) -> None:
    try:
        repo.append_audit(AuditRow(at=clock.iso(clock.now()), id=new_id("aud"), actor=actor, role=role, action=action,
                                   resource=resource, decision=decision, reason=reason[:500]))
    except Exception as exc:
        log(_LOG, "siren audit write failed", 40, error=str(exc)[:200])


def _timeline(repo: Repo, alert_id: str | None, step: str, detail: str) -> None:
    if not alert_id:
        return
    try:
        repo.add_timeline(alert_id, step, detail[:500])
    except Exception as exc:
        log(_LOG, "siren timeline write failed", 30, alert_id=alert_id, error=str(exc)[:200])


# -- issuing one command -----------------------------------------------------------------------------
def issue(repo: Repo, d: Device, *, action: str, pattern: str | None, level: str | None, src: str,
          alert_id: str | None = None, by: str = "system", round_no: int = 0, expires: datetime | None = None,
          cap_on_s: int | None = None, volume: int | None = None, now: datetime | None = None) -> SirenCommand:
    """Sign one command for one device, record it, and put it in the device's "siren" shadow.

    The command is stored before the shadow write; a shadow error marks it failed and is raised to the caller."""
    now = now or clock.now()
    params = dict(PATTERN_DEFAULTS.get(pattern or "", {"cycles": 0, "repeat_every_s": 0, "repeat_cycles": 0,
                                                       "cap_on_s": 0, "volume": 0}))
    if cap_on_s is not None:
        params["cap_on_s"] = cap_on_s
    if volume is not None:
        params["volume"] = volume
    iat = _epoch(now)
    exp = iat + CMD_LIFETIME_S
    if expires is not None:
        exp = max(iat + 60, min(exp, _epoch(expires)))
    cmd = SirenCommand(id=new_id("cmd"), device_id=d.device_id, village_id=d.village_id, action=action,  # type: ignore[arg-type]
                       pattern=pattern, clip=clip_for(d.village_id, pattern), clip_sha256_16=None, level=level,
                       alert_id=alert_id, iat=iat, exp=exp, ctr=repo.next_device_ctr(d.device_id), src=src,
                       kid=d.kid, round=round_no, by=by, simulated=d.simulated, commanded_at=clock.iso(now), **params)
    wire = wire_command(cmd)
    wire["sig"] = protocol.sign_command(keys.derive(d.device_id, d.kid), wire, d.device_id)
    repo.put_command(cmd)
    try:
        shadow.get_client(repo).update_desired(d.device_id, "siren", {"cmd": wire})
    except Exception as exc:
        repo.update_command(d.device_id, cmd.id, state="failed", reason=f"shadow: {type(exc).__name__}"[:200])
        raise
    _relay_via_boxes(repo, d, wire)
    try:
        repo.update_device(d.village_id, d.device_id, pending_cmd={
            "cmd_id": cmd.id, "pattern": pattern, "action": action, "at": cmd.commanded_at, "state": "commanded",
            "alert_id": alert_id, "by": by})
    except Exception as exc:
        log(_LOG, "pending command write failed", 30, device_id=d.device_id, error=str(exc)[:200])
    metric("SirenCommanded", 1, Action=action)
    return cmd


def wire_command(cmd: SirenCommand) -> dict[str, Any]:
    """The command as the device reads it (desired.cmd), before its signature is added."""
    return {"id": cmd.id, "action": cmd.action, "pattern": cmd.pattern, "clip": cmd.clip,
            "clip_sha256_16": cmd.clip_sha256_16, "level": cmd.level, "alert_id": cmd.alert_id,
            "cycles": cmd.cycles, "repeat_every_s": cmd.repeat_every_s, "repeat_cycles": cmd.repeat_cycles,
            "cap_on_s": cmd.cap_on_s, "volume": cmd.volume, "iat": cmd.iat, "exp": cmd.exp, "ctr": cmd.ctr,
            "src": cmd.src, "kid": cmd.kid}


def _relay_via_boxes(repo: Repo, d: Device, wire: dict[str, Any]) -> int:
    """The same command, in its compact LoRa form, for the village's pradhan boxes to forward to a siren
    that has lost its cell link (box shadow desired.relay_cmd.<siren>, protocol.relay_cmd). The inner
    signature is the siren's own: a box carries it but cannot make or change it. Sound and stop only: the
    compact form has no volume, so a silent test sent this way would play aloud. Never raises."""
    if d.lora_addr is None or wire.get("action") not in {"sound", "stop"}:
        return 0
    try:
        entry = protocol.relay_cmd(keys.derive(d.device_id, d.kid), wire, d.device_id, d.lora_addr)
    except Exception as exc:
        log(_LOG, "no compact form for the box relay", 30, device_id=d.device_id, error=str(exc)[:200])
        return 0
    n = 0
    for b in boxes_of(repo, d.village_id):
        try:
            shadow.get_client(repo).update_desired(b.device_id, "siren", {"relay_cmd": {d.device_id: entry}})
            n += 1
        except Exception as exc:
            log(_LOG, "box relay_cmd update failed", 30, device_id=b.device_id, error=str(exc)[:200])
    return n


def _box_update(repo: Repo, village_id: str, desired: dict[str, Any]) -> int:
    """The pradhan boxes' shadow: level LEDs, the indoor clip (a chime at Watch). Never raises."""
    n = 0
    for b in boxes_of(repo, village_id):
        try:
            shadow.get_client(repo).update_desired(b.device_id, "siren", desired)
            n += 1
        except Exception as exc:
            log(_LOG, "box shadow update failed", 30, device_id=b.device_id, error=str(exc)[:200])
    return n


# -- the approval workflow's SoundSirens step ----------------------------------------------------------
def plan(repo: Repo, alert: Alert) -> tuple[str | None, str, bool]:
    """(pattern, Cedar action, critical held back for a second officer)."""
    if alert.decision_trace.get("drill"):
        return "D1", "test_siren", False
    if alert.level == "warning":
        return "W1", "sound_siren", False
    if alert.level == "critical":
        if machine_evidence_critical(alert.decision_trace) or _confirmed_request(repo, alert.village_id, alert.id):
            return "C1", "sound_siren", False
        return "W1", "sound_siren", True
    return None, "sound_siren", False


def sound_for_alert(repo: Repo, alert: Alert, *, src: str = "approval", round_no: int = 0,
                    only_devices: set[str] | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Command every siren of the alert's village once for this round. Never raises: a siren problem must
    never stop the people's delivery (the state machine also catches anything and goes on to Deliver)."""
    try:
        return _sound_for_alert(repo, alert, src=src, round_no=round_no, only_devices=only_devices,
                                now=now or clock.now()).as_dict()
    except Exception as exc:
        log(_LOG, "sirens step failed", 40, alert_id=alert.id, error=str(exc)[:300])
        _timeline(repo, alert.id, "sirens", f"siren command failed: {type(exc).__name__}; people's delivery goes on")
        return {"commanded": 0, "error": type(exc).__name__}


def _sound_for_alert(repo: Repo, alert: Alert, *, src: str, round_no: int, only_devices: set[str] | None,
                     now: datetime) -> SoundResult:
    out = SoundResult()
    village = repo.get_village(alert.village_id)
    if alert.level == "watch":
        boxes = _box_update(repo, alert.village_id, {"level": "watch", "alert_id": alert.id, "clip": "chime"})
        out.reason = "watch_no_outdoor"
        _timeline(repo, alert.id, "sirens", f"Watch: no outdoor siren; {boxes} pradhan box(es) told (LED and chime)")
        return out
    if alert.level not in {"warning", "critical"}:
        out.reason = "level_normal"
        return out
    sirens = [d for d in sirens_of(repo, alert.village_id) if only_devices is None or d.device_id in only_devices]
    if not sirens:
        out.reason = "no_sirens"
        return out
    pattern, action, held = plan(repo, alert)
    out.pattern = pattern
    if round_no == 0 and not _rate_ok(repo, alert.village_id, alert.id, now):
        out.reason = "rate_limited"
        metric("SirenRateLimited", 1)
        _timeline(repo, alert.id, "sirens", f"not commanded: over {get_settings().siren_commands_per_village_per_hour} "
                                            "siren commands this hour for the village")
        return out
    from Pukaar.services import cap  # alert expiry

    drill = bool(alert.decision_trace.get("drill"))
    evidence = machine_evidence_critical(alert.decision_trace)
    second = pattern == "C1" and _confirmed_request(repo, alert.village_id, alert.id) is not None
    for d in sirens:
        ctx = {"level": alert.level, "approved": alert.approved, "all_officers_timed_out":
               alert.status == "auto_sent_unapproved", "critical_auto_send": get_settings().critical_auto_send,
               "pattern": pattern, "src": src, "drill": drill, "replay": alert.replay, "device_simulated": d.simulated,
               "machine_evidence_critical": evidence, "second_officer_distinct": second,
               "village_id": alert.village_id}
        decision = authorize(SYSTEM, action, "alert", alert.id, ctx, repo=repo)
        row = SirenDelivery(alert_id=alert.id, device_id=d.device_id, village_id=alert.village_id, round=round_no,
                            pattern=pattern, level=alert.level, src=src, commanded_at=clock.iso(now),
                            simulated=d.simulated)
        if not decision.allowed:
            row.status, row.error = "skipped", f"blocked: {decision.reason}"[:200]
            repo.put_siren_row(row)
            out.skipped.append({"device_id": d.device_id, "reason": decision.reason})
            continue
        if not repo.put_siren_row(row):
            continue  # this alert already commanded this device in this round (a retried step)
        try:
            cmd = issue(repo, d, action="test" if pattern == "D1" else "sound", pattern=pattern,
                        level="drill" if pattern == "D1" else alert.level, src="drill" if drill else src,
                        alert_id=alert.id, round_no=round_no, expires=cap.expires_at(alert), now=now)
        except Exception as exc:
            repo.update_siren_row(alert.id, d.device_id, round_no, status="failed",
                                  error=f"{type(exc).__name__}: {exc}"[:200])
            metric("SirenCommandFailed", 1)
            continue
        repo.update_siren_row(alert.id, d.device_id, round_no, cmd_id=cmd.id)
        out.commanded += 1
        out.cmd_ids.append(cmd.id)
        out.devices.append(d.device_id)
    _box_update(repo, alert.village_id, {"level": alert.level, "alert_id": alert.id,
                                         "clip": clip_for(alert.village_id, pattern)})
    note = None
    if held and round_no == 0 and village is not None:
        req = _request_for_alert(repo, alert, village, now)
        out.request_id, note = (req.id if req else None), "needs_second_officer"
    fields: dict[str, Any] = {"siren_pattern": pattern}
    if note:
        fields["siren_note"] = note
    repo.update_alert(alert.id, **fields)
    recount(repo, alert.id)
    names = hi.PATTERN_EN.get(pattern or "", pattern)
    detail = (f"round {round_no}: {out.commanded} of {len(sirens)} siren(s) commanded, pattern {pattern} ({names})"
              + (f"; skipped {len(out.skipped)}: {out.skipped[0]['reason']}" if out.skipped else "")
              + ("; Critical held back: no machine evidence at Critical, a second officer is asked (W1 meanwhile)"
                 if note else ""))
    _timeline(repo, alert.id, "sirens", detail)
    return out


def _request_for_alert(repo: Repo, alert: Alert, village: Village, now: datetime) -> SirenRequest | None:
    """A Critical alert without machine evidence: ask for a second officer (the approver is the first)."""
    first = (alert.decided_by or "system").split(" ")[0]
    req = SirenRequest(id=new_id("srq"), village_id=village.id, level="critical", alert_id=alert.id,
                       reason="Critical alert without machine evidence at Critical", requested_by=first,
                       requested_at=clock.iso(now), expires_at=clock.iso(now + timedelta(seconds=REQUEST_SECONDS)))
    try:
        repo.put_siren_request(req)
    except ConflictError:
        return None
    if not alert.replay:
        _tell_officers(repo, village, hi.siren_second_officer(
            village.name_hi, village.name, first, f"{get_settings().web_url}/console?siren_request={req.id}"),
            title=f"पुकार: दूसरे अधिकारी की पुष्टि · Second officer: {village.name}", kind="siren_request",
            url=f"{get_settings().web_url}/console?siren_request={req.id}", exclude={first})
    return req


def recount(repo: Repo, alert_id: str) -> Alert | None:
    """The alert's siren counters from its rows, by device (a re-issued round never counts twice)."""
    rows = repo.list_siren_rows(alert_id)
    commanded = {r.device_id for r in rows if r.status not in {"skipped", "failed"}}
    started = {r.device_id for r in rows if r.status in STARTED}
    verified = {r.device_id for r in rows if r.status == "verified"}
    first_started = min((r.started_at for r in rows if r.started_at), default=None)
    first_verified = min((r.verified_at for r in rows if r.verified_at), default=None)
    try:
        alert = repo.update_alert(alert_id, sirens_total=len(commanded), sirens_started=len(started),
                                  sirens_verified=len(verified), siren_first_started_at=first_started,
                                  siren_first_verified_at=first_verified)
    except ConflictError:
        return None
    events.counts_changed(alert)
    return alert


def tier(repo: Repo, alert: Alert) -> dict[str, Any]:
    """SirenTier for the console: the counters and every row (commanded -> started -> verified)."""
    rows = sorted(repo.list_siren_rows(alert.id), key=lambda r: (r.device_id, r.round))
    return {"total": alert.sirens_total, "started": alert.sirens_started, "verified": alert.sirens_verified,
            "pattern": alert.siren_pattern, "note": alert.siren_note,
            "rows": [r.model_dump(exclude={"alert_id", "village_id"}) for r in rows]}


# -- recall: check, then re-issue to the sirens that did not verify ---------------------------------
def recall(repo: Repo, alert: Alert, now: datetime | None = None) -> dict[str, Any]:
    now = now or clock.now()
    try:
        check_unconfirmed(repo, now, alert_id=alert.id)
        if alert.all_clear_at:
            return {"commanded": 0, "reason": "stood_down"}
        rows = repo.list_siren_rows(alert.id)
        if not rows:
            return {"commanded": 0, "reason": "no_sirens"}
        latest: dict[str, SirenDelivery] = {}
        for r in rows:
            if r.device_id not in latest or r.round > latest[r.device_id].round:
                latest[r.device_id] = r
        verified = {r.device_id for r in rows if r.status == "verified"}
        todo = {dev for dev, r in latest.items() if dev not in verified and r.status in {"commanded", "started",
                                                                                          "not_confirmed", "failed",
                                                                                          "rejected"}}
        if not todo:
            return {"commanded": 0, "reason": "all_verified"}
        next_round = max(r.round for r in rows) + 1
        return sound_for_alert(repo, repo.get_alert(alert.id) or alert, src="recall", round_no=next_round,
                               only_devices=todo, now=now)
    except Exception as exc:
        log(_LOG, "siren recall failed", 40, alert_id=alert.id, error=str(exc)[:300])
        return {"commanded": 0, "error": type(exc).__name__}


# -- the all-clear: A1 only on the sirens that started for this alert -------------------------------------
def all_clear(repo: Repo, alert: Alert, now: datetime | None = None) -> dict[str, Any]:
    now = now or clock.now()
    out = {"commanded": 0, "cmd_ids": []}
    try:
        rows = repo.list_siren_rows(alert.id)
        started = {r.device_id for r in rows if r.status in STARTED}
        if not started:
            if rows:
                _box_update(repo, alert.village_id, {"level": "normal", "alert_id": alert.id, "clip": None})
            return out
        for d in sirens_of(repo, alert.village_id):
            if d.device_id not in started:
                continue
            # Cedar's all_clear: a replay's all-clear goes to the stub only, and a labelled simulator is one.
            channel = "stub" if (alert.replay and d.simulated) else "siren"
            decision = authorize(SYSTEM, "all_clear", "alert", alert.id,
                                 {"replay": alert.replay, "channel": channel, "level": alert.level}, repo=repo)
            if not decision.allowed:
                continue
            try:
                cmd = issue(repo, d, action="sound", pattern="A1", level="all_clear", src="all_clear",
                            alert_id=alert.id, now=now)
            except Exception as exc:
                log(_LOG, "all-clear siren command failed", 40, device_id=d.device_id, error=str(exc)[:200])
                continue
            out["commanded"] += 1
            out["cmd_ids"].append(cmd.id)
        _box_update(repo, alert.village_id, {"level": "normal", "alert_id": alert.id,
                                             "clip": clip_for(alert.village_id, "A1")})
        _timeline(repo, alert.id, "sirens_all_clear",
                  f"all-clear pattern A1 ({hi.PATTERN_EN['A1']}) to {out['commanded']} siren(s) that started")
    except Exception as exc:
        log(_LOG, "siren all-clear failed", 40, alert_id=alert.id, error=str(exc)[:300])
    return out


# -- by hand: an officer or a pradhan in the console -----------------------------------------------------
def manual_sound(repo: Repo, village: Village, level: str, principal: Principal, *, reason: str = "",
                 second_officer: str | None = None, request_id: str | None = None,
                 now: datetime | None = None) -> SoundResult:
    """Sound every siren of the village at Warning (W1) or Critical (C1). Cedar decides first (and audits):
    an officer's Critical needs a distinct second officer. Raises PermissionError when refused."""
    now = now or clock.now()
    distinct = bool(second_officer and second_officer != principal.username)
    ctx = {"level": level, "village_id": village.id, "second_officer_distinct": distinct,
           "src": "officer_manual" if principal.role == "officer" else "pradhan_manual",
           "pattern": PATTERN_FOR_LEVEL.get(level, "")}
    decision = authorize(principal, "sound_siren", "village", village.id, ctx, repo=repo)
    if not decision.allowed:
        raise PermissionError(decision.reason)
    out = SoundResult(pattern=PATTERN_FOR_LEVEL[level])
    if not _rate_ok(repo, village.id, request_id or new_id("man"), now):
        out.reason = "rate_limited"
        return out
    by = principal.username + (f"+{second_officer}" if distinct else "")
    for d in sirens_of(repo, village.id):
        try:
            cmd = issue(repo, d, action="sound", pattern=out.pattern, level=level, src=ctx["src"], by=by, now=now)
        except Exception as exc:
            out.skipped.append({"device_id": d.device_id, "reason": type(exc).__name__})
            continue
        out.commanded += 1
        out.cmd_ids.append(cmd.id)
        out.devices.append(d.device_id)
    _audit(repo, principal.username, principal.role, "sound_siren_manual", f"village:{village.id}", "allow",
           f"{level} ({out.pattern}) to {out.commanded} siren(s): {reason or 'no reason given'}"
           + (f"; second officer {second_officer}" if distinct else ""))
    _tell_officers(repo, village, f"पुकार: {village.name_hi} में सायरन बजाया गया ({hi.LEVEL_HI[level]}), "
                                  f"{by} द्वारा · Pukaar: sirens sounded by hand in {village.name} "
                                  f"({hi.LEVEL_EN[level]}) by {by}.",
                   title=f"सायरन · Sirens: {village.name}", kind="siren_manual",
                   url=f"{get_settings().web_url}/console", exclude={principal.username})
    return out


def request_critical(repo: Repo, village: Village, principal: Principal, reason: str,
                     now: datetime | None = None) -> SirenRequest:
    """The first officer of the two-person rule for a hand-sounded Critical: open a 120 s request."""
    now = now or clock.now()
    req = SirenRequest(id=new_id("srq"), village_id=village.id, level="critical", reason=reason[:200],
                       requested_by=principal.username, requested_at=clock.iso(now),
                       expires_at=clock.iso(now + timedelta(seconds=REQUEST_SECONDS)))
    repo.put_siren_request(req)
    _audit(repo, principal.username, principal.role, "sound_siren_request", f"village:{village.id}", "allow",
           f"critical, needs a second officer within {REQUEST_SECONDS} s: {reason or 'no reason given'}")
    url = f"{get_settings().web_url}/console?siren_request={req.id}"
    _tell_officers(repo, village, hi.siren_second_officer(village.name_hi, village.name, principal.username, url),
                   title=f"पुकार: दूसरे अधिकारी की पुष्टि · Second officer: {village.name}", kind="siren_request",
                   url=url, exclude={principal.username})
    return req


class RequestError(Exception):
    def __init__(self, status: int, code: str, reason: str) -> None:
        super().__init__(reason)
        self.status, self.code, self.reason = status, code, reason


def confirm_request(repo: Repo, request_id: str, principal: Principal, now: datetime | None = None) -> SoundResult:
    """The second officer. Distinct from the first, before the request expires; then C1 sounds."""
    now = now or clock.now()
    req = repo.get_siren_request(request_id)
    if req is None:
        raise RequestError(404, "not_found", "No such siren request")
    if req.status != "open":
        raise RequestError(409, req.status, f"This request is already {req.status}")
    if now > clock.parse(req.expires_at):
        try:
            repo.update_siren_request(req.id, condition=Attr("status").eq("open"), status="expired")
        except ConflictError:
            pass
        raise RequestError(409, "expired", "The 120-second window for a second officer has passed")
    if principal.role != "officer" or principal.username == req.requested_by:
        _audit(repo, principal.username, principal.role, "sound_siren_confirm", f"sirenreq:{req.id}", "deny",
               "the second officer must be a different officer")
        raise RequestError(409, "same_officer", "The second officer must be a different officer")
    village = repo.get_village(req.village_id)
    if village is None:
        raise RequestError(404, "not_found", "Village not found")
    try:
        req = repo.update_siren_request(req.id, condition=Attr("status").eq("open"), status="confirmed",
                                        confirmed_by=principal.username, confirmed_at=clock.iso(now))
    except ConflictError:
        raise RequestError(409, "taken", "Another officer confirmed this request first") from None
    if req.alert_id:
        alert = repo.get_alert(req.alert_id)
        if alert is None or alert.status not in OPEN_ALERT_STATUSES | {"delivered", "auto_sent_unapproved"}:
            raise RequestError(409, "alert_closed", "The alert is no longer active")
        _audit(repo, principal.username, principal.role, "sound_siren_confirm", f"alert:{alert.id}", "allow",
               f"second officer for the Critical pattern (first: {req.requested_by})")
        rows = repo.list_siren_rows(alert.id)
        res = sound_for_alert(repo, alert, src="approval", round_no=max((r.round for r in rows), default=0) + 1,
                              now=now)
        return SoundResult(commanded=res.get("commanded", 0), cmd_ids=res.get("cmd_ids", []),
                           devices=res.get("devices", []), pattern=res.get("pattern"))
    first = Principal(req.requested_by, "officer")
    return manual_sound(repo, village, "critical", first, reason=req.reason, second_officer=principal.username,
                        request_id=req.id, now=now)


def stop(repo: Repo, village: Village, principal: Principal, *, reason: str = "", cmd_id: str | None = None,
         now: datetime | None = None) -> dict[str, Any]:
    """Stop the village's sirens (or the one command named). A pradhan may stop only what they started."""
    now = now or clock.now()
    sirens = sirens_of(repo, village.id)
    mine = any(_starter(d) == principal.username for d in sirens)
    decision = authorize(principal, "stop_siren", "village", village.id,
                         {"village_id": village.id, "started_by_self": mine}, repo=repo)
    if not decision.allowed:
        raise PermissionError(decision.reason)
    out: dict[str, Any] = {"stopped": 0, "cmd_ids": []}
    for d in sirens:
        pend = d.pending_cmd or {}
        if cmd_id and pend.get("cmd_id") != cmd_id:
            continue
        if principal.role == "pradhan" and _starter(d) != principal.username:
            continue
        try:
            cmd = issue(repo, d, action="stop", pattern=None, level=None, src="officer_manual", by=principal.username,
                        alert_id=pend.get("alert_id"), now=now)
        except Exception as exc:
            log(_LOG, "stop command failed", 40, device_id=d.device_id, error=str(exc)[:200])
            continue
        if pend.get("cmd_id"):
            try:
                repo.update_command(d.device_id, pend["cmd_id"], state="stopped", reason=f"stopped by {principal.username}")
            except ConflictError:
                pass
        out["stopped"] += 1
        out["cmd_ids"].append(cmd.id)
        _timeline(repo, pend.get("alert_id"), "siren_stopped", f"{d.device_id} stopped by {principal.username}: {reason}")
    _audit(repo, principal.username, principal.role, "stop_siren", f"village:{village.id}", "allow",
           f"{out['stopped']} siren(s): {reason or 'no reason given'}")
    return out


def _starter(d: Device) -> str:
    """Who started the device's current command ("officer1+officer2" -> officer1)."""
    return str((d.pending_cmd or {}).get("by") or "").split("+")[0]


def test(repo: Repo, d: Device, kind: str, principal: Principal | None = None, *, reason: str = "",
         now: datetime | None = None) -> SirenCommand:
    """A silent (into the dummy load, volume 0) or audible (T1 at 50 %) test. Cedar decides; one per
    TEST_GAP_SECONDS per device. Raises PermissionError or RequestError(429)."""
    now = now or clock.now()
    who = principal or SYSTEM
    village = repo.get_village(d.village_id)
    open_alert = bool(village and village.open_alert_id)
    decision = authorize(who, "test_siren", "device", d.device_id,
                         {"kind": kind, "hour_ist": hour_ist(now), "village_id": d.village_id,
                          "device_simulated": d.simulated, "village_alert_open": open_alert}, repo=repo)
    if not decision.allowed:
        raise PermissionError(decision.reason)
    slot = str(_epoch(now) // TEST_GAP_SECONDS)
    if repo.bump_rate("sirentest", d.device_id, slot, ttl_seconds=3600) > 1:
        raise RequestError(429, "too_soon", f"One test per {TEST_GAP_SECONDS // 60} minutes per siren")
    cmd = issue(repo, d, action="test", pattern="T1", level="test", src="officer_manual" if principal else "schedule",
                by=who.username, volume=0 if kind == "silent" else 50, now=now)
    _audit(repo, who.username, who.role, "test_siren", f"device:{d.device_id}", "allow",
           f"{kind} test {cmd.id}: {reason or 'no reason given'}")
    return cmd


def sms_fallback(repo: Repo, d: Device, cmd_id: str, principal: Principal, now: datetime | None = None) -> dict[str, Any]:
    """The signed SMS for a command, to send from the officer's own (allow-listed) phone. Audited."""
    now = now or clock.now()
    cmd = repo.get_command(d.device_id, cmd_id)
    if cmd is None:
        raise RequestError(404, "not_found", "No such command for this device")
    if cmd.action == "sound" and cmd.level not in protocol.SMS_LEVELS:
        raise RequestError(409, "not_sms", "This command has no SMS form")
    ctr = repo.next_device_ctr(d.device_id)
    exp = max(cmd.exp, _epoch(now) + 600)
    level = cmd.level if cmd.level in protocol.SMS_LEVELS else "warning"
    text = protocol.sms_text(keys.derive(d.device_id, d.kid), d.device_id, cmd.action, level, ctr, exp)
    _audit(repo, principal.username, principal.role, "siren_sms_fallback", f"device:{d.device_id}", "allow",
           f"signed SMS for {cmd.id} (ctr {ctr}); SIM number shown to the officer")
    number = d.sim_number or ""
    return {"text": text, "sim_number": number or None, "ctr": ctr, "exp": exp,
            "sms_uri": f"sms:{number}?body={quote(text)}" if number else f"sms:?body={quote(text)}"}


# -- telling officers ------------------------------------------------------------------------------------
def _tell_officers(repo: Repo, village: Village, text: str, *, title: str, kind: str, url: str,
                   exclude: set[str] = frozenset()) -> int:  # type: ignore[assignment]
    """Telegram and Web Push to the district's duty chain (or the village's fallback list). Never raises."""
    from Pukaar.delivery import telegram
    from Pukaar.services import officer_push, roster

    told = 0
    try:
        chain = [o for o in roster.chain_for(repo, village).chain if o not in exclude]
    except Exception:
        chain = [o for o in village.officers if o not in exclude]
    for officer in chain:
        got = False
        chat = repo.get_officer_chat(officer)
        if chat and telegram.configured():
            try:
                telegram.send_text(chat, text)
                got = True
            except Exception as exc:
                log(_LOG, "siren telegram to officer failed", 30, error=str(exc)[:200])
        try:
            payload = {"kind": kind, "title": title, "body": text.split("\n")[-1][:180], "tag": f"{kind}-{village.id}",
                       "renotify": True, "requireInteraction": True, "actions": [],
                       "data": {"url": url, "village_id": village.id}}
            if officer_push.send_to_user(repo, officer, payload, ttl=600, kind=kind).sent:
                got = True
        except Exception as exc:
            log(_LOG, "siren push to officer failed", 30, error=str(exc)[:200])
        told += int(got)
    return told


# -- the check: commanded, but not verified in time ----------------------------------------------------
def check_unconfirmed(repo: Repo, now: datetime | None = None, *, alert_id: str | None = None) -> list[str]:
    """Mark commands not verified siren_check_seconds after they were commanded as not_confirmed, emit
    SirenUnconfirmed for each real (non-simulated) siren, tell the duty officer, and put it on the alert's
    timeline. Returns the command ids. Never raises."""
    now = now or clock.now()
    wait = get_settings().siren_check_seconds
    out: list[str] = []
    try:
        devices = [d for d in repo.list_devices() if d.kind == "siren" and d.pending_cmd]
    except Exception as exc:
        log(_LOG, "siren check failed", 40, error=str(exc)[:200])
        return out
    for d in devices:
        pend = d.pending_cmd or {}
        if pend.get("state") not in {"commanded", "started"} or pend.get("action") == "stop":
            continue
        if alert_id is not None and pend.get("alert_id") != alert_id:
            continue
        if (now - clock.parse(str(pend["at"]))).total_seconds() < wait:
            continue
        try:
            _not_confirmed(repo, d, pend, now)
            out.append(str(pend["cmd_id"]))
        except Exception as exc:
            log(_LOG, "siren not-confirmed handling failed", 40, device_id=d.device_id, error=str(exc)[:200])
    return out


def _not_confirmed(repo: Repo, d: Device, pend: dict[str, Any], now: datetime) -> None:
    cmd_id = str(pend["cmd_id"])
    try:
        repo.update_device(d.village_id, d.device_id, condition=Attr("pending_cmd.cmd_id").eq(cmd_id),
                           pending_cmd={**pend, "state": "not_confirmed"})
    except ConflictError:
        return  # a newer command, or the device answered meanwhile
    cmd = repo.get_command(d.device_id, cmd_id)
    if cmd is not None:
        try:
            repo.update_command(d.device_id, cmd_id, condition=Attr("state").is_in(["commanded", "started"]),
                                state="not_confirmed", reason=f"not verified within {get_settings().siren_check_seconds} s")
        except ConflictError:
            pass
    alert_id = pend.get("alert_id")
    if alert_id and cmd is not None:
        try:
            repo.update_siren_row(alert_id, d.device_id, cmd.round, condition=Attr("status").is_in(["commanded", "started"]),
                                  status="not_confirmed", error="not verified in time")
        except ConflictError:
            pass
    alert = repo.get_alert(alert_id) if alert_id else None
    replay = bool(alert and alert.replay)
    if not d.simulated and not replay:
        metric("SirenUnconfirmed", 1)
    village = repo.get_village(d.village_id)
    told = 0
    if village is not None and not d.simulated and not replay:
        told = _tell_officers(repo, village, hi.siren_unconfirmed_officer(village.name_hi, village.name, d.device_id,
                                                                         sms_hint=True),
                              title=f"सायरन पुष्टि नहीं · Siren not confirmed: {village.name}", kind="siren_unconfirmed",
                              url=f"{get_settings().web_url}/console" + (f"?alert={alert_id}" if alert_id else ""))
    _timeline(repo, alert_id, "siren_not_confirmed",
              f"{d.device_id} did not confirm it sounded ({cmd_id}); " +
              ("simulated: no officer paged" if d.simulated or replay else
               f"duty officer told ({told}); phone the pradhan, or send the signed SMS from the console"))
    if alert_id:
        recount(repo, alert_id)


# -- what the devices report (handlers/device_ingest.py) ----------------------------------------------------
def on_event(repo: Repo, d: Device, ev: dict[str, Any], *, via: str = "cell", now: datetime | None = None,
             live: bool = True) -> dict[str, Any]:
    """Apply one device event to the command, the alert's siren tier, the registry and the alarms.
    live False (a backfilled event): recorded, but a manual or autonomous trigger is not acted on again."""
    now = now or clock.now()
    etype = str(ev.get("type"))
    at = str(ev.get("at") or clock.iso(now))
    cmd = repo.get_command(d.device_id, str(ev["cmd_id"])) if ev.get("cmd_id") else None
    if cmd is None and re.fullmatch(r"[0-9a-f]{12}", str(ev.get("cmd_id") or "")):
        # a command the siren took over LoRa (a box's relay_cmd) is named by its cmd_id48
        cmd = next((c for c in repo.list_commands(d.device_id, limit=20)
                    if protocol.cmd_id48(c.id).hex() == ev["cmd_id"]), None)
    meas = ev.get("meas") if isinstance(ev.get("meas"), dict) else None
    out: dict[str, Any] = {"type": etype, "cmd_id": cmd.id if cmd else None}
    if etype in {"cmd_received", "started"} and cmd:
        _started(repo, d, cmd, at, via)
    elif etype == "verified" and cmd:
        faults = list(d.faults) + [str(f) for f in ev.get("faults") or []]
        if is_verified(meas, amp_a_ref=d.amp_a_ref, spl_rise_min_db=d.spl_rise_min_db, faults=faults):
            _verified(repo, d, cmd, at, meas or {}, via)
            out["verified"] = True
        else:
            _started(repo, d, cmd, at, via)
            _note(repo, cmd, "the device said verified, but the measurements do not show the sound", meas)
            out["verified"] = False
    elif etype == "not_verified" and cmd:
        _started(repo, d, cmd, at, via)
        _note(repo, cmd, "not verified by the device (current or microphone)", meas)
    elif etype == "rejected" and cmd:
        reason = str(ev.get("reason") or "rejected")[:60]
        repo.update_command(d.device_id, cmd.id, state="rejected", reason=reason)
        if cmd.alert_id:
            _row(repo, cmd, status="rejected", error=f"rejected by the device: {reason}")
            _timeline(repo, cmd.alert_id, "siren_rejected", f"{d.device_id} refused {cmd.id}: {reason}")
        metric("DeviceRejected", 1, Reason=reason)
        _pending(repo, d, cmd, "rejected")
    elif etype in {"finished", "stopped"}:
        if cmd and cmd.state in {"commanded", "started", "verified"} and cmd.action != "stop":
            repo.update_command(d.device_id, cmd.id, state="finished" if etype == "finished" else "stopped")
        registry.touch(repo, d.village_id, d.device_id, at, via, state="idle", state_since=at)
    elif etype == "test_result":
        _test_result(repo, d, ev, cmd, at, meas)
    elif etype == "tamper":
        repo.update_device(d.village_id, d.device_id, tamper_at=at)
        metric("DeviceTamper", 1)
        _audit(repo, d.device_id, "device", "tamper", f"village:{d.village_id}", "allow", "door switch opened")
    elif etype == "fault" and isinstance(ev.get("faults"), list):
        repo.update_device(d.village_id, d.device_id, faults=[str(f)[:24] for f in ev["faults"]][:16])
    elif etype == "power":
        fields = {k: (meas or {}).get(k) for k in ("soc", "batt_mv") if (meas or {}).get(k) is not None}
        if fields:
            repo.update_device(d.village_id, d.device_id, **fields)
    elif etype == "manual_trigger":
        out["manual"] = pradhan_trigger(repo, d, ev, now=now, live=live)
    elif etype == "autonomous_trigger":
        out["autonomous"] = autonomous_trigger(repo, d, ev, now=now, live=live)
    elif etype == "report" and d.kind == "box":
        out["report"] = box_report(repo, d, ev, now=now, live=live)
    elif etype == "ack" and d.kind == "box":
        out["ack"] = box_ack(repo, d, ev, now=now)
    registry.touch(repo, d.village_id, d.device_id, at, via)
    return out


def _row(repo: Repo, cmd: SirenCommand, **fields: Any) -> None:
    if not cmd.alert_id:
        return
    try:
        repo.update_siren_row(cmd.alert_id, cmd.device_id, cmd.round, **fields)
    except ConflictError:
        pass


def _pending(repo: Repo, d: Device, cmd: SirenCommand, state: str) -> None:
    pend = d.pending_cmd or {}
    if pend.get("cmd_id") != cmd.id:
        return
    try:
        repo.update_device(d.village_id, d.device_id, condition=Attr("pending_cmd.cmd_id").eq(cmd.id),
                           pending_cmd={**pend, "state": state})
    except ConflictError:
        pass


def _note(repo: Repo, cmd: SirenCommand, text: str, meas: dict[str, Any] | None) -> None:
    repo.update_command(cmd.device_id, cmd.id, reason=text[:200], meas=meas)
    _row(repo, cmd, error=text[:200], meas=_short_meas(meas))


def _short_meas(meas: dict[str, Any] | None) -> dict[str, Any] | None:
    if not meas:
        return None
    return {k: meas[k] for k in ("amp_a", "spl_rise_db", "siren_a") if isinstance(meas.get(k), (int, float))}


def _started(repo: Repo, d: Device, cmd: SirenCommand, at: str, via: str) -> None:
    if cmd.state == "commanded":
        try:
            repo.update_command(d.device_id, cmd.id, condition=Attr("state").eq("commanded"), state="started",
                                started_at=at, via=via)
        except ConflictError:
            pass
    if cmd.alert_id:
        try:
            repo.update_siren_row(cmd.alert_id, d.device_id, cmd.round, condition=Attr("started_at").not_exists(),
                                  status="started", started_at=at)
            recount(repo, cmd.alert_id)
        except ConflictError:
            pass
    _pending(repo, d, cmd, "started")
    state = {"test": "testing", "stop": "idle"}.get(cmd.action, "sounding")
    if cmd.action == "sound" and cmd.pattern in {"W1", "C1", "A1", "D1"}:
        repo.update_device(d.village_id, d.device_id, state=state, state_since=at,
                           last_sound={"alert_id": cmd.alert_id, "at": at, "pattern": cmd.pattern, "verified": False})
    elif cmd.action == "test" and cmd.pattern == "D1":
        repo.update_device(d.village_id, d.device_id, state=state, state_since=at,
                           last_sound={"alert_id": cmd.alert_id, "at": at, "pattern": "D1", "verified": False})
    else:
        repo.update_device(d.village_id, d.device_id, state=state, state_since=at)


def _verified(repo: Repo, d: Device, cmd: SirenCommand, at: str, meas: dict[str, Any], via: str) -> None:
    _started(repo, d, repo.get_command(d.device_id, cmd.id) or cmd, at, via)
    try:
        repo.update_command(d.device_id, cmd.id, condition=Attr("verified_at").not_exists(), state="verified",
                            verified_at=at, meas=meas, via=via)
    except ConflictError:
        return  # already verified (a duplicate event)
    _pending(repo, d, cmd, "verified")
    short = _short_meas(meas)
    if cmd.alert_id:
        try:
            repo.update_siren_row(cmd.alert_id, d.device_id, cmd.round, condition=Attr("verified_at").not_exists(),
                                  status="verified", verified_at=at, meas=short, error=None)
        except ConflictError:
            pass
        recount(repo, cmd.alert_id)
        _timeline(repo, cmd.alert_id, "siren_verified",
                  f"{d.device_id}: " + hi.siren_verified_detail(meas.get("amp_a"), meas.get("spl_rise_db")))
    if cmd.action != "test" or cmd.pattern == "D1":
        repo.update_device(d.village_id, d.device_id, last_sound={"alert_id": cmd.alert_id, "at": at,
                                                                  "pattern": cmd.pattern, "verified": True})
    metric("SirenVerified", 1, Pattern=cmd.pattern or "-")


def _test_result(repo: Repo, d: Device, ev: dict[str, Any], cmd: SirenCommand | None, at: str,
                 meas: dict[str, Any] | None) -> None:
    kind = "audible" if ev.get("kind") == "audible" else "silent"
    ok = ev.get("ok") is True
    detail = str(ev.get("detail") or "")[:200]
    if kind == "audible" and ok and meas is not None:
        ok = is_verified(meas, amp_a_ref=d.amp_a_ref, spl_rise_min_db=d.spl_rise_min_db, faults=d.faults)
    record: dict[str, Any] = {"at": at, "ok": ok, "detail": detail}
    if kind == "audible":
        record.update(amp_a=(meas or {}).get("amp_a"), spl_rise_db=(meas or {}).get("spl_rise_db"))
    repo.update_device(d.village_id, d.device_id, **{f"last_test_{kind}": record})
    repo.put_device_test(d.device_id, at, {"kind": kind, "ok": ok, "detail": detail, "cmd_id": cmd.id if cmd else None,
                                           "meas": _short_meas(meas)})
    if cmd is not None:
        try:
            repo.update_command(d.device_id, cmd.id, state="verified" if ok else "not_confirmed", verified_at=at if ok else None,
                                meas=meas, reason=None if ok else f"test failed: {detail}"[:200])
        except ConflictError:
            pass
        _pending(repo, d, cmd, "verified" if ok else "not_confirmed")
    if not ok:
        metric("SirenTestFailed", 1, Kind=kind)
        log(_LOG, "siren test failed", 30, device_id=d.device_id, kind=kind, detail=detail)


# -- the pradhan's box and the gauge's edge autonomy ----------------------------------------------------
def pradhan_trigger(repo: Repo, box: Device, ev: dict[str, Any], *, now: datetime | None = None,
                    live: bool = True) -> dict[str, Any]:
    """A pradhan pressed the box key and held C for 3 s (or the siren's own key switch).

    Audited; the duty officers are told at once; a report (source pradhan_box, severity high,
    verified_auto) goes to the rules, which cap it at Warning; and unless the box got a LoRa ACK from the
    village's sirens, the cloud commands them (Cedar: own village only). At most 3 per hour per box."""
    now = now or clock.now()
    level = "critical" if str(ev.get("button", "")).endswith("critical") or ev.get("level") == "critical" else "warning"
    village = repo.get_village(box.village_id)
    out: dict[str, Any] = {"level": level, "commanded": 0, "report_id": None}
    if village is None:
        return out
    if not live:
        _audit(repo, box.device_id, "device", "manual_siren", f"village:{village.id}", "allow",
               f"{level} by the pradhan's box at {ev.get('at')} (reported late, from the device's buffer)")
        return out
    slot = now.strftime("%Y-%m-%dT%H")
    if repo.bump_rate("box", box.device_id, slot, ttl_seconds=7200) > BOX_PRESSES_PER_HOUR:
        _audit(repo, box.device_id, "device", "manual_siren", f"village:{village.id}", "deny",
               f"over {BOX_PRESSES_PER_HOUR} manual triggers this hour")
        out["reason"] = "rate_limited"
        return out
    _audit(repo, box.device_id, "device", "manual_siren", f"village:{village.id}", "allow",
           f"{level} by the pradhan's box (key and 3 s hold)")
    at_ist = clock.parse(str(ev.get("at") or clock.iso(now))).astimezone(IST).strftime("%H:%M")
    out["officers_told"] = _tell_officers(repo, village, hi.siren_manual_officer(village.name_hi, village.name, at_ist,
                                                                               level),
                                          title=f"प्रधान ने सायरन बजाया · Pradhan siren: {village.name}",
                                          kind="siren_manual", url=f"{get_settings().web_url}/console")
    report = Report(id=new_id("rep"), village_id=village.id, created_at=clock.iso(now),
                    text=hi.siren_report_text(village.name_hi, level), report_type="water_rising", severity="high",
                    summary_en=f"The pradhan sounded the village siren ({level}) from the box.",
                    state="verified_auto", parser_source="pradhan_box", flags=["pradhan_box"],
                    verified_by=f"device:{box.device_id}")
    repo.put_report(report)
    out["report_id"] = report.id
    if not ev.get("lora_acked"):
        for d in sirens_of(repo, village.id):
            decision = authorize(SYSTEM, "sound_siren", "village", village.id,
                                 {"src": "pradhan_box", "village_id": village.id, "device_village_id": box.village_id,
                                  "pattern": PATTERN_FOR_LEVEL[level], "level": level}, repo=repo)
            if not decision.allowed:
                continue
            try:
                issue(repo, d, action="sound", pattern=PATTERN_FOR_LEVEL[level], level=level, src="pradhan_box",
                      by=f"device:{box.device_id}", cap_on_s=MANUAL_CAP_S, now=now)
                out["commanded"] += 1
            except Exception as exc:
                log(_LOG, "pradhan siren propagation failed", 40, device_id=d.device_id, error=str(exc)[:200])
    try:  # the report may raise the village (capped at Warning: verified_auto)
        from Pukaar.services.decision_engine import recompute_village
        from Pukaar.workflow.client import get_workflow

        res = recompute_village(repo, village, now=now, workflow=get_workflow(), only_if_rising=True)
        out["alert_id"] = res.alert_id
    except Exception as exc:
        log(_LOG, "recompute after the pradhan trigger failed", 40, village_id=village.id, error=str(exc)[:200])
    return out


def box_report(repo: Repo, box: Device, ev: dict[str, Any], *, now: datetime | None = None,
               live: bool = True) -> dict[str, Any]:
    """Box button A ("पानी बढ़ रहा है"): the pradhan says the water is rising.

    A report (water_rising, severity medium, verified_auto: Watch on its own) goes to the rules, which may
    only raise the village. Audited; at most 3 per hour per box. A backfilled press is recorded and audited,
    never acted on late."""
    now = now or clock.now()
    village = repo.get_village(box.village_id)
    out: dict[str, Any] = {"report_id": None}
    if village is None:
        return out
    if not live:
        _audit(repo, box.device_id, "device", "box_report", f"village:{village.id}", "allow",
               f"water rising, pressed at {ev.get('at')} (reported late, from the device's buffer)")
        return out
    if repo.bump_rate("box_report", box.device_id, now.strftime("%Y-%m-%dT%H"), ttl_seconds=7200) > BOX_PRESSES_PER_HOUR:
        out["reason"] = "rate_limited"
        return out
    _audit(repo, box.device_id, "device", "box_report", f"village:{village.id}", "allow", "water rising (button A)")
    report = Report(id=new_id("rep"), village_id=village.id, created_at=clock.iso(now),
                    text=hi.box_water_rising_text(village.name_hi), report_type="water_rising", severity="medium",
                    summary_en="The pradhan pressed 'water rising' on the box.", state="verified_auto",
                    parser_source="pradhan_box", flags=["pradhan_box", "box_button"],
                    verified_by=f"device:{box.device_id}")
    repo.put_report(report)
    out["report_id"] = report.id
    if box.simulated:
        return out  # a labelled simulator never raises a village
    try:
        from Pukaar.services.decision_engine import recompute_village
        from Pukaar.workflow.client import get_workflow

        res = recompute_village(repo, village, now=now, workflow=get_workflow(), only_if_rising=True)
        out["alert_id"] = res.alert_id
    except Exception as exc:
        log(_LOG, "recompute after a box report failed", 40, village_id=village.id, error=str(exc)[:200])
    return out


def box_ack(repo: Repo, box: Device, ev: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Box button B ("मिल गया"): the pradhan acknowledges the alert the box shows (the event's alert_id, else the
    village's open alert). It acknowledges the pradhan's own delivery row (the box's owner_recipient_id), like a
    Telegram tap, which stops re-sends to them. Only an alert of the box's own village; idempotent."""
    from Pukaar.delivery import dispatch

    out: dict[str, Any] = {"alert_id": None, "acknowledged": False}
    if not box.owner_recipient_id:
        out["reason"] = "no_owner"
        return out
    village = repo.get_village(box.village_id)
    alert_id = str(ev.get("alert_id") or "") or (village.open_alert_id if village else None)
    alert = repo.get_alert(alert_id) if alert_id else None
    if alert is None or alert.village_id != box.village_id:
        out["reason"] = "no_alert"
        return out
    out["alert_id"] = alert.id
    for channel in ("", "voice"):
        if dispatch.acknowledge(repo, alert.id, box.owner_recipient_id, channel) is not None:
            out["acknowledged"] = True
            break
    if out["acknowledged"]:
        _audit(repo, box.device_id, "device", "box_ack", f"alert:{alert.id}", "allow",
               f"the pradhan pressed 'mil gaya' on the box at {ev.get('at')}")
        _timeline(repo, alert.id, "box_ack", f"the pradhan acknowledged on the box ({box.device_id})")
    else:
        out["reason"] = "already_or_not_sent"
    return out


def autonomous_trigger(repo: Repo, siren: Device, ev: dict[str, Any], *, now: datetime | None = None,
                       live: bool = True) -> dict[str, Any]:
    """The siren sounded on its own (an upstream gauge's signed GAUGE_ALARM and no cloud for 600 s).

    EdgeAutonomousSiren is emitted, and the cloud opens a Critical alert for an officer to confirm or stand
    down. No CAP goes out until an officer approves it (services/cap.is_published)."""
    now = now or clock.now()
    metric("EdgeAutonomousSiren", 1)
    village = repo.get_village(siren.village_id)
    out: dict[str, Any] = {"alert_id": None}
    _audit(repo, siren.device_id, "device", "autonomous_siren", f"village:{siren.village_id}", "allow",
           f"edge autonomy from {ev.get('frame_src') or 'an upstream gauge'} at {ev.get('at')}" + ("" if live else " (late)"))
    if village is None or not live:
        return out
    if village.open_alert_id:
        current = repo.get_alert(village.open_alert_id)
        if current is not None and current.status in OPEN_ALERT_STATUSES and current.level == "critical":
            _timeline(repo, current.id, "edge_autonomous", f"{siren.device_id} sounded on its own (edge autonomy)")
            out["alert_id"] = current.id
            return out
    stamp = clock.iso(now)
    trace = {"schema": "edge-autonomous", "village_id": village.id, "previous_level": village.level,
             "raw_level": "critical", "level": "critical", "rules_fired": [f"edge_autonomous:{ev.get('frame_src') or '?'}"],
             "edge_autonomous": {"siren": siren.device_id, "gauge": ev.get("frame_src"), "at": ev.get("at"),
                                 "meas": ev.get("meas")},
             "evidence": [], "contradictions": [], "replay": False}
    alert = Alert(id=new_id("alr"), village_id=village.id, village_name=village.name, village_name_hi=village.name_hi,
                  level="critical", previous_level=village.level, status="drafting", created_at=stamp, updated_at=stamp,
                  decision_trace=trace, siren_note="edge_autonomous")
    repo.put_alert(alert)
    repo.update_village(village.id, open_alert_id=alert.id, last_alert_id=alert.id)
    repo.add_timeline(alert.id, "created", f"edge autonomy: {siren.device_id} sounded C1 on its own after a signed "
                                           f"gauge alarm from {ev.get('frame_src') or '?'}; confirm or stand down")
    events.alert_changed(alert)
    out["alert_id"] = alert.id
    try:
        from Pukaar.services.decision_engine import start_workflow
        from Pukaar.workflow.client import get_workflow

        start_workflow(repo, get_workflow(), alert)
    except Exception as exc:
        log(_LOG, "workflow start for an autonomous siren failed", 40, alert_id=alert.id, error=str(exc)[:200])
    return out


# -- the sweep: health of every siren and box ------------------------------------------------------------
def health_scan(repo: Repo, now: datetime | None = None) -> dict[str, Any]:
    """SirenOffline (alarmed), SirenTestOverdue and SirenOfflineDuringAlert for installed, non-simulated
    sirens and boxes. Never raises."""
    now = now or clock.now()
    out: dict[str, Any] = {"offline": [], "overdue": [], "offline_during_alert": []}
    try:
        devices = [d for d in repo.list_devices() if d.kind in registry.SOUNDERS]
        open_levels: dict[str, str] = {}
        for a in repo.open_alerts():
            if not a.replay:
                open_levels[a.village_id] = max(open_levels.get(a.village_id, "normal"), a.level, key=level_rank)
        for d in devices:
            state, _ = registry.health(d, now)
            counted = d.installed and not d.simulated
            if state == "offline" and counted:
                out["offline"].append(d.device_id)
                if level_rank(open_levels.get(d.village_id, "normal")) >= level_rank("warning"):
                    out["offline_during_alert"].append(d.device_id)
            if counted and registry.test_overdue(d, now):
                out["overdue"].append(d.device_id)
        metric("SirenOffline", len(out["offline"]))
        metric("SirenTestOverdue", len(out["overdue"]))
        if out["offline_during_alert"]:
            metric("SirenOfflineDuringAlert", len(out["offline_during_alert"]))
        for dev in out["offline"]:
            log(_LOG, "siren_offline", 30, device_id=dev)
    except Exception as exc:
        log(_LOG, "siren health scan failed", 40, error=str(exc)[:200])
    return out


def cmd_hash(cmd_id: str) -> str:
    """cmd_id48 as hex, the name a LoRa event gives a command."""
    return hashlib.sha256(cmd_id.encode("ascii")).digest()[:6].hex()


__all__ = ["LEVELS", "SoundResult", "sound_for_alert", "recall", "all_clear", "manual_sound", "request_critical",
           "confirm_request", "stop", "test", "sms_fallback", "check_unconfirmed", "on_event", "health_scan", "tier"]
