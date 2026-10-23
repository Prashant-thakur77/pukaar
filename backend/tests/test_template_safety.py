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
    # CloudWatch metrics have no resource type; the canary's grant is held to the Pukaar namespace by a
    # condition instead (test_canary_may_only_put_pukaar_metrics).
    "cloudwatch:PutMetricData",
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
    "AWS::WAFv2::WebACL",
}

# Billed by the month whatever the traffic, allowed only on prod, each behind a condition that is true
# for Stage=prod alone. AWS WAF ($5 a month per web ACL and $1 per rule): AWS WAF cannot attach to an
# HTTP API, so on prod CloudFront carries it in front of the API (infra/waf-edge.yaml, us-east-1).
PROD_ONLY_MONTHLY = {"AWS::WAFv2::WebACL"}
EDGE_TEMPLATE = TEMPLATE.parent / "waf-edge.yaml"


def _unwrap_if(pol: Any) -> list:
    """A conditional policy (!If [cond, policy, !Ref AWS::NoValue]) is checked as if its condition were true."""
    if isinstance(pol, dict) and "Fn::If" in pol:
        return [p for branch in pol["Fn::If"][1:] for p in _unwrap_if(branch)]
    return [pol]


def _statements() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for name, res in RES.items():
        props = res.get("Properties", {})
        for pol in [p for raw in props.get("Policies") or [] for p in _unwrap_if(raw)]:
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


def _load(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_CfnLoader)


def _prod_only(template: dict, condition: str) -> bool:
    """True when the named condition holds only for Stage=prod (alone, or And-ed with anything)."""
    expr = template.get("Conditions", {}).get(condition)
    if expr == {"Fn::Equals": [{"Fn::Ref": "Stage"}, "prod"]}:
        return True
    if isinstance(expr, dict) and "Fn::And" in expr:
        return any(_prod_only(template, c["Fn::Condition"]) for c in expr["Fn::And"]
                   if isinstance(c, dict) and "Fn::Condition" in c)
    return False


def test_nothing_billed_by_the_hour():
    for template in (T, _load(EDGE_TEMPLATE)):
        for name, r in template["Resources"].items():
            if r["Type"] not in ALWAYS_ON:
                continue
            assert r["Type"] in PROD_ONLY_MONTHLY, f"always-on resource {name} ({r['Type']})"
            assert _prod_only(template, r.get("Condition", "")), f"{name} must exist on Stage=prod only"


def test_dev_has_no_waf_and_prod_puts_cloudfront_with_waf_in_front_of_the_api():
    edge = _load(EDGE_TEMPLATE)
    acl = edge["Resources"]["EdgeWebAcl"]["Properties"]
    assert acl["Scope"] == "CLOUDFRONT"  # an HTTP API cannot take a web ACL; CloudFront can
    rules = {r["Name"]: r for r in acl["Rules"]}
    managed = {r["Statement"]["ManagedRuleGroupStatement"]["Name"] for r in rules.values()
               if "ManagedRuleGroupStatement" in r["Statement"]}
    assert {"AWSManagedRulesCommonRuleSet", "AWSManagedRulesAmazonIpReputationList"} <= managed
    reports = rules["reports-per-ip"]["Statement"]["RateBasedStatement"]
    assert reports["AggregateKeyType"] == "IP" and reports["EvaluationWindowSec"] == 300
    assert edge["Parameters"]["ReportsPerIpPer5Min"]["Default"] == 100
    matches = [s["ByteMatchStatement"]["SearchString"]
               for s in reports["ScopeDownStatement"]["AndStatement"]["Statements"]]
    assert matches == ["/reports", "POST"]
    # A villager's photo report is larger than the common rule set's 8 KB body limit: counted, never blocked.
    overrides = {o["Name"]: o["ActionToUse"] for o in
                 rules["aws-common"]["Statement"]["ManagedRuleGroupStatement"]["RuleActionOverrides"]}
    assert overrides["SizeRestrictions_BODY"] == {"Count": {}}
    # The main stack: CloudFront and its function only when prod has an edge web ACL.
    assert _prod_only(T, "HasApiEdge")
    for name in ("ApiEdgeDistribution", "ApiEdgeHostFunction"):
        assert RES[name]["Condition"] == "HasApiEdge", name
    dist = RES["ApiEdgeDistribution"]["Properties"]["DistributionConfig"]
    assert dist["WebACLId"] == {"Fn::Ref": "EdgeWebAclArn"}
    assert dist["Origins"][0]["OriginCustomHeaders"][0]["HeaderName"] == "X-Pukaar-Edge"
    assert T["Parameters"]["EdgeWebAclArn"]["Default"] == ""
    env = T["Globals"]["Function"]["Environment"]["Variables"]
    assert env["PUKAAR_EDGE_REQUIRED"] == {"Fn::If": ["HasApiEdge", "true", "false"]}
    assert "EdgeWebAclArn" not in (ROOT / "samconfig.toml").read_text(encoding="utf-8")  # set per deployment


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
    s = RES["SweepSchedule"]["Properties"]["Target"]
    assert s["RetryPolicy"]["MaximumRetryAttempts"] == 0
    assert "DeadLetterConfig" in s


