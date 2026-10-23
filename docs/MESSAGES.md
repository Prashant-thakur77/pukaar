# What the alerts say

**Status: the Hindi on this page is pending review by a native speaker.** Every sentence was written for the
pilot and has not yet been checked by a Hindi speaker from Mandi or Hamirpur, nor recorded in Mandeali or Kangri.
That review is a pilot-readiness item; until it is done, no village hears these words in a real alert.

## Five elements, in this order

People act on a warning that names who is speaking, what is coming, where, when, and what to do
([Mileti and Sorensen; NIST, "Communicating the Emergency"](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=907983)).
Every alert text is built in `backend/src/Pukaar/templates/script.py` from five parts, Hindi first and English
after. Code decides every part; a checked model draft may add one advice line after the hazard, never replace a
part.

| # | Element | Hindi | Where it comes from |
|---|---|---|---|
| 1 | Source | जिला आपदा प्रबंधन प्राधिकरण मंडी की ओर से | the village's district (`data/districts.json`); Pukaar is the DDMA's tool |
| 2 | Hazard | सतर्क रहें / चेतावनी / गंभीर ख़तरा, then heavy rain, a rising river, or both | the level and the rules that fired |
| 3 | Place | थुनाग (मंडी) में, ख़ासकर नदी-नालों और ढलानों के पास | the village record |
| 4 | Timing | अभी, or अगले 6 / 12 / 24 / 48 घंटे में | "now" for a Critical or anything observed; else the forecast window, rounded up, never a promise of exact lead time |
| 5 | Action, ending with where to go | the level's safety line, then सबसे पास सुरक्षित जगह: <name> | the place a pradhan or officer marked OPEN or STANDBY; else "the nearest high, safe ground" |

"आपात स्थिति में 112 पर कॉल करें" comes before the action, so the script ends with where to go.

An example (Warning, heavy rain, a place marked open):

> जिला आपदा प्रबंधन प्राधिकरण मंडी की ओर से, पुकार: चेतावनी। भारी बारिश से नदी-नालों में अचानक बाढ़ और भूस्खलन का ख़तरा, थुनाग (मंडी) में, ख़ासकर नदी-नालों और ढलानों के पास, अगले 24 घंटे में। आपात स्थिति में 112 पर कॉल करें। नदी-नालों और ढलानों से दूर रहें। ज़रूरी सामान तैयार रखें और ऊँची, सुरक्षित जगह जाने के लिए तैयार रहें। सबसे पास सुरक्षित जगह: राजकीय विद्यालय थुनाग।

The drafting checker and the template fallback are unchanged: a model draft with a number, place or link not in
the decision trace is refused and the fixed script goes out (`services/drafting.py`). The auto-send, the
failsafe and an escalation before approval use the same fixed script.

The source line names the DDMA because Pukaar may warn only as the DDMA's tool
([COMPLIANCE_INDIA.md](COMPLIANCE_INDIA.md)). Until a DDMA has adopted it, alerts reach only labelled drills and
replays.

## Voice length

A call is billed by the minute. `script.voice_check()` estimates how long Polly takes to say the Hindi alert and
the "press 1" menu (2.3 words a second and a short pause per sentence, generous on purpose). Over 55 seconds the
draft step and an officer's edit put a `voice_long` line on the alert's timeline, log a warning and emit
`VoiceScriptLong`. Every fixed script, with the longest village and safe-place names, fits: a test checks it
(`tests/test_alert_script.py`).

## Why we warned

After an alert ends, everyone it reached gets one short note (`services/followup.py`, texts in
`templates/care.py`): what Pukaar saw, what happened (from the officer's "was this real?", or "the danger has
passed"), and thanks for pressing "मिल गया" (or a request to press it next time). It goes once per alert: when
the outcome is recorded, an hour after the all-clear, or a day after a closed alert with neither. Replays never
send one, a drill's says DRILL, and voice-only households are not called again for it.

## Assisted households

The check-on-them message to a named neighbour or relay is also in `templates/care.py`. It names the person by
first name and why they need help ("बुज़ुर्ग", "दिव्यांग", "अकेले रहते हैं"), and has one button, "देख लिया".
