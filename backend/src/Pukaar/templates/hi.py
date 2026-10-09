"""Fixed safety text. Needs native-speaker review (see PROGRESS.md).

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


def fallback_alert(level: str, village_hi: str, village_en: str) -> tuple[str, str]:
    """The fixed alert text used when no checked model draft exists."""
    text_hi = f"पुकार: {village_hi} के लिए {LEVEL_HI[level]}। {SAFETY_HI[level]} {CALL_112_HI}"
    text_en = f"Pukaar: {LEVEL_EN[level]} for {village_en}. {SAFETY_EN[level]} {CALL_112_EN}"
    return text_hi, text_en