def test_canary_runs_every_15_minutes_without_synthetics():
    types = {r["Type"] for r in RES.values()}
    assert not {t for t in types if t.startswith("AWS::Synthetics::")}  # billed per canary run
    sched = RES["CanarySchedule"]["Properties"]
    assert sched["ScheduleExpression"] == "rate(15 minutes)"
    assert sched["Target"]["Arn"] == {"Fn::GetAtt": "CanaryFunction.Arn"}
    fn = RES["CanaryFunction"]["Properties"]
    assert fn["ImageConfig"]["Command"] == ["Pukaar.handlers.canary.handler"]
    assert fn["EventInvokeConfig"]["MaximumRetryAttempts"] == 0 and fn["Tracing"] == "PassThrough"


def test_canary_may_only_put_pukaar_metrics():
    grants = [s for n, s in _statements() if n == "CanaryFunction"]
    assert len(grants) == 1
    (s,) = grants
    assert _as_list(s["Action"]) == ["cloudwatch:PutMetricData"] and s["Resource"] == "*"
    assert s["Condition"] == {"StringEquals": {"cloudwatch:namespace": "Pukaar"}}
    assert RES["CanaryFunction"]["Properties"]["Policies"] == [{"Statement": [s]}]
    role = RES["CanaryScheduleRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    assert role == [{"Effect": "Allow", "Action": "lambda:InvokeFunction",
                     "Resource": {"Fn::GetAtt": "CanaryFunction.Arn"}}]


def test_cors_preflight_skips_the_authorizer():
    """The browser sends OPTIONS without a token; it must not meet the Cognito authorizer."""
    events = [
        e["Properties"]
        for r in RES.values()
        if r["Type"] == "AWS::Serverless::Function"
        for e in (r["Properties"].get("Events") or {}).values()
        if e.get("Type") == "HttpApi"
    ]
    pre = [e for e in events if e.get("Method") == "OPTIONS" and e.get("Path") == "/{proxy+}"]
    assert pre and pre[0].get("Auth", {}).get("Authorizer") == "NONE"


def test_cap_feed_routes_are_public_get_only():
    """SACHET and other CAP aggregators fetch the feed with no token; only GET is opened."""
    events = [
        e["Properties"]
        for r in RES.values()
        if r["Type"] == "AWS::Serverless::Function"
        for e in (r["Properties"].get("Events") or {}).values()
        if e.get("Type") == "HttpApi"
    ]
    for path in ("/cap/alerts.atom", "/cap/alerts/{file}"):
        routes = [e for e in events if e.get("Path") == path]
        assert [e["Method"] for e in routes] == ["GET"], path
        assert routes[0].get("Auth", {}).get("Authorizer") == "NONE", path


def test_web_push_key_is_the_only_public_push_route_and_cors_allows_delete():
    """Browsers fetch the VAPID public key signed out; subscribing stays behind Cognito (ANY /{proxy+})."""
    events = [
        e["Properties"]
        for r in RES.values()
        if r["Type"] == "AWS::Serverless::Function"
        for e in (r["Properties"].get("Events") or {}).values()
        if e.get("Type") == "HttpApi"
    ]
    routes = [e for e in events if e.get("Path") == "/push/vapid-public-key"]
    assert [e["Method"] for e in routes] == ["GET"]
    assert routes[0].get("Auth", {}).get("Authorizer") == "NONE"
    assert not [e for e in events if "/me" in str(e.get("Path")) or "push-" in str(e.get("Path"))]
    cors = RES["HttpApi"]["Properties"]["CorsConfiguration"]
    assert "DELETE" in cors["AllowMethods"]  # DELETE /me/push-subscriptions/{id}


VOICE_ROUTES = {
    ("/voice/exotel/flow", "GET"), ("/voice/exotel/flow", "HEAD"), ("/voice/exotel/gather", "GET"),
    ("/voice/exotel/status", "POST"), ("/voice/plivo/answer", "POST"), ("/voice/plivo/digits", "POST"),
    ("/voice/plivo/hangup", "POST"),
    # inbound calls (delivery/inbound.py): IVR self-enrolment and "report what you see"
    ("/voice/exotel/inbound/{part}", "GET"), ("/voice/exotel/inbound/{part}", "HEAD"),
    ("/voice/plivo/inbound", "POST"), ("/voice/plivo/inbound-hangup", "POST"),
}


def test_voice_webhooks_are_exactly_these_public_routes_and_each_checks_its_key():
    """Call providers carry no Cognito token: each /voice route is opened alone, and the app refuses it without
    the webhook key (the signed call token, the call id and Plivo's signature are tested in test_voice.py)."""
    events = [
        e["Properties"]
        for r in RES.values()
        if r["Type"] == "AWS::Serverless::Function"
        for e in (r["Properties"].get("Events") or {}).values()
        if e.get("Type") == "HttpApi"
    ]
    voice_events = [e for e in events if str(e.get("Path")).startswith("/voice/")]
    assert {(e["Path"], e["Method"]) for e in voice_events} == VOICE_ROUTES
    assert all(e.get("Auth", {}).get("Authorizer") == "NONE" for e in voice_events)
    params = T["Parameters"]
    assert params["VoiceProvider"]["Default"] == "off"
    assert set(params["VoiceProvider"]["AllowedValues"]) == {"off", "exotel", "plivo"}
    env = T["Globals"]["Function"]["Environment"]["Variables"]
    assert env["PUKAAR_VOICE_PROVIDER"] == {"Fn::Ref": "VoiceProvider"}
    # No provider credential is ever a template parameter or an environment value.
    text = TEMPLATE.read_text(encoding="utf-8").lower()
    assert "exotel_token" not in text and "plivo_auth_token" not in text

    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient

    from Pukaar.main import app

    app_routes = {(r.path, m) for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/voice/")
                  for m in r.methods}
    assert app_routes == VOICE_ROUTES
    client = TestClient(app)
    for path, method in VOICE_ROUTES:
        assert client.request(method, path, params={"digits": '"1"', "CallSid": "x"}).status_code == 403, (path, method)


