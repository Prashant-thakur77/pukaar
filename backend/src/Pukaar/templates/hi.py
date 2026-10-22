"""Fixed safety text. Needs review by a native Hindi speaker before real use.

These sentences go out unchanged when the model is unavailable or its draft
fails the checker. The model never rewrites them; it may only fill the slots
in the drafting prompt.
"""

from __future__ import annotations

LEVEL_HI = {"normal": "सामान्य", "watch": "सतर्क रहें", "warning": "चेतावनी", "critical": "गंभीर ख़तरा"}
LEVEL_EN = {"normal": "Normal", "watch": "Watch", "warning": "Warning", "critical": "Critical"}

# One fixed safety line per level.
SAFETY_HI = {
    "watch": "नदी-नालों से दूर रहें और रात में सतर्क रहें।",
    "warning": "नदी-नालों और ढलानों से दूर रहें। ज़रूरी सामान तैयार रखें और ऊँची, सुरक्षित जगह जाने के लिए तैयार रहें।",
    "critical": "तुरंत नदी-नालों और ढलानों से दूर ऊँची, सुरक्षित जगह पर जाएँ। पुल और नाले पार न करें।",
}
SAFETY_EN = {
    "watch": "Stay away from streams and stay alert at night.",
    "warning": "Keep away from streams and slopes. Keep essentials ready and be ready to move to high, safe ground.",
    "critical": "Move now to high, safe ground away from streams and slopes. Do not cross bridges or streams.",
}
# Optional line, only when a pradhan or officer has marked a baked safe place OPEN or STANDBY.
# The name comes from data/safe_places (OpenStreetMap) via the decision trace, never from a model.
SAFE_PLACE_HI = "सबसे पास सुरक्षित जगह: {name}।"
SAFE_PLACE_EN = "Nearest safe place: {name}."
CALL_112_HI = "आपात स्थिति में 112 पर कॉल करें।"
CALL_112_EN = "In an emergency call 112."
ACK_HI = "संदेश मिलने पर 'मिल गया' दबाएँ।"
ACK_BUTTON_HI = "मिल गया"

DIRECTIVE_HI = {
    "evacuate": "प्रशासन का आदेश: तुरंत सुरक्षित ऊँची जगह पर जाएँ।",
    "shelter_in_place": "प्रशासन का आदेश: जहाँ हैं वहीं सुरक्षित रहें, नदी-नालों की ओर न जाएँ।",
    "advisory": "प्रशासन की सलाह: सतर्क रहें और आगे की सूचना का इंतज़ार करें।",
    "all_clear": "प्रशासन की सूचना: ख़तरा टल गया है। फिर भी नदी-नालों से सावधान रहें।",
}
DIRECTIVE_EN = {
    "evacuate": "Administration order: move to safe high ground now.",
    "shelter_in_place": "Administration order: stay where you are and keep away from streams.",
    "advisory": "Administration advisory: stay alert and wait for further updates.",
    "all_clear": "Administration notice: the danger has passed. Still take care near streams.",
}

REPORT_THANKS_HI = "आपकी सूचना मिल गई है। अधिकारी इसे देखेंगे।"
REPORT_URGENT_HI = "आपकी सूचना मिल गई है। तुरंत सुरक्षित जगह जाएँ और 112 पर कॉल करें।"
LATE_REPLY_HI = "यह लिंक अब काम नहीं करता: इस चेतावनी पर फ़ैसला हो चुका है या समय समाप्त हो गया है।"
LATE_REPLY_EN = "This link no longer works: the alert was already decided or the time ran out."
INVALID_LINK_HI = "यह लिंक सही नहीं है। कृपया संदेश में आया पूरा लिंक खोलें या कंसोल से मंज़ूरी दें।"
INVALID_LINK_EN = "This link is not valid. Open the full link from the message, or approve from the console."
REFUSAL_HI = "मैं केवल बाढ़ से जुड़ी जानकारी दे सकता हूँ।"
REFUSAL_EN = "I can only answer questions about flood operations."

# "Surakshit Hoon" safety roll-call (sent only after a live alert reached the village, or by an officer).
ROLLCALL_SAFE_BUTTON_HI = "मैं सुरक्षित हूँ"
ROLLCALL_HELP_BUTTON_HI = "मदद चाहिए"
ROLLCALL_DRILL_HI = "अभ्यास (DRILL), असली चेतावनी नहीं।"
ROLLCALL_SAFE_THANKS_HI = "धन्यवाद, आप सुरक्षित दर्ज हो गए।"
ROLLCALL_HELP_THANKS_HI = "मदद का अनुरोध दर्ज हो गया।"
ROLLCALL_SAME_HI = "आपका जवाब पहले ही दर्ज है।"
ROLLCALL_CLOSED_HI = "यह रोल-कॉल बंद हो चुका है। मदद चाहिए तो 112 पर कॉल करें।"
ROLLCALL_NOT_ASKED_HI = "यह सवाल आपके लिए नहीं था। मदद चाहिए तो 112 पर कॉल करें।"
ROLLCALL_HELP_REPLY = ("पुकार: अधिकारी को बता दिया गया है कि आपको मदद चाहिए। जान का ख़तरा हो तो अभी 112 पर कॉल करें।\n"
                       "आप कहाँ हैं, एक छोटे संदेश में लिखें (जैसे: स्कूल के पास, छत पर, कितने लोग)।\n\n"
                       "Pukaar: the officer has been told you need help. If life is at risk, call 112 now. "
                       "Reply with one short message saying where you are.")
