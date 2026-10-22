import time

import pytest

from Pukaar.policy.guard import SYSTEM, Principal, authorize, evaluate
from Pukaar.workflow import tokens

OFFICER = Principal("officer1", "officer")
PRADHAN = Principal("pradhan_thunag", "pradhan", ["thunag"])
AGENT = Principal("drafting-agent", "agent")


def test_officer_may_approve_and_pradhan_may_not():
    assert evaluate(OFFICER, "approve", "alert", "a1").allowed
    d = evaluate(PRADHAN, "approve", "alert", "a1")
    assert not d.allowed and d.reason == "Only a district officer can approve an alert."


def test_pradhan_sees_only_own_village_reports():
    assert evaluate(PRADHAN, "view_reports", "village", "thunag", {"village_id": "thunag"}).allowed
    assert not evaluate(PRADHAN, "view_reports", "village", "gohar", {"village_id": "gohar"}).allowed


def test_system_sends_only_approved_or_critical_auto_send():
    assert evaluate(SYSTEM, "deliver", "alert", "a", {"approved": True}).allowed
    assert not evaluate(SYSTEM, "deliver", "alert", "a", {"approved": False}).allowed
    assert not evaluate(SYSTEM, "auto_send", "alert", "a", {"level": "warning", "all_officers_timed_out": True}).allowed
    assert evaluate(SYSTEM, "auto_send", "alert", "a", {"level": "critical", "all_officers_timed_out": True}).allowed


def test_forbid_replay_to_real_phones_overrides_permit():
    d = evaluate(SYSTEM, "deliver", "alert", "a", {"approved": True, "replay": True, "channel": "telegram"})
    assert not d.allowed and d.policy_ids == ["no-replay-to-phones"]


def test_agents_get_read_only_tools_and_nothing_else():
    assert evaluate(AGENT, "use_tool", "tool", "get_village_risk").allowed
    assert not evaluate(AGENT, "use_tool", "tool", "send_telegram").allowed
    assert evaluate(AGENT, "deliver", "alert", "a").policy_ids == ["agents-never-send"]
    assert not evaluate(OFFICER, "use_tool", "tool", "get_village_risk").allowed


def test_unknown_role_and_action_fail_closed():
    assert not evaluate(Principal("x", "admin"), "approve", "alert", "a").allowed
    assert not evaluate(OFFICER, "drop_tables", "app", "pukaar").allowed


def test_every_decision_is_audited(repo, frozen):
    authorize(PRADHAN, "approve", "alert", "a1", repo=repo)
    rows = repo.list_audit("2026-07-01", "alert:a1")
    assert len(rows) == 1 and rows[0].decision == "deny" and rows[0].role == "pradhan"


def test_no_audit_means_no_permission():
    class BrokenRepo:
        def append_audit(self, row):
            raise RuntimeError("table unavailable")

    assert not authorize(OFFICER, "approve", "alert", "a1", repo=BrokenRepo()).allowed


def test_approval_token_round_trip_and_tamper():
    t = tokens.sign("alr_1", "officer1", 3, "approve")
    parsed = tokens.verify(t, "approve")
    assert (parsed.alert_id, parsed.subject, parsed.version) == ("alr_1", "officer1", 3)
    body, mac = t.split(".")
    with pytest.raises(tokens.TokenError):
        tokens.verify(body + "x." + mac, "approve")
    with pytest.raises(tokens.TokenError):
        tokens.verify(t, "ack")


# -- the public demo accounts (password published in the README) -----------------------------
JUDGE = Principal("judge", "officer")
JUDGE_PRADHAN = Principal("judge_pradhan", "pradhan", ["thunag"])
LIVE_ONLY = ["approve", "decline", "issue_directive", "send_drill", "set_shelter_status", "block_road",
             "open_rollcall", "remind_rollcall", "tick_checklist", "set_report_state", "set_gauge_thresholds",
             "manage_staff_gauge", "confirm_staff_reading", "dev_link"]


@pytest.mark.parametrize("action", LIVE_ONLY)
def test_judge_cannot_touch_live_alerts_or_villages(action):
    for resource_type, rid in (("alert", "a1"), ("village", "thunag"), ("report", "r1")):
        d = evaluate(JUDGE, action, resource_type, rid, {"village_id": "thunag", "replay": False})
        assert not d.allowed and d.policy_ids == ["public-demo-accounts-replay-only"], (action, resource_type)
        assert "Public demo account" in d.reason
    # the same request with no replay flag at all is live too
    assert not evaluate(JUDGE, action, "alert", "a1").allowed


def test_judge_pradhan_is_held_to_replays_even_in_its_own_village():
    ctx = {"village_id": "thunag", "replay": False}
    for action in ("block_road", "set_shelter_status", "tick_checklist", "open_rollcall"):
        d = evaluate(JUDGE_PRADHAN, action, "village", "thunag", ctx)
        assert not d.allowed and d.policy_ids == ["public-demo-accounts-replay-only"]
        # a real pradhan of the same village keeps the permission
        assert evaluate(PRADHAN, action, "village", "thunag", ctx).allowed


