"""Operations hardening for a shadow pilot: reading retention, the scheduled canary, the restore drill and
the CloudFront + AWS WAF edge on prod (scorecard cycle 4, code items 2, 4 to 6 and 8)."""

from __future__ import annotations

import importlib.util
import json
from datetime import timedelta
from pathlib import Path

import pytest

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.handlers import canary
from Pukaar.store.models import Reading, SensorReading

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def env(monkeypatch):
    def apply(**kw):
        for k, v in kw.items():
            monkeypatch.setenv(k, str(v))
        get_settings.cache_clear()

    yield apply
    monkeypatch.undo()
    get_settings.cache_clear()


# -- reading retention ------------------------------------------------------------------------------
def _ttl_days(item, frozen) -> float:
    return (int(item["ttl"]) - frozen["now"].timestamp()) / 86400


def test_a_prod_configured_reading_is_kept_at_least_a_year(repo, frozen, env):
    v = repo.get_village("thunag")
    repo.put_reading(Reading(village_id=v.id, at=clock.iso(frozen["now"]), rain_24h_mm=1.0))
    dev = repo._get(f"VILLAGE#{v.id}", f"READING#{clock.iso(frozen['now'])}")
    assert round(_ttl_days(dev, frozen)) == 30  # the default, as on dev

    env(PUKAAR_READING_RETENTION_DAYS=400)  # samconfig.toml [prod]
    later = frozen["now"] + timedelta(minutes=15)
    frozen["now"] = later
    repo.put_reading(Reading(village_id=v.id, at=clock.iso(later), rain_24h_mm=1.0))
    prod = repo._get(f"VILLAGE#{v.id}", f"READING#{clock.iso(later)}")
    assert _ttl_days(prod, frozen) >= 365
    # River-gauge readings follow the same setting.
    g = SensorReading(village_id=v.id, device_id="dev-1", at=clock.iso(later), water_level_cm=100.0)
    assert repo.put_sensor_reading(g)
    item = repo._get(f"VILLAGE#{v.id}", f"SENSOR#{clock.iso(later)}#dev-1")
    assert _ttl_days(item, frozen) >= 365


# -- the canary -----------------------------------------------------------------------------------------
API, WEB = "https://api.example", "https://web.example"
GOOD_OVERVIEW = {"villages": [{"id": "thunag", "level": "watch", "data_status": "ok"}],
                 "counters": {"forecast_checks_24h": 480}}


def site(**override):
    pages = {
        f"{API}/health": canary.Response(200, b'{"status": "ok", "mode": "aws"}', "application/json"),
        f"{API}/public/overview": canary.Response(200, json.dumps(GOOD_OVERVIEW).encode(), "application/json"),
        f"{API}/cap/alerts.atom": canary.Response(
            200, b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>', "application/atom+xml"),
        f"{WEB}/": canary.Response(200, b'<html><div id="root"></div><script src="/a.js"></script></html>', "text/html"),
    }
    pages.update(override)
    hits: list[str] = []

    def get(url):
        hits.append(url)
        r = pages[url]
        if isinstance(r, Exception):
            raise r
        return r

    return get, hits


class FakeCloudWatch:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kw):
        self.calls.append(kw)


def test_a_healthy_site_passes_and_sends_canary_failed_0(monkeypatch):
    monkeypatch.setenv("PUKAAR_CANARY_API_URL", API)
    monkeypatch.setenv("PUKAAR_WEB_URL", WEB)
    get, hits = site()
    cw = FakeCloudWatch()
    out = canary.handler({}, None, get=get, cloudwatch=cw, sleep=lambda s: None)
    assert out["ok"] and set(out["results"].values()) == {"ok"}
    assert hits == [f"{API}/health", f"{API}/public/overview", f"{API}/cap/alerts.atom", f"{WEB}/"]
    (call,) = cw.calls
    assert call["Namespace"] == "Pukaar"  # the only namespace its role may write
    assert call["MetricData"] == [{"MetricName": "CanaryFailed", "Value": 0.0, "Unit": "Count"}]


