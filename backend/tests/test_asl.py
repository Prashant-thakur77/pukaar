"""Offline checks of infra/approval.asl.json (the approval state machine).

Self-contained: a tiny interpreter walks the definition with a fake workflow
Lambda, so every approval path is tested without AWS.
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
    "VoiceRetrySeconds": "600",
}
TERMINAL_TYPES = {"Succeed", "Fail"}
UNCAUGHT_TASKS = {"Failsafe", "Close"}
# SoundSirens catches everything into Deliver, never the failsafe: a siren problem never blocks people.
TO_DELIVER_TASKS = {"SoundSirens"}


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
    """Every task, and the delivery Map, ends in the failsafe on any error. The delivery's own states go
    through DeliveryBroken, which sends the failsafe's own delivery to close instead (no loop)."""
    states = definition["States"]
    for name, state in states.items():
        if state["Type"] not in {"Task", "Map"} or name in UNCAUGHT_TASKS | TO_DELIVER_TASKS:
            continue
        catch_all = [
            c for c in state.get("Catch", []) if "States.ALL" in c["ErrorEquals"]
        ]
        assert catch_all and catch_all[-1]["Next"] in {"Failsafe", "DeliveryBroken"}, name
        assert state["Catch"][-1] is catch_all[-1], f"{name}: States.ALL must be last"
    broken = states["DeliveryBroken"]
    assert broken["Default"] == "Failsafe"
    assert [c["Next"] for c in broken["Choices"]] == ["OutcomeFailsafe"]
    assert states["FailsafeBatches"]["Default"] == "OutcomeFailsafe"


def test_timeout_path_and_execution_limit(definition):
    states = definition["States"]
    assert definition["TimeoutSeconds"] == 7200
    ask = states["AskOfficer"]
    assert ask["Resource"].endswith(":lambda:invoke.waitForTaskToken")
    assert ask["Parameters"]["Payload"]["task_token.$"] == "$$.Task.Token"
    # The window is split in two: ask, then (no decision) remind the same officer, then time out.
    assert ask["TimeoutSecondsPath"] == "$.timers.nudge_after_seconds"
    first = ask["Catch"][0]
    assert first["ErrorEquals"] == ["States.Timeout"] and first["Next"] == "NudgeOfficer"
    nudge = states["NudgeOfficer"]
    assert nudge["Resource"].endswith(":lambda:invoke.waitForTaskToken")
    assert nudge["Parameters"]["Payload"]["task_token.$"] == "$$.Task.Token"
    assert nudge["TimeoutSecondsPath"] == "$.timers.nudge_wait_seconds"
    assert nudge["Catch"][0]["ErrorEquals"] == ["States.Timeout"]
    assert states[nudge["Catch"][0]["Next"]]["Result"] == {"decision": "timeout"}
    assert nudge["Next"] == ask["Next"] == "RouteDecision"
    assert states["WaitForAcks"]["SecondsPath"] == "$.config.ack_wait_seconds"
    assert states["WaitBeforeRecall"]["SecondsPath"] == "$.config.voice_retry_seconds"
    # The timers come from draft, and for every later officer from next_officer (the level may have risen).
    assert states["DraftAlert"]["Next"] == "SetTimers" and states["SetTimers"]["ResultPath"] == "$.timers"
    assert states["UseNextOfficer"]["Next"] == "UseNextTimers" and states["UseNextTimers"]["Next"] == "AskOfficer"
    assert states["UseNextTimers"]["Parameters"]["nudge_after_seconds.$"] == "$.next.result.nudge_after_seconds"


