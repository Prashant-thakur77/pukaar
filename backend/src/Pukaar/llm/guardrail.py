"""Screen villager text before any model or rule acts on it.

screen() asks the Bedrock guardrail (ApplyGuardrail, source INPUT) when one is
configured. ApplyGuardrail needs no model access, so this runs on the live
stack today. Without a guardrail (local mode, tests) or on any error, a local
heuristic stands in: regexes for orders aimed at the warning system, in
English, Hindi (Devanagari) and Roman Hindi, plus phone and e-mail masking.

screen() never raises. A held report is kept; the caller only stops it from
being auto-verified or shown to a model.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log, metric

_LOG = get_logger("guardrail")
Engine = Literal["bedrock-guardrail", "local-heuristic"]
MAX_CHARS = 2000
# The denied topic in infra/template.yaml (ReportGuardrail), by its exact name.
INSTRUCTION_TOPIC = "Instructions to the system"


@dataclass(frozen=True)
class ScreenResult:
    allowed: bool
    action: str  # "NONE", "GUARDRAIL_INTERVENED" or "HEURISTIC_BLOCKED"
    reasons: list[str] = field(default_factory=list)
    masked_text: str | None = None  # set only when the text was changed (PII masked)
    engine: Engine = "local-heuristic"


# -- local heuristic ------------------------------------------------------
_EN_OVERRIDE = re.compile(
    r"\b(ignore|disregard|forget|override|bypass|skip)\b.{0,40}?"
    r"\b(previous|prior|earlier|above|all|your|these|those|system)\b.{0,30}?"
    r"\b(instructions?|rules?|prompts?|directions?|guidelines?|orders?|commands?)\b",
    re.IGNORECASE | re.DOTALL,
)
_EN_PERSONA = re.compile(
    r"\b(system prompt|developer mode|jailbreak|you are now|act as (an?|the) |pretend (to be|you are)"
    r"|new instructions?|reveal (your|the) (prompt|instructions|rules))",
    re.IGNORECASE,
)
_EN_STEER = re.compile(
    r"\b(mark|set|change|declare|flag|switch|turn)\b.{0,30}?"
    r"\b(every|all|each|the other)\b.{0,15}?\bvillages?\b.{0,30}?"
    r"\b(critical|normal|levels?|status)\b",
    re.IGNORECASE | re.DOTALL,
)
_EN_LEVEL = re.compile(
    r"\b(set|change|raise|lower|force)\b.{0,20}?\b(alert|warning|risk|village|danger)\s+levels?\b.{0,20}?\bto\b",
    re.IGNORECASE | re.DOTALL,
)
# Hindi in Devanagari. \b is unreliable with combining marks, so none is used.
_HI_RULES = re.compile(r"(नियम|निर्देश|आदेश|हिदायत)\S*.{0,30}?(बदल|भूल|अनदेखा|नज़रअंदाज़|नजरअंदाज|मत मान)", re.DOTALL)
_HI_STEER = re.compile(
    r"(सभी|सारे|सारी|हर|सब)\s+गा[ँं]व\S*.{0,25}?(गंभीर|क्रिटिकल|ख़तरनाक|खतरनाक|रेड|सामान्य).{0,20}?"
    r"(घोषित|मार्क|कर\s*(दो|दें|दीजिए|देना|दिया)|करो|करें|बना|डाल)",
    re.DOTALL,
)
_HI_SYSTEM = re.compile(r"(सिस्टम|प्रॉम्प्ट|प्रोम्प्ट).{0,30}?(नियम|निर्देश|आदेश|बदल|भूल|बताओ|बताइए|दिखाओ)", re.DOTALL)
# Roman Hindi.
_ROMAN = re.compile(
    r"\b(niyam|nirdesh|aadesh|adesh)\w*\b.{0,30}?\b(badal|bhool|bhul|ignore|hata|mat maan)"
    r"|\b(sabhi|saare|sare|har|sab)\s+gaon\w*\b.{0,25}?\b(critical|gambhir|khatarnak|red)\b.{0,20}?"
    r"\b(kar\s*(do|de|dein|dijiye)|karo|ghoshit|mark)",
    re.IGNORECASE | re.DOTALL,
)
_PROMPT_ATTACK = (_EN_OVERRIDE, _EN_PERSONA, _HI_RULES, _HI_SYSTEM)
_INSTRUCTION = (_EN_STEER, _EN_LEVEL, _HI_STEER, _ROMAN)

_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def heuristic(text: str) -> ScreenResult:
    t = _norm(text)
    reasons: list[str] = []
    if any(p.search(t) for p in _PROMPT_ATTACK):
        reasons.append("prompt_attack")
    if any(p.search(t) for p in _INSTRUCTION):
        reasons.append("instruction_to_system")
    if reasons:
        return ScreenResult(False, "HEURISTIC_BLOCKED", reasons, None, "local-heuristic")
    masked = _EMAIL.sub("{EMAIL}", _PHONE.sub("{PHONE}", t))
    if masked != t:
        found = (["pii:phone"] if "{PHONE}" in masked else []) + (["pii:email"] if "{EMAIL}" in masked else [])
        return ScreenResult(True, "NONE", found, masked, "local-heuristic")
    return ScreenResult(True, "NONE", [], None, "local-heuristic")


# -- Bedrock Guardrails ---------------------------------------------------
@lru_cache(maxsize=1)
def _runtime() -> Any:
    import boto3
    from botocore.config import Config

    s = get_settings()
    return boto3.client("bedrock-runtime", region_name=s.aws_region, config=Config(
        connect_timeout=3, read_timeout=s.guardrail_timeout_seconds, retries={"mode": "standard", "max_attempts": 2}))


def _code(kind: str, name: str) -> str:
    if kind == "topic":
        return "instruction_to_system" if name.strip().lower() == INSTRUCTION_TOPIC.lower() else f"topic:{name}"
    return name.lower()


def from_response(resp: dict[str, Any]) -> ScreenResult:
    """Turn an ApplyGuardrail response into a ScreenResult."""
    if resp.get("action") != "GUARDRAIL_INTERVENED":
        return ScreenResult(True, "NONE", [], None, "bedrock-guardrail")
    blocked: list[str] = []
    masked: list[str] = []
    for a in resp.get("assessments") or []:
        for t in (a.get("topicPolicy") or {}).get("topics") or []:
            if t.get("action") == "BLOCKED":
                blocked.append(_code("topic", str(t.get("name", ""))))
        for f in (a.get("contentPolicy") or {}).get("filters") or []:
            if f.get("action") == "BLOCKED":
                blocked.append(_code("content", str(f.get("type", "content"))))
        words = a.get("wordPolicy") or {}
        if any(w.get("action") == "BLOCKED" for w in (words.get("customWords") or []) + (words.get("managedWordLists") or [])):
            blocked.append("word_filter")
        sip = a.get("sensitiveInformationPolicy") or {}
        for e in (sip.get("piiEntities") or []) + (sip.get("regexes") or []):
            kind = f"pii:{str(e.get('type') or e.get('name') or 'other').lower()}"
            if e.get("action") == "BLOCKED":
                blocked.append(kind)
            elif e.get("action") == "ANONYMIZED":
                masked.append(kind)
    blocked = list(dict.fromkeys(blocked))
    masked = list(dict.fromkeys(masked))
    if blocked or not masked:
        # Intervened with no masking to explain it: treat as held (fail closed on unknown policies).
        return ScreenResult(False, "GUARDRAIL_INTERVENED", blocked or ["guardrail_intervened"], None, "bedrock-guardrail")
    out = "".join(str(o.get("text", "")) for o in resp.get("outputs") or [])
    return ScreenResult(True, "GUARDRAIL_INTERVENED", masked, out or None, "bedrock-guardrail")


def _apply(text: str) -> ScreenResult:
    s = get_settings()
    resp = _runtime().apply_guardrail(
        guardrailIdentifier=s.guardrail_id, guardrailVersion=s.guardrail_version, source="INPUT",
        content=[{"text": {"text": text}}],
    )
    return from_response(resp)


def screen(text: str, source: str = "report") -> ScreenResult:
    """Screen one piece of villager text. Never raises."""
    text = _norm(text or "")[:MAX_CHARS]
    if not text.strip():
        return ScreenResult(True, "NONE", [], None, "local-heuristic")
    s = get_settings()
    result: ScreenResult | None = None
    if s.guardrail_enabled:
        try:
            result = _apply(text)
        except Exception as exc:  # any failure: the heuristic stands in
            log(_LOG, "guardrail unavailable, local heuristic used", 30, source=source,
                error=f"{type(exc).__name__}: {str(exc)[:200]}")
            metric("GuardrailFallback", 1, Source=source)
    else:
        log(_LOG, "guardrail not configured, local heuristic used", source=source, mode=s.mode)
    if result is None:
        try:
            result = heuristic(text)
        except Exception as exc:  # a regex bug must not lose or stall a report
            log(_LOG, "heuristic failed", 40, source=source, error=str(exc)[:200])
            return ScreenResult(True, "NONE", ["screen_unavailable"], None, "local-heuristic")
    metric("ReportScreened", 1, Engine=result.engine, Outcome="allowed" if result.allowed else "held")
    if not result.allowed:
        log(_LOG, "text held for review", 30, source=source, engine=result.engine, reasons=result.reasons)
    return result
