"""Alert drafting: the model fills a few slots, code builds and checks the text.

Fixed safety sentences come from templates/hi.py. If the model is down, or its
draft fails the checker, the fixed template goes out and the alert records
reasoning_model = "rule-fallback".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from Pukaar.core.log import get_logger, log
from Pukaar.llm.bedrock import AlertDraft, BedrockLLM
from Pukaar.llm.tools import DataTools
from Pukaar.store.models import DraftCheck, Village
from Pukaar.store.repo import Repo
from Pukaar.templates import hi

_LOG = get_logger("drafting")
DRAFT_TOOLS = ["get_village_risk", "get_recent_reports", "get_past_events", "get_safe_places"]
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
# Phrases that would contradict a raised level.
_CONTRADICTIONS = ("कोई ख़तरा नहीं", "कोई खतरा नहीं", "no danger", "no risk", "all clear", "ख़तरा टल")
DRAFT_SYSTEM = (
    "You draft one flood alert for villagers in Himachal Pradesh. Code has already decided the level; you never "
    "change it. Call the tools for the village to read the decision trace. Fill only: a Hindi time-window phrase, "
    "one short Hindi advice line (Devanagari), the same advice in English, and a reason of at most 35 words that "
    "cites signals by name and value exactly as the tools give them. Use no number, place or time that is not in "
    "the tool results. Reports labelled UNVERIFIED must not be presented as facts."
)


@dataclass
class DraftResult:
    text_hi: str
    text_en: str
    reason_en: str
    reasoning_model: str
    check: DraftCheck
    tools: list[dict[str, Any]]


def numbers_in(text: str) -> set[str]:
    return {n.rstrip("0").rstrip(".") if "." in n else n for n in _NUMBER.findall(text.translate(_DEVANAGARI_DIGITS))}


def _trace_numbers(obj: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        for v in obj.values():
            found |= _trace_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= _trace_numbers(v)
    elif isinstance(obj, bool) or obj is None:
        pass
    elif isinstance(obj, (int, float)):
        for value in {obj, round(obj, 1), round(obj), round(obj, 2)}:
            found |= numbers_in(str(value))
    else:
        found |= numbers_in(str(obj))
    return found


def check_draft(draft: AlertDraft, village: Village, trace: dict[str, Any], other_places: list[str]) -> DraftCheck:
    """Mostly plain code: numbers, places and tone must match the decision trace."""
    allowed = _trace_numbers(trace) | {"112", "24", "12", "6", "48"}
    text = " ".join([draft.time_window_hi, draft.advice_hi, draft.advice_en, draft.reason_en])
    stray = sorted(numbers_in(text) - allowed)
    if stray:
        return DraftCheck(passed=False, reason=f"numbers not in the decision trace: {', '.join(stray[:5])}")
    lowered = text.lower()
    for place in other_places:
        if place and place.lower() in lowered:
            return DraftCheck(passed=False, reason=f"names another place: {place}")
    if any(p in lowered for p in _CONTRADICTIONS):
        return DraftCheck(passed=False, reason="contradicts the raised level")
    if not re.search(r"[ऀ-ॿ]", draft.advice_hi):
        return DraftCheck(passed=False, reason="Hindi advice is not in Devanagari")
    if len(draft.advice_hi) > 160 or len(draft.reason_en.split()) > 45:
        return DraftCheck(passed=False, reason="draft too long")
    if "http" in lowered or "www." in lowered:
        return DraftCheck(passed=False, reason="contains a link")
    return DraftCheck(passed=True, reason="every number and place found in the decision trace")


def rule_reason(level: str, trace: dict[str, Any]) -> str:
    rules = trace.get("rules_fired") or ["no rules fired"]
    return f"{hi.LEVEL_EN[level]} set by rules: {', '.join(rules[:4])}."


def draft_alert(village: Village, level: str, trace: dict[str, Any], repo: Repo, llm: BedrockLLM | None) -> DraftResult:
    fallback_hi, fallback_en = hi.fallback_alert(level, village.name_hi, village.name)
    tools_trace: list[dict[str, Any]] = []
    draft: AlertDraft | None = None
    if llm is not None and level != "normal":
        from Pukaar.policy.hook import ToolGuard

        data = DataTools(repo)
        guard = ToolGuard("drafting-agent", "AlertDraft", tools_trace, repo=repo)
        prompt = (f"Village id: {village.id}. Level decided by code: {level}. "
                  f"Rules fired: {', '.join(trace.get('rules_fired', []))}.")
        try:
            draft = llm.draft_alert(DRAFT_SYSTEM, prompt, tools=data.strands_tools(DRAFT_TOOLS), hooks=[guard])
        except Exception as exc:  # never raise into the workflow
            log(_LOG, "draft failed", 30, error=str(exc))
            draft = None

    if draft is None:
        return DraftResult(fallback_hi, fallback_en, rule_reason(level, trace), "rule-fallback",
                           DraftCheck(passed=False, reason="model unavailable; fixed template used"), tools_trace)

    others = [v.name for v in repo.list_villages() if v.id != village.id] + \
             [v.name_hi for v in repo.list_villages() if v.id != village.id]
    check = check_draft(draft, village, {"trace": trace, "tools": tools_trace}, others)
    if not check.passed:
        log(_LOG, "draft rejected", 30, village_id=village.id, reason=check.reason)
        return DraftResult(fallback_hi, fallback_en, rule_reason(level, trace), "rule-fallback",
                           DraftCheck(passed=False, reason=f"draft rejected ({check.reason}); fixed template used"),
                           tools_trace)

    text_hi = (f"पुकार: {village.name_hi} के लिए {hi.LEVEL_HI[level]}। {draft.time_window_hi.strip()} "
               f"{draft.advice_hi.strip()} {hi.SAFETY_HI[level]} {hi.CALL_112_HI}")
    text_en = (f"Pukaar: {hi.LEVEL_EN[level]} for {village.name}. {draft.advice_en.strip()} "
               f"{hi.SAFETY_EN[level]} {hi.CALL_112_EN}")
    return DraftResult(re.sub(r"\s+", " ", text_hi), re.sub(r"\s+", " ", text_en), draft.reason_en.strip(),
                       llm.model_name if llm else "rule-fallback", check, tools_trace)
