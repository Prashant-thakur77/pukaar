"""Villager reports: intake, processing, auto-verification.

Intake (API, fast): store media in S3, keyword-structure any text, save. A
report is never dropped: a failed transcription or structuring keeps the raw
audio and a flag. Processing (worker, slow): Transcribe, model structuring,
photo description, auto-verification, then recompute the village.

Auto-verification (code, never the model): a second report within 500 m and
30 minutes that agrees, AND the two are independent (services/report_guard.py):
a different device and session, not the same IP or network range, and both GPS
fixes plausible (inside the village radius, not 0,0, not the published village
point). A photo the model says agrees is flagged for the officer ("photo_agrees")
but no longer verifies a report on its own: one forged report with a stock photo
must not raise a public level. Only verified reports can raise a level.

Abuse: every report is counted per source (salted IP hash) and per village. One
over a limit is kept and held for an officer, never dropped (report_guard.py).

Screening: before any structuring, the words (typed text or transcript) go
through the guardrail (llm/guardrail.py). A held report is kept and shown to
officers, structured by keyword rules only (no model sees it), never
auto-verified and never used to corroborate another report.
"""

from __future__ import annotations

import math
from datetime import timedelta

from Pukaar.core import clock
from Pukaar.core.ids import new_id, track_code
from Pukaar.core.log import get_logger, log
from Pukaar.llm import guardrail
from Pukaar.llm.bedrock import BedrockLLM
from Pukaar.services import report_guard as guard
from Pukaar.services import storage
from Pukaar.services.report_structuring import structure
from Pukaar.store.models import AuditRow, Report, ReportScreen, ReportSource, StaffReading, Village
from Pukaar.store.repo import Repo
from Pukaar.voice import transcribe

_LOG = get_logger("reports")
VILLAGE_RADIUS_M = 5000
CORROBORATION_RADIUS_M = 500
CORROBORATION_MINUTES = 30
DUPLICATE_RADIUS_M = 25
DUPLICATE_MINUTES = 60
AUDIO_TYPES = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4", "audio/mpeg": "mp3", "audio/wav": "wav",
               "audio/x-wav": "wav", "audio/aac": "mp4", "video/webm": "webm"}
PHOTO_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _has_gps(r: Report) -> bool:
    return r.lat is not None and r.lon is not None


def inside_village(r: Report, v: Village) -> bool:
    return _has_gps(r) and distance_m(r.lat, r.lon, v.lat, v.lon) <= VILLAGE_RADIUS_M  # type: ignore[arg-type]


def find_duplicate(repo: Repo, r: Report) -> Report | None:
    if not _has_gps(r):
        return None
    created = clock.parse(r.created_at)
    for other in repo.list_reports(r.village_id, limit=50):
        if other.id == r.id or not _has_gps(other) or other.replay != r.replay:
            continue
        if abs((clock.parse(other.created_at) - created).total_seconds()) > DUPLICATE_MINUTES * 60:
            continue
        if other.report_type == r.report_type and distance_m(r.lat, r.lon, other.lat, other.lon) <= DUPLICATE_RADIUS_M:  # type: ignore[arg-type]
            return other
    return None


def _candidate(r: Report, other: Report, created) -> bool:
    """Same village window, type and replay flag; not a duplicate, false or held report."""
    if other.id == r.id or not _has_gps(other) or other.replay != r.replay:
        return False
    if other.state in {"duplicate", "false"} or "possible_duplicate" in other.flags or other.held:
        return False
    if abs((clock.parse(other.created_at) - created).total_seconds()) > CORROBORATION_MINUTES * 60:
        return False
    return other.report_type == r.report_type and other.report_type != "other"


def find_corroboration(repo: Repo, r: Report, village: Village) -> tuple[Report | None, list[str]]:
    """An independent partner for r, and why any nearby agreeing report was not one."""
    if not _has_gps(r):
        return None, []
    created = clock.parse(r.created_at)
    rejected: list[str] = []
    for other in repo.list_reports(r.village_id, limit=50):
        if not _candidate(r, other, created):
            continue
        d = distance_m(r.lat, r.lon, other.lat, other.lon)  # type: ignore[arg-type]
        if not (DUPLICATE_RADIUS_M < d <= CORROBORATION_RADIUS_M
                or (d <= DUPLICATE_RADIUS_M and other.reporter_name != r.reporter_name and r.reporter_name)):
            continue
        why = guard.not_independent(r, other) or guard.implausible_gps(other, village, VILLAGE_RADIUS_M)
        if why is None:
            return other, rejected
        if why not in rejected:
            rejected.append(why)
    return None, rejected


def corroborating(repo: Repo, r: Report) -> Report | None:
    village = repo.get_village(r.village_id)
    return find_corroboration(repo, r, village)[0] if village else None


def _drop_rejections(flags: list[str]) -> list[str]:
    return [f for f in flags if not f.startswith("corroboration_rejected:")]


