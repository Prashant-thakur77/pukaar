"""Google Public Alerts CAP profile rules, run over every kind of message Pukaar publishes.

The rules are ported from Google's cap-library (https://github.com/google/cap-library,
Apache License 2.0, Copyright Google Inc.): profile/GoogleProfile.java (errors and the
recommendations listed below), CapValidator.java (circular and postdated references) and
feed/CapFeedValidator.java (unique ATOM entry ids, a CAP link on every entry). Only the
checks are ported, as Python; no cap-library code is copied. SACHET's 50-character
areaDesc limit is checked as well (docs/SACHET.md).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pytest
import xmlschema
from fastapi.testclient import TestClient

from Pukaar.core.ids import new_id
from Pukaar.services import cap
from Pukaar.store.models import Alert, Village

XSD = Path(__file__).parent / "data" / "CAP-v1.2.xsd"
SCHEMA = xmlschema.XMLSchema(str(XSD))
NS = {"cap": cap.CAP_NS, "atom": cap.ATOM_NS}
SENDER = "pukaar-test@example.org"
WEB = "https://web.example"

GOHAR = Village(id="gohar", name="Gohar", name_hi="गोहर", district="Mandi", lat=31.57975, lon=77.04841,
                level="normal", level_since="2026-07-01T06:00:00Z")
SUJANPUR = Village(id="sujanpur", name="Sujanpur", name_hi="सुजानपुर", district="Hamirpur", lat=31.83364,
                   lon=76.50539)


def make(level="warning", *, previous_level="normal", created="2026-07-01T02:00:00Z",
         decided="2026-07-01T02:04:00Z", village=GOHAR, status="delivered", trace=None, replay=False) -> Alert:
    return Alert(id=new_id("alr"), village_id=village.id, village_name=village.name, village_name_hi=village.name_hi,
                 level=level, previous_level=previous_level, status=status, created_at=created, updated_at=created,
                 decided_at=decided, approved=True, replay=replay,
                 decision_trace=trace if trace is not None else {"rules_fired": ["rain_24h>=64.5mm:watch"]},
                 text_hi=f"पुकार: {village.name_hi} के लिए चेतावनी।", text_en=f"Pukaar: Warning for {village.name}.")


# -- the profile, as a checker ------------------------------------------------

def _time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _t(el: ET.Element, path: str) -> str | None:
    found = el.find(path, NS)
    return None if found is None or found.text is None else found.text.strip()


def profile_errors(xml: bytes) -> list[str]:
    """Every Google profile error and checked recommendation this <alert> breaks (empty when it passes)."""
    root = ET.fromstring(xml)
    errors: list[str] = []
    ident, sent, msg_type = _t(root, "cap:identifier"), _t(root, "cap:sent"), _t(root, "cap:msgType")
    refs = (_t(root, "cap:references") or "").split()

    # GoogleProfile: an Update or Cancel references the messages it updates or cancels.
    if msg_type in ("Update", "Cancel") and not refs:
        errors.append("UPDATE_OR_CANCEL_MUST_REFERENCE")
    # CapValidator: references are sender,identifier,sent; never itself, never later than this message.
    for ref in refs:
        parts = ref.split(",")
        if len(parts) != 3:
            errors.append(f"MALFORMED_REFERENCE {ref}")
            continue
        if parts[1] == ident:
            errors.append(f"CIRCULAR_REFERENCE {ref}")
        if sent and _time(parts[2]) > _time(sent):
            errors.append(f"POSTDATED_REFERENCE {ref}")

    infos = root.findall("cap:info", NS)
    if not infos:
        errors.append("INFO_IS_REQUIRED")
    categories = event_codes = None
    for i, info in enumerate(infos, 1):
        where = f"info[{i}]"
        cats = {c.text for c in info.findall("cap:category", NS)}
        codes = {(_t(e, "cap:valueName"), _t(e, "cap:value")) for e in info.findall("cap:eventCode", NS)}
        if categories is None:
            categories, event_codes = cats, codes
        else:
            if cats != categories:
                errors.append(f"CATEGORIES_MUST_MATCH {where}")
            if codes != event_codes:
                errors.append(f"EVENT_CODES_MUST_MATCH {where}")
        for tag in ("description", "web", "expires", "urgency", "severity", "certainty"):
            if not _t(info, f"cap:{tag}"):
                errors.append(f"{tag.upper()}_IS_REQUIRED {where}")
        effective = _t(info, "cap:effective") or sent
        expires = _t(info, "cap:expires")
        if effective and expires and _time(effective) > _time(expires):
            errors.append(f"EFFECTIVE_NOT_AFTER_EXPIRES {where}")
        areas = info.findall("cap:area", NS)
        if not areas:
            errors.append(f"AREA_IS_REQUIRED {where}")
        for area in areas:
            if not any(area.find(f"cap:{s}", NS) is not None for s in ("polygon", "circle", "geocode")):
                errors.append(f"CIRCLE_POLYGON_OR_GEOCODE_IS_REQUIRED {where}")
            for g in area.findall("cap:geocode", NS):
                if not _t(g, "cap:valueName") or not _t(g, "cap:value"):
                    errors.append(f"EMPTY_GEOCODE_FIELD {where}")
            if len(_t(area, "cap:areaDesc") or "") > cap.AREA_DESC_MAX:  # SACHET, not Google
                errors.append(f"AREA_DESC_TOO_LONG {where}")
        # Recommendations Pukaar holds itself to.
        headline, description, instruction = (_t(info, f"cap:{t}") or "" for t in ("headline", "description",
                                                                                    "instruction"))
        if len(headline) >= 140:
            errors.append(f"HEADLINE_TOO_LONG {where}")
        if headline == description:
            errors.append(f"HEADLINE_AND_DESCRIPTION_SHOULD_DIFFER {where}")
        if not instruction or instruction == description or instruction == headline:
            errors.append(f"DESCRIPTION_AND_INSTRUCTION_SHOULD_DIFFER {where}")
        for tag in ("senderName", "responseType", "contact"):
            if not _t(info, f"cap:{tag}"):
                errors.append(f"{tag.upper()}_RECOMMENDED {where}")
    if any((el.text or "").strip() == "Unknown" for el in root.iter()):
        errors.append("UNKNOWN_VALUE_DISCOURAGED")
    return errors


def feed_errors(feed: bytes) -> list[str]:
    """CapFeedValidator's ATOM checks: unique entry ids, and a CAP link on every entry."""
    errors, ids = [], set()
    for i, entry in enumerate(ET.fromstring(feed).findall("atom:entry", NS), 1):
        links = [ln for ln in entry.findall("atom:link", NS) if ln.get("rel", "alternate") != "self"]
        types = [ln.get("type") for ln in links]
        others = [t for t in types if t is None or not t.startswith(("image", "audio", "video"))]
        if not (len(links) == 1 or "application/cap+xml" in types or len(others) == 1):
            errors.append(f"ATOM_ENTRY_MISSING_CAP_LINK entry[{i}]")
        eid = _t(entry, "atom:id")
        if eid in ids:
            errors.append(f"ATOM_ENTRY_NON_UNIQUE_IDS {eid}")
        ids.add(eid)
    return errors


