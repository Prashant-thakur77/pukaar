"""Safety, cost and operations claims, checked against the real SAM template.

README.md promises least-privilege IAM, nothing billed by the hour, and
recoverable data. These tests parse infra/template.yaml so the promises fail
the build if the template drifts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

TEMPLATE = Path(__file__).resolve().parents[2] / "infra" / "template.yaml"


class _CfnLoader(yaml.SafeLoader):
    """Reads CloudFormation short tags (!Sub, !Ref, ...) as plain values."""


def _tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return {f"Fn::{suffix}": loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {f"Fn::{suffix}": loader.construct_sequence(node, deep=True)}
    return {f"Fn::{suffix}": loader.construct_mapping(node, deep=True)}


_CfnLoader.add_multi_constructor("!", _tag)
T = yaml.load(TEMPLATE.read_text(encoding="utf-8"), Loader=_CfnLoader)
RES: dict[str, dict] = T["Resources"]

# Actions AWS does not allow to be scoped to a resource ARN. Each use in the
# template carries a comment saying why.
UNSCOPABLE = {
    "states:SendTaskSuccess",
    "states:SendTaskFailure",
    "states:SendTaskHeartbeat",
    "polly:SynthesizeSpeech",
    "transcribe:StartStreamTranscription",
    "transcribe:StartStreamTranscriptionWebSocket",
    # Step Functions log delivery (vended logs) requires "*".
    "logs:CreateLogDelivery",
    "logs:GetLogDelivery",
    "logs:UpdateLogDelivery",
    "logs:DeleteLogDelivery",
    "logs:ListLogDeliveries",
    "logs:PutResourcePolicy",
    "logs:DescribeResourcePolicies",
    "logs:DescribeLogGroups",
}

# Anything billed per hour whether or not it is used.
ALWAYS_ON = {
    "AWS::EC2::NatGateway",
    "AWS::EC2::Instance",
    "AWS::RDS::DBInstance",
    "AWS::RDS::DBCluster",
    "AWS::ElastiCache::CacheCluster",
    "AWS::ElastiCache::ReplicationGroup",
    "AWS::OpenSearchService::Domain",
    "AWS::OpenSearchServerless::Collection",
    "AWS::Kendra::Index",
    "AWS::ECS::Service",
    "AWS::ElasticLoadBalancingV2::LoadBalancer",
    "AWS::EKS::Cluster",
    "AWS::MSK::Cluster",
    "AWS::Redshift::Cluster",
    "AWS::SageMaker::Endpoint",
}


def _statements() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for name, res in RES.items():
        props = res.get("Properties", {})
        for pol in props.get("Policies") or []:
            if isinstance(pol, dict) and "Statement" in pol:
                out += [(name, s) for s in pol["Statement"]]
        for pol in props.get("Policies", []) if res["Type"] == "AWS::IAM::Role" else []:
            doc = pol.get("PolicyDocument", {}) if isinstance(pol, dict) else {}
            out += [(name, s) for s in doc.get("Statement", [])]
    return out


def _as_list(v: Any) -> list:
    return v if isinstance(v, list) else [v]


def test_template_has_policies_to_check():
    assert len(_statements()) >= 10


def test_no_service_wide_or_global_allow():
    for name, s in _statements():
        if s.get("Effect") != "Allow":
            continue
        for action in _as_list(s["Action"]):
            assert action != "*" and not action.endswith(":*"), f"{name} allows {action}"


def test_wildcard_resources_only_for_unscopable_actions():
    for name, s in _statements():
        if s.get("Effect") == "Allow" and s.get("Resource") == "*":
            extra = set(_as_list(s["Action"])) - UNSCOPABLE
            assert not extra, f"{name} grants {sorted(extra)} on every resource"


def test_nothing_billed_by_the_hour():
    types = {r["Type"] for r in RES.values()}
    assert not types & ALWAYS_ON, f"always-on resources: {sorted(types & ALWAYS_ON)}"


def test_table_recoverable_and_expiring():
    tables = [r for r in RES.values() if r["Type"] == "AWS::DynamoDB::Table"]
    assert len(tables) == 1, "single-table design"
    p = tables[0]["Properties"]
    assert p["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"] is True
    assert p["TimeToLiveSpecification"]["Enabled"] is True
    assert p.get("BillingMode") == "PAY_PER_REQUEST"


def test_logs_expire():
    groups = [n for n, r in RES.items() if r["Type"] == "AWS::Logs::LogGroup"]
    assert groups
    for n in groups:
        assert 1 <= RES[n]["Properties"].get("RetentionInDays", 0) <= 90, n


def test_bucket_private_encrypted_tls_only():
    b = next(r for r in RES.values() if r["Type"] == "AWS::S3::Bucket")["Properties"]
    assert all(b["PublicAccessBlockConfiguration"].values())
    assert b["BucketEncryption"]["ServerSideEncryptionConfiguration"]
    deny = [
        s
        for r in RES.values()
        if r["Type"] == "AWS::S3::BucketPolicy"
        for s in r["Properties"]["PolicyDocument"]["Statement"]
        if s["Effect"] == "Deny"
    ]
    assert any(s.get("Condition", {}).get("Bool", {}).get("aws:SecureTransport") == "false" for s in deny)


def test_queues_encrypted():
    for n, r in RES.items():
        if r["Type"] == "AWS::SQS::Queue":
            assert r["Properties"].get("SqsManagedSseEnabled") is True, n


def test_sweep_schedule_does_not_retry_and_has_dlq():
    s = next(r for r in RES.values() if r["Type"] == "AWS::Scheduler::Schedule")["Properties"]["Target"]
    assert s["RetryPolicy"]["MaximumRetryAttempts"] == 0
    assert "DeadLetterConfig" in s
