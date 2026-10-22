"""The production stage (docs/DEPLOY.md, "Production stage"): samconfig.toml [prod], the template's
prod rule, Cognito MFA, DPDP retention, region independence and the safe defaults."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

import pytest

from test_template_safety import RES, T

ROOT = Path(__file__).resolve().parents[2]
SAMCONFIG = tomllib.loads((ROOT / "samconfig.toml").read_text(encoding="utf-8"))
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
REGION_NAME = re.compile(r"\b(?:us|eu|ap|sa|ca|me|af|il|mx)-(?:east|west|north|south|central|northeast|southeast|"
                         r"northwest|southwest)-\d\b")


def _overrides(env: str) -> dict[str, str]:
    raw = SAMCONFIG[env]["deploy"]["parameters"]["parameter_overrides"]
    return dict(token.split("=", 1) for token in raw.split())


def _params(env: str, **extra: str) -> dict[str, str]:
    """Every parameter as CloudFormation would see it: the template default, then samconfig, then extra."""
    out = {k: str(v.get("Default", "")) for k, v in T["Parameters"].items()}
    out.update(_overrides(env))
    out.update(extra)
    return out


def _eval(expr, params: dict[str, str]):
    """The few intrinsic functions the template's Rules use."""
    if isinstance(expr, dict):
        (fn, arg), = expr.items()
        if fn == "Fn::Ref":
            return params[arg]
        if fn == "Fn::Equals":
            a, b = (_eval(x, params) for x in arg)
            return str(a) == str(b)
        if fn == "Fn::Not":
            return not _eval(arg[0], params)
        if fn == "Fn::And":
            return all(_eval(x, params) for x in arg)
        raise AssertionError(f"unexpected function {fn}")
    return expr


def _rule_failures(params: dict[str, str]) -> list[str]:
    out = []
    for rule in T["Rules"].values():
        if "RuleCondition" in rule and not _eval(rule["RuleCondition"], params):
            continue
        out += [a["AssertDescription"] for a in rule["Assertions"] if not _eval(a["Assert"], params)]
    return out


AUTHORITY = {"CapSender": "ddma-mandi@hp.gov.in", "CapSenderName": "District Disaster Management Authority, Mandi"}


# -- samconfig.toml --------------------------------------------------------------------------------
def test_prod_is_its_own_stack_in_mumbai():
    assert SAMCONFIG["prod"]["global"]["parameters"] == {"stack_name": "pukaar-prod", "region": "ap-south-1"}
    assert SAMCONFIG["default"]["global"]["parameters"]["stack_name"] == "pukaar-dev"
    prod = SAMCONFIG["prod"]["deploy"]["parameters"]
    assert prod["s3_prefix"] == "pukaar-prod" and prod["resolve_image_repos"] is True
    assert prod["confirm_changeset"] is True  # a person reads the prod change set before it runs


def test_prod_settings_are_the_safe_ones():
    p = _overrides("prod")
    assert p["Stage"] == "prod"
    assert p["ReplayEnabled"] == "false" and p["CriticalAutoSend"] == "false"
    assert p["RequireMfa"] == "true" and int(p["RetentionDays"]) == 365
    # no Nova model is in-region in ap-south-1: the us. profile cannot be called from there
    assert not p["BedrockModelId"].startswith("us.") and not p["BedrockFallbackRegion"].startswith("us-")
    # VoiceProvider is whatever the deployment configures (.env.deploy.prod.local), never fixed here
    assert "VoiceProvider" not in p


def test_deployment_values_never_live_in_git():
    text = (ROOT / "samconfig.toml").read_text(encoding="utf-8")
    for key in ("AlarmEmail=", "CapSender=", "CapSenderName=", "AfterActionFrom="):
        assert key not in text, key


def test_critical_auto_send_is_off_unless_set():
    assert T["Parameters"]["CriticalAutoSend"]["Default"] == "false"
    assert _overrides("default")["CriticalAutoSend"] == "false"  # dev turns it off on its next deploy too
    assert T["Globals"]["Function"]["Environment"]["Variables"]["PUKAAR_CRITICAL_AUTO_SEND"] == {"Fn::Ref": "CriticalAutoSend"}


