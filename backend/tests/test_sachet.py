"""SACHET in (services/sachet.py: NDMA's public CAP feed as an official source) and out (services/sachet_request.py:
the package an officer sends HPSDMA). The feed parsers run on the live Himachal feed and one of its CAP messages,
saved on 23 October 2026, and on a hand-written flood message in the same shape (tests/data/*.NOTICE.txt)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from Pukaar.core import clock
from Pukaar.services import fetch_cache, official_data, risk_rules, sachet, sachet_request
from Pukaar.store.models import Alert, Reading, Village

DATA = Path(__file__).parent / "data"
RSS = (DATA / "sachet_rss_himachal.xml").read_bytes()
THUNDER = (DATA / "sachet_cap_imd_shimla_thunderstorm.xml").read_bytes()
FLOOD = (DATA / "sachet_cap_flood_fixture.xml").read_bytes()
THUNAG = Village(id="thunag", name="Thunag", name_hi="थुनाग", district="Mandi", lat=31.55929, lon=77.16515,
                 district_hi="मंडी", lgd_district_code="22")
SUJANPUR = Village(id="sujanpur", name="Sujanpur", name_hi="सुजानपुर", district="Hamirpur", lat=31.83, lon=76.50,
                   district_hi="हमीरपुर", lgd_district_code="17")
CAP_NS = "{urn:oasis:names:tc:emergency:cap:1.2}"


@pytest.fixture(autouse=True)
def _fresh_cache():
    fetch_cache.clear()
    yield
    fetch_cache.clear()


class Resp:
    def __init__(self, body: bytes, status: int = 200):
        self.content, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Feed:
    """The SACHET site: the RSS, and each CAP file by its identifier."""

    def __init__(self, rss: bytes, caps: dict[str, bytes]):
        self.rss, self.caps, self.calls = rss, caps, []

    def get(self, url, **kw):
        self.calls.append(url)
        if url.endswith(".xml") and "rss" in url:
            return Resp(self.rss)
        for ident, body in self.caps.items():
            if url.endswith(ident):
                return Resp(body)
        raise ConnectionError(f"no route to {url}")


def _rss(*items: tuple[str, str]) -> bytes:
    rows = "".join(f"<item><title>t</title><link>https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?"
                   f"identifier={i}</link><guid>{i}</guid><pubDate>{d}</pubDate></item>" for i, d in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>HP</title>{rows}</channel></rss>'.encode()


# -- parsing the live feed -------------------------------------------------------------------------
def test_the_saved_himachal_feed_and_message_parse():
    items = sachet.parse_rss(RSS)
    assert len(items) == 10 and items[0]["guid"] == "1792044694412014"
    assert items[0]["author"].endswith("(IMD Shimla)") and "FetchXMLFile" in items[0]["link"]
    msg = sachet.parse_cap(THUNDER)
    assert msg["sender"] == "Himachal-Pradesh-SDMA" and msg["status"] == "Actual" and msg["msg_type"] == "Update"
    assert [i["language"] for i in msg["infos"]] == ["HI", "en-IN"] and msg["infos"][0]["severity"] == "Moderate"


def test_a_thunderstorm_names_mandi_but_implies_no_flood_level():
    msg = sachet.parse_cap(THUNDER)
    assert sachet.how_it_covers(msg, THUNAG) == "names Mandi"
    assert sachet.implies(msg) is None  # thunderstorms and light snow are not a flood source
    when = datetime(2026, 10, 15, 7, 0, tzinfo=timezone.utc)  # 12:30 IST, before it expired at 14:27 IST
    item = sachet.item_for([(msg, "link", None)], THUNAG, when)
    assert item["status"] == "ok" and item["level"] == "normal" and len(item["matched"]) == 1
    assert "none flood-related" in item["detail"]
    assert sachet.item_for([(msg, "link", None)], THUNAG, datetime(2026, 10, 16, tzinfo=timezone.utc))["matched"] == []


def test_a_flood_message_covers_by_polygon_and_lgd_code_and_implies_warning():
    msg = sachet.parse_cap(FLOOD)
    assert sachet.how_it_covers(msg, THUNAG) == "polygon"
    assert sachet.implies(msg) == "warning"  # Severe heavy rain and flash floods
    assert sachet.how_it_covers(msg, SUJANPUR) is None  # another district
    when = datetime(2026, 7, 10, 18, 0, tzinfo=timezone.utc)
    item = sachet.item_for([(msg, "l", None)], THUNAG, when)
    assert item["level"] == "warning" and item["matched"][0]["covers"] == "polygon"
    assert item["matched"][0]["headline_en"].startswith("Heavy rainfall")
    assert sachet.item_for([(msg, "l", None)], SUJANPUR, when)["regional_count"] == 1


def test_exercises_and_cancelled_messages_are_ignored():
    msg = sachet.parse_cap(FLOOD)
    when = datetime(2026, 7, 10, 18, 0, tzinfo=timezone.utc)
    exercise = {**msg, "status": "Exercise"}
    cancel = {**msg, "identifier": "IN-X-CANCEL", "msg_type": "Cancel",
              "references": "Himachal-Pradesh-SDMA,IN-TEST-FLOOD-MANDI-1,2026-07-10T21:00:00+05:30"}
    assert sachet.item_for([(exercise, "l", None)], THUNAG, when)["matched"] == []
    assert sachet.item_for([(msg, "l", None), (cancel, "l", None)], THUNAG, when)["level"] == "normal"


def test_dtds_and_other_documents_are_refused():
    with pytest.raises(sachet.SachetError):
        sachet.parse_rss(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><rss><channel/></rss>')
    with pytest.raises(sachet.SachetError):
        sachet.parse_cap(RSS)
    with pytest.raises(sachet.SachetError):
        sachet.parse_rss(b"not xml")


# -- as an official source ---------------------------------------------------------------------------
def test_the_feed_is_fetched_once_and_read_for_every_village(frozen):
    frozen["now"] = datetime(2026, 7, 10, 18, 0, tzinfo=timezone.utc)
    site = Feed(_rss(("IN-TEST-FLOOD-MANDI-1", "Fri, 10 Jul 2026 15:30:00 GMT")), {"IN-TEST-FLOOD-MANDI-1": FLOOD})
    a = sachet.item(site, THUNAG)
    b = sachet.item(site, SUJANPUR)
    assert a["level"] == "warning" and b["level"] == "normal" and b["regional_count"] == 1
    assert len(site.calls) == 2  # the RSS and the one CAP file, once for both villages


def test_an_unreachable_feed_is_unavailable_never_normal(frozen):
    item = sachet.item(Feed(b"", {}), THUNAG)
    assert item["status"] == "unavailable" and item["level"] is None
    items = {i["source"]: i for i in official_data.for_village(THUNAG, frozen["now"], client=Feed(b"", {}))}
    assert items["sachet"]["status"] == "unavailable"


def test_switched_off_says_so(monkeypatch):
    from Pukaar.core.config import get_settings

    monkeypatch.setenv("PUKAAR_SACHET", "false")
    get_settings.cache_clear()
    try:
        assert sachet.item(Feed(RSS, {}), THUNAG)["status"] == "off"
    finally:
        monkeypatch.delenv("PUKAAR_SACHET")
        get_settings.cache_clear()


def test_sachet_raises_a_level_only_when_official_data_may_and_is_in_the_trace():
    now = datetime(2026, 7, 10, 18, 0, tzinfo=timezone.utc)
    item = sachet.item_for([(sachet.parse_cap(FLOOD), "l", None)], THUNAG, now)
    reading = Reading(village_id="thunag", at=clock.iso(now), rain_24h_mm=2.0, official=[item])
    off = risk_rules.assess(reading, None, [], now, official_raises=False)
    on = risk_rules.assess(reading, None, [], now, official_raises=True)
    assert off.level == "normal" and "official_corroborates:sachet:warning" in off.rules_fired
    assert on.level == "warning" and "official:sachet:warning" in on.rules_fired
    ev = next(e for e in off.evidence if e["kind"] == "official")
    assert ev["items"][0]["source"] == "sachet"
    # Never lowers: a higher level from rain stays.
    calm = sachet.item_for([], THUNAG, now)
    high = Reading(village_id="thunag", at=clock.iso(now), rain_24h_mm=400.0, official=[calm])
    assert risk_rules.assess(high, None, [], now, official_raises=True).level != "normal"


# -- SACHET out: the package for HPSDMA -----------------------------------------------------------------
def _alert(repo, level="critical", status="approved", replay=False, flash=True) -> Alert:
    v = repo.get_village("thunag")
    now = clock.iso(clock.now())
    a = Alert(id=f"alr_sachet_{level}_{status}", village_id="thunag", village_name=v.name, village_name_hi=v.name_hi,
              level=level, status=status, approved=status == "approved", created_at=now, updated_at=now,
              decided_at=now, decided_by="officer1", replay=replay,
              text_hi="पुकार: थुनाग के लिए गंभीर ख़तरा।", text_en="Pukaar: Critical for Thunag.",
              decision_trace={"rain_level": "critical" if flash else "normal", "river_level": "warning"})
    repo.put_alert(a)
    return repo.get_alert(a.id)


def test_the_package_is_cap_with_a_polygon_and_texts_within_cell_broadcast_limits(repo, frozen):
    a = _alert(repo)
    pkg = sachet_request.build(a, repo.get_village("thunag"), radius_km=3)
    root = ET.fromstring(pkg.cap_xml.encode())
    assert root.find(f"{CAP_NS}scope").text == "Restricted" and root.find(f"{CAP_NS}status").text == "Actual"
    assert "not issued by pukaar" in root.find(f"{CAP_NS}restriction").text.lower()
    infos = root.findall(f"{CAP_NS}info")
    assert [i.find(f"{CAP_NS}language").text for i in infos] == ["hi-IN", "en-IN"]
    poly = infos[0].find(f"{CAP_NS}area/{CAP_NS}polygon").text.split()
    assert len(poly) == sachet_request.POLYGON_POINTS + 1 and poly[0] == poly[-1]
    lat, lon = map(float, poly[0].split(","))
    assert abs(sachet._km(lat, lon, 31.55929, 77.16515) - 3) < 0.1
    assert infos[1].find(f"{CAP_NS}severity").text == "Extreme"
    assert any(g.find(f"{CAP_NS}value").text == "22" for g in infos[0].iter(f"{CAP_NS}geocode"))
    # Cell broadcast: Hindi in UCS-2, English in GSM 7-bit, each within the target pages.
    assert sachet_request.cb_pages(pkg.text_hi) <= sachet_request.CB_TARGET_PAGES
    assert sachet_request.is_gsm7(pkg.text_en) and sachet_request.cb_pages(pkg.text_en) <= sachet_request.CB_TARGET_PAGES
    assert "थुनाग" in pkg.text_hi and "112" in pkg.text_hi and "Thunag" in pkg.text_en and "112" in pkg.text_en
    assert "Flash flood" in pkg.text_en and "DDMA Mandi" in pkg.text_en
    assert pkg.steps_en[0].startswith("Call the HPSDMA State Emergency Operation Centre (1070)")
    assert pkg.mailto.startswith("mailto:?subject=") and "not%20sent" in pkg.mailto.lower()


def test_cell_broadcast_page_arithmetic():
    assert sachet_request.cb_pages("a" * 93) == 1 and sachet_request.cb_pages("a" * 94) == 2
    assert sachet_request.cb_pages("ब" * 41) == 1 and sachet_request.cb_pages("ब" * 42) == 2
    assert sachet_request.cb_limit("Flood") == 4 * 93 and sachet_request.cb_limit("बाढ़") == 4 * 41


def test_only_a_published_warning_or_critical_can_be_requested(repo, frozen):
    v = repo.get_village("thunag")
    with pytest.raises(sachet_request.NotRequestable):
        sachet_request.build(_alert(repo, status="pending"), v)
    with pytest.raises(sachet_request.NotRequestable):
        sachet_request.build(_alert(repo, level="watch"), v)
    replay = sachet_request.build(_alert(repo, level="warning", replay=True), v)
    assert replay.exercise and "EXERCISE" in replay.text_en and "Exercise" in replay.cap_xml


@pytest.fixture()
def client(repo, monkeypatch):
    from Pukaar.api import auth
    from Pukaar.api.routers import reach
    from Pukaar.main import app

    for mod in (auth, reach):
        monkeypatch.setattr(mod, "get_repo", lambda: repo)
    monkeypatch.setattr("Pukaar.store.repo.get_repo", lambda: repo)
    return TestClient(app)


def _token(client, user):
    return {"Authorization": "Bearer " + client.post("/auth/dev-login", json={"username": user}).json()["token"]}


def test_the_route_is_audited_never_claims_a_broadcast_and_refuses_a_pradhan(client, repo, frozen):
    a = _alert(repo)
    r = client.post(f"/alerts/{a.id}/sachet-request", json={"via": "copy", "radius_km": 4},
                    headers=_token(client, "officer1"))
    assert r.status_code == 200
    body = r.json()
    assert body["radius_km"] == 4 and body["limits"]["hi"]["encoding"] == "UCS-2"
    assert "not sent" in body["not_sent_en"].lower() and "<cap:" not in body["cap_xml"]
    rows = [x for x in repo.list_audit(clock.iso(clock.now())[:10]) if x.action == "sachet_request_prepared"]
    assert rows and "via copy" in rows[0].reason and "not sent by Pukaar" in rows[0].reason
    assert any(t.step == "sachet_request" for t in repo.list_timeline(a.id))
    assert client.post(f"/alerts/{a.id}/sachet-request", headers=_token(client, "pradhan_thunag")).status_code == 403
    assert client.post(f"/alerts/{a.id}/sachet-request", headers=_token(client, "judge")).status_code == 403
    pending = _alert(repo, status="pending")
    assert client.post(f"/alerts/{pending.id}/sachet-request", headers=_token(client, "officer1")).status_code == 409
