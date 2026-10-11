"""After-action report for one alert: what happened, when, who decided, who heard.

Officers have to write one after every event; Pukaar already holds every
timestamp. build() turns an alert's record (timeline, deliveries, audit rows,
roll-call) into three things:

- an e-mail-safe HTML page (tables and inline CSS only, Hindi and English,
  water-theme colours),
- a plain-text copy for mail clients that do not render HTML,
- a small JSON summary.

Privacy: no phone number, chat id or recipient id is ever written. People are
shown by first name only, raw delivery errors are left out (they can carry a
chat id), and any long run of digits in free text is masked.

The workflow's close step calls on_close(): it stores the report in the private
bucket (reports/after-action/<alert id>.html and .json) and, when PUKAAR_SES_FROM
and recipients are configured, e-mails it with SES. Nothing here may break
closing an alert: every failure is logged and counted (AfterActionFailed).
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Any

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log, metric
from Pukaar.store.models import Alert, AuditRow, Delivery, TimelineEvent
from Pukaar.store.repo import Repo
from Pukaar.templates import hi

_LOG = get_logger("after_action")

KEY_PREFIX = "reports/after-action/"
IST = timezone(timedelta(hours=5, minutes=30))
MAX_AUDIT_DAYS = 7
MAX_RECIPIENTS = 20
# Actions that do not describe how the alert was handled (reading this report is one).
_AUDIT_SKIP = {"view_after_action"}
_EMAIL_RE = re.compile(r"^[^@\s,;<>\"]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
# Seven or more digits in a row (spaces allowed): phone numbers and Telegram chat ids.
_DIGITS_RE = re.compile(r"[+-]?\d(?:[ ]?\d){6,}")

# Water theme (frontend/src/theme.css), as literal colours for mail clients.
NAVY, NAVY_2, INK_ON_NAVY, INK_2_ON_NAVY = "#081828", "#123049", "#eaf4fb", "#9cc0dc"
RIVER, RIVER_DEEP, RIVER_LIGHT = "#4fb3ff", "#2f7df6", "#8ad0ff"
BG, SURFACE, INK, INK_3, LINE = "#f2f8fc", "#ffffff", "#0b1f33", "#557089", "#d6e6f1"
LEVEL_COLOURS = {
    "normal": ("#1f9468", "#def5ea", "#0f6443"),
    "watch": ("#e7b800", "#fff4c7", "#6b5000"),
    "warning": ("#ef6a1c", "#ffe6d5", "#9a3a00"),
    "critical": ("#c8173f", "#ffdfe6", "#9c0d2f"),
}
STEP_LABELS: dict[str, tuple[str, str]] = {
    "created": ("स्तर बढ़ा, चेतावनी बनी", "Level rose, alert created"),
    "escalated": ("मंज़ूरी से पहले स्तर और बढ़ा", "Level rose again while awaiting approval"),
    "drafted": ("संदेश तैयार", "Message drafted"),
    "asked_officer": ("अधिकारी से पूछा", "Officer asked"),
    "officer_timeout": ("अधिकारी ने समय पर जवाब नहीं दिया", "Officer did not answer in time"),
    "approved": ("मंज़ूर", "Approved"),
    "declined": ("नामंज़ूर", "Declined"),
    "decision_not_taken": ("फ़ैसला देर से आया", "Decision arrived late"),
    "auto_send": ("बिना मंज़ूरी भेजा (गंभीर)", "Sent without approval (critical)"),
    "expired": ("समय समाप्त, कुछ नहीं भेजा", "Expired, nothing sent"),
    "delivered": ("फ़ोन पर भेजा", "Sent to phones"),
    "recall": ("दोबारा भेजा", "Re-sent"),
    "failsafe": ("सुरक्षा टेम्पलेट", "Failsafe template"),
    "rollcall_opened": ("सुरक्षा रोल-कॉल शुरू", "Safety roll-call opened"),
    "start_failed": ("वर्कफ़्लो शुरू नहीं हुआ", "Workflow failed to start"),
    "closed": ("बंद", "Closed"),
}
OUTCOME_LABELS: dict[str, tuple[str, str]] = {
    "delivered": ("मंज़ूरी के बाद भेजा गया", "Delivered after approval"),
    "declined": ("अधिकारी ने नामंज़ूर किया, कुछ नहीं भेजा", "Declined by the officer; nothing sent"),
    "expired": ("किसी ने जवाब नहीं दिया, कुछ नहीं भेजा", "No officer answered; nothing sent"),
    "auto_sent_unapproved": ("बिना मंज़ूरी भेजा गया (गंभीर)", "Sent unapproved (critical, every officer timed out)"),
    "failsafe": ("सुरक्षा टेम्पलेट से भेजा गया", "Sent with the failsafe template"),
    "closed": ("बंद", "Closed"),
}


# -- small helpers ------------------------------------------------------------------
def scrub(text: str | None) -> str:
    """Mask phone numbers and chat ids in free text."""
    return _DIGITS_RE.sub("•••", text or "")


def first_name(name: str | None) -> str:
    word = (name or "").strip().split(" ")[0][:40]
    return scrub(word) if word and name != "Telegram user" else "—"


def ist(value: str | None, *, with_date: bool = True) -> str:
    if not value:
        return "—"
    try:
        dt = clock.parse(value).astimezone(IST)
    except ValueError:
        return "—"
    return dt.strftime("%d %b %Y, %H:%M:%S IST" if with_date else "%H:%M:%S IST")


def gap_seconds(start: str | None, end: str | None) -> int | None:
    """Seconds from start to end, or None if either is missing or the order is wrong (as TimeToEar.tsx)."""
    if not start or not end:
        return None
    try:
        s = (clock.parse(end) - clock.parse(start)).total_seconds()
    except ValueError:
        return None
    return round(s) if s >= 0 else None


def fmt_gap(seconds: int | None, lang: str) -> str:
    """"1 min 05 s" / "1 मि 05 से", the same form as the console's time-to-ear strip; hours when long."""
    if seconds is None:
        return "—"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if lang == "hi":
        if h:
            return f"{h} घं {m:02d} मि"
        return f"{m} मि {s:02d} से" if m else f"{s} से"
    if h:
        return f"{h} h {m:02d} min"
    return f"{m} min {s:02d} s" if m else f"{s} s"