def test_delivery_fans_out_in_a_bounded_map(definition):
    states = definition["States"]
    m = states["DeliverBatches"]
    assert m["Type"] == "Map" and m["ItemProcessor"]["ProcessorConfig"]["Mode"] == "INLINE"
    assert m["ItemsPath"] == "$.delivery.result.batches"
    # A fixed number, the same as the workers' share of the rate assumes (PUKAAR_DELIVERY_CONCURRENCY in the
    # template and the code's default): more workers than that would together go over Telegram's limit.
    from Pukaar.core.config import Settings

    from test_template_safety import RES

    env = RES["WorkflowFunction"]["Properties"]["Environment"]["Variables"]
    assert m["MaxConcurrency"] == int(env["PUKAAR_DELIVERY_CONCURRENCY"]) == Settings.delivery_concurrency == 4
    inner = m["ItemProcessor"]["States"]
    assert inner["DeliverBatch"]["Parameters"]["Payload"]["step"] == "deliver_batch"
    # A batch that fails is reported unfinished; it never fails the whole delivery.
    assert inner["DeliverBatch"]["Catch"][-1]["Next"] == "BatchUnfinished"
    assert inner["BatchUnfinished"]["Parameters"] == {"spec.$": "$.item", "unfinished": True}
    payload = inner["DeliverBatch"]["Parameters"]["Payload"]
    assert payload["first.$"] == "$.item.first" and payload["last.$"] == "$.item.last"
    for name in ("Deliver", "Recall", "DeliverDone", "Failsafe"):
        assert states[name]["ResultPath"] == "$.delivery", name
    assert states["Deliver"]["Next"] == states["Recall"]["Next"] == "RunBatches"
    assert states["DeliverDone"]["Next"] == "RunBatches"
    # Every run of the Map first waits out the retry_after Telegram asked for (0 when none).
    assert [c["Next"] for c in states["RunBatches"]["Choices"]] == ["WaitBeforeBatches"]
    assert [c["Next"] for c in states["FailsafeBatches"]["Choices"]] == ["WaitBeforeBatches"]
    assert states["WaitBeforeBatches"]["SecondsPath"] == "$.delivery.result.wait_seconds"
    assert states["WaitBeforeBatches"]["Next"] == "DeliverBatches"


