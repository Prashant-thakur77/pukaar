"""CAP 1.2 export: schema-valid against the official OASIS XSD, honest status, both languages."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import xmlschema
from fastapi.testclient import TestClient

from Pukaar.core.ids import new_id
from Pukaar.services import cap
from Pukaar.store.models import Alert, Village

XSD = Path(__file__).parent / "data" / "CAP-v1.2.xsd"
NS = {"cap": cap.CAP_NS, "atom": cap.ATOM_NS}
SCHEMA = xmlschema.XMLSchema(str(XSD))

VILLAGE = Village(id="gohar", name="Gohar", name_hi="गोहर", district="Mandi", lat=31.5456, lon=76.9871)


def make(level="warning", status="delivered", *, replay=False, drill=False, previous_level="normal",
         created="2026-07-01T02:00:00Z", decided="2026-07-01T02:04:00Z", approved=True, village="gohar") -> Alert:
    trace = {"rules_fired": ["rain_24h >= 115.6 mm (IMD heavy)", "river p95"]}
    if drill:
        trace["drill"] = True
    return Alert(id=new_id("alr"), village_id=village, village_name="Gohar", village_name_hi="गोहर", level=level,
                 previous_level=previous_level, status=status, created_at=created, updated_at=created,
                 decided_at=decided, approved=approved, replay=replay, decision_trace=trace,
                 text_hi="पुकार: गोहर के लिए चेतावनी।", text_en="Pukaar: Warning for Gohar.")


def render(a: Alert, refs: list[Alert] | None = None, village: Village | None = VILLAGE) -> ET.Element:
    xml = cap.render(a, village, sender="pukaar-test@example.org", web_url="https://web.example", refs=refs or [])
    SCHEMA.validate(xml.decode("utf-8"))  # raises on any schema violation
    return ET.fromstring(xml)


def text(el: ET.Element, path: str) -> str:
    found = el.find(path, NS)
    assert found is not None, path
    return found.text or ""


@pytest.mark.parametrize("level,expected", [
    ("watch", ("Expected", "Moderate", "Possible", "Monitor")),
    ("warning", ("Expected", "Severe", "Likely", "Prepare")),
    ("critical", ("Immediate", "Extreme", "Likely", "Evacuate")),
])
def test_schema_valid_with_level_mapping(level, expected):
    root = render(make(level))
    assert text(root, "cap:status") == "Actual" and text(root, "cap:msgType") == "Alert"
    assert text(root, "cap:scope") == "Public"
    for info in root.findall("cap:info", NS):
        got = tuple(text(info, f"cap:{t}") for t in ("urgency", "severity", "certainty", "responseType"))
        assert got == expected
        assert text(info, "cap:category") == "Met"
        assert text(info, "cap:area/cap:circle") == "31.54560,76.98710 5"
        params = {text(p, "cap:valueName"): text(p, "cap:value") for p in info.findall("cap:parameter", NS)}
        assert params["level"] == level and "IMD heavy" in params["rules_fired"]
        assert params["coordinates"].startswith("approximate")


def test_hindi_and_english_info_blocks():
    root = render(make("critical"))
    infos = {text(i, "cap:language"): i for i in root.findall("cap:info", NS)}
    assert set(infos) == {"hi-IN", "en-IN"}
    assert text(infos["hi-IN"], "cap:event") == "बाढ़" and text(infos["en-IN"], "cap:event") == "Flood"
    assert text(infos["hi-IN"], "cap:description").startswith("पुकार: गोहर")
    assert text(infos["en-IN"], "cap:area/cap:areaDesc") == "Gohar, Mandi, Himachal Pradesh"
    assert text(infos["en-IN"], "cap:web") == "https://web.example/village/gohar"
    assert text(infos["en-IN"], "cap:senderName") == "Pukaar — District Disaster Management (demo)"


def test_times_use_an_offset_and_expire_after_12_hours():
    root = render(make())
    assert text(root, "cap:sent") == "2026-07-01T07:34:00+05:30"
    info = root.find("cap:info", NS)
    assert text(info, "cap:effective") == "2026-07-01T07:34:00+05:30"
    assert text(info, "cap:expires") == "2026-07-01T19:34:00+05:30"


def test_replay_and_drill_are_exercises():
    for a in (make(replay=True), make(drill=True)):
        root = render(a)
        assert text(root, "cap:status") == "Exercise"
        assert "EXERCISE" in text(root, "cap:info[cap:language='en-IN']/cap:headline")
        assert "not" in text(root, "cap:note")


def test_auto_sent_and_failsafe_are_published_pending_and_declined_are_not():
    assert cap.is_published(make("critical", "auto_sent_unapproved", approved=False))
    assert cap.is_published(make("critical", "failsafe", approved=False))
    assert not cap.is_published(make("warning", "failsafe", approved=False))  # failsafe sent nothing
    for status in ("drafting", "pending", "declined", "expired"):
        assert not cap.is_published(make(status=status, approved=False))
    with pytest.raises(ValueError):
        cap.render(make(status="pending"), VILLAGE, sender="s", web_url="w")


def test_update_references_every_unexpired_earlier_alert():
    first = make("watch", created="2026-07-01T01:00:00Z", decided="2026-07-01T01:03:00Z")
    second = make("warning", previous_level="watch", created="2026-07-01T01:30:00Z", decided="2026-07-01T01:31:00Z")
    stale = make("watch", created="2026-06-30T10:00:00Z", decided="2026-06-30T10:01:00Z")  # expired by 02:04
    third = make("critical", previous_level="warning")
    pool = [third, second, first, stale, make("warning", "declined", approved=False),
            make("watch", village="pandoh", created="2026-07-01T01:10:00Z"),
            make("watch", drill=True, created="2026-07-01T01:20:00Z")]
    refs = cap.references(third, pool)
    assert refs == [first, second]  # oldest first; not the expired, declined, other-village or drill alerts
    root = render(third, refs=refs)
    assert text(root, "cap:msgType") == "Update"
    assert text(root, "cap:references") == (f"pukaar-test@example.org,{first.id},2026-07-01T06:33:00+05:30 "
                                            f"pukaar-test@example.org,{second.id},2026-07-01T07:01:00+05:30")
    # A replay never updates a live alert, and a rise from normal starts a new event.
    assert cap.references(make("critical", previous_level="watch", replay=True), pool) == []
    assert cap.references(make("critical", previous_level="normal"), pool) == []
    assert text(render(make("critical", previous_level="normal")), "cap:msgType") == "Alert"


@pytest.mark.parametrize("trace,code,event", [
    ({"rain_level": "warning", "river_level": "watch"}, "OET-079", "Flash Flood"),
    ({"rain_level": "warning", "river_level": "normal", "gauge_level": "warning"}, "OET-081", "Flood"),
    ({"rain_level": "normal", "river_level": "critical"}, "OET-081", "Flood"),
    ({}, "OET-081", "Flood"),  # drills and failsafe: no readings recorded
])
def test_event_code_matches_the_alert_type(trace, code, event):
    a = make("warning")
    a.decision_trace.update(trace)
    root = render(a)
    for info in root.findall("cap:info", NS):
        assert text(info, "cap:eventCode/cap:valueName") == "OET:v1.2"
        assert text(info, "cap:eventCode/cap:value") == code
    en = root.find("cap:info[cap:language='en-IN']", NS)
    assert text(en, "cap:event") == event and text(en, "cap:headline").startswith(event.replace("Flood", "Flood Warning"))


def test_area_desc_fits_50_characters_and_carries_the_lgd_district_code():
    long = Village(id="janjehli", name="Janjehli Upper Seraj Valley", name_hi="जंजैहली ऊपरी सिराज घाटी बस्ती",
                   district="Mandi", lat=31.5, lon=77.2)
    for village in (VILLAGE, long, Village(id="sujanpur", name="Sujanpur", name_hi="सुजानपुर", district="Hamirpur",
                                           lat=31.8, lon=76.5)):
        root = render(make(village=village.id), village=village)
        for info in root.findall("cap:info", NS):
            desc = text(info, "cap:area/cap:areaDesc")
            assert 0 < len(desc) <= cap.AREA_DESC_MAX, desc
            geo = {text(g, "cap:valueName"): text(g, "cap:value") for g in info.findall("cap:area/cap:geocode", NS)}
            assert geo == {"LGD District Code": {"Mandi": "22", "Hamirpur": "17"}[village.district]}
    hi_desc = text(render(make()).find("cap:info[cap:language='hi-IN']", NS), "cap:area/cap:areaDesc")
    assert hi_desc == "गोहर, मंडी, हिमाचल प्रदेश"
    # No code for a district we could not verify; the circle still locates the area.
    other = Village(id="x", name="Kasol", name_hi="कसोल", district="Kullu", lat=32.0, lon=77.3)
    assert render(make(village="x"), village=other).find("cap:info/cap:area/cap:geocode", NS) is None


# -- HTTP ----------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from Pukaar.main import app

    return TestClient(app)


def test_routes_serve_published_alerts_and_hide_the_rest(client):
    from Pukaar.store.repo import get_repo

    repo = get_repo()
    sent = make("warning", village="pandoh")
    pending = make("critical", "pending", approved=False, village="pandoh")
    replayed = make("watch", replay=True, village="pandoh", created="2026-07-01T03:00:00Z",
                    decided="2026-07-01T03:01:00Z")
    for a in (sent, pending, replayed):
        repo.put_alert(a)

    r = client.get(f"/cap/alerts/{sent.id}.xml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/cap+xml")
    SCHEMA.validate(r.text)
    root = ET.fromstring(r.content)
    assert text(root, "cap:identifier") == sent.id
    assert "Pandoh" in text(root, "cap:info[cap:language='en-IN']/cap:area/cap:areaDesc")
    assert client.get(f"/cap/alerts/{pending.id}.xml").status_code == 404
    assert client.get("/cap/alerts/alr_missing.xml").status_code == 404

    feed = client.get("/cap/alerts.atom", headers={"x-forwarded-proto": "https", "host": "api.example"})
    assert feed.status_code == 200 and feed.headers["content-type"].startswith("application/atom+xml")
    root = ET.fromstring(feed.content)  # well-formed
    assert root.tag == f"{{{cap.ATOM_NS}}}feed"
    hrefs = [e.find("atom:link[@type='application/cap+xml']", NS).get("href") for e in root.findall("atom:entry", NS)]
    ours = [h for h in hrefs if replayed.id in h or sent.id in h]  # other tests may share this app's table
    assert ours == [f"https://api.example/cap/alerts/{replayed.id}.xml",
                    f"https://api.example/cap/alerts/{sent.id}.xml"]  # newest first
    stamps = [e.find("atom:updated", NS).text for e in root.findall("atom:entry", NS)]
    assert stamps == sorted(stamps, reverse=True)
    assert not any(pending.id in h for h in hrefs)
    assert len(hrefs) <= cap.FEED_SIZE
    for field in ("id", "title", "updated", "author/atom:name"):
        assert root.find(f"atom:{field}", NS) is not None


# -- who the message is from (CapSender, CapSenderName, CapSenderNameHi) -------------------------
AUTHORITY = "District Disaster Management Authority, Mandi"
AUTHORITY_HI = "ज़िला आपदा प्रबंधन प्राधिकरण, मंडी"


def _sender_names(root: ET.Element) -> dict[str, str]:
    return {text(i, "cap:language"): text(i, "cap:senderName") for i in root.findall("cap:info", NS)}


def test_demo_sender_is_marked_demo_and_says_it_is_not_official():
    root = render(make())
    assert _sender_names(root) == {"hi-IN": cap.SENDER_NAME_HI, "en-IN": cap.SENDER_NAME}
    assert "(demo)" in cap.SENDER_NAME and cap.DEMO_NOTE in text(root, "cap:note")


def test_authority_sender_name_replaces_the_demo_one_in_both_languages():
    xml = cap.render(make(), VILLAGE, sender="ddma-mandi@hp.gov.in", web_url="https://web.example",
                     sender_name=AUTHORITY, sender_name_hi=AUTHORITY_HI)
    SCHEMA.validate(xml.decode("utf-8"))
    root = ET.fromstring(xml)
    assert text(root, "cap:sender") == "ddma-mandi@hp.gov.in"
    assert _sender_names(root) == {"hi-IN": AUTHORITY_HI, "en-IN": AUTHORITY}
    assert root.find("cap:note", NS) is None  # a live alert from the authority carries no demo note
    assert "(demo)" not in xml.decode("utf-8") and "डेमो" not in xml.decode("utf-8")
    # no Hindi name given: the English one in both blocks; a replay still says it is a replay
    replay = ET.fromstring(cap.render(make(replay=True), VILLAGE, sender="s@x", web_url="w", sender_name=AUTHORITY))
    assert set(_sender_names(replay).values()) == {AUTHORITY}
    assert "Replay" in text(replay, "cap:note") and cap.DEMO_NOTE not in text(replay, "cap:note")


def test_all_clear_and_feed_carry_the_authority_name():
    sent = make("warning", created="2026-07-01T02:00:00Z")
    gohar = VILLAGE.model_copy(update={"level": "normal", "level_since": "2026-07-01T06:00:00Z"})
    clear = cap.all_clear(gohar, [sent])
    assert clear is not None
    root = ET.fromstring(cap.render_all_clear(clear, sender="ddma-mandi@hp.gov.in", web_url="w",
                                              sender_name=AUTHORITY, sender_name_hi=AUTHORITY_HI))
    assert _sender_names(root) == {"hi-IN": AUTHORITY_HI, "en-IN": AUTHORITY}
    assert cap.DEMO_NOTE not in text(root, "cap:note")
    feed = ET.fromstring(cap.atom([sent], api_base="https://api.example", web_url="w", sender_name=AUTHORITY))
    assert feed.find("atom:author/atom:name", NS).text == AUTHORITY
    assert "(demo)" not in feed.find("atom:title", NS).text
    demo_feed = ET.fromstring(cap.atom([sent], api_base="https://api.example", web_url="w"))
    assert demo_feed.find("atom:title", NS).text.endswith("(demo)")


def test_settings_read_the_sender_from_the_stack(monkeypatch, client):
    from Pukaar.core.config import get_settings
    from Pukaar.store.repo import get_repo

    monkeypatch.setenv("PUKAAR_CAP_SENDER", "ddma-mandi@hp.gov.in")
    monkeypatch.setenv("PUKAAR_CAP_SENDER_NAME", AUTHORITY)
    monkeypatch.setenv("PUKAAR_CAP_SENDER_NAME_HI", AUTHORITY_HI)
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert (s.cap_sender, s.cap_sender_name, s.cap_sender_name_hi) == ("ddma-mandi@hp.gov.in", AUTHORITY, AUTHORITY_HI)
        a = make("warning", village="janjehli")
        get_repo().put_alert(a)
        root = ET.fromstring(client.get(f"/cap/alerts/{a.id}.xml").content)
        assert text(root, "cap:sender") == "ddma-mandi@hp.gov.in"
        assert _sender_names(root)["en-IN"] == AUTHORITY
    finally:
        for var in ("PUKAAR_CAP_SENDER", "PUKAAR_CAP_SENDER_NAME", "PUKAAR_CAP_SENDER_NAME_HI"):
            monkeypatch.delenv(var)
        get_settings.cache_clear()
    s = get_settings()
    assert s.cap_sender.startswith("pukaar-dev@") and s.cap_sender_name == ""  # dev keeps the demo sender
