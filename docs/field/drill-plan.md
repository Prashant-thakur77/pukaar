# अभ्यास योजना · Monthly drill plan

A drill (अभ्यास) sends a labelled practice alert through the real Pukaar path to real, registered
phones in one pilot village, and measures how long it takes to reach people and who confirms it. It
tests the whole chain: the duty officer's phone, the approval, delivery, the relays' siren and
megaphone, "मिल गया", the call menu, and the pradhan's follow-up of unreachable numbers.

This plan turns the schedule in [RUNBOOK.md, "Drills"](../RUNBOOK.md#drills) into a step-by-step day.
The consented voice-call field drill in [VOICE.md](../VOICE.md#the-consented-field-drill) is the same
plan with `CHANNEL=voice`.

## Schedule

| When | Drill | Channel |
|---|---|---|
| Monthly, October to May | One village a month in rotation: Thunag, Janjehli, Gohar, Pandoh, Sujanpur | `all` |
| Weekly, 1 June to 30 September | Rotating villages | `all`, plus `voice` once a month for the consented voice households |
| Before 15 May | A full drill in every village | `all` |

## Safety and consent rules

These are not optional. Break one and the drill is cancelled.

1. **Never unannounced.** The pradhan and the village are told the date and hour at least 7 days before
   (T-7), and reminded the day before. Households registered for calls agreed to a practice call when
   they were registered (consent script in VOICE.md).
2. **Always labelled.** Every drill message starts "अभ्यास (DRILL), असली चेतावनी नहीं।" (Pukaar adds it to the
   alert text, the call, the officer's notifications, the roll-call and the all-clear). Never send a drill
   any other way, and never word a drill as a real warning on the megaphone: the relay says "यह अभ्यास है,
   असली चेतावनी नहीं".
3. **Never in bad weather.** Cancel if, on the day, the village is above Normal, IMD has an orange or red
   warning for Mandi, it is raining hard, or any village in the district has a live alert pending. A real
   alert always comes first: if one starts during the drill, stop the drill (section "Stopping a drill").
4. **Consent before calls.** `make drill CHANNEL=voice` refuses to run while any voice number in the
   village has no recorded consent. Never add a number on the day without the household's consent and
   the DPDP notice ([RUNBOOK.md, "Consent records"](../RUNBOOK.md#consent-records)).
5. **A person in the village.** A field volunteer is present to help anyone who pressed 2 or is upset by
   the call, and to collect feedback.
6. **No directives in a drill.** A directive from the console (Evacuate, Shelter in place, Advisory, All
   clear) is not labelled as a drill and shows on the village's public page. Do not issue one.
7. **Results are not targets for people.** Nobody is blamed for not answering; silence is a number-hygiene
   task for the pradhan.

## Roles

| Role | Who | Does |
|---|---|---|
| Drill lead | DDMO or the DEOC duty officer | Agrees the date with the pradhan, decides go / no-go on the day, signs the result sheet |
| Duty officer | The DEOC officer on shift | Receives and **approves** the drill alert as for a real one; watches recipients and the roll-call |
| Engineer | On-call engineer (Pukaar) | Runs the commands, checks the stack beforehand, reads the numbers afterwards |
| Pradhan (relay) | The village pradhan | Announces the drill in advance; on the day sounds the siren if agreed, announces "this is a practice" by megaphone, presses 1 or "मिल गया"; follows up unreachable households |
| Field volunteer | DDMA staff or a trained volunteer in the village | Stays in the village, times the siren and megaphone, helps anyone who pressed 2, asks five or six households afterwards |
| Timekeeper | Anyone at the DEOC with a clock | Notes the officer's own times (phone buzzed, link opened, decided) on the sheet |

## Timeline

### T-7 days: announce and check numbers
- Drill lead and pradhan agree the date and the hour (daytime, not a market or exam day). Write it in the
  DEOC log.
- Pradhan announces it in the village (gram sabha, temple, school, shops): the day, the hour, that the
  message will say "अभ्यास", and what people should do (listen, press 1 or "मिल गया").
- Engineer lists the village's registered voice numbers and checks every one has consent:
  ```
  make voice-list STAGE=prod VILLAGE=<id>
  ```
  The pradhan checks the Telegram sign-ups with the households (early-action checklist item "Telegram
  sign-ups checked").
- For a voice drill: confirm voice calls are on for the pilot (`VOICE_PROVIDER` in
  `.env.deploy.prod.local`) and that the stack was deployed with `AckWaitSeconds=600` and
  `VoiceRetrySeconds=600` (10 minutes between calls), as VOICE.md says for a voice pilot.

### T-1 day: remind and test
- Pradhan reminds the village.
- Duty officer for the drill hour checks their phone: **Send a test notification** under **Get approval
  alerts on this phone** in the console (Act tab), and that their Telegram is linked.
- Engineer checks the stack is healthy: no alarm in `ALARM`, the console's **System** card all OK, and the
  sweep heartbeat is fine (RUNBOOK, "Where to look").
- Engineer checks the duty roster for the drill hour has a primary, backup and escalation officer
  (`/roster`).

### T-0, 30 minutes before: go / no-go
- Drill lead checks the safety rules above (weather, levels, live alerts). Go or cancel; tell the pradhan
  either way.
- Field volunteer is in the village; pradhan has the megaphone and the siren ready.
- Engineer confirms the village has no open alert: the drill command refuses one
  ("already has an open alert").

### T-0: run the drill
1. Engineer starts the drill and notes the time (the alert's creation is the clock's zero):
   ```
   make drill STAGE=prod VILLAGE=<id> LEVEL=watch CHANNEL=all        # Telegram and calls, each person's own channel
   make drill STAGE=prod VILLAGE=<id> LEVEL=watch CHANNEL=telegram   # Telegram only
   make drill STAGE=prod VILLAGE=<id> LEVEL=watch CHANNEL=voice      # consented voice households only
   ```
   It prints the alert id and how many Telegram phones and voice numbers it will reach, then "Approve it
   in the console (or from the Telegram link)." The village's own level is not changed.
2. The duty officer's phone buzzes (Telegram link, Web Push labelled "[अभ्यास DRILL]", the console card).
   The officer opens it, presses **Listen**, checks the text starts "अभ्यास (DRILL), असली चेतावनी नहीं।", and
   presses **Approve**, then confirms. The timekeeper notes when the phone buzzed and when the officer
   decided. (To also test the reminder and wake-up call, agree beforehand that the officer waits past 3
   minutes; never in a real alert.)
3. Relays get it first. The pradhan announces the practice by megaphone ("यह अभ्यास है, असली चेतावनी नहीं"),
   sounds the siren if agreed, then presses 1 or **✅ मिल गया**. The field volunteer notes the time the
   siren and the announcement started and ended.
4. Everyone else gets the spoken alert. Unacknowledged phones get it again after `AckWaitSeconds`; voice
   numbers are called up to three times.
5. The duty officer watches **Recipients (N)** on the alert in **Recent alerts**: sent, acknowledged,
   "Relay done: siren and megaphone", failures. A 2 pressed on a call shows as a need-help item: the field
   volunteer goes to that house at once.
6. Optional, to exercise the roll-call: after the alert closes, open one from the console's **Roll-call**
   tab with **As an exercise (phones see "DRILL")** ticked (or run the drill at `LEVEL=warning` with the
   DDMA's agreement: a Warning drill opens the roll-call by itself as a labelled exercise when it closes).
7. The alert closes by itself after the re-send round. The pradhan announces by megaphone that the
   practice is over.

### T+1 hour: read the numbers
- Duty officer opens **After-action report ↗** under the drill alert and downloads it. "Key times" gives
  Level rose (the drill's start), Approved, First voice on a phone and First "मिल गया", with the gaps.
- Engineer reads per-person rows from the console's recipient list or `GET /alerts/{id}` (officer token)
  for the measures below. `/pilot` shows the same drill numbers across all drills.
- "Was this real?" cannot be answered for a drill; nothing to do there.

### T+1 day: follow up and record
- Field volunteer asks five or six households what they heard, whether the Hindi was clear, whether
  anyone pressed a key by mistake, and whether anyone was frightened.
- Pradhan checks every number flagged unreachable (sent to them on Telegram) and reports wrong or
  withdrawn numbers; the engineer removes them with `make voice-remove STAGE=prod VILLAGE=<id> ID=<recipient id>`.
- Drill lead fills in the result sheet, adds the row to the drill log in RUNBOOK's format, and sends it to
  the DDMA with the after-action report.

## Stopping a drill

If a real alert starts, the weather turns, or the village is alarmed:
1. The duty officer **declines** the drill alert if it is still pending (reason: "drill stopped").
2. If it was already delivered, the pradhan announces by megaphone that it was a practice and is over.
3. Real alerts are handled first. Note the stop and the reason in the drill log.

## What to measure

| Measure | How | Pilot target (agree with the DDMA) |
|---|---|---|
| Approval time | After-action report, Key times: Level rose → Approved | Within 10 minutes |
| Time to first voice | Approved → First voice on a phone | Within 2 minutes of approval |
| Time to first acknowledgement | Level rose → First "मिल गया" | |
| Relay time | Approved → "Relay done: siren and megaphone" on the pradhan's row; and the volunteer's siren and megaphone times | Within 10 minutes of approval (suggested) |
| Reached | People with a sent time ÷ people the drill was sent to | |
| Acknowledged in 15 minutes | Acknowledged within 15 minutes of approval ÷ reached | Half or more |
| Voice: reached | Voice rows with `sent_at` set ÷ households called | |
| Voice: pressed 1 | Rows with `digit: "1"` ÷ households called (report presses of 2 separately) | |
| Voice: calls needed | The spread of `attempts` (1, 2 or 3) among acknowledged rows | |
| Why not reached | Counts of `error_category` (busy, no_answer, failed, invalid_number, …), `not_connected`, `no_key` | |
| Unreachable | Rows marked unreachable; did the pradhan's note arrive, and did someone go to the house? | Every one checked within a week (RUNBOOK) |
| Failed deliveries | Rows with an error; Telegram "bot was blocked by the user" | Removed at the next number review |
| Roll-call (if run) | Safe / Need help / Not answered at 30 and 60 minutes | |

## Result sheet

Copy for each drill. Times in IST.

```
PUKAAR DRILL RESULT · अभ्यास का नतीजा

Date ____________   Village ____________   Level  watch / warning   Channel  all / telegram / voice
Alert id ____________________   Drill lead ____________   Duty officer ____________
Pradhan ____________   Field volunteer ____________   Engineer ____________

Go / no-go check at ____:____   weather OK [ ]  village at Normal [ ]  no live alert [ ]  announced on ________

TIMES                                      clock time      minutes from start
Drill started (alert created)              ____:____       0
Officer's phone buzzed                     ____:____       ____
Officer opened the link / console          ____:____       ____
Approved                                   ____:____       ____
First voice on a phone                     ____:____       ____
Relay pressed (Relay done)                 ____:____       ____
Siren started / megaphone started          ____:____       ____
Megaphone round finished                   ____:____       ____
First "मिल गया"                             ____:____       ____
Alert closed                               ____:____       ____

PEOPLE                                     Telegram        Voice        Total
Sent to                                    ____            ____         ____
Reached (sent time set)                    ____            ____         ____
Acknowledged (1 or मिल गया)                ____            ____         ____
  of them within 15 min of approval        ____            ____         ____
Pressed 2 (need help)                                      ____
Failed / not connected                     ____            ____         ____
Unreachable after 3 calls                                  ____
Voice: answered with no key (no_key)                       ____
Voice: calls needed for acknowledged       1: ____   2: ____   3: ____

ROLL-CALL (if run)   safe ____   need help ____   not answered ____   at ____:____

WHAT HOUSEHOLDS SAID (5 or 6)
1. ________________________________________________________________
2. ________________________________________________________________
3. ________________________________________________________________
4. ________________________________________________________________
5. ________________________________________________________________

PROBLEMS AND ACTIONS (who, by when)
________________________________________________________________________
________________________________________________________________________

Unreachable numbers followed up by pradhan on ________   removed ____   corrected ____

Signed: drill lead ______________   pradhan ______________
```

Then add one row to the drill log (RUNBOOK):

| Date | Village | Channel | Approved after | First voice after | First ack after | Reached / acknowledged | Notes |
|---|---|---|---|---|---|---|---|
