"""Cedar for Pukaar Raahat (policy/base.cedar): who may release relief, and the audit row it leaves."""

from __future__ import annotations

from Pukaar.policy.guard import SYSTEM, Principal, authorize, evaluate

OFFICER = Principal("officer1", "officer")
PRADHAN = Principal("pradhan_thunag", "pradhan", ["thunag"])
JUDGE = Principal("judge", "officer")
JUDGE_PRADHAN = Principal("judge_pradhan", "pradhan", ["thunag"])
AGENT = Principal("drafting-agent", "agent")


def test_officer_releases_relief_live_or_replay():
    for replay in (False, True):
        assert evaluate(OFFICER, "release_relief", "alert", "a1", {"replay": replay, "village_id": "thunag"}).allowed


def test_pradhan_never_releases_relief_even_in_own_village():
    d = evaluate(PRADHAN, "release_relief", "alert", "a1", {"replay": False, "village_id": "thunag"})
    assert not d.allowed and d.reason == "Only a district officer can release relief."


def test_judge_releases_relief_on_replay_alerts_only():
    """Same guard as deliver: the published judge password can never move money for a live alert."""
    live = evaluate(JUDGE, "release_relief", "alert", "a1", {"replay": False, "village_id": "sujanpur"})
    assert not live.allowed and live.policy_ids == ["public-demo-accounts-replay-only"]
    assert not evaluate(JUDGE, "release_relief", "alert", "a1").allowed  # no replay flag at all is live
    assert evaluate(JUDGE, "release_relief", "alert", "a1", {"replay": True}).allowed
    assert not evaluate(JUDGE_PRADHAN, "release_relief", "alert", "a1", {"replay": True}).allowed


def test_system_and_agents_never_release_relief():
    """Code decides eligibility; only a human officer releases."""
    for who in (SYSTEM, AGENT):
        assert not evaluate(who, "release_relief", "alert", "a1", {"replay": True}).allowed


def test_release_decisions_are_audited(repo, frozen):
    assert authorize(OFFICER, "release_relief", "alert", "a7", {"replay": False}, repo=repo).allowed
    assert not authorize(JUDGE, "release_relief", "alert", "a8", {"replay": False}, repo=repo).allowed
    allow = repo.list_audit("2026-07-01", "alert:a7")[0]
    deny = repo.list_audit("2026-07-01", "alert:a8")[0]
    assert (allow.actor, allow.action, allow.decision) == ("officer1", "release_relief", "allow")
    assert (deny.actor, deny.action, deny.decision) == ("judge", "release_relief", "deny")
    assert deny.reason.startswith("Public demo account")


def test_relief_message_reaches_real_phones_for_live_alerts_only():
    assert evaluate(SYSTEM, "notify_relief", "alert", "a1", {"replay": False, "channel": "telegram"}).allowed
    d = evaluate(SYSTEM, "notify_relief", "alert", "a1", {"replay": True, "channel": "telegram"})
    assert not d.allowed and d.policy_ids == ["no-replay-to-phones"]
    assert not evaluate(OFFICER, "notify_relief", "alert", "a1", {"replay": False, "channel": "telegram"}).allowed