def test_every_task_names_a_contract_step(definition):
    steps = {
        "draft",
        "ask_officer",
        "nudge_officer",
        "nudge_officer",
        "next_officer",
        "auto_send",
        "unanswered",
        "expire",
        "deliver",
        "recall",
        "close",
        "failsafe",
        "sirens",
    }
    steps |= {"deliver_done", "deliver_batch"}
    every = list(definition["States"].values())
    for s in list(every):
        if s["Type"] == "Map":
            every += list(s["ItemProcessor"]["States"].values())
    used = {s["Parameters"]["Payload"]["step"] for s in every if s["Type"] == "Task"}
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
            if "TimeoutSecondsPath" in state:
                timeout = _must(data, state["TimeoutSecondsPath"], {})
                assert isinstance(timeout, int) and timeout > 0
                if hasattr(fake, "timeouts"):
                    fake.timeouts.append((name, timeout))
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
        elif kind == "Map":
            items = _must(data, state["ItemsPath"], {})
            limit = state["MaxConcurrency"]
            assert isinstance(items, list) and isinstance(limit, int) and limit >= 1
            outputs, failed = [], None
            for i, item in enumerate(items):
                context = {"Map": {"Item": {"Value": item, "Index": i}}}
                sub_input = _resolve(state["ItemSelector"], data, context)
                sub_steps, sub = run(state["ItemProcessor"], sub_input, fake)
                steps.extend(sub_steps)
                if sub["status"] != "SUCCEEDED":
                    failed = sub.get("error", "States.TaskFailed")
                    break
                outputs.append(sub["data"])
            if failed is not None:
                handler = next((c for c in state.get("Catch", [])
                                if failed in c["ErrorEquals"] or "States.ALL" in c["ErrorEquals"]), None)
                if handler is None:
                    return steps, {"status": "FAILED", "error": failed}
                data = _put(data, handler.get("ResultPath", "$"), {"Error": failed, "Cause": "map"})
                name = handler["Next"]
                continue
            data = _put(data, state.get("ResultPath", "$"), json.loads(json.dumps(outputs)))
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
    """Fake workflow Lambda. `decisions` answers ask_officer per call.

    Delivery: `batches` extra batches after the deliver step's own (also for recall), and
    `failsafe_batches` for the failsafe; `defer` maps a batch to how many passes it reports sends
    still queued; `broken` batches always fail.
    """

    def __init__(self, level="warning", officers=2, decisions=(), fail_step=None, voice_rounds=0, auto_off=False,
                 batches=0, defer=None, broken=(), max_passes=4, next_level=None, failsafe_batches=0,
                 last_call="timeout"):
        self.level, self.officers, self.fail_step = level, officers, fail_step
        self.auto_off = auto_off  # PUKAAR_CRITICAL_AUTO_SEND=false
        self.decisions = list(decisions)
        self.voice_rounds = voice_rounds  # how many recall results say "again" (another voice round)
        self.batches, self.defer, self.broken = batches, dict(defer or {}), set(broken)
        self.max_passes, self.next_level, self.failsafe_batches = max_passes, next_level, failsafe_batches
        self.last_call = last_call  # the answer to the last call: "timeout", "approved" or "declined"
        self.calls: list[dict] = []
        self.timeouts: list[tuple[str, int]] = []

    @staticmethod
    def _timers(level):
        if level == "critical":
            return {"nudge_after_seconds": 150, "nudge_wait_seconds": 150, "last_call_seconds": 300}
        return {"nudge_after_seconds": 180, "nudge_wait_seconds": 420, "last_call_seconds": 600}

    def _again(self):
        again = bool(self.voice_rounds)
        if again:
            self.voice_rounds -= 1
        return again

    @staticmethod
    def _round(alert_id, mode, n):
        return {"alert_id": alert_id, "mode": mode, "more": True, "pass": 1, "counts": {"sent": 3, "failed": 0},
                "batches": [{"batch": b, "first": f"{b}a", "last": f"{b}z", "mode": mode, "share": min(4, n)}
                            for b in range(1, n + 1)],
                "concurrency": min(4, n), "wait_seconds": 5}

    def __call__(self, payload: dict):
        self.calls.append(payload)
        step, alert_id = payload["step"], payload["alert_id"]
        if step == self.fail_step:
            raise TaskFailed("RuntimeError", f"forced failure in {step}")
        if step == "draft":
            return {"alert_id": alert_id, "level": self.level, "officer_count": self.officers,
                    "recipients_count": 3, **self._timers(self.level)}
        if step in {"ask_officer", "nudge_officer"}:
            assert payload["task_token"].startswith("token-")
            # "timeout": no answer in either half; "nudged:<d>": no answer, then <d> after the reminder.
            decision = self.decisions.pop(0)
            if decision == "timeout" and step == "ask_officer":
                self.decisions.insert(0, "timeout")
            if decision.startswith("nudged:"):
                self.decisions.insert(0, decision.split(":", 1)[1])
                raise TaskFailed("States.Timeout")
            if decision == "timeout":
                raise TaskFailed("States.Timeout")
            return {
                "decision": decision,
                "by": f"officer{payload['officer_index'] + 1}",
            }
        if step == "unanswered":
            assert payload["task_token"].startswith("token-")
            if self.last_call == "timeout":
                raise TaskFailed("States.Timeout")
            return {"decision": self.last_call, "by": "adm_mandi"}
        if step == "next_officer":
            nxt = payload["officer_index"] + 1
            has_next = nxt < self.officers
            level = self.next_level or self.level
            return {"has_next": has_next, "officer_index": nxt if has_next else payload["officer_index"],
                    "level": level, **self._timers(level)}
        if step == "close":
            return {"alert_id": alert_id, "status": payload["outcome"]}
        if step == "auto_send":
            return {"alert_id": alert_id, "mode": "off" if self.auto_off else "auto"}
        if step == "deliver":
            if self.batches:
                return self._round(alert_id, "deliver", self.batches)
            return {"alert_id": alert_id, "mode": "deliver", "more": False, "sent": 3, "failed": 0}
        if step == "failsafe":
            if self.failsafe_batches:
                return {**self._round(alert_id, "failsafe", self.failsafe_batches), "sent": 3}
            return {"alert_id": alert_id, "mode": "failsafe", "more": False, "sent": 3}
        if step == "recall":
            if self.batches:
                return self._round(alert_id, "recall", self.batches)
            return {"alert_id": alert_id, "mode": "recall", "more": False, "resent": 1, "again": self._again()}
        if step == "deliver_batch":
            b = payload["batch"]
            assert payload["mode"] in {"deliver", "recall", "failsafe"} and payload["share"] >= 1
            assert (payload["first"], payload["last"]) == (f"{b}a", f"{b}z")
            if b in self.broken:
                raise TaskFailed("Lambda.Unknown", "the worker stopped")
            deferred = 0
            if self.defer.get(b):
                self.defer[b] -= 1
                deferred = 2
            spec = {"batch": b, "first": payload["first"], "last": payload["last"]}
            return {"spec": spec, "sent": 10 - deferred, "failed": 0, "deferred": deferred, "retry_after": 7}
        if step == "deliver_done":
            todo = [r["spec"] for r in payload["results"] if r.get("unfinished") or r.get("deferred")]
            if todo and payload["pass"] < self.max_passes:
                return {"alert_id": alert_id, "mode": payload["mode"], "more": True, "pass": payload["pass"] + 1,
                        "counts": payload["counts"],
                        "batches": [{"batch": sp["batch"], "first": sp["first"], "last": sp["last"],
                                     "mode": payload["mode"], "share": 1} for sp in todo],
                        "concurrency": 1, "wait_seconds": 7}
            out = {"alert_id": alert_id, "mode": payload["mode"], "more": False}
            if payload["mode"] == "recall":
                out["again"] = self._again()
            return out
        return {"alert_id": alert_id, "step": step}


