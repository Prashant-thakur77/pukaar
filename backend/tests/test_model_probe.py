"""The cached Bedrock model-access probe and the honest agent status built from it."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest
from botocore.exceptions import ClientError
from conftest import NOW

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.services import agents as agents_svc
from Pukaar.services import model_probe
from Pukaar.store.models import Alert, DraftCheck


def client_error(code: str, message: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, "Converse")


ACCESS_DENIED = client_error("AccessDeniedException", "You don't have access to the model with the specified model ID.")
NOT_ALLOWED = client_error("ValidationException", "Operation not allowed")


class Calls:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.seen: list[tuple[str, str]] = []

    def __call__(self, model_id: str, region: str) -> None:
        self.seen.append((model_id, region))
        out = self.outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out


def never_call(*_a, **_k):
    raise AssertionError("no model may be called here")


@pytest.fixture()
def llm_on(monkeypatch):
    on = dataclasses.replace(get_settings(), llm_enabled=True)
    monkeypatch.setattr(model_probe, "get_settings", lambda: on)
    monkeypatch.setattr(agents_svc, "get_settings", lambda: on)
    monkeypatch.setattr(model_probe, "_converse_once", never_call)
    return on


def test_classify_access_refusals_as_pending_and_the_rest_as_errors():
    assert model_probe.classify(ACCESS_DENIED)[0] == "pending"
    assert model_probe.classify(NOT_ALLOWED)[0] == "pending"
    assert model_probe.classify(client_error("ResourceNotFoundException",
                                             "Model use case details have not been submitted for this account."))[0] == "pending"
    assert model_probe.classify(client_error("ThrottlingException", "Too many requests"))[0] == "error"
    assert model_probe.classify(client_error("ValidationException", "maxTokens must be at least 1"))[0] == "error"
    assert model_probe.classify(TimeoutError("read timed out"))[0] == "error"
    state, detail = model_probe.classify(NOT_ALLOWED)
    assert detail.startswith("ValidationException: Operation not allowed")


def test_probe_is_off_when_model_calls_are_off(repo, frozen, monkeypatch):
    monkeypatch.setattr(model_probe, "_converse_once", never_call)
    assert model_probe.maybe_run(repo) is None and repo.get_model_probe() is None


def test_probe_runs_at_most_every_six_hours_and_keeps_the_last_definite_answer(repo, frozen, llm_on):
    calls = Calls(ACCESS_DENIED, client_error("ThrottlingException", "slow down"), None)
    rec = model_probe.maybe_run(repo, call=calls)
    assert rec["access"] == "pending" and rec["state"] == "pending" and rec["model"] == llm_on.bedrock_model_id
    assert calls.seen == [(llm_on.bedrock_model_id, llm_on.aws_region)]
    # The next sweeps within 6 hours do not call again.
    for minutes in (15, 30, 6 * 60 - 1):
        frozen["now"] = NOW + timedelta(minutes=minutes)
        assert model_probe.maybe_run(repo, call=calls) is None
    assert len(calls.seen) == 1
    # Six hours on: a throttle is an error, not an answer; the last definite answer stays.
    frozen["now"] = NOW + timedelta(hours=6, minutes=1)
    rec = model_probe.maybe_run(repo, call=calls)
    assert rec["state"] == "error" and rec["access"] == "pending" and rec["access_checked_at"] == clock.iso(NOW)
    # Access lands: the next probe sees it.
    frozen["now"] = NOW + timedelta(hours=12, minutes=2)
    rec = model_probe.maybe_run(repo, call=calls)
    assert rec["access"] == "live" and rec["access_checked_at"] == clock.iso(frozen["now"])


def test_probe_never_raises_into_the_sweep(repo, frozen, llm_on, monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("table gone")

    monkeypatch.setattr(repo, "claim_model_probe", broken)
    assert model_probe.maybe_run(repo, call=Calls(None)) is None


def test_sweep_handler_runs_the_probe(monkeypatch):
    from Pukaar.handlers import sweep

    seen = []
    monkeypatch.setattr(sweep, "sweep_all", lambda repo, workflow=None: [])
    monkeypatch.setattr(sweep, "get_repo", lambda: "repo")
    monkeypatch.setattr(sweep, "get_workflow", lambda: None)
    monkeypatch.setattr(sweep.model_probe, "maybe_run", lambda repo: seen.append(repo))
    sweep.handler({}, None)
    assert seen == ["repo"]


# -- the status on /agents -------------------------------------------------------------
def _draft(repo, model, reason, at):
    v = repo.get_village("thunag")
    repo.put_alert(Alert(id=f"alr_{at.timestamp():.0f}", village_id=v.id, village_name=v.name,
                         village_name_hi=v.name_hi, level="warning", status="pending", created_at=clock.iso(at),
                         updated_at=clock.iso(at), reasoning_model=model,
                         draft_check=DraftCheck(passed=model != "rule-fallback", reason=reason)))


def test_status_with_no_evidence_says_not_checked_and_calls_no_model(repo, frozen, llm_on):
    st = agents_svc.model_status(repo)
    assert st["state"] == "unknown" and "not checked" in st["label_en"] and "6 hours" in st["evidence"]
    reg = agents_svc.registry(repo)  # never_call guards every model path
    assert reg["model"]["status"]["state"] == "unknown"


def test_pending_access_is_shown_with_the_honest_evidence_line(repo, frozen, llm_on):
    model_probe.maybe_run(repo, call=Calls(NOT_ALLOWED))
    reg = agents_svc.registry(repo)
    by_id = {a["id"]: a for a in reg["agents"]}
    for aid, words in (("drafting-agent", "fixed template"), ("analyst-agent", "keyword router"),
                       ("report-agent", "keyword parser")):
        st = by_id[aid]["status"]
        assert st["state"] == "pending" and st["label_en"].startswith("Pending model access") and words in st["label_en"]
        assert st["evidence"].startswith("Bedrock model access for this account is pending an AWS support case; "
                                         "drafts use the fixed Hindi template")
        assert st["evidence_hi"]
    # A failed draft after that keeps saying pending, with the draft as evidence.
    _draft(repo, "rule-fallback", "model unavailable; fixed template used", NOW + timedelta(minutes=5))
    st = agents_svc.model_status(repo)
    assert st["state"] == "pending" and "model unavailable" in st["evidence"]


def test_the_page_turns_live_by_itself_when_access_lands(repo, frozen, llm_on):
    model_probe.maybe_run(repo, call=Calls(ACCESS_DENIED))
    _draft(repo, "rule-fallback", "model unavailable; fixed template used", NOW + timedelta(hours=1))
    assert agents_svc.model_status(repo)["state"] == "pending"
    frozen["now"] = NOW + timedelta(hours=7)
    model_probe.maybe_run(repo, call=Calls(None))
    st = agents_svc.model_status(repo)
    assert st["state"] == "live" and st["label_en"] == "Live: model access confirmed"
    assert agents_svc.model_status(repo, "analyst")["state"] == "live"
    assert agents_svc.report_model_status(repo)["state"] == "live"
    # A later draft by the model is newer evidence and names the model.
    _draft(repo, "us.amazon.nova-2-lite-v1:0", "every number and place found in the decision trace",
           NOW + timedelta(hours=8))
    assert "Nova 2 Lite" in agents_svc.model_status(repo)["label_en"]
    # A later draft that could not reach the model, after access was confirmed, is an outage, not "pending".
    _draft(repo, "rule-fallback", "model unavailable; fixed template used", NOW + timedelta(hours=9))
    st = agents_svc.model_status(repo)
    assert st["state"] == "fallback" and "unreachable" in st["label_en"] and "confirmed" in st["evidence"]


def test_agents_endpoint_never_calls_a_model(repo, frozen, llm_on, monkeypatch):
    from fastapi.testclient import TestClient

    from Pukaar.llm import bedrock
    from Pukaar.main import app

    monkeypatch.setattr(bedrock.BedrockLLM, "_run", never_call)
    r = TestClient(app).get("/agents")
    assert r.status_code == 200, r.text
    assert {a["status"]["state"] for a in r.json()["agents"] if a["id"] == "drafting-agent"} <= {
        "unknown", "pending", "live", "fallback"}
