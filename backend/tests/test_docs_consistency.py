"""Numbers the docs state about the stack, checked against infra/template.yaml.

README.md, docs/DEPLOY.md and the submission docs say how many Lambda functions and CloudWatch
alarms the stack has ("nine alarms", "4 container functions", "the five Lambdas"). Add a function
or an alarm to the template without updating them and this test names each stale line.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from test_template_safety import RES

ROOT = Path(__file__).resolve().parents[2]
DOCS = [ROOT / "README.md", ROOT / "docs" / "DEPLOY.md", *sorted((ROOT / "docs" / "submission").glob("*.md"))]

WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
NUMBER = r"(?P<n>\d+|" + "|".join(WORDS) + r")"
# A number, then up to three qualifying words, then the plural noun: "nine alarms", "9 CloudWatch alarms",
# "4 container functions", "the four Lambda functions", "the five Lambdas".
QUALIFIER = r"(?:(?:AWS|Lambda|container|container-image|CloudWatch|deployed)\s+){0,3}"
PATTERNS = {
    "alarms": re.compile(rf"\b{NUMBER}\s+{QUALIFIER}alarms\b", re.IGNORECASE),
    "functions": re.compile(rf"\b{NUMBER}\s+{QUALIFIER}(?:functions|Lambdas)\b", re.IGNORECASE),
}
# Sentences about AWS quotas, not about this stack ("the free tier covers ten alarms").
NOT_ABOUT_US = re.compile(r"free tier", re.IGNORECASE)


def _template_counts() -> dict[str, int]:
    types = [r.get("Type") for r in RES.values()]
    return {
        "alarms": sum(1 for t in types if t == "AWS::CloudWatch::Alarm"),
        "functions": sum(1 for t in types if t in {"AWS::Serverless::Function", "AWS::Lambda::Function"}),
    }


def _value(token: str) -> int:
    return int(token) if token.isdigit() else WORDS[token.lower()]


def _claims(kind: str) -> list[tuple[str, int, int, str]]:
    """(file, line number, number stated, the matched text) for every claim of this kind."""
    out = []
    for path in DOCS:
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in PATTERNS[kind].finditer(line):
                before = line[max(0, m.start() - 40):m.start()]
                if NOT_ABOUT_US.search(before):
                    continue
                out.append((str(path.relative_to(ROOT)), no, _value(m.group("n")), m.group(0)))
    return out


def test_template_has_the_resources_counted():
    counts = _template_counts()
    assert counts["alarms"] > 0 and counts["functions"] > 0


@pytest.mark.parametrize("kind", ["alarms", "functions"])
def test_docs_state_the_template_counts(kind):
    expected = _template_counts()[kind]
    claims = _claims(kind)
    assert claims, f"no doc states how many {kind} the stack has; the pattern may need a new phrasing"
    stale = [f"{f}:{no}: '{text}' says {n}, template has {expected}" for f, no, n, text in claims if n != expected]
    assert not stale, "\n".join(stale)


@pytest.mark.parametrize(("text", "kind", "n"), [
    ("Nine alarms, one dashboard", "alarms", 9),
    ("and 9 CloudWatch alarms watch it all", "alarms", 9),
    ("Lambda (4 container functions)", "functions", 4),
    ("the four Lambda functions are container images", "functions", 4),
    ("from the five Lambdas, whose roles", "functions", 5),
    ("Lambda (5 functions, container images", "functions", 5),
])
def test_the_patterns_read_digits_and_words(text, kind, n):
    m = PATTERNS[kind].search(text)
    assert m is not None and _value(m.group("n")) == n


@pytest.mark.parametrize(("text", "kind"), [
    ("one IAM role per function", "functions"),
    ("(one function, dispatch on `step`)", "functions"),
    ("each with an alarm", "alarms"),
])
def test_the_patterns_skip_other_uses(text, kind):
    assert PATTERNS[kind].search(text) is None


# -- docs/RUNBOOK.md: one section per alarm --------------------------------------------------------
RUNBOOK = ROOT / "docs" / "RUNBOOK.md"
RUNBOOK_PARTS = ("**What it means.**", "**First 3 checks.**", "**Fix.**", "**Who to call.**", "**Tell the DDMA?**")


def _alarm_suffixes() -> dict[str, str]:
    """Alarm resource -> the part of its name after 'pukaar-${Stage}-'."""
    out = {}
    for name, res in RES.items():
        if res.get("Type") != "AWS::CloudWatch::Alarm":
            continue
        alarm = res["Properties"]["AlarmName"]
        alarm = alarm["Fn::Sub"] if isinstance(alarm, dict) else alarm
        assert alarm.startswith("pukaar-${Stage}-"), f"{name}: AlarmName {alarm!r} does not follow pukaar-${{Stage}}-<name>"
        out[name] = alarm.removeprefix("pukaar-${Stage}-")
    return out


def _runbook_sections() -> dict[str, str]:
    """'model-errors' -> that section's text, for every '### pukaar-<stage>-model-errors' heading."""
    text = RUNBOOK.read_text(encoding="utf-8")
    parts = re.split(r"^### pukaar-<stage>-([a-z0-9-]+)\s*$", text, flags=re.MULTILINE)
    return {parts[i]: parts[i + 1].split("\n## ", 1)[0] for i in range(1, len(parts), 2)}


def test_every_alarm_has_a_runbook_section():
    sections = _runbook_sections()
    missing = [f"{res} (pukaar-<stage>-{suffix})" for res, suffix in _alarm_suffixes().items() if suffix not in sections]
    assert not missing, "docs/RUNBOOK.md has no section for: " + ", ".join(missing)


def test_runbook_has_no_section_for_an_alarm_that_is_gone():
    known = set(_alarm_suffixes().values())
    stale = [s for s in _runbook_sections() if s not in known]
    assert not stale, "docs/RUNBOOK.md describes alarms not in the template: " + ", ".join(stale)


def test_each_runbook_section_says_what_to_do():
    for suffix, body in _runbook_sections().items():
        missing = [p for p in RUNBOOK_PARTS if p not in body]
        assert not missing, f"pukaar-<stage>-{suffix}: missing {', '.join(missing)}"
        checks = body.split("**First 3 checks.**", 1)[1].split("**Fix.**", 1)[0]
        assert re.search(r"^\s*3\. ", checks, re.MULTILINE), f"pukaar-<stage>-{suffix}: needs three numbered checks"


def test_runbook_covers_the_routine_work():
    text = RUNBOOK.read_text(encoding="utf-8")
    for heading in ("## Drills", "## Phone-number hygiene", "## Consent records", "## Secret rotation",
                    "## Monsoon pre-season checklist"):
        assert heading in text, heading
    for secret in ("telegram_token", "VAPID", "voice_webhook_key", "Exotel"):
        assert secret in text, secret
    assert "Digital Personal Data Protection Act" in text and "डेटा संरक्षण बोर्ड" in text  # notice in both languages
