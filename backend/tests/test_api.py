"""HTTP routes against the local-mode app (in-process moto)."""

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from Pukaar.main import app

    return TestClient(app)


def token(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_health_is_public_and_honest(client):
    body = client.get("/health").json()
    assert body["mode"] == "local"
    assert body["services"]["bedrock"].startswith("disabled")
    assert body["services"]["telegram"].startswith("not configured")


def test_public_pages_work_signed_out(client):
    villages = client.get("/villages").json()
    assert {v["id"] for v in villages} == {"thunag", "janjehli", "gohar", "pandoh", "sujanpur"}
    assert all(v["coords_verified"] is False and v["population"] is None for v in villages)
    overview = client.get("/public/overview").json()
    assert set(overview["counters"]) == {"villages_watched", "alerts_sent", "phones_acknowledged", "reports_received"}
    detail = client.get("/villages/pandoh").json()
    assert detail["past_events"] and detail["past_events"][0]["source"].startswith("Open-Meteo")


def test_officer_routes_need_sign_in_and_explain_denials(client):
    assert client.get("/alerts").status_code == 401
    r = client.post("/replay/start", json={}, headers=token(client, "pradhan_thunag"))
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "Only a district officer can start or reset a replay."


def test_anonymous_report_returns_tracking_code(client):
    r = client.post("/reports", data={"village_id": "thunag", "text": "पुल टूट गया है", "lat": "31.56", "lon": "77.165"},
                    files={"photo": ("p.jpg", b"\xff\xd8\xff", "image/jpeg")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report"]["report_type"] == "bridge_unsafe" and body["report"]["photo_url"].endswith(".jpg")
    track = client.get(f"/track/{body['track_code']}").json()
    assert track["steps"][0]["done"] is True
    assert client.post("/reports", data={"village_id": "thunag"}).status_code == 400


def test_pradhan_sees_only_own_village_reports(client):
    h = token(client, "pradhan_thunag")
    assert client.get("/reports?village_id=thunag", headers=h).status_code == 200
    assert client.get("/reports?village_id=gohar", headers=h).status_code == 403


def test_report_state_change_and_undo(client):
    h = token(client, "officer1")
    rid = client.post("/reports", data={"village_id": "gohar", "text": "pani badh raha"}).json()["report"]["id"]
    r = client.patch(f"/reports/{rid}/state", json={"state": "false"}, headers=h).json()
    assert r["state"] == "false" and r["previous_state"] in {"unverified", "received"}
    undone = client.patch(f"/reports/{rid}/state", json={"state": r["previous_state"]}, headers=h).json()
    assert undone["state"] == r["previous_state"]


def test_full_loop_replay_approve_by_link_and_audit(client, monkeypatch):
    from Pukaar.workflow.client import get_workflow

    wf = get_workflow()
    monkeypatch.setattr(wf, "ack_wait", 0)
    h = token(client, "officer1")
    client.post("/replay/reset", headers=h)
    started = client.post("/replay/start", json={"scenario": "himachal_2023_07", "speed_seconds_per_hour": 0}, headers=h)
    assert started.status_code == 200 and started.json()["active"]
    deadline = time.time() + 60
    while time.time() < deadline and client.get("/replay/status").json()["active"]:
        time.sleep(0.2)
    pending = []
    while time.time() < deadline and not pending:
        pending = [a for a in client.get("/alerts?status=pending", headers=h).json()]
        time.sleep(0.2)
    assert pending and all(a["replay"] for a in pending)
    alert = pending[0]

    # one-tap link: officer1 is asked first
    from Pukaar.store.repo import get_repo
    from Pukaar.workflow import tokens

    stored = get_repo().get_alert(alert["id"])
    link = tokens.sign(alert["id"], "officer1", stored.token_version, "approve")
    view = client.get(f"/approval/{link}").json()
    assert view["valid"] and view["alert"]["text_hi"]
    assert "task_token" not in view["alert"]
    ok = client.post(f"/approval/{link}", json={"decision": "approve"})
    assert ok.status_code == 200 and ok.json()["status"] in {"approved", "delivering", "delivered"}
    late = client.post(f"/approval/{link}", json={"decision": "approve"})
    assert late.status_code == 409 and late.json()["detail"]["message_hi"]

    while time.time() < deadline:
        detail = client.get(f"/alerts/{alert['id']}", headers=h).json()
        if detail["alert"]["status"] == "delivered":
            break
        time.sleep(0.2)
    assert detail["alert"]["status"] == "delivered"
    assert {d["channel"] for d in detail["deliveries"]} == {"stub"}  # replay never reaches phones
    assert [a for a in detail["audit"] if a["action"] == "deliver" and a["decision"] == "allow"]
    assert client.post("/replay/reset", headers=h).json()["active"] is False


def test_ask_pukaar_returns_chart_from_tool_data(client):
    out = client.post("/ask/officer", json={"question": "Which villages need attention?"},
                      headers=token(client, "officer1")).json()
    assert out["tools"][0]["name"] == "rank_villages"
    assert out["chart"]["type"] == "bar" and out["model"].startswith("rule-router")
    refused = client.post("/ask/officer", json={"question": "Write me a poem"}, headers=token(client, "officer1")).json()
    assert refused["answer"] == "I can only answer questions about flood operations."


def test_telegram_webhook_rejects_wrong_secret(client):
    assert client.post("/telegram/webhook", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": "nope"}).status_code == 403