def _earliest(values: Iterable[str | None]) -> str | None:
    xs = sorted(v for v in values if v)
    return xs[0] if xs else None


def time_to_ear(alert: Alert, deliveries: list[Delivery]) -> dict[str, Any]:
    """Level rose -> approved -> first voice on a phone -> first acknowledgement, with the gaps.

    The same four marks as the console's TimeToEar strip (components/TimeToEar.tsx).
    """
    marks = [
        ("rose", alert.created_at),
        ("decided", alert.decided_at),
        ("first_voice", _earliest(d.sent_at for d in deliveries)),
        ("first_ack", _earliest(d.acknowledged_at for d in deliveries)),
    ]
    out: dict[str, Any] = {"marks": []}
    for i, (key, at) in enumerate(marks):
        out["marks"].append({"key": key, "at": at,
                             "gap_seconds": gap_seconds(marks[i - 1][1], at) if i else None})
    out["total_seconds"] = gap_seconds(alert.created_at, marks[3][1])
    out["to_voice_seconds"] = gap_seconds(alert.created_at, marks[2][1])
    return out


MARK_LABELS = {
    "rose": ("स्तर बढ़ा", "Level rose"),
    "decided": ("मंज़ूरी", "Approved"),
    "first_voice": ("पहली आवाज़ फ़ोन पर", "First voice on a phone"),
    "first_ack": ("पहला 'मिल गया'", "First acknowledgement"),
}


def mode_of(alert: Alert) -> str:
    if alert.replay:
        return "replay"
    if alert.decision_trace.get("drill"):
        return "drill"
    return "live"


MODE_LABELS = {
    "live": ("असली चेतावनी", "LIVE"),
    "drill": ("अभ्यास (DRILL), असली चेतावनी नहीं", "DRILL, not a real warning"),
    "replay": ("रीप्ले: पुराने आँकड़े, किसी असली फ़ोन पर नहीं", "REPLAY: past data, no real phone"),
}