def checked(xml: bytes) -> ET.Element:
    SCHEMA.validate(xml.decode("utf-8"))
    assert profile_errors(xml) == []
    return ET.fromstring(xml)


# -- every kind of message passes ----------------------------------------------

WATCH = make("watch", created="2026-07-01T01:00:00Z", decided="2026-07-01T01:03:00Z")
WARNING = make("warning", previous_level="watch", created="2026-07-01T02:00:00Z", decided="2026-07-01T02:04:00Z")
CRITICAL = make("critical", previous_level="warning", created="2026-07-01T03:00:00Z", decided="2026-07-01T03:02:00Z",
                trace={"rain_level": "critical", "river_level": "warning", "rules_fired": ["rain_24h>=204.5mm"]})
POOL = [WATCH, WARNING, CRITICAL]


@pytest.mark.parametrize("alert", [
    WATCH, WARNING, CRITICAL,
    make("critical", status="auto_sent_unapproved"),
    make("critical", status="failsafe", trace={}),
    make("watch", replay=True),
    make("warning", trace={"drill": True, "rules_fired": ["drill"]}),
    make("warning", village=SUJANPUR),
], ids=["watch", "update-warning", "update-critical-flash", "auto-sent", "failsafe", "replay", "drill", "hamirpur"])
def test_every_alert_kind_passes_the_profile(alert):
    village = SUJANPUR if alert.village_id == "sujanpur" else GOHAR
    checked(cap.render(alert, village, sender=SENDER, web_url=WEB, refs=cap.references(alert, POOL)))


