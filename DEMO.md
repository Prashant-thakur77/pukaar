# DEMO.md

A three-minute walk through the whole loop, on the live URL or locally
(`make local`). Each step has a fallback if something is not available.

Before filming: `make reset-demo`. Deploy with short timers so timeouts show
on camera: `sam deploy --parameter-overrides ApprovalTimeoutSeconds=60 AckWaitSeconds=60`.

| # | Do | You should see | If it fails |
|---|---|---|---|
| 1 | Open the landing page | The promise, live counters, Watch -> Approve -> Call, the 112 button | Counters read 0 on a fresh stack; that is correct, not an error |
| 2 | Open **Live** | Map with five villages, each with a level icon and word; approximate-location note | If map tiles do not load, the village list below the map carries the same data |
| 3 | **Sign in** as `officer1` | Officer console: ranked village queue, pending approvals, reports, Ask Pukaar | Local mode: the demo-user buttons. AWS: the Cognito users from `make seed` |
| 4 | In the console press **Start replay** (July 2023) | REPLAY banner everywhere; Sujanpur, Pandoh and Gohar climb to critical within about a minute | If nothing rises, check `/replay/status`; `available` must list `himachal_2023_07` (`python -m Pukaar.scripts.fetch_replay`) |
| 5 | Open the pending Sujanpur alert | Hindi and English draft, which model wrote it (or "rule fallback"), draft-check result, recipients count, decision trace with values against thresholds | With no model access the fixed template shows, labelled "rule fallback". That is the outage path working, not a bug |
| 6 | Press **Listen** | Kajal reads the Hindi alert | Locally there is no Polly: the text is shown instead |
| 7 | Sign in as `pradhan_thunag` in another window and try to approve | Refused: "Only a district officer can approve an alert." | — |
| 8 | Back as the officer: **Approve** | Status goes to delivered; deliveries list each phone; replay alerts show the stub channel | — |
| 9 | Approve again (or open the old link) | The 409 page in Hindi and English: already decided | — |
| 10 | On a phone that sent `/start sujanpur` to the bot (live, not replay) | Spoken alert in Telegram with a "मिल गया" button; tapping it shows in the console | No bot token: deliveries show the stub channel. List the token under "Needs human" |
| 11 | Open **Report** on a phone, choose a village, record a voice note or take a photo, send | A tracking code and link | Offline: it says it will send later, and sends when the connection returns |
| 12 | Officer console: the report appears; mark it verified, then undo | State changes, undo restores | — |
| 13 | **Ask Pukaar**: "Which villages need attention?" | Answer, bar chart, highlighted villages, tool trace | Without a model it says "rule-router (no model call)" and still answers from the tools |
| 14 | Open the alert's audit trail | Every allow and deny with the policy and reason | — |
| 15 | Open **Impact** | Back-test table: July 2023 crosses; Mandi 2025 "never crossed", models missed it | — |
| 16 | **Reset replay** | Villages back to normal, replay data gone, audit kept | — |

Talking points (15 seconds each): code decides and the model only words the
alert; every alert has a human approval; the model being down still sends the
fixed Hindi template; replay data is real and labelled; the Mandi 2025 miss is
shown honestly.
