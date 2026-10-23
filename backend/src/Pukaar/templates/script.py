"""The five-element alert script (Mileti and Sorensen; NIST "Communicating the Emergency").

People act on a warning that names, in this order: who is speaking (the source), what is coming (the
hazard), where (the exact place), when (the timing) and what to do (the protective action, ending with
where to go). Every alert text Pukaar sends, the fixed template and a checked model draft alike, is
built here from those five parts, Hindi first and English after:

  1. source    "जिला आपदा प्रबंधन प्राधिकरण मंडी की ओर से": the DDMA speaks; Pukaar is its tool
  2. hazard    the level word and what the rules saw (heavy rain, a rising river, or both)
  3. place     the village and its district, and "near streams and slopes"
  4. timing    "अभी" (now) when something was observed, else "अगले N घंटे में" from the forecast
  5. action    the fixed safety line for the level, then where to go: the nearest safe place a person
               marked OPEN or STANDBY, else "the nearest high, safe ground"

Code decides every part. A model draft may add one checked advice line after the hazard; it never
replaces a part. The Hindi needs a native speaker's review before real use (docs/MESSAGES.md).

Voice is billed by the minute: spoken_seconds() estimates how long the call takes to say the Hindi
text and the "press 1" menu, and voice_check() flags a script over VOICE_LIMIT_SECONDS (55 s), which
would run past the first minute once the call connects and the menu repeats.
"""

from __future__ import annotations

import re
from typing import Any

from Pukaar.templates import hi

# -- 1. source --------------------------------------------------------------------------------------
SOURCE_HI = "जिला आपदा प्रबंधन प्राधिकरण {district} की ओर से"
SOURCE_HI_NO_DISTRICT = "जिला आपदा प्रबंधन प्राधिकरण की ओर से"
SOURCE_EN = "From the District Disaster Management Authority, {district}"
SOURCE_EN_NO_DISTRICT = "From the District Disaster Management Authority"

# -- 2. hazard --------------------------------------------------------------------------------------
HAZARD_HI = {
    "rain": "भारी बारिश से नदी-नालों में अचानक बाढ़ और भूस्खलन का ख़तरा",
    "river": "नदी का पानी बढ़ने से बाढ़ का ख़तरा",
    "both": "भारी बारिश और बढ़ती नदी से बाढ़ और भूस्खलन का ख़तरा",
    "flood": "बाढ़ का ख़तरा",
}
HAZARD_EN = {
    "rain": "flash floods and landslides from heavy rain",
    "river": "flooding as the river rises",
    "both": "floods and landslides from heavy rain and a rising river",
    "flood": "flood danger",
}

# -- 3. place ---------------------------------------------------------------------------------------
PLACE_HI = "{village} ({district}) में, ख़ासकर नदी-नालों और ढलानों के पास"
PLACE_HI_NO_DISTRICT = "{village} में, ख़ासकर नदी-नालों और ढलानों के पास"
PLACE_EN = "in {village} ({district}), above all near streams and slopes"
PLACE_EN_NO_DISTRICT = "in {village}, above all near streams and slopes"

# -- 4. timing --------------------------------------------------------------------------------------
NOW_HI, NOW_EN = "अभी", "now"
HOURS_HI, HOURS_EN = "अगले {h} घंटे में", "in the next {h} hours"
# Forecast hours are rounded up to one of these; the drafting checker already allows each number.
HOUR_STEPS = (6, 12, 24, 48)

# -- 5. where to go, when nobody has confirmed a named safe place --------------------------------------
GO_HIGH_HI = "कहाँ जाएँ: पास की ऊँची और सुरक्षित जगह पर।"
GO_HIGH_EN = "Where to go: the nearest high, safe ground."

# Rule families (risk_rules tags) by what they mean for the hazard and the timing.
_RAIN = ("rain_24h", "rain_intensity", "rain_burst", "rain_obs:")
_RIVER = ("discharge", "river_ensemble:", "gauge>=", "gauge_rising_fast", "staff_gauge", "official:")
# Something seen now, not forecast: the timing is "now".
_OBSERVED = ("gauge>=", "gauge_rising_fast", "staff_gauge", "verified_reports", "verified_impact_report",
             "rain_obs:", "gauge_silent_in_rain")

