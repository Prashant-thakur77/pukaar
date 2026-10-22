import type { Level } from '../types';

/*
 * What to do at each level, Hindi first. The same lines as the API (backend/src/Pukaar/templates/actions.py,
 * GET /public/villages/{id}/now): the page shows the API's copy, and this one when it has nothing yet.
 * backend/tests/test_status_now.py fails when the two drift apart.
 */

export type ActionLine = { hi: string; en: string };

/** The level in two words: what it asks of you. */
export const MEANS: Record<Level, ActionLine> = {
  normal: { hi: "सब सामान्य", en: "All normal" },
  watch: { hi: "नज़र रखें", en: "Stay alert" },
  warning: { hi: "तैयार रहें", en: "Get ready" },
  critical: { hi: "अभी निकलें", en: "Leave now" },
};

/** The first line of each level, the one that matters most (the home page shows it under a banner). */
export const LEAD: Record<Level, ActionLine> = {
  normal: { hi: "अभी कुछ करने की ज़रूरत नहीं।", en: "Nothing to do now." },
  watch: { hi: "नदी और नालों के किनारे न जाएँ।", en: "Keep away from the river and streams." },
  warning: { hi: "ऊँची जगह और वहाँ तक का रास्ता अभी देख लें।", en: "Look at the high place and the route to it now." },
  critical: { hi: "अभी ऊँची, सुरक्षित जगह पर जाएँ। सामान के लिए न रुकें।", en: "Go to high, safe ground now. Do not stop for belongings." },
};

/** At most three lines per level, the most important first. */
export const ACTIONS: Record<Level, ActionLine[]> = {
  normal: [
    LEAD.normal,
    { hi: "अपनी सबसे पास की ऊँची, सुरक्षित जगह पहले से जान लें।", en: "Know your nearest high, safe place in advance." },
  ],
  watch: [
    LEAD.watch,
    { hi: "काग़ज़, दवा, टॉर्च और पानी एक थैले में रख लें।", en: "Put papers, medicine, a torch and water in one bag." },
    { hi: "फ़ोन चार्ज रखें और चेतावनी सुनते रहें।", en: "Keep your phone charged and listen for alerts." },
  ],
  warning: [
    LEAD.warning,
    { hi: "बुज़ुर्ग, बच्चे, बीमार और पशु पहले ले जाने की तैयारी करें।", en: "Plan to move the elderly, children, the sick and animals first." },
    { hi: "नदी, नाले, पुल और ढलानों से दूर रहें।", en: "Stay away from the river, streams, bridges and slopes." },
  ],
  critical: [
    LEAD.critical,
    { hi: "पुल या बहता पानी पार न करें।", en: "Do not cross bridges or moving water." },
    { hi: "जान को ख़तरा हो तो 112 पर कॉल करें।", en: "If a life is in danger, call 112." },
  ],
};

/** Forecast data late or missing while the level reads Normal: Normal is then not a promise. */
export const NO_DATA: ActionLine[] = [
  { hi: "पूर्वानुमान डेटा अभी नहीं मिल रहा, इसलिए “सामान्य” पर भरोसा न करें।", en: "Forecast data is not coming in, so do not rely on “Normal”." },
  { hi: "नदी और नालों पर ख़ुद नज़र रखें; किनारे न जाएँ।", en: "Watch the river and streams yourself; stay off the banks." },
  { hi: "पानी तेज़ी से बढ़े या ख़तरा दिखे, तो ऊँची जगह जाएँ और 112 पर कॉल करें।", en: "If the water rises fast or you see danger, go to high ground and call 112." },
];
