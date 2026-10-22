# ड्यूटी अधिकारी की गाइड · Duty officer's guide

For the district duty officer at the DEOC (District Emergency Operations Centre) in Mandi during the
Pukaar pilot. It covers one shift from sign-in to hand-over. Button and screen names are written as the
console shows them in English, with the Hindi label in brackets where an officer may have switched the
console to Hindi (the **हि** / **EN** button in the top bar).

The pilot runs on the production stack (`pukaar-prod`, [DEPLOY.md](../DEPLOY.md#production-stage)), not on
the public demo site. Write its address here before printing:

> Console address: `https://______________________________/console`
>
> Pukaar Telegram bot for the pilot: `@______________________`
>
> DEOC landline: `______________`   On-call engineer: `______________`

The engineer gets the address from the stack outputs:
`PUKAAR_STACK=pukaar-prod AWS_REGION=ap-south-1 scripts/stack_env.sh | grep WebUrl`.

The one-page version of this guide is the [night checklist](print/night-checklist.html)
([PDF](print/night-checklist.pdf)).

**Contents:**
1. [Signing in](#1-साइन-इन--signing-in)
2. [Before the shift](#2-पारी-से-पहले--before-the-shift)
3. [Taking over a shift](#3-ड्यूटी-सँभालना--taking-over-a-shift)
4. [A pending alert](#4-मंज़ूरी-बाकी-चेतावनी--a-pending-alert)
5. [Why this level](#5-यह-स्तर-क्यों--why-this-level)
6. [Approve or decline](#6-मंज़ूर-या-अस्वीकार--approve-or-decline)
7. [The wake-up call](#7-जगाने-वाली-कॉल--the-wake-up-call)
8. [Escalation](#8-अगले-अधिकारी-तक--escalation)
9. [Critical windows](#9-गंभीर-चेतावनी-का-समय--critical-windows)
10. [Villager reports](#10-गाँव-की-सूचनाएँ--villager-reports)
11. [The roll-call board](#11-रोल-कॉल--the-roll-call-board)
12. [Road blocks and shelters](#12-बंद-रास्ते-और-आश्रय--road-blocks-and-shelters)
13. [Closing an alert](#13-चेतावनी-बंद-होना--closing-an-alert)
14. [The after-action report](#14-कार्रवाई-के-बाद-की-रिपोर्ट--the-after-action-report)
15. [Data and gauge alarms](#15-डेटा-या-गेज-का-अलार्म--data-and-gauge-alarms)
16. [Hand-over](#16-पारी-सौंपना--hand-over)

What Pukaar does, in one paragraph: every 15 minutes it reads the rain and river forecasts for each
pilot village and fixed rules (IMD rain bands, each village's own 1984-2024 river record, river gauges,
verified villager reports) set a level: **Normal (सामान्य)**, **Watch (सतर्क)**, **Warning (चेतावनी)** or
**Critical (गंभीर)**. When a level rises, a Hindi alert is drafted and waits for **you**. Nothing reaches a
village until a duty officer approves it. After you approve, the village relays (pradhan, gauge reader,
task force) get it first, then every registered phone, as a spoken Hindi message with a **"✅ मिल गया"**
button on Telegram, or a phone call with "press 1" where calls are switched on.

Pukaar does not replace IMD or CWC bulletins, the DEOC's own judgement, or 112. Global forecasts missed
the June 2025 Mandi cloudbursts in the back-test; a call from the village is often the first real
evidence.

---

## 1. साइन इन · Signing in

Every sign-in on the pilot needs your password **and** a 6-digit code from an authenticator app on your
phone (TOTP; the production stack sets MFA to required). Pradhans need the app too.

**First sign-in (enrol your phone):**
1. Install an authenticator app on your own phone: Google Authenticator, Microsoft Authenticator or
   any TOTP app.
2. Open the console address and go to **Officer sign-in** (अधिकारी साइन इन). Enter **Username**
   (यूज़रनेम) and **Password** (पासवर्ड) exactly as the engineer gave them to you in person, and press
   **Sign in** (साइन इन).
3. The page shows **Second step: authenticator app** (दूसरा चरण: ऑथेंटिकेटर ऐप) with a QR code and the
   text "This account needs two-step sign-in. Scan this QR code with an authenticator app on your phone
   (for example Google Authenticator), then enter the code it shows."
4. In the app, add an account and scan the QR code. If the camera cannot scan it, use **Cannot scan? Type
   this key** (स्कैन न हो तो यह कुंजी डालें) and type the key shown.
5. Type the 6-digit code the app shows into **6-digit code** (6 अंकों का कोड) and press **Verify**
   (पुष्टि करें). You are in the **Officer console**.

**Every later sign-in:** username, password, **Sign in**, then the current 6-digit code and **Verify**.
The code changes every 30 seconds; if it is refused, wait for the next one. **Back** (वापस) returns to the
password step.

**Lost or changed phone:** phone the on-call engineer. They delete your account and create it again
with the same groups and villages; you enrol the new phone at the next sign-in
([DEPLOY.md, "Officer accounts and MFA"](../DEPLOY.md#officer-accounts-and-mfa)). Do not share the
authenticator between people: the audit trail records every approval under your name.

You cannot change your own password in the app; ask the engineer. No password or code is ever sent to
you by Pukaar.

## 2. पारी से पहले · Before the shift

Do these once per phone, then check them at the start of every shift.

**Approval alerts on this phone (Web Push).** In the console open the **Act** (कार्रवाई) tab. Under
**Get approval alerts on this phone** (इस फ़ोन पर मंज़ूरी की सूचना पाएँ) press **Turn on** (चालू करें) and
allow notifications when the browser asks. The panel then says "On: this phone gets approval alerts".
Press **Send a test notification** (जाँच सूचना भेजें) and check that it arrives. An approval
notification shows the village, the level, the start of the Hindi text and "Approve within 10 min",
with two buttons, **✅ मंज़ूर** and **✖ नहीं**, that decide without opening the console.
- On iPhone and iPad, first add Pukaar to the Home Screen (Share, then Add to Home Screen), open it
  from there and turn this on. Safari shows no buttons on the notification: a tap opens the approval
  page.
- "Blocked by the browser": allow notifications in the site's settings and reopen the page.

**Approval links on Telegram.** On the same tab, under **Get approval links on Telegram** (Telegram पर
मंज़ूरी लिंक पाएँ), press **Get my code** (कोड बनाएँ). Copy the command it shows (it looks like
`/start link_ABC123`) and send it to the pilot's Pukaar bot within the time shown ("Expires in N min").
The bot answers "Pukaar: approval links for <your username> will come to this chat."

**Your phone for the wake-up call.** Give the on-call engineer your mobile number; they register it with
`make officer-phone STAGE=prod OFFICER=<your username> PHONE=+91...` (section 7).

**Phone settings for the night.** Keep the phone charged and its ringer on; allow notifications from
the browser (or the Home Screen app) and from Telegram even in Do Not Disturb if your phone allows it.

## 3. ड्यूटी सँभालना · Taking over a shift

Shifts are in IST: **Day shift** (दिन की पारी) 08:00 to 20:00 and **Night shift** (रात की पारी) 20:00 to
08:00, dated the evening it starts (so at 02:00 on 23 October the night shift of 22 October is on duty).

1. In the console header press **Duty roster** (ड्यूटी रोस्टर), or open `/roster`.
2. **On duty now** (अभी ड्यूटी पर) shows, for each district, the shift and the chain in the order it is
   asked: **Primary** (मुख्य अधिकारी), **Backup** (बैकअप), and the **Escalation officer** (ऊपर के अधिकारी),
   the ADM or DM.
3. If you are starting the shift and are not already the primary, press **Take over this shift**
   (ड्यूटी सँभालें). The page says "You are now the primary for this shift. Written to the audit trail."
   The previous primary is kept on the row ("Taken over from … at …"). The button is not shown when you
   are already the primary.
4. Check the chain has a backup and an escalation officer. If the row says "Nobody is rostered for this
   shift. Approvals go to the village list (…) and the alarm is on.", fill it now: under **The week**
   (सप्ताह) press **Edit** (बदलें) on the shift, enter the **Sign-in name** of each person, the **Post**
   (ADM or DM) of the escalation officer, an optional **Note**, and **Save** (सहेजें). **Clear shift** (पारी
   खाली करें) empties it. Every change is written to the audit trail.
5. Read the policy lines under the chain: whether a critical alert "goes out on its own" or "is not sent"
   when nobody in the chain answers (on the pilot: **is not sent** until the DDMA signs off). The line
   "Each officer is reminded after 5 min" is half the 10-minute window; the reminder and wake-up call
   actually come at 3 minutes (2.5 for a critical), as section 8 says.

**Important:** the chain is fixed on an alert when its draft is made. An alert raised at 19:58 keeps
asking the day-shift chain after 20:00. Any signed-in district officer can still decide it from the
console (section 6), so the incoming officer should look at **Pending approvals** first after taking over.

Only district officers see and change the roster; pradhans cannot.

## 4. मंज़ूरी बाकी चेतावनी · A pending alert

The console opens on **Pending approvals** (मंज़ूरी बाकी), most severe first, then oldest first. Two
cards are shown; **Show N more** (N और दिखाएँ) opens the rest, and its coloured dots show their levels so a
critical is never hidden. "All quiet: No alerts waiting for approval" means nothing is waiting.

Each card shows, top to bottom:

| Part | What it is |
|---|---|
| **Alert · alr_…** and how long ago | The alert's id (quote it to the engineer) and its age |
| Village name, Hindi and English | Links to the village page |
| The Hindi text, then the English | Exactly what people will read; the Hindi is what is spoken |
| **Listen** (सुनें) | Plays the Hindi audio (Amazon Polly, voice Kajal) that phones will get. Listen once before approving |
| **Level** (स्तर) | Previous level → new level. A critical is shown as a red pill |
| **Recipients** (पाने वाले) | "N people live in <village>" when the population is recorded, and "Dry run: N recipients", the phones that will get it |
| **Decline** (अस्वीकार करें) and **Approve** (मंज़ूर करें) | Your decision (section 6) |
| **Draft check** (मसौदा जाँच) | "Draft check passed" with the model's name, or an amber line: **Rule fallback: model unavailable — fixed Hindi template**, or **Level rose while waiting — fixed template for the new level**. A red **Model draft rejected: fixed template used** means the model's draft named a number or place not in the evidence and was thrown away. The fixed template is safe to send: it is the outage path, not a fault |
| **Created** (बनी) | The time the alert was drafted |
| **Why this level?** (यह स्तर क्यों?) | The evidence, section 5 |

A **Drill** alert starts its Hindi text with **"अभ्यास (DRILL), असली चेतावनी नहीं।"** Approve it like any
other: drills test the real path to phones (see [drill-plan.md](drill-plan.md)).

The alert text names the nearest safe place ("सबसे पास सुरक्षित जगह: …") only if a pradhan or officer has
marked one **Open** or **Standby** in the shelter ledger (section 12). If you know a place is open and the
text names none, set it on the village page now: a later draft will name it, but this draft does not
change.

## 5. यह स्तर क्यों · Why this level

Press **Why this level?** on the card. Code, not the AI model, set the level; this panel is the evidence
the rules used, one line per signal, the strongest first. Each line has an icon and, when it raised the
level, the level's colour.

| Line | Example | How to read it |
|---|---|---|
| **River** | "River peak 412 m³/s ≥ its 5-year flood level 380 m³/s (Warning)" | The highest forecast river flow at the village's river cell against the 2-, 5- and 20-year flood levels from that cell's own 1984-2024 record (Watch, Warning, Critical) |
| **River, forecast runs** | "17 of 51 forecast runs say the river passes its 2-year flood level within 2 days" | The GloFAS ensemble. When at least 3 runs in 10 agree (P ≥ 0.3) the line raises the level. "River: a single forecast, not the forecast runs (the ensemble is unavailable)" means only one forecast was read |
| **Rain** | "Rain next 24 h 118 mm ≥ 115.6 mm (IMD warning band)" | The 24-hour forecast against IMD's bands: 64.5 mm Watch, 115.6 mm Warning, 204.5 mm Critical |
| **Heavy burst** | only in the **Rules** line, e.g. `rain_intensity:3h=48>=45mm:watch` | The 1-, 3- and 6-hour maxima of the hourly forecast against 20, 45 and 50 mm. A burst alone raises Watch; with a heavy 24-hour band or saturated soil it raises Warning, never more |
| **Gauge** | "River gauge 182 cm → Warning" | A water-level gauge at the village bridge, counted once 2 of the last 3 good readings agree. "(simulated)" readings never raise a live village |
| **Reports** | "2 verified village reports: Water rising (High) → Warning" | Villager reports an officer (or the matching rules) verified. "1 unverified report (cannot raise the level)" waits for you in the report feed |
| **Two sources agree** | "Two sources agree: +1 level" | Two independent signals (for example rain and a verified report) at the same level raise it one more step |
| **Damage report** | "Verified damage report: at least Warning" | A verified report of homes affected or people trapped sets Warning or above |
| **Outlook** | the **Get ready** (तैयार रहें) line | The 7-day river outlook passed the river's 1-in-10-days line. Evidence only: it never raises a level or sends anything |
| **Official sources** | "CWC river stations: 3 stations above warning in India; 0 on this river"; "IMD district colour: orange for today and tomorrow (every weather hazard, not floods alone)" | Shown as backing. They never lower a level, and on the pilot they do not raise one either. "Unavailable, so saying nothing: …" means the source did not answer, not that all is well |
| **Data disagrees** | "Forecast data is low but village reports are severe: officer to check" | Read the reports yourself before deciding |
| **Holding** | "Holding at Warning: levels drop one step only after 3 calm sweeps (1 of 3 so far)" | The level rises at once but steps down only after three calm 15-minute checks |
| **Rules** | `rain_24h>=115.6mm:warning · discharge>=380.0:warning` | The raw rules that fired, for the engineer and the after-action report |

Other rule tags you may see: `rain_unknown` or `discharge_carried_forward` (a forecast value is missing:
the last good value is carried for an hour, then the village shows "data unavailable"),
`river_ensemble_unavailable`, `gauge_unconfirmed`, `gauge_simulated_ignored`, `verified_reports:<level>`,
`staff_gauge_confirmed:<level>` (a confirmed photo reading of a marked rock or pier),
`official_corroborates:cwc`, `drill`.

For more context open the village page from the card (village name): the same evidence with charts, the
trend, past high-water days and the safe places.

## 6. मंज़ूर या अस्वीकार · Approve or decline

**Approve when** the evidence is plausible for the village and the text is right: the village name, the
level and the advice. Do not wait for certainty at Warning or Critical: approving sends a warning people
can act on; a late warning is worth little. If you are unsure at Watch, phone the pradhan or gauge reader
first (a minute or two), then decide.

**Decline when** the evidence is plainly wrong (a known data fault, a gauge being worked on, the same
event already warned by the DEOC through other means) or the text would mislead. Declining sends nothing.

**How:**
- **Console:** press **Approve** (मंज़ूर करें) or **Decline** (अस्वीकार करें). A box asks you to confirm:
  "This alert goes to N people now. Approve?" or "The alert will not be sent. Decline?" with a field
  **Reason (optional)** for a decline. Write a short reason: it goes into the audit trail and the
  after-action report. Press the button again in the box to confirm, or **Cancel** (रद्द करें).
- **Telegram link:** the message "पुकार: <village> – <level>", the Hindi text and "Approve / decline:
  <link>". The link opens **One tap to approve** (एक टैप में मंज़ूरी) with the text and "Will reach N
  people"; tap **मंज़ूर करें · Approve** or **अस्वीकार करें · Decline**, then confirm in the box.
- **Phone notification:** **✅ मंज़ूर** or **✖ नहीं**; the phone then shows "Approved" or "Already decided".

Any signed-in district officer can decide from the console, whoever's turn it is. The first decision
wins; any later one gets **Already decided** (पहले ही फ़ैसला हो चुका है) and nothing is sent twice.
A link from an earlier step of the chain stops working once the next officer is asked; use the console.
Pradhans see a disabled **Approve (officers only)** button and cannot approve.

**What happens after you approve:**
1. Within seconds the status moves to delivering, then delivered (**Recent alerts**, हाल की चेतावनियाँ).
2. The village relays get it first, with the line "आप गाँव के रिले हैं: सायरन बजाएँ और माइक से सबको बताएँ,
   फिर 'मिल गया' दबाएँ।" Then every registered phone gets the spoken alert.
3. Open **Recipients (N)** (किसे भेजी गई) on the alert: one row per person with the channel (Telegram, Voice
   call), "sent HH:MM", and "acknowledged HH:MM" or "no acknowledgement yet". A relay row reads
   "Relay · Pradhan" and, when they press, **Relay done: siren and megaphone, HH:MM**. A red error on a row
   is a failed delivery (see RUNBOOK, delivery-failed). **Time to ear** (कान तक का समय) shows Level rose →
   Approved → Voice on first phone → First "मिल गया".
4. After 5 minutes (10 on a voice pilot) everyone who has not acknowledged is sent it once more; voice
   numbers are called up to three times in all, 10 to 15 minutes apart. Numbers no call reached are sent
   to the pradhan to check by hand.
5. The alert closes by itself after the re-send round. A live Warning or Critical then opens a safety
   roll-call (section 11). The after-action report is written (section 14).
6. The alert is also published in the CAP feed as an official-format message ("CAP XML ↗").

**If no relay has pressed within 10 minutes of approval, phone the pradhan.** The siren is the village's
fastest channel and it is not automatic.

**What happens after you decline:** nothing is sent; the decision and your reason are on the audit trail.
If the level still holds, the sweep asks again with a new alert that names this one: after 5 minutes
for a Critical, 30 for a Warning, 60 for a Watch.

**If the console will not load** (RUNBOOK, api-5xx): try the Telegram link (same API, so check it), and
if neither works decide by phone with the DDMO, warn the village by phone, and record what you did in the
DEOC log for the after-action review.

## 7. जगाने वाली कॉल · The wake-up call

Web Push and Telegram are silent on a phone in silent mode, so three minutes into your turn (2.5 minutes
for a critical), if you have not opened the approval link, Pukaar:
- sends a reminder on Telegram ("पुकार, याद दिलाना: <village> – <level>। आपकी मंज़ूरी बाकी है; N मिनट में
  अगले अधिकारी से पूछा जाएगा।") and Web Push ("याद दिलाना · Reminder: …"), and
- **phones you**, if your number is registered and voice calls are switched on for the pilot. The call
  says, in Hindi then English: "पुकार: <village> को अभी आपकी मंज़ूरी चाहिए, <level>। Pukaar: <village> needs
  your approval now, <level>." and "मंज़ूरी का लिंक टेलीग्राम पर पाने के लिए 1 दबाएँ। Press 1 to get your
  approval link on Telegram."

**Press 1:** the same approval link comes again to your Telegram and phone notifications. **Nothing on the
call approves or declines.** Open the link or the console and decide there, with the alert in front of
you.

The call comes once per alert, only if you had not opened the link. The alert's timeline (in the
after-action report) records whether the call was placed, answered, or "not possible" and why: voice is
off, no phone on file, or a replay. **At the start of the pilot voice calls are off** (`VOICE_PROVIDER=off`
until the DDMA's call-provider account exists): until then there is no call, only the reminders. Ask the
engineer which is true for your pilot and write it here: `Wake-up call: ON / OFF`.

The engineer sets your number with `make officer-phone STAGE=prod OFFICER=<username> PHONE=+91...`;
`PHONE=show` prints it masked and `PHONE=remove` stops the calls.

## 8. अगले अधिकारी तक · Escalation

Each alert asks the chain from the roster in order: **Primary → Backup → Escalation officer (ADM or DM)**.

| Minutes into your turn | Warning or Watch | Critical |
|---|---|---|
| 0 | Telegram link, Web Push, console card | same |
| 3 (critical 2.5) | Reminder on Telegram and Web Push; wake-up call if you have not opened the link | same |
| 10 (critical 5) | Your turn ends: "did not answer in time; asking <next>". The next officer gets the same messages | same |

When the last person in the chain has not answered, the alert is **not** dropped quietly:
- **Last call.** Everyone in the chain and everyone on the district roster now, including the ADM or DM,
  gets a fresh link on Telegram and Web Push, and the ADM or DM is phoned (when voice calls are on). Any
  of them can approve or decline for one more window: 5 minutes for a Critical, 10 otherwise. The
  `alert-unanswered` alarm fires at the same moment.
- **Then it expires unsent** ("Time ran out"). If the level still holds, the sweep asks again: after
  5 minutes for a Critical, 30 for a Warning, 60 for a Watch.
- **Critical on the pilot** follows the same path (`CriticalAutoSend=false`). Only after the DDMA's
  written sign-off can it be set to go out by itself with the fixed template, flagged "Auto-sent,
  unapproved". The roster page states which applies.

A chain of three holds a Warning for up to 30 minutes and a Critical for up to 15. That is too long for a
village in danger. Escalate **by phone** as well:
- An alert you cannot decide (you are unsure, or it needs the DM's call): phone the backup or the
  escalation officer at once rather than letting your 10 minutes run out.
- A pending **Critical**: decide it yourself; if you cannot, phone the DDMO and the pradhan in the same
  minute.
- The RUNBOOK's "Tell the DDMA" means the DEOC duty officer or the DDMO, by phone, in the same hour.

If the district has no roster row for the shift, approvals go to the village's fallback list and the
**nobody-on-duty** alarm fires (RUNBOOK). Fill the roster (section 3).

## 9. गंभीर चेतावनी का समय · Critical windows

Critical means "leave now". The villager advice at Critical is: "अभी ऊँची, सुरक्षित जगह पर जाएँ। सामान के
लिए न रुकें। पुल या बहता पानी पार न करें।"

- Each officer has **5 minutes**, not 10; the reminder and wake-up call come at **2.5 minutes**.
- An alert that rises to Critical while it waits is escalated in place (the card shows "Level rose
  while waiting — fixed template for the new level"); the next officer gets the critical window.
- **Target: decide a Critical within 2 minutes of the phone buzzing.** Listen if you can, read the first
  lines of Why this level, approve.
- After approving: watch **Relay done** on the recipients; if no relay pressed within 5 minutes, phone the
  pradhan. Ask the pradhan which safe place is open and set it on the village page (section 12).
- A Critical with no approval is never sent on the pilot (above). If you see a Critical card with
  "Time ran out" in Recent alerts, phone the village and the DDMO now; the sweep will ask again in 30
  minutes.
- Issue a directive if the administration orders it: **Act** tab, **Issue a directive** (निर्देश भेजें):
  choose **Village**, **Type** (**Evacuate** · गाँव खाली करें, **Shelter in place** · जहाँ हैं वहीं सुरक्षित
  रहें, **Advisory** · सलाह, **All clear** · ख़तरा टला), an optional **Note (English, optional)**, then
  **Issue directive**. The directive shows on the village's public page as "प्रशासन का आदेश: …". Only
  **All clear** also sends a message to phones (section 13).

## 10. गाँव की सूचनाएँ · Villager reports

Global forecasts can miss a cloudburst. A villager's report is often the first real evidence, and a
**verified** report can raise a village's level by itself.

The **Reports** tab (**Report feed**, सूचनाएँ) lists each report with its words, transcript, photo or voice
note and how it was read. Set its state with **Verified** (पुष्ट), **Actioned** (कार्रवाई हुई), **Resolved**
(सुलझ गई), **Duplicate** (दोहराई गई) or **False** (गलत); **Undo** (वापस लें) reverses the last change.
- Verify a report only after a check: a phone call to the sender, the pradhan or the gauge reader, or
  a photo you can place.
- "Held for review" means the report came over a rate limit or failed the safety screen: it never
  counts until you verify it (RUNBOOK, report-surge).
- "Photo agrees, officer to confirm" means a photo matched, but a photo alone never verifies.

Pradhans can read their own village's reports but cannot change their state.

## 11. रोल-कॉल · The roll-call board

After a **live Warning or Critical** alert closes having reached phones, Pukaar asks every Telegram
recipient in the village "पुकार: क्या आप सुरक्षित हैं? / Are you safe?" with two buttons, **✅ मैं सुरक्षित
हूँ** and **🆘 मदद चाहिए**. Pressing 2 on an alert call also counts as "need help". The roll-call stays open
48 hours. Replays never ask; drills ask as a labelled exercise.

Open the **Roll-call** tab (**Surakshit Hoon · roll-call**, मैं सुरक्षित हूँ · रोल-कॉल):
1. If more than one roll-call exists, pick it in **Choose a roll-call** (रोल-कॉल चुनें).
2. The counts: **Need help** (मदद चाहिए), **Safe** (सुरक्षित), **Not answered** (जवाब नहीं आया).
3. **Need help comes first**, with a first name, the time and any short note the person typed ("where I
   am"). Each one is a person, not a number: phone them back, or send the task force, and note what you
   did in the DEOC log. The **rollcall-need-help** alarm fires for each (RUNBOOK).
4. **Not answered:** "Demo, no phone" and "Send failed" chips say why. While the roll-call is open press
   **Remind the ones who have not answered** (जिनका जवाब नहीं आया, उनसे फिर पूछें), at most once every 30
   minutes. Ask the pradhan to check the silent households in person.
5. **Safe:** names and times. A person who answered safe gets a 7-day family link to forward, so
   relatives need not call.

The board shows names and times only, never phone numbers.

To open one yourself (after a directive, or for a drill): **Open a roll-call** (रोल-कॉल शुरू करें), choose
the **Village**, keep **As an exercise (phones see "DRILL")** ticked unless this is real, press **Open a
roll-call**, then **Confirm** in the box ("Every registered phone in <village> gets the question now.").
Voice-only households are not asked by call yet; they show as not answered.

## 12. बंद रास्ते और आश्रय · Road blocks and shelters

Both are kept on the village page (`/village/<id>`, section **Where to go** · कहाँ जाएँ). The pradhan keeps
them for their own village; officers can change any village. Ask the pradhan by phone before you change
theirs.

**Shelter ledger.** Each safe place (named places from OpenStreetMap, at least 15 m above the river, with
the walking route) shows its state, **Not checked** (जाँच बाकी) until someone sets it. Signed in, you see
four buttons under each place: **Open** (खुला), **Standby** (तैयार), **Full** (भरा हुआ), **Closed** (बंद). Press
one; "Status saved" and "Set by <you>" appear. The next alert names the nearest **Open** place (else the
nearest **Standby** one) as "सबसे पास सुरक्षित जगह: …". With none open or on standby, alerts name no place.

**Road blocks.** When a road, path or bridge on a route is cut:
1. Tap the route on the map at the spot (the page says "Tap a route on the map to mark a road or bridge
   blocked at that spot"), or press **Mark route blocked** (रास्ता बंद बताएँ) under the place (it then uses
   the middle of the route).
2. In **Mark a road or bridge blocked**, fill **Road or bridge (optional)** and **What is wrong
   (required)**, for example "Landslide across the path", and press **Mark blocked** (बंद बताएँ).
3. Routes through the block are crossed out; the next precomputed route is promoted, and the alert names
   the next place with an open route. Pukaar never draws a new route: if every route is blocked, alerts
   name no place.
4. A block lapses after 7 days. Under **Blocked roads** (बंद सड़कें) press **Still blocked (7 more days)**
   (अब भी बंद (7 दिन और)) to renew it, or **Road open again** (सड़क फिर खुली) to clear it.

Every change is audited.

## 13. चेतावनी बंद होना · Closing an alert

There is no "close" button: an alert closes itself after its re-send round (section 6). What the officer
does at the end of an event:

- **All-clear.** When the village's level returns to Normal, Pukaar sends everyone it contacted a short
  all-clear ("पुकार, <village>: बाढ़ का ख़तरा टल गया है। आप घर लौट सकते हैं, पर नदी-नालों से अभी भी दूर
  रहें। आपात स्थिति में 112।") on the same channel, and the recipient rows show **All-clear sent**. If the
  administration stands the village down earlier, issue an **All clear** directive (section 9): it sends
  the same message for every alert of the village from the last 72 hours that reached anyone. Do not issue it while water is still
  rising.
- **"Was this real?" (क्या यह असली था?).** Under the closed alert in **Recent alerts** choose **Real flood**
  (असली बाढ़), **No flood** (बाढ़ नहीं आई) or **Unknown** (पता नहीं). The line then reads "Recorded: …".
  Answer within 48 hours, after talking to the pradhan or the gauge reader; change it later if news
  arrives (each change is on the timeline and in the audit trail). The answers feed the false-alarm rate
  per rule on `/pilot`, which the DDMA reviews monthly in the monsoon. Drills and replays cannot be
  answered. Only officers can answer; pradhans cannot.

## 14. कार्रवाई के बाद की रिपोर्ट · The after-action report

Every closed alert has a one-page report in Hindi and English. Under the alert in **Recent alerts** press
**After-action report ↗** (कार्रवाई के बाद की रिपोर्ट ↗) to open it in a new tab, or **Download** (डाउनलोड)
to save the HTML file. If the DDMA set up e-mail, it is also mailed to the officers (drills are labelled;
replays are never mailed).

Sections: **Key times (time to ear)** (level rose, approved, first voice on a phone, first "मिल गया", with
the gap between each), **Decision trace** (sources, rules, model or fixed template), **Approval chain**
(who was asked, timeouts, reminders, the wake-up call), **Deliveries and acknowledgements** (by channel,
first names only, re-sends), **Safety roll-call**, **Audit decisions (Cedar)** (every allow and deny),
**Was this real?**, **Text sent** (the words spoken), and the **Full timeline** in IST.

Use it for the DDMA's event report and the drill log. It contains no phone numbers or chat ids, but it
does contain first names: share it only inside the administration. Pradhans can open the report for
their own village.

The **Audit trail** link on an alert (or **Audit trail** in the console header, `/audit`) lists every
decision, allowed or denied, with the policy and reason; routine reads are hidden until **Show reads**.

## 15. डेटा या गेज का अलार्म · Data and gauge alarms

Alarms go by e-mail and SMS to the subscribed on-call phones. The [RUNBOOK](../RUNBOOK.md#alarms) has one
section per alarm: what it means, the first three checks, the fix, who to call and whether to tell the
DDMA. The ones a duty officer acts on:

| Alarm | What you see | What you do |
|---|---|---|
| [sweep-heartbeat](../RUNBOOK.md#pukaar-stage-sweep-heartbeat) | Pukaar is not checking any village | Phone the on-call engineer at once; tell the DDMA "Pukaar is not watching any village since <time>"; rely on IMD and CWC bulletins and the gauge readers by phone |
| [village-data-stale](../RUNBOOK.md#pukaar-stage-village-data-stale) | The village shows **Data late** (डेटा देर से) or **No data** (डेटा नहीं) and "So “Normal” here does not mean safe: keep an eye on the river yourself." Its level is held, never lowered | If the village is at Watch or above, or rain is forecast, ask the pradhan or gauge reader for a reading by phone and tell the DDMA |
| [delivery-failed](../RUNBOOK.md#pukaar-stage-delivery-failed) | Red errors on recipient rows | If more than a few people in one village were not reached on a live Warning or Critical, phone the pradhan to pass it on |
| [unacknowledged-alerts](../RUNBOOK.md#pukaar-stage-unacknowledged-alerts) | Many "no acknowledgement yet" rows | Phone the relays first; tell the DDMA for a live alert |
| [rollcall-need-help](../RUNBOOK.md#pukaar-stage-rollcall-need-help) | A name under Need help | Call back or send the task force; tell the DDMA, always |
| [report-surge](../RUNBOOK.md#pukaar-stage-report-surge) | "Possible duplicate or flood of reports" in the report feed | Read the held reports; in a real event verify the true ones |
| [nobody-on-duty](../RUNBOOK.md#pukaar-stage-nobody-on-duty) | "Nobody is rostered for this shift" on the roster | Fill the shift or take it over (section 3) |
| [api-5xx](../RUNBOOK.md#pukaar-stage-api-5xx), [approval-failed](../RUNBOOK.md#pukaar-stage-approval-failed) | The console fails, or an alert stopped half way | Engineer at once; confirm by phone that the village was warned |

**River gauge.** On the village page and `/sensors`, a gauge that says **No reading in 30 min** (30 मिनट से
कोई माप नहीं) or shows low battery or bad readings is not counted towards the level. Its last reading is not
evidence. Ask the gauge reader to read the staff gauge by phone, and tell the engineer. Readings labelled
**Simulated** never change a live level.

The **System** card in the console shows whether each service is OK, Limited or a Problem; "Rule
fallback" on drafts means the model is unavailable, which never stops an alert.

## 16. पारी सौंपना · Hand-over

Before you leave:
- No alert is pending, or the incoming officer has seen each pending card.
- Open roll-calls with **Need help** or many **Not answered** are handed over by name.
- Blocked roads and shelter states are current for any village at Watch or above.
- Closed alerts from your shift have a "Was this real?" answer, or a note in the DEOC log why not yet.
- The incoming officer presses **Take over this shift**.
