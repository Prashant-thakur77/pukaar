"""A real Strands agent driven by a scripted model: the Cedar hook allows
read-only tools, cancels anything else, and the typed draft comes back."""

import json

from strands import Agent, tool
from strands.models.model import Model

from Pukaar.llm.bedrock import AlertDraft
from Pukaar.llm.tools import DataTools
from Pukaar.policy.hook import ToolGuard


class ScriptedModel(Model):
    """Plays back one tool call per turn, in Bedrock ConverseStream event shape."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.seen_tool_results = []

    def get_config(self):
        return {}

    def update_config(self, **kwargs):
        pass

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        for m in messages:
            for block in m.get("content", []):
                if "toolResult" in block:
                    self.seen_tool_results.append(block["toolResult"])
        name, args = self.turns.pop(0)
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t-{len(self.turns)}", "name": name}}}}
        yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}


DRAFT = {"time_window_hi": "अगले 24 घंटों में", "advice_hi": "नाले से दूर रहें।", "advice_en": "Keep away from the stream.",
         "reason_en": "River peak above the warning threshold.", "evidence_ids": []}


def run(repo, turns, extra_tools=()):
    trace = []
    model = ScriptedModel(turns)
    tools = DataTools(repo).strands_tools(["get_village_risk"]) + list(extra_tools)
    agent = Agent(model=model, tools=tools, hooks=[ToolGuard("drafting-agent", "AlertDraft", trace, repo=repo)],
                  callback_handler=None)
    result = agent("draft", structured_output_model=AlertDraft)
    return result, trace, model


def test_read_only_tool_runs_and_typed_output_returns(repo, frozen):
    result, trace, model = run(repo, [("get_village_risk", {"village_id": "thunag"}), ("AlertDraft", DRAFT)])
    assert isinstance(result.structured_output, AlertDraft)
    assert trace[0]["name"] == "get_village_risk" and trace[0]["decision"] == "allow"
    assert "Thunag" in trace[0]["output_summary"]
    assert [r.decision for r in repo.list_audit("2026-07-01", "tool:get_village_risk")] == ["allow"]


def test_tool_outside_the_allowlist_is_cancelled_and_audited(repo, frozen):
    sent = []

    @tool
    def send_alert(text: str) -> str:
        """Send an alert to every phone.

        Args:
            text: the message
        """
        sent.append(text)
        return "sent"

    result, trace, model = run(repo, [("send_alert", {"text": "evacuate"}), ("AlertDraft", DRAFT)], [send_alert])
    assert sent == []
    assert trace[0] == {"name": "send_alert", "input": {"text": "evacuate"}, "output_summary": trace[0]["output_summary"],
                        "decision": "deny"}
    assert any("Denied by policy" in json.dumps(r) for r in model.seen_tool_results)
    assert [r.decision for r in repo.list_audit("2026-07-01", "tool:send_alert")] == ["deny"]
