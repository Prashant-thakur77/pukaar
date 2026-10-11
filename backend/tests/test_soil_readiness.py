"""Soil-moisture modifier (feature 15) and two-stage readiness with checklists (feature 16)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import NOW
from fastapi.testclient import TestClient
from Pukaar.services import checklist, readiness, soil
from Pukaar.services import risk_rules as rr
from Pukaar.store.models import Reading, SoilRange, Thresholds

TH = Thresholds(watch=10.0, warning=20.0, critical=30.0)
RANGE = SoilRange(dry=0.20, wet=0.40, source="test")


def reading(rain=None, sm=None, peak=None, outlook=None, at="2026-07-01T02:00:00Z"):
    return Reading(village_id="thunag", at=at, rain_24h_mm=rain, discharge_peak=peak, soil_moisture_root=sm,
                   discharge_outlook=outlook or [])


def sm_for(s: float) -> float:
    """Soil moisture that gives saturation s on RANGE."""
    return RANGE.dry + s * (RANGE.wet - RANGE.dry)


# -- soil math and bounds ----------------------------------------------------
def test_saturation_is_clipped_and_uses_default_range_when_uncalibrated():
    assert soil.saturation(0.30, RANGE) == 0.5
    assert soil.saturation(0.10, RANGE) == 0.0
    assert soil.saturation(0.55, RANGE) == 1.0
    assert soil.saturation(None, RANGE) is None
    assert soil.saturation(0.30, None) == 0.5  # default 0.15..0.45
    assert soil.DEFAULT_RANGE.dry == 0.15 and soil.DEFAULT_RANGE.wet == 0.45
    assert soil.saturation(0.3, SoilRange(dry=0.3, wet=0.3)) is None


def test_band_factor_starts_at_0_8_and_never_goes_below_70_percent():
    assert soil.band_factor(None) == 1.0
    assert soil.band_factor(0.79) == 1.0
    assert soil.band_factor(0.8) == 1.0
    assert soil.band_factor(0.9) == pytest.approx(0.85)
    assert soil.band_factor(0.92) == pytest.approx(0.82)
    assert soil.band_factor(1.0) == pytest.approx(0.7)
    assert soil.band_factor(1.5) == pytest.approx(0.7)
    assert rr.scaled_bands(0.1) == rr.scaled_bands(0.7)
    assert dict(rr.scaled_bands(0.7))["watch"] == pytest.approx(45.2, abs=0.06)
    assert rr.scaled_bands(1.0) == rr.RAIN_BANDS


def test_root_zone_is_the_mean_of_the_two_deep_layers():
    h = {"soil_moisture_9_to_27cm": [0.30, None], "soil_moisture_27_to_81cm": [0.40, 0.4]}
    assert soil.root_zone(h, 0) == pytest.approx(0.35)
    assert soil.root_zone(h, 1) is None
    assert soil.root_zone({}, 0) is None


def test_flag_off_changes_nothing():
    wet = reading(rain=55.0, sm=sm_for(1.0))
    off = rr.assess(wet, TH, [], NOW, soil=RANGE, soil_modifier=False)
    plain = rr.assess(reading(rain=55.0), TH, [], NOW, soil=RANGE, soil_modifier=False)
    assert off.level == plain.level == "normal"
    assert not any(r.startswith("soil_saturated") for r in off.rules_fired)
    ev = next(e for e in off.evidence if e["kind"] == "soil")
    assert ev["state"] == "off" and ev["factor"] == 1.0 and ev["factor_if_on"] == pytest.approx(0.7)
    reading_ev = next(e for e in off.evidence if e["kind"] == "reading")
    assert reading_ev["rain_bands_mm"] == reading_ev["rain_bands_imd_mm"]


def test_flag_on_lowers_rain_bands_and_records_the_rule():
    a = rr.assess(reading(rain=55.0, sm=sm_for(0.92)), TH, [], NOW, soil=RANGE, soil_modifier=True)
    assert a.rain_level == "watch" and a.level == "watch"
    assert "soil_saturated:S=0.92:bands x0.82" in a.rules_fired
    assert "rain_24h>=52.9mm:watch" in a.rules_fired
    ev = next(e for e in a.evidence if e["kind"] == "reading")
    assert ev["rain_bands_mm"]["watch"] == pytest.approx(52.9) and ev["rain_bands_imd_mm"]["watch"] == 64.5


def test_soil_never_raises_a_level_by_itself_or_below_the_floor():
    dry_day = rr.assess(reading(rain=0.0, sm=sm_for(1.0)), TH, [], NOW, soil=RANGE, soil_modifier=True)
    assert dry_day.level == "normal" and dry_day.rain_level == "normal"
    floor = rr.assess(reading(rain=45.0, sm=0.99), TH, [], NOW, soil=RANGE, soil_modifier=True)
    assert floor.rain_level == "normal"  # 45 mm < 70% of 64.5 mm
    unsaturated = rr.assess(reading(rain=60.0, sm=sm_for(0.79)), TH, [], NOW, soil=RANGE, soil_modifier=True)
    assert unsaturated.level == "normal" and not any(r.startswith("soil") for r in unsaturated.rules_fired)


def test_soil_is_not_an_independent_source():
    # River at Watch and rain lowered to Watch: two_sources_agree still needs real rain to reach the band.
    a = rr.assess(reading(rain=10.0, sm=sm_for(1.0), peak=11), TH, [], NOW, soil=RANGE, soil_modifier=True)
    assert a.level == "watch" and "two_sources_agree:+1" not in a.rules_fired


def test_setting_default_drives_the_modifier(monkeypatch):
    from Pukaar.core import config

    wet = reading(rain=55.0, sm=sm_for(1.0))
    monkeypatch.setattr(config, "get_settings", lambda: type("S", (), {"soil_modifier_enabled": True})())
    assert rr.assess(wet, TH, [], NOW, soil=RANGE).level == "watch"
    monkeypatch.setattr(config, "get_settings", lambda: type("S", (), {"soil_modifier_enabled": False})())
    assert rr.assess(wet, TH, [], NOW, soil=RANGE).level == "normal"


def test_replay_reading_carries_archived_soil_and_outlook():
    from datetime import datetime, timezone

    from Pukaar.scripts.backtest import villages_from_files
    from Pukaar.services import external_data

    v = next(x for x in villages_from_files() if x.id == "thunag")
    assert v.soil is not None and v.soil.dry < v.soil.wet
    r = external_data.replay_reading("himachal_2023_07", v, datetime(2023, 7, 9, 0, tzinfo=timezone.utc))
    assert r is not None and r.soil_moisture_root is not None and 0.2 < r.soil_moisture_root < 0.6
    assert r.discharge_outlook and r.discharge_outlook[0]["date"] == "2023-07-09"
    assert len(r.discharge_outlook) <= external_data.OUTLOOK_DAYS + 1


# -- readiness ------------------------------------------------------------------
def _days(values, start="2026-07-01"):
    from datetime import date

    d0 = date.fromisoformat(start)
    return [{"date": (d0 + timedelta(days=i)).isoformat(), "value": q} for i, q in enumerate(values)]


def test_readiness_get_ready_when_days_2_to_7_reach_watch():
    out = readiness.outlook(reading(outlook=_days([5, 6, 7, 12, 15, 9, 8, 7])), TH)
    assert out["state"] == "get_ready" and out["available"]
    assert out["horizon_days"] == 3 and out["peak_day"] == "2026-07-05"
    assert out["peak_vs_watch_ratio"] == 1.5
    assert out["source"].startswith("Open-Meteo flood API")


def test_readiness_ignores_days_0_and_1_and_beyond_7():
    # Today and tomorrow belong to the 24-hour levels; day 8 is beyond the outlook.
    out = readiness.outlook(reading(outlook=_days([50, 40, 5, 5, 5, 5, 5, 5, 99])), TH)
    assert out["state"] == "none" and out["peak_vs_watch_ratio"] == 0.5
    assert all(2 <= d["days_ahead"] <= 7 for d in out["days"])


def test_readiness_none_without_data():
    assert readiness.outlook(None, TH)["state"] == "none"
    assert readiness.outlook(reading(outlook=_days([20] * 8)), None)["available"] is False
    assert readiness.outlook(reading(outlook=[]), TH)["available"] is False


def test_readiness_never_changes_the_level(repo, frozen, workflow):
    from Pukaar.services.decision_engine import recompute_village

    v = repo.get_village("gohar")
    th = v.thresholds
    r = Reading(village_id="gohar", at="2026-07-01T02:00:00Z", rain_24h_mm=0.0, discharge_peak=th.watch * 0.5,
                discharge_outlook=_days([th.watch * 0.5] * 3 + [th.critical * 2] * 5))
    res = recompute_village(repo, v, now=NOW, reading=r, workflow=workflow)
    assert res.level == "normal" and res.alert_id is None and workflow.started == []


# -- checklist storage ------------------------------------------------------------
def test_checklist_seeded_and_tick_is_audited(repo, frozen):
    view = checklist.view(repo, "thunag")
    assert view["total"] == 7 and view["done"] == 0
    assert {i["item"] for i in view["items"]} == checklist.ITEM_IDS
    assert all(i["label_hi"] and i["label_en"] for i in view["items"])
    item = checklist.set_done(repo, "thunag", "drill_run", True, "pradhan_thunag", "pradhan")
    assert item.done and item.done_by == "pradhan_thunag" and item.done_at
    rows = repo.list_audit(NOW.date().isoformat(), "checklist:thunag:drill_run")
    assert rows and rows[0].action == "checklist_tick"
    checklist.seed(repo, "thunag")  # re-seeding never resets a tick
    assert checklist.view(repo, "thunag")["done"] == 1
    undone = checklist.set_done(repo, "thunag", "drill_run", False, "officer1", "officer")
    assert not undone.done and undone.done_by is None
    with pytest.raises(KeyError):
        checklist.set_done(repo, "thunag", "unknown", True, "officer1", "officer")


# -- API: auth and views ----------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    from Pukaar.main import app

    return TestClient(app)


def token(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_checklist_auth(client):
    url = "/villages/thunag/checklist/khad_watcher"
    assert client.post(url, json={"done": True}).status_code == 401  # public denied
    r = client.post(url, json={"done": True}, headers=token(client, "pradhan_thunag"))  # own pradhan
    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["item"] == "khad_watcher")
    assert item["done"] and item["done_by"] == "pradhan_thunag"
    other = client.post("/villages/gohar/checklist/khad_watcher", json={"done": True},
                        headers=token(client, "pradhan_thunag"))
    assert other.status_code == 403  # another village's pradhan
    assert "pradhan" in other.json()["detail"]["reason"]
    off = client.post(url, json={"done": False}, headers=token(client, "officer1"))  # officer, any village
    assert off.status_code == 200
    assert not next(i for i in off.json()["items"] if i["item"] == "khad_watcher")["done"]
    assert client.post("/villages/thunag/checklist/nope", json={"done": True},
                       headers=token(client, "officer1")).status_code == 404
    assert client.post("/villages/nowhere/checklist/khad_watcher", json={"done": True},
                       headers=token(client, "officer1")).status_code == 404


def test_views_include_soil_readiness_and_checklist(client):
    detail = client.get("/villages/thunag").json()
    assert detail["checklist"]["total"] == 7
    assert {"state", "horizon_days", "peak_day", "peak_vs_watch_ratio", "source"} <= set(detail["village"]["readiness"])
    assert detail["village"]["soil"]["dry"] < detail["village"]["soil"]["wet"]
    s = detail["soil"]
    assert {"moisture_root", "saturation", "factor", "enabled", "applied", "state", "dry", "wet"} <= set(s)
    listing = client.get("/villages").json()
    assert all("readiness" in v for v in listing)
