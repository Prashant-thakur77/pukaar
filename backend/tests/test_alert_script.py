"""The five-element alert script (templates/script.py): source, hazard, place, timing, action ending with where to go,
and the 55-second voice limit."""

from __future__ import annotations

import pytest

from Pukaar.templates import hi, script

PLACE = {"name": "Government Senior Secondary School Thunag", "name_hi": "राजकीय वरिष्ठ माध्यमिक विद्यालय थुनाग"}
RAIN = {"rules_fired": ["rain_24h>=115.6mm:warning"]}
RIVER = {"rules_fired": ["discharge>=2.5:warning"]}
BOTH = {"rules_fired": ["rain_24h>=64.5mm:watch", "river_ensemble:P(watch)=0.4>=0.3:watch", "two_sources_agree:+1"]}
GAUGE = {"rules_fired": ["gauge>=180cm:warning"]}


@pytest.mark.parametrize("level", ["watch", "warning", "critical"])
@pytest.mark.parametrize("trace", [RAIN, RIVER, BOTH, GAUGE, {}])
@pytest.mark.parametrize("place", [PLACE, None])
def test_every_fixed_script_has_the_five_elements_in_order(level, trace, place):
    text_hi, text_en = hi.fallback_alert(level, "थुनाग", "Thunag", place, district_hi="मंडी", district_en="Mandi",
                                         trace=trace)
    assert all(script.elements(text_hi, level, "थुनाग", place).values()), text_hi
    # 1. the DDMA speaks first, in both languages
    assert text_hi.startswith("जिला आपदा प्रबंधन प्राधिकरण मंडी की ओर से")
    assert text_en.startswith("From the District Disaster Management Authority, Mandi")
    # 2-4 in order: the level word and hazard, then the place, then the timing
    i_level, i_place = text_hi.index(hi.LEVEL_HI[level]), text_hi.index("थुनाग (मंडी)")
    i_when = text_hi.index("अभी") if "अभी" in text_hi else text_hi.index("अगले")
    assert i_level < i_place < i_when
    # 5. the action, ending with where to go
    go_hi, go_en = script.where_to_go(place)
    assert text_hi.endswith(go_hi) and text_en.endswith(go_en)
    assert text_hi.index(hi.SAFETY_HI[level]) < text_hi.index(go_hi)
    assert hi.CALL_112_HI in text_hi and hi.CALL_112_EN in text_en


def test_the_hazard_names_what_the_rules_saw():
    assert "भारी बारिश" in hi.fallback_alert("warning", "गोहर", "Gohar", trace=RAIN)[0]
    assert "नदी का पानी बढ़ने" in hi.fallback_alert("warning", "गोहर", "Gohar", trace=RIVER)[0]
    assert "बढ़ती नदी" in hi.fallback_alert("watch", "गोहर", "Gohar", trace=BOTH)[0]
    assert "flash floods" in hi.fallback_alert("warning", "गोहर", "Gohar", trace=RAIN)[1].lower()


def test_timing_is_now_when_observed_and_a_rounded_window_when_forecast():
    assert script.timing("critical", RAIN) == ("अभी", "now")
    assert script.timing("warning", GAUGE) == ("अभी", "now")
    assert script.timing("watch", {"rules_fired": ["gauge_silent_in_rain:watch"]})[0] == "अभी"
    assert script.timing("warning", RAIN) == ("अगले 24 घंटे में", "in the next 24 hours")
    assert script.timing("watch", RIVER)[0] == "अगले 48 घंटे में"  # river only, no nowcast: the 2-day window
    assert script.timing("warning", {**RAIN, "nowcast": {"hours": 5.2}})[0] == "अगले 6 घंटे में"
    assert script.timing("warning", {**RAIN, "nowcast": {"hours": 30}})[0] == "अगले 48 घंटे में"
    assert script.timing("warning", {**RAIN, "nowcast": {"hours": 300}})[0] == "अगले 48 घंटे में"  # never longer


def test_without_a_district_the_source_is_still_the_ddma():
    text_hi, text_en = hi.fallback_alert("watch", "गोहर", "Gohar")
    assert text_hi.startswith("जिला आपदा प्रबंधन प्राधिकरण की ओर से")
    assert text_en.startswith("From the District Disaster Management Authority (Pukaar)")


def test_a_drill_label_in_front_keeps_the_elements():
    text_hi, _ = hi.fallback_alert("warning", "गोहर", "Gohar", district_hi="मंडी", trace=RAIN)
    assert all(script.elements(f"अभ्यास (DRILL), असली चेतावनी नहीं। {text_hi}", "warning", "गोहर").values())


@pytest.mark.parametrize("level", ["watch", "warning", "critical"])
def test_every_fixed_script_and_the_menu_fit_in_55_seconds(level):
    # The longest names the five villages and their baked safe places can give.
    text_hi, _ = hi.fallback_alert(level, "जंजैहली", "Janjehli", PLACE, district_hi="हमीरपुर", district_en="Hamirpur",
                                   trace=BOTH)
    check = script.voice_check(text_hi)
    assert not check["over"] and check["total_seconds"] <= 55, check
    assert check["menu_seconds"] > 0


def test_a_long_script_is_flagged_on_the_timeline(repo):
    from Pukaar.core import clock
    from Pukaar.store.models import Alert

    stamp = clock.iso(clock.now())
    repo.put_alert(Alert(id="alr_long", village_id="gohar", village_name="Gohar", village_name_hi="गोहर",
                         level="warning", status="pending", created_at=stamp, updated_at=stamp))
    long_hi = " ".join(["नदी-नालों से दूर रहें।"] * 40)
    assert script.voice_check(long_hi)["over"]
    script.note_voice_length(repo, "alr_long", long_hi)
    assert any(t.step == "voice_long" and "55" in t.detail for t in repo.list_timeline("alr_long"))
    short, _ = hi.fallback_alert("watch", "गोहर", "Gohar")
    assert not script.note_voice_length(repo, "alr_long", short)["over"]
    assert sum(1 for t in repo.list_timeline("alr_long") if t.step == "voice_long") == 1


def test_the_draft_step_writes_the_ddma_script(repo, frozen):
    from Pukaar.core.ids import new_id
    from Pukaar.store.models import Alert
    from Pukaar.workflow.steps import Steps

    from Pukaar.core import clock

    stamp = clock.iso(clock.now())
    a = Alert(id=new_id("alr"), village_id="gohar", village_name="Gohar", village_name_hi="गोहर", level="warning",
              status="drafting", created_at=stamp, updated_at=stamp, decision_trace=RAIN, district="Mandi")
    repo.put_alert(a)
    Steps(repo, None, synthesize=lambda *_: None).handle({"step": "draft", "alert_id": a.id})
    got = repo.get_alert(a.id)
    assert got.text_hi.startswith("जिला आपदा प्रबंधन प्राधिकरण मंडी की ओर से")
    assert all(script.elements(got.text_hi, "warning", "गोहर").values())
    # The auto-send and failsafe text is the same five-element script, read from the stored alert.
    fixed_hi, _ = script.fallback_for_alert(repo, got)
    assert fixed_hi.startswith("जिला आपदा प्रबंधन प्राधिकरण मंडी") and "भारी बारिश" in fixed_hi
