"""The public agent registry, round-by-round traces and the sensor board.

Everything here is read from code or from stored records, never typed twice:
tool lists come from drafting.DRAFT_TOOLS / analyst.ANALYST_TOOLS, their
descriptions from llm.tools.TOOL_DOCS, the "never" list from the Cedar
forbid policy in policy/base.cedar, turn and time budgets from llm.bedrock,
output fields from the typed output models. Live status is read from what the
last real draft and report actually used, and from the cached model-access
probe the sweep runs at most every 6 hours (services/model_probe.py),
whichever is newer; no model is called here.

No personal data leaves these views: no recipient names, officer usernames,
report text, phone numbers or chat ids.
"""

from __future__ import annotations

import importlib.util
import os
import re
from datetime import timedelta
from typing import Any

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.llm import bedrock
from Pukaar.llm.tools import TOOL_DOCS
from Pukaar.policy import guard
from Pukaar.services import risk_rules, watch
from Pukaar.services.analyst import ANALYST_TOOLS, AnalystAnswer
from Pukaar.services.drafting import DRAFT_TOOLS
from Pukaar.store.models import Alert, Village
from Pukaar.store.repo import Repo
from Pukaar.templates import hi

GUARDRAIL_MODULES = ("Pukaar.services.guardrail", "Pukaar.services.guardrails", "Pukaar.llm.guardrail")
SERIES_POINTS = 48

# Plain words for the Cedar actions an agent is forbidden.
ACTION_TEXT: dict[str, tuple[str, str]] = {
    "approve": ("Approve an alert", "चेतावनी मंज़ूर करना"),
    "decline": ("Decline an alert", "चेतावनी रद्द करना"),
    "deliver": ("Send an alert to phones", "फ़ोन पर चेतावनी भेजना"),
    "auto_send": ("Auto-send without approval", "बिना मंज़ूरी अपने आप भेजना"),
    "failsafe": ("Fire the failsafe template", "फ़ेलसेफ़ संदेश भेजना"),
    "issue_directive": ("Issue an evacuation or other order", "निकासी या कोई आदेश जारी करना"),
    "open_rollcall": ("Open a safety roll-call", "सुरक्षा हाज़िरी शुरू करना"),
    "remind_rollcall": ("Remind people in a roll-call", "हाज़िरी की याद दिलाना"),
    "set_shelter_status": ("Change the shelter ledger", "आश्रय की स्थिति बदलना"),
    "block_road": ("Mark a road blocked or open", "सड़क बंद या खुली बताना"),
}
# By design, not by policy: the typed outputs have no field for these.
DESIGN_NEVER: list[dict[str, str]] = [
    {"action": "set_level", "en": "Set or change a village's level", "hi": "गाँव का स्तर तय करना या बदलना",
     "source": "design: code sets the level; the output has no level field"},
    {"action": "choose_recipients", "en": "Choose who receives an alert", "hi": "चेतावनी किसे मिले, यह चुनना",
     "source": "design: recipients come from the village list"},
]


def _model_label(model_id: str) -> str:
    m = re.search(r"nova-(\d+)-(lite|pro|micro|premier)", model_id)
    if m:
        return f"Nova {m.group(1)} {m.group(2).capitalize()}"
    m = re.search(r"nova-(lite|pro|micro|premier)", model_id)
    return f"Nova {m.group(1).capitalize()}" if m else model_id


def forbidden_agent_actions() -> list[str]:
    """Action names in the Cedar forbid policy 'agents-never-send', read from the policy file."""
    text, _ = guard._policies()
    m = re.search(r'@id\("agents-never-send"\).*?action in \[(.*?)\]', text, re.DOTALL)
    return re.findall(r'Action::"([^"]+)"', m.group(1)) if m else []


def _policy(pid: str) -> dict[str, str]:
    _, meta = guard._policies()
    desc = next((d for i, d in meta if i == pid), "")
    return {"id": pid, "desc": desc}


def _never() -> list[dict[str, str]]:
    out = [{"action": a, "en": ACTION_TEXT.get(a, (a, a))[0], "hi": ACTION_TEXT.get(a, (a, a))[1],
            "source": "cedar: agents-never-send"} for a in forbidden_agent_actions()]
    return DESIGN_NEVER + out


