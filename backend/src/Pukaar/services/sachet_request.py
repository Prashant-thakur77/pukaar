"""SACHET out: the "Request SACHET / cell broadcast" package an officer sends to HPSDMA.

Only an issuing agency or the SDMA can issue on SACHET or cell broadcast (C-DOT's CBS, nationwide since
2 May 2026); a district, and so Pukaar, cannot. What Pukaar can do is decide when to ask, and make the
asking fast: for an approved (published) Warning or Critical alert it builds

  - a CAP 1.2 message for the SACHET operator: scope Restricted (a request, not an issued alert), the
    village as a polygon (a circle of radius_km drawn as POLYGON_POINTS points, closed), the same circle,
    the LGD district code, and Hindi and English blocks;
  - the cell-broadcast text in Hindi and English, each within CB_TARGET_PAGES pages of a CBS message
    (3GPP TS 23.041: a page is 82 octets, 93 GSM 7-bit characters or 41 UCS-2 characters; Hindi is UCS-2),
    so it also fits SACHET's SMS and app;
  - the steps: call the HPSDMA State Emergency Operation Centre (1070), e-mail the file, wait for HPSDMA
    to authorise and issue, and send the cancel the same way when the village is back to normal.

The officer downloads, copies or e-mails it. Every preparation is in the audit trail and on the alert's
timeline ("prepared for HPSDMA; not sent by Pukaar"). Pukaar never sends a broadcast and never says it did.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.services import cap
from Pukaar.store.models import Alert, AuditRow, Village
from Pukaar.store.repo import Repo
from Pukaar.templates import hi

LEVELS = ("warning", "critical")
POLYGON_POINTS = 16
CBS_PAGE_OCTETS = 82
GSM7_PER_PAGE = 93
UCS2_PER_PAGE = 41
CB_MAX_PAGES = 15
CB_TARGET_PAGES = 4
SEOC_PHONE = "1070"  # the state emergency operation centre's toll-free number in Himachal Pradesh
DEOC_PHONE = "1077"
NOT_SENT_EN = "Prepared for HPSDMA. Pukaar has not sent a broadcast and cannot: only HPSDMA can issue it."
NOT_SENT_HI = "HPSDMA के लिए तैयार। पुकार ने कोई ब्रॉडकास्ट नहीं भेजा और भेज नहीं सकता: इसे केवल HPSDMA जारी कर सकता है।"
VIA = ("view", "download", "copy", "email")

# The GSM 03.38 basic character set (7-bit); anything else makes a message UCS-2.
_GSM7 = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
            "¿abcdefghijklmnopqrstuvwxyzäöñüà")
_GSM7_EXT = set("^{}\\[~]|€")


class NotRequestable(ValueError):
    """The alert cannot be sent to HPSDMA (not published, or below Warning); the message says why."""


def is_gsm7(text: str) -> bool:
    return all(c in _GSM7 or c in _GSM7_EXT for c in text)


def cb_pages(text: str) -> int:
    """CBS pages the text needs: GSM 7-bit when every character is in the GSM set, else UCS-2."""
    if is_gsm7(text):
        units = sum(2 if c in _GSM7_EXT else 1 for c in text)
        return max(1, math.ceil(units / GSM7_PER_PAGE))
    return max(1, math.ceil(len(text) / UCS2_PER_PAGE))


def cb_limit(text: str) -> int:
    """Characters allowed in CB_TARGET_PAGES pages for this text's encoding."""
    return CB_TARGET_PAGES * (GSM7_PER_PAGE if is_gsm7(text) else UCS2_PER_PAGE)


def _ascii(text: str) -> str:
    """English for a GSM 7-bit page: plain quotes and dashes, nothing outside the GSM set."""
    text = (text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
            .replace("—", "-").replace("–", "-").replace("…", "..."))
    return "".join(c if (c in _GSM7 or c in _GSM7_EXT) else " " for c in text)


def _fit(options: list[str]) -> str:
    for o in options:
        o = re.sub(r"\s+", " ", o).strip()
        if cb_pages(o) <= CB_TARGET_PAGES:
            return o
    last = re.sub(r"\s+", " ", options[-1]).strip()
    return last[: cb_limit(last)]