def auto_verify(repo: Repo, r: Report, village: Village, photo_agrees: bool | None = None) -> list[Report]:
    """Returns the reports that became verified_auto (this one and/or its partner)."""
    if r.state != "unverified" or r.held:
        return []
    flags = list(r.flags)
    if photo_agrees and "photo_agrees" not in flags:
        flags.append("photo_agrees")  # shown to the officer; not enough to verify on its own
    gps_problem = guard.implausible_gps(r, village, VILLAGE_RADIUS_M)
    partner, rejected = (None, []) if gps_problem else find_corroboration(repo, r, village)
    tag = f"gps_implausible:{gps_problem}"
    if gps_problem and gps_problem not in {"no_gps", "outside_village"} and tag not in flags:
        flags.append(tag)
    flags += [f"corroboration_rejected:{why}" for why in rejected if f"corroboration_rejected:{why}" not in flags]
    if partner is None:
        if flags != r.flags:
            repo.update_report(r.id, flags=flags)
        return []
    changed = [repo.update_report(r.id, state="verified_auto", previous_state=r.state,
                                  verified_by=f"auto:corroborated-by:{partner.id}",
                                  flags=_drop_rejections(flags) + ["corroborated"]
                                  + (["verified_by_photo"] if photo_agrees else []))]
    if partner.state == "unverified":
        changed.append(repo.update_report(partner.id, state="verified_auto", previous_state=partner.state,
                                          verified_by=f"auto:corroborated-by:{r.id}",
                                          flags=_drop_rejections(partner.flags) + ["corroborated"]))
    return changed


def intake(repo: Repo, village: Village, *, text: str = "", audio: tuple[bytes, str] | None = None,
           photo: tuple[bytes, str] | None = None, lat: float | None = None, lon: float | None = None,
           reporter_name: str | None = None, offline_created: bool = False, replay: bool = False,
           staff_reading: StaffReading | None = None, source: ReportSource | None = None) -> Report:
    """Store a report. Never drops one: a report over a rate limit is kept and held for an officer."""
    rid = new_id("rpt")
    now = clock.now()
    flags: list[str] = []
    audio_key = photo_key = None
    if audio:
        ext = AUDIO_TYPES.get(audio[1].split(";")[0].strip(), "webm")
        audio_key = storage.put_bytes(f"audio/reports/{rid}.{ext}", audio[0], audio[1].split(";")[0])
    if photo:
        ext = PHOTO_TYPES.get(photo[1], "jpg")
        photo_key = storage.put_bytes(f"photos/{rid}.{ext}", photo[0], photo[1])
    if lat is None or lon is None:
        flags.append("no_gps")
    hold_reason = None
    if not replay:
        if source is None or not source.ip:
            flags.append(guard.FLAG_SOURCE_UNKNOWN)
        rate = guard.check_rate(repo, village.id, source or ReportSource())
        hold_reason = rate.hold_reason
        flags += rate.flags
    structured = structure(text, village.name, None, has_photo=photo is not None)
    needs_transcript = bool(audio_key) and not text.strip()
    report = Report(
        id=rid, village_id=village.id, created_at=clock.iso(now), text=text[:2000], transcript="",
        report_type=structured.report_type, severity=structured.severity, summary_en=structured.summary_en,
        reply_hi=structured.reply_hi, lat=lat, lon=lon, photo_key=photo_key, audio_key=audio_key,
        state="transcribing" if needs_transcript else "unverified", parser_source=structured.parser_source,
        flags=flags, track_code=track_code(), reporter_name=(reporter_name or None),
        offline_created=offline_created, replay=replay, staff_reading=staff_reading,
        source=source, hold_reason=hold_reason,
    )
    dup = find_duplicate(repo, report)
    if dup is not None:
        report.flags.append("possible_duplicate")
        report.flags.append(f"duplicate_of:{dup.id}")
    twin = _same_source_recent(repo, report)
    if twin is not None:
        # "Possible duplicate or flood of reports": the officer sees which earlier report shares a source.
        report.flags.append(guard.FLAG_SAME_SOURCE)
        report.flags.append(f"same_source_as:{twin.id}")
    repo.put_report(report)
    log(_LOG, "report received", report_id=rid, village_id=village.id, type=report.report_type,
        severity=report.severity, audio=bool(audio_key), photo=bool(photo_key), gps=lat is not None,
        held=hold_reason)
    return report


def _same_source_recent(repo: Repo, r: Report) -> Report | None:
    """The newest report in this village in the last hour from the same IP, network range or device."""
    if r.source is None:
        return None
    created = clock.parse(r.created_at)
    for other in repo.list_reports(r.village_id, limit=50):
        if other.id == r.id or other.replay != r.replay:
            continue
        if abs((clock.parse(other.created_at) - created).total_seconds()) > DUPLICATE_MINUTES * 60:
            continue
        if guard.same_source(r.source, other.source):
            return other
    return None


