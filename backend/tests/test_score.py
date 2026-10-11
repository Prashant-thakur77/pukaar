"""Scoring and source ablation on a tiny synthetic scenario (no network, no data files)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from Pukaar.scripts import score
from Pukaar.store.models import Reading, Thresholds, Village

T0 = datetime(2030, 7, 1, tzinfo=timezone.utc)
HOURS = [T0 + timedelta(hours=i) for i in range(48)]
TH = Thresholds(watch=10, warning=20, critical=30, source="test")


def _village(vid: str) -> Village:
    return Village(id=vid, name=vid.title(), name_hi=vid, district="Test", lat=31.5, lon=77.0, thresholds=TH)


# rainy: heavy rain from hour 6, river quiet          -> rain hit, river miss, both hit
# riverine: river high from hour 10, rain quiet         -> rain miss, river hit, both hit
# quiet: rain at Warning band but nothing happened      -> false alarm for rain and both
# unknown: truth uncertain                              -> never scored
def _reading(vid: str, at: datetime) -> Reading:
    i = HOURS.index(at)
    rain, q = 5.0, 1.0
    if vid == "rainy" and i >= 6:
        rain = 80.0
    if vid == "riverine" and i >= 10:
        q = 15.0
    if vid in ("quiet", "unknown") and i >= 20:
        rain = 120.0
    return Reading(village_id=vid, at=at.isoformat(), rain_24h_mm=rain, discharge_peak=q)


TRUTH = {
    "rainy": {"truth": "event", "event_day": "2030-07-02"},
    "riverine": {"truth": "event", "event_day": "2030-07-02"},
    "quiet": {"truth": "no_event"},
    "unknown": {"truth": "uncertain"},
}


def _patch(monkeypatch, tmp_path):
    sc = {"title": "Synthetic", "start": HOURS[0].isoformat(), "end": HOURS[-1].isoformat(), "villages": {}}
    monkeypatch.setattr(score.external_data, "list_scenarios", lambda: ["synthetic"])
    monkeypatch.setattr(score.external_data, "load_scenario", lambda name: sc)
    monkeypatch.setattr(score.external_data, "replay_hours", lambda name: HOURS)
    monkeypatch.setattr(score.external_data, "replay_reading", lambda name, v, at: _reading(v.id, at))
    (tmp_path / "ground_truth.json").write_text(json.dumps({"scenarios": {"synthetic": TRUTH}}), encoding="utf-8")


def test_ablation_counts(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    villages = [_village(v) for v in TRUTH]
    result = score.run(tmp_path, villages)
    cfg = {c["key"]: c for c in result["scenarios"][0]["configs"]}
    assert (cfg["rain"]["hits"], cfg["rain"]["misses"], cfg["rain"]["false_alarms"]) == (1, 1, 1)
    assert (cfg["river"]["hits"], cfg["river"]["misses"], cfg["river"]["false_alarms"]) == (1, 1, 0)
    assert (cfg["both"]["hits"], cfg["both"]["misses"], cfg["both"]["false_alarms"]) == (2, 0, 1)
    assert all(c["scored"] == 3 for c in cfg.values())  # "unknown" is left out
    # rainy: Watch at hour 6 -> 18 h before the event day; riverine: hour 10 -> 14 h.
    assert cfg["rain"]["median_lead_hours"] == 18.0
    assert cfg["river"]["median_lead_hours"] == 14.0
    assert cfg["both"]["median_lead_hours"] == 16.0


def test_judge_watch_after_event_day_is_a_miss():
    first = {"watch": datetime(2030, 7, 3, 1, tzinfo=timezone.utc), "warning": None, "critical": None}
    assert score.judge(first, {"truth": "event", "event_day": "2030-07-02"})["result"] == "miss"
    first["watch"] = datetime(2030, 7, 2, 23, tzinfo=timezone.utc)
    j = score.judge(first, {"truth": "event", "event_day": "2030-07-02"})
    assert j == {"result": "hit", "lead_hours": -23.0}


def test_watch_only_is_not_a_false_alarm():
    first = {"watch": T0, "warning": None, "critical": None}
    assert score.judge(first, {"truth": "no_event"})["result"] == "correct_quiet"


def test_first_times_uses_production_hysteresis():
    # one hour at Warning, then calm: Warning is reached once and recorded.
    series = [(HOURS[0], "normal"), (HOURS[1], "warning"), (HOURS[2], "normal"), (HOURS[3], "normal")]
    first = score.first_times(series)
    assert first == {"watch": HOURS[1], "warning": HOURS[1], "critical": None}


def test_soil_configuration_is_scored_and_unchanged_without_soil(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    villages = [_village(v) for v in TRUTH]
    sc = score.run(tmp_path, villages)["scenarios"][0]
    cfg = {c["key"]: c for c in sc["configs"]}
    assert cfg["both_soil"]["label"] == "both + soil"
    same = lambda c: {k: v for k, v in c.items() if k not in {"key", "label"}}
    assert same(cfg["both_soil"]) == same(cfg["both"])
    assert len(sc["soil_effect"]) == len(villages)
    assert all(e["changed"] is False and e["hours_with_soil"] == 0 for e in sc["soil_effect"])


def test_soil_configuration_lowers_bands_on_saturated_ground(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    from Pukaar.store.models import SoilRange

    # 55 mm is below the IMD Watch band (64.5) but above it at full saturation (x0.7 = 45.2).
    monkeypatch.setattr(score.external_data, "replay_reading", lambda name, v, at: Reading(
        village_id=v.id, at=at.isoformat(), rain_24h_mm=55.0 if v.id == "rainy" else 5.0, discharge_peak=1.0,
        soil_moisture_root=0.45))
    villages = [_village(v).model_copy(update={"soil": SoilRange(dry=0.2, wet=0.4)}) for v in TRUTH]
    sc = score.run(tmp_path, villages)["scenarios"][0]
    cfg = {c["key"]: c for c in sc["configs"]}
    assert (cfg["both"]["hits"], cfg["both_soil"]["hits"]) == (0, 1)
    rainy = next(e for e in sc["soil_effect"] if e["village_id"] == "rainy")
    assert rainy["changed"] and rainy["max_saturation"] == 1.0 and rainy["both"]["first_watch"] is None