# -- river gauges over AWS IoT Core ------------------------------------------
THING = "${!iot:Connection.Thing.ThingName}"  # IoT policy variable, escaped from Fn::Sub


def test_gauge_iot_policy_allows_only_own_client_id_and_own_reading_topic():
    """A stolen gauge certificate can connect as that gauge and publish its readings (live and
    backfill); nothing else."""
    policies = {n for n, r in RES.items() if r["Type"] == "AWS::IoT::Policy"}
    assert policies == {"PukaarGaugePolicy", "PukaarSirenPolicy", "PukaarBoxPolicy", "PukaarRelayPolicy"}
    stmts = RES["PukaarGaugePolicy"]["Properties"]["PolicyDocument"]["Statement"]
    assert all(s["Effect"] == "Allow" for s in stmts)
    by_action = {}
    for s in stmts:
        actions, resources = _as_list(s["Action"]), _as_list(s["Resource"])
        assert len(actions) == 1, s
        assert "*" not in actions[0], f"wildcard action {actions[0]}"
        by_action[actions[0]] = ([r["Fn::Sub"] for r in resources], s.get("Condition"))
    assert set(by_action) == {"iot:Connect", "iot:Publish"}  # no Subscribe, Receive, shadow or jobs

    connect, cond = by_action["iot:Connect"]
    assert connect == [f"arn:${{AWS::Partition}}:iot:${{AWS::Region}}:${{AWS::AccountId}}:client/{THING}"]
    assert cond == {"Bool": {"iot:Connection.Thing.IsAttached": "true"}}
    publish, _ = by_action["iot:Publish"]
    assert publish == [f"arn:${{AWS::Partition}}:iot:${{AWS::Region}}:${{AWS::AccountId}}:"
                       f"topic/pukaar/gauge/*/{THING}/{kind}" for kind in ("reading", "backfill")]


def test_gauge_rule_feeds_the_ingest_lambda_with_errors_to_the_dlq():
    rule = RES["PukaarGaugeRule"]["Properties"]["TopicRulePayload"]
    assert rule["Sql"] == ("SELECT *, topic(3) AS village_id, topic(4) AS device_id, topic(5) AS topic_kind "
                           "FROM 'pukaar/gauge/+/+/+' WHERE topic(5) = 'reading' OR topic(5) = 'backfill'")
    assert rule["AwsIotSqlVersion"] == "2016-03-23"
    assert rule["Actions"] == [{"Lambda": {"FunctionArn": {"Fn::GetAtt": "GaugeIngestFunction.Arn"}}}]
    assert rule["ErrorAction"]["Sqs"]["QueueUrl"] == {"Fn::Ref": "WorkerDLQ"}

    fn = RES["GaugeIngestFunction"]["Properties"]
    assert fn["ImageConfig"]["Command"] == ["Pukaar.handlers.gauge_ingest.handler"]
    assert fn["EventInvokeConfig"]["MaximumRetryAttempts"] == 0
    assert fn["EventInvokeConfig"]["DestinationConfig"]["OnFailure"]["Destination"] == {"Fn::GetAtt": "WorkerDLQ.Arn"}

    perms = [r["Properties"] for r in RES.values() if r["Type"] == "AWS::Lambda::Permission"
             and r["Properties"]["Principal"] == "iot.amazonaws.com"]
    rules = sorted(n for n, r in RES.items() if r["Type"] == "AWS::IoT::TopicRule")
    # One permission per topic rule, each for its own rule only, all on the one ingest function.
    assert sorted(p["SourceArn"]["Fn::GetAtt"].removesuffix(".Arn") for p in perms) == rules
    assert all(p["FunctionName"] == {"Fn::GetAtt": "GaugeIngestFunction.Arn"} for p in perms)

    # The handler module the rule names exists and parses the rule's output.
    from Pukaar.handlers import gauge_ingest

    assert callable(gauge_ingest.handler)


def test_sweep_may_only_invoke_the_nova_model_for_its_access_probe():
    """The sweep's one model permission is a plain InvokeModel (what Converse needs) on Nova models and
    Nova inference profiles of this region (any geography: us., apac., global.)."""
    grants = [s for n, s in _statements() if n == "SweepFunction" and any(a.startswith("bedrock:") for a in _as_list(s["Action"]))]
    assert len(grants) == 1
    (s,) = grants
    assert s["Sid"] == "ModelAccessProbe" and _as_list(s["Action"]) == ["bedrock:InvokeModel"]
    resources = [r["Fn::Sub"] for r in _as_list(s["Resource"])]
    assert resources and all(":foundation-model/amazon.nova-" in r or ":inference-profile/*.amazon.nova-" in r
                             for r in resources)
    assert not any(r.endswith("*:*") or r.endswith("/*") for r in resources)
    profiles = [r for r in resources if ":inference-profile/" in r]
    assert profiles and all(":${AWS::Region}:${AWS::AccountId}:" in r for r in profiles)


