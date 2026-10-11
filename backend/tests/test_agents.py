"""Public /agents, /agents/traces and /sensors: read from code, honest about fallbacks, no personal data."""

from __future__ import annotations

import dataclasses
import json
from datetime import timedelta

import pytest
from conftest import NOW
from fastapi.testclient import TestClient

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.services import agents as agents_svc
from Pukaar.services import watch
from Pukaar.services.analyst import ANALYST_TOOLS
from Pukaar.services.drafting import DRAFT_TOOLS
from Pukaar.store.models import Alert, DraftCheck, SensorReading
from Pukaar.workflow.client import decide
from Pukaar.workflow.steps import Steps


def sr(village, cm, minutes_ago, battery=4.0, transport="https"):
    v_device = f"gauge-{village}-sim"
    return SensorReading(village_id=village, device_id=v_device, at=clock.iso(NOW - timedelta(minutes=minutes_ago)),
                         water_level_cm=cm, battery_v=battery, simulated=True, transport=transport,
                         received_at=clock.iso(NOW - timedelta(minutes=minutes_ago)))


def kinds(findings):
    return sorted(f.kind for f in findings)


# -- Watch agent ------------------------------------------------------------------
def test_watch_healthy_gauge_has_no_findings(repo, frozen):
    v = repo.get_village("gohar")
    readings = [sr("gohar", 80 + (i % 3), 20 - i) for i in range(20)]
    assert watch.check(v, readings, NOW) == []


def test_watch_flags_stale_flatline_jump_and_battery(repo, frozen):
    v = repo.get_village("gohar")
    stale = [sr("gohar", 80 + i, 120 - i) for i in range(3)]
    assert kinds(watch.check(v, stale, NOW)) == ["stale"]
    flat = [sr("gohar", 91.0, 20 - i) for i in range(16)]
    assert kinds(watch.check(v, flat, NOW)) == ["flatline"]
    jump = [sr("gohar", 80, 5), sr("gohar", 81, 4), sr("gohar", 260, 3), sr("gohar", 82, 2)]
    found = watch.check(v, jump, NOW)
    assert kinds(found) == ["jump"] and abs(found[0].value) == 179
    low = [sr("gohar", 80, 2, battery=3.31)]
    found = watch.check(v, low, NOW)
    assert kinds(found) == ["battery"] and "3.31" in found[0].message_en and "V" in found[0].message_hi


def test_watch_without_any_reading_says_so(repo, frozen):
    v = repo.get_village("gohar")
    found = watch.check(v, [], NOW, None)
    assert [(f.kind, f.severity) for f in found] == [("no_data", "info")]


# -- registry -----------------------------------------------------------------------
def test_registry_is_read_from_code(repo, frozen):
    reg = agents_svc.registry(repo)
    by_id = {a["id"]: a for a in reg["agents"]}
    assert set(by_id) == {"drafting-agent", "analyst-agent", "report-agent", "report-guardrail", "watch-agent"}
    assert [t["name"] for t in by_id["drafting-agent"]["tools"]] == DRAFT_TOOLS
    assert [t["name"] for t in by_id["analyst-agent"]["tools"]] == ANALYST_TOOLS
    assert all(t["read_only"] and t["description"] for a in reg["agents"] for t in a["tools"])
    never = {n["action"] for n in by_id["drafting-agent"]["never"]}
    # Every Cedar forbid action for agents, plus the design rules.
    assert {"approve", "decline", "deliver", "auto_send", "failsafe", "issue_directive"} <= never
    assert {"set_level", "choose_recipients"} <= never
    assert set(agents_svc.forbidden_agent_actions()) == {"approve", "decline", "deliver", "auto_send", "failsafe",
                                                         "issue_directive", "open_rollcall", "remind_rollcall", "set_shelter_status",
                                                         "block_road"}
    assert by_id["drafting-agent"]["max_turns"] == 4
    assert "time_window_hi" in by_id["drafting-agent"]["output_fields"]
    assert any("Strands" in p for p in by_id["drafting-agent"]["primitives"])
    assert reg["counters"]["read_only_tools"] == 10 and reg["counters"]["cedar_policies"] >= 8