@pytest.mark.parametrize("url,response,check", [
    (f"{API}/health", canary.Response(503, b"", ""), "health"),
    (f"{API}/health", canary.Response(200, b'{"status": "degraded"}', ""), "health"),
    (f"{API}/public/overview", canary.Response(200, b'{"villages": []}', ""), "overview"),
    (f"{API}/public/overview", canary.Response(200, json.dumps({**GOOD_OVERVIEW, "counters": {
        "forecast_checks_24h": 0}}).encode(), ""), "overview"),
    (f"{API}/public/overview", canary.Response(200, b"<html>", ""), "overview"),
    (f"{API}/cap/alerts.atom", canary.Response(200, b"<rss></rss>", ""), "cap"),
    (f"{WEB}/", canary.Response(404, b"", ""), "web"),
    (f"{WEB}/", TimeoutError("timed out"), "web"),
])
def test_each_broken_check_is_reported_with_its_dimension(monkeypatch, url, response, check):
    monkeypatch.setenv("PUKAAR_CANARY_API_URL", API)
    monkeypatch.setenv("PUKAAR_WEB_URL", WEB)
    get, hits = site(**{url: response})
    cw = FakeCloudWatch()
    pauses = []
    out = canary.handler({}, None, get=get, cloudwatch=cw, sleep=pauses.append)
    assert not out["ok"] and out["results"][check] != "ok"
    assert hits.count(url) == 2 and pauses == [canary.RETRY_SECONDS]  # tried twice before it counts
    data = cw.calls[0]["MetricData"]
    assert data[0] == {"MetricName": "CanaryFailed", "Value": 1.0, "Unit": "Count"}
    assert data[1]["Dimensions"] == [{"Name": "Check", "Value": check}]


def test_a_check_that_recovers_on_the_retry_passes(monkeypatch):
    monkeypatch.setenv("PUKAAR_CANARY_API_URL", API)
    monkeypatch.setenv("PUKAAR_WEB_URL", WEB)
    get, _ = site()
    first = {"done": False}

    def flaky(url):
        if url.endswith("/health") and not first["done"]:
            first["done"] = True
            raise ConnectionResetError("reset")
        return get(url)

    out = canary.handler({}, None, get=flaky, cloudwatch=FakeCloudWatch(), sleep=lambda s: None)
    assert out["ok"]


def test_without_its_urls_the_canary_fails_loudly(monkeypatch):
    monkeypatch.delenv("PUKAAR_CANARY_API_URL", raising=False)
    cw = FakeCloudWatch()
    out = canary.handler({}, None, get=lambda u: None, cloudwatch=cw, sleep=lambda s: None)
    assert not out["ok"] and cw.calls[0]["MetricData"][0]["Value"] == 1.0


def test_the_canary_imports_nothing_from_the_app():
    text = (ROOT / "backend" / "src" / "Pukaar" / "handlers" / "canary.py").read_text(encoding="utf-8")
    assert "from Pukaar" not in text and "import Pukaar" not in text