def test_apply_guardrail_scoped_to_the_report_guardrail():
    """Only the worker screens report text, and only with Pukaar's own guardrail."""
    grants = [(n, s) for n, s in _statements() if "bedrock:ApplyGuardrail" in _as_list(s["Action"])]
    assert [n for n, _ in grants] == ["WorkerFunction"]
    for _, s in grants:
        assert _as_list(s["Action"]) == ["bedrock:ApplyGuardrail"]
        assert s["Resource"] == {"Fn::GetAtt": "ReportGuardrail.GuardrailArn"}


def test_report_guardrail_blocks_prompt_attacks_and_masks_phones():
    from Pukaar.llm.guardrail import INSTRUCTION_TOPIC

    g = RES["ReportGuardrail"]
    assert g["Type"] == "AWS::Bedrock::Guardrail"
    filters = {f["Type"]: f for f in g["Properties"]["ContentPolicyConfig"]["FiltersConfig"]}
    assert filters["PROMPT_ATTACK"]["InputStrength"] == "HIGH" and filters["PROMPT_ATTACK"]["OutputStrength"] == "NONE"
    topics = g["Properties"]["TopicPolicyConfig"]["TopicsConfig"]
    assert any(t["Type"] == "DENY" and t["Name"] == INSTRUCTION_TOPIC for t in topics)
    pii = {p["Type"]: p["Action"] for p in g["Properties"]["SensitiveInformationPolicyConfig"]["PiiEntitiesConfig"]}
    assert pii == {"PHONE": "ANONYMIZE", "EMAIL": "ANONYMIZE"}
    assert RES["ReportGuardrailVersion"]["Type"] == "AWS::Bedrock::GuardrailVersion"
    env = T["Globals"]["Function"]["Environment"]["Variables"]
    assert env["PUKAAR_GUARDRAIL_ID"] == {"Fn::GetAtt": "ReportGuardrail.GuardrailId"}
    assert env["PUKAAR_GUARDRAIL_VERSION"] == {"Fn::GetAtt": "ReportGuardrailVersion.Version"}


# -- live push (AppSync Events) ----------------------------------------------
IAM_ONLY = [{"AuthType": "AWS_IAM"}]
PUBLISH_FUNCTIONS = {"ApiFunction", "SweepFunction", "WorkflowFunction", "WorkerFunction", "GaugeIngestFunction"}
NAMESPACE_ARNS = [{"Fn::GetAtt": "PublicEvents.ChannelNamespaceArn"}, {"Fn::GetAtt": "OfficerEvents.ChannelNamespaceArn"}]


def test_live_push_publish_is_iam_only_everywhere():
    """Neither the public API key nor an officer's Cognito token can publish an event."""
    api = RES["PukaarEvents"]
    assert api["Type"] == "AWS::AppSync::Api"
    cfg = api["Properties"]["EventConfig"]
    assert cfg["DefaultPublishAuthModes"] == IAM_ONLY
    assert {p["AuthType"] for p in cfg["AuthProviders"]} == {"API_KEY", "AWS_IAM", "AMAZON_COGNITO_USER_POOLS"}
    cognito = next(p for p in cfg["AuthProviders"] if p["AuthType"] == "AMAZON_COGNITO_USER_POOLS")["CognitoConfig"]
    assert cognito["UserPoolId"] == {"Fn::Ref": "UserPool"}
    assert "AWS_IAM" not in {m["AuthType"] for m in cfg["ConnectionAuthModes"]}  # browsers only connect

    spaces = {r["Properties"]["Name"]: r["Properties"] for r in RES.values()
              if r["Type"] == "AWS::AppSync::ChannelNamespace"}
    assert set(spaces) == {"public", "officer"}
    for name, ns in spaces.items():
        assert ns["ApiId"] == {"Fn::GetAtt": "PukaarEvents.ApiId"}
        assert ns["PublishAuthModes"] == IAM_ONLY, name
        assert "CodeHandlers" not in ns and "HandlerConfigs" not in ns  # nothing rewrites events in flight
    assert {m["AuthType"] for m in spaces["public"]["SubscribeAuthModes"]} == {"API_KEY", "AMAZON_COGNITO_USER_POOLS"}
    assert spaces["officer"]["SubscribeAuthModes"] == [{"AuthType": "AMAZON_COGNITO_USER_POOLS"}]

    key = [r["Properties"] for r in RES.values() if r["Type"] == "AWS::AppSync::ApiKey"]
    assert len(key) == 1 and key[0]["ApiId"] == {"Fn::GetAtt": "PukaarEvents.ApiId"}
    assert key[0]["Expires"] == {"Fn::Ref": "EventsApiKeyExpires"}


