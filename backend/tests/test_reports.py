from datetime import timedelta

import pytest

from Pukaar.services import reports as svc
from Pukaar.services.report_structuring import keyword_parse, structure

# Hindi report set: Devanagari and Roman script (needs native-speaker review).
HINDI_SET = [
    ("नाले में पानी बहुत तेज़ी से बढ़ रहा है", "water_rising", "high"),
    ("pani badh raha hai khad mein", "water_rising", "medium"),
    ("सड़क बंद हो गई, मलबा आ गया", "landslide", "high"),
    ("sadak band hai thunag ki taraf", "road_cut", "medium"),
    ("पुल टूट गया है", "bridge_unsafe", "high"),
    ("pul beh gaya", "bridge_unsafe", "critical"),
    ("घर में पानी घुस गया", "homes_affected", "high"),
    ("लोग फँसे हैं, बचाओ", "people_trapped", "critical"),
    ("badal phata hai upar gaon mein", "landslide", "critical"),
    ("सब ठीक है, पानी कम है", "other", "low"),
]


@pytest.mark.parametrize("text,type_,severity", HINDI_SET)
def test_hindi_keyword_parser(text, type_, severity):
    r = keyword_parse(text)
    assert (r.report_type, r.severity) == (type_, severity)
    assert r.reply_hi  # every report gets a Hindi reply


def test_model_result_merges_and_more_severe_wins():
    class Model:
        def structure_report(self, text, village):
            return {"report_type": "road_cut", "severity": "low", "summary_en": "Road blocked", "reply_hi": "ठीक है"}

    r = structure("लोग फँसे हैं", "Thunag", Model())
    assert r.severity == "critical" and r.report_type == "people_trapped" and r.parser_source == "model+rules"
    assert "112" in r.reply_hi  # urgent reply stays the fixed safety text


def _intake(repo, text="sadak band", lat=31.5600, lon=77.1650, name="a", **kw):
    return svc.intake(repo, repo.get_village("thunag"), text=text, lat=lat, lon=lon, reporter_name=name, **kw)


def test_report_without_text_keeps_audio_and_waits_for_transcript(repo, frozen):
    r = _intake(repo, text="", audio=(b"RIFF....", "audio/webm;codecs=opus"))
    assert r.state == "transcribing" and r.audio_key.endswith(".webm")
    processed = svc.process(repo, r.id, None)
    assert processed.state == "unverified" and "transcription_unavailable" in processed.flags
    assert processed.audio_key  # never lost


def test_sos_pin_within_25m_and_1h_is_flagged_duplicate(repo, frozen):
    first = _intake(repo)
    second = _intake(repo, lat=31.56005, name="a")
    assert "possible_duplicate" in second.flags and f"duplicate_of:{first.id}" in second.flags


def test_two_agreeing_reports_verify_each_other(repo, frozen, workflow):
    a = _intake(repo, name="a")
    b = _intake(repo, lat=31.5630, name="b")  # ~330 m away, same type
    svc.process(repo, a.id, None, workflow=workflow)
    svc.process(repo, b.id, None, workflow=workflow)
    assert repo.get_report(a.id).state == "verified_auto"
    assert repo.get_report(b.id).state == "verified_auto"
    # a verified road-cut report floors the village at warning and opens an alert
    assert repo.get_village("thunag").level == "warning" and workflow.started


def test_reports_outside_the_village_do_not_verify(repo, frozen):
    a = _intake(repo, lat=31.70, lon=77.40, name="a")
    b = _intake(repo, lat=31.7003, lon=77.40, name="b")
    svc.process(repo, a.id, None)
    svc.process(repo, b.id, None)
    assert repo.get_report(b.id).state == "unverified"


def test_reports_far_apart_in_time_do_not_verify(repo, frozen):
    a = _intake(repo, name="a")
    frozen["now"] += timedelta(minutes=45)
    b = _intake(repo, lat=31.5630, name="b")
    svc.process(repo, b.id, None)
    assert repo.get_report(b.id).state == "unverified" and repo.get_report(a.id).state == "unverified"


def test_tracking_code_shows_steps(repo, frozen):
    r = _intake(repo)
    found = repo.report_by_track(r.track_code)
    steps = svc.track_steps(found)
    assert [s["key"] for s in steps] == ["received", "verified", "acted_on"]
    assert [s["done"] for s in steps] == [True, False, False]
