"""Virtual staff gauges (CrowdWater pattern): set-up and storage, Cedar, the villager's mark on a
report, officer confirmation with audit, and what a reading may do to the level."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import NOW, FakeWorkflow
from fastapi.testclient import TestClient
from Pukaar.core import clock
from Pukaar.policy.guard import SYSTEM, Principal, evaluate
from Pukaar.services import risk_rules as rr
from Pukaar.services import staff_gauge as sg
from Pukaar.services import storage
from Pukaar.store.models import Reading, Report, StaffReading, Thresholds

OFFICER = Principal("officer1", "officer")
PRADHAN = Principal("pradhan_thunag", "pradhan", ["thunag"])
AGENT = Principal("drafting", "agent")
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"
TH = Thresholds(watch=10.0, warning=20.0, critical=30.0)


def class_meta(**over):
    """CrowdWater-style classes -5..+5 drawn between two taps (bottom y=0.8, top y=0.2)."""
    marks = [{"label": f"{v:+d}" if v else "0", "value": v, "x": 0.5, "y": round(0.8 - (v + 5) * 0.06, 4)}
             for v in range(-5, 6)]
    meta = {"name": "Big rock by the khad", "name_hi": "खड्ड के पास बड़ा पत्थर", "where": "Stand on the bridge, face upstream",
            "scale_top": {"x": 0.5, "y": 0.2}, "scale_bottom": {"x": 0.5, "y": 0.8}, "unit": "class",
            "marks": marks, "watch_at": 1, "warning_at": 3, "critical_at": 5}
    meta.update(over)
    return meta


def make_gauge(repo, village="thunag", **over):
    return sg.create(repo, repo.get_village(village), photo=(JPEG, "image/jpeg"), fields=class_meta(**over),
                     actor="officer1", role="officer")


def staff_report(rid, *, status="confirmed", level="warning", mark="+3", value=3.0, state="unverified",
                 minutes_old=10, rtype="water_rising", severity="medium"):
    sr = StaffReading(gauge_id="stg_1", gauge_name="Rock", mark=mark, value=value, chosen_at=clock.iso(NOW),
                      status=status, confirmed_mark=mark if status == "confirmed" else None,
                      confirmed_value=value if status == "confirmed" else None,
                      confirmed_level=level if status == "confirmed" else None,
                      confirmed_by="officer1" if status == "confirmed" else None)
    created = NOW - timedelta(minutes=minutes_old)
    r = Report(id=rid, village_id="thunag", created_at=clock.iso(created), report_type=rtype, severity=severity,
               state=state, staff_reading=sr)
    return r, created


def quiet():
    return Reading(village_id="thunag", at=clock.iso(NOW), rain_24h_mm=0, discharge_peak=1)


# -- set-up, validation and storage ------------------------------------------------
def test_create_stores_photo_in_s3_and_gauge_under_the_village(repo, frozen):
    g = make_gauge(repo)
    assert g.id.startswith("stg") and g.photo_key == f"staffgauges/thunag/{g.id}.jpg"
    assert storage.get_bytes(g.photo_key) == (JPEG, "image/jpeg")
    item = repo.t.get_item(Key={"pk": "VILLAGE#thunag", "sk": f"STAFFGAUGE#{g.id}"})["Item"]
    assert item["name"] == "Big rock by the khad" and len(item["marks"]) == 11
    assert [x.id for x in repo.list_staff_gauges("thunag")] == [g.id]
    view = sg.view(g)
    assert "photo_key" not in view and view["photo_url"].endswith(f"{g.id}.jpg")
    assert "Bedrock" in view["vision_note_en"]
    audit = repo.list_audit(clock.iso(NOW)[:10], f"staffgauge:thunag:{g.id}")
    assert audit and audit[0].action == "staff_gauge_create" and "11 marks -5..+5" in audit[0].reason


@pytest.mark.parametrize("over, why", [
    ({"scale_top": {"x": 0.5, "y": 0.5}, "scale_bottom": {"x": 0.5, "y": 0.52}}, "further apart"),
    ({"scale_top": {"x": 0.5, "y": 0.8}, "scale_bottom": {"x": 0.5, "y": 0.2}}, "above its bottom"),
    ({"marks": [{"label": "0", "value": 0, "x": 0.5, "y": 0.5}]}, "between"),
    ({"warning_at": 0.5}, "one of the marks"),
    ({"watch_at": 3, "warning_at": 1}, "must rise"),
    ({"unit": "cm"}, "height in cm"),
])
def test_bad_scales_are_refused_in_both_languages(repo, frozen, over, why):
    with pytest.raises(sg.StaffGaugeError) as exc:
        make_gauge(repo, **over)
    assert why in exc.value.en and exc.value.hi != exc.value.en


def test_marks_upside_down_are_refused(repo, frozen):
    meta = class_meta()
    meta["marks"][0]["y"], meta["marks"][-1]["y"] = meta["marks"][-1]["y"], meta["marks"][0]["y"]
    with pytest.raises(sg.StaffGaugeError, match="higher in the photo"):
        sg.create(repo, repo.get_village("thunag"), photo=(JPEG, "image/jpeg"), fields=meta, actor="o", role="officer")


def test_cm_scale_and_level_for(repo, frozen):
    marks = [{"label": f"{h} cm", "value": h, "height_cm": h, "x": 0.4, "y": round(0.9 - h / 250, 3)} for h in (0, 50, 100, 150, 200)]
    g = make_gauge(repo, unit="cm", marks=marks, watch_at=100, warning_at=150, critical_at=None)
    assert [sg.level_for(g, v) for v in (0, 50, 100, 150, 200)] == ["normal", "normal", "watch", "warning", "warning"]
    assert sg.mark_for(g, 150).height_cm == 150
    with pytest.raises(sg.StaffGaugeError):
        sg.mark_for(g, 75)


def test_update_changes_thresholds_and_retires_with_audit(repo, frozen):
    g = make_gauge(repo)
    g2 = sg.update(repo, g, {"warning_at": 2, "watch_at": 0}, actor="officer1", role="officer")
    assert (g2.watch_at, g2.warning_at, g2.updated_by) == (0, 2, "officer1")
    reason = repo.list_audit(clock.iso(NOW)[:10], f"staffgauge:thunag:{g.id}")[0].reason
    assert "watch 1, warning 3, critical 5 -> watch 0, warning 2, critical 5" in reason
    sg.update(repo, g2, {"active": False}, actor="officer1", role="officer")
    assert sg.active(repo, "thunag") == [] and len(repo.list_staff_gauges("thunag")) == 1


# -- Cedar ---------------------------------------------------------------------------
def test_cedar_staff_gauge_policies():
    own, other = {"village_id": "thunag"}, {"village_id": "gohar"}
    assert evaluate(OFFICER, "manage_staff_gauge", "village", "gohar", other).allowed
    assert evaluate(PRADHAN, "manage_staff_gauge", "village", "thunag", own).allowed
    assert not evaluate(PRADHAN, "manage_staff_gauge", "village", "gohar", other).allowed
    assert not evaluate(PRADHAN, "manage_staff_gauge", "village", "thunag", {"village_id": ""}).allowed
    assert evaluate(OFFICER, "confirm_staff_reading", "report", "rpt_1", own).allowed
    assert not evaluate(PRADHAN, "confirm_staff_reading", "report", "rpt_1", own).allowed
    for action in ("manage_staff_gauge", "confirm_staff_reading"):
        assert not evaluate(AGENT, action, "village", "thunag", own).allowed
        assert not evaluate(SYSTEM, action, "village", "thunag", own).allowed


# -- what a reading may do to the level -----------------------------------------------
def test_unconfirmed_mark_is_evidence_only():
    r = staff_report("rpt_a", status="unconfirmed")
    a = rr.assess(quiet(), TH, [r], NOW)
    assert a.level == "normal" and a.staff_level == "normal"
    ev = next(e for e in a.evidence if e["kind"] == "staff_gauge")
    assert ev["status"] == "unconfirmed" and ev["mark"] == "+3" and ev["level"] is None
    assert not any(x.startswith("staff_gauge") for x in a.rules_fired)


def test_confirmed_mark_at_threshold_raises_alone():
    a = rr.assess(quiet(), TH, [staff_report("rpt_a")], NOW)
    assert a.staff_level == "warning" and a.level == "warning"
    assert "staff_gauge:+3:warning" in a.rules_fired and "staff_gauge_confirmed:warning" in a.rules_fired
    ev = next(e for e in a.evidence if e["kind"] == "staff_gauge")
    assert ev["confirmed_by"] == "officer1" and ev["level"] == "warning"


def test_confirmed_below_every_mark_changes_nothing():
    a = rr.assess(quiet(), TH, [staff_report("rpt_a", level="normal", mark="0", value=0)], NOW)
    assert a.level == "normal" and any(e["kind"] == "staff_gauge" for e in a.evidence)


def test_confirmed_reading_corroborates_another_verified_report():
    staff_r = staff_report("rpt_a", level="watch", mark="+1", value=1)
    other = Report(id="rpt_b", village_id="thunag", created_at=clock.iso(NOW - timedelta(minutes=5)),
                   report_type="water_rising", severity="medium", state="verified")
    a = rr.assess(quiet(), TH, [staff_r, (other, NOW - timedelta(minutes=5))], NOW)
    assert "two_sources_agree:+1" in a.rules_fired and a.level == "warning"


def test_a_photo_never_counts_twice():
    # Its own report is verified at watch and its reading confirmed at watch: one observation, no +1.
    r = staff_report("rpt_a", level="watch", mark="+1", value=1, state="verified")
    a = rr.assess(quiet(), TH, [r], NOW)
    assert a.level == "watch" and "two_sources_agree:+1" not in a.rules_fired


def test_old_confirmed_reading_fades_like_a_report():
    a = rr.assess(quiet(), TH, [staff_report("rpt_a", minutes_old=150)], NOW)  # weight 0.25
    assert a.staff_level == "watch"
    gone = rr.assess(quiet(), TH, [staff_report("rpt_a", minutes_old=200)], NOW)
    assert gone.staff_level == "normal" and not any(e["kind"] == "staff_gauge" for e in gone.evidence)


# -- HTTP: set-up, villager mark, officer confirmation --------------------------------
@pytest.fixture()
def client(repo, monkeypatch):
    from Pukaar.api import auth
    from Pukaar.api.routers import gauges, public
    from Pukaar.api.routers import reports as reports_router
    from Pukaar.main import app

    for mod in (auth, public, gauges, reports_router):
        monkeypatch.setattr(mod, "get_repo", lambda: repo)
    wf = FakeWorkflow()
    monkeypatch.setattr(gauges, "get_workflow", lambda: wf)
    monkeypatch.setattr(reports_router.worker, "dispatch", lambda event: None)
    c = TestClient(app)
    c.workflow = wf  # type: ignore[attr-defined]
    return c


def token(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def post_gauge(client, village, user, meta=None):
    import json

    return client.post(f"/villages/{village}/staff-gauges", data={"meta": json.dumps(meta or class_meta())},
                       files={"photo": ("rock.jpg", JPEG, "image/jpeg")},
                       headers=token(client, user) if user else {})


def test_routes_enforce_who_may_set_up(client, repo, frozen):
    assert post_gauge(client, "thunag", None).status_code == 401
    denied = post_gauge(client, "gohar", "pradhan_thunag")
    assert denied.status_code == 403 and "pradhan of this village" in denied.json()["detail"]["reason"]
    own = post_gauge(client, "thunag", "pradhan_thunag")
    assert own.status_code == 200, own.text
    assert post_gauge(client, "gohar", "officer1").status_code == 200
    bad = post_gauge(client, "thunag", "officer1", class_meta(watch_at=0.5))
    assert bad.status_code == 400 and bad.json()["detail"]["message_hi"]
    listed = client.get("/villages/thunag/staff-gauges").json()  # public: the report page needs it
    assert [g["name"] for g in listed] == ["Big rock by the khad"] and listed[0]["marks"][0]["label"] == "-5"
    detail = client.get("/villages/thunag").json()["staff_gauges"]
    assert detail["gauges"][0]["id"] == own.json()["id"] and detail["readings"] == []
    gid = own.json()["id"]
    r = client.patch(f"/villages/thunag/staff-gauges/{gid}", json={"active": False}, headers=token(client, "pradhan_thunag"))
    assert r.status_code == 200 and client.get("/villages/thunag/staff-gauges").json() == []


def send_report(client, gid, mark, photo=True):
    files = {"photo": ("p.jpg", JPEG, "image/jpeg")} if photo else None
    data = {"village_id": "thunag", "text": "पानी बढ़ रहा है", "lat": "31.56", "lon": "77.165",
            "staff_gauge_id": gid, "staff_mark": str(mark)}
    return client.post("/reports", data=data, files=files)


def test_villager_mark_is_saved_and_officer_confirms_with_audit(client, repo, frozen):
    gid = post_gauge(client, "thunag", "officer1").json()["id"]
    assert send_report(client, gid, 7).status_code == 400  # not a mark on this gauge
    nophoto = send_report(client, gid, 3, photo=False)
    assert nophoto.status_code == 400 and "photo" in nophoto.json()["detail"]["message_en"]
    r = send_report(client, gid, 3)
    assert r.status_code == 200, r.text
    rep = r.json()["report"]
    assert rep["staff_reading"]["mark"] == "+3" and rep["staff_reading"]["status"] == "unconfirmed"
    assert repo.get_village("thunag").level == "normal"

    url = f"/reports/{rep['id']}/staff-reading"
    assert client.post(url, json={"value": 3}).status_code == 401
    assert client.post(url, json={"value": 3}, headers=token(client, "pradhan_thunag")).status_code == 403
    assert client.post(url, json={"value": 9}, headers=token(client, "officer1")).status_code == 400
    ok = client.post(url, json={"value": 4}, headers=token(client, "officer1"))  # adjusted from +3
    assert ok.status_code == 200, ok.text
    sr = ok.json()["staff_reading"]
    assert (sr["status"], sr["confirmed_mark"], sr["confirmed_level"], sr["confirmed_by"]) == ("confirmed", "+4", "warning", "officer1")
    assert sr["mark"] == "+3"  # the villager's own choice is kept
    audit = repo.list_audit(clock.iso(NOW)[:10], f"report:{rep['id']}")
    row = next(a for a in audit if a.action == "staff_reading_confirm")
    assert row.reason == "villager chose +3, unconfirmed -> confirmed +4 (warning) (adjusted from the villager's mark)"
    v = repo.get_village("thunag")
    assert v.level == "warning" and client.workflow.started  # the confirmed reading raised the level
    alert = repo.get_alert(v.open_alert_id)
    assert "staff_gauge_confirmed:warning" in alert.decision_trace["rules_fired"]
    readings = client.get("/villages/thunag").json()["staff_gauges"]["readings"]
    assert readings[0]["mark"] == "+4" and readings[0]["status"] == "confirmed" and "confirmed_by" not in readings[0]

    bad = client.post(url, json={"unreadable": True}, headers=token(client, "officer1"))
    assert bad.json()["staff_reading"]["status"] == "unreadable"
    assert any(a.reason.endswith("-> unreadable") for a in repo.list_audit(clock.iso(NOW)[:10], f"report:{rep['id']}"))
