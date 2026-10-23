# पुकार कार्ड · Villager card

> **छापने से पहले:** यह हिंदी बिना किसी स्थानीय जानकार के लिखी गई है। मंडी के किसी हिंदी बोलने वाले
> व्यक्ति से पढ़वाकर ठीक करवाएँ, फिर छापें।
>
> *Before printing: have a Hindi speaker from Mandi review this text. Then fill in the blanks below
> (the bot name, the report address and each village's safe places), by hand or in
> [print/villager-card.html](print/villager-card.html) before rendering it again.*

The card for every household: one A5 sheet printed on both sides
([PDF](print/villager-card.pdf)). For the wall of the panchayat bhawan, school or shop, print the same
PDF on A4 or A3 with "fit to page"; it scales up. The four levels and what to do at each are the same
words as the "What to do now" box on each village's page (`frontend/src/components/WhatToDo.tsx`), so
the card, the website and the spoken alert agree. On the card the Normal line ends with "know your nearest safe place" instead of the website's "look below", and 112 has its own bar instead of the last Critical line.

The text of the card follows, side by side as printed. Body text on the printed card is 18 pt or
larger.

---

### आगे (front)

## पुकार · बाढ़ की चेतावनी
**Pukaar flood warning · DDMA Mandi**

### चार स्तर: क्या करें · Four levels: what to do

| स्तर | मतलब | क्या करें |
|---|---|---|
| ✅ **सामान्य** · Normal | सब सामान्य | अभी कुछ करने की ज़रूरत नहीं। सबसे पास की ऊँची, सुरक्षित जगह जान लें। |
| 👁 **सतर्क** · Watch | नज़र रखें | नदी और नालों के किनारे न जाएँ। काग़ज़, दवा, टॉर्च और पानी एक थैले में रख लें। फ़ोन चार्ज रखें। |
| ⚠ **चेतावनी** · Warning | तैयार रहें | जाने के लिए तैयार रहें: ऊँची जगह और रास्ता अभी देख लें। बुज़ुर्ग, बच्चे, बीमार और पशु पहले ले जाने की तैयारी करें। नदी, नाले, पुल और ढलानों से दूर रहें। |
| 🚨 **गंभीर** · Critical | अभी निकलें | अभी ऊँची, सुरक्षित जगह पर जाएँ। सामान के लिए न रुकें। पुल या बहता पानी पार न करें। |

**जान को ख़तरा? · Life in danger? Call 112**

### पीछे (back)

### चेतावनी कैसे आती है · How an alert comes
**टेलीग्राम** पर हिंदी में बोला गया संदेश: सुनकर **✅ मिल गया** दबाएँ। **फ़ोन कॉल** पर सुनकर बटन दबाएँ:

| दबाएँ | मतलब |
|---|---|
| **1** | **मिल गया** · heard it |
| **2** | **मदद चाहिए** · need help |
| **3** | **दोबारा सुनें** · repeat |

अभ्यास हो तो पहले सुनेंगे: **"अभ्यास, असली चेतावनी नहीं"**।

### हमारी सुरक्षित जगहें · Our safe places
(प्रधान जी भरें · filled in by hand)

| | जगह | रास्ता |
|---|---|---|
| 1 | | |
| 2 | | |
| 3 | | |

### पानी बढ़ रहा है? बताइए · Report rising water
`______________________/report` (the report page)
फ़ोन में खोलें, बोलें, फ़ोटो लें या लिखें। नेटवर्क न हो तो भी भेजें।

टेलीग्राम: `@______________` को `/start` + गाँव भेजें

**पुकार कभी OTP, पैसे या बैंक की जानकारी नहीं माँगता।**

---

## What to say when handing out the card

The card has no room for these; the pradhan or volunteer says them.

- The Telegram message comes from the Pukaar bot as an audio file (an MP3 titled "पुकार" that plays in
  Telegram's audio player when tapped; not a voice note), with the same alert written in Hindi under it
  and the **✅ मिल गया** button. On a slow connection the written text arrives first: read it, then press. The
  phone call is a woman's voice reading the alert: "पुकार: [गाँव] के लिए …", then "संदेश मिल गया हो तो 1
  दबाएँ। मदद चाहिए तो 2 दबाएँ। संदेश दोबारा सुनने के लिए 3 दबाएँ।"
- If nobody presses a key, the call may come again 10 to 15 minutes later, three calls at most.
- Village codes for Telegram: थुनाग `thunag`, जंजैहली `janjehli`, गोहर `gohar`, पंडोह `pandoh`,
  सुजानपुर `sujanpur`. Example: `/start gohar`. The bot then shows what it keeps (chat id, Telegram name,
  village), why and for how long; nothing is kept until the person presses **✅ सहमत हूँ / I agree**.
  Sending a district's name (`/start Mandi`) lists its village codes.
- To stop the alerts, send `/stop` or **बंद करें**: the name and chat id are removed at once, and from the
  records of past alerts within 30 days.
- On the report page, choose the village, then speak (up to 20 seconds), take a photo or write, and
  press **भेजें**. Without network the report waits on the phone and goes by itself later. A code comes
  back to follow what happened.
- After a Warning or Critical, Telegram asks "क्या आप सुरक्षित हैं?": press **✅ मैं सुरक्षित हूँ** or
  **🆘 मदद चाहिए**.
- The pradhan also sounds the siren and announces by megaphone.

## Notes for whoever prints it

- **Report address:** the pilot's web address plus `/report`. The engineer gets it with
  `PUKAAR_STACK=pukaar-prod AWS_REGION=ap-south-1 scripts/stack_env.sh | grep WebUrl`. Do not print
  the demo site's address on a village card: the demo is not the pilot.
- **Bot name:** the pilot's own Telegram bot (DEPLOY.md, "Production stage": a second bot for prod).
- **Phone calls** only reach households registered for calls, and only once the DDMA switches calls on
  (docs/VOICE.md). Until then the call section tells people what to expect later; say so when you hand
  the card out.
- **Safe places:** write only places the pradhan has checked on foot and marked Open or Standby on the
  village page (pradhan-guide-hi.md, section 4).
