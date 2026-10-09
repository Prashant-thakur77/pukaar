"""BedrockLLM failure handling and the draft checker, with a fake Strands agent."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from Pukaar.llm.bedrock import AlertDraft, BedrockLLM, ReportFields
from Pukaar.services.drafting import check_draft, draft_alert


class Throttled(Exception):
    pass


def llm_with(behaviour):
    """behaviour(region) -> structured output, or raises."""
    calls = []

    def factory(region, system, tools, hooks, max_tokens, temperature, timeout):
        def run(prompt, **kwargs):
            calls.append(region)
            out = behaviour(region)
            return SimpleNamespace(structured_output=out)

        return run

    llm = BedrockLLM(agent_factory=factory)
    llm.settings = replace(llm.settings, llm_enabled=True)
    return llm, calls


FIELDS = ReportFields(report_type="road_cut", severity="medium", summary_en="Road cut", reply_hi="धन्यवाद")


def test_success_returns_typed_output():
    llm, calls = llm_with(lambda region: FIELDS)
    assert llm.structure_report("सड़क बंद", "Thunag")["report_type"] == "road_cut"
    assert calls == ["us-east-1"]


def test_throttling_fails_over_to_second_region_once():
    def behaviour(region):
        if region == "us-east-1":
            raise Throttled("ThrottlingException: Too many requests")
        return FIELDS

    llm, calls = llm_with(behaviour)
    assert llm.structure_report("x", "Thunag") is not None
    assert calls == ["us-east-1", "us-west-2"]


@pytest.mark.parametrize("error", ["AccessDeniedException: no model access", "ValidationException: bad input"])
def test_non_regional_errors_return_none_without_failover(error):
    def behaviour(region):
        raise RuntimeError(error)

    llm, calls = llm_with(behaviour)
    assert llm.structure_report("x", "Thunag") is None
    assert calls == ["us-east-1"]


def test_malformed_output_returns_none():
    llm, _ = llm_with(lambda region: {"not": "typed"})
    assert llm.structure_report("x", "Thunag") is None


def test_both_regions_down_returns_none():
    def behaviour(region):
        raise TimeoutError("Read timed out")

    llm, calls = llm_with(behaviour)
    assert llm.structure_report("x", "Thunag") is None and len(calls) == 2


def _draft(**kw):
    base = dict(time_window_hi="अगले 24 घंटों में", advice_hi="नाले के पास न जाएँ।", advice_en="Keep away from the stream.",
                reason_en="River peak 2.94 m3/s is above the warning threshold 2.5.", evidence_ids=[])
    base.update(kw)
    return AlertDraft(**base)


TRACE = {"evidence": [{"discharge_peak": 2.94, "thresholds": {"warning": 2.5}}]}


def test_checker_passes_numbers_from_the_trace(repo):
    v = repo.get_village("thunag")
    assert check_draft(_draft(), v, TRACE, ["Gohar"]).passed


def test_checker_rejects_invented_numbers_places_and_tone(repo):
    v = repo.get_village("thunag")
    assert "numbers" in check_draft(_draft(reason_en="About 300 homes are at risk."), v, TRACE, []).reason
    # Devanagari digits are normalised before the check.
    assert not check_draft(_draft(advice_hi="३०० घर ख़तरे में।"), v, TRACE, []).passed
    assert "another place" in check_draft(_draft(advice_en="Move towards Gohar."), v, TRACE, ["Gohar"]).reason
    assert not check_draft(_draft(advice_en="There is no danger tonight."), v, TRACE, []).passed
    assert not check_draft(_draft(advice_hi="Stay away"), v, TRACE, []).passed


def test_model_draft_is_wrapped_in_fixed_safety_text(repo):
    class GoodLLM:
        model_name = "us.amazon.nova-2-lite-v1:0"

        def draft_alert(self, *a, **k):
            return _draft()

    v = repo.get_village("thunag")
    out = draft_alert(v, "warning", TRACE, repo, GoodLLM())
    assert out.reasoning_model == "us.amazon.nova-2-lite-v1:0" and out.check.passed
    assert out.text_hi.endswith("आपात स्थिति में 112 पर कॉल करें।")


def test_rejected_draft_falls_back_to_template(repo):
    class BadLLM:
        model_name = "m"

        def draft_alert(self, *a, **k):
            return _draft(reason_en="Expect 500 mm of rain.")

    v = repo.get_village("thunag")
    out = draft_alert(v, "warning", TRACE, repo, BadLLM())
    assert out.reasoning_model == "rule-fallback" and "rejected" in out.check.reason
