"""Strands hook: every agent tool call passes the Cedar guard first."""

from __future__ import annotations

import json
from typing import Any

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookRegistry

from Pukaar.policy.guard import Principal, authorize


class ToolGuard:
    """Denies unknown tools, records an audit row and a visible trace entry per call."""

    def __init__(self, agent_name: str, schema_tool: str, trace: list[dict[str, Any]], repo: Any = None) -> None:
        self.principal = Principal(agent_name, "agent")
        self.schema_tool = schema_tool
        self.trace = trace
        self.repo = repo

    def register_hooks(self, registry: HookRegistry, **_: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before)
        registry.add_callback(AfterToolCallEvent, self.after)

    def before(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use.get("name", "")
        if name == self.schema_tool:
            return  # the structured-output tool is not a data tool
        decision = authorize(self.principal, "use_tool", "tool", name, repo=self.repo)
        self.trace.append({"name": name, "input": event.tool_use.get("input", {}), "output_summary": "",
                           "decision": "allow" if decision.allowed else "deny"})
        if not decision.allowed:
            event.cancel_tool = f"Denied by policy: {decision.reason}"

    def after(self, event: AfterToolCallEvent) -> None:
        name = event.tool_use.get("name", "")
        if name == self.schema_tool or not self.trace:
            return
        entry = next((t for t in reversed(self.trace) if t["name"] == name and not t["output_summary"]), None)
        if entry is None:
            return
        content = (event.result or {}).get("content", [])
        text = " ".join(str(c.get("text", c.get("json", ""))) for c in content if isinstance(c, dict))
        entry["output_summary"] = text[:400] if text else json.dumps(event.result, default=str)[:400]