# Voice: Polly Hindi at its default rate, measured on the fixed templates; generous on purpose, so the
# estimate errs long. One pause per sentence.
WORDS_PER_SECOND = 2.3
PAUSE_SECONDS = 0.4
VOICE_LIMIT_SECONDS = 55.0


def _rules(trace: dict[str, Any] | None) -> list[str]:
    return [str(r) for r in ((trace or {}).get("rules_fired") or [])]


def hazard_key(trace: dict[str, Any] | None) -> str:
    rules = _rules(trace)
    rain = any(r.startswith(_RAIN) for r in rules)
    river = any(r.startswith(_RIVER) for r in rules)
    return "both" if rain and river else "rain" if rain else "river" if river else "flood"


def observed_now(trace: dict[str, Any] | None) -> bool:
    return any(r.startswith(_OBSERVED) for r in _rules(trace))


def timing(level: str, trace: dict[str, Any] | None) -> tuple[str, str]:
    """"Now" for a Critical or anything observed; else the forecast hours rounded up to 6, 12, 24 or 48.
    Never a promise of lead time: a forecast window says "within", never "in exactly"."""
    if level == "critical" or observed_now(trace):
        return NOW_HI, NOW_EN
    hours = None
    nc = (trace or {}).get("nowcast")
    if isinstance(nc, dict) and isinstance(nc.get("hours"), (int, float)) and nc["hours"] > 0:
        hours = float(nc["hours"])
    rules = _rules(trace)
    if hours is None:
        hours = 48.0 if any(r.startswith(("discharge", "river_ensemble:")) for r in rules) and not any(
            r.startswith(_RAIN) for r in rules) else 24.0
    step = next((h for h in HOUR_STEPS if hours <= h), HOUR_STEPS[-1])
    return HOURS_HI.format(h=step), HOURS_EN.format(h=step)


def source(district_hi: str | None, district_en: str | None) -> tuple[str, str]:
    d_hi, d_en = (district_hi or district_en or "").strip(), (district_en or district_hi or "").strip()
    return (SOURCE_HI.format(district=d_hi) if d_hi else SOURCE_HI_NO_DISTRICT,
            SOURCE_EN.format(district=d_en) if d_en else SOURCE_EN_NO_DISTRICT)


def place(village_hi: str, village_en: str, district_hi: str | None, district_en: str | None) -> tuple[str, str]:
    d_hi, d_en = (district_hi or district_en or "").strip(), (district_en or district_hi or "").strip()
    return (PLACE_HI.format(village=village_hi, district=d_hi) if d_hi else PLACE_HI_NO_DISTRICT.format(village=village_hi),
            PLACE_EN.format(village=village_en, district=d_en) if d_en else PLACE_EN_NO_DISTRICT.format(village=village_en))


def where_to_go(safe_place: dict | None) -> tuple[str, str]:
    named_hi, named_en = hi.safe_place_lines(safe_place)
    return (named_hi, named_en) if named_hi else (GO_HIGH_HI, GO_HIGH_EN)


