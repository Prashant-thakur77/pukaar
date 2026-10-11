"""River gauge over MQTT (AWS IoT Core): the topic-rule Lambda and the shared ingest path."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import NOW
from Pukaar.core import clock
from Pukaar.handlers import gauge_ingest
from Pukaar.store.models import GaugeConfig, SensorReading, Village

G = GaugeConfig(device_id="gauge-gohar-sim", watch_cm=120, warning_cm=200, critical_cm=280)


class FakeRepo:
    """Just the calls gauge.ingest makes, with the real one-per-minute, never-earlier rule."""

    def __init__(self) -> None:
        self.village = Village.model_construct(id="gohar", level="normal", gauge=G)
        self.readings: list[SensorReading] = []
        self.audit: list = []

    def get_village(self, village_id):
        return self.village if village_id == "gohar" else None

    def latest_sensor_reading(self, village_id, max_age_minutes=30, now=None):
        return self.readings[-1] if self.readings else None

    def put_sensor_reading(self, r):
        if self.readings and clock.parse(r.at) <= clock.parse(self.readings[-1].at) + timedelta(seconds=59):
            return False
        self.readings.append(r)
        return True

    def append_audit(self, row):
        self.audit.append(row)


def event(**kw):
    """What the rule hands the Lambda: the payload plus topic(3) and topic(4)."""
    base = {"at": clock.iso(NOW - timedelta(seconds=30)), "water_level_cm": 80.5, "battery_v": 3.97, "rssi": -67,
            "simulated": True, "village_id": "gohar", "device_id": "gauge-gohar-sim"}
    return {**base, **kw}


def test_valid_reading_is_stored_with_mqtt_transport():
    repo = FakeRepo()
    out = gauge_ingest.handle(event(rain_mm_1h=1.2), repo=repo, now=NOW)
    assert out["status"] == "accepted" and out["gauge_level"] == "normal" and out["simulated"] is True
    r = repo.readings[0]
    assert (r.village_id, r.device_id, r.transport, r.water_level_cm, r.rain_mm_1h) == (
        "gohar", "gauge-gohar-sim", "mqtt", 80.5, 1.2)
    assert r.received_at == clock.iso(NOW)


def test_rule_payload_extras_are_ignored_and_level_change_is_audited(monkeypatch):
    import Pukaar.services.decision_engine as de
    import Pukaar.services.replay as rp

    calls = []
    monkeypatch.setattr(rp, "is_running", lambda repo: False)
    monkeypatch.setattr(de, "recompute_village", lambda repo, v, **kw: calls.append((v.id, kw["only_if_rising"])))
    repo = FakeRepo()
    out = gauge_ingest.handle(event(water_level_cm=130, firmware="0.3.1"), repo=repo, now=NOW)
    assert out["status"] == "accepted" and out["gauge_level"] == "watch"
    assert repo.audit and "via mqtt" in repo.audit[0].reason and repo.audit[0].actor == "gauge-gohar-sim"
    assert calls == [("gohar", True)]  # at watch: re-evaluated at once, only ever to raise the level


def test_wrong_device_or_village_is_rejected():
    repo = FakeRepo()
    out = gauge_ingest.handle(event(device_id="gauge-pandoh-sim"), repo=repo, now=NOW)
    assert out == {"status": "rejected", "code": "wrong_device",
                   "reason": "This device is not the gauge for this village"}
    assert gauge_ingest.handle(event(village_id="nowhere"), repo=repo, now=NOW)["code"] == "not_found"
    assert not repo.readings


@pytest.mark.parametrize("bad", [
    {"water_level_cm": "80"},            # a string, not a number
    {"water_level_cm": True},
    {"water_level_cm": None},
    {"water_level_cm": 99999},           # outside the physical bounds
    {"battery_v": "low"},
    {"rssi": 5},
    {"rain_mm_1h": -1},
    {"at": "yesterday"},
    {"village_id": "../etc"},
    {"device_id": "a b"},
])
def test_bad_payload_is_rejected_without_raising(bad):
    repo = FakeRepo()
    out = gauge_ingest.handle(event(**bad), repo=repo, now=NOW)
    assert out["status"] == "rejected" and out["code"] == "bad_payload", out
    assert not repo.readings


def test_missing_fields_and_non_object_payloads_are_rejected():
    repo = FakeRepo()
    for ev in ({"village_id": "gohar", "device_id": "gauge-gohar-sim", "water_level_cm": 1.0},  # no "at"
               {"village_id": "gohar", "at": clock.iso(NOW), "water_level_cm": 1.0},          # no device
               ["not", "an", "object"], "raw text"):
        assert gauge_ingest.handle(ev, repo=repo, now=NOW)["code"] == "bad_payload"
    assert not repo.readings


def test_stale_or_future_timestamp_is_rejected():
    repo = FakeRepo()
    for seconds in (-(gauge_ingest.WINDOW_SECONDS + 5), gauge_ingest.WINDOW_SECONDS + 5):
        out = gauge_ingest.handle(event(at=clock.iso(NOW - timedelta(seconds=seconds))), repo=repo, now=NOW)
        assert out["status"] == "rejected" and out["code"] == "stale"
    # inside the ten-minute window, either side, is fine
    assert gauge_ingest.handle(event(at=clock.iso(NOW - timedelta(minutes=9))), repo=repo, now=NOW)["status"] == "accepted"
    assert gauge_ingest.handle(event(at=clock.iso(NOW + timedelta(minutes=9))), repo=repo, now=NOW)["status"] == "accepted"


def test_duplicate_or_too_frequent_reading_is_ignored():
    repo = FakeRepo()
    assert gauge_ingest.handle(event(), repo=repo, now=NOW)["status"] == "accepted"
    assert gauge_ingest.handle(event(), repo=repo, now=NOW)["status"] == "ignored"  # QoS 1 redelivery
    assert len(repo.readings) == 1


def test_storage_failure_raises_so_the_invocation_reaches_the_dlq():
    class Broken(FakeRepo):
        def put_sensor_reading(self, r):
            raise RuntimeError("ProvisionedThroughputExceeded")

    with pytest.raises(RuntimeError):
        gauge_ingest.handle(event(), repo=Broken(), now=NOW)


def test_rising_mqtt_reading_raises_the_village_through_the_real_repo(repo, frozen, workflow, monkeypatch):
    import Pukaar.workflow.client as wc

    monkeypatch.setattr(wc, "get_workflow", lambda: workflow)
    v = repo.get_village("gohar")
    out = gauge_ingest.handle(event(device_id=v.gauge.device_id, water_level_cm=v.gauge.warning_cm + 10,
                                    at=clock.iso(NOW)), repo=repo, now=NOW)
    assert out["status"] == "accepted" and out["gauge_level"] == "warning"
    assert out["village_level"] in {"warning", "critical"} and out["alert_id"]
    latest = repo.latest_sensor_reading("gohar", 30, now=NOW)
    assert latest.transport == "mqtt" and latest.simulated is True
    assert workflow.started == [out["alert_id"]]


def test_simulator_and_provisioner_agree_with_the_rule_and_policy():
    from Pukaar.scripts import gauge_sim_mqtt, iot_provision

    topic = gauge_sim_mqtt.topic_for("gohar", "gauge-gohar-sim")
    assert topic == "pukaar/gauge/gohar/gauge-gohar-sim/reading"
    parts = topic.split("/")
    assert (parts[2], parts[3]) == ("gohar", "gauge-gohar-sim")  # topic(3), topic(4) in the rule
    payload = gauge_sim_mqtt.payload(clock.parse("2026-10-11T09:30:00Z"), 150.0, 3.9)
    assert payload["simulated"] is True and "device_id" not in payload  # identity comes from the topic
    merged = {**payload, "village_id": parts[2], "device_id": parts[3]}
    assert gauge_ingest.MqttReading.model_validate(merged).water_level_cm == 150.0
    assert iot_provision.param_names("gauge-gohar-sim") == (
        "/pukaar/gauge/gauge-gohar-sim/key", "/pukaar/gauge/gauge-gohar-sim/cert")


def test_provisioning_is_idempotent_rolls_back_and_tears_down(capsys):
    import json

    import boto3
    from botocore.exceptions import ClientError
    from moto import mock_aws
    from Pukaar.scripts import iot_provision as ip

    with mock_aws():
        iot, ssm = boto3.client("iot", region_name="us-east-1"), boto3.client("ssm", region_name="us-east-1")
        iot.create_policy(policyName="pukaar-gauge-test", policyDocument=json.dumps(
            {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "iot:Connect", "Resource": "*"}]}))
        dev = "gauge-gohar-sim"

        # A failure after the certificate exists (unknown policy) leaves no active certificate behind.
        with pytest.raises(ClientError):
            ip.provision(iot, ssm, "gohar", dev, "no-such-policy")
        assert not [c for c in iot.list_certificates()["certificates"] if c["status"] == "ACTIVE"]

        assert ip.provision(iot, ssm, "gohar", dev, "pukaar-gauge-test") == "created"
        (cert_arn,) = iot.list_thing_principals(thingName=dev)["principals"]
        assert [p["policyName"] for p in iot.list_attached_policies(target=cert_arn)["policies"]] == ["pukaar-gauge-test"]
        key_name, cert_name = ip.param_names(dev)
        params = {p["Name"]: p for p in
                  ssm.get_parameters(Names=[key_name, cert_name], WithDecryption=True)["Parameters"]}
        assert params[key_name]["Type"] == params[cert_name]["Type"] == "SecureString"
        assert "PRIVATE KEY" in params[key_name]["Value"] and "BEGIN CERTIFICATE" in params[cert_name]["Value"]
        out = capsys.readouterr().out
        assert "PRIVATE KEY" not in out and params[key_name]["Value"][40:80] not in out  # never printed

        assert ip.provision(iot, ssm, "gohar", dev, "pukaar-gauge-test") == "exists"  # idempotent
        assert len(iot.list_thing_principals(thingName=dev)["principals"]) == 1

        ip.teardown(iot, ssm, dev)
        assert not iot.list_things()["things"]
        assert not ssm.get_parameters(Names=[key_name, cert_name])["Parameters"]
        ip.teardown(iot, ssm, dev)  # a second teardown is a no-op