def test_live_push_grant_is_publish_only_and_scoped_to_the_two_namespaces():
    grants = [(n, s) for n, s in _statements()
              if any(str(a).startswith("appsync:") for a in _as_list(s["Action"]))]
    assert {n for n, _ in grants} == PUBLISH_FUNCTIONS
    for name, s in grants:
        assert _as_list(s["Action"]) == ["appsync:EventPublish"], name  # no subscribe, connect or admin
        assert s["Resource"] == NAMESPACE_ARNS, name
    env = T["Globals"]["Function"]["Environment"]["Variables"]
    assert env["PUKAAR_EVENTS_HTTP_DOMAIN"] == {"Fn::GetAtt": "PukaarEvents.Dns.Http"}
    outs = T["Outputs"]
    assert outs["EventsHttpDomain"]["Value"] == {"Fn::GetAtt": "PukaarEvents.Dns.Http"}
    assert outs["EventsRealtimeDomain"]["Value"] == {"Fn::GetAtt": "PukaarEvents.Dns.Realtime"}
    assert outs["EventsApiKey"]["Value"] == {"Fn::GetAtt": "PublicEventsKey.ApiKey"}


# -- alarms that reach someone ---------------------------------------------------------------
ROOT = TEMPLATE.parents[1]
SRC = ROOT / "backend" / "src" / "Pukaar"


def _alarms() -> dict[str, dict]:
    return {n: r["Properties"] for n, r in RES.items() if r["Type"] == "AWS::CloudWatch::Alarm"}


def test_every_alarm_notifies_the_alarm_topic():
    for name, props in _alarms().items():
        assert props.get("AlarmActions") == [{"Fn::Ref": "AlarmTopic"}], name


def test_alarm_email_is_subscribed_and_make_deploy_passes_it_from_the_local_env_file():
    sub = RES["AlarmEmailSubscription"]
    assert sub["Condition"] == "HasAlarmEmail"
    assert sub["Properties"]["Endpoint"] == {"Fn::Ref": "AlarmEmail"}
    assert sub["Properties"]["TopicArn"] == {"Fn::Ref": "AlarmTopic"}
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "-include .env.deploy.local" in makefile
    assert "$(if $(ALARM_EMAIL),AlarmEmail=$(ALARM_EMAIL))" in makefile
    deploy = makefile.split("\ndeploy:", 1)[1].split("\n\n", 1)[0]
    assert "$(DEPLOY_EXTRA)" in deploy and "ALARM_EMAIL is not set" in deploy
    # the address itself is never committed
    assert "AlarmEmail=" not in (ROOT / "samconfig.toml").read_text(encoding="utf-8")


def test_per_village_stale_data_alarm_watches_the_metric_the_sweep_emits():
    props = _alarms()["VillageDataStaleAlarm"]
    expr = props["Metrics"][0]["Expression"]
    assert "VillageDataStale" in expr and props["Metrics"][0]["Period"] <= 900
    assert props["ComparisonOperator"] == "GreaterThanOrEqualToThreshold" and props["Threshold"] == 1
    engine = (SRC / "services" / "decision_engine.py").read_text(encoding="utf-8")
    assert 'metric("VillageDataStale", 1, Village=village.id)' in engine


def test_delivery_failed_alarm_watches_the_metric_dispatch_emits():
    expr = _alarms()["DeliveryFailedAlarm"]["Metrics"][0]["Expression"]
    assert "DeliveryFailed" in expr
    dispatch = (SRC / "delivery" / "dispatch.py").read_text(encoding="utf-8")
    assert dispatch.count('metric("DeliveryFailed"') >= 2  # Telegram errors and blocked sends


def test_replay_can_be_switched_off_for_a_real_pilot():
    p = T["Parameters"]["ReplayEnabled"]
    assert set(p["AllowedValues"]) == {"true", "false"}
    assert T["Globals"]["Function"]["Environment"]["Variables"]["PUKAAR_REPLAY_ENABLED"] == {"Fn::Ref": "ReplayEnabled"}


# -- browser hardening (Amplify custom headers) -------------------------------------------------
def _amplify_headers() -> dict[str, str]:
    raw = RES["AmplifyApp"]["Properties"]["CustomHeaders"]
    text = raw["Fn::Sub"] if isinstance(raw, dict) else raw
    text = text[0] if isinstance(text, list) else text  # !Sub [text, {variables}]
    rules = yaml.safe_load(text)["customHeaders"]
    everything = [r for r in rules if r["pattern"] == "**"]
    assert everything, "headers must apply to every path"
    return {h["key"]: h["value"] for h in everything[0]["headers"]}


def _csp() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for part in _amplify_headers()["Content-Security-Policy"].split(";"):
        words = part.split()
        if words:
            out[words[0]] = words[1:]
    return out


def test_amplify_sends_the_security_headers():
    h = _amplify_headers()
    hsts = h["Strict-Transport-Security"]
    assert int(hsts.split("max-age=")[1].split(";")[0]) >= 31536000
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] in {"strict-origin-when-cross-origin", "no-referrer", "same-origin"}
    perms = {p.split("=")[0].strip(): p.split("=")[1].strip() for p in h["Permissions-Policy"].split(",")}
    # The report page records voice notes and reads GPS on its own origin; nothing uses the camera API.
    assert perms["microphone"] == "(self)" and perms["geolocation"] == "(self)" and perms["camera"] == "()"


