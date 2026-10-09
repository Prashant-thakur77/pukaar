# DEMO.md

A walk through the whole loop (about ten minutes with the full replay; the replay itself runs about six to seven), on the live URL or locally
(`make local`). Each step has a fallback if something is not available.

Before filming: `make reset-demo`. Deploy with short timers so timeouts show
on camera: `sam deploy --parameter-overrides ApprovalTimeoutSeconds=60 AckWaitSeconds=60`.

| # | Do | You should see | If it fails |
|---|---|---|---|
| 1 | Open the landing page | The promise, live counters, Watch -> Approve -> Call, the 112 button | Counters read 0 on a fresh stack; that is correct, not an error |
| 2 | Open **Live** | Map with five villages, each with a level icon and word; approximate-location note | If map tiles do not load, the village list below the map carries the same data |
| 3 | **Sign in** as `officer1` | Officer console: ranked village queue, pending approvals, reports, Ask Pukaar | Local mode: the demo-user buttons. AWS: the Cognito users from `make seed` |
| 4 | In the console press **Start replay** (July 2023) | REPLAY banner everywhere with a progress bar. The console asks for about 4 s per hour of data ("Replay speed: ~4 s per hour of data"), so the 97 hours take about 6-7 minutes. Sujanpur reaches critical first, within seconds; Pandoh and Gohar follow to critical about three to four minutes in. Open alerts stay pending at the level they rose to even after the village level eases: the alert card keeps the level it rose to. At the end the banner reads "Replay finished — Reset to clear" | If nothing rises, check `/replay/status`; `available` must list `himachal_2023_07` (`python -m Pukaar.scripts.fetch_replay`) |
| 5 | Open the pending Sujanpur alert | Hindi and English draft, which model wrote it, draft-check result, recipients count, decision trace with values against thresholds | With no model access the amber chip reads "Rule fallback: model unavailable — fixed Hindi template". That is the outage path working, not a bug. If the level rose again while the alert waited, the chip reads "Level rose while waiting — fixed template for the new level" |
| 6 | Press **Listen** | Kajal reads the Hindi alert | Locally there is no Polly: the text is shown instead |
| 7 | Sign in as `pradhan_thunag` in another window (a pradhan only sees their own village) | Header reads "Pradhan view"; no replay, directive, Telegram or phone-link controls. The pending card shows a disabled **Approve (officers only)** button; press **Try anyway** under it | Refused with the server's reason: "Only a district officer can approve an alert." The deny is in the audit trail. If Thunag has no pending alert yet, wait for the replay to raise it |
| 8 | Back as the officer: **Approve** | Status goes to delivered; under **Recent alerts**, delivered counts and the per-recipient list (name, channel, sent, acknowledged); replay alerts use the stub channel ("stub (no phone)") | — |
| 9 | On another pending card press **Open officer's phone link** (local mode) and approve there (tap, then confirm); then press it again, or reload that tab | The "One tap to approve" page; the confirm is a short bottom sheet on a phone. Then the 409 page in Hindi and English: "Already decided / पहले ही फ़ैसला हो चुका है". A broken link shows "This link is not valid" instead | AWS: the link arrives in the officer's Telegram; open it twice |
| 10 | On a phone that sent `/start sujanpur` to the bot (live, not replay) | Spoken alert in Telegram with a "मिल गया" button; tapping it shows in the console | No bot token: deliveries show the stub channel. List the token under "Needs human" |
| 11 | Open **Report** on a phone, choose a village, record a voice note or take a photo, send | A tracking code and link | Offline: it says it will send later; when the connection returns it sends, and the same screen turns into the tracking code and link |
| 12 | Officer console: the report appears; mark it verified, then undo | State changes, undo restores | — |
| 13 | **Ask Pukaar**: "Which villages need attention?" | Answer, bar chart with each bar in its village's level colour (icon and word in the legend) and a dashed 100 % "warning threshold" line, highlighted villages, tool trace. Under the chart: "Level also depends on rain, verified reports and the 3-sweep hold" | Without a model it says "rule-router (no model call)" and still answers from the tools |
| 14 | Open the **Audit trail** on the alert | Every allow and deny for that alert with the policy and reason; routine reads are hidden by default ("Show reads"), denies are counted and highlighted | — |
| 15 | Open **Impact** | Back-test table: July 2023 crosses; Mandi 2025 "never crossed", models missed it | — |
| 16 | **Reset replay** | The button reads "Resetting…", then a toast: "Replay reset: villages back to normal". Replay data gone, audit kept | — |

Talking points (15 seconds each): code decides and the model only words the
alert; every alert has a human approval; the model being down still sends the
fixed Hindi template; replay data is real and labelled; the Mandi 2025 miss is
shown honestly.