def process(repo: Repo, report_id: str, llm: BedrockLLM | None, *, workflow=None) -> Report:
    """Slow path: transcript, model structuring, photo description, verification, recompute."""
    from Pukaar.services.decision_engine import recompute_village

    r = repo.get_report(report_id)
    if r is None:
        raise KeyError(report_id)
    village = repo.get_village(r.village_id)
    if village is None:
        raise KeyError(r.village_id)
    fields: dict = {}
    text = r.text
    source = "text"
    # Over a rate limit: no transcription, model or photo description (a script must not run up the
    # bill). The officer listens to the audio and looks at the photo instead.
    rate_held = bool(r.hold_reason)
    if r.audio_key and not text.strip() and rate_held:
        fields["flags"] = r.flags + ["transcript_skipped_held"]
    elif r.audio_key and not text.strip():
        transcript = transcribe.transcribe_key(r.audio_key, f"pukaar-{r.id}")
        if transcript:
            fields["transcript"] = transcript
            text = transcript
            source = "transcript"
        else:
            fields["flags"] = r.flags + ["transcription_unavailable"]
    held = False
    if text.strip():
        # Screen first: nothing below (rules or model) acts on words the guardrail stopped.
        verdict = guardrail.screen(text, source)
        held = not verdict.allowed
        fields["screen"] = ReportScreen(allowed=verdict.allowed, action=verdict.action, reasons=verdict.reasons,
                                        engine=verdict.engine, at=clock.iso(clock.now()), field=source).model_dump()
        if verdict.masked_text:
            fields["masked_text"] = verdict.masked_text
            text = verdict.masked_text  # no phone number or e-mail reaches the model
        s = structure(text, village.name, None if (held or rate_held) else llm, has_photo=bool(r.photo_key))
        fields.update(report_type=s.report_type, severity=s.severity, summary_en=s.summary_en, reply_hi=s.reply_hi,
                      parser_source=s.parser_source)
        if held:
            _audit_hold(repo, r, verdict)
    photo_agrees = None
    if r.photo_key and llm is not None and not rate_held:
        try:
            data, ctype = storage.get_bytes(r.photo_key)
            fmt = "png" if "png" in ctype else ("webp" if "webp" in ctype else "jpeg")
            desc = llm.describe_image(data, fmt, fields.get("report_type", r.report_type))
            if desc is not None:
                fields["photo_description"] = desc.description_en
                photo_agrees = desc.agrees_with_type and desc.shows_flood_signs
        except Exception as exc:
            log(_LOG, "photo description failed", 30, report_id=r.id, error=str(exc)[:200])
    if r.state == "transcribing":
        fields.update(state="unverified", previous_state="transcribing")
    unwound = held and r.state == "verified_auto"
    if unwound:
        # A partner verified it before screening finished: undo that, and the partner's own.
        fields.update(state="unverified", previous_state="verified_auto", verified_by=None,
                      flags=[f for f in fields.get("flags", r.flags) if f != "corroborated"])
        _unwind_partner(repo, r)
    r = repo.update_report(r.id, **fields) if fields else r
    verified = auto_verify(repo, r, village, photo_agrees)
    if verified or unwound:
        recompute_village(repo, repo.get_village(village.id) or village, workflow=workflow, replay=r.replay)
    return repo.get_report(r.id) or r


def _audit_hold(repo: Repo, r: Report, verdict: guardrail.ScreenResult) -> None:
    try:
        repo.append_audit(AuditRow(
            at=clock.iso(clock.now()), id=new_id("aud"), actor=verdict.engine, role="guardrail",
            action="screen_report", resource=f"report:{r.id}", decision="deny",
            reason="held for review: " + ", ".join(verdict.reasons or ["guardrail"]),
        ))
    except Exception as exc:  # the report is kept either way
        log(_LOG, "screen audit write failed", 40, report_id=r.id, error=str(exc)[:200])


def _unwind_partner(repo: Repo, held: Report) -> None:
    for other in repo.list_reports(held.village_id, limit=50):
        if other.state == "verified_auto" and other.verified_by == f"auto:corroborated-by:{held.id}":
            repo.update_report(other.id, state="unverified", previous_state="verified_auto", verified_by=None,
                               flags=[f for f in other.flags if f != "corroborated"])


def track_steps(r: Report) -> list[dict]:
    verified = r.state in {"verified_auto", "verified", "reviewed", "actioned", "resolved"}
    acted = r.state in {"actioned", "resolved"}
    return [
        {"key": "received", "done": True, "at": r.created_at},
        {"key": "verified", "done": verified, "at": None},
        {"key": "acted_on", "done": acted, "at": r.acted_at},
    ]


def within_hours(r: Report, hours: int) -> bool:
    return clock.parse(r.created_at) >= clock.now() - timedelta(hours=hours)