START = {"alert_id": "01TESTALERT", "village_id": "thunag", "level": "warning"}


def _run(definition, fake, level="warning"):
    return run(definition, {**START, "level": level}, fake)


def test_approve(definition):
    fake = FakeWorkflow(decisions=["approved"])
    steps, result = _run(definition, fake)
    assert steps == ["draft", "ask_officer", "sirens", "deliver", "recall", "close"]
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
        "nudge_officer",
        "next_officer",
        "ask_officer",
        "sirens",
        "deliver",
        "recall",
        "close",
    ]
    asks = [c for c in fake.calls if c["step"] == "ask_officer"]
    assert [a["officer_index"] for a in asks] == [0, 1]
    nudges = [c for c in fake.calls if c["step"] == "nudge_officer"]
    assert [n["officer_index"] for n in nudges] == [0]  # the first officer was reminded before the second was asked
    assert nudges[0]["task_token"] not in {a["task_token"] for a in asks}
    assert asks[0]["task_token"] != asks[1]["task_token"]
    assert fake.calls[-1]["outcome"] == "delivered"


def test_all_timeout_critical_auto_sends(definition):
    fake = FakeWorkflow(level="critical", decisions=["timeout", "timeout"])
    steps, _ = _run(definition, fake, level="critical")
    assert steps == [
        "draft",
        "ask_officer",
        "nudge_officer",
        "next_officer",
        "ask_officer",
        "nudge_officer",
        "next_officer",
        "auto_send",
        "sirens",
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
        "nudge_officer",
        "next_officer",
        "ask_officer",
        "nudge_officer",
        "next_officer",
        "unanswered",
        "expire",
        "close",
    ]
    assert fake.calls[-1]["outcome"] == "expired"
    # The last call waited one more window before the alert expired.
    assert fake.timeouts[-1] == ("LastCall", 600)


def test_no_officers_critical_auto_sends(definition):
    fake = FakeWorkflow(level="critical", officers=0)
    steps, _ = _run(definition, fake, level="critical")
    assert steps == ["draft", "auto_send", "sirens", "deliver", "recall", "close"]


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


def test_voice_recall_rounds_loop_then_close(definition):
    """Unanswered voice calls are tried again after VoiceRetrySeconds while recall says again=true."""
    fake = FakeWorkflow(decisions=["approved"], voice_rounds=2)
    steps, result = _run(definition, fake)
    assert steps == ["draft", "ask_officer", "sirens", "deliver", "recall", "recall", "recall", "close"]
    assert result["status"] == "SUCCEEDED" and fake.calls[-1]["outcome"] == "delivered"


