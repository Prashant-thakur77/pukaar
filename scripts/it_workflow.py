"""Integration test of the approval state machine on the DEPLOYED stack.

Runs real executions for: approve, decline, timeout -> next officer -> approve,
critical auto-send after every officer times out, and forced error -> failsafe.
Each scenario writes its own test village and alert (test=true, replay=false),
starts an execution named after the alert id, drives it through the stored
`task_token`, asserts the final execution status, the states visited and the
alert `status`, then deletes what it wrote.

Deploy with short timers first, or this takes a long time:
    sam deploy --parameter-overrides ApprovalTimeoutSeconds=60 AckWaitSeconds=30
Run:  python scripts/it_workflow.py [scenario ...]
Needs AWS credentials for the stack's account (PUKAAR_STACK, default pukaar-dev).
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

REGION = (
    os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
)
STACK = os.environ.get("PUKAAR_STACK", "pukaar-dev")
OFFICERS = ["officer1", "officer2"]
POLL_SECONDS = 3


@dataclass
class Scenario:
    name: str
    level: str
    answers: list[str]  # what each asked officer does: approved | declined | timeout
    expected_status: str | None  # alert status after Close; None when no alert exists
    expected_states: list[str]  # states that must have been entered
    create_alert: bool = True
    alert_id: str = field(default="")
    village_id: str = field(default="")


SCENARIOS = {
    "approve": Scenario(
        "approve",
        "warning",
        ["approved"],
        "delivered",
        ["AskOfficer", "Deliver", "WaitForAcks", "Recall", "Close"],
    ),
    "decline": Scenario(
        "decline",
        "warning",
        ["declined"],
        "declined",
        ["AskOfficer", "OutcomeDeclined", "Close"],
    ),
    "timeout_next": Scenario(
        "timeout_next",
        "warning",
        ["timeout", "approved"],
        "delivered",
        ["NextOfficer", "UseNextOfficer", "Deliver", "Close"],
    ),
    "critical_auto": Scenario(
        "critical_auto",
        "critical",
        ["timeout", "timeout"],
        "auto_sent_unapproved",
        ["NextOfficer", "AutoSend", "Deliver", "Close"],
    ),
    # No alert item: the draft step fails, so the run must go Failsafe -> Close.
    "forced_error": Scenario(
        "forced_error", "warning", [], None, ["Failsafe", "Close"], create_alert=False
    ),
}


class Stack:
    def __init__(self) -> None:
        cfn = boto3.client("cloudformation", region_name=REGION)
        stack = cfn.describe_stacks(StackName=STACK)["Stacks"][0]
        outputs = {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}
        params = {
            p["ParameterKey"]: p["ParameterValue"] for p in stack.get("Parameters", [])
        }
        self.table = boto3.resource("dynamodb", region_name=REGION).Table(
            outputs["TableName"]
        )
        self.state_machine_arn = outputs["StateMachineArn"]
        self.sfn = boto3.client("stepfunctions", region_name=REGION)
        self.approval_timeout = int(params.get("ApprovalTimeoutSeconds", "600"))
        self.ack_wait = int(params.get("AckWaitSeconds", "300"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def seed(stack: Stack, sc: Scenario) -> None:
    """Write the test village and alert in the shapes of PLAN.md section 6."""
    stack.table.put_item(
        Item={
            "pk": f"VILLAGE#{sc.village_id}",
            "sk": "META",
            "id": sc.village_id,
            "name": f"IT {sc.name}",
            "name_hi": f"IT {sc.name}",
            "district": "test",
            "lat": None,
            "lon": None,
            "coords_verified": False,
            "population": None,
            "officers": OFFICERS,
            "level": sc.level,
            "level_since": now(),
            "calm_sweeps": 0,
            "thresholds": None,
            "replay": False,
            "test": True,
        }
    )
    if sc.create_alert:
        stack.table.put_item(
            Item={
                "pk": f"ALERT#{sc.alert_id}",
                "sk": "META",
                "id": sc.alert_id,
                "village_id": sc.village_id,
                "village_name": f"IT {sc.name}",
                "level": sc.level,
                "previous_level": "watch",
                "status": "drafting",
                "created_at": now(),
                "updated_at": now(),
                "officer_index": 0,
                "token_version": 0,
                "replay": False,
                "test": True,
            }
        )


def cleanup(stack: Stack, sc: Scenario) -> None:
    # Audit rows (AUDIT#date) are append-only by design and are left in place.
    for pk in (f"ALERT#{sc.alert_id}", f"VILLAGE#{sc.village_id}"):
        items = stack.table.query(
            KeyConditionExpression=Key("pk").eq(pk), ProjectionExpression="pk, sk"
        )["Items"]
        with stack.table.batch_writer() as batch:
            for item in items:
                batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})


def alert(stack: Stack, alert_id: str) -> dict:
    return stack.table.get_item(
        Key={"pk": f"ALERT#{alert_id}", "sk": "META"}, ConsistentRead=True
    ).get("Item", {})


def wait_for_token(
    stack: Stack, sc: Scenario, officer_index: int, seen: set[str]
) -> str:
    """Wait until ask_officer stored a new task_token for this officer."""
    deadline = time.time() + stack.approval_timeout + 120
    while time.time() < deadline:
        item = alert(stack, sc.alert_id)
        token = item.get("task_token")
        if (
            token
            and token not in seen
            and int(item.get("officer_index", -1)) == officer_index
        ):
            seen.add(token)
            return token
        time.sleep(POLL_SECONDS)
    raise AssertionError(f"{sc.name}: no task_token for officer_index {officer_index}")


def wait_for_end(stack: Stack, execution_arn: str, budget: int) -> str:
    deadline = time.time() + budget
    while time.time() < deadline:
        status = stack.sfn.describe_execution(executionArn=execution_arn)["status"]
        if status != "RUNNING":
            return status
        time.sleep(POLL_SECONDS)
    raise AssertionError(f"{execution_arn} still running after {budget}s")


def states_entered(stack: Stack, execution_arn: str) -> list[str]:
    names, kwargs = [], {"executionArn": execution_arn, "maxResults": 1000}
    while True:
        page = stack.sfn.get_execution_history(**kwargs)
        names += [
            e["stateEnteredEventDetails"]["name"]
            for e in page["events"]
            if "stateEnteredEventDetails" in e
        ]
        if "nextToken" not in page:
            return names
        kwargs["nextToken"] = page["nextToken"]


def run(stack: Stack, sc: Scenario) -> str:
    suffix = uuid.uuid4().hex[:10]
    sc.alert_id, sc.village_id = (
        f"it-{sc.name.replace('_', '-')}-{suffix}",
        f"it-village-{suffix}",
    )
    seed(stack, sc)
    execution_arn = None
    try:
        execution_arn = stack.sfn.start_execution(
            stateMachineArn=stack.state_machine_arn,
            name=sc.alert_id,
            input=json.dumps(
                {
                    "alert_id": sc.alert_id,
                    "village_id": sc.village_id,
                    "level": sc.level,
                }
            ),
        )["executionArn"]

        seen: set[str] = set()
        for index, answer in enumerate(sc.answers):
            token = wait_for_token(stack, sc, index, seen)
            if answer != "timeout":  # a timeout is simply not answering
                stack.sfn.send_task_success(
                    taskToken=token,
                    output=json.dumps({"decision": answer, "by": OFFICERS[index]}),
                )

        budget = stack.approval_timeout * len(OFFICERS) + stack.ack_wait + 300
        status = wait_for_end(stack, execution_arn, budget)
        assert status == "SUCCEEDED", f"{sc.name}: execution {status}"

        entered = states_entered(stack, execution_arn)
        missing = [s for s in sc.expected_states if s not in entered]
        assert not missing, f"{sc.name}: states never entered {missing}; path {entered}"
        if sc.name != "forced_error":
            assert "Failsafe" not in entered, (
                f"{sc.name}: unexpected Failsafe; path {entered}"
            )
        if sc.name == "timeout_next":
            assert entered.count("AskOfficer") == 2, entered

        if sc.expected_status is not None:
            final = alert(stack, sc.alert_id).get("status")
            assert final == sc.expected_status, (
                f"{sc.name}: alert status {final!r}, want {sc.expected_status!r}"
            )
        return f"PASS {sc.name}: {' -> '.join(entered)}"
    finally:
        if (
            execution_arn
            and stack.sfn.describe_execution(executionArn=execution_arn)["status"]
            == "RUNNING"
        ):
            stack.sfn.stop_execution(
                executionArn=execution_arn, cause="it_workflow cleanup"
            )
        cleanup(stack, sc)


def main(argv: list[str]) -> int:
    names = argv or list(SCENARIOS)
    unknown = set(names) - set(SCENARIOS)
    if unknown:
        print(
            f"unknown scenario(s) {sorted(unknown)}; choose from {list(SCENARIOS)}",
            file=sys.stderr,
        )
        return 2
    stack = Stack()
    if stack.approval_timeout > 120:
        print(
            f"note: ApprovalTimeoutSeconds={stack.approval_timeout}; timeout scenarios will be slow"
        )

    failures = 0
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        futures = {name: pool.submit(run, stack, SCENARIOS[name]) for name in names}
        for name, future in futures.items():
            try:
                print(future.result())
            except Exception as exc:  # noqa: BLE001 - report every scenario, then fail
                failures += 1
                print(f"FAIL {name}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
