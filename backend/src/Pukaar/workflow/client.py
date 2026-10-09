"""Workflow clients.

AwsWorkflow:   Step Functions (infra/approval.asl.json); execution name = alert id.
LocalWorkflow: a threaded runner with the same states, used in local mode so
               the full loop works without AWS.
decide():      the approve/decline path shared by the console and the signed
               link. Single use: a conditional update on token_version, so a
               late or repeated reply gets ConflictError (HTTP 409).
"""

from __future__ import annotations

import json
import threading
import time
from functools import lru_cache
from typing import Any

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log, metric
from Pukaar.store.models import Alert
from Pukaar.store.repo import ConflictError, Repo

_LOG = get_logger("workflow.client")


class AwsWorkflow:
    def __init__(self, client: Any = None) -> None:
        import boto3

        s = get_settings()
        self.arn = s.state_machine_arn
        self.sfn = client or boto3.client("stepfunctions", region_name=s.aws_region)

    def start(self, alert: Alert) -> str | None:
        resp = self.sfn.start_execution(stateMachineArn=self.arn, name=alert.id,
                                        input=json.dumps({"alert_id": alert.id, "village_id": alert.village_id,
                                                          "level": alert.level}))
        return resp["executionArn"]

    def send_success(self, token: str, output: dict) -> None:
        self.sfn.send_task_success(taskToken=token, output=json.dumps(output))


class LocalWorkflow:
    """Runs the approval state machine in a background thread per alert."""

    def __init__(self, repo_factory, steps_factory, approval_timeout: float | None = None,
                 ack_wait: float | None = None) -> None:
        s = get_settings()
        self.repo_factory = repo_factory
        self.steps_factory = steps_factory
        self.approval_timeout = approval_timeout if approval_timeout is not None else s.approval_timeout_seconds
        self.ack_wait = ack_wait if ack_wait is not None else s.ack_wait_seconds
        self._waiting: dict[str, tuple[threading.Event, dict]] = {}
        self._lock = threading.Lock()
        self.threads: list[threading.Thread] = []

    def start(self, alert: Alert) -> str | None:
        t = threading.Thread(target=self._run, args=(alert.id,), daemon=True, name=f"wf-{alert.id}")
        self.threads.append(t)
        t.start()
        return f"local:{alert.id}"

    def send_success(self, token: str, output: dict) -> None:
        with self._lock:
            entry = self._waiting.get(token)
        if entry is None:
            raise ConflictError("no task is waiting for this token")
        entry[1].update(output)
        entry[0].set()

    def _wait_for_decision(self, steps, alert_id: str, index: int) -> dict | None:
        token = f"local:{alert_id}:{index}:{time.monotonic_ns()}"
        event, holder = threading.Event(), {}
        with self._lock:
            self._waiting[token] = (event, holder)
        try:
            steps.handle({"step": "ask_officer", "alert_id": alert_id, "officer_index": index, "task_token": token})
            return holder if event.wait(self.approval_timeout) else None
        finally:
            with self._lock:
                self._waiting.pop(token, None)

    def _run(self, alert_id: str) -> None:
        steps = self.steps_factory(self.repo_factory())
        outcome = "failsafe"
        try:
            draft = steps.handle({"step": "draft", "alert_id": alert_id})
            index, level, decision = 0, draft["level"], None
            if draft["officer_count"] > 0:
                while True:
                    decision = self._wait_for_decision(steps, alert_id, index)
                    if decision is not None:
                        break
                    nxt = steps.handle({"step": "next_officer", "alert_id": alert_id, "officer_index": index})
                    level = nxt["level"]
                    if not nxt["has_next"]:
                        break
                    index = nxt["officer_index"]
            if decision is not None and decision.get("decision") == "declined":
                outcome = "declined"
            elif decision is not None and decision.get("decision") == "approved":
                steps.handle({"step": "deliver", "alert_id": alert_id})
                time.sleep(self.ack_wait)
                steps.handle({"step": "recall", "alert_id": alert_id})
                outcome = "delivered"
            elif level == "critical":
                steps.handle({"step": "auto_send", "alert_id": alert_id})
                steps.handle({"step": "deliver", "alert_id": alert_id})
                time.sleep(self.ack_wait)
                steps.handle({"step": "recall", "alert_id": alert_id})
                outcome = "auto_sent_unapproved"
            else:
                steps.handle({"step": "expire", "alert_id": alert_id})
                outcome = "expired"
        except Exception as exc:
            log(_LOG, "local workflow error -> failsafe", 40, alert_id=alert_id, error=str(exc)[:300])
            steps.handle({"step": "failsafe", "alert_id": alert_id, "error": {"Error": type(exc).__name__, "Cause": str(exc)[:500]}})
            outcome = "failsafe"
        steps.handle({"step": "close", "alert_id": alert_id, "outcome": outcome})