def test_status_is_honest(repo, frozen, monkeypatch):
    # Tests run with the model switched off: every model agent says fallback.
    reg = agents_svc.registry(repo)
    by_id = {a["id"]: a for a in reg["agents"]}
    assert by_id["drafting-agent"]["status"]["state"] == "fallback"
    assert by_id["report-agent"]["status"]["state"] == "fallback"
    assert by_id["watch-agent"]["status"]["state"] == "deterministic"
    # The guardrail screen is a separate feature: until its module ships, it says so.
    gr = by_id["report-guardrail"]["status"]
    assert gr["state"] in {"pending", "fallback", "live"}
    if not agents_svc.guardrail_status()["present"]:
        assert gr["label_en"] == "Pending deploy"

    on = dataclasses.replace(get_settings(), llm_enabled=True)
    monkeypatch.setattr(agents_svc, "get_settings", lambda: on)
    assert agents_svc.model_status(repo)["state"] == "unknown"
    v = repo.get_village("thunag")
    stamp = clock.iso(clock.now())

    def put(model, reason, minutes):
        at = clock.iso(clock.now() + timedelta(minutes=minutes))
        repo.put_alert(Alert(id=f"alr_{minutes}", village_id=v.id, village_name=v.name, village_name_hi=v.name_hi,
                             level="warning", status="pending", created_at=at, updated_at=stamp,
                             reasoning_model=model, draft_check=DraftCheck(passed=model != "rule-fallback", reason=reason)))

    put("rule-fallback", "model unavailable; fixed template used", 1)
    st = agents_svc.model_status(repo)
    assert st["state"] == "pending" and st["label_en"].startswith("Pending model access")
    put("us.amazon.nova-2-lite-v1:0", "every number and place found in the decision trace", 2)
    st = agents_svc.model_status(repo)
    assert st["state"] == "live" and "Nova 2 Lite" in st["label_en"]


# -- traces ---------------------------------------------------------------------------
def test_traces_turn_a_real_alert_into_rounds_without_personal_data(repo, frozen, workflow):
    v = repo.get_village("thunag")
    stamp = clock.iso(clock.now())
    trace = {"rules_fired": ["rain_24h>=64.5mm:warning"], "previous_level": "normal", "raw_level": "warning",
             "level": "warning", "evidence": [
                 {"kind": "reading", "rain_24h_mm": 72.4, "rain_level": "warning", "discharge_peak": 8.1,
                  "river_level": "normal"},
                 {"kind": "gauge", "water_level_cm": 150.0, "gauge_level": "watch", "simulated": True},
                 {"kind": "report", "report_id": "rep_1", "verified": False}]}
    a = Alert(id="alr_t1", village_id=v.id, village_name=v.name, village_name_hi=v.name_hi, level="warning",
              status="drafting", created_at=stamp, updated_at=stamp, decision_trace=trace)
    repo.put_alert(a)
    s = Steps(repo, None, synthesize=lambda *_: None)
    s.handle({"step": "draft", "alert_id": a.id})
    s.handle({"step": "ask_officer", "alert_id": a.id, "officer_index": 0, "task_token": "TOKEN-1"})
    decide(repo, workflow, a.id, "approved", "officer_secret_name")
    s.handle({"step": "deliver", "alert_id": a.id})

    out = agents_svc.traces(repo, 5)
    t = next(x for x in out if x["alert_id"] == "alr_t1")
    assert [r["kind"] for r in t["rounds"]] == ["sense", "rules", "tools", "draft", "approve", "deliver"]
    rounds = {r["kind"]: r for r in t["rounds"]}
    sense = json.dumps(rounds["sense"]["facts"])
    assert "72.4 mm" in sense and "150 cm" in sense and "simulated" in sense and "1 (0 verified)" in sense
    assert "rain_24h>=64.5mm:warning" in json.dumps(rounds["rules"]["facts"])
    # No model was reached: no invented tool calls, the template is named.
    assert rounds["tools"]["state"] == "skipped"
    assert rounds["draft"]["state"] == "fallback" and "template" in json.dumps(rounds["draft"]["facts"])
    assert rounds["approve"]["state"] == "ok" and "duty officer" in json.dumps(rounds["approve"]["facts"])
    assert rounds["deliver"]["state"] == "ok"
    blob = json.dumps(out, ensure_ascii=False)
    assert "officer_secret_name" not in blob and "Demo phone" not in blob and "TOKEN-1" not in blob
    assert "text_hi" not in blob