def test_judge_may_act_on_replay_alerts_and_read_freely():
    assert evaluate(JUDGE, "approve", "alert", "a1", {"replay": True}).allowed
    assert evaluate(JUDGE, "decline", "alert", "a1", {"replay": True}).allowed
    assert evaluate(JUDGE, "set_report_state", "report", "r1", {"replay": True}).allowed
    for action in ("view_console", "start_replay", "read_audit", "ask_analyst"):
        assert evaluate(JUDGE, action, "app", "pukaar").allowed, action
    # villagers' data: replay records only
    for action in ("view_reports", "view_recipients", "view_rollcall", "view_after_action"):
        assert evaluate(JUDGE, action, "alert", "a1", {"replay": True}).allowed, action
    # other officers are not affected
    assert evaluate(OFFICER, "approve", "alert", "a1", {"replay": False}).allowed


def test_judge_refusal_reason_is_in_the_audit_log(repo, frozen):
    d = authorize(JUDGE, "approve", "alert", "a9", {"replay": False}, repo=repo)
    assert not d.allowed
    row = repo.list_audit("2026-07-01", "alert:a9")[0]
    assert row.actor == "judge" and row.decision == "deny"
    assert row.reason.startswith("Public demo account") and "replay alerts only" in row.reason


def test_approval_token_expires_after_30_minutes():
    t = tokens.sign("alr_1", "officer1", 1, "approve", now=time.time() - 31 * 60)
    with pytest.raises(tokens.TokenError, match="expired"):
        tokens.verify(t, "approve")


# -- villagers' data and the published demo password ----------------------------------------------
PERSONAL_READS = ["view_reports", "view_recipients", "view_rollcall", "view_after_action"]


@pytest.mark.parametrize("action", PERSONAL_READS)
@pytest.mark.parametrize("who", [JUDGE, JUDGE_PRADHAN])
def test_demo_accounts_read_villagers_data_from_replays_only(action, who):
    for resource_type, rid in (("alert", "a1"), ("village", "thunag"), ("report", "r1"), ("rollcall", "rc1"),
                               ("app", "pukaar")):
        d = evaluate(who, action, resource_type, rid, {"village_id": "thunag", "replay": False})
        assert not d.allowed, (action, resource_type)
        assert d.policy_ids in ([], ["public-demo-accounts-replay-only"]), d.policy_ids
    # no replay flag at all is live too
    assert not evaluate(who, action, "alert", "a1", {"village_id": "thunag"}).allowed


def test_demo_accounts_read_replay_records_and_real_staff_keep_live_reads():
    for action in ("view_reports", "view_recipients"):
        assert evaluate(JUDGE, action, "village", "thunag", {"village_id": "thunag", "replay": True}).allowed
    assert evaluate(JUDGE, "view_after_action", "alert", "a1", {"village_id": "thunag", "replay": True}).allowed
    assert evaluate(JUDGE_PRADHAN, "view_reports", "village", "thunag", {"village_id": "thunag", "replay": True}).allowed
    assert evaluate(OFFICER, "view_reports", "village", "gohar", {"village_id": "gohar"}).allowed
    assert evaluate(OFFICER, "view_recipients", "alert", "a1", {"village_id": "gohar"}).allowed
    assert evaluate(PRADHAN, "view_reports", "village", "thunag", {"village_id": "thunag"}).allowed
    assert evaluate(PRADHAN, "view_recipients", "alert", "a1", {"village_id": "thunag"}).allowed
    assert not evaluate(PRADHAN, "view_recipients", "alert", "a1", {"village_id": "gohar"}).allowed


PRADHAN_ACTIONS = ["view_console", "view_reports", "view_recipients", "view_rollcall", "open_rollcall",
                   "remind_rollcall", "view_after_action", "tick_checklist", "set_shelter_status", "block_road",
                   "view_gauge_proposal", "manage_staff_gauge"]


@pytest.mark.parametrize("action", PRADHAN_ACTIONS)
def test_a_pradhan_request_naming_no_village_never_matches(action):
    for resource_type in ("app", "village", "alert", "report", "rollcall"):
        for ctx in ({}, {"village_id": ""}, {"village_id": "", "replay": False}):
            assert not evaluate(PRADHAN, action, resource_type, "x", ctx).allowed, (action, resource_type, ctx)
    # not even for a pradhan whose village list holds an empty id
    odd = Principal("pradhan_odd", "pradhan", [""])
    assert not evaluate(odd, action, "village", "x", {"village_id": ""}).allowed


def test_no_policy_matches_on_an_empty_village_id():
    from Pukaar.policy.guard import _POLICY_FILE

    assert 'village_id == ""' not in _POLICY_FILE.read_text(encoding="utf-8")
