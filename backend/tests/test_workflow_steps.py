import pytest

from Pukaar.core import clock
from Pukaar.core.ids import new_id
from Pukaar.store.models import Alert, Recipient
from Pukaar.store.repo import ConflictError
from Pukaar.workflow.client import decide
from Pukaar.workflow.steps import StepError, Steps


def make_alert(repo, level="warning", replay=False, village="thunag"):
    v = repo.get_village(village)
    stamp = clock.iso(clock.now())
    a = Alert(id=new_id("alr"), village_id=v.id, village_name=v.name, village_name_hi=v.name_hi, level=level,
              status="drafting", created_at=stamp, updated_at=stamp, decision_trace={"rules_fired": ["test"]}, replay=replay)
    repo.put_alert(a)
    return a


def steps(repo, llm=None):
    return Steps(repo, llm, synthesize=lambda alert_id, text: None)


def drafted_and_asked(repo, level="warning", replay=False):
    s = steps(repo)
    a = make_alert(repo, level, replay)
    out = s.handle({"step": "draft", "alert_id": a.id})
    s.handle({"step": "ask_officer", "alert_id": a.id, "officer_index": 0, "task_token": "TOKEN-1"})
    return s, a, out


def test_draft_without_model_uses_fixed_hindi_template(repo, frozen):
    s, a, out = drafted_and_asked(repo)
    alert = repo.get_alert(a.id)
    assert out["officer_count"] == 2 and out["recipients_count"] == 2
    assert alert.status == "pending" and alert.reasoning_model == "rule-fallback"
    assert "112" in alert.text_hi and "थुनाग" in alert.text_hi


def test_model_outage_still_alerts(repo, frozen):
    class DownLLM:
        model_name = "us.amazon.nova-2-lite-v1:0"

        def draft_alert(self, *a, **k):
            return None  # what BedrockLLM returns on any failure

    s = Steps(repo, DownLLM(), synthesize=lambda *_: None)
    a = make_alert(repo, "critical")
    s.handle({"step": "draft", "alert_id": a.id})
    alert = repo.get_alert(a.id)
    assert alert.reasoning_model == "rule-fallback" and alert.text_hi.startswith("पुकार:")
    assert alert.draft_check.passed is False


def test_approve_then_deliver_then_recall_once(repo, frozen, workflow):
    s, a, _ = drafted_and_asked(repo)
    decide(repo, workflow, a.id, "approved", "officer1")
    assert workflow.successes[0] == ("TOKEN-1", {"decision": "approved", "by": "officer1"})
    out = s.handle({"step": "deliver", "alert_id": a.id})
    assert out == {"alert_id": a.id, "sent": 2, "failed": 0}
    assert s.handle({"step": "recall", "alert_id": a.id})["resent"] == 2
    assert s.handle({"step": "recall", "alert_id": a.id})["resent"] == 0  # only one automatic re-send
    s.handle({"step": "close", "alert_id": a.id, "outcome": "delivered"})
    assert repo.get_alert(a.id).status == "delivered"
    assert repo.get_village("thunag").open_alert_id is None


def test_resend_keeps_the_first_send_time(repo, frozen, workflow):
    """Time to ear reads the first send; the automatic re-send must not move it."""
    from datetime import timedelta

    s, a, _ = drafted_and_asked(repo)
    decide(repo, workflow, a.id, "approved", "officer1")
    s.handle({"step": "deliver", "alert_id": a.id})
    first = {d.recipient_id: d.sent_at for d in repo.list_deliveries(a.id)}
    frozen["now"] = frozen["now"] + timedelta(minutes=5)
    s.handle({"step": "recall", "alert_id": a.id})
    after = repo.list_deliveries(a.id)
    assert all(d.attempts == 2 for d in after)
    assert {d.recipient_id: d.sent_at for d in after} == first


def test_late_or_repeated_approval_is_rejected(repo, frozen, workflow):
    _, a, _ = drafted_and_asked(repo)
    version = repo.get_alert(a.id).token_version
    decide(repo, workflow, a.id, "approved", "officer1", token_version=version)
    with pytest.raises(ConflictError):
        decide(repo, workflow, a.id, "approved", "officer2", token_version=version)
    assert len(workflow.successes) == 1


