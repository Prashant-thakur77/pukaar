"""The river trigger: return-period thresholds, the GloFAS ensemble probability, CAP certainty from it,
the once-a-day ensemble fetch, and official data that corroborates but never lowers a level."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import pytest

from conftest import NOW

from Pukaar.core import clock
from Pukaar.core.ids import new_id
from Pukaar.scripts import calibrate
from Pukaar.services import cap, external_data, fetch_cache
from Pukaar.services import risk_rules as rr
from Pukaar.store.models import Alert, Reading, Thresholds, Village

TH = Thresholds(watch=100.0, warning=150.0, critical=220.0, method="return_period",
                return_period_years={"watch": 2, "warning": 5, "critical": 20}, cell_lat=31.675, cell_lon=77.025,
                river="Beas", cell_verified=True)


@pytest.fixture(autouse=True)
def _fresh_cache():
    fetch_cache.clear()
    yield
    fetch_cache.clear()


def ensemble(*days: list[float], status: str = "ok") -> dict:
    return {"status": status, "members": len(days[0]) if days else 0, "run_date": "2026-07-01",
            "days": [{"date": f"2026-07-0{lead + 1}", "lead": lead, "values": sorted(v)} for lead, v in enumerate(days, 1)]}


def reading(*, today=50.0, peak=None, ens=None, rain=0.0, official=None) -> Reading:
    return Reading(village_id="pandoh", at="2026-07-01T02:00:00Z", rain_24h_mm=rain, discharge=today,
                   discharge_peak=peak if peak is not None else today, discharge_ensemble=ens, official=official or [])


# -- return periods -------------------------------------------------------------------
def test_gumbel_fit_recovers_a_known_distribution():
    mu, beta = 300.0, 60.0
    n = 400
    # A synthetic annual-maximum series: the Gumbel quantiles at the plotting positions (i - 0.35) / n.
    series = [mu - beta * math.log(-math.log((i - 0.35) / n)) for i in range(1, n + 1)]
    fit_mu, fit_beta = calibrate.gumbel_fit(series)
    assert fit_mu == pytest.approx(mu, rel=0.01) and fit_beta == pytest.approx(beta, rel=0.02)
    rp = calibrate.return_period_thresholds(series)
    for name, years in (("watch", 2), ("warning", 5), ("critical", 20)):
        exact = mu - beta * math.log(-math.log(1 - 1 / years))
        assert rp[name] == pytest.approx(exact, rel=0.01)
    assert rp["watch"] < rp["warning"] < rp["critical"]
    assert rp["return_period_years"] == {"watch": 2, "warning": 5, "critical": 20}


def test_return_level_formula_and_annual_maxima():
    # The 2-year flood of a Gumbel is mu - beta * ln(ln 2).
    assert calibrate.return_level(10.0, 2.0, 2) == pytest.approx(10.0 - 2.0 * math.log(math.log(2)))
    days = [(f"2001-{m:02d}-01", float(m)) for m in range(1, 13)] + [("2002-07-01", 99.0)]
    assert calibrate.annual_maxima(days, min_days=10) == [(2001, 12.0)]  # 2002 has too few days


def test_gumbel_fit_refuses_short_or_flat_series():
    with pytest.raises(ValueError):
        calibrate.gumbel_fit([1.0] * 5)
    with pytest.raises(ValueError):
        calibrate.gumbel_fit([2.0] * 20)


def test_days_and_episodes_at_or_above_use_the_three_day_look_ahead():
    pairs = [(f"2020-07-{d:02d}", q) for d, q in enumerate([1, 1, 1, 1, 5, 1, 1, 1, 1, 1, 6, 1], 1)]
    out = calibrate.days_at_or_above(pairs, 5.0, lookahead=3)
    # Day 5 is seen from day 2 (3 days ahead) and held to day 5; day 11 from day 8 to day 11.
    assert out == {"days": {"2020": 8}, "episodes": {"2020": 2}}


def test_cell_search_lists_cells_within_the_radius_nearest_first():
    cells = calibrate.cell_centres(31.83364, 76.50539, radius_km=7.0)
    assert cells and all(km <= 7.0 for _, _, km in cells)
    assert [c[2] for c in cells] == sorted(c[2] for c in cells)
    assert (31.825, 76.475) in [(lat, lon) for lat, lon, _ in cells]  # the Beas cell at Sujanpur
    pick = calibrate.suggest_cell([{"lat": 1, "lon": 1, "mean": 0.8}, {"lat": 2, "lon": 2, "mean": 232.1},
                                   {"lat": 3, "lon": 3, "mean": None}])
    assert pick["mean"] == 232.1


# -- ensemble probability -------------------------------------------------------------
def test_exceedance_probability_is_the_share_of_members_per_lead_day():
    probs = rr.exceedance_probabilities(ensemble([90] * 6 + [120] * 3 + [230], [10] * 10)["days"], TH)
    assert probs[0] == {"date": "2026-07-02", "lead": 1, "members": 10,
                        "p": {"watch": 0.4, "warning": 0.1, "critical": 0.1}}
    assert probs[1]["p"] == {"watch": 0.0, "warning": 0.0, "critical": 0.0}
    # Missing member values are left out of both counts; lead days beyond 3 are ignored.
    days = [{"date": "d", "lead": 1, "values": [200, None, 50]}, {"date": "e", "lead": 4, "values": [500]}]
    assert rr.exceedance_probabilities(days, TH) == [
        {"date": "d", "lead": 1, "members": 2, "p": {"watch": 0.5, "warning": 0.5, "critical": 0.0}}]


@pytest.mark.parametrize(("above_warning", "level"), [(2, "watch"), (3, "warning"), (4, "warning")])
def test_a_level_is_raised_when_p_reaches_0_3(above_warning, level):
    # Every member above Watch; `above_warning` of 10 above Warning on lead day 2.
    ens = ensemble([110] * 10, [110] * (10 - above_warning) + [160] * above_warning, [105] * 10)
    info = rr.river_assessment(reading(ens=ens), TH, p_min=0.3, use_ensemble=True)
    assert info["mode"] == "ensemble" and info["level"] == level
    assert info["p_at_level"] == (1.0 if level == "watch" else above_warning / 10)


def test_p_min_is_configurable_and_read_from_settings(monkeypatch):
    ens = ensemble([160] * 4 + [110] * 6)
    assert rr.river_assessment(reading(ens=ens), TH, p_min=0.3, use_ensemble=True)["level"] == "warning"
    assert rr.river_assessment(reading(ens=ens), TH, p_min=0.5, use_ensemble=True)["level"] == "watch"
    monkeypatch.setenv("PUKAAR_RIVER_ENSEMBLE_P_MIN", "0.5")
    from Pukaar.core.config import get_settings

    get_settings.cache_clear()
    try:
        assert rr.river_assessment(reading(ens=ens), TH)["level"] == "watch"
    finally:
        monkeypatch.delenv("PUKAAR_RIVER_ENSEMBLE_P_MIN")
        get_settings.cache_clear()


def test_a_deterministic_crossing_the_ensemble_does_not_back_raises_nothing():
    # The single forecast peaks above Warning, but only 1 member in 10 does.
    ens = ensemble([60] * 9 + [160])
    a = rr.assess(reading(today=60, peak=160, ens=ens), TH, [], NOW, ensemble_p_min=0.3)
    assert a.river_level == "normal" and a.level == "normal"
    river = next(e for e in a.evidence if e["kind"] == "river")
    assert river["deterministic_level"] == "warning" and river["p_max"]["warning"] == 0.1


def test_todays_discharge_counts_even_when_the_ensemble_is_calm():
    a = rr.assess(reading(today=155, ens=ensemble([60] * 10)), TH, [], NOW, ensemble_p_min=0.3)
    assert a.river_level == "warning" and "discharge_today>=150.0:warning" in a.rules_fired
    assert next(e for e in a.evidence if e["kind"] == "river")["p_at_level"] is None


def test_the_trace_carries_p_and_the_rule_names_it():
    a = rr.assess(reading(ens=ensemble([160] * 5 + [110] * 5)), TH, [], NOW, ensemble_p_min=0.3)
    assert a.river_level == "warning"
    assert "river_ensemble:P(warning)=0.5>=0.3:warning" in a.rules_fired
    river = next(e for e in a.evidence if e["kind"] == "river")
    assert river["mode"] == "ensemble" and river["p_at_level"] == 0.5 and river["members"] == 10
    assert river["cell"] == {"lat": 31.675, "lon": 77.025} and river["cell_verified"] is True
    assert river["lead_days"][0]["p"]["warning"] == 0.5


def test_without_an_ensemble_the_peak_is_used_and_an_outage_is_named():
    a = rr.assess(reading(today=60, peak=160, ens={"status": "unavailable", "error": "timeout"}), TH, [], NOW)
    assert a.river_level == "warning" and "river_ensemble_unavailable" in a.rules_fired
    assert next(e for e in a.evidence if e["kind"] == "river")["mode"] == "deterministic"
    replay = rr.assess(reading(today=60, peak=105), TH, [], NOW)  # replays carry no ensemble
    assert replay.river_level == "watch" and "river_ensemble_unavailable" not in replay.rules_fired


def test_parse_ensemble_keeps_the_control_and_fifty_members():
    daily = {"time": ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"],
             "river_discharge": [1.0, 2.0, 3.0, 4.0]}
    for m in range(1, 51):
        daily[f"river_discharge_member{m:02d}"] = [1.0, 2.0 + m / 100, 3.0, None if m == 50 else 4.0]
    out = external_data.parse_ensemble({"daily": daily}, "2026-07-01")
    assert out["status"] == "ok" and out["members"] == 51
    assert [d["lead"] for d in out["days"]] == [1, 2, 3]
    assert len(out["days"][0]["values"]) == 51 and len(out["days"][2]["values"]) == 50
    assert out["days"][0]["values"] == sorted(out["days"][0]["values"])
    with pytest.raises(ValueError):
        external_data.parse_ensemble({"daily": {"time": ["2026-07-01"], "river_discharge": [1.0]}}, "2026-07-01")


# -- the cached daily fetch -----------------------------------------------------------
class FakeFlood:
    def __init__(self, fail: bool = False):
        self.calls = 0
        self.fail = fail

    def get(self, url, params=None, **_):
        self.calls += 1
        assert params["ensemble"] == "true" and params["latitude"] == 31.675
        if self.fail:
            raise TimeoutError("flood API timed out")
        start = datetime.fromisoformat("2026-07-01")
        times = [(start + timedelta(days=i)).date().isoformat() for i in range(10)]
        daily = {"time": times, **{f"river_discharge_member{m:02d}": [100.0 + m] * 10 for m in range(1, 51)}}

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"daily": daily}

        return R()


def test_the_ensemble_is_fetched_once_a_day_and_cached(frozen):
    client = FakeFlood()
    first = external_data.fetch_ensemble(client, 31.675, 77.025, frozen["now"])
    for minutes in (15, 30, 600):
        frozen["now"] = NOW + timedelta(minutes=minutes)
        assert external_data.fetch_ensemble(client, 31.675, 77.025, frozen["now"]) == first
    assert client.calls == 1 and first["status"] == "ok"
    frozen["now"] = datetime(2026, 7, 2, 0, 5, tzinfo=timezone.utc)  # a new UTC day: a new forecast
    second = external_data.fetch_ensemble(client, 31.675, 77.025, frozen["now"])
    assert client.calls == 2 and second["days"][0]["date"] == "2026-07-03"


def test_a_failed_ensemble_fetch_is_unavailable_and_retried_after_an_hour(frozen):
    client = FakeFlood(fail=True)
    got = external_data.fetch_ensemble(client, 31.675, 77.025, frozen["now"])
    assert got["status"] == "unavailable" and "timed out" in got["error"]
    frozen["now"] = NOW + timedelta(minutes=45)
    external_data.fetch_ensemble(client, 31.675, 77.025, frozen["now"])
    assert client.calls == 1  # not asked again on every sweep
    frozen["now"] = NOW + timedelta(minutes=external_data.ENSEMBLE_RETRY_MINUTES + 1)
    external_data.fetch_ensemble(client, 31.675, 77.025, frozen["now"])
    assert client.calls == 2


def test_the_cache_survives_a_cold_start_on_aws(repo, frozen, monkeypatch):
    monkeypatch.setattr(fetch_cache, "_repo", lambda: repo)
    fetch_cache.put("k", {"status": "ok", "x": 1.5, "none": None}, 3600)
    fetch_cache._MEM.clear()  # a new Lambda container
    assert fetch_cache.get("k") == {"status": "ok", "x": 1.5, "none": None}
    frozen["now"] = NOW + timedelta(hours=2)
    fetch_cache._MEM.clear()
    assert fetch_cache.get("k") is None  # expired, though DynamoDB's TTL has not deleted it yet


def test_live_fetch_asks_about_the_river_cell_not_the_village(monkeypatch, frozen):
    asked = []

    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class R:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    def get(self, url, params=None, **_):
        asked.append((url, dict(params or {})))
        if url == external_data.FORECAST_URL:
            return R({"hourly": {"time": [f"2026-07-01T{h:02d}:00" for h in range(24)], "precipitation": [0.0] * 24}})
        if url == external_data.FLOOD_URL and params.get("ensemble"):
            return R({"daily": {"time": ["2026-07-01", "2026-07-02"], "river_discharge_member01": [1.0, 2.0]}})
        if url == external_data.FLOOD_URL:
            return R({"daily": {"time": ["2026-07-01", "2026-07-02"], "river_discharge": [50.0, 60.0]}})
        raise RuntimeError("official source offline")

    Client.get = get
    monkeypatch.setattr(external_data.httpx, "Client", Client)
    v = Village(id="pandoh", name="Pandoh", name_hi="पंडोह", district="Mandi", lat=31.669, lon=77.054, thresholds=TH)
    r = external_data.fetch_live(v, frozen["now"])
    flood = [p for u, p in asked if u == external_data.FLOOD_URL]
    assert flood and all((p["latitude"], p["longitude"]) == (31.675, 77.025) for p in flood)
    rain = next(p for u, p in asked if u == external_data.FORECAST_URL)
    assert (rain["latitude"], rain["longitude"]) == (31.669, 77.054)
    assert r.discharge_ensemble["status"] == "ok" and r.discharge_ensemble["members"] == 1
    # Every official source failed or is off: unavailable, never a calm "normal".
    assert r.official and {i["status"] for i in r.official} <= {"unavailable", "off"}
    assert all(i["level"] is None for i in r.official)


# -- CAP certainty --------------------------------------------------------------------
@pytest.mark.parametrize(("p", "certainty"), [(1.0, "Likely"), (0.8, "Likely"), (0.79, "Possible"), (0.3, "Possible"),
                                              (0.29, None), (None, None)])
def test_certainty_from_probability(p, certainty):
    assert cap.certainty_from_probability(p) == certainty


def _alert_from(a: rr.Assessment, level: str) -> Alert:
    trace = {"rules_fired": a.rules_fired, "river_level": a.river_level, "rain_level": a.rain_level,
             "evidence": a.evidence}
    return Alert(id=new_id("alr"), village_id="pandoh", village_name="Pandoh", village_name_hi="पंडोह", level=level,
                 previous_level="normal", status="delivered", approved=True, created_at="2026-07-01T02:00:00Z",
                 updated_at="2026-07-01T02:00:00Z", decided_at="2026-07-01T02:04:00Z", decision_trace=trace,
                 text_hi="पुकार", text_en="Pukaar")


def _certainty_in_xml(alert: Alert) -> list[str]:
    xml = cap.render(alert, None, sender="pukaar-test@example.org", web_url="https://web.example", refs=[])
    root = ET.fromstring(xml)
    return [el.text for el in root.iter(f"{{{cap.CAP_NS}}}certainty")]


def test_cap_certainty_follows_the_ensemble_probability():
    possible = rr.assess(reading(ens=ensemble([160] * 4 + [110] * 6)), TH, [], NOW, ensemble_p_min=0.3)
    likely = rr.assess(reading(ens=ensemble([230] * 9 + [110])), TH, [], NOW, ensemble_p_min=0.3)
    assert (possible.level, likely.level) == ("warning", "critical")
    assert cap.alert_certainty(_alert_from(possible, "warning")) == "Possible"
    assert cap.alert_certainty(_alert_from(likely, "critical")) == "Likely"
    assert set(_certainty_in_xml(_alert_from(possible, "warning"))) == {"Possible"}


def test_cap_certainty_keeps_the_default_when_the_river_did_not_set_the_level():
    rain = rr.assess(reading(rain=130.0, ens=ensemble([110] * 4 + [60] * 6)), TH, [], NOW, ensemble_p_min=0.3)
    assert rain.level == "critical"  # rain warning + river watch agree: one up
    assert cap.alert_certainty(_alert_from(rain, rain.level)) == cap.MAPPING["critical"][2]
    today = rr.assess(reading(today=155, ens=ensemble([60] * 10)), TH, [], NOW, ensemble_p_min=0.3)
    assert cap.alert_certainty(_alert_from(today, "warning")) == cap.MAPPING["warning"][2]


# -- official corroboration -----------------------------------------------------------
def off(source: str, level: str | None, status: str = "ok") -> dict:
    return {"source": source, "name": source, "status": status, "level": level}


def test_corroboration_never_lowers_a_level():
    r = reading(rain=130.0, official=[off("cwc", "normal"), off("imd", "watch")])
    for raises in (True, False):
        a = rr.assess(r, TH, [], NOW, official_raises=raises)
        assert a.level == "warning"
    a = rr.assess(reading(rain=210.0, official=[off("imd", "normal")]), TH, [], NOW, official_raises=True)
    assert a.level == "critical"


def test_corroboration_raises_only_when_configured():
    r = reading(official=[off("cwc", "warning"), off("imd", "warning"), off("flood_hub", None, "unavailable")])
    shown = rr.assess(r, TH, [], NOW, official_raises=False)
    assert shown.level == "normal" and "official_corroborates:cwc+imd:warning" in shown.rules_fired
    item = next(e for e in shown.evidence if e["kind"] == "official")
    assert item["raises_level"] is False and len(item["items"]) == 3
    raised = rr.assess(r, TH, [], NOW, official_raises=True)
    assert raised.level == "warning" and "official:cwc+imd:warning" in raised.rules_fired
    assert "two_sources_agree:+1" not in raised.rules_fired  # official data is not a second source


def test_an_unavailable_source_says_nothing():
    assert rr.official_level([off("cwc", "critical", "unavailable"), off("imd", None, "off")]) == ("normal", [])
    a = rr.assess(reading(official=[off("cwc", "critical", "unavailable")]), TH, [], NOW, official_raises=True)
    assert a.level == "normal" and not any(r.startswith("official") for r in a.rules_fired)