def _tool(name: str) -> dict[str, Any]:
    return {"name": name, "description": TOOL_DOCS.get(name, ""), "read_only": name in guard.READ_ONLY_TOOLS,
            "aws": "DynamoDB (read)"}


# -- live status --------------------------------------------------------------
def _status(state: str, en: str, hi_: str, evidence: str = "", evidence_hi: str = "") -> dict[str, str]:
    """state: live | fallback | pending | deterministic | unknown."""
    return {"state": state, "label_en": en, "label_hi": hi_, "evidence": evidence, "evidence_hi": evidence_hi or evidence}


def _last_real_draft(repo: Repo) -> Alert | None:
    for a in repo.list_alerts(limit=25):
        if a.replay or a.decision_trace.get("drill") or a.status == "drafting" or a.draft_check is None:
            continue
        if "escalated" in (a.draft_check.reason or ""):
            continue  # an escalation swaps in the template without asking the model
        return a
    return None


def _probe(repo: Repo) -> tuple[str | None, str]:
    """The cached model-access answer (services/model_probe.py): ("live"|"pending"|None, when it was seen)."""
    try:
        rec = repo.get_model_probe() or {}
    except Exception:
        rec = {}
    access = rec.get("access") if rec.get("access") in ("live", "pending") else None
    return access, str(rec.get("access_checked_at") or "")


# What the fallback is called, per agent, while the model cannot be reached.
_FALLBACK_WORDS = {
    "draft": ("fixed template in use", "तय ढाँचा इस्तेमाल हो रहा है"),
    "analyst": ("keyword router in use", "शब्द-आधारित राउटर चल रहा है"),
}


