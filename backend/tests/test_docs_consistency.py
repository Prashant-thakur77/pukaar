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