def test_recall_without_again_goes_straight_to_close(definition):
    """A Telegram-only recall result (again false or absent) ends the run."""
    states = definition["States"]
    assert states["Recall"]["Next"] == "RunBatches"
    after = states["AfterDelivery"]
    to_close = [c for c in after["Choices"] if c["Next"] == "Close"]
    assert len(to_close) == 1 and after["Default"] == "OutcomeFailsafe"
    assert definition["States"]["Init"]["Parameters"]["config"]["voice_retry_seconds.$"] == "States.StringToJson('600')"
    fake = FakeWorkflow(decisions=["approved"])
    steps, result = _run(definition, fake)
    assert steps[-2:] == ["recall", "close"] and fake.calls[-1]["outcome"] == "delivered"


# --- delivery at scale --------------------------------------------------------


def test_many_recipients_fan_out_in_batches_then_wait_for_acks(definition):
    """Deliver sends the first batch and returns the rest; the Map runs each once; deliver_done finishes."""
    fake = FakeWorkflow(decisions=["approved"], batches=5)
    steps, result = _run(definition, fake)
    assert steps[:4] == ["draft", "ask_officer", "sirens", "deliver"]
    first_done = steps.index("deliver_done")
    assert steps[4:first_done] == ["deliver_batch"] * 5
    batches = [c["batch"] for c in fake.calls if c["step"] == "deliver_batch"][:5]
    assert batches == [1, 2, 3, 4, 5]
    done = next(c for c in fake.calls if c["step"] == "deliver_done")
    assert done["mode"] == "deliver" and done["pass"] == 1 and done["counts"] == {"sent": 3, "failed": 0}
    assert [r["spec"]["batch"] for r in done["results"]] == [1, 2, 3, 4, 5]
    # then WaitForAcks and the recall, itself batched, then close
    assert steps[first_done + 1] == "recall" and steps[-1] == "close"
    assert result["status"] == "SUCCEEDED" and fake.calls[-1]["outcome"] == "delivered"


def test_a_batch_with_queued_sends_goes_round_again_and_is_never_lost(definition):
    """A Telegram 429 (deferred sends) re-queues that batch only, after wait_seconds."""
    fake = FakeWorkflow(decisions=["approved"], batches=3, defer={2: 2})
    steps, result = _run(definition, fake)
    deliver_part = steps[:steps.index("recall")]
    runs = [c for c in fake.calls if c["step"] == "deliver_batch"]
    assert [c["batch"] for c in runs[:5]] == [1, 2, 3, 2, 2]  # batch 2 twice more, alone
    assert deliver_part.count("deliver_done") == 3
    assert result["status"] == "SUCCEEDED" and fake.calls[-1]["outcome"] == "delivered"


def test_a_stopped_batch_is_unfinished_not_a_failed_execution(definition):
    """A worker that dies is reported unfinished and run again; after the last pass the round finishes
    (deliver_done records who was never reached), and the run does not go to the failsafe."""
    fake = FakeWorkflow(decisions=["approved"], batches=2, broken={1}, max_passes=3)
    steps, result = _run(definition, fake)
    assert "failsafe" not in steps
    dones = [c for c in fake.calls if c["step"] == "deliver_done" and c["mode"] == "deliver"]
    assert [d["pass"] for d in dones] == [1, 2, 3]
    assert dones[0]["results"][0]["unfinished"] is True and dones[0]["results"][0]["spec"]["batch"] == 1
    assert result["status"] == "SUCCEEDED" and fake.calls[-1]["outcome"] == "delivered"


def test_recall_rounds_are_batched_and_still_loop_for_voice(definition):
    fake = FakeWorkflow(decisions=["approved"], batches=2, voice_rounds=1)
    steps, result = _run(definition, fake)
    recall_dones = [c for c in fake.calls if c["step"] == "deliver_done" and c["mode"] == "recall"]
    assert steps.count("recall") == 2 and len(recall_dones) == 2
    assert result["status"] == "SUCCEEDED" and fake.calls[-1]["outcome"] == "delivered"


