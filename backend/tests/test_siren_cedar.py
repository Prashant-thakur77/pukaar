"""Every siren permit and forbid in policy/base.cedar, both sides (allowed by it, and refused just outside it)."""

from __future__ import annotations

import pytest

from Pukaar.policy.guard import SYSTEM, Principal, evaluate

O, O2 = Principal("officer1", "officer"), Principal("officer2", "officer")
P = Principal("pradhan_thunag", "pradhan", ["thunag"])
J, JP = Principal("judge", "officer"), Principal("judge_pradhan", "pradhan", ["thunag"])
A = Principal("drafting-agent", "agent")
W = {"level": "warning", "approved": True, "pattern": "W1"}
C = {"level": "critical", "approved": True, "pattern": "C1"}

CASES = [
    # (policy, principal, action, resource type, context, allowed)
    ("system-sound-siren-approved", SYSTEM, "sound_siren", "alert", W, True),
    ("system-sound-siren-approved", SYSTEM, "sound_siren", "alert", {**W, "approved": False}, False),
    ("system-sound-siren-approved", SYSTEM, "sound_siren", "alert", {**W, "level": "watch"}, False),
    ("system-sound-siren-approved", SYSTEM, "sound_siren", "alert", C, False),
    ("system-sound-siren-approved", SYSTEM, "sound_siren", "alert", {**C, "machine_evidence_critical": True}, True),
    ("system-sound-siren-approved", SYSTEM, "sound_siren", "alert", {**C, "second_officer_distinct": True}, True),
    ("system-sound-siren-approved", SYSTEM, "sound_siren", "alert", {**C, "pattern": "W1"}, True),
    ("system-sound-siren-approved", SYSTEM, "sound_siren", "alert",
     {**W, "pattern": "C1", "machine_evidence_critical": True}, False),  # C1 is for a Critical only
    ("system-sound-siren-approved", SYSTEM, "sound_siren", "alert",
     {**C, "approved": False, "all_officers_timed_out": True, "critical_auto_send": True, "pattern": "W1"}, True),
    ("system-sound-siren-approved", SYSTEM, "sound_siren", "alert",
     {**C, "approved": False, "all_officers_timed_out": True, "critical_auto_send": False, "pattern": "W1"}, False),
    ("system-sound-siren-failsafe", SYSTEM, "sound_siren", "alert",
     {"level": "critical", "pattern": "W1", "src": "failsafe"}, True),
    ("system-sound-siren-failsafe", SYSTEM, "sound_siren", "alert",
     {"level": "warning", "pattern": "W1", "src": "failsafe"}, False),
    ("system-drill-pattern", SYSTEM, "test_siren", "alert", {"drill": True, "pattern": "D1", "approved": True}, True),
    ("system-drill-pattern", SYSTEM, "test_siren", "alert", {"drill": True, "pattern": "W1", "approved": True}, False),
    ("system-propagate-pradhan-siren", SYSTEM, "sound_siren", "village",
     {"src": "pradhan_box", "village_id": "thunag", "device_village_id": "thunag", "pattern": "C1"}, True),
    ("system-propagate-pradhan-siren", SYSTEM, "sound_siren", "village",
     {"src": "pradhan_box", "village_id": "gohar", "device_village_id": "thunag", "pattern": "C1"}, False),
    ("system-scheduled-test", SYSTEM, "test_siren", "device", {"kind": "silent", "hour_ist": 2}, True),
    ("system-scheduled-test", SYSTEM, "test_siren", "device", {"kind": "audible", "hour_ist": 11}, True),
    ("system-scheduled-test", SYSTEM, "test_siren", "device",
     {"kind": "audible", "hour_ist": 11, "village_alert_open": True}, False),
    ("officer-manual-siren", O, "sound_siren", "village", {"level": "warning", "village_id": "gohar"}, True),
    ("officer-manual-siren", O, "sound_siren", "village", {"level": "critical", "village_id": "gohar"}, False),
    ("officer-manual-siren", O, "sound_siren", "village",
     {"level": "critical", "village_id": "gohar", "second_officer_distinct": True}, True),
    ("officer-stop-view-devices", O, "stop_siren", "village", {"village_id": "gohar"}, True),
    ("officer-stop-view-devices", P, "stop_siren", "village", {"village_id": "thunag"}, False),
    ("officer-test-siren", O, "test_siren", "device", {"kind": "audible", "hour_ist": 17}, True),
    ("officer-test-siren", O, "test_siren", "device", {"kind": "audible", "hour_ist": 18}, False),
    ("officer-test-siren", P, "test_siren", "device", {"kind": "silent", "village_id": "thunag"}, False),
    ("officer-manage-device", O, "manage_device", "device", {"change": "settings"}, True),
    ("officer-manage-device", O, "manage_device", "device", {"change": "autonomy_enable"}, False),
    ("officer-manage-device", O, "manage_device", "device",
     {"change": "autonomy_enable", "second_officer_distinct": True}, True),
    ("pradhan-view-own-devices", P, "view_devices", "village", {"village_id": "thunag"}, True),
    ("pradhan-view-own-devices", P, "view_devices", "village", {"village_id": "gohar"}, False),
    ("pradhan-siren-own-village", P, "sound_siren", "village", {"village_id": "thunag", "level": "critical"}, True),
    ("pradhan-siren-own-village", P, "sound_siren", "village", {"village_id": "thunag", "level": "watch"}, False),
    ("pradhan-stop-own-trigger", P, "stop_siren", "village", {"village_id": "thunag", "started_by_self": True}, True),
    ("pradhan-stop-own-trigger", P, "stop_siren", "village", {"village_id": "thunag", "started_by_self": False}, False),
    ("staff-pour-test", P, "pour_test", "device", {"village_id": "thunag"}, True),
    ("staff-pour-test", P, "pour_test", "device", {"village_id": "gohar"}, False),
    ("staff-pour-test", O, "pour_test", "device", {"village_id": "gohar"}, True),
    ("no-replay-sirens", SYSTEM, "sound_siren", "alert", {**W, "replay": True}, False),
    ("no-replay-sirens", SYSTEM, "sound_siren", "alert", {**W, "replay": True, "device_simulated": True}, True),
    ("drill-never-real-pattern", SYSTEM, "sound_siren", "alert", {**W, "drill": True}, False),
    ("drill-never-real-pattern", O, "sound_siren", "village", {"level": "warning", "drill": True}, False),
    ("external-cap-never-sounds", SYSTEM, "sound_siren", "alert", {**W, "src": "external_cap"}, False),
    ("public-demo-accounts-never-act-on-sirens", J, "sound_siren", "village", {"level": "warning"}, False),
    ("public-demo-accounts-never-act-on-sirens", JP, "stop_siren", "village",
     {"village_id": "thunag", "started_by_self": True}, False),
    ("public-demo-accounts-never-act-on-sirens", J, "test_siren", "device", {"kind": "silent", "replay": True}, False),
    ("public-demo-accounts-never-act-on-sirens", J, "view_devices", "app", {}, True),
    ("agents-never-send", A, "sound_siren", "village", {"level": "warning", "village_id": "thunag"}, False),
    ("agents-never-send", A, "manage_device", "device", {"change": "settings"}, False),
]


@pytest.mark.parametrize("policy,who,action,rtype,ctx,allowed", CASES,
                         ids=[f"{c[0]}:{c[2]}:{i}" for i, c in enumerate(CASES)])
def test_siren_policy(policy, who, action, rtype, ctx, allowed):
    d = evaluate(who, action, rtype, "r1", ctx)
    assert d.allowed is allowed, (policy, d.reason)
    if allowed:
        assert policy in d.policy_ids or policy.startswith(("public-demo", "no-replay")), d.policy_ids
    elif d.policy_ids:  # refused by a forbid: it is the one named
        assert policy in d.policy_ids or not policy.startswith(("no-", "drill-", "external-", "public-", "agents-"))


def test_every_siren_policy_is_covered_here():
    from pathlib import Path
    import re

    text = (Path(__file__).resolve().parents[1] / "src" / "Pukaar" / "policy" / "base.cedar").read_text(encoding="utf-8")
    siren_part = text.split("// -- the alarm layer", 1)[1]
    ids = set(re.findall(r'@id\("([^"]+)"\)', siren_part))
    assert ids <= {c[0] for c in CASES}, ids - {c[0] for c in CASES}