def test_update_references_every_alert_still_in_force():
    root = checked(cap.render(CRITICAL, GOHAR, sender=SENDER, web_url=WEB, refs=cap.references(CRITICAL, POOL)))
    assert root.find("cap:msgType", NS).text == "Update"
    ids = [r.split(",")[1] for r in root.find("cap:references", NS).text.split()]
    assert ids == [WATCH.id, WARNING.id]
    codes = {e.text for e in root.findall("cap:info/cap:eventCode/cap:value", NS)}
    assert codes == {"OET-079"}  # rain drove it above the river: flash flood, in both languages


def test_cancel_when_the_village_returns_to_normal():
    clear = cap.all_clear(GOHAR, [*POOL, make("watch", village=SUJANPUR)])
    assert clear is not None and [c.id for c in clear.cancels] == [WATCH.id, WARNING.id, CRITICAL.id]
    root = checked(cap.render_all_clear(clear, sender=SENDER, web_url=WEB))
    assert root.find("cap:msgType", NS).text == "Cancel" and root.find("cap:status", NS).text == "Actual"
    assert root.find("cap:identifier", NS).text == "allclear-gohar-20260701060000"
    assert root.find("cap:sent", NS).text == "2026-07-01T11:30:00+05:30"
    refs = root.find("cap:references", NS).text.split()
    assert [r.split(",")[1] for r in refs] == [WATCH.id, WARNING.id, CRITICAL.id]
    infos = {i.find("cap:language", NS).text: i for i in root.findall("cap:info", NS)}
    assert set(infos) == {"hi-IN", "en-IN"}
    for info in infos.values():
        assert info.find("cap:responseType", NS).text == "AllClear"
        assert info.find("cap:urgency", NS).text == "Past"
        assert info.find("cap:eventCode/cap:value", NS).text == "OET-079"  # same event as the latest alert
        assert info.find("cap:area/cap:geocode/cap:value", NS).text == "22"
    assert infos["en-IN"].find("cap:headline", NS).text.startswith("All clear: Gohar (Mandi)")
    assert "ख़तरा टल गया" in infos["hi-IN"].find("cap:headline", NS).text
    assert "11:30 IST" in infos["en-IN"].find("cap:description", NS).text
    assert "112" in infos["hi-IN"].find("cap:instruction", NS).text


def test_no_cancel_unless_a_live_published_alert_is_still_in_force():
    assert cap.all_clear(GOHAR.model_copy(update={"level": "watch"}), POOL) is None  # not back to normal
    assert cap.all_clear(GOHAR.model_copy(update={"level_since": None}), POOL) is None  # never left normal
    assert cap.all_clear(GOHAR.model_copy(update={"replay": True}), POOL) is None  # replay owns the level
    assert cap.all_clear(GOHAR.model_copy(update={"level_since": "2026-07-02T06:00:00Z"}), POOL) is None  # expired
    assert cap.all_clear(GOHAR, [make("watch", replay=True), make("warning", status="declined")]) is None
    assert cap.all_clear(GOHAR, [make("warning", created="2026-07-01T07:00:00Z")]) is None  # raised after
    # Approved after the village fell back: the Cancel is sent then, so the reference is not postdated.
    late = make("warning", created="2026-07-01T05:50:00Z", decided="2026-07-01T06:20:00Z")
    clear = cap.all_clear(GOHAR, [late])
    assert clear is not None and cap.cap_time(clear.sent) == "2026-07-01T11:50:00+05:30"
    checked(cap.render_all_clear(clear, sender=SENDER, web_url=WEB))