def test_failsafe_delivery_is_batched_and_cannot_loop(definition):
    """The failsafe's own batches run through the same Map; if that delivery breaks, the run closes."""
    fake = FakeWorkflow(decisions=["approved"], fail_step="deliver", failsafe_batches=2)
    steps, result = _run(definition, fake)
    assert steps[-5:] == ["failsafe", "deliver_batch", "deliver_batch", "deliver_done", "close"]
    assert fake.calls[-1]["outcome"] == "failsafe" and result["status"] == "SUCCEEDED"

    broken = FakeWorkflow(decisions=["approved"], fail_step="deliver_done", failsafe_batches=1, batches=1)
    steps, result = _run(definition, broken)
    assert steps.count("failsafe") == 1  # deliver_done broke in the failsafe's delivery too: no second failsafe
    assert broken.calls[-1]["outcome"] == "failsafe" and result["status"] == "SUCCEEDED"


def test_failsafe_for_an_unknown_alert_closes(definition):
    """failsafe answers {alert_id, sent: 0} for an alert it cannot find: that must close, not deliver."""
    states = definition["States"]
    data = {"delivery": {"result": {"alert_id": "missing", "sent": 0}}}
    assert next((c["Next"] for c in states["FailsafeBatches"]["Choices"] if _choice(c, data)), None) is None
    assert states["FailsafeBatches"]["Default"] == "OutcomeFailsafe"


# --- approval windows ------------------------------------------------------------


def test_critical_windows_are_shorter_and_follow_an_escalation(definition):
    critical = FakeWorkflow(level="critical", decisions=["timeout", "timeout"])
    _run(definition, critical, level="critical")
    assert critical.timeouts == [("AskOfficer", 150), ("NudgeOfficer", 150)] * 2
    warning = FakeWorkflow(decisions=["timeout", "approved"])
    _run(definition, warning)
    assert warning.timeouts[:2] == [("AskOfficer", 180), ("NudgeOfficer", 420)]
    # Raised to critical while the first officer waited: the next officer gets the critical window.
    raised = FakeWorkflow(decisions=["timeout", "approved"], next_level="critical")
    _run(definition, raised)
    assert raised.timeouts == [("AskOfficer", 180), ("NudgeOfficer", 420), ("AskOfficer", 150)]


def test_reminded_officer_approves_in_the_second_half(definition):
    """Night-friendly: the first officer is reminded half-way and approves before the next is asked."""
    fake = FakeWorkflow(decisions=["nudged:approved"])
    steps, _ = _run(definition, fake)
    assert steps == ["draft", "ask_officer", "nudge_officer", "sirens", "deliver", "recall", "close"]
    assert fake.calls[-1]["outcome"] == "delivered"


def test_critical_auto_send_off_expires_without_delivering(definition):
    """PUKAAR_CRITICAL_AUTO_SEND=false (needs DDMA sign-off to turn on): nothing goes out unapproved."""
    fake = FakeWorkflow(level="critical", decisions=["timeout", "timeout"], auto_off=True)
    steps, _ = _run(definition, fake, level="critical")
    assert steps[-4:] == ["auto_send", "unanswered", "expire", "close"] and "deliver" not in steps
    assert fake.calls[-1]["outcome"] == "expired"
    assert fake.timeouts[-1] == ("LastCall", 300)  # the critical window


# --- the last call: nobody answered ------------------------------------------------


