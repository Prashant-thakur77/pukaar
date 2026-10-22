"""Official corroboration: the CWC and IMD parsers on saved responses, the Flood Hub and BIPAD
adapters, and every failure read as "unavailable", never as a calm "normal"."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from Pukaar.services import fetch_cache, official_data as od
from Pukaar.store.models import Thresholds, Village

DATA = Path(__file__).parent / "data"
CWC_SAMPLE = json.loads((DATA / "cwc_station_water_level_above_warning.json").read_text(encoding="utf-8"))
IMD_SAMPLE = json.loads((DATA / "imd_district_warning_featureinfo.json").read_text(encoding="utf-8"))
THUNAG = Village(id="thunag", name="Thunag", name_hi="थुनाग", district="Mandi", lat=31.55929, lon=77.16515,
                 thresholds=Thresholds(watch=1.43, warning=1.97, critical=2.66, cell_lat=31.575, cell_lon=77.175))
NOW = datetime(2026, 10, 22, 12, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_cache():
    fetch_cache.clear()
    yield
    fetch_cache.clear()


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class Client:
    """Answers by URL; anything not listed raises, like a site that is down."""

    def __init__(self, routes: dict[str, object]):
        self.routes, self.calls = routes, []

    def _answer(self, url, **kw):
        self.calls.append((url, kw))
        for prefix, body in self.routes.items():
            if url.startswith(prefix):
                if isinstance(body, BaseException):
                    raise body
                return Resp(body)
        raise ConnectionError(f"no route to {url}")

    def get(self, url, **kw):
        return self._answer(url, **kw)

    def post(self, url, **kw):
        return self._answer(url, **kw)


# -- CWC --------------------------------------------------------------------------
def test_cwc_parser_reads_the_saved_response():
    stations = od.parse_cwc(CWC_SAMPLE)
    assert len(stations) == 11
    first = stations[0]
    assert first["station_code"] == "033-MGD5PTN" and first["status"] == "WARNING" and first["value_m"] == 54.77
    assert first["trend"] == "STEADY" and first["river"] is None and first["state"] is None


def test_cwc_maps_nothing_to_a_village_without_a_station_or_river_match():
    result = od.cwc_for_village(od.parse_cwc(CWC_SAMPLE), {"cwc_rivers": ["Beas"], "cwc_stations": []})
    assert result["level"] == "normal" and result["matched"] == [] and result["stations_above_warning"] == 11


def test_cwc_maps_a_listed_code_or_a_named_river_and_keeps_other_himachal_stations_as_context():
    stations = od.parse_cwc(CWC_SAMPLE) + [
        {"station_code": "X-BEAS", "status": "DANGER", "trend": "RISING", "value_m": 1.0, "name": "Mandi",
         "river": "Beas", "state": "Himachal Pradesh"},
        {"station_code": "X-SUTLEJ", "status": "WARNING", "trend": "RISING", "value_m": 1.0, "name": "Rampur",
         "river": "Sutlej", "state": "Himachal Pradesh"},
    ]
    by_code = od.cwc_for_village(stations, {"cwc_stations": ["033-mgd5ptn"]})
    assert by_code["level"] == "watch" and [m["station_code"] for m in by_code["matched"]] == ["033-MGD5PTN"]
    by_river = od.cwc_for_village(stations, {"cwc_rivers": ["Beas"]})
    assert by_river["level"] == "warning" and [m["station_code"] for m in by_river["matched"]] == ["X-BEAS"]
    assert [r["station_code"] for r in by_river["regional"]] == ["X-SUTLEJ"]  # shown, implies nothing


def test_cwc_parser_rejects_another_shape():
    for body in ({"error": "maintenance"}, [{"id": 1}], "<html>"):
        with pytest.raises(ValueError):
            od.parse_cwc(body)


def test_cwc_item_from_the_sample_is_ok_and_says_what_it_could_not_map():
    item = od.cwc_item(od.fetch_cwc(Client({od.CWC_URL: CWC_SAMPLE})), THUNAG)
    assert item["status"] == "ok" and item["level"] == "normal"
    assert "11 CWC station(s) above warning level" in item["detail"] and "no station codes mapped" in item["detail"]


# -- IMD --------------------------------------------------------------------------
def test_imd_parser_reads_the_saved_response():
    parsed = od.parse_imd(IMD_SAMPLE, date(2026, 10, 22), "Mandi")
    assert parsed["district"] == "MANDI" and parsed["issued"] == "2026-10-21"
    assert parsed["colour"] == "green" and parsed["level"] == "normal"
    assert [d["date"] for d in parsed["window"]] == ["2026-10-22", "2026-10-23"]  # Day 2 and 3 of the issue


def test_imd_colour_maps_to_a_level():
    body = json.loads(json.dumps(IMD_SAMPLE))
    props = body["features"][0]["properties"]
    props.update(Day2_Color=3, Day3_Color=2)
    parsed = od.parse_imd(body, date(2026, 10, 22), "Mandi")
    assert (parsed["colour"], parsed["level"]) == ("orange", "warning")
    props.update(Day2_Color=1)
    assert od.parse_imd(body, date(2026, 10, 22), "Mandi")["level"] == "critical"


def test_imd_rejects_a_point_without_a_district_or_a_stale_issue():
    with pytest.raises(ValueError):
        od.parse_imd({"type": "FeatureCollection", "features": []}, date(2026, 10, 22))
    with pytest.raises(ValueError):
        od.parse_imd(IMD_SAMPLE, date(2026, 11, 30))  # a warning issued in October does not cover 30 November


def test_imd_is_cached_per_district_and_day():
    client = Client({od.IMD_WMS_URL: IMD_SAMPLE})
    gohar = THUNAG.model_copy(update={"id": "gohar"})
    a = od.fetch_imd(client, THUNAG, date(2026, 10, 22))
    b = od.fetch_imd(client, gohar, date(2026, 10, 22))
    assert a["status"] == b["status"] == "ok" and len(client.calls) == 1


# -- Flood Hub and BIPAD -----------------------------------------------------------
def test_flood_hub_gauges_near_the_river_cell_set_the_level():
    body = {"floodStatuses": [
        {"gaugeId": "hybas_1", "severity": "SEVERE", "gaugeLocation": {"latitude": 31.6, "longitude": 77.2}},
        {"gaugeId": "hybas_2", "severity": "EXTREME", "gaugeLocation": {"latitude": 32.5, "longitude": 77.2}},
        {"gaugeId": "hybas_3", "severity": "UNKNOWN", "gaugeLocation": {"latitude": 31.58, "longitude": 77.18}},
    ]}
    gauges = od.parse_flood_hub(body)
    near = od.flood_hub_for_point(gauges, 31.575, 77.175, 25)
    assert near["level"] == "warning" and [g["gauge_id"] for g in near["gauges"]] == ["hybas_3", "hybas_1"]


def test_flood_hub_is_off_by_default_and_unavailable_without_a_key():
    items = {i["source"]: i for i in od.for_village(THUNAG, NOW, client=Client({}))}
    assert items["flood_hub"]["status"] == "off" and items["bipad"]["status"] == "off"
    assert od.fetch_flood_hub(Client({}))["status"] == "unavailable"  # no PUKAAR_FLOOD_HUB_API_KEY in tests


def test_bipad_request_and_parser():
    params = od.bipad_url_params(17, datetime(2026, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 1, 6, tzinfo=timezone.utc))
    assert params["station"] == 17 and params["water_level_on__gt"].startswith("2026-07-01T00:00")
    body = {"count": 1, "results": [{"title": "Chisapani", "basin": "Karnali", "waterLevel": 9.1,
                                     "warningLevel": 8.0, "dangerLevel": 10.8, "status": "ABOVE WARNING LEVEL",
                                     "waterLevelOn": "2026-07-01T05:45:00+05:45"}]}
    reading = od.parse_bipad(body)
    assert reading["implies"] == "watch" and reading["title"] == "Chisapani"
    assert od.parse_bipad({"results": []}) is None
    with pytest.raises(ValueError):
        od.parse_bipad([])


# -- failure is "unavailable" ----------------------------------------------------------
def test_every_failure_becomes_unavailable_never_normal():
    down = Client({od.CWC_URL: TimeoutError("read timed out"), od.IMD_WMS_URL: ConnectionError("503 from geoserver")})
    items = {i["source"]: i for i in od.for_village(THUNAG, NOW, client=down)}
    assert items["cwc"]["status"] == "unavailable" and items["cwc"]["level"] is None
    assert "timed out" in items["cwc"]["error"]
    assert items["imd"]["status"] == "unavailable" and items["imd"]["level"] is None


def test_a_changed_response_is_unavailable_too():
    changed = Client({od.CWC_URL: {"message": "moved"}, od.IMD_WMS_URL: {"type": "FeatureCollection", "features": []}})
    items = {i["source"]: i for i in od.for_village(THUNAG, NOW, client=changed)}
    assert items["cwc"]["status"] == items["imd"]["status"] == "unavailable"


def test_a_failure_is_retried_after_a_short_wait_not_every_sweep(frozen):
    client = Client({})
    od.fetch_cwc(client)
    od.fetch_cwc(client)
    assert len(client.calls) == 1


def test_a_bug_in_one_adapter_does_not_stop_the_others(monkeypatch):
    monkeypatch.setattr(od, "fetch_cwc", lambda client: 1 / 0)
    items = {i["source"]: i for i in od.for_village(THUNAG, NOW, client=Client({od.IMD_WMS_URL: IMD_SAMPLE}))}
    assert items["cwc"]["status"] == "unavailable" and "ZeroDivisionError" in items["cwc"]["error"]
    assert items["imd"]["status"] == "ok" and items["imd"]["level"] == "normal"


def test_switched_off_means_no_items(monkeypatch):
    monkeypatch.setenv("PUKAAR_OFFICIAL_DATA", "false")
    from Pukaar.core.config import get_settings

    get_settings.cache_clear()
    try:
        assert od.for_village(THUNAG, NOW, client=Client({})) == []
    finally:
        monkeypatch.delenv("PUKAAR_OFFICIAL_DATA")
        get_settings.cache_clear()
