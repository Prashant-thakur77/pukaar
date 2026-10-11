"""After-action report: content and privacy, storage on close, SES call shape, Cedar access, template IAM."""

from __future__ import annotations

import json
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from Pukaar.core.config import get_settings
from Pukaar.delivery import dispatch
from Pukaar.policy.guard import SYSTEM, Principal, evaluate
from Pukaar.services import after_action as aa
from Pukaar.services import storage
from Pukaar.store.models import Recipient
from Pukaar.workflow.client import decide
from test_workflow_steps import drafted_and_asked

CHAT_ID = "987654321"
PHONE = "+91 98765 43210"
OFFICER = Principal("officer1", "officer")
PRADHAN = Principal("pradhan_thunag", "pradhan", ["thunag"])


def run_alert(repo, workflow, frozen, *, level="warning", drill=False, replay=False, ack=True, close=True):
    """A warning that is drafted, approved after 2 min, delivered, acknowledged after 3 min and closed."""
    repo.put_recipient(Recipient(id=CHAT_ID, village_id="thunag", name="Ramesh Kumar", channel="telegram"))
    s, a, _ = drafted_and_asked(repo, level, replay)
    if drill:
        repo.update_alert(a.id, decision_trace={**repo.get_alert(a.id).decision_trace, "drill": True})
    frozen["now"] += timedelta(minutes=2)
    decide(repo, workflow, a.id, "approved", "officer1")
    frozen["now"] += timedelta(seconds=30)
    s.handle({"step": "deliver", "alert_id": a.id})
    if ack:
        frozen["now"] += timedelta(minutes=3, seconds=5)
        dispatch.acknowledge(repo, a.id, CHAT_ID)
    out = s.handle({"step": "close", "alert_id": a.id, "outcome": "delivered"}) if close else None
    return s, repo.get_alert(a.id), out


# -- content ---------------------------------------------------------------------
def test_report_has_times_durations_hindi_english_and_no_phone_or_chat_id(repo, frozen, workflow):
    _, a, _ = run_alert(repo, workflow, frozen)
    # A delivery error that quotes a chat id and a phone must not leak either.
    repo.update_delivery(a.id, "stub-thunag-1", error=f"telegram 400 chat {CHAT_ID} phone {PHONE}")
    r = aa.build(repo, a)
    for body in (r.html, r.text, json.dumps(r.summary, ensure_ascii=False)):
        assert CHAT_ID not in body and "98765" not in body and "Kumar" not in body
        # seven or more digits (spaces allowed) that are not part of a colour or an id: a phone or chat id
        assert not re.search(r"(?<![#\w])\d(?: ?\d){6,}", body), "a long digit run (phone or chat id) leaked"
    assert "Ramesh" in r.html and "Ramesh" in r.text  # first name only

    # Hindi and English side by side, the Hindi alert text and the English text
    assert "थुनाग" in r.html and "Thunag" in r.html and a.text_hi in r.html and a.text_en in r.text
    assert "कार्रवाई के बाद की रिपोर्ट" in r.html and "After-action report" in r.html
    # Key times in IST with the gaps (approved +2 min, first voice +30 s, first ack +3 min 05 s)
    assert "07:30:00 IST" in r.html  # 02:00 UTC is 07:30 IST
    assert "+2 min 00 s" in r.html and "+2 मि 00 से" in r.html
    assert "+30 s" in r.html and "+3 min 05 s" in r.html
    assert "Time to ear: 5 min 35 s / 5 मि 35 से" in r.text
    tte = r.summary
    assert tte["time_to_voice_seconds"] == 150 and tte["time_to_ear_seconds"] == 335
    assert tte["decided_by"] == "officer1" and tte["fixed_template"] is True and tte["drafting"] == "rule-fallback"
    assert "Fixed Hindi template (rule-fallback)" in r.html
    # Deliveries by channel, acknowledgement counted, and Cedar decisions (deliver was allowed)
    assert tte["deliveries"]["total"] == 3 and tte["deliveries"]["acknowledged"] == 1
    assert tte["audit"]["allow"] >= 1 and tte["audit"]["deny"] == 0
    assert "stub" in tte["deliveries_by_channel"]
    assert r.subject.startswith("पुकार after-action: Thunag Warning 01 Jul 2026")
    assert "<script" not in r.html.lower()


