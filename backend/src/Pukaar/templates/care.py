"""Fixed texts for the assisted-household check and the "why we warned" follow-up. Hindi first, English after.
Needs review by a native Hindi speaker before real use (docs/MESSAGES.md). Names are first names only.
"""

from __future__ import annotations

from Pukaar.templates import hi

CHECKED_BUTTON = "✅ देख लिया / Checked"
CHECK_THANKS = "धन्यवाद, दर्ज हो गया। · Thank you, recorded."
CHECK_SAME = "पहले ही दर्ज है। · Already recorded."
CHECK_NOT_YOURS = "यह अनुरोध आपके लिए नहीं था। · This request was not for you."

ASSISTED_REASON_HI = {"elderly": "बुज़ुर्ग", "disabled": "दिव्यांग", "alone": "अकेले रहते हैं", "pregnant": "गर्भवती",
                      "other": "मदद चाहिए"}
ASSISTED_REASON_EN = {"elderly": "elderly", "disabled": "disabled", "alone": "lives alone", "pregnant": "pregnant",
                      "other": "needs help"}


def first_name(name: str | None) -> str:
    return (name or "").strip().split(" ")[0] or "?"


def assisted_check(person: str, reason: str | None, village_hi: str, village_en: str, level: str, minutes: int,
                   drill: bool = False) -> str:
    """To the named neighbour or relay: an assisted household has not confirmed the alert."""
    label_hi, label_en = ("अभ्यास (DRILL): ", "DRILL: ") if drill else ("", "")
    why_hi = f" ({ASSISTED_REASON_HI[reason]})" if reason in ASSISTED_REASON_HI else ""
    why_en = f" ({ASSISTED_REASON_EN[reason]})" if reason in ASSISTED_REASON_EN else ""
    return (f"पुकार, {label_hi}{village_hi}: {person}{why_hi} ने {minutes} मिनट में चेतावनी ({hi.LEVEL_HI[level]}) की "
            f"पुष्टि नहीं की। कृपया जाकर या फ़ोन करके बताएँ और सुरक्षित जगह जाने में मदद करें, फिर “देख लिया” दबाएँ। "
            f"जान का ख़तरा हो तो 112।\n"
            f"Pukaar, {label_en}{village_en}: {person}{why_en} has not confirmed the {hi.LEVEL_EN[level]} alert in "
            f"{minutes} min. Please go or call, help them to safety, then press “Checked”. If life is at risk, call 112.")


# -- the "why we warned" note, once per alert after it ends (services/followup.py) ---------------------
SEEN_HI = {
    "rain": "भारी बारिश का अनुमान या मापी गई बारिश",
    "river": "नदी का पानी बढ़ने का अनुमान या गेज पर बढ़ता पानी",
    "both": "भारी बारिश और नदी का बढ़ता पानी",
    "reports": "गाँव से मिली सूचनाएँ",
    "gauge_silent": "बारिश के बीच नदी के गेज का बंद हो जाना",
    "flood": "बाढ़ के संकेत",
}
SEEN_EN = {
    "rain": "heavy rain, forecast or measured",
    "river": "the river rising, forecast or on the gauge",
    "both": "heavy rain and a rising river",
    "reports": "reports from the village",
    "gauge_silent": "the river gauge going silent while it rained",
    "flood": "signs of a flood",
}
HAPPENED_HI = {
    "real_flood": "बाढ़ या नुक़सान दर्ज हुआ।",
    "no_flood": "इस बार बाढ़ नहीं आई। जल्दी चेतावनी देना ही सुरक्षा है: अगली बार भी ध्यान दें।",
    "unknown": "अधिकारी अभी पता कर रहे हैं कि क्या हुआ।",
    None: "ख़तरा टल गया है।",
}
HAPPENED_EN = {
    "real_flood": "A flood or damage was recorded.",
    "no_flood": "No flood came this time. Warning early is how we keep you safe: please heed the next one too.",
    "unknown": "Officers are still finding out what happened.",
    None: "The danger has passed.",
}


def why_we_warned(village_hi: str, village_en: str, level: str, seen: str, outcome: str | None, confirmed: bool,
                  drill: bool = False) -> str:
    """One short note after an alert ends: what was seen, what happened, and thanks for confirming."""
    label_hi, label_en = ("अभ्यास (DRILL): ", "DRILL: ") if drill else ("", "")
    happened_hi = HAPPENED_HI.get(outcome, HAPPENED_HI[None])
    happened_en = HAPPENED_EN.get(outcome, HAPPENED_EN[None])
    thanks_hi = ("“मिल गया” दबाने के लिए धन्यवाद: इससे अधिकारी जान पाए कि आप तक संदेश पहुँचा।" if confirmed else
                 "अगली बार संदेश मिलते ही “मिल गया” दबाएँ, ताकि अधिकारी जान सकें कि आप तक पहुँचा।")
    thanks_en = ("Thank you for pressing “मिल गया”: it told the officers the warning reached you." if confirmed else
                 "Next time please press “मिल गया” when the warning arrives, so officers know it reached you.")
    return (f"पुकार, {label_hi}{village_hi}: हमने {hi.LEVEL_HI[level]} की चेतावनी क्यों दी? हमने देखा: "
            f"{SEEN_HI.get(seen, SEEN_HI['flood'])}। {happened_hi} {thanks_hi}\n"
            f"Pukaar, {label_en}{village_en}: why we sent a {hi.LEVEL_EN[level]} alert. We saw "
            f"{SEEN_EN.get(seen, SEEN_EN['flood'])}. {happened_en} {thanks_en}")