def test_traces_show_tool_calls_and_denials(repo, frozen):
    v = repo.get_village("gohar")
    stamp = clock.iso(clock.now())
    a = Alert(id="alr_t2", village_id=v.id, village_name=v.name, village_name_hi=v.name_hi, level="watch",
              status="pending", created_at=stamp, updated_at=stamp, reasoning_model="us.amazon.nova-2-lite-v1:0",
              draft_check=DraftCheck(passed=True, reason="every number and place found in the decision trace"),
              decision_trace={"rules_fired": ["x"], "drafting_tools": [
                  {"name": "get_village_risk", "input": {"village_id": "gohar"}, "decision": "allow",
                   "output_summary": "secret output"},
                  {"name": "send_alert", "input": {}, "decision": "deny", "output_summary": ""}]})
    repo.put_alert(a)
    t = agents_svc.traces(repo, 1)[0]
    rounds = {r["kind"]: r for r in t["rounds"]}
    assert rounds["tools"]["state"] == "deny"
    assert [f["en"] for f in rounds["tools"]["facts"]] == ["get_village_risk", "send_alert"]
    assert "secret output" not in json.dumps(t)
    assert rounds["draft"]["state"] == "ok" and rounds["approve"]["state"] == "pending"


# -- sensors ---------------------------------------------------------------------------
def test_sensor_board_counts_freshness_transport_and_findings(repo, frozen):
    for i in range(6):
        assert repo.put_sensor_reading(sr("gohar", 150 + i, 10 - i * 2, transport="mqtt" if i % 2 else "https"))
    repo.put_sensor_reading(sr("pandoh", 60, 300, battery=3.2))
    board = agents_svc.sensors(repo)
    rows = {r["id"]: r for r in board["villages"]}
    assert set(rows) == {"thunag", "janjehli", "gohar", "pandoh", "sujanpur"}
    g = rows["gohar"]
    assert g["readings_24h"] == 6 and g["fresh"] and g["gauge_level"] == "watch" and g["simulated"]
    assert g["latest"]["water_level_cm"] == 155 and g["latest"]["transport"] == "mqtt"
    assert g["gauge"]["watch_cm"] == 140 and len(g["series"]) == 6
    p = rows["pandoh"]
    assert not p["fresh"] and p["gauge_level"] is None
    assert {f["kind"] for f in p["findings"]} == {"stale", "battery"}
    assert {f["kind"] for f in rows["thunag"]["findings"]} == {"no_data"}
    assert board["readings_24h"] == 7 and board["by_transport"] == {"https": 4, "mqtt": 3}
    assert board["fresh_gauges"] == 1 and board["gauges"] == 5
    assert "device_id" in g["gauge"] and "note" not in g["gauge"]


# -- HTTP --------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    from Pukaar.main import app

    return TestClient(app)


def test_public_routes_need_no_sign_in(client):
    reg = client.get("/agents")
    assert reg.status_code == 200 and len(reg.json()["agents"]) == 5
    tr = client.get("/agents/traces?limit=3")
    assert tr.status_code == 200 and isinstance(tr.json(), list)
    assert client.get("/agents/traces?limit=50").status_code == 422
    sn = client.get("/sensors")
    assert sn.status_code == 200 and "readings_24h" in sn.json() and len(sn.json()["villages"]) == 5


def test_template_lists_the_routes_as_public_gets():
    from test_template_safety import RES

    events = RES["ApiFunction"]["Properties"]["Events"]
    paths = {(e["Properties"]["Path"], e["Properties"]["Method"]): e["Properties"].get("Auth", {}).get("Authorizer")
             for e in events.values()}
    for path in ("/agents", "/agents/traces", "/sensors"):
        assert paths[(path, "GET")] == "NONE"
