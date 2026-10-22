"""CAP 1.2 (Common Alerting Protocol) export of published alerts, and an ATOM index of them.

India's national alerting system (NDMA's SACHET) is built on CAP, as are Google
Public Alerts and most alert aggregators. Each alert that actually went out is
rendered as one CAP 1.2 <alert> with two <info> blocks (hi-IN, en-IN), a circle
around the village point and the district's LGD code. docs/SACHET.md maps it to
SACHET's profile; tests/test_cap_profile.py checks the Google Public Alerts rules.

What is published: alerts an officer approved, critical alerts auto-sent after
every officer timed out, and alerts the failsafe broadcast. Never pending,
declined, expired or drafting alerts. Plus one Cancel ("all clear") per village
that returned to normal while a published alert was still in force.

Choices (OASIS CAP 1.2, http://docs.oasis-open.org/emergency/cap/v1.2/):
- status: Actual for live alerts; Exercise for replays of archived floods and
  for drills (decision_trace.drill), which never describe a real flood now.
- msgType: Update when the village was already above normal and earlier alerts
  for it are still in force; <references> lists every one of them (Google's
  profile requires all unexpired related messages). Alert otherwise.
  Cancel when the village is back to normal: derived when the feed is built from
  the village's stored level and level_since, never written by the sweep. It
  references every published live alert for the village still in force then.
  It stays in the feed while the village stays normal; once the level rises
  again the village's state no longer says when it fell, so the Cancel is not
  rebuilt (aggregators that fetched it keep it; its identifier is stable).
  Replays get no Cancel: their level_since is archive time, not wall time.
- eventCode: OASIS Event Terms (OET v1.2): OET-079 flash flood when rain drove
  the level above the river and gauge readings, OET-081 flood otherwise.
- times: CAP forbids "Z"; times are written in IST (+05:30). sent and effective
  are the decision time (approval, auto-send) or, failing that, creation time.
- expires: effective + 12 hours. The sweep re-evaluates every 15 minutes and a
  new alert is raised if the level rises, so a 12-hour window covers one night.
- area: a 5 km circle around the village point (geocoded, not verified on the
  ground; a parameter says so), the LGD District Code SACHET uses, and an
  areaDesc of at most 50 characters in each language.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from Pukaar.core import clock
from Pukaar.store.models import Alert, Village, level_rank
from Pukaar.templates import hi

CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"
ATOM_NS = "http://www.w3.org/2005/Atom"
CAP_CONTENT_TYPE = "application/cap+xml; charset=utf-8"
ATOM_CONTENT_TYPE = "application/atom+xml; charset=utf-8"

IST = timezone(timedelta(hours=5, minutes=30))
EXPIRES_AFTER = timedelta(hours=12)
AREA_RADIUS_KM = 5.0
AREA_DESC_MAX = 50  # characters, in every language
FEED_SIZE = 50
SENDER_NAME = "Pukaar — District Disaster Management (demo)"
SENDER_NAME_HI = "पुकार — ज़िला आपदा प्रबंधन (डेमो)"
STATE = "Himachal Pradesh"
STATE_HI = "हिमाचल प्रदेश"

# OASIS Event Terms v1.2 (http://docs.oasis-open.org/emergency/etl/v1.0/).
OET_VALUE_NAME = "OET:v1.2"
OET_FLOOD = "OET-081"
OET_FLASH_FLOOD = "OET-079"

# Local Government Directory (lgdirectory.gov.in) district codes, the geocode SACHET's
# own CAP messages carry ("LGD District Code"). Checked against the LGD district list
# as mirrored by Google Data Commons (scripts/india_lgd) and the India Data Portal
# (district_lgd.csv): Himachal Pradesh is state 2, Hamirpur 17, Mandi 22. The same
# lists give Jaisalmer 103, which a live SACHET message for Jaisalmer carries.
LGD_DISTRICT_VALUE_NAME = "LGD District Code"
LGD_DISTRICT_CODES: dict[str, str] = {"Hamirpur": "17", "Mandi": "22"}
# LGD village codes, by village id. Empty: none of the five villages' codes could be
# verified from a public LGD extract, and an unverified code is worse than none.
LGD_VILLAGE_VALUE_NAME = "LGD Village Code"
LGD_VILLAGE_CODES: dict[str, str] = {}
DISTRICT_HI = {"Hamirpur": "हमीरपुर", "Mandi": "मंडी"}

# level -> (urgency, severity, certainty, responseType)
MAPPING: dict[str, tuple[str, str, str, str]] = {
    "watch": ("Expected", "Moderate", "Possible", "Monitor"),
    "warning": ("Expected", "Severe", "Likely", "Prepare"),
    "critical": ("Immediate", "Extreme", "Likely", "Evacuate"),
}
ALL_CLEAR_MAPPING = ("Past", "Minor", "Observed", "AllClear")
LEVEL_EN = {"watch": "Flood Watch", "warning": "Flood Warning", "critical": "Critical Flood Warning"}
LEVEL_HI = {"watch": "बाढ़ — सतर्क रहें", "warning": "बाढ़ की चेतावनी", "critical": "बाढ़ का गंभीर ख़तरा"}

ALL_CLEAR_PREFIX = "allclear-"

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


def _stream(a: Alert) -> str:
    """Alerts only ever reference alerts of the same stream: a drill never updates a replay or a live alert."""
    if a.decision_trace.get("drill"):
        return "drill"
    return "replay" if (a.replay or a.decision_trace.get("replay")) else "live"


def is_flash_flood(a: Alert) -> bool:
    """Rain drove the level above every river, gauge and staff-gauge reading: a flash flood (OET-079)."""
    t = a.decision_trace
    rain = level_rank(str(t.get("rain_level") or "normal"))
    water = max(level_rank(str(t.get(k) or "normal")) for k in ("river_level", "gauge_level", "staff_level"))
    return rain > 0 and rain > water


def event_code(a: Alert) -> str:
    return OET_FLASH_FLOOD if is_flash_flood(a) else OET_FLOOD


def event_name(a: Alert, hindi: bool = False) -> str:
    if hindi:
        return "अचानक बाढ़" if is_flash_flood(a) else "बाढ़"
    return "Flash Flood" if is_flash_flood(a) else "Flood"


def level_label(a: Alert, hindi: bool = False) -> str:
    if hindi:
        label = LEVEL_HI[a.level]
        return label.replace("बाढ़", "अचानक बाढ़", 1) if is_flash_flood(a) else label
    label = LEVEL_EN[a.level]
    return label.replace("Flood", "Flash Flood", 1) if is_flash_flood(a) else label


def cap_time(value: str | datetime) -> str:
    dt = clock.parse(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).isoformat(timespec="seconds")


def sent_at(a: Alert) -> str:
    return a.decided_at or a.created_at


def _sent(a: Alert) -> datetime:
    return clock.parse(sent_at(a))


def expires_at(a: Alert) -> datetime:
    return _sent(a) + EXPIRES_AFTER


def references(a: Alert, candidates: Iterable[Alert]) -> list[Alert]:
    """Every earlier published alert for the same village and event still in force when `a` was sent, oldest first.

    Empty when the village rose from normal: that starts a new event (msgType Alert),
    the earlier one having been closed by its Cancel. "Same event" is the village's
    flood hazard, flash or not: a flash-flood alert superseded by a river-flood
    alert must not stay active in an aggregator.
    """
    if a.previous_level == "normal":
        return []
    sent, created = _sent(a), clock.parse(a.created_at)
    found: dict[str, Alert] = {}
    for c in candidates:
        if c.id == a.id or c.village_id != a.village_id or not is_published(c) or _stream(c) != _stream(a):
            continue
        if clock.parse(c.created_at) >= created or _sent(c) > sent or expires_at(c) <= sent:
            continue
        found[c.id] = c
    return sorted(found.values(), key=_sent)


def reference(sender: str, a: Alert) -> str:
    return f"{sender},{a.id},{cap_time(sent_at(a))}"


@dataclass(frozen=True)
class AllClear:
    """A Cancel for a village back at normal: derived from stored state, never stored itself."""

    village: Village
    normal_since: str  # the village's level_since
    sent: datetime
    cancels: list[Alert] = field(default_factory=list)  # oldest first, all live and published

    @property
    def identifier(self) -> str:
        stamp = clock.parse(self.normal_since).astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{ALL_CLEAR_PREFIX}{self.village.id}-{stamp}"

    @property
    def latest(self) -> Alert:
        return self.cancels[-1]


def parse_all_clear_id(identifier: str) -> str | None:
    """The village id inside an all-clear identifier, or None if it is not one."""
    if not identifier.startswith(ALL_CLEAR_PREFIX):
        return None
    village_id, _, stamp = identifier[len(ALL_CLEAR_PREFIX):].rpartition("-")
    return village_id if village_id and len(stamp) == 14 and stamp.isdigit() else None


def all_clear(village: Village | None, candidates: Iterable[Alert]) -> AllClear | None:
    """The Cancel owed for this village, or None.

    Owed when the village is at normal now and at least one published live alert,
    created before it fell to normal, was still in force at that moment. Sent at
    the later of that moment and the newest such alert's own sent time, so no
    reference is ever postdated (an officer may approve after the level fell).
    """
    if village is None or village.level != "normal" or not village.level_since or village.replay:
        return None
    since = clock.parse(village.level_since)
    found: dict[str, Alert] = {}
    for c in candidates:
        if c.village_id != village.id or not is_published(c) or _stream(c) != "live":
            continue
        if clock.parse(c.created_at) > since or expires_at(c) <= since:
            continue
        found[c.id] = c
    if not found:
        return None
    cancels = sorted(found.values(), key=_sent)
    return AllClear(village=village, normal_since=village.level_since,
                    sent=max([since, *(_sent(c) for c in cancels)]), cancels=cancels)


def _sub(parent: ET.Element, tag: str, text: str | None = None, ns: str = CAP_NS) -> ET.Element:
    el = ET.SubElement(parent, f"{{{ns}}}{tag}" if ns else tag)
    if text is not None:
        el.text = text
    return el


def _fit(options: list[str]) -> str:
    for o in options:
        if len(o) <= AREA_DESC_MAX:
            return o
    return options[-1][:AREA_DESC_MAX]


def area_desc(village: Village | None, name: str, name_hi: str, hindi: bool) -> str:
    """At most 50 characters (SACHET's areaDesc limit), shortening the state, then the district."""
    district = village.district if village else ""
    if hindi:
        d = DISTRICT_HI.get(district, district)
        options = [f"{name_hi}, {d}, {STATE_HI}", f"{name_hi}, {d}, हि.प्र.", f"{name_hi}, {d}"] if d \
            else [f"{name_hi}, {STATE_HI}"]
        return _fit([*options, name_hi])
    options = [f"{name}, {district}, {STATE}", f"{name}, {district}, HP", f"{name}, {district}"] if district \
        else [f"{name}, {STATE}"]
    return _fit([*options, name])


def _area(info: ET.Element, village: Village | None, name: str, name_hi: str, hindi: bool) -> None:
    area = _sub(info, "area")
    _sub(area, "areaDesc", area_desc(village, name, name_hi, hindi))
    if village is None:
        return
    _sub(area, "circle", f"{village.lat:.5f},{village.lon:.5f} {AREA_RADIUS_KM:g}")
    codes = [(LGD_DISTRICT_VALUE_NAME, LGD_DISTRICT_CODES.get(village.district)),
             (LGD_VILLAGE_VALUE_NAME, LGD_VILLAGE_CODES.get(village.id))]
    for value_name, value in codes:
        if value:
            g = _sub(area, "geocode")
            _sub(g, "valueName", value_name)
            _sub(g, "value", value)


def _params(info: ET.Element, params: list[tuple[str, str]]) -> None:
    for name, value in params:
        p = _sub(info, "parameter")
        _sub(p, "valueName", name)
        _sub(p, "value", value)


def _event_code(info: ET.Element, code: str) -> None:
    ec = _sub(info, "eventCode")
    _sub(ec, "valueName", OET_VALUE_NAME)
    _sub(ec, "value", code)


def _approval(a: Alert) -> str:
    if a.status == "auto_sent_unapproved":
        return "auto-sent: no officer answered in time at critical; fixed template, unapproved"
    if a.status == "failsafe":
        return "failsafe: workflow error; fixed template sent"
    return "approved by a duty officer"


def _coords(village: Village) -> list[tuple[str, str]]:
    return [("coordinates", "verified" if village.coords_verified
             else "approximate: geocoded (GeoNames via Open-Meteo), not verified on the ground"),
            ("area_radius_km", f"{AREA_RADIUS_KM:g}")]


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
        params += _coords(village)
    if a.replay or a.decision_trace.get("replay"):
        params.append(("exercise", "replay of archived data; not a current flood"))
    if a.decision_trace.get("drill"):
        params.append(("exercise", "drill: a test alert started by hand; not a real flood"))
    return params


def _info(alert_el: ET.Element, a: Alert, village: Village | None, lang: str, web_url: str) -> None:
    urgency, severity, certainty, response = MAPPING[a.level]
    effective = _sent(a)
    hindi = lang == "hi-IN"
    district = village.district if village else ""
    info = _sub(alert_el, "info")
    _sub(info, "language", lang)
    _sub(info, "category", "Met")
    _sub(info, "event", event_name(a, hindi))
    _sub(info, "responseType", response)
    _sub(info, "urgency", urgency)
    _sub(info, "severity", severity)
    _sub(info, "certainty", certainty)
    _event_code(info, event_code(a))
    _sub(info, "effective", cap_time(effective))
    _sub(info, "expires", cap_time(effective + EXPIRES_AFTER))
    _sub(info, "senderName", SENDER_NAME_HI if hindi else SENDER_NAME)
    if hindi:
        headline = f"{a.village_name_hi}: {level_label(a, True)}"
        description = a.text_hi or hi.fallback_alert(a.level, a.village_name_hi, a.village_name)[0]
        instruction = f"{hi.SAFETY_HI[a.level]} {hi.CALL_112_HI}"
    else:
        headline = f"{level_label(a)}: {a.village_name}" + (f" ({district})" if district else "")
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
    _params(info, _parameters(a, village))
    if village is not None:
        _area(info, village, village.name, village.name_hi, hindi)
    else:
        _area(info, None, a.village_name, a.village_name_hi, hindi)


def _document(root: ET.Element) -> bytes:
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True, default_namespace=CAP_NS)