def test_names_are_escaped_and_denies_are_listed(repo, frozen, workflow):
    from Pukaar.policy.guard import authorize

    repo.put_recipient(Recipient(id="stub-x", village_id="thunag", name="<b>Eve</b> Smith", channel="stub"))
    _, a, _ = run_alert(repo, workflow, frozen, close=False)
    authorize(PRADHAN, "approve", "alert", a.id, {"village_id": "thunag"}, repo=repo)  # a deny on this alert
    r = aa.build(repo, repo.get_alert(a.id))
    assert "<b>Eve" not in r.html and "&lt;b&gt;Eve&lt;/b&gt;" in r.html and "Smith" not in r.html
    assert r.summary["audit"]["deny"] == 1
    assert "Only a district officer can approve an alert." in r.html
    assert "Interim" in r.html  # not closed yet: labelled as an interim report


def test_drill_and_replay_are_labelled(repo, frozen, workflow):
    _, a, _ = run_alert(repo, workflow, frozen, drill=True)
    r = aa.build(repo, a)
    assert r.mode == "drill" and "DRILL, not a real warning" in r.html and r.subject.endswith("[DRILL]")
    assert "exercise" in r.text  # the drill opened an exercise roll-call: counts only

    _, b, _ = run_alert(repo, workflow, frozen, replay=True)
    rb = aa.build(repo, b)
    assert rb.mode == "replay" and "REPLAY: past data, no real phone" in rb.html and rb.subject.endswith("[REPLAY]")


def test_rollcall_counts_only(repo, frozen, workflow):
    _, a, out = run_alert(repo, workflow, frozen)
    assert out["rollcall_id"]
    r = aa.build(repo, a)
    assert r.summary["rollcall"]["asked"] == 3 and r.summary["rollcall"]["safe"] == 0
    assert "Safety roll-call" in r.html


def test_fmt_gap_matches_the_console():
    assert aa.fmt_gap(65, "en") == "1 min 05 s" and aa.fmt_gap(65, "hi") == "1 मि 05 से"
    assert aa.fmt_gap(9, "en") == "9 s" and aa.fmt_gap(3 * 3600 + 120, "en") == "3 h 02 min"
    assert aa.gap_seconds("2026-07-01T02:00:00Z", "2026-07-01T01:00:00Z") is None


# -- close step -------------------------------------------------------------------
def test_close_stores_the_report_privately_in_s3(repo, frozen, workflow):
    _, a, out = run_alert(repo, workflow, frozen)
    assert out["status"] == "delivered" and out["after_action_key"] == f"reports/after-action/{a.id}.html"
    body, ctype = storage.get_bytes(out["after_action_key"])
    assert ctype.startswith("text/html") and "थुनाग" in body.decode("utf-8")
    summary = json.loads(storage.get_bytes(f"reports/after-action/{a.id}.json")[0])
    assert summary["alert_id"] == a.id and summary["status"] == "delivered"


def test_close_never_raises_when_the_report_fails(repo, frozen, workflow, monkeypatch, capsys):
    def boom(*_a, **_k):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(storage, "put_bytes", boom)
    _, a, out = run_alert(repo, workflow, frozen)
    assert out["status"] == "delivered" and "after_action_key" not in out
    assert repo.get_alert(a.id).status == "delivered"
    assert '"AfterActionFailed"' in capsys.readouterr().out

    monkeypatch.setattr(aa, "build", boom)
    _, _, out = run_alert(repo, workflow, frozen)
    assert out["status"] == "delivered"
    monkeypatch.setattr(aa, "on_close", boom)  # even if the whole hook blows up
    _, _, out = run_alert(repo, workflow, frozen)
    assert out["status"] == "delivered" and repo.get_village("thunag").open_alert_id is None


