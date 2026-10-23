"""The ten pilot metrics (services/pilot_metrics.py, docs/PILOT_PROTOCOL.md): per alert for the console, pooled on
/public/pilot-metrics with live alerts, drills and replays apart, and nothing personal in the public answer."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from Pukaar.api import pilot
from Pukaar.core import clock
from Pukaar.delivery import dispatch
from Pukaar.services import assisted, pilot_metrics
from Pukaar.store.models import Recipient

from test_rollcall import tg  # noqa: F401  (fixture)
from test_roster import approved, people


def _live(repo, workflow, frozen, **kw):
    people(repo)
    repo.put_recipient(Recipient(id="5550010", village_id="thunag", name="Dadi Ma", channel="telegram"))
    assisted.set_care(repo, "thunag", "5550010", assisted=True, reason="elderly", escalate_to="5550004",
                      actor="officer1", actor_role="officer")
    s, alert = approved(repo, workflow, **kw)
    start = frozen["now"]
    frozen["now"] = start + timedelta(minutes=10)
    dispatch.acknowledge(repo, alert.id, "5550001")
    frozen["now"] = start + timedelta(minutes=40)
    dispatch.acknowledge(repo, alert.id, "5550003")
    frozen["now"] = start + timedelta(minutes=50)
    s.handle({"step": "close", "alert_id": alert.id, "outcome": "delivered"})
    return repo.get_alert(alert.id), start


def test_one_live_alert_measured_from_its_records(repo, frozen, workflow, tg):
    alert, start = _live(repo, workflow, frozen)
    repo.update_alert(alert.id, sirens_total=2, sirens_verified=1, outcome="real_flood",
                      outcome_onset_at=clock.iso(start + timedelta(minutes=90)))
    m = pilot_metrics.alert_metrics(repo, repo.get_alert(alert.id))
    assert m["kind"] == "live"
    # 1. coverage: 6 phones registered, no household list yet
    assert m["coverage"]["registered"] == 6 and m["coverage"]["share"] is None and m["coverage"]["observers"] == 3
    # 2. confirmed reach: 6 targeted on a phone; one at 10 min, one at 40 min
    r = m["confirmed_reach"]
    assert r["targeted"] == 6 and r["confirmed"] == 2
    assert (r["within_15"], r["within_30"], r["within_60"]) == (1, 1, 2)
    assert r["share_15"] == round(1 / 6, 3) and r["share_60"] == round(2 / 6, 3)
    # 3. assisted reach: Dadi Ma did not confirm; nobody checked yet
    a = m["assisted_reach"]
    assert a["targeted"] == 1 and a["confirmed"] == 0 and a["confirmed_or_checked_share"] == 0.0
    # 4. time chain: every step stamped, in order
    at = m["time_chain"]["at"]
    assert at["rule"] and at["asked"] and at["approved"] and at["first_delivery"] and at["first_ack"]
    assert m["time_chain"]["minutes"]["first_delivery_to_first_ack"] == 10.0
    # 5. lead time: harm began 90 min after the first send
    assert m["lead_time"]["from_first_delivery"] == 90.0 and m["lead_time"]["from_first_ack"] == 80.0
    # 6, 7: the outcome and siren proof
    assert m["outcome"]["outcome"] == "real_flood"
    assert m["siren"] == {"commanded": 2, "started": 0, "verified": 1, "verified_share": 0.5}
    # 8. data health at alert time; 9. the roll-call the close opened; 10. readiness
    assert m["data_health"]["gauge"] in {"none", "not_fresh", "fresh", "silent"}
    assert m["protective_action"] is not None and m["protective_action"]["asked"] >= 1
    assert m["readiness"]["checklist"]["items"] == 12 and m["readiness"]["observers"] == 3


def test_the_public_numbers_are_pooled_kept_apart_and_carry_nobody(repo, frozen, workflow, tg):
    alert, _ = _live(repo, workflow, frozen)
    _, replay = approved(repo, workflow, replay=True)
    out = pilot.metrics(repo)
    ten = out["ten"]
    assert ten["live"]["alerts"] == 1 and ten["replay"]["alerts"] == 1 and ten["drill"]["alerts"] == 0
    live = ten["live"]["confirmed_reach"]
    assert live["targeted"] == 6 and live["share_60"] == round(2 / 6, 3)
    # A replay reaches only the demo stub: no phone, so no reach to measure.
    assert ten["replay"]["confirmed_reach"]["targeted"] == 0 and ten["replay"]["confirmed_reach"]["share_15"] is None
    assert ten["replay"]["time_chain_median_minutes"]["rule_to_asked"] is not None
    assert ten["drill"]["confirmed_reach"]["share_30"] is None  # nothing measured is null, never 0
    assert ten["coverage"]["registered_phones"] >= 6 and ten["coverage"]["share"] is None
    assert ten["readiness"]["checklist"]["items"] == 12 and ten["readiness"]["assisted_households"] == 1
    assert ten["data_health_now"]["expected_24h"] == 5 * 96
    text = json.dumps(ten, ensure_ascii=False)
    for secret in (alert.id, replay.id, "Asha", "Dadi", "5550001"):
        assert secret not in text


def test_an_alert_that_reached_nobody_is_not_counted(repo, frozen, workflow):
    from test_workflow_steps import make_alert

    make_alert(repo, "warning", False)
    ten = pilot_metrics.ten(repo)
    assert ten["live"]["alerts"] == 0 and ten["live"]["outcomes"]["false_alarm_rate"] is None


@pytest.fixture()
def api(repo, monkeypatch):
    from Pukaar.api import auth
    from Pukaar.api.routers import officer
    from Pukaar.main import app

    for mod in (auth, officer):
        monkeypatch.setattr(mod, "get_repo", lambda: repo)
    return TestClient(app)


def _h(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_the_console_reads_one_alerts_metrics(api, repo, frozen, workflow, tg):
    alert, _ = _live(repo, workflow, frozen)
    r = api.get(f"/alerts/{alert.id}/metrics", headers=_h(api, "officer1"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["alert_id"] == alert.id and body["confirmed_reach"]["confirmed"] == 2
    assert api.get(f"/alerts/{alert.id}/metrics", headers=_h(api, "pradhan_thunag")).status_code == 200
    from Pukaar.store.models import Alert

    stamp = clock.iso(frozen["now"])
    repo.put_alert(Alert(id="alr_gohar_m", village_id="gohar", village_name="Gohar", village_name_hi="गोहर",
                         level="watch", status="closed", created_at=stamp, updated_at=stamp))
    assert api.get("/alerts/alr_gohar_m/metrics", headers=_h(api, "pradhan_thunag")).status_code in {403, 404}
    assert api.get("/alerts/alr_missing/metrics", headers=_h(api, "officer1")).status_code == 404
    assert api.get(f"/alerts/{alert.id}/metrics").status_code == 401
