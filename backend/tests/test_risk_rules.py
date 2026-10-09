from datetime import timedelta

from conftest import NOW

from Pukaar.services import risk_rules as rr
from Pukaar.store.models import Reading, Report, Thresholds

TH = Thresholds(watch=10.0, warning=20.0, critical=30.0)


def reading(rain=None, peak=None):
    return Reading(village_id="thunag", at="2026-07-01T02:00:00Z", rain_24h_mm=rain, discharge_peak=peak)


def report(state="verified_auto", severity="high", type_="water_rising", minutes=10):
    created = NOW - timedelta(minutes=minutes)
    r = Report(id=f"r{minutes}{state}", village_id="thunag", created_at=created.isoformat(), state=state,
               severity=severity, report_type=type_)
    return r, created


def test_imd_rain_bands():
    assert rr.rain_level(64.4) == "normal"
    assert rr.rain_level(64.5) == "watch"
    assert rr.rain_level(115.6) == "warning"
    assert rr.rain_level(204.5) == "critical"
    assert rr.rain_level(None) == "normal"


def test_river_percentile_levels():
    assert rr.river_level(9.9, TH) == "normal"
    assert rr.river_level(10, TH) == "watch"
    assert rr.river_level(25, TH) == "warning"
    assert rr.river_level(31, TH) == "critical"
    assert rr.river_level(31, None) == "normal"


def test_village_level_is_higher_of_rain_and_river():
    a = rr.assess(reading(rain=120, peak=11), TH, [], NOW)
    assert (a.rain_level, a.river_level) == ("warning", "watch")
    # two independent sources at watch or above: one level up
    assert a.level == "critical"
    assert "two_sources_agree:+1" in a.rules_fired


def test_unverified_reports_never_raise_a_level():
    a = rr.assess(reading(rain=0, peak=1), TH, [report(state="unverified", severity="critical", type_="people_trapped")], NOW)
    assert a.level == "normal"
    assert "data_disagrees" in a.rules_fired


def test_verified_impact_report_floors_at_warning():
    a = rr.assess(reading(rain=0, peak=1), TH, [report(severity="medium", type_="road_cut")], NOW)
    assert a.level == "warning"
    assert "verified_impact_report:floor_warning" in a.rules_fired


def test_report_weight_fades_over_three_hours():
    assert rr.report_weight(NOW - timedelta(minutes=30), NOW) == 1.0
    assert abs(rr.report_weight(NOW - timedelta(hours=2), NOW) - 0.5) < 1e-9
    assert rr.report_weight(NOW - timedelta(hours=3), NOW) == 0.0
    old = rr.assess(reading(), TH, [report(severity="critical", type_="water_rising", minutes=200)], NOW)
    assert old.level == "normal"


def test_hysteresis_rises_at_once_and_drops_after_three_calm_sweeps():
    assert rr.apply_hysteresis("normal", 0, "critical") == ("critical", 0, True)
    level, calm = "critical", 0
    for expected_calm in (1, 2):
        level, calm, rose = rr.apply_hysteresis(level, calm, "normal")
        assert (level, calm, rose) == ("critical", expected_calm, False)
    level, calm, _ = rr.apply_hysteresis(level, calm, "normal")
    assert (level, calm) == ("warning", 0)  # one level at a time


def test_hysteresis_calm_count_resets_on_equal_level():
    assert rr.apply_hysteresis("warning", 2, "warning") == ("warning", 0, False)


def test_trace_evidence_lists_reading_and_reports():
    a = rr.assess(reading(rain=70, peak=5), TH, [report()], NOW)
    kinds = [e["kind"] for e in a.evidence]
    assert kinds == ["reading", "report"]
    assert a.evidence[0]["thresholds"]["warning"] == 20.0