class RetryLater(Exception):
    """The workflow could not be reached; the alert is pending again."""


_LATE_MARKERS = ("TaskTimedOut", "InvalidToken", "TaskDoesNotExist", "no task is waiting")


def decide(repo: Repo, workflow: Any, alert_id: str, decision: str, by: str, *,
           token_version: int | None = None, reason: str = "") -> Alert:
    """decision is "approved" or "declined". Raises ConflictError when late or reused.

    The token is consumed first (single use), then the workflow is told. If the
    workflow had already moved on, the decision is undone and reported as late;
    if telling it failed for a transient reason, the alert goes back to pending
    with its token, so the officer can simply try again.
    """
    from boto3.dynamodb.conditions import Attr

    alert = repo.get_alert(alert_id)
    if alert is None:
        raise KeyError(alert_id)
    if alert.status != "pending" or not alert.task_token:
        raise ConflictError(f"alert is {alert.status}")
    version = alert.token_version if token_version is None else token_version
    task_token = alert.task_token
    updated = repo.consume_task_token(alert_id, version, status="approved" if decision == "approved" else "declined",
                                      approved=decision == "approved", decided_by=by,
                                      decided_at=clock.iso(clock.now()))
    error: Exception | None = None
    for attempt in range(3):
        try:
            workflow.send_success(task_token, {"decision": decision, "by": by})
            error = None
            break
        except Exception as exc:
            error = exc
            if any(m in f"{type(exc).__name__} {exc}" for m in _LATE_MARKERS):
                break
            time.sleep(0.3 * (attempt + 1))
    if error is not None:
        late = any(m in f"{type(error).__name__} {error}" for m in _LATE_MARKERS)
        log(_LOG, "workflow did not take the decision", 30, alert_id=alert_id, late=late, error=str(error)[:200])
        try:
            if late:
                # The workflow moved on (next officer or expiry); keep its state, drop our decision.
                repo.update_alert(alert_id, condition=Attr("decided_by").eq(by), approved=False, decided_by=None,
                                  decided_at=None)
            else:
                repo.update_alert(alert_id, condition=Attr("decided_by").eq(by), status="pending", approved=False,
                                  decided_by=None, decided_at=None, task_token=task_token,
                                  token_version=version)
        except ConflictError:
            pass  # the workflow already wrote a newer state
        repo.add_timeline(alert_id, "decision_not_taken", "late: the workflow had moved on" if late
                          else "temporary error; the alert is pending again")
        if late:
            raise ConflictError("the approval window closed before the decision arrived") from error
        raise RetryLater("could not reach the workflow; the alert is pending again, please try again") from error
    repo.add_timeline(alert_id, decision, f"by {by}" + (f": {reason}" if reason else ""))
    metric("ApprovalDecision", 1, Decision=decision)
    return updated


@lru_cache(maxsize=1)
def get_workflow():
    s = get_settings()
    if s.is_local:
        from Pukaar.llm.bedrock import BedrockLLM
        from Pukaar.store.repo import get_repo
        from Pukaar.workflow.steps import Steps

        llm = BedrockLLM() if s.llm_enabled else None
        return LocalWorkflow(get_repo, lambda repo: Steps(repo, llm))
    return AwsWorkflow()
