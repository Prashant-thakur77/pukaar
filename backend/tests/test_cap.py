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


def render(a: Alert, previous: Alert | None = None) -> ET.Element:
    xml = cap.render(a, VILLAGE, sender="pukaar-test@example.org", web_url="https://web.example", previous=previous)
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


def test_update_references_the_earlier_published_alert():
    first = make("watch", created="2026-07-01T01:00:00Z", decided="2026-07-01T01:03:00Z")
    second = make("critical", previous_level="watch")
    prev = cap.previous_published(second, [second, first, make("warning", "declined", approved=False)])
    assert prev is first
    root = render(second, previous=prev)
    assert text(root, "cap:msgType") == "Update"
    assert text(root, "cap:references") == f"pukaar-test@example.org,{first.id},2026-07-01T06:33:00+05:30"
    # A replay never updates a live alert.
    assert cap.previous_published(make("critical", previous_level="watch", replay=True), [first]) is None


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
