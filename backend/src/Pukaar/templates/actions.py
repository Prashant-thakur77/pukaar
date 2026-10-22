"""What a villager should do at each level, Hindi first: the lines the village page and /public/villages/{id}/now
show. The web app keeps the same lines in frontend/src/lib/actions.ts as its offline fallback;
tests/test_status_now.py fails when the two drift apart."""

from __future__ import annotations

Line = dict[str, str]


def _l(hi: str, en: str) -> Line:
    return {"hi": hi, "en": en}


# The level in two words: what the level asks of you.
MEANS: dict[str, Line] = {
    "normal": _l("सब सामान्य", "All normal"),
    "watch": _l("नज़र रखें", "Stay alert"),
    "warning": _l("तैयार रहें", "Get ready"),
    "critical": _l("अभी निकलें", "Leave now"),
}

# At most three lines per level, the most important first.
ACTIONS: dict[str, list[Line]] = {
    "normal": [
        _l("अभी कुछ करने की ज़रूरत नहीं।", "Nothing to do now."),
        _l("अपनी सबसे पास की ऊँची, सुरक्षित जगह पहले से जान लें।", "Know your nearest high, safe place in advance."),
    ],
    "watch": [
        _l("नदी और नालों के किनारे न जाएँ।", "Keep away from the river and streams."),
        _l("काग़ज़, दवा, टॉर्च और पानी एक थैले में रख लें।", "Put papers, medicine, a torch and water in one bag."),
        _l("फ़ोन चार्ज रखें और चेतावनी सुनते रहें।", "Keep your phone charged and listen for alerts."),
    ],
    "warning": [
        _l("ऊँची जगह और वहाँ तक का रास्ता अभी देख लें।", "Look at the high place and the route to it now."),
        _l("बुज़ुर्ग, बच्चे, बीमार और पशु पहले ले जाने की तैयारी करें।",
           "Plan to move the elderly, children, the sick and animals first."),
        _l("नदी, नाले, पुल और ढलानों से दूर रहें।", "Stay away from the river, streams, bridges and slopes."),
    ],
    "critical": [
        _l("अभी ऊँची, सुरक्षित जगह पर जाएँ। सामान के लिए न रुकें।", "Go to high, safe ground now. Do not stop for belongings."),
        _l("पुल या बहता पानी पार न करें।", "Do not cross bridges or moving water."),
        _l("जान को ख़तरा हो तो 112 पर कॉल करें।", "If a life is in danger, call 112."),
    ],
}

# Forecast data late or missing while the level reads Normal: Normal is then not a promise.
NO_DATA: list[Line] = [
    _l("पूर्वानुमान डेटा अभी नहीं मिल रहा, इसलिए “सामान्य” पर भरोसा न करें।",
       "Forecast data is not coming in, so do not rely on “Normal”."),
    _l("नदी और नालों पर ख़ुद नज़र रखें; किनारे न जाएँ।", "Watch the river and streams yourself; stay off the banks."),
    _l("पानी तेज़ी से बढ़े या ख़तरा दिखे, तो ऊँची जगह जाएँ और 112 पर कॉल करें।",
       "If the water rises fast or you see danger, go to high ground and call 112."),
]


def all_lines() -> list[Line]:
    return [*MEANS.values(), *(x for lines in ACTIONS.values() for x in lines), *NO_DATA]