def render(a: Alert, village: Village | None, *, sender: str, web_url: str,
           refs: Sequence[Alert] = ()) -> bytes:
    """One CAP 1.2 <alert> document (UTF-8 bytes) for a published alert.

    refs: what references(a, ...) returned. Non-empty makes it an Update.
    """
    if not is_published(a):
        raise ValueError(f"alert {a.id} is not published (status {a.status})")
    root = ET.Element(f"{{{CAP_NS}}}alert")
    _sub(root, "identifier", a.id)
    _sub(root, "sender", sender)
    _sub(root, "sent", cap_time(sent_at(a)))
    _sub(root, "status", "Exercise" if is_exercise(a) else "Actual")
    _sub(root, "msgType", "Update" if refs else "Alert")
    _sub(root, "scope", "Public")
    notes = []
    if a.replay or a.decision_trace.get("replay"):
        notes.append("Replay of archived forecast data through the live rules; not a current flood.")
    if a.decision_trace.get("drill"):
        notes.append("Drill: a labelled test alert started by hand; not a real flood.")
    notes.append("Demo deployment of Pukaar, not an official government channel.")
    _sub(root, "note", " ".join(notes))
    if refs:
        _sub(root, "references", " ".join(reference(sender, r) for r in refs))
    _info(root, a, village, "hi-IN", web_url)
    _info(root, a, village, "en-IN", web_url)
    return _document(root)


