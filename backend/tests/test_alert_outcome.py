"""'Was this real?': an officer's answer after a live alert closes, shown in the after-action report and
counted per rule as a false-alarm rate on /public/pilot-metrics (counts only, no personal data)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from Pukaar.api import pilot
from Pukaar.core import clock
from Pukaar.services import after_action
from Pukaar.store.models import Alert

from conftest import NOW


def _alert(repo, n: int, *, status: str = "closed", rules=("rain_24h>=115.6mm:warning",), outcome=None,
           drill: bool = False, replay: bool = False, aid: str | None = None) -> Alert:
    stamp = clock.iso(NOW - timedelta(hours=n))
    trace = {"rules_fired": list(rules)}
    if drill:
        trace["drill"] = True
    a = Alert(id=aid or f"alr_fa_{n:03d}", village_id="gohar", village_name="Gohar", village_name_hi="गोहर",
              level="warning", status=status, approved=True, created_at=stamp, updated_at=stamp, replay=replay,
              decision_trace=trace, outcome=outcome, outcome_by="officer1" if outcome else None)
    repo.put_alert(a)
    return a


def test_false_alarm_rate_per_rule_counts_only_closed_live_alerts(repo, frozen):
    _alert(repo, 1, outcome="real_flood", rules=("rain_24h>=115.6mm:warning", "discharge>=310.2:watch"))
    _alert(repo, 2, outcome="no_flood", rules=("rain_24h>=64.5mm:watch",))
    _alert(repo, 3, outcome="no_flood", rules=("gauge>=180cm:warning", "auto_verified_capped:rpt_x"))
    _alert(repo, 4, outcome="unknown")
    _alert(repo, 5)  # closed, not answered yet
    _alert(repo, 6, status="pending", outcome=None)  # still open: not counted
    _alert(repo, 7, outcome="no_flood", drill=True)  # drills and replays are never counted
    _alert(repo, 8, outcome="no_flood", replay=True)
    fa = pilot.metrics(repo)["false_alarms"]
    assert fa["closed_alerts"] == 5
    assert (fa["real_flood"], fa["no_flood"], fa["unknown"], fa["not_set"]) == (1, 2, 1, 1)
    assert fa["false_alarm_rate"] == round(2 / 3, 3)
    rules = {r["rule"]: r for r in fa["by_rule"]}
    assert set(rules) == {"rain_24h", "discharge", "gauge", "auto_verified_capped"}
    assert rules["rain_24h"]["alerts"] == 4 and rules["rain_24h"]["no_flood"] == 1
    assert rules["rain_24h"]["false_alarm_rate"] == 0.5
    assert rules["gauge"]["false_alarm_rate"] == 1.0 and rules["discharge"]["false_alarm_rate"] == 0.0


def test_nothing_answered_is_null_not_zero(repo, frozen):
    _alert(repo, 1)
    fa = pilot.metrics(repo)["false_alarms"]
    assert fa["false_alarm_rate"] is None and fa["by_rule"][0]["false_alarm_rate"] is None


def test_after_action_report_shows_the_answer(repo, frozen):
    a = _alert(repo, 1)
    report = after_action.build(repo, a)
    assert "Was this real?" in report.html and "Not set yet" in report.html and report.summary["was_real"] is None
    a = repo.update_alert(a.id, outcome="no_flood", outcome_by="officer1", outcome_at=clock.iso(NOW))
    report = after_action.build(repo, a)
    assert "No flood (false alarm)" in report.html and "WAS THIS REAL?" in report.text
    assert report.summary["was_real"] == "no_flood"


# -- the route ------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    from Pukaar.main import app

    return TestClient(app)


def _h(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_officer_records_the_outcome_and_metrics_show_counts_only(client):
    from Pukaar.store.repo import get_repo

    repo = get_repo()
    a = _alert(repo, 1, aid="alr_route_closed")
    # Still open ("delivering", not "pending": the app's table is shared with tests that list pending alerts).
    open_a = _alert(repo, 2, status="delivering", aid="alr_route_open")
    drill = _alert(repo, 3, drill=True, aid="alr_route_drill")
    officer = _h(client, "officer1")

    r = client.post(f"/alerts/{a.id}/outcome", json={"outcome": "real_flood"}, headers=officer)
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "real_flood" and r.json()["outcome_by"] == "officer1"
    assert any(t.step == "outcome" for t in repo.list_timeline(a.id))
    # It can be corrected; bad values, open alerts and drills are refused; pradhans cannot set it.
    assert client.post(f"/alerts/{a.id}/outcome", json={"outcome": "no_flood"}, headers=officer).json()["outcome"] == "no_flood"
    assert client.post(f"/alerts/{a.id}/outcome", json={"outcome": "maybe"}, headers=officer).status_code == 400
    assert client.post(f"/alerts/{open_a.id}/outcome", json={"outcome": "no_flood"}, headers=officer).status_code == 409
    assert client.post(f"/alerts/{drill.id}/outcome", json={"outcome": "no_flood"}, headers=officer).status_code == 409
    assert client.post(f"/alerts/{a.id}/outcome", json={"outcome": "no_flood"}).status_code == 401
    denied = client.post(f"/alerts/{a.id}/outcome", json={"outcome": "real_flood"}, headers=_h(client, "pradhan_thunag"))
    assert denied.status_code == 403

    # The after-action view shows it; the public metrics carry counts and rule names, never the officer.
    aar = client.get(f"/alerts/{a.id}/after-action", headers=officer).text
    assert "No flood (false alarm)" in aar
    metrics = client.get("/public/pilot-metrics")
    assert metrics.status_code == 200
    fa = metrics.json()["false_alarms"]
    assert fa["no_flood"] >= 1 and any(r["rule"] == "rain_24h" for r in fa["by_rule"])
    assert "officer1" not in metrics.text and a.id not in metrics.text