# -- SES ------------------------------------------------------------------------------
class FakeSes:
    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.calls: list[dict] = []
        self.fail_for = fail_for or set()

    def send_email(self, **kw):
        self.calls.append(kw)
        if kw["Destination"]["ToAddresses"][0] in self.fail_for:
            raise RuntimeError("MessageRejected: Email address is not verified.")
        return {"MessageId": f"m-{len(self.calls)}"}


@pytest.fixture()
def ses_env(monkeypatch):
    monkeypatch.setenv("PUKAAR_SES_FROM", "pukaar@example.org")
    monkeypatch.setenv("PUKAAR_AFTER_ACTION_TO", "dm@example.org, bad-address, sdm@example.org, DM@example.org")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_ses_call_shape_one_message_per_verified_recipient(repo, frozen, workflow, ses_env):
    _, a, _ = run_alert(repo, workflow, frozen, close=False)
    fake = FakeSes(fail_for={"sdm@example.org"})
    result = aa.email(aa.build(repo, a), client=fake)
    assert result == {"sent": 1, "failed": 1, "message_ids": ["m-1"]}
    assert [c["Destination"]["ToAddresses"] for c in fake.calls] == [["dm@example.org"], ["sdm@example.org"]]
    call = fake.calls[0]
    assert call["FromEmailAddress"] == "pukaar@example.org"
    simple = call["Content"]["Simple"]
    assert simple["Subject"]["Charset"] == "UTF-8" and simple["Subject"]["Data"].startswith("पुकार after-action: Thunag")
    assert simple["Body"]["Html"]["Charset"] == "UTF-8" and simple["Body"]["Html"]["Data"].startswith("<!doctype html>")
    assert simple["Body"]["Text"]["Charset"] == "UTF-8" and "KEY TIMES" in simple["Body"]["Text"]["Data"]


def test_close_emails_a_drill_through_ses(repo, frozen, workflow, ses_env, monkeypatch):
    fake = FakeSes()
    real = aa.on_close
    monkeypatch.setattr(aa, "on_close", lambda r, alert_id: real(r, alert_id, ses_client=fake))
    _, _, out = run_alert(repo, workflow, frozen, drill=True)
    assert out["after_action_key"] and len(fake.calls) == 2
    assert fake.calls[0]["Content"]["Simple"]["Subject"]["Data"].endswith("[DRILL]")


def test_email_skipped_without_config_in_local_mode_and_for_replays(repo, frozen, workflow, monkeypatch):
    monkeypatch.delenv("PUKAAR_SES_FROM", raising=False)
    get_settings.cache_clear()
    _, a, _ = run_alert(repo, workflow, frozen, close=False)
    r = aa.build(repo, a)
    assert aa.email(r) == {"skipped": "local"}
    fake = FakeSes()
    assert aa.email(r, client=fake) == {"skipped": "no sender"} and fake.calls == []
    r.mode = "replay"
    assert aa.email(r, client=fake) == {"skipped": "replay"}
    monkeypatch.setenv("PUKAAR_SES_FROM", "pukaar@example.org")
    monkeypatch.delenv("PUKAAR_AFTER_ACTION_TO", raising=False)
    get_settings.cache_clear()
    r.mode = "live"
    assert aa.email(r, client=fake) == {"skipped": "no recipients"}
    get_settings.cache_clear()