def test_app_default_for_critical_auto_send_is_off(monkeypatch):
    from Pukaar.core.config import get_settings

    monkeypatch.delenv("PUKAAR_CRITICAL_AUTO_SEND", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().critical_auto_send is False
    finally:
        get_settings.cache_clear()


# -- the template refuses an unsafe prod deploy ------------------------------------------------------
def test_prod_rule_passes_with_the_authority_set():
    assert _rule_failures(_params("prod", **AUTHORITY)) == []


@pytest.mark.parametrize("change,needs", [
    ({"CapSender": ""}, "CapSender"),
    ({"CapSenderName": ""}, "CapSenderName"),
    ({"ReplayEnabled": "true"}, "ReplayEnabled=false"),
    ({"RequireMfa": "false"}, "RequireMfa=true"),
    ({"RetentionDays": "0"}, "RetentionDays"),
])
def test_prod_rule_refuses_each_missing_setting(change, needs):
    failures = _rule_failures(_params("prod", **{**AUTHORITY, **change}))
    assert len(failures) == 1 and needs in failures[0]


def test_dev_is_not_held_to_the_prod_rule():
    # dev keeps the demo sender, replay and optional MFA
    assert _rule_failures(_params("default")) == []


def test_make_deploy_refuses_prod_without_the_authority_and_never_seeds_demo_users():
    deploy = MAKEFILE.split("\ndeploy:", 1)[1].split("\n\n", 1)[0]
    assert "--config-env $(SAM_ENV)" in deploy
    assert 'test -n "$(CAP_SENDER)" -a -n "$(CAP_SENDER_NAME)"' in deploy and '*"(demo)"*' in deploy
    assert "-include .env.deploy.$(STAGE).local" in MAKEFILE
    assert "'CapSenderName=\"$(CAP_SENDER_NAME)\"'" in MAKEFILE  # one quoted value: names hold spaces and commas
    seed = MAKEFILE.split("\nseed:", 1)[1].split("\n\n", 1)[0]
    assert '"$(STAGE)" = prod' in seed and "seed_users.py" in seed
    reset = MAKEFILE.split("\nreset-demo:", 1)[1].split("\n\n", 1)[0]
    assert 'test "$(STAGE)" != prod' in reset


def test_seed_users_refuses_a_production_stack():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import seed_users
    finally:
        sys.path.pop(0)
    assert seed_users.is_production("pukaar-prod", "") and seed_users.is_production("pukaar-x", "prod")
    assert not seed_users.is_production("pukaar-dev", "dev")


# -- Cognito MFA -----------------------------------------------------------------------------------------
def test_mfa_is_totp_required_when_asked_and_optional_otherwise():
    p = T["Parameters"]["RequireMfa"]
    assert set(p["AllowedValues"]) == {"true", "false"} and p["Default"] == "false"
    assert T["Conditions"]["MfaRequired"] == {"Fn::Equals": [{"Fn::Ref": "RequireMfa"}, "true"]}
    pool = RES["UserPool"]["Properties"]
    assert pool["MfaConfiguration"] == {"Fn::If": ["MfaRequired", "ON", "OPTIONAL"]}
    assert pool["EnabledMfas"] == ["SOFTWARE_TOKEN_MFA"]  # an authenticator app, never SMS


# -- DPDP retention ------------------------------------------------------------------------------------------
def test_retention_expires_report_media_in_s3_and_reports_in_dynamodb():
    p = T["Parameters"]["RetentionDays"]
    assert p["Type"] == "Number" and p["Default"] == 0 and p["MinValue"] == 0
    cond, rules, otherwise = RES["Bucket"]["Properties"]["LifecycleConfiguration"]["Fn::If"]
    assert cond == "HasRetention" and otherwise == {"Fn::Ref": "AWS::NoValue"}
    by_prefix = {r["Prefix"]: r for r in rules["Rules"]}
    for r in by_prefix.values():
        assert r["Status"] == "Enabled" and r["ExpirationInDays"] == {"Fn::Ref": "RetentionDays"}
    # the prefixes are the ones reports are stored under
    src = (ROOT / "backend" / "src" / "Pukaar" / "services" / "reports.py").read_text(encoding="utf-8")
    for prefix in by_prefix:
        assert f'f"{prefix}' in src, prefix
    assert set(by_prefix) == {"audio/reports/", "photos/"}
    env = T["Globals"]["Function"]["Environment"]["Variables"]
    assert env["PUKAAR_REPORT_RETENTION_DAYS"] == {"Fn::Ref": "RetentionDays"}
    assert RES["Table"]["Properties"]["TimeToLiveSpecification"] == {"AttributeName": "ttl", "Enabled": True}


def test_a_report_carries_its_expiry_and_is_never_served_after_it(repo, frozen, monkeypatch):
    from Pukaar.core import clock
    from Pukaar.core.config import get_settings
    from Pukaar.store.models import Report

    monkeypatch.setenv("PUKAAR_REPORT_RETENTION_DAYS", "365")
    get_settings.cache_clear()
    try:
        now = clock.now()
        fresh = Report(id="rpt_fresh", village_id="gohar", created_at=clock.iso(now), track_code="FRESH1")
        old = Report(id="rpt_old", village_id="gohar", created_at="2025-06-01T00:00:00Z", track_code="OLD001")
        repo.put_report(fresh)
        repo.put_report(old)
        item = repo._get("VILLAGE#gohar", f"REPORT#{fresh.created_at}#{fresh.id}")
        assert int(item["ttl"]) == int(now.timestamp()) + 365 * 86400
        assert int(repo._get("REPORTREF#rpt_fresh", "META")["ttl"]) == int(item["ttl"])
        assert int(repo._get("TRACK#FRESH1", "META")["ttl"]) == int(item["ttl"])
        # over a year old: DynamoDB may not have deleted it yet, but nothing serves it
        assert [r.id for r in repo.list_reports("gohar")] == ["rpt_fresh"]
        assert repo.get_report("rpt_old") is None and repo.report_by_track("OLD001") is None
        # writing it again (a state change) never extends the expiry
        repo.put_report(fresh.model_copy(update={"state": "verified"}))
        assert int(repo._get("VILLAGE#gohar", f"REPORT#{fresh.created_at}#{fresh.id}")["ttl"]) == int(item["ttl"])
    finally:
        monkeypatch.delenv("PUKAAR_REPORT_RETENTION_DAYS")
        get_settings.cache_clear()
    # 0 (dev): kept
    repo.put_report(Report(id="rpt_kept", village_id="thunag", created_at="2020-01-01T00:00:00Z"))
    assert "ttl" not in repo._get("VILLAGE#thunag", "REPORT#2020-01-01T00:00:00Z#rpt_kept")
    assert repo.get_report("rpt_kept") is not None


# -- region independence ----------------------------------------------------------------------------------
def test_no_region_is_written_into_the_resources():
    """Every region comes from ${AWS::Region} or a parameter, so the stack deploys to ap-south-1 as is.
    Region names may appear only as parameter defaults (the dev stack's)."""
    for section in ("Resources", "Globals", "Outputs", "Conditions", "Rules"):
        text = json.dumps(T.get(section, {}), ensure_ascii=False)
        found = REGION_NAME.findall(text)
        assert not found, (section, found)
    assert "us.amazon.nova" not in json.dumps(T["Resources"])  # the IAM grants cover any Nova profile


def test_model_and_fallback_region_are_parameters_that_accept_mumbai_values():
    model = re.compile(T["Parameters"]["BedrockModelId"]["AllowedPattern"])
    for ok in ("us.amazon.nova-2-lite-v1:0", "global.amazon.nova-2-lite-v1:0", "apac.amazon.nova-lite-v1:0"):
        assert model.fullmatch(ok), ok
    assert not model.fullmatch("anthropic.claude-v2")
    region = re.compile(T["Parameters"]["BedrockFallbackRegion"]["AllowedPattern"])
    assert region.fullmatch("ap-southeast-1") and region.fullmatch("us-west-2") and not region.fullmatch("mumbai")
    env = T["Globals"]["Function"]["Environment"]["Variables"]
    assert env["PUKAAR_AWS_REGION"] == {"Fn::Ref": "AWS::Region"}
    assert env["PUKAAR_BEDROCK_MODEL_ID"] == {"Fn::Ref": "BedrockModelId"}


def test_scripts_follow_the_stage_region():
    for path in ("backend/src/Pukaar/scripts/iot_provision.py", "backend/src/Pukaar/scripts/gauge_sim.py",
                 "scripts/seed_users.py", "scripts/stack_env.sh", "scripts/put_secrets.sh"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "AWS_REGION" in text, path
        for line in text.splitlines():
            if "us-east-1" in line:
                assert "AWS_REGION" in line or "AWS_DEFAULT_REGION" in line, (path, line)  # only as the fallback
    assert "export AWS_REGION   = $(REGION)" in MAKEFILE and "export PUKAAR_STACK = $(STACK)" in MAKEFILE


# -- CAP sender ---------------------------------------------------------------------------------------------
def test_cap_sender_parameters_reach_the_functions():
    env = T["Globals"]["Function"]["Environment"]["Variables"]
    for var, param in (("PUKAAR_CAP_SENDER", "CapSender"), ("PUKAAR_CAP_SENDER_NAME", "CapSenderName"),
                       ("PUKAAR_CAP_SENDER_NAME_HI", "CapSenderNameHi")):
        assert env[var] == {"Fn::Ref": param}
        assert T["Parameters"][param]["Default"] == ""  # dev keeps the demo sender
    sender = re.compile(T["Parameters"]["CapSender"]["AllowedPattern"])
    assert sender.fullmatch("ddma-mandi@hp.gov.in") and sender.fullmatch("")
    for bad in ("DDMA Mandi", "a,b", "a<b", "a&b"):
        assert not sender.fullmatch(bad), bad