ROLLCALL_NOTE_THANKS = "पुकार: आपका संदेश अधिकारी तक पहुँच गया। 112 पर कॉल करें अगर जान का ख़तरा है।\nPukaar: your note reached the officer."


def rollcall_question(village_hi: str, village_en: str, exercise: bool) -> str:
    drill = f"{ROLLCALL_DRILL_HI}\n" if exercise else ""
    return (f"{drill}पुकार: क्या आप सुरक्षित हैं? / Are you safe?\n{village_hi} · {village_en}\n"
            "एक बटन दबाएँ। इससे फ़ोन लाइनें खाली रहती हैं और अधिकारी जानते हैं कि किसे मदद चाहिए।\n"
            "Tap one button. It keeps phone lines free and tells the officer who needs help.")


def rollcall_safe_reply(link: str) -> str:
    return ("पुकार: धन्यवाद। आप सुरक्षित दर्ज हो गए।\n"
            f"अपने परिवार को यह लिंक भेजें, ताकि उन्हें फ़ोन न करना पड़े: {link}\n\n"
            f"Pukaar: thank you, you are marked safe. Forward this link to your family so they need not call: {link}")


def safe_place_lines(safe_place: dict | None) -> tuple[str, str]:
    """The optional "nearest safe place" line in Hindi and English, or two empty strings."""
    if not safe_place or not (safe_place.get("name_hi") or safe_place.get("name")):
        return "", ""
    name_hi = safe_place.get("name_hi") or safe_place["name"]
    name_en = safe_place.get("name") or name_hi
    return SAFE_PLACE_HI.format(name=name_hi), SAFE_PLACE_EN.format(name=name_en)


def fallback_alert(level: str, village_hi: str, village_en: str, safe_place: dict | None = None) -> tuple[str, str]:
    """The fixed alert text used when no checked model draft exists."""
    place_hi, place_en = safe_place_lines(safe_place)
    text_hi = f"पुकार: {village_hi} के लिए {LEVEL_HI[level]}। {SAFETY_HI[level]} {place_hi} {CALL_112_HI}"
    text_en = f"Pukaar: {LEVEL_EN[level]} for {village_en}. {SAFETY_EN[level]} {place_en} {CALL_112_EN}"
    return " ".join(text_hi.split()), " ".join(text_en.split())


# -- voice calls with "press 1" (delivery/voice.py, docs/VOICE.md) --------------------------------
VOICE_MENU_HI = "संदेश मिल गया हो तो 1 दबाएँ। मदद चाहिए तो 2 दबाएँ। संदेश दोबारा सुनने के लिए 3 दबाएँ।"
VOICE_ACK_HI = "धन्यवाद, दर्ज हो गया। सुरक्षित रहें।"
VOICE_HELP_HI = "मदद का अनुरोध अधिकारी तक पहुँच गया है। जान का ख़तरा हो तो अभी 112 पर कॉल करें।"
VOICE_GOODBYE_HI = "धन्यवाद। आपात स्थिति में 112 पर कॉल करें।"
VOICE_REASON_HI = {
    "busy": "फ़ोन व्यस्त था", "no_answer": "किसी ने नहीं उठाया", "failed": "कॉल नहीं लगी",
    "no_status": "कॉल का नतीजा नहीं मिला", "invalid_number": "नंबर ग़लत या बंद है", "machine": "मशीन ने उठाया",
    "provider_error": "कॉल सेवा में गड़बड़ी",
}


def voice_unreachable_pradhan(name: str, village_hi: str, attempts: int, category: str, drill: bool) -> str:
    """To the pradhan: a household the call could not reach. A first name only, never the number."""
    label = "अभ्यास (DRILL), " if drill else ""
    reason = VOICE_REASON_HI.get(category, "कॉल नहीं लगी")
    return (f"पुकार, {label}{village_hi}: {name} तक चेतावनी की कॉल {attempts} बार कोशिश के बाद भी नहीं पहुँची "
            f"({reason})। कृपया किसी को घर भेजकर बताएँ।")


