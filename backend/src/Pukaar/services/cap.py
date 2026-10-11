"""CAP 1.2 (Common Alerting Protocol) export of published alerts, and an ATOM index of them.

India's national alerting system (NDMA's SACHET) is built on CAP, as are Google
Public Alerts and most alert aggregators. Each alert that actually went out is
rendered as one CAP 1.2 <alert> with two <info> blocks (hi-IN, en-IN) and a
circle around the village point.

What is published: alerts an officer approved, critical alerts auto-sent after
every officer timed out, and alerts the failsafe broadcast. Never pending,
declined, expired or drafting alerts.

Choices (OASIS CAP 1.2, http://docs.oasis-open.org/emergency/cap/v1.2/):
- status: Actual for live alerts; Exercise for replays of archived floods and
  for drills (decision_trace.drill), which never describe a real flood now.
- msgType: Update when the village was already above normal and an earlier
  alert for it was published (that alert goes in <references>); Alert otherwise.
- times: CAP forbids "Z"; times are written in IST (+05:30). sent and effective
  are the decision time (approval, auto-send) or, failing that, creation time.
- expires: effective + 12 hours. The sweep re-evaluates every 15 minutes and a
  new alert is raised if the level rises, so a 12-hour window covers one night.
- area: a 5 km circle around the village point. The points are geocoded and not
  verified on the ground; a parameter says so.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Iterable

from Pukaar.core import clock
from Pukaar.store.models import Alert, Village
from Pukaar.templates import hi

CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"
ATOM_NS = "http://www.w3.org/2005/Atom"
CAP_CONTENT_TYPE = "application/cap+xml; charset=utf-8"
ATOM_CONTENT_TYPE = "application/atom+xml; charset=utf-8"

IST = timezone(timedelta(hours=5, minutes=30))
EXPIRES_AFTER = timedelta(hours=12)
AREA_RADIUS_KM = 5.0
FEED_SIZE = 50
SENDER_NAME = "Pukaar — District Disaster Management (demo)"
SENDER_NAME_HI = "पुकार — ज़िला आपदा प्रबंधन (डेमो)"
STATE = "Himachal Pradesh"
STATE_HI = "हिमाचल प्रदेश"

# level -> (urgency, severity, certainty, responseType)
MAPPING: dict[str, tuple[str, str, str, str]] = {
    "watch": ("Expected", "Moderate", "Possible", "Monitor"),
    "warning": ("Expected", "Severe", "Likely", "Prepare"),
    "critical": ("Immediate", "Extreme", "Likely", "Evacuate"),
}
LEVEL_EN = {"watch": "Flood Watch", "warning": "Flood Warning", "critical": "Critical Flood Warning"}
LEVEL_HI = {"watch": "बाढ़ — सतर्क रहें", "warning": "बाढ़ की चेतावनी", "critical": "बाढ़ का गंभीर ख़तरा"}

_SENT_STATUSES = {"approved", "delivering", "delivered", "auto_sent_unapproved"}


def is_published(a: Alert) -> bool:
    """True only for alerts that went (or are going) out to people."""
    if a.level not in MAPPING:
        return False
    if a.status in _SENT_STATUSES:
        return True
    if a.status == "failsafe":  # the failsafe broadcasts only critical or already-approved alerts
        return a.level == "critical" or a.approved
    if a.status == "closed":
        return a.approved
    return False


def is_exercise(a: Alert) -> bool:
    return bool(a.replay or a.decision_trace.get("replay") or a.decision_trace.get("drill"))


def cap_time(value: str | datetime) -> str:
    dt = clock.parse(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).isoformat(timespec="seconds")


def sent_at(a: Alert) -> str:
    return a.decided_at or a.created_at


def previous_published(a: Alert, candidates: Iterable[Alert]) -> Alert | None:
    """The newest published alert for the same village created before this one."""
    best: Alert | None = None
    for c in candidates:
        if c.id == a.id or c.village_id != a.village_id or not is_published(c):
            continue
        if is_exercise(c) != is_exercise(a) or c.created_at >= a.created_at:
            continue
        if best is None or c.created_at > best.created_at:
            best = c
    return best


def _sub(parent: ET.Element, tag: str, text: str | None = None, ns: str = CAP_NS) -> ET.Element:
    el = ET.SubElement(parent, f"{{{ns}}}{tag}" if ns else tag)
    if text is not None:
        el.text = text
    return el


def _approval(a: Alert) -> str:
    if a.status == "auto_sent_unapproved":
        return "auto-sent: no officer answered in time at critical; fixed template, unapproved"
    if a.status == "failsafe":
        return "failsafe: workflow error; fixed template sent"
    return "approved by a duty officer"


def _parameters(a: Alert, village: Village | None) -> list[tuple[str, str]]:
    rules = [str(r) for r in a.decision_trace.get("rules_fired") or []]
    params = [
        ("level", a.level),
        ("previous_level", a.previous_level),
        ("rules_fired", ", ".join(rules) if rules else "none recorded"),
        ("approval", _approval(a)),
        ("text_source", a.reasoning_model),
    ]
    if village is not None:
        params.append(("coordinates",
                       "verified" if village.coords_verified
                       else "approximate: geocoded (GeoNames via Open-Meteo), not verified on the ground"))
        params.append(("area_radius_km", f"{AREA_RADIUS_KM:g}"))
    if a.replay or a.decision_trace.get("replay"):
        params.append(("exercise", "replay of archived data; not a current flood"))
    if a.decision_trace.get("drill"):
        params.append(("exercise", "drill: a test alert started by hand; not a real flood"))
    return params


def _info(alert_el: ET.Element, a: Alert, village: Village | None, lang: str, web_url: str) -> None:
    urgency, severity, certainty, response = MAPPING[a.level]
    effective = clock.parse(sent_at(a))
    hindi = lang == "hi-IN"
    district = village.district if village else ""
    info = _sub(alert_el, "info")
    _sub(info, "language", lang)
    _sub(info, "category", "Met")
    _sub(info, "event", "बाढ़" if hindi else "Flood")
    _sub(info, "responseType", response)
    _sub(info, "urgency", urgency)
    _sub(info, "severity", severity)
    _sub(info, "certainty", certainty)
    _sub(info, "effective", cap_time(effective))
    _sub(info, "expires", cap_time(effective + EXPIRES_AFTER))
    _sub(info, "senderName", SENDER_NAME_HI if hindi else SENDER_NAME)
    if hindi:
        headline = f"{a.village_name_hi}: {LEVEL_HI[a.level]}"
        description = a.text_hi or hi.fallback_alert(a.level, a.village_name_hi, a.village_name)[0]
        instruction = f"{hi.SAFETY_HI[a.level]} {hi.CALL_112_HI}"
    else:
        headline = f"{LEVEL_EN[a.level]}: {a.village_name}" + (f" ({district})" if district else "")
        description = a.text_en or hi.fallback_alert(a.level, a.village_name_hi, a.village_name)[1]
        if a.reason_en:
            description += f" Why: {a.reason_en}"
        instruction = f"{hi.SAFETY_EN[a.level]} {hi.CALL_112_EN}"
    if is_exercise(a):
        headline = ("अभ्यास, असली चेतावनी नहीं — " if hindi else "EXERCISE, not a real warning — ") + headline
    _sub(info, "headline", headline)
    _sub(info, "description", description)
    _sub(info, "instruction", instruction)
    _sub(info, "web", f"{web_url}/village/{a.village_id}")
    _sub(info, "contact", "आपात स्थिति: 112" if hindi else "Emergency: 112")
    for name, value in _parameters(a, village):
        p = _sub(info, "parameter")
        _sub(p, "valueName", name)
        _sub(p, "value", value)
    area = _sub(info, "area")
    if village is not None:
        if hindi:
            _sub(area, "areaDesc", f"{village.name_hi} ({village.name}), {village.district}, {STATE_HI}")
        else:
            _sub(area, "areaDesc", f"{village.name}, {village.district}, {STATE}")
        _sub(area, "circle", f"{village.lat:.5f},{village.lon:.5f} {AREA_RADIUS_KM:g}")
    else:
        _sub(area, "areaDesc", f"{a.village_name}, {STATE}")


def render(a: Alert, village: Village | None, *, sender: str, web_url: str,
           previous: Alert | None = None) -> bytes:
    """One CAP 1.2 <alert> document (UTF-8 bytes) for a published alert."""
    if not is_published(a):
        raise ValueError(f"alert {a.id} is not published (status {a.status})")
    root = ET.Element(f"{{{CAP_NS}}}alert")
    _sub(root, "identifier", a.id)
    _sub(root, "sender", sender)
    _sub(root, "sent", cap_time(sent_at(a)))
    _sub(root, "status", "Exercise" if is_exercise(a) else "Actual")
    update = previous is not None and a.previous_level != "normal"
    _sub(root, "msgType", "Update" if update else "Alert")
    _sub(root, "scope", "Public")
    notes = []
    if a.replay or a.decision_trace.get("replay"):
        notes.append("Replay of archived forecast data through the live rules; not a current flood.")
    if a.decision_trace.get("drill"):
        notes.append("Drill: a labelled test alert started by hand; not a real flood.")
    notes.append("Demo deployment of Pukaar, not an official government channel.")
    _sub(root, "note", " ".join(notes))
    if update and previous is not None:
        _sub(root, "references", f"{sender},{previous.id},{cap_time(sent_at(previous))}")
    _info(root, a, village, "hi-IN", web_url)
    _info(root, a, village, "en-IN", web_url)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True, default_namespace=CAP_NS)


def atom(alerts: list[Alert], *, api_base: str, web_url: str, now: datetime | None = None) -> bytes:
    """ATOM 1.0 index: one entry per published alert, newest first, linking to its CAP XML."""
    published = sorted((a for a in alerts if is_published(a)), key=sent_at, reverse=True)[:FEED_SIZE]
    feed = ET.Element("feed", {"xmlns": ATOM_NS})  # Atom elements unqualified under a default xmlns
    self_url = f"{api_base}/cap/alerts.atom"
    _sub(feed, "id", self_url, ns="")
    _sub(feed, "title", "Pukaar CAP 1.2 flood alerts, Himachal Pradesh (demo)", ns="")
    _sub(feed, "subtitle", "Published village flood alerts (approved, auto-sent or failsafe). "
                           "Replays and drills carry CAP status Exercise.", ns="")
    updated = sent_at(published[0]) if published else clock.iso(now or clock.now())
    _sub(feed, "updated", clock.iso(clock.parse(updated)), ns="")
    author = _sub(feed, "author", ns="")
    _sub(author, "name", SENDER_NAME, ns="")
    ET.SubElement(feed, "link", rel="self", type="application/atom+xml", href=self_url)
    ET.SubElement(feed, "link", rel="alternate", type="text/html", href=f"{web_url}/how")
    for a in published:
        url = f"{api_base}/cap/alerts/{a.id}.xml"
        entry = _sub(feed, "entry", ns="")
        _sub(entry, "id", url, ns="")
        title = f"{LEVEL_EN[a.level]}: {a.village_name}"
        _sub(entry, "title", ("[Exercise] " if is_exercise(a) else "") + title, ns="")
        stamp = clock.iso(clock.parse(sent_at(a)))
        _sub(entry, "updated", stamp, ns="")
        _sub(entry, "published", stamp, ns="")
        _sub(entry, "summary", a.text_en or title, ns="")
        ET.SubElement(entry, "category", term=a.level)
        ET.SubElement(entry, "link", rel="alternate", type="application/cap+xml", href=url)
        ET.SubElement(entry, "link", rel="related", type="text/html",
                      href=f"{web_url}/village/{a.village_id}")
    ET.indent(feed)
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True)