def test_csp_is_strict_where_it_matters():
    csp = _csp()
    assert csp["default-src"] == ["'self'"]
    assert csp["frame-ancestors"] == ["'none'"] and csp["object-src"] == ["'none'"]
    assert csp["base-uri"] == ["'self'"] and csp["form-action"] == ["'self'"]
    assert "'unsafe-inline'" not in csp["script-src"] and "'unsafe-eval'" not in csp["script-src"]
    # No <style> element but the app's own critical CSS, allowed by its hash (frontend/boot-plugin.ts); inline
    # style attributes only, for the after-action report the console opens from a blob: URL (a blob: page
    # inherits this policy).
    assert csp["style-src"][0] == "'self'" and all(s.startswith("'sha256-") for s in csp["style-src"][1:])
    assert "'unsafe-inline'" not in csp["style-src"] and csp["style-src-attr"] == ["'unsafe-inline'"]
    for directive, sources in csp.items():
        assert "*" not in sources and "https:" not in sources and "http:" not in sources, directive
    connect = " ".join(csp["connect-src"])
    for host in ("execute-api.${AWS::Region}.amazonaws.com", "https://cognito-idp.${AWS::Region}.amazonaws.com",
                 "wss://*.appsync-realtime-api.${AWS::Region}.amazonaws.com", "https://tile.openstreetmap.org"):
        assert host in connect, host
    assert "blob:" in csp["worker-src"] and "blob:" in csp["media-src"]  # MapLibre workers, recorded voice notes


def test_csp_allows_exactly_the_inline_blocks_of_the_built_index_html():
    import base64
    import hashlib
    import json
    import re

    # The theme guard is written in frontend/index.html; the boot painter and the critical CSS are added by the
    # build (frontend/boot-plugin.ts). frontend/csp-hashes.json is the build's list, committed by
    # scripts/csp-sync.mjs together with this template; deploy_web.sh refuses a build the template does not allow.
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    theme = {"'sha256-" + base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode() + "'" for s in inline}
    built = json.loads((ROOT / "frontend" / "csp-hashes.json").read_text(encoding="utf-8"))
    csp = _csp()
    allowed_scripts = {s for s in csp["script-src"] if s.startswith("'sha256-")}
    allowed_styles = {s for s in csp["style-src"] if s.startswith("'sha256-")}
    assert theme and theme <= set(built["script"]), "edit the theme snippet, then build and run scripts/csp-sync.mjs"
    assert allowed_scripts == set(built["script"]) and len(built["script"]) == 2  # the theme guard and the painter
    assert allowed_styles == set(built["style"]) and len(built["style"]) == 1  # the critical CSS


def test_report_route_has_its_own_throttle_and_the_api_reads_the_report_salt():
    api = RES["HttpApi"]["Properties"]
    assert api["RouteSettings"]["POST /reports"]["ThrottlingRateLimit"] <= api["DefaultRouteSettings"]["ThrottlingRateLimit"]
    ssm = [s for name, s in _statements() if name == "ApiFunction" and "ssm:GetParameter" in _as_list(s.get("Action"))]
    assert ssm, "the API reads /pukaar/report_ip_salt from SSM"
    assert "report_ip_salt" in (ROOT / "scripts" / "put_secrets.sh").read_text(encoding="utf-8")


def test_report_surge_alarm_watches_the_metric_the_report_guard_emits():
    expr = _alarms()["ReportSurgeAlarm"]["Metrics"][0]["Expression"]
    assert "ReportSurge" in expr
    guard = (SRC / "services" / "report_guard.py").read_text(encoding="utf-8")
    assert guard.count('metric("ReportSurge"') == 2  # one source, one village


# -- the alarms added for a shadow pilot ---------------------------------------------------------
def test_unanswered_gauge_and_canary_alarms_watch_the_metrics_the_code_emits():
    alarms = _alarms()
    for name, metric_name, source in (
        ("AlertUnansweredAlarm", "AlertUnanswered", SRC / "workflow" / "steps.py"),
        ("GaugeUnhealthyAlarm", "GaugeUnhealthy", SRC / "services" / "gauge.py"),
        ("CanaryFailedAlarm", "CanaryFailed", SRC / "handlers" / "canary.py"),
    ):
        props = alarms[name]
        assert metric_name in props["Metrics"][0]["Expression"], name
        assert f'"{metric_name}"' in source.read_text(encoding="utf-8"), name
    unanswered = alarms["AlertUnansweredAlarm"]
    assert unanswered["Metrics"][0]["Period"] == 60 and unanswered["Threshold"] == 1
    assert unanswered["TreatMissingData"] == "notBreaching"
    assert alarms["CanaryFailedAlarm"]["TreatMissingData"] == "breaching"  # a canary that stopped is a failure


def test_reading_retention_is_a_parameter_30_on_dev_and_400_on_prod():
    import tomllib

    p = T["Parameters"]["ReadingRetentionDays"]
    assert p["Default"] == 30 and p["MinValue"] >= 1
    env = T["Globals"]["Function"]["Environment"]["Variables"]
    assert env["PUKAAR_READING_RETENTION_DAYS"] == {"Fn::Ref": "ReadingRetentionDays"}
    cfg = tomllib.loads((ROOT / "samconfig.toml").read_text(encoding="utf-8"))

    def overrides(env_name):
        raw = cfg[env_name]["deploy"]["parameters"]["parameter_overrides"]
        return dict(t.split("=", 1) for t in raw.split())

    assert overrides("default")["ReadingRetentionDays"] == "30"
    assert int(overrides("prod")["ReadingRetentionDays"]) >= 365