ACTION_EN = {
    "warning": ["Keep away from streams and slopes; be ready to move to high, safe ground.",
                "Keep away from streams; be ready to move to high ground."],
    "critical": ["Move now to high, safe ground away from streams and slopes. Do not cross bridges or streams.",
                 "Move now to high ground. Do not cross streams."],
}
ACTION_HI = {
    "warning": ["नदी-नालों से दूर रहें, ऊँची जगह जाने को तैयार रहें।", "नदी-नालों से दूर रहें।"],
    "critical": ["तुरंत ऊँची सुरक्षित जगह जाएँ, नाले पार न करें।", "तुरंत ऊँची जगह जाएँ।"],
}
LEVEL_EN = {"warning": "warning", "critical": "SEVERE danger"}
LEVEL_HI = {"warning": "की चेतावनी", "critical": "का गंभीर ख़तरा"}


def cb_text(a: Alert, village: Village | None, sender_en: str, sender_hi: str) -> tuple[str, str]:
    """(Hindi, English) cell-broadcast text: source, hazard, place, action, 112 (the NIST elements), each
    within CB_TARGET_PAGES pages. Drills and replays say EXERCISE first."""
    district = village.district if village else ""
    district_hi = cap.district_hi(village) if village else ""
    hazard_en = "Flash flood" if cap.is_flash_flood(a) else "Flood"
    hazard_hi = "अचानक बाढ़" if cap.is_flash_flood(a) else "बाढ़"
    ex_en = "EXERCISE, not real. " if cap.is_exercise(a) else ""
    ex_hi = "अभ्यास, असली नहीं। " if cap.is_exercise(a) else ""
    place_en = f"{a.village_name} ({district})" if district else a.village_name
    place_hi = f"{a.village_name_hi} ({district_hi})" if district_hi else a.village_name_hi
    en = _fit([_ascii(o) for o in [f"{ex_en}{sender_en}: {hazard_en} {LEVEL_EN[a.level]} for {place_en}. {act} Emergency: 112."
               for act in ACTION_EN[a.level]]
              + [f"{ex_en}{hazard_en} {LEVEL_EN[a.level]}: {a.village_name}. {ACTION_EN[a.level][-1]} Call 112."]])
    text_hi = _fit([f"{ex_hi}{sender_hi}: {place_hi} में {hazard_hi} {LEVEL_HI[a.level]}। {act} आपात: 112"
               for act in ACTION_HI[a.level]]
              + [f"{ex_hi}{a.village_name_hi} में {hazard_hi} {LEVEL_HI[a.level]}। {ACTION_HI[a.level][-1]} 112"])
    return text_hi, en


def polygon(lat: float, lon: float, radius_km: float, points: int = POLYGON_POINTS) -> list[tuple[float, float]]:
    """A circle as a closed CAP polygon (first point repeated last), lat/lon in WGS 84."""
    out = []
    for i in range(points):
        t = 2 * math.pi * i / points
        dlat = radius_km / 111.2 * math.cos(t)
        dlon = radius_km / (111.2 * math.cos(math.radians(lat))) * math.sin(t)
        out.append((round(lat + dlat, 5), round(lon + dlon, 5)))
    return out + [out[0]]


def polygon_text(poly: list[tuple[float, float]]) -> str:
    return " ".join(f"{la:.5f},{lo:.5f}" for la, lo in poly)


@dataclass
class Package:
    alert_id: str
    identifier: str
    cap_xml: str
    text_hi: str
    text_en: str
    radius_km: float
    polygon: list[tuple[float, float]]
    steps_en: list[str]
    steps_hi: list[str]
    mailto: str
    email_to: str
    filename: str
    exercise: bool

    def view(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id, "identifier": self.identifier, "cap_xml": self.cap_xml,
            "filename": self.filename, "text_hi": self.text_hi, "text_en": self.text_en,
            "limits": {
                "hi": {"chars": len(self.text_hi), "pages": cb_pages(self.text_hi), "encoding": "UCS-2",
                       "max_chars": cb_limit(self.text_hi)},
                "en": {"chars": len(self.text_en), "pages": cb_pages(self.text_en),
                       "encoding": "GSM 7-bit" if is_gsm7(self.text_en) else "UCS-2",
                       "max_chars": cb_limit(self.text_en)},
                "target_pages": CB_TARGET_PAGES, "max_pages": CB_MAX_PAGES,
                "page": f"{CBS_PAGE_OCTETS} octets: {GSM7_PER_PAGE} GSM 7-bit or {UCS2_PER_PAGE} UCS-2 characters",
            },
            "radius_km": self.radius_km, "polygon": [list(p) for p in self.polygon],
            "steps_en": self.steps_en, "steps_hi": self.steps_hi, "mailto": self.mailto, "email_to": self.email_to,
            "exercise": self.exercise, "not_sent_en": NOT_SENT_EN, "not_sent_hi": NOT_SENT_HI,
        }


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, f"{{{cap.CAP_NS}}}{tag}")
    if text is not None:
        el.text = text
    return el


