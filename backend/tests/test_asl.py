"""Offline checks of infra/approval.asl.json (the approval state machine).

Self-contained: a tiny interpreter walks the definition with a fake workflow
Lambda, so the paths of PLAN.md section 9 are tested without AWS.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ASL_PATH = Path(__file__).resolve().parents[2] / "infra" / "approval.asl.json"
SUBSTITUTIONS = {
    "WorkflowFunctionArn": "arn:aws:lambda:us-east-1:123456789012:function:pukaar-workflow-test",
    "ApprovalTimeoutSeconds": "600",
    "AckWaitSeconds": "300",
}
TERMINAL_TYPES = {"Succeed", "Fail"}
UNCAUGHT_TASKS = {"Failsafe", "Close"}


def load_definition() -> dict:
    raw = ASL_PATH.read_text(encoding="utf-8")
    placeholders = set(re.findall(r"\$\{(\w+)\}", raw))
    assert placeholders == set(SUBSTITUTIONS), placeholders
    for key, value in SUBSTITUTIONS.items():
        raw = raw.replace("${" + key + "}", value)
    return json.loads(raw)


@pytest.fixture(scope="module")
def definition() -> dict:
    return load_definition()


# --- structure ---------------------------------------------------------------


def _targets(state: dict) -> list[str]:
    out = [state[k] for k in ("Next", "Default") if k in state]
    out += [c["Next"] for c in state.get("Choices", [])]
    out += [c["Next"] for c in state.get("Catch", [])]
    return out


def test_targets_exist_and_all_states_reachable(definition):
    states = definition["States"]
    assert definition["StartAt"] in states
    for name, state in states.items():
        for target in _targets(state):
            assert target in states, f"{name} -> missing {target}"
        if state["Type"] not in TERMINAL_TYPES | {"Choice"}:
            assert state.get("End") or "Next" in state, f"{name} has no Next/End"

    seen, todo = set(), [definition["StartAt"]]
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo.extend(_targets(states[name]))
    assert seen == set(states), f"unreachable: {set(states) - seen}"


def test_every_task_catches_all_into_failsafe(definition):
    for name, state in definition["States"].items():
        if state["Type"] != "Task" or name in UNCAUGHT_TASKS:
            continue
        catch_all = [
            c for c in state.get("Catch", []) if "States.ALL" in c["ErrorEquals"]
        ]
        assert catch_all and catch_all[-1]["Next"] == "Failsafe", name
        assert state["Catch"][-1] is catch_all[-1], f"{name}: States.ALL must be last"


def test_timeout_path_and_execution_limit(definition):
    states = definition["States"]
    assert definition["TimeoutSeconds"] == 7200
    ask = states["AskOfficer"]
    assert ask["Resource"].endswith(":lambda:invoke.waitForTaskToken")
    assert ask["Parameters"]["Payload"]["task_token.$"] == "$$.Task.Token"
    assert ask["TimeoutSecondsPath"] == "$.config.approval_timeout_seconds"
    first = ask["Catch"][0]
    assert first["ErrorEquals"] == ["States.Timeout"]
    assert states[first["Next"]]["Result"] == {"decision": "timeout"}
    assert states["WaitForAcks"]["SecondsPath"] == "$.config.ack_wait_seconds"


def test_every_task_names_a_contract_step(definition):
    steps = {
        "draft",
        "ask_officer",
        "next_officer",
        "auto_send",
        "expire",
        "deliver",
        "recall",
        "close",
        "failsafe",
    }
    used = {
        s["Parameters"]["Payload"]["step"]
        for s in definition["States"].values()
        if s["Type"] == "Task"
    }
    assert used == steps


# --- tiny interpreter ----------------------------------------------------------

_MISSING = object()


class TaskFailed(Exception):
    def __init__(self, error: str, cause: str = "") -> None:
        super().__init__(error)
        self.error, self.cause = error, cause


def _get(data, path: str, context: dict):
    if path.startswith("$$."):
        data, path = context, "$" + path[2:]
    if path == "$":
        return data
    cur = data
    for part in path[2:].split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _must(data, path, context):
    value = _get(data, path, context)
    if value is _MISSING:
        raise AssertionError(
            f"States.Runtime: {path} not found"
        )  # uncatchable in AWS too
    return value


def _intrinsic(expr: str):
    m = re.fullmatch(r"States\.StringToJson\('(.*)'\)", expr)
    assert m, f"unsupported intrinsic {expr}"
    return json.loads(m.group(1))


def _resolve(template, data, context):
    if isinstance(template, dict):
        out = {}
        for key, value in template.items():
            if key.endswith(".$"):
                out[key[:-2]] = (
                    _intrinsic(value)
                    if value.startswith("States.")
                    else _must(data, value, context)
                )
            else:
                out[key] = _resolve(value, data, context)
        return out
    if isinstance(template, list):
        return [_resolve(v, data, context) for v in template]
    return template


def _put(data: dict, path: str, value) -> dict:
    if path == "$":
        return value
    keys = path[2:].split(".")
    cur = data
    for key in keys[:-1]:
        cur = cur.setdefault(key, {})
    cur[keys[-1]] = value
    return data


def _choice(rule: dict, data) -> bool:
    if "And" in rule:
        return all(_choice(r, data) for r in rule["And"])
    if "Or" in rule:
        return any(_choice(r, data) for r in rule["Or"])
    if "Not" in rule:
        return not _choice(rule["Not"], data)
    value = _get(data, rule["Variable"], {})
    if "IsPresent" in rule:
        return (value is not _MISSING) == rule["IsPresent"]
    if value is _MISSING:
        raise AssertionError(f"States.Runtime: {rule['Variable']} not found")
    for op, fn in {
        "StringEquals": lambda a, b: isinstance(a, str) and a == b,
        "BooleanEquals": lambda a, b: isinstance(a, bool) and a == b,
        "NumericGreaterThan": lambda a, b: isinstance(a, (int, float)) and a > b,
    }.items():
        if op in rule:
            return fn(value, rule[op])
    raise AssertionError(f"unsupported choice rule {rule}")


def run(definition: dict, execution_input: dict, fake) -> tuple[list[str], dict]:
    """Walk the machine; fake(payload) returns a step result or raises TaskFailed."""
    states, name, data = (
        definition["States"],
        definition["StartAt"],
        dict(execution_input),
    )
    steps: list[str] = []
    for _ in range(200):
        state = states[name]
        kind = state["Type"]
        if kind == "Pass":
            effective = _get(data, state.get("InputPath", "$"), {})
            if "Parameters" in state:
                effective = _resolve(state["Parameters"], effective, {})
            if "Result" in state:
                effective = state["Result"]
            data = _put(
                data, state.get("ResultPath", "$"), json.loads(json.dumps(effective))
            )
        elif kind == "Task":
            context = {"Task": {"Token": f"token-{len(steps)}"}}
            params = _resolve(state["Parameters"], data, context)
            payload = params["Payload"]
            steps.append(payload["step"])
            try:
                result = fake(payload)
            except TaskFailed as exc:
                handler = next(
                    (
                        c
                        for c in state.get("Catch", [])
                        if exc.error in c["ErrorEquals"]
                        or "States.ALL" in c["ErrorEquals"]
                    ),
                    None,
                )
                if handler is None:
                    return steps, {"status": "FAILED", "error": exc.error}
                data = _put(
                    data,
                    handler.get("ResultPath", "$"),
                    {"Error": exc.error, "Cause": exc.cause},
                )
                name = handler["Next"]
                continue
            if state["Resource"].endswith(".waitForTaskToken"):
                response = result  # callback output is used as-is
            else:
                response = {"Payload": result, "StatusCode": 200}
                if "ResultSelector" in state:
                    response = _resolve(state["ResultSelector"], response, {})
            data = _put(data, state.get("ResultPath", "$"), response)
        elif kind == "Choice":
            name = (
                next((c["Next"] for c in state["Choices"] if _choice(c, data)), None)
                or state["Default"]
            )
            continue
        elif kind == "Wait":
            assert isinstance(_must(data, state["SecondsPath"], {}), int)
        elif kind in TERMINAL_TYPES:
            return steps, {
                "status": "SUCCEEDED" if kind == "Succeed" else "FAILED",
                "data": data,
            }
        if state.get("End"):
            return steps, {"status": "SUCCEEDED", "data": data}
        name = state["Next"]
    raise AssertionError("state machine did not finish in 200 transitions")


class FakeWorkflow:
    """Fake workflow Lambda. `decisions` answers ask_officer per call."""

    def __init__(self, level="warning", officers=2, decisions=(), fail_step=None):
        self.level, self.officers, self.fail_step = level, officers, fail_step
        self.decisions = list(decisions)
        self.calls: list[dict] = []

    def __call__(self, payload: dict):
        self.calls.append(payload)
        step, alert_id = payload["step"], payload["alert_id"]
        if step == self.fail_step:
            raise TaskFailed("RuntimeError", f"forced failure in {step}")
        if step == "draft":
            return {
                "alert_id": alert_id,
                "level": self.level,
                "officer_count": self.officers,
                "recipients_count": 3,
            }
        if step == "ask_officer":
            assert payload["task_token"].startswith("token-")
            decision = self.decisions.pop(0)
            if decision == "timeout":
                raise TaskFailed("States.Timeout")
            return {
                "decision": decision,
                "by": f"officer{payload['officer_index'] + 1}",
            }
        if step == "next_officer":
            nxt = payload["officer_index"] + 1
            has_next = nxt < self.officers
            return {
                "has_next": has_next,
                "officer_index": nxt if has_next else payload["officer_index"],
                "level": self.level,
            }
        if step == "close":
            return {"alert_id": alert_id, "status": payload["outcome"]}
        return {"alert_id": alert_id, "step": step}


START = {"alert_id": "01TESTALERT", "village_id": "thunag", "level": "warning"}


def _run(definition, fake, level="warning"):
    return run(definition, {**START, "level": level}, fake)


def test_approve(definition):
    fake = FakeWorkflow(decisions=["approved"])
    steps, result = _run(definition, fake)
    assert steps == ["draft", "ask_officer", "deliver", "recall", "close"]
    assert result["status"] == "SUCCEEDED"
    assert fake.calls[-1]["outcome"] == "delivered"
    assert result["data"]["alert_id"] == "01TESTALERT"
    assert result["data"]["village_id"] == "thunag"


def test_decline(definition):
    fake = FakeWorkflow(decisions=["declined"])
    steps, _ = _run(definition, fake)
    assert steps == ["draft", "ask_officer", "close"]
    assert fake.calls[-1]["outcome"] == "declined"


def test_timeout_then_next_officer_approves(definition):
    fake = FakeWorkflow(decisions=["timeout", "approved"])
    steps, _ = _run(definition, fake)
    assert steps == [
        "draft",
        "ask_officer",
        "next_officer",
        "ask_officer",
        "deliver",
        "recall",
        "close",
    ]
    asks = [c for c in fake.calls if c["step"] == "ask_officer"]
    assert [a["officer_index"] for a in asks] == [0, 1]
    assert asks[0]["task_token"] != asks[1]["task_token"]
    assert fake.calls[-1]["outcome"] == "delivered"


def test_all_timeout_critical_auto_sends(definition):
    fake = FakeWorkflow(level="critical", decisions=["timeout", "timeout"])
    steps, _ = _run(definition, fake, level="critical")
    assert steps == [
        "draft",
        "ask_officer",
        "next_officer",
        "ask_officer",
        "next_officer",
        "auto_send",
        "deliver",
        "recall",
        "close",
    ]
    assert fake.calls[-1]["outcome"] == "auto_sent_unapproved"


def test_all_timeout_warning_expires(definition):
    fake = FakeWorkflow(level="warning", decisions=["timeout", "timeout"])
    steps, _ = _run(definition, fake)
    assert steps == [
        "draft",
        "ask_officer",
        "next_officer",
        "ask_officer",
        "next_officer",
        "expire",
        "close",
    ]
    assert fake.calls[-1]["outcome"] == "expired"


def test_no_officers_critical_auto_sends(definition):
    fake = FakeWorkflow(level="critical", officers=0)
    steps, _ = _run(definition, fake, level="critical")
    assert steps == ["draft", "auto_send", "deliver", "recall", "close"]


@pytest.mark.parametrize("fail_step", ["draft", "ask_officer", "deliver", "recall"])
def test_forced_error_goes_to_failsafe_then_close(definition, fail_step):
    fake = FakeWorkflow(decisions=["approved"], fail_step=fail_step)
    steps, result = _run(definition, fake)
    assert steps[-2:] == ["failsafe", "close"]
    assert steps.index(fail_step) == len(steps) - 3
    failsafe = fake.calls[-2]
    assert failsafe["error"]["Error"] == "RuntimeError"
    assert fake.calls[-1]["outcome"] == "failsafe"
    assert result["status"] == "SUCCEEDED"


def test_unknown_decision_goes_to_failsafe(definition):
    fake = FakeWorkflow(decisions=["maybe"])
    steps, _ = _run(definition, fake)
    assert steps == ["draft", "ask_officer", "failsafe", "close"]