def test_link_from_a_timed_out_officer_is_rejected(repo, frozen, workflow):
    s, a, _ = drafted_and_asked(repo)
    old_version = repo.get_alert(a.id).token_version
    nxt = s.handle({"step": "next_officer", "alert_id": a.id, "officer_index": 0})
    assert nxt == {"has_next": True, "officer_index": 1, "level": "warning"}
    s.handle({"step": "ask_officer", "alert_id": a.id, "officer_index": 1, "task_token": "TOKEN-2"})
    with pytest.raises(ConflictError):
        decide(repo, workflow, a.id, "approved", "officer1", token_version=old_version)


def test_decision_after_workflow_timeout_is_a_conflict(repo, frozen, workflow):
    _, a, _ = drafted_and_asked(repo)
    workflow.reject = True
    with pytest.raises(ConflictError):
        decide(repo, workflow, a.id, "approved", "officer1")


def test_deliver_refuses_an_unapproved_alert(repo, frozen):
    s, a, _ = drafted_and_asked(repo)
    with pytest.raises(StepError):
        s.handle({"step": "deliver", "alert_id": a.id})


def test_critical_auto_send_is_flagged_unapproved(repo, frozen):
    s, a, _ = drafted_and_asked(repo, "critical")
    s.handle({"step": "auto_send", "alert_id": a.id})
    s.handle({"step": "deliver", "alert_id": a.id})
    alert = repo.get_alert(a.id)
    assert alert.status == "auto_sent_unapproved" and not alert.approved and alert.delivered_count == 2


def test_warning_cannot_auto_send(repo, frozen):
    s, a, _ = drafted_and_asked(repo, "warning")
    with pytest.raises(StepError, match="denied"):
        s.handle({"step": "auto_send", "alert_id": a.id})


def test_replay_alert_never_reaches_a_real_phone(repo, frozen, workflow, monkeypatch):
    monkeypatch.setenv("PUKAAR_TELEGRAM_TOKEN", "fake")
    sent = []
    monkeypatch.setattr("Pukaar.delivery.telegram.send_alert", lambda *a, **k: sent.append(a))
    repo.put_recipient(Recipient(id="12345", village_id="thunag", name="Real phone", channel="telegram"))
    s, a, _ = drafted_and_asked(repo, "warning", replay=True)
    decide(repo, workflow, a.id, "approved", "officer1")
    s.handle({"step": "deliver", "alert_id": a.id})
    assert sent == []
    channels = {d.recipient_id: d.channel for d in repo.list_deliveries(a.id)}
    assert channels["12345"] == "stub"


def test_live_alert_goes_to_telegram_recipients(repo, frozen, workflow, monkeypatch):
    monkeypatch.setenv("PUKAAR_TELEGRAM_TOKEN", "fake")
    sent = []
    monkeypatch.setattr("Pukaar.delivery.telegram.send_alert", lambda chat, alert_id, text, audio: sent.append(chat))
    repo.put_recipient(Recipient(id="12345", village_id="thunag", name="Real phone", channel="telegram"))
    s, a, _ = drafted_and_asked(repo)
    decide(repo, workflow, a.id, "approved", "officer1")
    s.handle({"step": "deliver", "alert_id": a.id})
    assert sent == ["12345"]


def test_failsafe_and_close_survive_an_unknown_alert(repo, frozen):
    s = steps(repo)
    assert s.handle({"step": "failsafe", "alert_id": "missing", "error": {"Error": "X"}}) == {"alert_id": "missing", "sent": 0}
    assert s.handle({"step": "close", "alert_id": "missing", "outcome": "failsafe"})["status"] == "missing"


def test_failsafe_sends_fixed_template(repo, frozen):
    s, a, _ = drafted_and_asked(repo, "critical")
    out = s.handle({"step": "failsafe", "alert_id": a.id, "error": {"Error": "States.TaskFailed"}})
    alert = repo.get_alert(a.id)
    assert out["sent"] == 2 and alert.status == "failsafe" and alert.reasoning_model == "rule-fallback"


def test_acknowledgement_is_recorded_once(repo, frozen, workflow):
    from Pukaar.delivery.dispatch import acknowledge

    s, a, _ = drafted_and_asked(repo)
    decide(repo, workflow, a.id, "approved", "officer1")
    s.handle({"step": "deliver", "alert_id": a.id})
    assert acknowledge(repo, a.id, "stub-thunag-1") is not None
    assert acknowledge(repo, a.id, "stub-thunag-1") is None
    assert repo.get_alert(a.id).acknowledged_count == 1


def test_unknown_step_is_an_error(repo):
    with pytest.raises(StepError):
        steps(repo).handle({"step": "launch_rockets"})