# -- the restore drill ------------------------------------------------------------------------------
def _drill_module():
    spec = importlib.util.spec_from_file_location("restore_drill", ROOT / "scripts" / "restore_drill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeDynamo:
    """Enough of DynamoDB for the drill: a live table, a restore that makes a copy, scans and deletes."""

    def __init__(self, items, restored=None, pitr="ENABLED"):
        self.tables = {"pukaar-dev": items}
        self.restored, self.pitr = restored, pitr
        self.calls: list[tuple[str, dict]] = []

    def describe_continuous_backups(self, TableName):
        return {"ContinuousBackupsDescription": {"PointInTimeRecoveryDescription": {
            "PointInTimeRecoveryStatus": self.pitr, "EarliestRestorableDateTime": "2026-10-01",
            "LatestRestorableDateTime": "2026-10-22"}}}

    def restore_table_to_point_in_time(self, **kw):
        self.calls.append(("restore", kw))
        self.tables[kw["TargetTableName"]] = list(self.tables[kw["SourceTableName"]] if self.restored is None
                                                  else self.restored)

    def describe_table(self, TableName):
        return {"Table": {"TableStatus": "ACTIVE"}}

    def scan(self, TableName, **kw):
        self.calls.append(("scan", {"TableName": TableName, **kw}))
        return {"Items": [{"pk": {"S": pk}} for pk in self.tables[TableName]]}

    def delete_table(self, TableName):
        self.calls.append(("delete", {"TableName": TableName}))
        del self.tables[TableName]


LIVE = ["VILLAGE#thunag"] * 40 + ["ALERT#a1"] * 10 + ["REPORT#r1"] * 5


def test_restore_drill_restores_to_a_scratch_table_compares_and_deletes_it(capsys):
    drill = _drill_module()
    db = FakeDynamo(LIVE)
    assert drill.drill(db, "dev", None, poll_s=0) is True
    (restore,) = [kw for c, kw in db.calls if c == "restore"]
    target = restore["TargetTableName"]
    assert target.startswith("pukaar-dev-restore-drill-") and restore["SourceTableName"] == "pukaar-dev"
    assert restore["UseLatestRestorableTime"] is True and restore["BillingModeOverride"] == "PAY_PER_REQUEST"
    assert [kw["TableName"] for c, kw in db.calls if c == "delete"] == [target]
    assert set(db.tables) == {"pukaar-dev"}  # the live table is untouched; the copy is gone
    assert all(kw.get("ProjectionExpression") == "pk" for c, kw in db.calls if c == "scan")
    out = capsys.readouterr().out
    assert "VILLAGE#" in out and "PASS" in out


def test_restore_drill_fails_on_a_missing_prefix_and_still_deletes_the_copy():
    drill = _drill_module()
    db = FakeDynamo(LIVE, restored=["VILLAGE#thunag"] * 40)
    assert drill.drill(db, "dev", None, poll_s=0) is False
    assert set(db.tables) == {"pukaar-dev"}


def test_restore_drill_refuses_without_pitr_and_never_names_anything_but_a_scratch_table():
    drill = _drill_module()
    db = FakeDynamo(LIVE, pitr="DISABLED")
    assert drill.drill(db, "dev", None, poll_s=0) is False and db.calls == []
    assert drill.is_scratch(drill.scratch_name("dev"), "dev") and not drill.is_scratch("pukaar-dev", "dev")
    ok, _ = drill.compare({"ALERT#": 100}, {"ALERT#": 95}, 0.1)
    assert ok
    ok, _ = drill.compare({"ALERT#": 100}, {"ALERT#": 50}, 0.1)
    assert not ok


# -- prod behind CloudFront and AWS WAF ----------------------------------------------------------------
def test_without_the_edge_every_request_is_served(env):
    from Pukaar.api import edge

    env(PUKAAR_EDGE_REQUIRED="false")
    assert edge.allowed("/public/overview", {})


def test_with_the_edge_a_request_that_bypassed_cloudfront_is_refused(env):
    from fastapi.testclient import TestClient

    from Pukaar.main import app
    from Pukaar.services import report_guard

    env(PUKAAR_EDGE_REQUIRED="true", PUKAAR_EDGE_ORIGIN_SECRET="edge-secret-value")
    client = TestClient(app)
    r = client.get("/villages")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "edge_only"
    assert client.get("/villages", headers={"X-Pukaar-Edge": "wrong"}).status_code == 403
    assert client.get("/villages", headers={"X-Pukaar-Edge": "edge-secret-value"}).status_code == 200
    assert client.get("/health").status_code == 200  # the Lambda Web Adapter's readiness check
    # The caller's IP is CloudFront's viewer address, not the edge address API Gateway saw.
    headers = {"cloudfront-viewer-address": "203.0.113.7:51234", "x-forwarded-for": "198.51.100.1, 64.252.1.1",
               "x-amzn-request-context": json.dumps({"http": {"sourceIp": "64.252.1.1"}})}
    assert report_guard.client_ip(headers, None) == "203.0.113.7"
    assert report_guard.client_ip({"cloudfront-viewer-address": "2001:db8::7:443"}, None) == "2001:db8::7"
    assert report_guard.client_ip({"x-forwarded-for": "198.51.100.1, 64.252.1.1"}, None) == "198.51.100.1"


def test_with_the_edge_but_no_secret_it_fails_closed(env):
    from Pukaar.api import edge

    env(PUKAAR_EDGE_REQUIRED="true")
    assert not edge.allowed("/villages", {"x-pukaar-edge": ""})
