"""Regression tests for the independent review's findings (PROGRESS.md, review 1)."""

from datetime import timedelta

import pytest

from Pukaar.api.auth import _from_claims, verify_cognito
from Pukaar.core import clock
from Pukaar.services import decision_engine as de
from Pukaar.services import replay
from Pukaar.services import reports as svc
from Pukaar.services.risk_rules import assess
from Pukaar.store.models import Reading, Report
from Pukaar.workflow.client import RetryLater, decide
from test_workflow_steps import drafted_and_asked, make_alert, steps


def test_failsafe_on_a_warning_notifies_officers_but_sends_nothing(repo, frozen):
    s, a, _ = drafted_and_asked(repo, "warning")
    out = s.handle({"step": "failsafe", "alert_id": a.id, "error": {"Error": "States.Timeout"}})
    alert = repo.get_alert(a.id)
    assert out["sent"] == 0 and alert.status == "failsafe" and repo.list_deliveries(a.id) == []


def test_failsafe_on_an_approved_warning_still_sends(repo, frozen, workflow):
    s, a, _ = drafted_and_asked(repo, "warning")
    decide(repo, workflow, a.id, "approved", "officer1")
    assert s.handle({"step": "failsafe", "alert_id": a.id, "error": {}})["sent"] == 2


def test_officer_chat_links_only_with_a_one_time_code(repo, frozen):
    repo.put_link_code("ABCDEF123456", "officer1")
    assert repo.consume_link_code("ABCDEF123456") == "officer1"
    assert repo.consume_link_code("ABCDEF123456") is None  # single use
    assert repo.consume_link_code("NOSUCHCODE") is None
    repo.put_link_code("OLDCODE", "officer1", ttl_seconds=-1)
    assert repo.consume_link_code("OLDCODE") is None  # expired


def test_replay_alerts_do_not_use_up_the_live_daily_cap(repo, frozen):
    for _ in range(6):
        make_alert(repo, "watch", replay=True)
    assert repo.alerts_on_day("thunag", clock.iso(frozen["now"])[:10]) == 0
    replay.reset(repo)
    assert repo.list_alerts() == []  # the alert log rows went with them


def test_auto_verified_reports_raise_at_most_to_warning(repo, frozen):
    r = Report(id="r1", village_id="thunag", created_at=clock.iso(frozen["now"]), state="verified_auto",
               severity="critical", report_type="people_trapped")
    a = assess(Reading(village_id="thunag", at=clock.iso(frozen["now"])), None, [(r, frozen["now"])], frozen["now"])
    assert a.level == "warning" and "auto_verified_capped:r1" in a.rules_fired
    r.state = "verified"  # an officer verified it
    assert assess(None, None, [(r, frozen["now"])], frozen["now"]).level == "critical"


def test_alert_whose_workflow_failed_to_start_is_restarted(repo, frozen, workflow):
    class Down:
        def start(self, alert):
            raise RuntimeError("ThrottlingException")

    v = repo.get_village("thunag")
    reading = Reading(village_id="thunag", at=clock.iso(frozen["now"]), discharge_peak=v.thresholds.warning)
    res = de.recompute_village(repo, v, now=frozen["now"], reading=reading, workflow=Down())
    assert repo.get_alert(res.alert_id).execution_arn is None
    frozen["now"] += timedelta(minutes=5)
    assert de.restart_stuck(repo, workflow, frozen["now"]) == [res.alert_id]
    assert repo.get_alert(res.alert_id).execution_arn == f"arn:fake:{res.alert_id}"


def test_transient_callback_error_puts_the_alert_back_to_pending(repo, frozen):
    class Flaky:
        def send_success(self, token, output):
            raise RuntimeError("ServiceUnavailable")

    _, a, _ = drafted_and_asked(repo)
    with pytest.raises(RetryLater):
        decide(repo, Flaky(), a.id, "approved", "officer1")
    alert = repo.get_alert(a.id)
    assert alert.status == "pending" and alert.task_token == "TOKEN-1" and not alert.approved


def test_escalation_invalidates_links_for_the_old_text(repo, frozen, workflow):
    from Pukaar.store.repo import ConflictError

    _, a, _ = drafted_and_asked(repo, "watch")
    old = repo.get_alert(a.id).token_version
    repo.update_village("thunag", open_alert_id=a.id, level="watch")
    v = repo.get_village("thunag")
    de.recompute_village(repo, v, now=frozen["now"], workflow=workflow,
                         reading=Reading(village_id="thunag", at=clock.iso(frozen["now"]), discharge_peak=v.thresholds.critical))
    with pytest.raises(ConflictError):
        decide(repo, workflow, a.id, "approved", "officer1", token_version=old)


def test_villages_are_listed_from_the_registry(repo):
    assert [v.id for v in repo.list_villages()] == ["gohar", "janjehli", "pandoh", "sujanpur", "thunag"]


def test_stale_replay_stops_owning_levels(repo, frozen):
    replay.start(repo, "himachal_2023_07")
    assert replay.is_running(repo)
    frozen["now"] += timedelta(minutes=10)
    assert not replay.is_running(repo) and replay.status(repo)["stale"]


def test_replay_speed_fits_in_one_worker_run():
    assert replay.max_speed(97) * 97 <= replay.WORKER_BUDGET_SECONDS


def test_cognito_groups_in_string_form_and_unconfigured_pool():
    p = _from_claims({"cognito:groups": "[officer pradhan]", "cognito:username": "o1", "custom:village_ids": "thunag, gohar"})
    assert (p.role, p.username, p.village_ids) == ("officer", "o1", ["thunag", "gohar"])
    assert _from_claims({"cognito:groups": ["nobody"]}) is None
    assert verify_cognito("not-a-jwt") is None  # no pool configured -> nobody is trusted


def test_unknown_report_is_never_lost_when_processing_fails(repo, frozen):
    r = svc.intake(repo, repo.get_village("thunag"), text="", audio=(b"x", "audio/ogg"))
    assert repo.get_report(r.id).audio_key.endswith(".ogg")


def test_step_unknown_alert_raises_for_failsafe_routing(repo):
    with pytest.raises(Exception):
        steps(repo).handle({"step": "draft", "alert_id": "missing"})