# -- the record -----------------------------------------------------------------------
def _sources(trace: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for ev in trace.get("evidence") or []:
        kind = ev.get("kind")
        if kind == "reading":
            out.append(f"Forecast ({ev.get('source') or 'open-meteo'}): rain 24 h {ev.get('rain_24h_mm')} mm "
                       f"({ev.get('rain_level')}); river peak {ev.get('discharge_peak')} m³/s ({ev.get('river_level')})")
        elif kind == "soil":
            out.append(f"Soil moisture (root zone): {ev.get('moisture_root')} m³/m³"
                       + (f", saturation {ev.get('saturation')}" if ev.get("saturation") is not None else ""))
        elif kind == "gauge":
            out.append(f"River gauge {ev.get('device_id')}: {ev.get('water_level_cm')} cm ({ev.get('gauge_level')})"
                       + (" SIMULATED" if ev.get("simulated") else ""))
        elif kind == "report":
            out.append(f"Villager report: {ev.get('type')}, severity {ev.get('severity')}, "
                       f"{'verified' if ev.get('verified') else 'unverified'}")
    if not out and trace.get("drill"):
        out.append("Drill started by hand (scripts/drill.py); no forecast evidence")
    elif not out:
        out.append("No evidence recorded in the decision trace")
    return [scrub(s) for s in out]


def _drafting(alert: Alert) -> dict[str, Any]:
    model = alert.reasoning_model or "rule-fallback"
    fixed = model == "rule-fallback" or alert.status in {"auto_sent_unapproved", "failsafe"}
    if fixed:
        how_en = "Fixed Hindi template (rule-fallback): no model wrote this text"
        how_hi = "तय हिन्दी टेम्पलेट (rule-fallback): यह संदेश किसी मॉडल ने नहीं लिखा"
    else:
        how_en = f"Model {model} filled the fixed Hindi template; the checker read every number and place"
        how_hi = f"मॉडल {model} ने तय हिन्दी टेम्पलेट भरा; जाँच ने हर संख्या और जगह मिलाई"
    return {"model": model, "fixed_template": fixed, "how_en": how_en, "how_hi": how_hi,
            "check_passed": alert.draft_check.passed if alert.draft_check else None,
            "check_reason": scrub(alert.draft_check.reason) if alert.draft_check else None}


def _approval(alert: Alert, timeline: list[TimelineEvent]) -> dict[str, Any]:
    asked = [scrub(t.detail.split(" ")[0]) for t in timeline if t.step == "asked_officer" and t.detail]
    return {
        "officers_asked": asked,
        "timeouts": sum(1 for t in timeline if t.step == "officer_timeout"),
        "escalations": sum(1 for t in timeline if t.step == "escalated"),
        "decided_by": scrub(alert.decided_by) if alert.decided_by else None,
        "decided_at": alert.decided_at,
        "approved": alert.approved,
        "auto_sent_unapproved": alert.status == "auto_sent_unapproved" or any(t.step == "auto_send" for t in timeline),
        "failsafe": any(t.step == "failsafe" for t in timeline),
        "steps": [{"at": t.at, "step": t.step, "detail": scrub(t.detail)} for t in timeline
                  if t.step in {"asked_officer", "officer_timeout", "escalated", "approved", "declined",
                                "decision_not_taken", "auto_send", "expired", "failsafe"}],
    }


def _deliveries(deliveries: list[Delivery], timeline: list[TimelineEvent]) -> dict[str, Any]:
    by_channel: dict[str, dict[str, int]] = {}
    rows = []
    for d in sorted(deliveries, key=lambda x: (x.sent_at or "~", first_name(x.name))):
        c = by_channel.setdefault(d.channel, {"total": 0, "sent": 0, "failed": 0, "acknowledged": 0, "resent": 0})
        c["total"] += 1
        c["sent"] += 1 if d.sent_at else 0
        c["failed"] += 1 if d.status == "failed" else 0
        c["acknowledged"] += 1 if d.acknowledged_at else 0
        c["resent"] += 1 if d.attempts >= 2 and d.sent_at else 0
        # Raw errors can carry a chat id; only say whether policy blocked it.
        failure = None
        if d.status == "failed":
            failure = "blocked by policy" if (d.error or "").startswith("blocked") else "send failed"
        rows.append({"name": first_name(d.name), "channel": d.channel, "status": d.status, "sent_at": d.sent_at,
                     "acknowledged_at": d.acknowledged_at, "attempts": d.attempts, "failure": failure})
    totals = {k: sum(c[k] for c in by_channel.values()) for k in ("total", "sent", "failed", "acknowledged", "resent")}
    return {"by_channel": by_channel, "totals": totals, "rows": rows,
            "resend_rounds": [{"at": t.at, "detail": scrub(t.detail)} for t in timeline if t.step == "recall"]}


def _rollcall(repo: Repo, alert: Alert) -> dict[str, Any] | None:
    for rc in repo.list_rollcalls(alert.village_id, limit=20):
        if rc.alert_id == alert.id:
            return {"exercise": rc.exercise, "opened_at": rc.opened_at, "closes_at": rc.closes_at, "asked": rc.asked,
                    "safe": rc.safe, "need_help": rc.need_help,
                    "not_answered": max(rc.asked - rc.safe - rc.need_help, 0)}
    return None


def _audit(repo: Repo, alert: Alert, closed_at: str | None) -> dict[str, Any]:
    start = clock.parse(alert.created_at).date()
    end = clock.parse(closed_at).date() if closed_at else clock.now().date()
    days = [(start + timedelta(days=i)).isoformat() for i in range(min(max((end - start).days, 0), MAX_AUDIT_DAYS) + 1)]
    rows: list[AuditRow] = []
    for day in days:
        rows += [r for r in repo.list_audit(day, f"alert:{alert.id}") if r.action not in _AUDIT_SKIP]
    rows.sort(key=lambda r: r.at)
    denies = [{"at": r.at, "actor": scrub(r.actor), "role": r.role, "action": r.action, "reason": scrub(r.reason)}
              for r in rows if r.decision == "deny"]
    by_action: dict[str, dict[str, int]] = {}
    for r in rows:
        by_action.setdefault(r.action, {"allow": 0, "deny": 0})[r.decision] += 1
    return {"allow": sum(1 for r in rows if r.decision == "allow"), "deny": len(denies),
            "by_action": by_action, "denies": denies}


def collect(repo: Repo, alert: Alert) -> dict[str, Any]:
    """Everything the report shows, as plain data (also the JSON summary)."""
    timeline = repo.list_timeline(alert.id)
    deliveries = repo.list_deliveries(alert.id)
    village = repo.get_village(alert.village_id)
    closed = next((t for t in reversed(timeline) if t.step == "closed"), None)
    trace = alert.decision_trace or {}
    return {
        "alert_id": alert.id,
        "mode": mode_of(alert),
        "village": {"id": alert.village_id, "name": alert.village_name, "name_hi": alert.village_name_hi,
                    "district": village.district if village else ""},
        "level": alert.level,
        "previous_level": alert.previous_level,
        "status": alert.status,
        # Interim until the workflow's close step has run (deliveries may still be acknowledged).
        "open": closed is None,
        "created_at": alert.created_at,
        "closed_at": closed.at if closed else None,
        "generated_at": clock.iso(clock.now()),
        "time_to_ear": time_to_ear(alert, deliveries),
        "decision": {"rules_fired": [scrub(str(r)) for r in trace.get("rules_fired") or []],
                     "sources": _sources(trace),
                     "contradictions": [scrub(str(c)) for c in trace.get("contradictions") or []],
                     "reason_en": scrub(alert.reason_en),
                     "drafting": _drafting(alert)},
        "approval": _approval(alert, timeline),
        "deliveries": _deliveries(deliveries, timeline),
        "rollcall": _rollcall(repo, alert),
        "audit": _audit(repo, alert, closed.at if closed else None),
        "text_hi": scrub(alert.text_hi),
        "text_en": scrub(alert.text_en),
        "timeline": [{"at": t.at, "step": t.step, "detail": scrub(t.detail)} for t in timeline],
    }


def subject(data: dict[str, Any]) -> str:
    when = ist(data["created_at"]).split(",")[0]
    label = {"drill": " [DRILL]", "replay": " [REPLAY]"}.get(data["mode"], "")
    return f"पुकार after-action: {data['village']['name']} {hi.LEVEL_EN.get(data['level'], data['level'])} {when}{label}"


def summary_json(data: dict[str, Any]) -> dict[str, Any]:
    """The small JSON summary: counts and key times, no rows."""
    d, tte = data["deliveries"], data["time_to_ear"]
    return {
        "alert_id": data["alert_id"], "mode": data["mode"], "village_id": data["village"]["id"],
        "level": data["level"], "status": data["status"], "created_at": data["created_at"],
        "closed_at": data["closed_at"], "generated_at": data["generated_at"],
        "times": {m["key"]: m["at"] for m in tte["marks"]},
        "time_to_voice_seconds": tte["to_voice_seconds"], "time_to_ear_seconds": tte["total_seconds"],
        "drafting": data["decision"]["drafting"]["model"],
        "fixed_template": data["decision"]["drafting"]["fixed_template"],
        "decided_by": data["approval"]["decided_by"], "officer_timeouts": data["approval"]["timeouts"],
        "deliveries": d["totals"], "deliveries_by_channel": d["by_channel"],
        "rollcall": data["rollcall"],
        "audit": {"allow": data["audit"]["allow"], "deny": data["audit"]["deny"]},
    }


# -- rendering ---------------------------------------------------------------------------
def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


_FONT = "font-family:'Noto Sans Devanagari','Mangal',Arial,Helvetica,sans-serif;"


def _section(title_hi: str, title_en: str, body: str) -> str:
    return (f'<tr><td style="padding:20px 24px 4px 24px;{_FONT}">'
            f'<div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:{RIVER_DEEP};font-weight:bold;">'
            f'{_e(title_en)}</div>'
            f'<div style="font-size:17px;color:{INK};font-weight:bold;margin:2px 0 10px 0;">{_e(title_hi)}</div>'
            f'{body}</td></tr>')


def _table(head: list[str], rows: list[list[str]], *, raw: bool = False) -> str:
    th = "".join(f'<th align="left" style="padding:6px 8px;border-bottom:2px solid {RIVER};font-size:12px;'
                 f'color:{INK_3};{_FONT}">{_e(h)}</th>' for h in head)
    body = ""
    for i, row in enumerate(rows):
        bg = SURFACE if i % 2 == 0 else BG
        body += "<tr>" + "".join(
            f'<td valign="top" style="padding:6px 8px;border-bottom:1px solid {LINE};font-size:13px;color:{INK};'
            f'background:{bg};{_FONT}">{c if raw else _e(c)}</td>' for c in row) + "</tr>"
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="border-collapse:collapse;">{"<tr>" + th + "</tr>" if head else ""}{body}</table>')


def _p(text: str, *, muted: bool = False) -> str:
    return f'<p style="margin:4px 0;font-size:13px;color:{INK_3 if muted else INK};{_FONT}">{_e(text)}</p>'


def render_html(data: dict[str, Any]) -> str:
    lv = data["level"]
    lv_main, lv_bg, lv_ink = LEVEL_COLOURS.get(lv, LEVEL_COLOURS["watch"])
    mode = data["mode"]
    mode_hi, mode_en = MODE_LABELS[mode]
    outcome_hi, outcome_en = OUTCOME_LABELS.get(data["status"], (data["status"], data["status"]))
    v = data["village"]
    tte = data["time_to_ear"]
    sections: list[str] = []

    # Key times
    rows = []
    for m in tte["marks"]:
        lab_hi, lab_en = MARK_LABELS[m["key"]]
        g = m["gap_seconds"]
        rows.append([f"{lab_en} / {lab_hi}", ist(m["at"]),
                     f"+{fmt_gap(g, 'en')} / +{fmt_gap(g, 'hi')}" if g is not None else "—"])
    total = tte["total_seconds"]
    body = _table(["Mark / पड़ाव", "Time (IST) / समय", "Gap / अंतर"], rows)
    body += _p(f"Level rose to first acknowledgement: {fmt_gap(total, 'en')}" if total is not None
               else "No acknowledgement yet: time to ear not measured.")
    body += _p(f"स्तर बढ़ने से पहले 'मिल गया' तक: {fmt_gap(total, 'hi')}" if total is not None
               else "अभी तक 'मिल गया' नहीं आया।", muted=True)
    sections.append(_section("मुख्य समय", "Key times (time to ear)", body))

    # Decision trace
    dec = data["decision"]
    dr = dec["drafting"]
    body = _p("Sources / स्रोत:")
    body += _table([], [[s] for s in dec["sources"]] or [["—"]])
    body += _p("Rules fired / लागू नियम: " + (", ".join(dec["rules_fired"]) or "—"))
    if dec["contradictions"]:
        body += _p("Data disagrees / आँकड़े आपस में अलग: " + "; ".join(dec["contradictions"]))
    if dec["reason_en"]:
        body += _p("Reason: " + dec["reason_en"], muted=True)
    body += _p(f"Text: {dr['how_en']}")
    body += _p(f"संदेश: {dr['how_hi']}", muted=True)
    if dr["check_passed"] is not None:
        body += _p(f"Checker / जाँच: {'pass' if dr['check_passed'] else 'fail'}, {dr['check_reason']}", muted=True)
    sections.append(_section("फ़ैसला कैसे हुआ", "Decision trace", body))

    # Approval chain
    ap = data["approval"]
    rows = [[ist(s["at"]), " / ".join(reversed(STEP_LABELS.get(s["step"], (s["step"], s["step"])))), s["detail"]]
            for s in ap["steps"]]
    body = _table(["Time (IST)", "Step / चरण", "Detail"], rows or [["—", "—", "—"]])
    if ap["auto_sent_unapproved"]:
        who = "system: every officer timed out at critical (flagged unapproved) / सभी अधिकारियों का समय समाप्त"
    elif ap["decided_by"]:
        who = f"{ap['decided_by']} at {ist(ap['decided_at'])} ({'approved / मंज़ूर' if ap['approved'] else 'declined / नामंज़ूर'})"
    else:
        who = "nobody decided / किसी ने फ़ैसला नहीं किया"
    body += _p(f"Decided by / फ़ैसला: {who}")
    body += _p(f"Officers asked: {len(ap['officers_asked'])}; timeouts: {ap['timeouts']}; "
               f"escalations: {ap['escalations']}" + ("; failsafe used" if ap["failsafe"] else ""), muted=True)
    sections.append(_section("मंज़ूरी की कड़ी", "Approval chain", body))

    # Deliveries
    d = data["deliveries"]
    rows = [[ch, str(c["total"]), str(c["sent"]), str(c["failed"]), str(c["acknowledged"]), str(c["resent"])]
            for ch, c in sorted(d["by_channel"].items())]
    body = _table(["Channel / माध्यम", "Phones", "Sent", "Failed", "Acknowledged", "Re-sent"],
                  rows or [["—", "0", "0", "0", "0", "0"]])
    if any(ch == "stub" for ch in d["by_channel"]):
        body += _p("stub = demo recipient with no phone: nothing reached a real phone on that channel.", muted=True)
    if d["rows"]:
        people = [[r["name"], r["channel"], ist(r["sent_at"], with_date=False),
                   ist(r["acknowledged_at"], with_date=False) if r["acknowledged_at"] else "—",
                   str(r["attempts"]) + (f" ({r['failure']})" if r["failure"] else "")] for r in d["rows"]]
        body += '<div style="height:8px"></div>' + _table(
            ["First name / नाम", "Channel", "Sent", "Acknowledged / मिल गया", "Attempts"], people)
    for rr in d["resend_rounds"]:
        body += _p(f"Re-send round at {ist(rr['at'])}: {rr['detail']}", muted=True)
    sections.append(_section("किस तक पहुँचा", "Deliveries and acknowledgements", body))

    # Roll-call
    rc = data["rollcall"]
    if rc:
        body = _table(["Asked / पूछा", "Safe / सुरक्षित", "Need help / मदद चाहिए", "Not answered / जवाब नहीं"],
                      [[str(rc["asked"]), str(rc["safe"]), str(rc["need_help"]), str(rc["not_answered"])]])
        body += _p(f"Opened {ist(rc['opened_at'])}; open until {ist(rc['closes_at'])}"
                   + (" (exercise / अभ्यास)" if rc["exercise"] else "") + ". Counts only; names stay on the board.",
                   muted=True)
        sections.append(_section("सुरक्षा रोल-कॉल (सुरक्षित हूँ)", "Safety roll-call (Surakshit Hoon)", body))

    # Audit
    au = data["audit"]
    rows = [[a, str(c["allow"]), str(c["deny"])] for a, c in sorted(au["by_action"].items())]
    body = _p(f"Policy decisions on this alert: {au['allow']} allowed, {au['deny']} denied "
              f"/ इस चेतावनी पर नीति के फ़ैसले: {au['allow']} अनुमति, {au['deny']} मना")
    if rows:
        body += _table(["Action", "Allow", "Deny"], rows)
    if au["denies"]:
        body += '<div style="height:8px"></div>' + _table(
            ["Time (IST)", "Who", "Action", "Reason"],
            [[ist(x["at"]), f"{x['actor']} ({x['role']})", x["action"], x["reason"]] for x in au["denies"]])
    sections.append(_section("नीति ऑडिट (Cedar)", "Audit decisions (Cedar)", body))

    # Text sent
    body = (f'<div lang="hi" style="background:{BG};border-left:4px solid {RIVER};padding:10px 12px;font-size:16px;'
            f'line-height:1.6;color:{INK};{_FONT}">{_e(data["text_hi"] or "—")}</div>'
            f'<div lang="en" style="padding:8px 12px;font-size:13px;color:{INK_3};{_FONT}">{_e(data["text_en"] or "—")}</div>')
    sections.append(_section("भेजा गया संदेश (आवाज़ में यही पढ़ा गया)", "Text sent (the words spoken by Polly)", body))

    # Full timeline
    rows = [[ist(t["at"]), " / ".join(reversed(STEP_LABELS.get(t["step"], (t["step"], t["step"])))), t["detail"]]
            for t in data["timeline"]]
    sections.append(_section("पूरी समय-रेखा", "Full timeline", _table(["Time (IST)", "Step / चरण", "Detail"],
                                                                     rows or [["—", "—", "—"]])))

    interim = ('<div style="margin-top:8px;font-size:12px;color:#ffd166;">Interim: this alert is still open / '
               'अंतरिम: चेतावनी अभी खुली है</div>') if data["open"] else ""
    mode_bg = {"live": RIVER, "drill": "#e7b800", "replay": INK_2_ON_NAVY}[mode]
    header = (
        f'<tr><td style="background:{NAVY};background-image:linear-gradient(160deg,{NAVY} 0%,{NAVY_2} 100%);'
        f'padding:22px 24px;{_FONT}">'
        f'<div style="font-size:13px;letter-spacing:3px;color:{RIVER_LIGHT};font-weight:bold;">पुकार · PUKAAR</div>'
        f'<div style="font-size:24px;color:{INK_ON_NAVY};font-weight:bold;margin-top:6px;">After-action report</div>'
        f'<div style="font-size:18px;color:{INK_2_ON_NAVY};">कार्रवाई के बाद की रिपोर्ट</div>'
        f'<div style="margin-top:12px;">'
        f'<span style="display:inline-block;background:{lv_bg};color:{lv_ink};border:1px solid {lv_main};'
        f'border-radius:999px;padding:3px 12px;font-size:13px;font-weight:bold;">'
        f'{_e(hi.LEVEL_HI.get(lv, lv))} · {_e(hi.LEVEL_EN.get(lv, lv))}</span> '
        f'<span style="display:inline-block;background:{mode_bg};color:{NAVY};border-radius:999px;padding:3px 12px;'
        f'font-size:12px;font-weight:bold;">{_e(mode_en)} · {_e(mode_hi)}</span></div>'
        f'<div style="font-size:20px;color:{INK_ON_NAVY};margin-top:12px;font-weight:bold;">'
        f'{_e(v["name_hi"])} · {_e(v["name"])}</div>'
        f'<div style="font-size:13px;color:{INK_2_ON_NAVY};">{_e(v["district"])} district · alert {_e(data["alert_id"])}</div>'
        f'<div style="font-size:13px;color:{INK_2_ON_NAVY};margin-top:6px;">'
        f'Level rose / स्तर बढ़ा: {_e(ist(data["created_at"]))}<br>'
        f'Closed / बंद: {_e(ist(data["closed_at"]))}<br>'
        f'Outcome / नतीजा: {_e(outcome_en)} / {_e(outcome_hi)}</div>{interim}</td></tr>'
        f'<tr><td height="6" style="height:6px;line-height:6px;font-size:0;background:{RIVER};'
        f'background-image:linear-gradient(100deg,{RIVER_LIGHT} 0%,{RIVER} 45%,{RIVER_DEEP} 100%);">&nbsp;</td></tr>'
    )
    footer = (f'<tr><td style="padding:18px 24px 24px 24px;font-size:11px;color:{INK_3};{_FONT}">'
              f'Generated {_e(ist(data["generated_at"]))} from the alert\'s own records (timeline, deliveries, '
              f'Cedar audit log). No phone numbers or chat ids appear in this report; people are shown by first name only. '
              f'/ यह रिपोर्ट चेतावनी के अपने रिकॉर्ड से बनी है; इसमें कोई फ़ोन नंबर नहीं है।</td></tr>')
    title = _e(subject(data))
    return (
        '<!doctype html><html lang="hi"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:">'
        f'<title>{title}</title></head>'
        f'<body style="margin:0;padding:0;background:{BG};">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{BG}" '
        f'style="background:{BG};"><tr><td align="center" style="padding:16px 8px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{SURFACE}" '
        f'style="max-width:680px;background:{SURFACE};border:1px solid {LINE};border-radius:12px;overflow:hidden;">'
        f'{header}{"".join(sections)}{footer}</table></td></tr></table></body></html>'
    )


def render_text(data: dict[str, Any]) -> str:
    v, tte, mode = data["village"], data["time_to_ear"], data["mode"]
    mode_hi, mode_en = MODE_LABELS[mode]
    outcome_hi, outcome_en = OUTCOME_LABELS.get(data["status"], (data["status"], data["status"]))
    lines = [
        "पुकार · PUKAAR: after-action report / कार्रवाई के बाद की रिपोर्ट",
        f"{v['name_hi']} · {v['name']} ({v['district']})",
        f"Level / स्तर: {hi.LEVEL_EN.get(data['level'], data['level'])} / {hi.LEVEL_HI.get(data['level'], data['level'])}",
        f"Mode: {mode_en} / {mode_hi}",
        f"Alert: {data['alert_id']}",
        f"Level rose: {ist(data['created_at'])}   Closed: {ist(data['closed_at'])}",
        f"Outcome: {outcome_en} / {outcome_hi}",
    ]
    if data["open"]:
        lines.append("Interim: this alert is still open / अंतरिम: चेतावनी अभी खुली है")
    lines += ["", "KEY TIMES / मुख्य समय"]
    for m in tte["marks"]:
        lab_hi, lab_en = MARK_LABELS[m["key"]]
        g = m["gap_seconds"]
        lines.append(f"  {lab_en} / {lab_hi}: {ist(m['at'])}" + (f"  (+{fmt_gap(g, 'en')} / +{fmt_gap(g, 'hi')})" if g is not None else ""))
    total = tte["total_seconds"]
    lines.append(f"  Time to ear: {fmt_gap(total, 'en')} / {fmt_gap(total, 'hi')}" if total is not None
                 else "  Time to ear: no acknowledgement yet / अभी तक 'मिल गया' नहीं आया")

    dec = data["decision"]
    lines += ["", "DECISION TRACE / फ़ैसला कैसे हुआ"]
    lines += [f"  - {s}" for s in dec["sources"]] or ["  - —"]
    lines.append(f"  Rules fired: {', '.join(dec['rules_fired']) or '—'}")
    if dec["contradictions"]:
        lines.append(f"  Data disagrees: {'; '.join(dec['contradictions'])}")
    lines.append(f"  Text: {dec['drafting']['how_en']}")
    lines.append(f"  संदेश: {dec['drafting']['how_hi']}")

    ap = data["approval"]
    lines += ["", "APPROVAL CHAIN / मंज़ूरी की कड़ी"]
    for s in ap["steps"]:
        lab_hi, lab_en = STEP_LABELS.get(s["step"], (s["step"], s["step"]))
        lines.append(f"  {ist(s['at'])}  {lab_en} / {lab_hi}  {s['detail']}")
    if ap["auto_sent_unapproved"]:
        lines.append("  Decided by: system (every officer timed out at critical; flagged unapproved)")
    elif ap["decided_by"]:
        lines.append(f"  Decided by: {ap['decided_by']} at {ist(ap['decided_at'])} ({'approved' if ap['approved'] else 'declined'})")
    else:
        lines.append("  Decided by: nobody / किसी ने फ़ैसला नहीं किया")
    lines.append(f"  Officers asked: {len(ap['officers_asked'])}; timeouts: {ap['timeouts']}; escalations: {ap['escalations']}")

    d = data["deliveries"]
    lines += ["", "DELIVERIES / किस तक पहुँचा"]
    for ch, c in sorted(d["by_channel"].items()):
        lines.append(f"  {ch}: phones {c['total']}, sent {c['sent']}, failed {c['failed']}, "
                     f"acknowledged {c['acknowledged']}, re-sent {c['resent']}")
    if not d["by_channel"]:
        lines.append("  nothing was sent / कुछ नहीं भेजा गया")
    for r in d["rows"]:
        lines.append(f"  - {r['name']} ({r['channel']}): sent {ist(r['sent_at'], with_date=False)}, "
                     f"acknowledged {ist(r['acknowledged_at'], with_date=False) if r['acknowledged_at'] else '—'}, "
                     f"attempts {r['attempts']}" + (f" ({r['failure']})" if r["failure"] else ""))

    rc = data["rollcall"]
    if rc:
        lines += ["", "SAFETY ROLL-CALL / सुरक्षा रोल-कॉल" + (" (exercise / अभ्यास)" if rc["exercise"] else ""),
                  f"  asked {rc['asked']}, safe {rc['safe']}, need help {rc['need_help']}, not answered {rc['not_answered']}"]

    au = data["audit"]
    lines += ["", "AUDIT (Cedar) / नीति ऑडिट", f"  {au['allow']} allowed, {au['deny']} denied"]
    for x in au["denies"]:
        lines.append(f"  DENY {ist(x['at'])} {x['actor']} ({x['role']}) {x['action']}: {x['reason']}")

    lines += ["", "TEXT SENT / भेजा गया संदेश", f"  {data['text_hi'] or '—'}", f"  {data['text_en'] or '—'}",
              "", f"Generated {ist(data['generated_at'])}. No phone numbers or chat ids; first names only."]
    return "\n".join(lines) + "\n"


@dataclass
class AfterAction:
    alert_id: str
    mode: str
    subject: str
    html: str
    text: str
    summary: dict[str, Any]


def build(repo: Repo, alert: Alert) -> AfterAction:
    data = collect(repo, alert)
    return AfterAction(alert_id=alert.id, mode=data["mode"], subject=subject(data), html=render_html(data),
                       text=render_text(data), summary=summary_json(data))


# -- storage and e-mail -----------------------------------------------------------------------
def html_key(alert_id: str) -> str:
    return f"{KEY_PREFIX}{alert_id}.html"


def store(report: AfterAction) -> str:
    from Pukaar.services import storage

    key = storage.put_bytes(html_key(report.alert_id), report.html.encode("utf-8"), "text/html; charset=utf-8")
    storage.put_bytes(f"{KEY_PREFIX}{report.alert_id}.json",
                      json.dumps(report.summary, ensure_ascii=False, indent=1).encode("utf-8"), "application/json")
    return key


def load_stored(alert_id: str) -> str | None:
    from Pukaar.services import storage

    try:
        body, _ = storage.get_bytes(html_key(alert_id))
    except Exception:
        return None
    return body.decode("utf-8")


def _valid(addresses: Iterable[str]) -> list[str]:
    out: list[str] = []
    for a in addresses:
        a = a.strip()
        if a and _EMAIL_RE.match(a) and a.lower() not in {x.lower() for x in out}:
            out.append(a)
    return out[:MAX_RECIPIENTS]


def recipients() -> list[str]:
    """Officers' addresses: PUKAAR_AFTER_ACTION_TO (env, or SSM /pukaar/after_action_to on AWS), comma separated,
    plus any officer "email" in data/villages.json. In the SES sandbox each one must be a verified identity."""
    from Pukaar.core.secrets import get_secret

    found = [a for a in (get_secret("after_action_to") or "").split(",")]
    try:
        cfg = json.loads((get_settings().data_dir / "villages.json").read_text(encoding="utf-8"))
        found += [str(o.get("email") or "") for o in cfg.get("officers", [])]
    except Exception as exc:
        log(_LOG, "officer config unreadable", 30, error=str(exc)[:200])
    return _valid(found)


def send_email(report: AfterAction, *, sender: str, to: list[str], client: Any = None) -> dict[str, Any]:
    """One SES v2 SendEmail per recipient, so one unverified address (SES sandbox) cannot stop the others."""
    if client is None:
        import boto3

        client = boto3.client("sesv2", region_name=get_settings().aws_region)
    sent, failed = [], []
    for address in to:
        try:
            resp = client.send_email(
                FromEmailAddress=sender,
                Destination={"ToAddresses": [address]},
                Content={"Simple": {
                    "Subject": {"Data": report.subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": report.text, "Charset": "UTF-8"},
                             "Html": {"Data": report.html, "Charset": "UTF-8"}},
                }},
            )
            sent.append(resp.get("MessageId", ""))
        except Exception as exc:
            failed.append(type(exc).__name__)
            log(_LOG, "after-action e-mail failed", 40, alert_id=report.alert_id, error=str(exc)[:300])
    return {"sent": len(sent), "failed": len(failed), "message_ids": sent}


def email(report: AfterAction, *, client: Any = None) -> dict[str, Any]:
    """Send when configured; otherwise say why not. Replays are never e-mailed (they are not real events)."""
    s = get_settings()
    if report.mode == "replay":
        return {"skipped": "replay"}
    if s.is_local and client is None:
        log(_LOG, "after-action e-mail skipped: local mode", alert_id=report.alert_id)
        return {"skipped": "local"}
    if not s.ses_from:
        log(_LOG, "after-action e-mail skipped: PUKAAR_SES_FROM not set", alert_id=report.alert_id)
        return {"skipped": "no sender"}
    to = recipients()
    if not to:
        log(_LOG, "after-action e-mail skipped: no recipients", alert_id=report.alert_id)
        return {"skipped": "no recipients"}
    result = send_email(report, sender=s.ses_from, to=to, client=client)
    if result["failed"]:
        metric("AfterActionFailed", result["failed"])
    if result["sent"]:
        metric("AfterActionSent", result["sent"])
    log(_LOG, "after-action e-mailed", alert_id=report.alert_id, sent=result["sent"], failed=result["failed"])
    return result


def on_close(repo: Repo, alert_id: str, *, ses_client: Any = None) -> dict[str, Any]:
    """Called by the workflow's close step. Never raises."""
    out: dict[str, Any] = {"stored": None, "email": None}
    try:
        alert = repo.get_alert(alert_id)
        if alert is None:
            return out
        report = build(repo, alert)
    except Exception as exc:
        log(_LOG, "after-action build failed", 40, alert_id=alert_id, error=str(exc)[:300])
        metric("AfterActionFailed")
        return out
    try:
        out["stored"] = store(report)
    except Exception as exc:
        log(_LOG, "after-action store failed", 40, alert_id=alert_id, error=str(exc)[:300])
        metric("AfterActionFailed")
    try:
        out["email"] = email(report, client=ses_client)
    except Exception as exc:
        log(_LOG, "after-action e-mail error", 40, alert_id=alert_id, error=str(exc)[:300])
        metric("AfterActionFailed")
    return out