def test_the_checker_catches_each_broken_rule():
    """The checks are real: each one fires on a message broken in that way."""
    good = cap.render(CRITICAL, GOHAR, sender=SENDER, web_url=WEB, refs=cap.references(CRITICAL, POOL))
    assert profile_errors(good) == []

    def broken(old: str, new: str) -> list[str]:
        xml = good.decode("utf-8")
        assert old in xml, old
        return profile_errors(xml.replace(old, new, 1).encode("utf-8"))

    first_ref = f"{SENDER},{WATCH.id},"
    assert "UPDATE_OR_CANCEL_MUST_REFERENCE" in profile_errors(
        cap.render(CRITICAL, GOHAR, sender=SENDER, web_url=WEB).replace(b">Alert<", b">Update<"))
    assert any(e.startswith("CIRCULAR") for e in broken(first_ref, f"{SENDER},{CRITICAL.id},"))
    assert any(e.startswith("POSTDATED") for e in broken(cap.cap_time(cap.sent_at(WATCH)), "2026-07-02T00:00:00+05:30"))
    assert any(e.startswith("EVENT_CODES_MUST_MATCH") for e in
               profile_errors(good.replace(b"OET-079", b"OET-081", 1)))
    assert any(e.startswith("CATEGORIES_MUST_MATCH") for e in broken("<category>Met", "<category>Geo"))
    assert any(e.startswith("EFFECTIVE_NOT_AFTER") for e in broken("<effective>2026", "<effective>2027"))
    assert any(e.startswith("HEADLINE_TOO_LONG") for e in broken("<headline>", "<headline>" + "x" * 140))
    assert any(e.startswith("CIRCLE_POLYGON_OR_GEOCODE") for e in
               profile_errors(_strip(good, ("circle", "geocode"))))
    assert any(e.startswith("WEB_IS_REQUIRED") for e in profile_errors(_strip(good, ("web",))))
    assert "UNKNOWN_VALUE_DISCOURAGED" in broken("<certainty>Likely", "<certainty>Unknown")
    assert any(e.startswith("AREA_DESC_TOO_LONG") for e in broken("<areaDesc>", "<areaDesc>" + "x" * 50))


def _strip(xml: bytes, tags: tuple[str, ...]) -> bytes:
    root = ET.fromstring(xml)
    for parent in root.iter():
        for child in list(parent):
            if child.tag in {f"{{{cap.CAP_NS}}}{t}" for t in tags}:
                parent.remove(child)
    return ET.tostring(root, encoding="utf-8")


def test_feed_checker_catches_duplicate_ids_and_missing_links():
    feed = cap.atom(POOL, api_base="https://api.example", web_url=WEB)
    assert feed_errors(feed) == []
    root = ET.fromstring(feed)
    entries = root.findall("atom:entry", NS)
    entries[1].find("atom:id", NS).text = entries[0].find("atom:id", NS).text
    for link in entries[2].findall("atom:link", NS):
        link.set("type", "text/html")
    errors = feed_errors(ET.tostring(root))
    assert any(e.startswith("ATOM_ENTRY_NON_UNIQUE_IDS") for e in errors)
    assert "ATOM_ENTRY_MISSING_CAP_LINK entry[3]" in errors


# -- end to end through the API ------------------------------------------------

@pytest.fixture()
def client(repo, monkeypatch):
    from Pukaar.api.routers import public
    from Pukaar.main import app

    monkeypatch.setattr(public, "get_repo", lambda: repo)
    return TestClient(app)


def test_feed_and_every_message_pass_the_profile(client, repo):
    for a in POOL:
        repo.put_alert(a)
    repo.put_alert(make("critical", status="pending"))  # never published
    repo.update_village("gohar", level="normal", level_since=GOHAR.level_since)

    feed = client.get("/cap/alerts.atom", headers={"x-forwarded-proto": "https", "host": "api.example"})
    assert feed.status_code == 200 and feed_errors(feed.content) == []
    hrefs = [e.find("atom:link[@type='application/cap+xml']", NS).get("href")
             for e in ET.fromstring(feed.content).findall("atom:entry", NS)]
    assert hrefs[0] == "https://api.example/cap/alerts/allclear-gohar-20260701060000.xml"  # newest first
    assert len(hrefs) == 4

    published: dict[str, str] = {}
    for href in reversed(hrefs):  # oldest first, so every reference points back to a message already seen
        r = client.get(href.removeprefix("https://api.example"))
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/cap+xml")
        root = checked(r.content)
        for ref in (_t(root, "cap:references") or "").split():
            _, ident, sent = ref.split(",")
            assert published[ident] == sent  # references a message the feed published, at its own sent time
        published[_t(root, "cap:identifier")] = _t(root, "cap:sent")
    types = [ET.fromstring(client.get(h.removeprefix("https://api.example")).content).find("cap:msgType", NS).text
             for h in hrefs]
    assert types == ["Cancel", "Update", "Update", "Alert"]

    # Once the village rises again its state no longer describes the all-clear: gone from the feed, 404.
    repo.update_village("gohar", level="watch", level_since="2026-07-01T07:00:00Z")
    assert client.get("/cap/alerts/allclear-gohar-20260701060000.xml").status_code == 404
    assert "allclear" not in client.get("/cap/alerts.atom").text
    assert client.get("/cap/alerts/allclear-nowhere-20260701060000.xml").status_code == 404