def model_status(repo: Repo, who: str = "draft") -> dict[str, str]:
    """Status from configuration plus the newest evidence: the last real draft or the cached access probe.

    Never calls a model. The 15-minute sweep refreshes the probe at most every 6 hours,
    so the page turns "Live" by itself once Bedrock model access is granted.
    """
    from Pukaar.services.model_probe import PENDING_EVIDENCE, PENDING_EVIDENCE_HI, PROBE_EVERY

    s = get_settings()
    if not s.llm_enabled:
        return _status("fallback", "Rule fallback: model calls are off here",
                       "नियम वाला विकल्प: यहाँ मॉडल बंद है", "PUKAAR_LLM_ENABLED is false")
    fb_en, fb_hi = _FALLBACK_WORDS.get(who, _FALLBACK_WORDS["draft"])
    access, access_at = _probe(repo)
    a = _last_real_draft(repo)
    draft_at = a.created_at if a else ""
    pending = _status("pending", f"Pending model access: {fb_en}", f"मॉडल की अनुमति बाकी: {fb_hi}",
                      f"{PENDING_EVIDENCE} (checked {access_at})" if access == "pending" else PENDING_EVIDENCE,
                      PENDING_EVIDENCE_HI)
    if a is not None and draft_at >= access_at:  # the last real draft is the newest evidence
        reason = (a.draft_check.reason if a.draft_check else "") or ""
        if a.reasoning_model and a.reasoning_model != "rule-fallback":
            return _status("live", f"Live: last draft by {_model_label(a.reasoning_model)}",
                           f"चालू: आख़िरी ड्राफ़्ट {_model_label(a.reasoning_model)} ने लिखा", f"alert at {a.created_at}")
        if not reason.startswith("model unavailable"):
            return _status("live", "Model answered; checker chose the template",
                           "मॉडल ने जवाब दिया; जाँच ने तय ढाँचा चुना", f"last draft {a.created_at}: {reason}")
        if access == "live":  # access was confirmed earlier, yet this draft could not reach the model
            return _status("fallback", f"Model unreachable at the last draft: {fb_en}",
                           f"पिछले ड्राफ़्ट पर मॉडल नहीं मिला: {fb_hi}",
                           f"last draft {a.created_at}: {reason}; model access was confirmed at {access_at}")
        out = dict(pending)
        out["evidence"] = f"{PENDING_EVIDENCE} (last draft {a.created_at}: {reason})"
        return out
    if access == "live":
        return _status("live", "Live: model access confirmed", "चालू: मॉडल की अनुमति मिल चुकी है",
                       f"a 1-token check answered at {access_at}")
    if access == "pending":
        return pending
    hours = int(PROBE_EVERY.total_seconds() // 3600)
    return _status("unknown", "Model configured; access not checked yet", "मॉडल तैयार; अनुमति अभी जाँची नहीं गई",
                   f"the 15-minute sweep checks model access at most every {hours} hours")


def report_model_status(repo: Repo) -> dict[str, str]:
    s = get_settings()
    if not s.llm_enabled:
        return _status("fallback", "Keyword parser: model calls are off here",
                       "शब्द-आधारित पार्सर: यहाँ मॉडल बंद है", "PUKAAR_LLM_ENABLED is false")
    latest = None
    for v in repo.list_villages():
        for r in repo.list_reports(v.id, limit=10):
            if r.replay or not (r.text or r.transcript):
                continue
            if latest is None or r.created_at > latest.created_at:
                latest = r
    from Pukaar.services.model_probe import PENDING_EVIDENCE, PENDING_EVIDENCE_HI

    access, access_at = _probe(repo)
    if latest is not None and latest.parser_source == "model+rules":
        return _status("live", "Live: model and keyword parser together", "चालू: मॉडल और शब्द-पार्सर साथ",
                       f"report at {latest.created_at}")
    if access == "live":
        if latest is None or access_at > latest.created_at:
            return _status("live", "Live: model access confirmed", "चालू: मॉडल की अनुमति मिल चुकी है",
                           f"a 1-token check answered at {access_at}")
        return _status("fallback", "Keyword parser used for the last report", "पिछली सूचना शब्द-पार्सर ने पढ़ी",
                       f"report at {latest.created_at} parsed by rules; model access was confirmed at {access_at}")
    if access == "pending" or latest is not None:
        seen = f"checked {access_at}" if access == "pending" else f"report at {latest.created_at} parsed by rules"
        return _status("pending", "Pending model access: keyword parser in use",
                       "मॉडल की अनुमति बाकी: शब्द-पार्सर चल रहा है", f"{PENDING_EVIDENCE} ({seen})",
                       PENDING_EVIDENCE_HI)
    return _status("unknown", "Model configured; no report yet", "मॉडल तैयार; अभी कोई सूचना नहीं",
                   "the 15-minute sweep checks model access at most every 6 hours")


def guardrail_status() -> dict[str, Any]:
    present = any(importlib.util.find_spec(m) is not None for m in GUARDRAIL_MODULES)
    configured = bool(getattr(get_settings(), "guardrail_id", "") or os.environ.get("PUKAAR_GUARDRAIL_ID"))
    if not present:
        st = _status("pending", "Pending deploy", "तैनाती बाकी", "screen not in this build")
    elif configured:
        st = _status("live", "Live: Amazon Bedrock Guardrails", "चालू: Amazon Bedrock Guardrails",
                     "guardrail configured")
    else:
        st = _status("fallback", "Local heuristic: no guardrail configured", "स्थानीय जाँच: गार्डरेल सेट नहीं",
                     "PUKAAR_GUARDRAIL_ID not set")
    return {"present": present, "configured": configured, "status": st}


# -- registry -------------------------------------------------------------------
def registry(repo: Repo) -> dict[str, Any]:
    s = get_settings()
    model = _model_label(s.bedrock_model_id)
    m_status = model_status(repo)
    never = _never()
    scan = watch.scan(repo)
    findings = [f for _, _, fs in scan.values() for f in fs]
    gr = guardrail_status()
    strands = f"Amazon Bedrock ({model}) via Strands Agents"

    agents: list[dict[str, Any]] = [
        {
            "id": "drafting-agent", "name_en": "Drafting agent", "name_hi": "संदेश लिखने वाला एजेंट",
            "kicker": "Amazon Bedrock · Strands",
            "role_en": "Writes the Hindi alert for a level that code has already set: a time phrase, one advice "
                       "line and a short reason. Every number must come from the decision trace.",
            "role_hi": "कोड के तय किए स्तर के लिए हिंदी चेतावनी लिखता है: समय, एक सलाह और छोटा कारण। हर संख्या "
                       "फ़ैसले के रिकॉर्ड से ही आनी चाहिए।",
            "primitives": [strands, "Cedar policy on every tool call (Strands hook)", "Typed output (AlertDraft)",
                           "AgentCore-ready"],
            "tools": [_tool(n) for n in DRAFT_TOOLS],
            "output_fields": list(bedrock.AlertDraft.model_fields),
            "never": never,
            "policies": [_policy("agent-read-only-tools"), _policy("agents-never-send")],
            "max_turns": bedrock.MAX_TURNS, "budget_seconds": bedrock.BUDGET_SECONDS["draft"],
            "fallback_en": "A checker rejects any number or place not in the trace; on rejection or outage the "
                           "fixed Hindi template goes out and the alert records rule-fallback.",
            "fallback_hi": "जाँच रिकॉर्ड से बाहर की हर संख्या या जगह रोकती है; तब या सेवा बंद होने पर तय हिंदी "
                           "ढाँचा जाता है और चेतावनी पर rule-fallback दर्ज होता है।",
            "status": m_status,
        },
        {
            "id": "analyst-agent", "name_en": "Ask Pukaar analyst", "name_hi": "पुकार से पूछें (विश्लेषक)",
            "kicker": "Amazon Bedrock · Strands",
            "role_en": "Answers an officer's question about villages, readings, alerts, deliveries and reports, "
                       "with a chart and a map built by code from the tool results.",
            "role_hi": "अधिकारी के सवाल का जवाब गाँवों, रीडिंग, चेतावनियों, डिलीवरी और सूचनाओं से देता है, "
                       "चार्ट और नक्शा कोड बनाता है।",
            "primitives": [strands, "Cedar policy on every tool call (Strands hook)", "Typed output (AnalystAnswer)",
                           "AgentCore-ready"],
            "tools": [_tool(n) for n in ANALYST_TOOLS],
            "output_fields": list(AnalystAnswer.model_fields),
            "never": never,
            "policies": [_policy("agent-read-only-tools"), _policy("agents-never-send"), _policy("officer-operate")],
            "max_turns": bedrock.MAX_TURNS, "budget_seconds": bedrock.BUDGET_SECONDS["analyst"],
            "fallback_en": "Any number not found in a tool result withholds the answer. Without a model, a keyword "
                           "router calls the same tools and says no model was used.",
            "fallback_hi": "टूल के नतीजे में न मिली कोई संख्या हो तो जवाब रोका जाता है। मॉडल न हो तो शब्द-आधारित "
                           "राउटर वही टूल चलाता है और साफ़ बताता है।",
            "access_en": "Officers only (Cedar action ask_analyst)",
            "access_hi": "सिर्फ़ अधिकारी (Cedar: ask_analyst)",
            "status": model_status(repo, "analyst"),
        },
        {
            "id": "report-agent", "name_en": "Report-structuring agent", "name_hi": "सूचना समझने वाला एजेंट",
            "kicker": "Amazon Bedrock · typed output",
            "role_en": "Turns a villager's Hindi words (typed or transcribed) into a type, a severity, one English "
                       "line for the officer and a calm spoken Hindi reply; describes photos.",
            "role_hi": "गाँव वाले के हिंदी शब्दों (लिखे या बोले) को प्रकार, गंभीरता, अधिकारी के लिए एक लाइन और "
                       "शांत हिंदी जवाब में बदलता है; फ़ोटो का वर्णन करता है।",
            "primitives": [f"Amazon Bedrock ({model}), text and image", "Amazon Transcribe (hi-IN)",
                           "Typed output (ReportFields)", "AgentCore-ready"],
            "tools": [],
            "output_fields": list(bedrock.ReportFields.model_fields),
            "never": [DESIGN_NEVER[0], {"action": "verify", "en": "Mark a report verified", "hi": "सूचना को सत्यापित करना",
                                        "source": "design: only code rules or an officer verify"},
                      {"action": "soften_reply", "en": "Soften the urgent safety reply", "hi": "ज़रूरी सुरक्षा जवाब नरम करना",
                       "source": "design: high and critical replies are fixed text"}],
            "policies": [],
            "max_turns": bedrock.MAX_TURNS, "budget_seconds": bedrock.BUDGET_SECONDS["report"],
            "fallback_en": "A keyword parser (Devanagari, Roman Hindi, English) always runs; the more severe "
                           "reading wins.",
            "fallback_hi": "शब्द-आधारित पार्सर (देवनागरी, रोमन हिंदी, अंग्रेज़ी) हमेशा चलता है; ज़्यादा गंभीर "
                           "नतीजा माना जाता है।",
            "status": report_model_status(repo),
        },
        {
            "id": "report-guardrail", "name_en": "Report guardrail screen", "name_hi": "सूचना की सुरक्षा जाँच",
            "kicker": "Amazon Bedrock Guardrails",
            "role_en": "Screens villager text before any agent reads it: prompt attacks, abuse, and phone numbers "
                       "masked. A blocked report is kept, marked and shown to officers, never auto-verified.",
            "role_hi": "किसी एजेंट के पढ़ने से पहले गाँव वालों का लिखा जाँचता है: प्रॉम्प्ट हमले, गाली, फ़ोन "
                       "नंबर छिपाना। रोकी गई सूचना रखी जाती है, निशान के साथ अधिकारी को दिखती है।",
            "primitives": ["Amazon Bedrock Guardrails (ApplyGuardrail)", "Prompt-attack filter", "PII masking"],
            "tools": [],
            "output_fields": ["screened", "reason"],
            "never": [{"action": "delete", "en": "Delete a report", "hi": "सूचना मिटाना",
                       "source": "design: blocked reports are kept"},
                      DESIGN_NEVER[0]],
            "policies": [],
            "max_turns": 0, "budget_seconds": None,
            "fallback_en": "A local heuristic stands in when Guardrails are unreachable.",
            "fallback_hi": "Guardrails न मिलें तो स्थानीय जाँच काम करती है।",
            "status": gr["status"],
        },
        {
            "id": "watch-agent", "name_en": "Watch agent (sensors)", "name_hi": "निगरानी एजेंट (सेंसर)",
            "kicker": "Deterministic · AWS Lambda",
            "role_en": "Checks every river gauge's own readings for the four field faults: stale, flat-lined, "
                       "impossible jumps and low battery. It flags; it never acts.",
            "role_hi": "हर नदी गेज की रीडिंग में चार ख़राबियाँ देखता है: पुरानी, अटकी, असंभव उछाल और कम बैटरी। "
                       "सिर्फ़ बताता है, कुछ करता नहीं।",
            "primitives": ["AWS Lambda (plain code, no model)", "Amazon DynamoDB (gauge readings)",
                           "AWS IoT Core / API Gateway (inputs)"],
            "tools": [{"name": c["kind"], "description": c["en"], "description_hi": c["hi"], "read_only": True,
                       "aws": "DynamoDB (read)"} for c in watch.CHECKS],
            "output_fields": ["village_id", "kind", "severity", "at", "value", "message_en", "message_hi"],
            "never": DESIGN_NEVER[:1] + [{"action": "deliver", "en": "Send anything", "hi": "कुछ भी भेजना",
                                          "source": "design: findings are shown, not sent"}],
            "policies": [],
            "max_turns": 0, "budget_seconds": None,
            "fallback_en": f"The rules already ignore a gauge reading older than {risk_rules.GAUGE_FRESH_MINUTES} "
                           "min; this makes the fault visible.",
            "fallback_hi": f"{risk_rules.GAUGE_FRESH_MINUTES} मिनट से पुरानी गेज रीडिंग नियम पहले से नहीं गिनते; "
                           "यह ख़राबी को सामने लाता है।",
            "status": _status("deterministic", "Running: plain code", "चालू: सादा कोड",
                              f"{len(scan)} gauges checked"),
            "findings": [watch.as_dict(f) for f in findings],
        },
    ]

    day = clock.iso(clock.now())[:10]
    audit = [r for r in repo.list_audit(day) if r.role == "agent" and r.action == "use_tool"]
    alerts = [a for a in repo.list_alerts(limit=100) if not a.replay and a.status != "drafting"]
    _, meta = guard._policies()
    return {
        "generated_at": clock.iso(clock.now()),
        "model": {"id": s.bedrock_model_id, "label": model, "enabled": s.llm_enabled, "status": m_status},
        "guardrail": gr,
        "agents": agents,
        "counters": {
            "agents": len(agents),
            "read_only_tools": len(guard.READ_ONLY_TOOLS),
            "cedar_policies": len(meta),
            "tool_calls_today": len(audit),
            "tool_calls_denied_today": sum(1 for r in audit if r.decision == "deny"),
            "drafts": len(alerts),
            "drafts_by_model": sum(1 for a in alerts if a.reasoning_model not in ("", "rule-fallback")),
            "drafts_by_template": sum(1 for a in alerts if a.reasoning_model in ("", "rule-fallback")),
            "watch_findings": sum(1 for f in findings if f.severity == "warn"),
        },
    }


# -- traces -------------------------------------------------------------------------
def _f(en: str, hi_: str, value: Any) -> dict[str, Any]:
    return {"en": en, "hi": hi_, "v": value}


def _fmt(x: Any, unit: str = "") -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        x = round(x, 1)
        x = int(x) if x == int(x) else x
    return f"{x}{unit}"


def _role_of(decided_by: str | None) -> str:
    if not decided_by:
        return "—"
    if decided_by.startswith("system"):
        return "system (auto-send)" if "auto" in decided_by else "system"
    return "duty officer (link)" if "(link)" in decided_by else "duty officer"


def trace_rounds(a: Alert, timeline_steps: list[tuple[str, str]]) -> list[dict[str, Any]]:
    t = a.decision_trace or {}
    drill = bool(t.get("drill"))
    rounds: list[dict[str, Any]] = []

    def add(kind: str, actor: str, en: str, hi_: str, aws: str, state: str, facts: list[dict[str, Any]],
            note_en: str = "", note_hi: str = "") -> None:
        rounds.append({"n": len(rounds) + 1, "kind": kind, "actor": actor, "title_en": en, "title_hi": hi_,
                       "aws": aws, "state": state, "facts": facts, "note_en": note_en, "note_hi": note_hi})

    # 1. sense
    facts: list[dict[str, Any]] = []
    for e in t.get("evidence") or []:
        k = e.get("kind")
        if k == "reading":
            facts.append(_f("Rain, next 24 h", "बारिश, अगले 24 घंटे",
                            f"{_fmt(e.get('rain_24h_mm'), ' mm')} · {e.get('rain_level', '—')}"))
            facts.append(_f("River peak (forecast)", "नदी का शिखर (पूर्वानुमान)",
                            f"{_fmt(e.get('discharge_peak'), ' m³/s')} · {e.get('river_level', '—')}"))
        elif k == "gauge":
            facts.append(_f("River gauge", "नदी गेज",
                            f"{_fmt(e.get('water_level_cm'), ' cm')} · {e.get('gauge_level', '—')}"
                            + (" · simulated" if e.get("simulated") else "")))
    reports = [e for e in t.get("evidence") or [] if e.get("kind") == "report"]
    if reports:
        facts.append(_f("Villager reports", "गाँव वालों की सूचनाएँ",
                        f"{len(reports)} ({sum(1 for r in reports if r.get('verified'))} verified)"))
    if drill:
        facts.append(_f("Source", "स्रोत", "drill started by hand (no forecast)"))
    elif not facts:
        facts.append(_f("Source", "स्रोत", "no reading stored"))
    add("sense", "code", "Read the sources", "स्रोत पढ़े", "EventBridge Scheduler · Lambda · DynamoDB", "ok", facts)

    # 2. rules
    rules = [r for r in t.get("rules_fired") or [] if r != "drill"]
    rf = [_f("Rules fired", "लागू नियम", ", ".join(rules) if rules else ("drill" if drill else "none"))]
    if t.get("raw_level"):
        rf.append(_f("Level", "स्तर", f"{t.get('previous_level', a.previous_level)} → {t.get('raw_level')} → {a.level}"))
    else:
        rf.append(_f("Level", "स्तर", a.level))
    if t.get("data_disagrees"):
        rf.append(_f("Sources disagree", "स्रोतों में मतभेद", ", ".join(t.get("contradictions") or [])))
    add("rules", "code", "Code set the level", "कोड ने स्तर तय किया", "Lambda (risk rules)", "ok", rf,
        "The model never sets the level.", "स्तर मॉडल तय नहीं करता।")

    # 3. tools
    tools = t.get("drafting_tools") or []
    if tools:
        tf = [_f(x.get("name", "?"), x.get("name", "?"),
                 f"{x.get('decision', '?')} · {', '.join(f'{k}={v}' for k, v in (x.get('input') or {}).items()) or '—'}")
              for x in tools]
        denied = any(x.get("decision") == "deny" for x in tools)
        add("tools", "agent", "Agent called read-only tools", "एजेंट ने सिर्फ़-पढ़ने वाले टूल चलाए",
            "Strands hook · Cedar", "deny" if denied else "ok", tf)
    else:
        add("tools", "agent", "Agent tools", "एजेंट के टूल", "Strands hook · Cedar", "skipped",
            [_f("Tool calls", "टूल कॉल", 0)],
            "No tool calls: the model was not reached, so nothing was invented.",
            "कोई टूल कॉल नहीं: मॉडल तक पहुँच नहीं हुई, इसलिए कुछ गढ़ा नहीं गया।")

    # 4. draft
    by_model = bool(a.reasoning_model) and a.reasoning_model != "rule-fallback"
    check = a.draft_check
    df = [_f("Written by", "किसने लिखा", _model_label(a.reasoning_model) if by_model else "fixed Hindi template"),
          _f("Checker", "जाँच", ("pass: " if check and check.passed else "") + (check.reason if check else "—"))]
    add("draft", "agent" if by_model else "template", "Hindi alert drafted" if by_model else "Fixed template used",
        "हिंदी संदेश लिखा गया" if by_model else "तय ढाँचा इस्तेमाल हुआ",
        "Bedrock via Strands · checker" if by_model else "templates/hi.py · Polly",
        "ok" if by_model and check and check.passed else "fallback", df)

    # 5. approval
    steps = [s for s, _ in timeline_steps]
    asked = steps.count("asked_officer")
    timeouts = steps.count("officer_timeout")
    af = [_f("Status", "स्थिति", a.status), _f("Officers asked", "पूछे गए अधिकारी", asked)]
    if timeouts:
        af.append(_f("Timed out", "समय पर जवाब नहीं", timeouts))
    af.append(_f("Decided by", "फ़ैसला", _role_of(a.decided_by)))
    if a.decided_at:
        af.append(_f("Decided at", "फ़ैसले का समय", a.decided_at))
    pending = a.status in {"drafting", "pending"}
    state = "pending" if pending else ("ok" if a.approved or a.status == "auto_sent_unapproved" else "skipped")
    if pending:
        title = ("Waiting for an officer", "अधिकारी का इंतज़ार")
    elif a.status == "auto_sent_unapproved":
        title = ("No answer: critical sent, flagged", "जवाब नहीं: गंभीर चेतावनी गई, निशान के साथ")
    elif a.approved:
        title = ("An officer approved", "अधिकारी ने मंज़ूरी दी")
    else:
        title = ("Not approved: nothing sent", "मंज़ूरी नहीं: कुछ नहीं भेजा")
    add("approve", "person", *title, "Step Functions waitForTaskToken · Cognito · Cedar",
        state, af, "Agents can never approve (Cedar forbid).", "एजेंट कभी मंज़ूरी नहीं दे सकते (Cedar मनाही)।")

    # 6. delivery
    resent = steps.count("recall")
    dfacts = [_f("Recipients", "पाने वाले", a.recipients_count), _f("Delivered", "पहुँचा", a.delivered_count),
              _f("Heard (मिल गया)", "सुना (मिल गया)", a.acknowledged_count)]
    if resent:
        dfacts.append(_f("Re-sent", "दोबारा भेजा", resent))
    if a.status in {"delivered", "closed", "auto_sent_unapproved", "failsafe"} and a.delivered_count:
        dstate = "ok"
    elif a.status in {"declined", "expired"}:
        dstate = "skipped"
    else:
        dstate = "pending" if pending or a.status in {"approved", "delivering"} else "skipped"
    dtitle = ("Spoken alert sent", "बोली गई चेतावनी भेजी") if dstate == "ok" else ("Spoken alert", "बोली गई चेतावनी")
    add("deliver", "system", *dtitle, "Polly (Kajal, hi-IN) · Telegram", dstate,
        dfacts, "Replays go to the stub channel only." if a.replay else "",
        "रीप्ले सिर्फ़ नकली चैनल पर जाते हैं।" if a.replay else "")
    return rounds


def traces(repo: Repo, limit: int = 5) -> list[dict[str, Any]]:
    out = []
    for a in repo.list_alerts(limit=max(1, min(limit, 10))):
        timeline = [(e.step, e.at) for e in repo.list_timeline(a.id)]
        out.append({
            "alert_id": a.id, "village_id": a.village_id, "village_name": a.village_name,
            "village_name_hi": a.village_name_hi, "level": a.level, "previous_level": a.previous_level,
            "status": a.status, "created_at": a.created_at, "replay": a.replay,
            "drill": bool((a.decision_trace or {}).get("drill")),
            "reasoning_model": a.reasoning_model,
            "rounds": trace_rounds(a, timeline),
        })
    return out


# -- sensors ------------------------------------------------------------------------
def _thin(points: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    if len(points) <= n:
        return points
    step = -(-len(points) // n)
    out = points[::step]
    if out[-1] is not points[-1]:
        out.append(points[-1])
    return out


def _gauge_village(v: Village, readings, latest, findings, now) -> dict[str, Any]:
    g = v.gauge
    assert g is not None
    fresh = risk_rules.gauge_is_fresh(latest, now)
    age = round((now - clock.parse(latest.at)).total_seconds() / 60, 1) if latest else None
    return {
        "id": v.id, "name": v.name, "name_hi": v.name_hi, "level": v.level,
        "gauge": {"device_id": g.device_id, "watch_cm": g.watch_cm, "warning_cm": g.warning_cm,
                  "critical_cm": g.critical_cm, "installed": g.installed},
        "latest": None if latest is None else {
            "at": latest.at, "water_level_cm": latest.water_level_cm, "battery_v": latest.battery_v,
            "rssi": latest.rssi, "simulated": latest.simulated, "transport": latest.transport,
            "received_at": latest.received_at,
        },
        "age_minutes": age,
        "fresh": fresh,
        "gauge_level": risk_rules.gauge_level(latest.water_level_cm, g) if latest and fresh else None,
        "readings_24h": len(readings),
        "simulated": bool(latest.simulated) if latest else g.device_id.endswith("-sim"),
        "series": _thin([{"at": r.at, "cm": r.water_level_cm} for r in readings], SERIES_POINTS),
        "findings": [watch.as_dict(f) for f in findings],
    }


def sensors(repo: Repo) -> dict[str, Any]:
    now = clock.now()
    scan = watch.scan(repo, now)
    villages = {v.id: v for v in repo.list_villages()}
    rows = [_gauge_village(villages[vid], readings, latest, findings, now)
            for vid, (readings, latest, findings) in scan.items()]
    transports: dict[str, int] = {}
    for readings, _, _ in scan.values():
        for r in readings:
            key = r.transport or "unrecorded"
            transports[key] = transports.get(key, 0) + 1
    findings = [f for r in rows for f in r["findings"]]
    since = now - timedelta(hours=watch.WINDOW_HOURS)
    return {
        "generated_at": clock.iso(now),
        "window_start": clock.iso(since),
        "fresh_minutes": risk_rules.GAUGE_FRESH_MINUTES,
        "readings_24h": sum(r["readings_24h"] for r in rows),
        "by_transport": transports,
        "gauges": len(rows),
        "fresh_gauges": sum(1 for r in rows if r["fresh"]),
        "installed_gauges": sum(1 for r in rows if r["gauge"]["installed"]),
        "villages": rows,
        "watch": {"checks": watch.CHECKS, "findings": findings,
                  "thresholds": {"stale_minutes": watch.STALE_MINUTES, "flat_min_readings": watch.FLAT_MIN_READINGS,
                                 "jump_cm_per_min": watch.JUMP_CM_PER_MIN, "low_battery_v": watch.LOW_BATTERY_V}},
        "level_names": {lvl: {"en": hi.LEVEL_EN[lvl], "hi": hi.LEVEL_HI[lvl]} for lvl in hi.LEVEL_EN},
    }