def _info(root: ET.Element, a: Alert, village: Village, lang: str, text: str, full: str, sender_name: str,
          poly: list[tuple[float, float]], radius_km: float) -> None:
    urgency, severity, _, response = cap.MAPPING[a.level]
    hindi = lang == "hi-IN"
    now = clock.now()
    info = _sub(root, "info")
    _sub(info, "language", lang)
    _sub(info, "category", "Met")
    _sub(info, "event", cap.event_name(a, hindi))
    _sub(info, "responseType", response)
    _sub(info, "urgency", urgency)
    _sub(info, "severity", severity)
    _sub(info, "certainty", cap.alert_certainty(a))
    ec = _sub(info, "eventCode")
    _sub(ec, "valueName", cap.OET_VALUE_NAME)
    _sub(ec, "value", cap.event_code(a))
    _sub(info, "effective", cap.cap_time(now))
    _sub(info, "expires", cap.cap_time(now + cap.EXPIRES_AFTER))
    _sub(info, "senderName", sender_name)
    _sub(info, "headline", text)
    _sub(info, "description", full or text)
    _sub(info, "instruction", (hi.SAFETY_HI if hindi else hi.SAFETY_EN)[a.level])
    _sub(info, "contact", "आपात स्थिति: 112" if hindi else "Emergency: 112")
    for name, value in (("PukaarAlertId", a.id), ("PukaarRequest", "request to HPSDMA; not issued by Pukaar"),
                        ("CellBroadcastText", text), ("area_radius_km", f"{radius_km:g}")):
        p = _sub(info, "parameter")
        _sub(p, "valueName", name)
        _sub(p, "value", value)
    area = _sub(info, "area")
    _sub(area, "areaDesc", cap.area_desc(village, village.name, village.name_hi, hindi))
    _sub(area, "polygon", polygon_text(poly))
    _sub(area, "circle", f"{village.lat:.5f},{village.lon:.5f} {radius_km:g}")
    district_code, village_code = cap.lgd_codes(village)
    for value_name, value in ((cap.LGD_DISTRICT_VALUE_NAME, district_code), (cap.LGD_VILLAGE_VALUE_NAME, village_code)):
        if value:
            g = _sub(area, "geocode")
            _sub(g, "valueName", value_name)
            _sub(g, "value", value)


