"""A gauge that goes silent while it rains is itself a Watch-level signal (Lachen 2023, Babai 2014).

risk_rules.silent_gauge_in_rain floors the level at Watch, never higher, never as a second source; the decision
engine reads the silence from the stored readings (services/gauge.silence) and the alert it raises tells the
officer. Simulated and not-installed gauges are silent by design: evidence only.
"""

from __future__ import annotations

from datetime import timedelta

from Pukaar.core import clock
from Pukaar.services import decision_engine as de
from Pukaar.services import gauge, risk_rules
from Pukaar.store.models import Reading, SensorReading

SILENT = {"device_id": "gauge-x", "installed": True, "simulated": False, "last_seen": "2026-07-01T00:00:00Z",
          "minutes_silent": 120.0, "silent_after_minutes": 30, "silent": True}


def _reading(mm, at="2026-07-01T02:00:00Z"):
    return Reading(village_id="thunag", at=at, rain_24h_mm=mm, discharge_peak=0.1, discharge_forecast=[])


def _assess(reading, silence, rain_obs=None, now=None):
    from datetime import datetime, timezone

    now = now or datetime(2026, 7, 1, 2, 0, tzinfo=timezone.utc)
    return risk_rules.assess(reading, None, [], now, gauge_silence=silence, rain_obs=rain_obs,
                             soil_modifier=False, rain_intensity_on=False)


def test_a_silent_gauge_in_moderate_rain_is_watch():
    a = _assess(_reading(20.0), SILENT)  # 20 mm: IMD "moderate", under the 64.5 mm Watch band
    assert a.level == "watch" and "gauge_silent_in_rain:watch" in a.rules_fired
    ev = next(e for e in a.evidence if e["kind"] == "gauge_silent")
    assert ev["counted"] and ev["raining"]["basis"] == "forecast" and ev["minutes_silent"] == 120.0


def test_no_rain_means_no_level_but_the_silence_is_still_evidence():
    a = _assess(_reading(5.0), SILENT)
    assert a.level == "normal" and not any(r.startswith("gauge_silent") for r in a.rules_fired)
    ev = next(e for e in a.evidence if e["kind"] == "gauge_silent")
    assert ev["raining"] is None and not ev["counted"]


def test_a_reporting_gauge_changes_nothing():
    a = _assess(_reading(20.0), {**SILENT, "silent": False, "minutes_silent": 3.0})
    assert a.level == "normal" and not any(e["kind"] == "gauge_silent" for e in a.evidence)


def test_simulated_or_not_installed_gauges_are_evidence_only():
    sim = _assess(_reading(20.0), {**SILENT, "simulated": True})
    assert sim.level == "normal" and "gauge_silent_in_rain_ignored:simulated" in sim.rules_fired
    off = _assess(_reading(20.0), {**SILENT, "installed": False})
    assert off.level == "normal" and "gauge_silent_in_rain_ignored:not_installed" in off.rules_fired


def test_silence_is_never_a_second_source_and_never_above_watch():
    # Heavy rain alone is Watch; a silent gauge adds a gap, not water: no "two sources agree".
    a = _assess(_reading(70.0), SILENT)
    assert a.level == "watch" and "two_sources_agree:+1" not in a.rules_fired
    assert "gauge_silent_in_rain:watch" in a.rules_fired
    # Very heavy rain stays at its own Warning.
    assert _assess(_reading(120.0), SILENT).level == "warning"


def test_observed_rain_counts_as_raining():
    obs = {"devices": [{"device_id": "rain-1", "fresh": True, "eval_level": "watch", "confirmed_level": "normal",
                        "quality": "good", "stuck": False}]}
    a = _assess(_reading(0.0), SILENT, rain_obs=obs)
    assert a.level == "watch" and "gauge_silent_in_rain:watch" in a.rules_fired
    ev = next(e for e in a.evidence if e["kind"] == "gauge_silent")
    assert ev["raining"]["basis"] == "observed"


def _install(repo, village_id):
    v = repo.get_village(village_id)
    v = v.model_copy(update={"gauge": v.gauge.model_copy(update={"installed": True, "device_id": "gauge-thunag-1"})})
    repo.put_village(v)
    return v


def test_the_sweep_raises_watch_and_an_alert_when_the_installed_gauge_goes_silent_in_rain(repo, frozen, workflow):
    v = _install(repo, "thunag")
    now = frozen["now"]
    last = now - timedelta(hours=2)
    repo.put_sensor_reading(SensorReading(village_id=v.id, device_id="gauge-thunag-1", at=clock.iso(last),
                                          received_at=clock.iso(last), water_level_cm=40.0))
    info = gauge.silence(repo, v, now)
    assert info["silent"] and info["installed"] and info["minutes_silent"] == 120.0
    res = de.recompute_village(repo, v, now=now, reading=_reading(20.0, clock.iso(now)), workflow=workflow)
    assert res.rose and res.level == "watch" and res.alert_id
    alert = repo.get_alert(res.alert_id)
    assert "gauge_silent_in_rain:watch" in alert.decision_trace["rules_fired"]
    assert any(e["kind"] == "gauge_silent" and e["counted"] for e in alert.decision_trace["evidence"])
    assert workflow.started == [res.alert_id]  # the officer is asked: the silence is an officer alert


def test_a_fresh_reading_means_not_silent(repo, frozen):
    v = _install(repo, "thunag")
    now = frozen["now"]
    repo.put_sensor_reading(SensorReading(village_id=v.id, device_id="gauge-thunag-1", at=clock.iso(now),
                                          received_at=clock.iso(now), water_level_cm=40.0))
    assert gauge.silence(repo, v, now)["silent"] is False
    assert gauge.silence(repo, v.model_copy(update={"gauge": None}), now) is None


def test_a_replay_never_reads_the_live_gauge(repo, frozen):
    # The replay works on its own copy and never mixes live sensors in (decision_engine passes no silence).
    v = _install(repo, "thunag")
    res = de.recompute_village(repo, v, now=frozen["now"], reading=_reading(20.0), replay=True)
    assert res.skipped  # no replay running: nothing changed
