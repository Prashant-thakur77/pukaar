"""Turn a villager's words into a typed report.

A keyword parser (Hindi in Devanagari and Roman script, plus English) always
runs. When the model is available its typed output is merged in, and the more
severe reading wins. Keyword lists need native-speaker review.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Protocol

from Pukaar.templates import hi

SEVERITY_ORDER = ("low", "medium", "high", "critical")
TYPE_PRIORITY = ("people_trapped", "homes_affected", "landslide", "bridge_unsafe", "road_cut", "water_rising", "other")

KEYWORDS: dict[str, tuple[str, ...]] = {
    "people_trapped": (
        "फँसे", "फंसे", "फँस गए", "फंस गए", "बचाओ", "बचाओ", "मदद करो", "दब गए", "लापता",
        "phanse", "fanse", "phas gaye", "bachao", "madad", "dab gaye", "lapata", "trapped", "missing", "help",
    ),
    "homes_affected": (
        "घर में पानी", "घरों में पानी", "मकान गिर", "घर बह", "मकान बह", "घर टूट", "गौशाला बह",
        "ghar mein pani", "ghar me pani", "makan gir", "ghar beh", "makaan", "house", "homes", "flooded house",
    ),
    "landslide": (
        "भूस्खलन", "पहाड़ गिर", "पहाड़ी गिर", "मलबा", "ढांक गिर", "ढाँक", "चट्टान", "पत्थर गिर", "बादल फटा",
        "bhuskhalan", "pahad gir", "pahadi gir", "malba", "dhank", "chattan", "patthar gir", "badal phata",
        "badal fata", "landslide", "debris", "cloudburst",
    ),
    "bridge_unsafe": (
        "पुल टूट", "पुल बह", "पुल पर पानी", "पुलिया", "पुल खतरनाक", "पुल ख़तरनाक",
        "pul toot", "pul tut", "pul beh", "pul par pani", "puliya", "bridge",
    ),
    "road_cut": (
        "सड़क बंद", "सड़क टूट", "सड़क बह", "रास्ता बंद", "रास्ता टूट", "रोड बंद", "मार्ग अवरुद्ध",
        "sadak band", "sadak toot", "sadak tut", "rasta band", "raasta band", "road band", "road cut", "road blocked",
    ),
    "water_rising": (
        "पानी बढ़", "पानी चढ़", "बढ़ रहा", "बढ़ रही", "चढ़ रहा", "नाले", "नाला", "नदी", "नाला उफान", "नाले में उफान", "खड्ड", "नदी उफान", "बाढ़", "पानी तेज़", "उफान",
        "pani badh", "paani badh", "pani chadh", "nala", "naala", "khad", "khadd", "nadi", "badh", "baadh", "ufaan",
        "water rising", "flood", "river rising",
    ),
}
CRITICAL_WORDS = (
    "बचाओ", "फँसे", "फंसे", "दब गए", "बह गया", "बह गए", "लापता", "बादल फटा", "जान",
    "bachao", "phanse", "fanse", "dab gaye", "beh gaya", "beh gaye", "lapata", "badal phata", "badal fata",
    "trapped", "swept away", "missing",
)
HIGH_WORDS = (
    "बहुत", "तेज़", "तेज", "ख़तरा", "खतरा", "तुरंत", "टूट", "गिर गया", "गिर रहा", "बह गया", "बह रहा",
    "bahut", "tez", "khatra", "turant", "toot", "tut gaya", "gir gaya", "gir raha", "beh gaya", "beh raha",
    "danger", "fast", "very",
)
LOW_WORDS = ("सामान्य", "ठीक", "कम", "samanya", "theek", "thik", "kam", "normal", "fine")


@dataclass
class StructuredReport:
    report_type: str
    severity: str
    summary_en: str
    reply_hi: str
    parser_source: str
    rules: list[str] = field(default_factory=list)


class ReportModel(Protocol):
    def structure_report(self, text: str, village_name: str) -> dict | None: ...


def _norm(text: str) -> str:
    # NFC folds the two encodings of nukta letters (ज़ / ज + ़) into one.
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).strip().lower())


def _has(text: str, words: tuple[str, ...]) -> list[str]:
    return [w for w in words if _norm(w) in text]


def keyword_parse(text: str, has_photo: bool = False) -> StructuredReport:
    t = _norm(text)
    rules: list[str] = []
    found = [k for k in TYPE_PRIORITY[:-1] if _has(t, KEYWORDS[k])]
    report_type = found[0] if found else "other"
    for k in found:
        rules.append(f"kw:{k}")

    if _has(t, CRITICAL_WORDS) or report_type == "people_trapped":
        severity = "critical"
    elif report_type in {"homes_affected", "landslide", "bridge_unsafe"} or _has(t, HIGH_WORDS):
        severity = "high"
    elif report_type in {"road_cut", "water_rising"}:
        severity = "medium"
    elif _has(t, LOW_WORDS) or not t:
        severity = "low"
    else:
        severity = "medium" if has_photo else "low"
    rules.append(f"severity:{severity}")

    summary = f"{report_type.replace('_', ' ')} ({severity}) reported" if t else "photo or voice report without text"
    return StructuredReport(report_type, severity, summary, _reply(severity), "rules", rules)


def _reply(severity: str) -> str:
    return hi.REPORT_URGENT_HI if severity in {"high", "critical"} else hi.REPORT_THANKS_HI


def _rank(sev: str) -> int:
    return SEVERITY_ORDER.index(sev) if sev in SEVERITY_ORDER else 0


def structure(text: str, village_name: str, model: ReportModel | None, has_photo: bool = False) -> StructuredReport:
    rules = keyword_parse(text, has_photo)
    if model is None or not text.strip():
        return rules
    payload = model.structure_report(text, village_name)
    if not payload:
        rules.rules.append("model_unavailable")
        return rules
    m_type = payload.get("report_type") if payload.get("report_type") in TYPE_PRIORITY else "other"
    m_sev = payload.get("severity") if payload.get("severity") in SEVERITY_ORDER else "low"
    # The more severe reading wins; on a tie keep the more specific type.
    severity = m_sev if _rank(m_sev) > _rank(rules.severity) else rules.severity
    if m_type == "other":
        report_type = rules.report_type
    elif rules.report_type == "other":
        report_type = m_type
    else:
        report_type = min(m_type, rules.report_type, key=TYPE_PRIORITY.index)
    summary = str(payload.get("summary_en") or rules.summary_en)[:240]
    reply = str(payload.get("reply_hi") or "").strip()
    # The urgent safety reply is fixed text; the model may not soften it.
    if severity in {"high", "critical"} or not reply:
        reply = _reply(severity)
    return StructuredReport(report_type, severity, summary, reply[:300], "model+rules",
                            rules.rules + [f"model:{m_type}/{m_sev}"])
