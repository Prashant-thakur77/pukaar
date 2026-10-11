"""Live push over AppSync Events (services/events.py): what is published, to which channel,
how it is signed, and that a failure never reaches the caller."""

from __future__ import annotations

import json

import pytest
from Pukaar.services import events
from Pukaar.services import rollcall as rcs
from Pukaar.workflow.client import decide
from test_sweep import make_reading
from test_workflow_steps import drafted_and_asked

DOMAIN = "abc123.appsync-api.us-east-1.amazonaws.com"

# Every key any event may carry. A new key fails this list until someone decides it is safe.
ALLOWED_KEYS = {
    "type", "kind", "village_id", "alert_id", "rollcall_id", "level", "previous", "status", "replay", "at",
    "recipients_count", "delivered_count", "acknowledged_count", "exercise", "asked", "safe", "need_help",
    "not_answered",
}


class Resp:
    def __init__(self, status: int = 200, body: dict | None = None) -> None:
        self.status_code = status
        self._body = body if body is not None else {"successful": [{"identifier": "x", "index": 0}], "failed": []}
        self.text = json.dumps(self._body)

    def json(self) -> dict:
        return self._body


class FakeHttp:
    def __init__(self, resp: Resp | None = None, exc: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.resp, self.exc = resp or Resp(), exc

    def post(self, url, *, content, headers, timeout):
        self.calls.append({"url": url, "body": json.loads(content), "headers": headers, "timeout": timeout})
        if self.exc:
            raise self.exc
        return self.resp

    def published(self) -> list[tuple[str, dict]]:
        out = []
        for c in self.calls:
            assert len(c["body"]["events"]) == 1
            out.append((c["body"]["channel"], json.loads(c["body"]["events"][0])))
        return out


@pytest.fixture()
def live(monkeypatch):
    from Pukaar.core.config import get_settings

    monkeypatch.setenv("PUKAAR_EVENTS_HTTP_DOMAIN", DOMAIN)
    get_settings.cache_clear()
    fake = FakeHttp()
    events.set_client(fake)
    yield fake
    events.set_client(None)
    monkeypatch.delenv("PUKAAR_EVENTS_HTTP_DOMAIN")
    get_settings.cache_clear()


def test_off_without_a_domain_sends_nothing():
    fake = FakeHttp()
    events.set_client(fake)
    try:
        assert events.configured() is False
        assert events.publish(events.PUBLIC_LEVELS, {"type": "level"}) is False
        events.level_changed("thunag", "watch", "normal")
        assert fake.calls == []
    finally:
        events.set_client(None)


def test_publish_is_a_sigv4_signed_post_with_one_stringified_event(live):
    assert events.publish(events.PUBLIC_LEVELS, {"type": "level", "village_id": "thunag", "level": "watch"}) is True
    call = live.calls[0]
    assert call["url"] == f"https://{DOMAIN}/event"
    assert call["body"]["channel"] == "/public/levels"
    assert isinstance(call["body"]["events"][0], str)  # AppSync wants each event as a JSON string
    assert json.loads(call["body"]["events"][0]) == {"type": "level", "village_id": "thunag", "level": "watch"}
    h = {k.lower(): v for k, v in call["headers"].items()}
    assert h["authorization"].startswith("AWS4-HMAC-SHA256 Credential=")
    assert "/us-east-1/appsync/aws4_request" in h["authorization"]
    assert "x-amz-date" in h and "x-api-key" not in h  # the server never uses the public key
    assert call["timeout"] <= 2.0


@pytest.mark.parametrize("fake", [
    FakeHttp(exc=RuntimeError("connection reset")),
    FakeHttp(resp=Resp(401, {"errors": [{"errorType": "UnauthorizedException"}]})),
    FakeHttp(resp=Resp(200, {"successful": [], "failed": [{"index": 0, "code": 400}]})),
])
def test_failures_are_swallowed_logged_and_counted(live, fake, capsys):
    events.set_client(fake)
    assert events.publish(events.OFFICER_ALERTS, {"type": "approval"}) is False
    out = capsys.readouterr().out
    assert "EventPublishFailed" in out and '"Namespace": "officer"' in out
    # The helpers the workflow calls return normally too.
    events.level_changed("thunag", "warning", "watch")


def test_signing_failure_is_swallowed(live, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(events, "_signed_headers", boom)
    assert events.publish(events.PUBLIC_ALERTS, {"type": "alert"}) is False
    assert "EventPublishFailed" in capsys.readouterr().out


def test_level_rise_publishes_the_level_and_the_new_alert(repo, frozen, workflow, live):
    from Pukaar.services import decision_engine as de

    v = repo.get_village("thunag")
    res = de.recompute_village(repo, v, now=frozen["now"], reading=make_reading(v, frozen["now"], v.thresholds.warning),
                               workflow=workflow)
    pub = live.published()
    levels = [e for ch, e in pub if ch == "/public/levels"]
    assert levels == [{"type": "level", "village_id": "thunag", "level": res.level, "previous": "normal",
                       "replay": False, "at": levels[0]["at"]}]
    alerts = [e for ch, e in pub if ch == "/public/alerts"]
    assert alerts and alerts[0]["alert_id"] == res.alert_id and alerts[0]["status"] == "drafting"

    live.calls.clear()  # same level again: nothing new to push
    de.recompute_village(repo, repo.get_village("thunag"), now=frozen["now"],
                         reading=make_reading(v, frozen["now"], v.thresholds.warning), workflow=workflow)
    assert [ch for ch, _ in live.published() if ch == "/public/levels"] == []


def test_whole_alert_life_pushes_ids_levels_statuses_and_counts_only(repo, frozen, workflow, live):
    s, a, _ = drafted_and_asked(repo, "warning")
    decide(repo, workflow, a.id, "approved", "officer1")
    s.handle({"step": "deliver", "alert_id": a.id})
    from Pukaar.delivery import dispatch

    first = repo.list_deliveries(a.id)[0]
    dispatch.acknowledge(repo, a.id, first.recipient_id)
    out = s.handle({"step": "close", "alert_id": a.id, "outcome": "delivered"})
    asked = repo.list_rollcall_asked(out["rollcall_id"])
    rcs.simulate_stub_answer(repo, out["rollcall_id"], asked[0].recipient_id, "need_help")

    pub = live.published()
    statuses = [e["status"] for ch, e in pub if ch == "/public/alerts"]
    assert statuses == ["pending", "approved", "delivering", "delivered", "delivered"]
    officer = [(e["type"], e["kind"]) for ch, e in pub if ch == "/officer/alerts"]
    assert ("approval", "approval_pending") in officer and ("approval", "approved") in officer
    assert ("rollcall", "need_help") in officer
    counts = [e for ch, e in pub if ch == "/public/deliveries"]
    assert counts[-1]["delivered_count"] == 2 and counts[-1]["acknowledged_count"] == 1
    rollcall = [e for ch, e in pub if ch == "/public/rollcall"]
    assert rollcall[-1]["need_help"] == 1 and rollcall[-1]["asked"] == 2

    # No personal data and no alert text, anywhere.
    alert = repo.get_alert(a.id)
    village = repo.get_village("thunag")
    secret_words = {alert.text_hi, alert.text_en, "officer1", village.name, village.name_hi}
    secret_words |= {r.name for r in repo.list_recipients("thunag")} | {r.id for r in repo.list_recipients("thunag")}
    for channel, event in pub:
        assert channel.split("/")[1] in {"public", "officer"}
        assert set(event) <= ALLOWED_KEYS, (channel, set(event) - ALLOWED_KEYS)
        for value in event.values():
            assert not isinstance(value, (dict, list)), (channel, event)
            assert str(value) not in secret_words, (channel, event)


def test_declined_reaches_the_officer_channel(repo, frozen, workflow, live):
    _, a, _ = drafted_and_asked(repo, "watch")
    live.calls.clear()
    decide(repo, workflow, a.id, "declined", "officer1")
    assert ("/officer/alerts", "declined") in [(ch, e.get("kind")) for ch, e in live.published()]


def test_replay_reset_pushes_levels_back_to_normal(repo, frozen, workflow, live):
    from Pukaar.services import replay

    repo.update_village("gohar", level="warning")
    live.calls.clear()
    replay.reset(repo)
    levels = [e for ch, e in live.published() if ch == "/public/levels"]
    assert [(e["village_id"], e["level"], e["previous"]) for e in levels] == [("gohar", "normal", "warning")]
