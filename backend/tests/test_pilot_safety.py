"""Life-safety fixes from the pilot-readiness scorecard.

1. A replay never touches live state (levels, live alerts, the live sweep).
3. A delivery to a real recipient is never a "sent" stub.
5. Public routes carry no personal data (see also test_public_privacy.py).
7. Missing forecast data is unknown, never 0 mm, and never walks a level down.
8. A declined or expired alert is asked again while the level holds.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from Pukaar.core import clock
from Pukaar.services import decision_engine as de
from Pukaar.services import external_data, replay
from Pukaar.store.models import Reading, Recipient
from Pukaar.workflow.client import decide
from Pukaar.workflow.steps import Steps


def reading(v, at, peak, rain=0.0, missing=()):
    return Reading(village_id=v.id, at=clock.iso(at), rain_24h_mm=rain, discharge_peak=peak,
                   discharge_forecast=[{"date": at.date().isoformat(), "value": peak}], missing=list(missing))


def live_warning(repo, frozen, workflow, village="thunag"):
    """A live Warning alert raised by the sweep, still open."""
    v = repo.get_village(village)
    res = de.recompute_village(repo, v, now=frozen["now"], reading=reading(v, frozen["now"], v.thresholds.warning),
                               workflow=workflow)
    assert res.alert_id and res.level == "warning"
    return res.alert_id


def metrics(capsys) -> list[dict]:
    out = []
    for line in capsys.readouterr().out.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if "_aws" in row:
            out.append(row)
    return out


# -- 1. replay isolation ----------------------------------------------------------------
def test_live_alert_and_level_survive_replay_start_run_and_reset(repo, frozen, workflow):
    alert_id = live_warning(repo, frozen, workflow)
    repo.update_alert(alert_id, status="pending")
    before = repo.get_village("thunag")

    replay.start(repo, "himachal_2023_07")
    after_start = repo.get_village("thunag")
    assert (after_start.level, after_start.open_alert_id, after_start.replay) == ("warning", alert_id, False)

    # a few replay hours through the real code path
    st = repo.get_replay()
    for at in external_data.replay_hours("himachal_2023_07")[55:60]:
        for v in repo.list_villages():
            r = external_data.replay_reading("himachal_2023_07", v, at)
            if r is not None:
                repo.put_reading(r)
            de.recompute_village(repo, v, now=at, reading=r, workflow=workflow,
                                 window_prefix=f"replay-x-{st.started_at}", replay=True)
    during = repo.get_village("thunag")
    assert (during.level, during.level_since, during.open_alert_id) == ("warning", before.level_since, alert_id)
    assert repo.get_replay_village("sujanpur").level != "normal"  # the replay ran on its own copies
    assert repo.get_village("sujanpur").level == "normal"

    replay.reset(repo)
    live = repo.get_alert(alert_id)
    assert live is not None and live.status == "pending" and not live.replay
    assert repo.get_village("thunag").level == "warning" and repo.get_village("thunag").open_alert_id == alert_id
    assert alert_id in {a.id for a in repo.open_alerts()}
    assert repo.list_replay_villages() == {}
    assert all(not a.replay for a in repo.list_alerts())


def test_live_sweep_keeps_working_while_a_replay_runs(repo, frozen, workflow):
    replay.start(repo, "himachal_2023_07")
    assert replay.is_running(repo)

    def fetch(v, at):
        return reading(v, at, v.thresholds.warning if v.id == "gohar" else 0.0)

    results = {r.village_id: r for r in de.sweep_all(repo, now=frozen["now"], fetch=fetch, workflow=workflow)}
    assert results["gohar"].level == "warning" and results["gohar"].alert_id  # a live alert, during a replay
    assert not repo.get_alert(results["gohar"].alert_id).replay
    assert workflow.started == [results["gohar"].alert_id]
    assert repo.get_replay_village("gohar").level == "normal"  # the replay's copy is separate


def test_replay_reset_never_removes_live_items(repo, frozen, workflow):
    alert_id = live_warning(repo, frozen, workflow, "gohar")
    v = repo.get_village("gohar")
    repo.put_reading(reading(v, frozen["now"], 1.0))
    replay.reset(repo)
    replay.reset(repo)
    assert repo.get_alert(alert_id) is not None
    assert any(not r.replay for r in repo.list_readings("gohar"))
    assert repo.get_village("gohar").level == "warning"


def test_a_replay_never_hides_a_live_warning_on_public_pages(repo, frozen, workflow):
    from Pukaar.api import views

    live_warning(repo, frozen, workflow, "thunag")
    replay.start(repo, "himachal_2023_07")
    repo.update_replay_village("thunag", level="critical")
    repo.update_replay_village("pandoh", level="critical")
    thunag = views.village(repo, repo.get_village("thunag"))
    pandoh = views.village(repo, repo.get_village("pandoh"))
    # live warning wins; the replay's level is only beside it
    assert (thunag["level"], thunag["replay"], thunag["live_level"], thunag["replay_level"]) == (
        "warning", False, "warning", "critical")
    # a quiet live village shows the replay, labelled, with its live level beside it
    assert (pandoh["level"], pandoh["replay"], pandoh["live_level"]) == ("critical", True, "normal")


def test_replay_disabled_stack_refuses_to_start(repo, frozen, monkeypatch):
    from Pukaar.core import config

    monkeypatch.setenv("PUKAAR_REPLAY_ENABLED", "false")
    config.get_settings.cache_clear()
    try:
        with pytest.raises(PermissionError):
            replay.start(repo, "himachal_2023_07")
    finally:
        monkeypatch.delenv("PUKAAR_REPLAY_ENABLED")
        config.get_settings.cache_clear()
    assert repo.list_replay_villages() == {}


def test_replay_alert_close_clears_the_copy_not_the_live_record(repo, frozen, workflow):
    replay.start(repo, "himachal_2023_07")
    v = repo.get_village("sujanpur")
    res = de.recompute_village(repo, v, now=frozen["now"], reading=reading(v, frozen["now"], v.thresholds.critical),
                               workflow=workflow, replay=True)
    assert repo.get_replay_village("sujanpur").open_alert_id == res.alert_id
    assert repo.get_village("sujanpur").open_alert_id is None
    Steps(repo, None, synthesize=lambda *_: None).handle({"step": "close", "alert_id": res.alert_id,
                                                           "outcome": "declined"})
    assert repo.get_replay_village("sujanpur").open_alert_id is None


# -- 3. delivery honesty --------------------------------------------------------------------
def _approved(repo, workflow):
    from test_workflow_steps import drafted_and_asked

    s, a, _ = drafted_and_asked(repo)
    decide(repo, workflow, a.id, "approved", "officer1")
    return s, a


def test_unreadable_token_is_a_failed_delivery_not_a_stub(repo, frozen, workflow, capsys):
    from Pukaar.delivery import telegram

    assert not telegram.configured()  # tests run with no token: as if SSM could not be read
    repo.put_recipient(Recipient(id="98765", village_id="thunag", name="Real phone", channel="telegram"))
    s, a = _approved(repo, workflow)
    capsys.readouterr()
    out = s.handle({"step": "deliver", "alert_id": a.id})
    deliveries = {d.recipient_id: d for d in repo.list_deliveries(a.id)}
    real = deliveries["98765"]
    assert real.channel == "telegram" and real.status == "failed" and "token unavailable" in real.error
    # the demo recipients that are explicitly stub still get a recorded stub delivery
    assert {d.status for k, d in deliveries.items() if k.startswith("stub-")} == {"sent"}
    assert out["sent"] == 2 and out["failed"] == 1
    assert any(m.get("DeliveryFailed") == 1 and m.get("Channel") == "telegram" for m in metrics(capsys))


def test_telegram_error_is_recorded_as_failed_with_reason(repo, frozen, workflow, monkeypatch):
    from Pukaar.delivery import telegram

    monkeypatch.setenv("PUKAAR_TELEGRAM_TOKEN", "fake")

    def boom(*a, **k):
        raise telegram.TelegramError("sendAudio failed: Too Many Requests")

    monkeypatch.setattr(telegram, "send_alert", boom)
    repo.put_recipient(Recipient(id="98765", village_id="thunag", name="Real phone", channel="telegram"))
    s, a = _approved(repo, workflow)
    s.handle({"step": "deliver", "alert_id": a.id})
    d = {x.recipient_id: x for x in repo.list_deliveries(a.id)}["98765"]
    assert (d.channel, d.status) == ("telegram", "failed") and "Too Many Requests" in d.error
    assert repo.get_alert(a.id).delivered_count == 2  # the two stub demo phones only


def test_ssm_failure_reads_as_unavailable_and_is_logged(monkeypatch, capsys):
    import boto3

    from Pukaar.core import secrets

    class Throttled:
        def get_parameter(self, **kw):
            raise RuntimeError("ThrottlingException: Rate exceeded")

    monkeypatch.setattr(boto3, "client", lambda *a, **k: Throttled())
    secrets._CACHE.clear()
    assert secrets._ssm("telegram_token") is None
    out = capsys.readouterr().out
    assert '"SecretReadFailed": 1' in out


def test_rollcall_to_a_real_phone_without_token_is_an_error_not_a_stub(repo, frozen):
    from Pukaar.policy.guard import Principal
    from Pukaar.services import rollcall

    repo.put_recipient(Recipient(id="98765", village_id="thunag", name="Asha Devi", channel="telegram"))
    rc = rollcall.open_rollcall(repo, repo.get_village("thunag"), principal=Principal("officer1", "officer"))
    asked = {x.recipient_id: x for x in repo.list_rollcall_asked(rc.id)}
    assert asked["98765"].channel == "telegram" and "token unavailable" in (asked["98765"].error or "")


# -- 7. missing data --------------------------------------------------------------------------
def test_missing_hourly_rain_is_unknown_not_zero(repo, monkeypatch):
    v = repo.get_village("thunag")
    hours = [f"2026-07-01T{h:02d}:00" for h in range(24)]
    rain = {"hourly": {"time": hours, "precipitation": [5.0] * 20 + [None] * 4}}
    flood = {"daily": {"time": ["2026-07-01"], "river_discharge": [None]}}

    class Resp:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            return Resp(rain if "forecast" in url else flood)

    monkeypatch.setattr(external_data.httpx, "Client", Client)
    r = external_data.fetch_live(v, clock.parse("2026-07-01T00:00:00Z"))
    assert r.rain_24h_mm is None and r.missing == ["rain", "discharge"]
    assert len(r.rain_hourly) == 20 and all(h["mm"] is not None for h in r.rain_hourly)


def test_missing_rain_is_carried_forward_then_unavailable_and_never_walks_the_level_down(repo, frozen, workflow,
                                                                                       capsys):
    v = repo.get_village("thunag")
    t0 = frozen["now"]
    # a complete sweep at warning-level rain
    de.recompute_village(repo, v, now=t0, fetch=lambda vv, at: reading(vv, at, 0.0, rain=130.0), workflow=workflow)
    ok = repo.get_village("thunag")
    assert (ok.level, ok.data_status, ok.data_ok_at) == ("warning", "ok", clock.iso(t0))

    gap = lambda vv, at: reading(vv, at, 0.0, rain=None, missing=["rain"])  # noqa: E731
    statuses = []
    for i in range(1, 8):
        res = de.recompute_village(repo, repo.get_village("thunag"), now=t0 + timedelta(minutes=15 * i), fetch=gap,
                                   workflow=workflow)
        cur = repo.get_village("thunag")
        statuses.append(cur.data_status)
        assert cur.level == "warning" and res.level == "warning"  # never walked down on missing data
    assert statuses[:4] == ["stale"] * 4 and statuses[4:] == ["unavailable"] * 3
    cur = repo.get_village("thunag")
    assert cur.data_ok_at == clock.iso(t0) and cur.data_missing_sweeps == 7 and "rain" in cur.data_note
    # stale sweeps used the last complete rain, and said so
    stored = [r for r in repo.list_readings("thunag") if r.missing]
    assert stored and all(r.rain_24h_mm is None for r in stored)  # what was stored is what arrived
    stale = [m for m in metrics(capsys) if "VillageDataStale" in m]
    assert stale and all(m["Village"] == "thunag" for m in stale)

    # complete data again: back to ok
    de.recompute_village(repo, repo.get_village("thunag"), now=t0 + timedelta(hours=3),
                         fetch=lambda vv, at: reading(vv, at, 0.0, rain=130.0), workflow=workflow)
    assert repo.get_village("thunag").data_status == "ok"


def test_a_rise_on_carried_values_records_where_they_came_from(repo, frozen, workflow):
    v = repo.get_village("gohar")
    t0 = frozen["now"]
    # complete data at watch-level rain, then the rain goes missing while the river rises to warning
    de.recompute_village(repo, v, now=t0, fetch=lambda vv, at: reading(vv, at, 0.0, rain=70.0), workflow=workflow)
    res = de.recompute_village(repo, repo.get_village("gohar"), now=t0 + timedelta(minutes=15), workflow=workflow,
                               fetch=lambda vv, at: reading(vv, at, v.thresholds.warning, rain=None, missing=["rain"]))
    assert res.rose
    trace = repo.get_alert(res.alert_id).decision_trace if res.alert_id else None
    if trace is None:  # the watch alert was escalated in place
        trace = repo.get_alert(repo.get_village("gohar").open_alert_id).decision_trace
    assert trace["data"]["status"] == "stale" and trace["data"]["carried_from"] == clock.iso(t0)
    assert "rain_carried_forward" in trace["rules_fired"]
    assert trace["forecast_snapshot"]["rain_24h_mm"] == 70.0


def test_fetch_failure_marks_the_village_and_holds_the_level(repo, frozen, workflow, capsys):
    repo.update_village("pandoh", level="watch", data_ok_at=clock.iso(frozen["now"] - timedelta(minutes=50)))

    def fetch(v, at):
        if v.id == "pandoh":
            raise RuntimeError("open-meteo 503")
        return reading(v, at, 0.0)

    results = {r.village_id: r for r in de.sweep_all(repo, now=frozen["now"], fetch=fetch, workflow=workflow)}
    assert results["pandoh"].note.startswith("error")
    p = repo.get_village("pandoh")
    assert p.level == "watch" and p.data_status in {"stale", "unavailable"} and "fetch failed" in p.data_note
    assert any(m.get("Village") == "pandoh" and m.get("VillageDataStale") == 1 for m in metrics(capsys))
    # shown on the public village view
    from Pukaar.api import views

    assert views.village(repo, p)["data_status"] == p.data_status


# -- 8. re-ask -------------------------------------------------------------------------------------
def _expire(repo, alert_id):
    s = Steps(repo, None, synthesize=lambda *_: None)
    s.handle({"step": "draft", "alert_id": alert_id})
    s.handle({"step": "expire", "alert_id": alert_id})
    s.handle({"step": "close", "alert_id": alert_id, "outcome": "expired"})


def test_expired_warning_is_asked_again_after_the_cooldown_while_the_level_holds(repo, frozen, workflow):
    first = live_warning(repo, frozen, workflow)
    _expire(repo, first)
    v = repo.get_village("thunag")
    held = lambda: reading(v, frozen["now"], v.thresholds.warning)  # noqa: E731

    frozen["now"] += timedelta(minutes=20)
    res = de.recompute_village(repo, repo.get_village("thunag"), now=frozen["now"], reading=held(), workflow=workflow)
    assert res.alert_id is None  # inside the cooldown: nothing yet

    frozen["now"] += timedelta(minutes=11)
    res = de.recompute_village(repo, repo.get_village("thunag"), now=frozen["now"], reading=held(), workflow=workflow)
    assert res.alert_id and res.alert_id != first and res.note == "asked again after an unsent alert"
    again = repo.get_alert(res.alert_id)
    assert again.level == "warning" and not again.replay
    reask = again.decision_trace["reask"]
    assert (reask["previous_alert_id"], reask["previous_status"], reask["cooldown_minutes"]) == (first, "expired", 30)
    assert "asked again: expired alert" in repo.list_timeline(again.id)[0].detail
    assert workflow.started[-1] == again.id
    assert repo.get_village("thunag").open_alert_id == again.id

    # while the new one is open, nothing more
    frozen["now"] += timedelta(minutes=45)
    res = de.recompute_village(repo, repo.get_village("thunag"), now=frozen["now"], reading=held(), workflow=workflow)
    assert res.alert_id is None


def test_declined_alert_is_asked_again_but_a_delivered_one_is_not(repo, frozen, workflow):
    first = live_warning(repo, frozen, workflow, "gohar")
    s = Steps(repo, None, synthesize=lambda *_: None)
    s.handle({"step": "draft", "alert_id": first})
    s.handle({"step": "ask_officer", "alert_id": first, "officer_index": 0, "task_token": "T"})
    decide(repo, workflow, first, "declined", "officer1", reason="looks wrong")
    s.handle({"step": "close", "alert_id": first, "outcome": "declined"})
    v = repo.get_village("gohar")
    frozen["now"] += timedelta(minutes=31)
    res = de.recompute_village(repo, repo.get_village("gohar"), now=frozen["now"],
                               reading=reading(v, frozen["now"], v.thresholds.warning), workflow=workflow)
    trace = repo.get_alert(res.alert_id).decision_trace["reask"]
    assert trace["previous_status"] == "declined" and trace["previous_decided_by"] == "officer1"

    # a delivered alert is not re-asked
    repo.update_alert(res.alert_id, status="delivered", approved=True)
    repo.update_village("gohar", open_alert_id=None)
    frozen["now"] += timedelta(hours=1)
    res2 = de.recompute_village(repo, repo.get_village("gohar"), now=frozen["now"],
                                reading=reading(v, frozen["now"], v.thresholds.warning), workflow=workflow)
    assert res2.alert_id is None


def test_no_reask_when_the_level_fell_below_the_unsent_alert(repo, frozen, workflow):
    first = live_warning(repo, frozen, workflow)
    _expire(repo, first)
    repo.update_village("thunag", level="watch")
    v = repo.get_village("thunag")
    frozen["now"] += timedelta(hours=1)
    res = de.recompute_village(repo, v, now=frozen["now"], reading=reading(v, frozen["now"], v.thresholds.watch),
                               workflow=workflow)
    assert res.alert_id is None


# -- 2. the judge account through the API ----------------------------------------------------------
def test_judge_cannot_decide_a_live_alert_but_can_a_replay_one():
    from fastapi.testclient import TestClient

    from Pukaar.core.ids import new_id
    from Pukaar.main import app
    from Pukaar.store.models import Alert
    from Pukaar.store.repo import get_repo

    client = TestClient(app)
    h = {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": "judge"}).json()["token"]}
    repo = get_repo()
    stamp = clock.iso(clock.now())
    live = Alert(id=new_id("alr"), village_id="janjehli", village_name="Janjehli", village_name_hi="जंजैहली",
                 level="warning", status="pending", created_at=stamp, updated_at=stamp, task_token="T1")
    repo.put_alert(live)
    r = client.post(f"/alerts/{live.id}/approve", headers=h)
    assert r.status_code == 403 and r.json()["detail"]["reason"].startswith("Public demo account")
    r = client.post(f"/alerts/{live.id}/decline", json={"reason": "x"}, headers=h)
    assert r.status_code == 403
    assert repo.get_alert(live.id).status == "pending"
    audit = [x for x in repo.list_audit(stamp[:10], f"alert:{live.id}") if x.actor == "judge"]
    assert audit and all(x.decision == "deny" and "replay alerts only" in x.reason for x in audit)
    # village actions on a live village are refused too
    assert client.post("/villages/thunag/roadblocks", json={"lat": 31.5, "lon": 77.1, "note": "x"},
                       headers=h).status_code == 403
    assert client.post("/directives", json={"village_id": "thunag", "type": "evacuate"}, headers=h).status_code == 403

    replay_alert = live.model_copy(update={"id": new_id("alr"), "replay": True})
    repo.put_alert(replay_alert)
    r = client.post(f"/alerts/{replay_alert.id}/approve", headers=h)
    assert r.status_code != 403  # Cedar allows it; the workflow decides what happens next