# -- relays: the village's own cascade (Practical Action pattern; delivery/dispatch.py) ------------
RELAY_ROLE_HI = {"pradhan": "प्रधान", "gauge_reader": "गेज रीडर", "task_force": "टास्क फ़ोर्स"}
RELAY_ROLE_EN = {"pradhan": "Pradhan", "gauge_reader": "Gauge reader", "task_force": "Task force"}
# Put before the alert text for a relay: they hear it first and pass it on while other phones still ring.
RELAY_LINE_HI = "आप गाँव के रिले हैं: सायरन बजाएँ और माइक से सबको बताएँ, फिर 'मिल गया' दबाएँ।"
RELAY_DONE_EN = "relay done: siren and megaphone"


def relay_done_detail(name: str, role: str, channel: str) -> str:
    """The timeline line for a relay's acknowledgement. A first name only."""
    first = (name or "").split(" ")[0] or "?"
    return f"{RELAY_DONE_EN} ({first}, {RELAY_ROLE_EN.get(role, role)}, by {channel})"


# -- the all-clear to everyone contacted for an alert (workflow/steps.stand_down) -----------------
def all_clear_message(village_hi: str, village_en: str, drill: bool = False) -> str:
    """Short, Hindi first, then English. Sent on the channel the person was warned on."""
    label_hi = "अभ्यास (DRILL): " if drill else ""
    label_en = "DRILL: " if drill else ""
    return (f"पुकार, {label_hi}{village_hi}: बाढ़ का ख़तरा टल गया है। आप घर लौट सकते हैं, "
            f"पर नदी-नालों से अभी भी दूर रहें। आपात स्थिति में 112।\n"
            f"Pukaar, {label_en}{village_en}: the flood danger has passed. You can go home, but keep away "
            f"from streams for now. In an emergency call 112.")


def all_clear_voice(village_hi: str, drill: bool = False) -> str:
    """The all-clear call: spoken once, no menu, no key to press."""
    label = "यह अभ्यास है। " if drill else ""
    return (f"{label}पुकार की सूचना। {village_hi} में बाढ़ का ख़तरा टल गया है। आप घर लौट सकते हैं, "
            f"पर नदी-नालों से अभी भी दूर रहें। आपात स्थिति में 112 पर कॉल करें।")


def all_clear_officer(village_hi: str, village_en: str, alert_id: str, reason: str, drill: bool = False) -> str:
    return f"{all_clear_message(village_hi, village_en, drill)}\n\nAlert {alert_id} stood down: {reason}."


# -- the night-friendly nudge, half-way through an officer's approval window ----------------------
# -- the wake-up call to the duty officer (delivery/officer_call.py). It never approves: "1" sends the
# one-tap approval link again; the decision stays a deliberate tap in the app.
OFFICER_WAKE_MENU_HI = ("मंज़ूरी का लिंक टेलीग्राम पर पाने के लिए 1 दबाएँ। "
                        "Press 1 to get your approval link on Telegram.")
OFFICER_LINK_SENT_HI = ("आपकी मंज़ूरी का लिंक टेलीग्राम और ऐप सूचना पर भेज दिया है; ऐप में खोलकर फ़ैसला करें। "
                        "Opening your approval link: sent to your Telegram and app notifications. "
                        "Decide in the app.")
OFFICER_LINK_NONE_HI = ("आपके टेलीग्राम या ऐप सूचना पर लिंक नहीं भेजा जा सका; पुकार कंसोल खोलें। "
                        "Your link could not be sent to Telegram or app notifications; open the Pukaar console.")
OFFICER_DECIDED_HI = "इस चेतावनी पर फ़ैसला हो चुका है। धन्यवाद। This alert has already been decided. Thank you."


def officer_wake_voice(village_hi: str, village_en: str, level: str, drill: bool = False) -> str:
    """Spoken by the provider's own voice, Hindi then English, and short: the officer may have just woken up."""
    flag_hi, flag_en = ("अभ्यास: ", "Drill: ") if drill else ("", "")
    return (f"{flag_hi}पुकार: {village_hi} को अभी आपकी मंज़ूरी चाहिए, {LEVEL_HI.get(level, level)}। "
            f"{flag_en}Pukaar: {village_en} needs your approval now, {LEVEL_EN.get(level, level)}.")


def nudge_officer(village_hi: str, level: str, minutes_left: int, url: str, replay: bool = False) -> str:
    flag = " [REPLAY]" if replay else ""
    return (f"पुकार{flag}, याद दिलाना: {village_hi} – {LEVEL_HI.get(level, level)}। आपकी मंज़ूरी बाकी है; "
            f"{minutes_left} मिनट में अगले अधिकारी से पूछा जाएगा।\n"
            f"Reminder: still waiting for your decision. The next officer is asked in {minutes_left} min.\n\n"
            f"Approve / decline: {url}")
