# Live jury demo

For a pitch in front of a jury (the Tata Imagination Challenge Idea Defence: 10 minutes and 5 minutes of
questions, on a video call). Jurors join from their own phones in about 30 seconds. You approve one practice
alert as the duty officer, and within seconds each juror's Telegram gets the spoken Hindi alert with the
"मिल गया" button. The presenter screen counts joined, delivered and confirmed, and the seconds to the first and
the median confirmation, live. Then the jury sees the same records and the ten pilot metrics a DDMA would see.

Code: `backend/src/Pukaar/services/demo.py`, `api/routers/demo.py`, the page `frontend/src/pages/console/LiveDemo.tsx`
(`/console/demo`), Cedar `run_demo` and `view_demo` in `policy/base.cedar`, tests in `backend/tests/test_live_demo.py`.

## What keeps it safe

- **Its own village.** `demo` ("डेमो गाँव / Demo village", district "Demo") is never in the village registry: it
  is not on any public page, the overview, the CAP feed, a SACHET request, the sweep (rules, forecasts, sirens),
  the counters or the ten pilot metrics. A page, report or enrolment form that names it gets 404.
- **Its own alerts.** A demo alert is written to its own log, never the alert log every list reads. It goes only to
  the demo village's consented people; dispatch and Cedar (`demo-stays-in-demo`) refuse it anywhere else, and
  refuse any other alert inside the demo village. It goes out only after an officer's hold-to-approve: never by
  auto-send or the failsafe, no roll-call, no siren, no SACHET, no after-action e-mail.
- **The message** is a fixed five-element script naming the demo village, under
  "अभ्यास / DEMO — यह असली चेतावनी नहीं है (this is not a real warning)", with the Polly audio and the "मिल गया" button.
- **Joining.** Telegram `/start demo-<code>`. The 4-digit code rotates per session and expires after 30 minutes; it
  shows only on the presenter screen (never to the public `judge` accounts). The notice, in Hindi and English:
  "This is a demo for the Tata Imagination Challenge jury; you will get one practice alert marked DEMO; your Telegram
  name and chat id are deleted within 24 hours." Nothing is stored before "I agree".
- **Limits.** At most 50 people per session; one demo alert per 2 minutes; and the per-village send guard's six
  alerts an hour.
- **Erasure.** The sweep deletes demo people and demo alerts (with their delivery rows) 24 hours after they were
  made; "Reset demo" (or `make demo-reset`) deletes them at once. Audit rows say "demo" and hold no name or chat id.
- **Who.** An officer or a state operator runs it (`run_demo`). The `judge` account may watch `/console/demo`
  (`view_demo`) but never sees the code, starts the alert, approves it or resets it. It is off on `STAGE=prod`
  unless `PUKAAR_LIVE_DEMO=true`.

## How to run it

1. The day before, on the dev stack: `make demo-open`. It prints the presenter URL, the code and the QR link
   (`https://t.me/PukaarRescuebot?start=demo-<code>`). Do one full rehearsal with two phones of your own, then
   `make demo-reset`.
2. Sign in as an officer (not `judge`) on the laptop you will share and open `/console/demo` (the URL above, or
   **Live demo** in the console's Demo group, which Settings turns on). Link your own Telegram in Settings if you
   want the approval link on your phone too.
3. In the pitch, share the screen and press **Open the demo** (or **New code**): the QR and the 4-digit code show
   large. Ask the jurors to scan it, or to send `/start demo-<code>` to @PukaarRescuebot, and press "I agree".
   The **Joined** count rises live.
4. Press **Start the demo alert**. Within a few seconds the practice alert appears under it (the fixed message,
   **Listen** for the audio). Hold **Approve** for one second: the real officer step, the same route and Cedar check
   as the inbox.
5. The jurors' phones get the spoken alert; as they press "मिल गया", **Delivered**, **Confirmed** and the seconds
   to the first and the median confirmation update. The timeline reads approved, sent, first "मिल गया".
6. Below, "What a DDMA sees for this alert": the ten pilot metrics for this alert, and a link to its record in
   the console (deliveries, timeline, the Cedar audit rows).
7. Afterwards press **Reset demo** (or `make demo-reset`). Anything left is erased by the sweep within 24 hours.

## Pre-flight checklist

- [ ] `/health` says `telegram: configured`; the bot answers `/start` on your own phone.
- [ ] `make demo-open` works and prints a code; your phone joins with it and gets the notice first.
- [ ] A rehearsal alert reached two phones and both "मिल गया" taps counted; Polly audio plays (**Listen**).
- [ ] You are signed in as an officer, not `judge`, and the laptop will not sleep; the browser zoom suits the share.
- [ ] `make demo-reset` after the rehearsal; open a fresh code in the last few minutes before the pitch
      (it lasts 30 minutes).
- [ ] The fallback below is ready in another tab.

## If something fails

- **A juror cannot join** (no Telegram, a work phone): they watch the screen; you join on your own phone.
- **Telegram is slow or down**: the timeline and the counts still show approved and sent; switch to the recorded
  demo video and the July 2023 replay (`DEMO.md`, step 4), which uses the stub channel and needs no phone.
- **"One demo alert per 2 minutes"**: wait for the countdown on the button. **"Still open"**: approve or decline the
  waiting alert first (or **Reset demo**).
- **The code expired**: **New code**; anyone already joined stays joined.