def test_the_last_call_waits_for_a_token_and_expires_only_after_it(definition):
    states = definition["States"]
    last = states["LastCall"]
    assert last["Resource"].endswith(":lambda:invoke.waitForTaskToken")
    assert last["Parameters"]["Payload"] == {"step": "unanswered", "alert_id.$": "$.alert_id",
                                             "task_token.$": "$$.Task.Token"}
    assert last["TimeoutSecondsPath"] == "$.timers.last_call_seconds"
    assert last["Catch"][0] == {"ErrorEquals": ["States.Timeout"], "ResultPath": "$.error", "Next": "Expire"}
    assert last["Next"] == "RouteDecision"
    # Every way of nobody answering goes through it: the chain ran out, or critical auto-send is off.
    assert states["IsCritical"]["Default"] == "LastCall" and states["AutoSendOn"]["Default"] == "LastCall"
    assert states["SetTimers"]["Parameters"]["last_call_seconds.$"] == "$.draft.result.last_call_seconds"
    assert states["UseNextTimers"]["Parameters"]["last_call_seconds.$"] == "$.next.result.last_call_seconds"
    # The comment says what the step does: it notifies all officers (workflow/steps.step_unanswered).
    assert "every officer on duty" in last["Comment"] and "ADM or DM" in last["Comment"]
    assert "notify all officers" not in states["Expire"]["Comment"]


@pytest.mark.parametrize("level,auto_off", [("warning", False), ("watch", False), ("critical", True)])
def test_someone_answering_the_last_call_approves_and_it_is_delivered(definition, level, auto_off):
    fake = FakeWorkflow(level=level, decisions=["timeout", "timeout"], auto_off=auto_off, last_call="approved")
    steps, result = _run(definition, fake, level=level)
    assert steps[steps.index("unanswered") + 1:] == ["sirens", "deliver", "recall", "close"]
    assert result["status"] == "SUCCEEDED" and fake.calls[-1]["outcome"] == "delivered"
    declined = FakeWorkflow(level=level, decisions=["timeout", "timeout"], auto_off=auto_off, last_call="declined")
    steps, _ = _run(definition, declined, level=level)
    assert steps[-2:] == ["unanswered", "close"] and declined.calls[-1]["outcome"] == "declined"


def test_no_officer_at_all_still_gets_the_last_call(definition):
    fake = FakeWorkflow(level="warning", officers=0)
    steps, _ = _run(definition, fake)
    assert steps == ["draft", "unanswered", "expire", "close"]


def test_a_broken_last_call_goes_to_the_failsafe(definition):
    fake = FakeWorkflow(level="warning", decisions=["timeout", "timeout"], fail_step="unanswered")
    steps, _ = _run(definition, fake)
    assert steps[-2:] == ["failsafe", "close"] and fake.calls[-1]["outcome"] == "failsafe"


# --- sirens (services/sirens.py): never block or fail the people's delivery ---------------------------
def test_sound_sirens_comes_after_approval_and_auto_send_and_always_reaches_deliver(definition):
    states = definition["States"]
    s = states["SoundSirens"]
    assert states["OutcomeDelivered"]["Next"] == states["OutcomeAutoSent"]["Next"] == "SoundSirens"
    assert s["Next"] == "Deliver" and s["Parameters"]["Payload"]["step"] == "sirens"
    assert s["TimeoutSeconds"] <= 20
    assert [c["Next"] for c in s["Catch"]] == ["Deliver"] and s["Catch"][0]["ErrorEquals"] == ["States.ALL"]
    assert s["ResultPath"] == "$.sirens"  # never overwrites the alert id or the delivery


@pytest.mark.parametrize("level", ["warning", "critical"])
def test_a_sound_sirens_failure_still_delivers(definition, level):
    fake = FakeWorkflow(level=level, decisions=["approved"], fail_step="sirens")
    steps, result = _run(definition, fake, level=level)
    assert steps == ["draft", "ask_officer", "sirens", "deliver", "recall", "close"]
    assert result["status"] == "SUCCEEDED" and fake.calls[-1]["outcome"] == "delivered"
    assert "failsafe" not in steps


def test_auto_sent_critical_passes_through_sound_sirens(definition):
    fake = FakeWorkflow(level="critical", officers=0, fail_step="sirens")
    steps, _ = _run(definition, fake, level="critical")
    assert steps == ["draft", "auto_send", "sirens", "deliver", "recall", "close"]
    assert fake.calls[-1]["outcome"] == "auto_sent_unapproved"