def build(a: Alert, village: Village | None, radius_km: float | None = None) -> Package:
    if a.level not in LEVELS:
        raise NotRequestable("only a Warning or Critical alert is sent to HPSDMA for SACHET or cell broadcast")
    if not cap.is_published(a):
        raise NotRequestable(f"the alert is {a.status}: only an approved (published) alert can be sent to HPSDMA")
    if village is None:
        raise NotRequestable("the village of this alert is unknown")
    s = get_settings()
    radius = max(0.5, min(25.0, float(radius_km if radius_km is not None else s.sachet_request_radius_km)))
    names = cap.sender_names(s.cap_sender_name, s.cap_sender_name_hi)
    district_hi = cap.district_hi(village)
    sender_en = f"DDMA {village.district}" if village.district else names[0]
    sender_hi = f"जिला आपदा प्रबंधन {district_hi}" if district_hi else names[1]
    text_hi, text_en = cb_text(a, village, sender_en, sender_hi)
    poly = polygon(village.lat, village.lon, radius)
    exercise = cap.is_exercise(a)
    identifier = f"{a.id}-sachet-request"
    root = ET.Element(f"{{{cap.CAP_NS}}}alert")
    _sub(root, "identifier", identifier)
    _sub(root, "sender", s.cap_sender)
    _sub(root, "sent", cap.cap_time(clock.now()))
    _sub(root, "status", "Exercise" if exercise else "Actual")
    _sub(root, "msgType", "Alert")
    _sub(root, "scope", "Restricted")
    _sub(root, "restriction", "For HPSDMA's SACHET and cell-broadcast operator: a district's request to issue. "
                              "Not issued by Pukaar.")
    notes = [f"Request from DDMA {village.district} via Pukaar, approved alert {a.id}, "
             f"{'approved by a duty officer' if a.approved else a.status}.", NOT_SENT_EN]
    if exercise:
        notes.insert(0, "EXERCISE: a replay or drill; never issue it to the public.")
    if cap.is_demo_sender(s.cap_sender_name):
        notes.append(cap.DEMO_NOTE)
    _sub(root, "note", " ".join(notes))
    _info(root, a, village, "hi-IN", text_hi, a.text_hi, names[1], poly, radius)
    _info(root, a, village, "en-IN", text_en, a.text_en, names[0], poly, radius)
    xml = cap._document(root).decode("utf-8")
    email_to = s.sachet_request_email
    subject = (f"{'[EXERCISE] ' if exercise else ''}SACHET / cell broadcast request: {cap.level_label(a)}, "
               f"{a.village_name} ({village.district})")
    steps_en = [
        f"Call the HPSDMA State Emergency Operation Centre ({SEOC_PHONE}) now: say a {cap.level_label(a)} for "
        f"{a.village_name}, {village.district} needs SACHET and cell broadcast, and that the request is coming by e-mail.",
        f"E-mail the CAP file ({identifier}.xml) and the two texts below to HPSDMA"
        + (f" ({email_to})." if email_to else " (the address the DDMA agreed with HPSDMA)."),
        f"HPSDMA authorises and issues it on SACHET and cell broadcast for the {radius:g} km polygon. "
        "Pukaar does not send it and does not know when it goes out: ask HPSDMA to confirm.",
        "Keep calling the people who did not confirm: cell broadcast does not tell you who heard.",
        "When the village is back to normal, send HPSDMA the cancel (all clear) the same way.",
    ]
    steps_hi = [
        f"अभी HPSDMA के राज्य आपातकालीन संचालन केंद्र ({SEOC_PHONE}) को फ़ोन करें: बताएँ कि {a.village_name_hi}, "
        f"{district_hi} के लिए SACHET और सेल ब्रॉडकास्ट चाहिए और अनुरोध ई-मेल से आ रहा है।",
        f"CAP फ़ाइल ({identifier}.xml) और नीचे के दोनों संदेश HPSDMA को ई-मेल करें"
        + (f" ({email_to})।" if email_to else " (DDMA और HPSDMA के बीच तय पते पर)।"),
        f"HPSDMA इसे {radius:g} किमी के क्षेत्र के लिए SACHET और सेल ब्रॉडकास्ट पर जारी करता है। पुकार इसे नहीं भेजता; "
        "HPSDMA से पुष्टि लें।",
        "जिन्होंने पुष्टि नहीं की, उन्हें कॉल करते रहें: सेल ब्रॉडकास्ट नहीं बताता कि किसने सुना।",
        "गाँव सामान्य होने पर रद्द करने (सब ठीक) का संदेश भी इसी तरह भेजें।",
    ]
    body = "\n\n".join([
        f"Hindi (cell broadcast, {cb_pages(text_hi)} page(s)):\n{text_hi}",
        f"English (cell broadcast, {cb_pages(text_en)} page(s)):\n{text_en}",
        f"Area: a {radius:g} km polygon around {village.lat:.5f}, {village.lon:.5f} ({a.village_name}, "
        f"{village.district}); the CAP file has it.",
        "Steps:\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(steps_en, 1)),
        f"Attach {identifier}.xml (downloaded from the Pukaar console).",
        NOT_SENT_EN,
    ])
    mailto = f"mailto:{quote(email_to)}?subject={quote(subject)}&body={quote(body)}"
    return Package(a.id, identifier, xml, text_hi, text_en, radius, poly, steps_en, steps_hi, mailto, email_to,
                   f"{identifier}.xml", exercise)


def prepare(repo: Repo, a: Alert, actor: str, actor_role: str, radius_km: float | None = None,
            via: str = "view") -> Package:
    """Build the package and record it: one audit row and a timeline entry. Never sends anything."""
    if a.decision_trace.get("demo"):
        raise NotRequestable("the live jury demo's practice alert is never sent to SACHET")
    village = repo.get_village(a.village_id)
    pkg = build(a, village, radius_km)
    via = via if via in VIA else "view"
    now = clock.iso(clock.now())
    repo.append_audit(AuditRow(at=now, id=new_id("aud"), actor=actor, role=actor_role,
                               action="sachet_request_prepared", resource=f"alert:{a.id}", decision="allow",
                               reason=f"{pkg.identifier} for HPSDMA, {pkg.radius_km:g} km polygon, via {via}; "
                                      "not sent by Pukaar"))
    repo.add_timeline(a.id, "sachet_request", f"SACHET / cell broadcast request prepared for HPSDMA by {actor} "
                                              f"({via}); not sent by Pukaar")
    return pkg