def _ist_text(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%d.%m.%Y, %H:%M IST")


def all_clear_text(c: AllClear, hindi: bool) -> tuple[str, str, str]:
    """(headline, description, instruction) for the all-clear."""
    v, since = c.village, _ist_text(clock.parse(c.normal_since))
    n = len(c.cancels)
    if hindi:
        return (
            f"{v.name_hi}: ख़तरा टल गया, बाढ़ की चेतावनी रद्द",
            f"पुकार के आकलन में {v.name_hi} का बाढ़ स्तर {since} से फिर सामान्य है। "
            f"गाँव के लिए पहले जारी {'चेतावनी' if n == 1 else f'{n} चेतावनियाँ'} अब लागू नहीं "
            f"{'है' if n == 1 else 'हैं'}।",
            "फिर भी उफनते नदी-नालों और कच्ची ढलानों से दूर रहें, और नदी किनारे के घर या खेत लौटने से पहले "
            f"स्थानीय प्रशासन की सलाह मानें। {hi.CALL_112_HI}",
        )
    district = f" ({v.district})" if v.district else ""
    return (
        f"All clear: {v.name}{district} is back to normal, flood alert cancelled",
        f"Pukaar's flood level for {v.name} has been back to normal since {since}. "
        f"{'The earlier alert' if n == 1 else f'All {n} earlier alerts'} for the village "
        f"(latest: {level_label(c.latest)}) {'is' if n == 1 else 'are'} cancelled.",
        "Still keep away from swollen streams and loose slopes, and follow local officials before going back to "
        f"riverside homes or fields. {hi.CALL_112_EN}",
    )


def _all_clear_info(alert_el: ET.Element, c: AllClear, lang: str, web_url: str) -> None:
    urgency, severity, certainty, response = ALL_CLEAR_MAPPING
    hindi = lang == "hi-IN"
    v, latest = c.village, c.latest
    info = _sub(alert_el, "info")
    _sub(info, "language", lang)
    _sub(info, "category", "Met")
    _sub(info, "event", event_name(latest, hindi))
    _sub(info, "responseType", response)
    _sub(info, "urgency", urgency)
    _sub(info, "severity", severity)
    _sub(info, "certainty", certainty)
    _event_code(info, event_code(latest))
    _sub(info, "effective", cap_time(c.sent))
    _sub(info, "expires", cap_time(c.sent + EXPIRES_AFTER))
    _sub(info, "senderName", SENDER_NAME_HI if hindi else SENDER_NAME)
    headline, description, instruction = all_clear_text(c, hindi)
    _sub(info, "headline", headline)
    _sub(info, "description", description)
    _sub(info, "instruction", instruction)
    _sub(info, "web", f"{web_url}/village/{v.id}")
    _sub(info, "contact", "आपात स्थिति: 112" if hindi else "Emergency: 112")
    _params(info, [("level", "normal"), ("previous_level", latest.level),
                   ("normal_since", cap_time(c.normal_since)), ("cancels", str(len(c.cancels))),
                   ("basis", "village level back to normal at a scheduled sweep (after the calm-sweep hysteresis)"),
                   *_coords(v)])
    _area(info, v, v.name, v.name_hi, hindi)


def render_all_clear(c: AllClear, *, sender: str, web_url: str) -> bytes:
    """The Cancel <alert> for a village back at normal, referencing every alert it cancels."""
    root = ET.Element(f"{{{CAP_NS}}}alert")
    _sub(root, "identifier", c.identifier)
    _sub(root, "sender", sender)
    _sub(root, "sent", cap_time(c.sent))
    _sub(root, "status", "Actual")
    _sub(root, "msgType", "Cancel")
    _sub(root, "scope", "Public")
    _sub(root, "note", "All clear: the village level is back to normal. "
                       "Demo deployment of Pukaar, not an official government channel.")
    _sub(root, "references", " ".join(reference(sender, r) for r in c.cancels))
    _all_clear_info(root, c, "hi-IN", web_url)
    _all_clear_info(root, c, "en-IN", web_url)
    return _document(root)


def atom(alerts: list[Alert], *, api_base: str, web_url: str, now: datetime | None = None,
         all_clears: Sequence[AllClear] = ()) -> bytes:
    """ATOM 1.0 index: one entry per published alert and per all-clear, newest first, linking to its CAP XML."""
    rows: list[tuple[datetime, str, str, str, str, str]] = []  # sent, id, title, summary, term, village
    seen: set[str] = set()
    for a in alerts:
        if not is_published(a) or a.id in seen:
            continue
        seen.add(a.id)
        title = f"{level_label(a)}: {a.village_name}"
        rows.append((_sent(a), a.id, ("[Exercise] " if is_exercise(a) else "") + title,
                     a.text_en or title, a.level, a.village_id))
    for c in all_clears:
        if c.identifier in seen:
            continue
        seen.add(c.identifier)
        headline, description, _ = all_clear_text(c, hindi=False)
        rows.append((c.sent, c.identifier, headline, description, "all_clear", c.village.id))
    rows = sorted(rows, key=lambda r: r[0], reverse=True)[:FEED_SIZE]

    feed = ET.Element("feed", {"xmlns": ATOM_NS})  # Atom elements unqualified under a default xmlns
    self_url = f"{api_base}/cap/alerts.atom"
    _sub(feed, "id", self_url, ns="")
    _sub(feed, "title", "Pukaar CAP 1.2 flood alerts, Himachal Pradesh (demo)", ns="")
    _sub(feed, "subtitle", "Published village flood alerts (approved, auto-sent or failsafe) and all-clear "
                           "cancellations. Replays and drills carry CAP status Exercise.", ns="")
    updated = rows[0][0] if rows else (now or clock.now())
    _sub(feed, "updated", clock.iso(updated), ns="")
    author = _sub(feed, "author", ns="")
    _sub(author, "name", SENDER_NAME, ns="")
    ET.SubElement(feed, "link", rel="self", type="application/atom+xml", href=self_url)
    ET.SubElement(feed, "link", rel="alternate", type="text/html", href=f"{web_url}/how")
    for sent, ident, title, summary, term, village_id in rows:
        url = f"{api_base}/cap/alerts/{ident}.xml"
        entry = _sub(feed, "entry", ns="")
        _sub(entry, "id", url, ns="")
        _sub(entry, "title", title, ns="")
        stamp = clock.iso(sent)
        _sub(entry, "updated", stamp, ns="")
        _sub(entry, "published", stamp, ns="")
        _sub(entry, "summary", summary, ns="")
        ET.SubElement(entry, "category", term=term)
        ET.SubElement(entry, "link", rel="alternate", type="application/cap+xml", href=url)
        ET.SubElement(entry, "link", rel="related", type="text/html", href=f"{web_url}/village/{village_id}")
    ET.indent(feed)
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True)