# -- the alarm layer: sirens, pradhan boxes, relays (docs/hardware/ALARM.md) --------------------------
ARN_IOT = "arn:${AWS::Partition}:iot:${AWS::Region}:${AWS::AccountId}:"


def _iot_policy(name: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for s in RES[name]["Properties"]["PolicyDocument"]["Statement"]:
        assert s["Effect"] == "Allow"
        (action,) = _as_list(s["Action"])
        assert "*" not in action, action
        out[action] = [r["Fn::Sub"].removeprefix(ARN_IOT) for r in _as_list(s["Resource"])]
    return out


def test_device_iot_policies_are_scoped_to_their_own_thing():
    """A stolen siren, box or relay certificate reaches its own topics, shadows and jobs, and nothing else:
    no iot:*, no other thing's name, no gauge topic."""
    for name, kind in (("PukaarSirenPolicy", "siren"), ("PukaarBoxPolicy", "box"), ("PukaarRelayPolicy", "relay")):
        pol = _iot_policy(name)
        assert set(pol) == {"iot:Connect", "iot:Publish", "iot:Subscribe", "iot:Receive"}, name
        assert pol["iot:Connect"] == [f"client/{THING}"]
        cond = [s.get("Condition") for s in RES[name]["Properties"]["PolicyDocument"]["Statement"]
                if s["Action"] == "iot:Connect"]
        assert cond == [{"Bool": {"iot:Connection.Thing.IsAttached": "true"}}]
        for action, resources in pol.items():
            for r in resources:
                assert THING in r, (name, action, r)  # every resource names the connecting thing itself
                assert "pukaar/gauge/" not in r, (name, r)
                assert r.split(THING)[0] in {"client/", f"topic/pukaar/{kind}/*/", "topic/pukaar/mesh/*/",
                                             "topic/$aws/things/", "topicfilter/$aws/things/"}, (name, r)
        assert RES[name]["Properties"]["PolicyName"] == {"Fn::Sub": f"pukaar-{kind}-${{Stage}}"}
    siren = _iot_policy("PukaarSirenPolicy")
    assert f"topic/pukaar/siren/*/{THING}/event" in siren["iot:Publish"]
    assert f"topic/$aws/things/{THING}/shadow/name/siren/update" in siren["iot:Publish"]
    assert f"topicfilter/$aws/things/{THING}/shadow/name/siren/*" in siren["iot:Subscribe"]
    relay = _iot_policy("PukaarRelayPolicy")
    assert not any("/shadow/name/siren/" in r for r in relay["iot:Publish"])  # a relay never sees a command shadow


def test_device_rules_filter_their_topics_and_feed_the_one_ingest_function():
    device = RES["PukaarDeviceRule"]["Properties"]["TopicRulePayload"]
    sql = device["Sql"]
    assert "FROM 'pukaar/+/+/+/+'" in sql and "topic(2) AS device_kind" in sql
    for part in ("topic(2) = 'siren'", "topic(2) = 'box'", "topic(2) = 'mesh'", "topic(5) = 'event'",
                 "topic(5) = 'heartbeat'", "topic(5) = 'backfill'", "topic(5) = 'relay'"):
        assert part in sql, part
    assert "'gauge'" not in sql  # gauges keep their own rule
    presence = RES["PukaarDevicePresenceRule"]["Properties"]["TopicRulePayload"]["Sql"]
    assert "'$aws/events/presence/+/+'" in presence
    assert all(f"startswith(clientId, '{p}-')" in presence for p in ("siren", "box", "relay"))
    shadow = RES["PukaarSirenShadowRule"]["Properties"]["TopicRulePayload"]["Sql"]
    assert "'$aws/things/+/shadow/name/siren/update/documents'" in shadow and "startswith(topic(3), 'siren-')" in shadow
    for name in ("PukaarDeviceRule", "PukaarDevicePresenceRule", "PukaarSirenShadowRule"):
        payload = RES[name]["Properties"]["TopicRulePayload"]
        assert payload["Actions"] == [{"Lambda": {"FunctionArn": {"Fn::GetAtt": "GaugeIngestFunction.Arn"}}}], name
        assert payload["ErrorAction"]["Sqs"]["QueueUrl"] == {"Fn::Ref": "WorkerDLQ"}, name
    from Pukaar.handlers import device_ingest

    assert device_ingest.is_device_message({"device_kind": "siren"})
    assert device_ingest.is_device_message({"eventType": "connected", "clientId": "siren-x"})


def test_only_three_roles_can_read_the_device_root_and_no_kms_key_on_any_stage():
    """The per-device keys derive from /pukaar/device_root (services/devices/keys.py). The API, the workflow and
    the device ingest may read it; the worker is denied it outright; nothing else has a grant that covers it.
    And no KMS key: it would bill $1 a month on dev."""
    assert not [n for n, r in RES.items() if r["Type"].startswith("AWS::KMS::")]
    root = "parameter/pukaar/device_root"
    allowed, denied = set(), set()
    for name, s in _statements():
        actions = _as_list(s.get("Action"))
        if not any(a.startswith("ssm:GetParameter") for a in actions):
            continue
        resources = [r["Fn::Sub"] if isinstance(r, dict) else r for r in _as_list(s["Resource"])]
        covers = any(r.endswith(root) or r.endswith("parameter/pukaar/*") for r in resources)
        if covers and s["Effect"] == "Allow":
            allowed.add(name)
        if covers and s["Effect"] == "Deny":
            denied.add(name)
    assert allowed - denied == {"ApiFunction", "WorkflowFunction", "GaugeIngestFunction"}
    assert denied == {"WorkerFunction"}


def test_only_the_signers_may_write_siren_and_box_shadows():
    grants = [(n, s) for n, s in _statements() if "iot:UpdateThingShadow" in _as_list(s.get("Action"))]
    assert {n for n, _ in grants} == {"ApiFunction", "WorkflowFunction", "GaugeIngestFunction"}
    for _, s in grants:
        assert _as_list(s["Action"]) == ["iot:UpdateThingShadow"]
        resources = [r["Fn::Sub"] for r in _as_list(s["Resource"])]
        assert sorted(r.rsplit(":", 1)[1] for r in resources) == ["thing/box-*", "thing/siren-*"]


def test_siren_alarms_watch_the_metrics_the_code_emits():
    alarms = _alarms()
    for name, metric_name, source in (
        ("SirenOfflineAlarm", "SirenOffline", SRC / "services" / "sirens.py"),
        ("SirenTestFailedAlarm", "SirenTestFailed", SRC / "services" / "sirens.py"),
        ("SirenUnconfirmedAlarm", "SirenUnconfirmed", SRC / "services" / "sirens.py"),
    ):
        props = alarms[name]
        assert metric_name in props["Metrics"][0]["Expression"], name
        assert f'"{metric_name}"' in source.read_text(encoding="utf-8"), name
    offline = alarms["SirenOfflineAlarm"]
    assert offline["EvaluationPeriods"] == offline["DatapointsToAlarm"] == 2 and offline["Metrics"][0]["Period"] == 900
    assert offline["OKActions"] == [{"Fn::Ref": "AlarmTopic"}]
    failed = alarms["SirenTestFailedAlarm"]
    assert failed["Metrics"][0]["Period"] == 3600 and failed["TreatMissingData"] == "notBreaching"
    assert alarms["SirenUnconfirmedAlarm"]["Metrics"][0]["Period"] == 60


def _route_keys() -> set[str]:
    out = set()
    for res in RES.values():
        for ev in (res.get("Properties", {}).get("Events") or {}).values():
            if ev.get("Type") == "HttpApi":
                p = ev["Properties"]
                out.add(f"{p['Method']} {p['Path']}")
    return out


def test_each_public_flow_has_its_own_throttle_so_none_starves_another():
    api = RES["HttpApi"]["Properties"]
    routes, default = api["RouteSettings"], api["DefaultRouteSettings"]
    assert set(routes) <= _route_keys(), set(routes) - _route_keys()  # every setting names a real route
    own = ["POST /telegram/webhook", "POST /alerts/{id}/ack", "GET /voice/exotel/gather", "POST /voice/exotel/status",
           "POST /voice/plivo/digits", "GET /public/villages/{id}/now", "GET /villages/{id}", "GET /public/overview",
           "POST /sensors/{id}/readings"]
    for key in own:
        assert key in routes, key
        assert routes[key]["ThrottlingBurstLimit"] >= routes[key]["ThrottlingRateLimit"] > 0, key
    # The ack and webhook paths, and the villagers' page, each above the console's default.
    for key in ("POST /telegram/webhook", "POST /alerts/{id}/ack", "GET /public/villages/{id}/now", "GET /villages/{id}"):
        assert routes[key]["ThrottlingRateLimit"] > default["ThrottlingRateLimit"], key
    assert routes["POST /sensors/{id}/readings"]["ThrottlingRateLimit"] >= 10  # 600 HTTPS gauges at 1/min
    # The report-abuse guard stays: reports below the default, each source and village limited in DynamoDB.
    assert routes["POST /reports"]["ThrottlingRateLimit"] <= 10
    # All buckets together stay well under the regional account quota (10,000 a second).
    assert sum(r["ThrottlingRateLimit"] for r in routes.values()) + default["ThrottlingRateLimit"] < 2000


def test_alert_status_index_and_staff_groups():
    from Pukaar.store.repo import table_schema

    p = next(r for r in RES.values() if r["Type"] == "AWS::DynamoDB::Table")["Properties"]
    names = [g["IndexName"] for g in p["GlobalSecondaryIndexes"]]
    assert names == ["gsi1", "gsi2"]
    local = table_schema("x")
    assert [g["IndexName"] for g in local["GlobalSecondaryIndexes"]] == names  # the local table mirrors it
    assert {a["AttributeName"] for a in p["AttributeDefinitions"]} == \
        {a["AttributeName"] for a in local["AttributeDefinitions"]}
    groups = {r["Properties"]["GroupName"] for r in RES.values() if r["Type"] == "AWS::Cognito::UserPoolGroup"}
    assert groups == {"officer", "pradhan", "state_operator", "ddma_head"}