def _tidy(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _sentence(text: str, stop: str) -> str:
    text = text.strip()
    if not text:
        return ""
    return text if text[-1] in "।.!?" else text + stop


def compose(level: str, village_hi: str, village_en: str, *, district_hi: str | None = None,
            district_en: str | None = None, trace: dict[str, Any] | None = None, safe_place: dict | None = None,
            advice_hi: str = "", advice_en: str = "") -> tuple[str, str]:
    """The alert in Hindi and English, in the five-element order; advice_* is an optional checked model line."""
    src_hi, src_en = source(district_hi, district_en)
    key = hazard_key(trace)
    at_hi, at_en = place(village_hi, village_en, district_hi, district_en)
    when_hi, when_en = timing(level, trace)
    go_hi, go_en = where_to_go(safe_place)
    text_hi = (f"{src_hi}, पुकार: {hi.LEVEL_HI[level]}। {HAZARD_HI[key]}, {at_hi}, {when_hi}। "
               f"{_sentence(advice_hi, '।')} {hi.CALL_112_HI} {hi.SAFETY_HI[level]} {go_hi}")
    text_en = (f"{src_en} (Pukaar): {hi.LEVEL_EN[level]}. {HAZARD_EN[key][0].upper()}{HAZARD_EN[key][1:]}, "
               f"{at_en}, {when_en}. {_sentence(advice_en, '.')} {hi.CALL_112_EN} {hi.SAFETY_EN[level]} {go_en}")
    return _tidy(text_hi), _tidy(text_en)


def elements(text_hi: str, level: str, village_hi: str, safe_place: dict | None = None) -> dict[str, bool]:
    """Which of the five elements a Hindi text carries (tests, and the console's draft check)."""
    go_hi, _ = where_to_go(safe_place)
    return {
        "source": text_hi.lstrip().removeprefix("अभ्यास (DRILL), असली चेतावनी नहीं।").strip().startswith(
            SOURCE_HI_NO_DISTRICT.split(" की ओर से")[0]),
        "hazard": hi.LEVEL_HI[level] in text_hi and "ख़तरा" in text_hi,
        "place": village_hi in text_hi,
        "timing": NOW_HI in text_hi or "अगले" in text_hi,
        "action": hi.SAFETY_HI[level] in text_hi and text_hi.rstrip().endswith(go_hi),
    }


# -- voice length -------------------------------------------------------------------------------------
def spoken_seconds(text: str) -> float:
    """An estimate of how long Polly takes to say text: words at WORDS_PER_SECOND, plus a pause per sentence."""
    words = len(re.findall(r"\S+", text))
    sentences = max(1, len(re.findall(r"[।.!?]", text)))
    return round(words / WORDS_PER_SECOND + sentences * PAUSE_SECONDS, 1)


def voice_check(text_hi: str) -> dict[str, Any]:
    """The spoken alert plus the "press 1" menu, against the 55-second limit (voice is billed per minute)."""
    alert_s, menu_s = spoken_seconds(text_hi), spoken_seconds(hi.VOICE_MENU_HI)
    total = round(alert_s + menu_s, 1)
    return {"alert_seconds": alert_s, "menu_seconds": menu_s, "total_seconds": total,
            "limit_seconds": VOICE_LIMIT_SECONDS, "over": total > VOICE_LIMIT_SECONDS}


def note_voice_length(repo: Any, alert_id: str, text_hi: str) -> dict[str, Any]:
    """Warn when the spoken alert and the menu run past 55 s: on the alert timeline (the officer sees it before
    approving), in the log and as the metric VoiceScriptLong. Never raises; returns the check."""
    check = voice_check(text_hi)
    if not check["over"]:
        return check
    try:
        from Pukaar.core.log import get_logger, log, metric

        log(get_logger("script"), "voice script over the limit", 30, alert_id=alert_id,
            seconds=check["total_seconds"], limit=VOICE_LIMIT_SECONDS)
        metric("VoiceScriptLong", 1)
        repo.add_timeline(alert_id, "voice_long",
                          f"the spoken alert and the 'press 1' menu take about {check['total_seconds']:g} s, over "
                          f"{VOICE_LIMIT_SECONDS:g} s: a call may run into a second billed minute; shorten the text")
    except Exception:
        pass
    return check


def district_names(repo: Any, village_id: str, district_en: str = "") -> tuple[str | None, str | None]:
    """(Hindi, English) district name for a village, from its record (data/districts.json at seed)."""
    try:
        v = repo.get_village(village_id)
    except Exception:
        v = None
    if v is None:
        return None, district_en or None
    from Pukaar.services.cap import district_hi

    return district_hi(v), v.district


def fallback_for_alert(repo: Any, alert: Any) -> tuple[str, str]:
    """The fixed five-element text for a stored alert (auto-send, failsafe): its own trace and safe place."""
    d_hi, d_en = district_names(repo, alert.village_id, getattr(alert, "district", "") or "")
    trace = alert.decision_trace or {}
    return hi.fallback_alert(alert.level, alert.village_name_hi, alert.village_name, trace.get("safe_place"),
                             district_hi=d_hi, district_en=d_en, trace=trace)