# -- Cedar and the route --------------------------------------------------------------
def test_cedar_after_action_access():
    assert evaluate(OFFICER, "view_after_action", "alert", "a1", {"village_id": "gohar"}).allowed
    assert evaluate(PRADHAN, "view_after_action", "alert", "a1", {"village_id": "thunag"}).allowed
    d = evaluate(PRADHAN, "view_after_action", "alert", "a1", {"village_id": "gohar"})
    assert not d.allowed and "pradhan of this village" in d.reason
    assert not evaluate(PRADHAN, "view_after_action", "alert", "a1", {"village_id": ""}).allowed
    assert not evaluate(Principal("bot", "agent"), "view_after_action", "alert", "a1", {"village_id": "thunag"}).allowed
    assert not evaluate(SYSTEM, "view_after_action", "alert", "a1", {"village_id": "thunag"}).allowed


@pytest.fixture()
def client(repo, monkeypatch):
    from Pukaar.api import auth
    from Pukaar.api.routers import officer
    from Pukaar.main import app

    for mod in (auth, officer):
        monkeypatch.setattr(mod, "get_repo", lambda: repo)
    return TestClient(app)


def token(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_route_serves_html_to_officers_and_own_pradhan_only(client, repo, frozen, workflow):
    _, a, _ = run_alert(repo, workflow, frozen)
    url = f"/alerts/{a.id}/after-action"
    assert client.get(url).status_code == 401
    r = client.get(url, headers=token(client, "officer1"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "default-src 'none'" in r.headers["content-security-policy"] and "थुनाग" in r.text
    assert client.get(url, headers=token(client, "pradhan_thunag")).status_code == 200
    assert client.get(url + "?format=json", headers=token(client, "officer1")).json()["alert_id"] == a.id
    assert client.get("/alerts/alr_missing/after-action", headers=token(client, "officer1")).status_code == 404


def test_route_denies_another_villages_pradhan_and_builds_when_not_stored(client, repo, frozen, workflow, monkeypatch):
    _, a, _ = run_alert(repo, workflow, frozen, close=False)
    repo.update_alert(a.id, village_id="gohar")
    r = client.get(f"/alerts/{a.id}/after-action", headers=token(client, "pradhan_thunag"))
    assert r.status_code == 403 and r.json()["detail"]["action"] == "view_after_action"
    # Nothing stored (never closed): built on the fly
    assert aa.load_stored(a.id) is None
    r = client.get(f"/alerts/{a.id}/after-action", headers=token(client, "officer1"))
    assert r.status_code == 200 and "Interim" in r.text


# -- template ----------------------------------------------------------------------------
def test_ses_permission_is_conditional_and_scoped():
    import test_template_safety as t

    assert t.T["Parameters"]["AfterActionFrom"]["Default"] == ""
    assert "HasAfterActionFrom" in t.T["Conditions"]
    grants = [(n, s) for n, s in t._statements() if any(a.startswith("ses:") for a in t._as_list(s["Action"]))]
    assert [n for n, _ in grants] == ["WorkflowFunction"], "only the workflow (close step) sends e-mail"
    for _, s in grants:
        assert t._as_list(s["Action"]) == ["ses:SendEmail"]
        resources = t._as_list(s["Resource"])
        assert resources and all("Fn::Sub" in r for r in resources)
        assert all(r["Fn::Sub"].startswith("arn:${AWS::Partition}:ses:${AWS::Region}:${AWS::AccountId}:identity/")
                   for r in resources)
        assert s["Condition"]["StringEquals"]["ses:FromAddress"] == {"Fn::Ref": "AfterActionFrom"}
    wf = t.RES["WorkflowFunction"]["Properties"]
    policy = next(p for p in wf["Policies"] if "Fn::If" in p)
    assert policy["Fn::If"][0] == "HasAfterActionFrom" and policy["Fn::If"][2] == {"Fn::Ref": "AWS::NoValue"}
    env = wf["Environment"]["Variables"]["PUKAAR_SES_FROM"]
    assert env == {"Fn::If": ["HasAfterActionFrom", {"Fn::Ref": "AfterActionFrom"}, {"Fn::Ref": "AWS::NoValue"}]}
