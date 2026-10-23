# Pukaar (पुकार): submission writeup

**The call that reaches the village before the river does.**

- Live app: https://main.d15r7ktz99l46x.amplifyapp.com (public pages need no sign-in)
- Code: https://github.com/Prashant-thakur77/pukaar
- Demo video (2:44): [docs/media/pukaar-demo.mp4](../media/pukaar-demo.mp4), with [script, chapters and captions](demo-script.md)
- Pitch video (4:20): [docs/media/pukaar-pitch.mp4](../media/pukaar-pitch.mp4), with [sources and credits](../media/pukaar-pitch-credits.md)
- Both narrations are Chatterbox TTS (open source) with its built-in synthetic voice; the Hindi alert is real Amazon Polly output ([media credits](../media/CREDITS.md))
- Track: Heat and Water (floods, monsoon)

**Pilot system; follow DDMA and IMD warnings; emergency 112 / 1077.** Pukaar is not an official warning channel.

## The problem

In the hill districts of Himachal Pradesh a mountain stream can become a flood within hours, often at night. On the night of 30 June to 1 July 2025, cloudbursts struck Mandi district; early official figures were at least 10 people dead and 34 missing ([Down To Earth](https://www.downtoearth.org.in/natural-disasters/cloudbursts-devastate-himachals-mandi-at-least-10-dead-34-missing-after-1900-excess-rain-on-july-1)).

Forecasts exist, but they are numbers on a website, not a warning a villager hears. Even when an official sees the danger in time, there is no quick way to send a spoken Hindi warning to every registered household and know who heard it.

## What we built

A loop from forecast to a confirmed warning, for five villages in Mandi district:

1. **Every 15 minutes** the sweep reads rain and river forecasts for each village.
2. **Code sets the level, never a model**: IMD rain bands (64.5 / 115.6 / 204.5 mm in 24 h), the 2-, 5- and 20-year river discharges at each village's river cell with the GloFAS ensemble's probability, two-source agreement, verified villager reports, and hysteresis on the way down.
3. **A Hindi alert is drafted** into a fixed template; a checker rejects any number or place not in the decision trace. If the model is unavailable, the fixed template goes out and is labelled `rule-fallback`.
4. **A district officer approves in one tap** (console or a signed single-use link). No answer moves to the next officer; a critical alert with nobody answering goes out with the template and is flagged unapproved.
5. **Polly speaks it** in Hindi, and every phone registered with the Telegram bot gets the voice and a "मिल गया" (got it) button. Anyone who has not confirmed is sent it again. The app times each alert from the level rising to the first confirmation. A press-1 voice call for keypad phones is built and off: Indian A2P calls must come from a government principal entity on DLT, so it waits for a DDMA.
6. **A river gauge can speak too.** A low-cost water-level gauge at a bridge (ESP32 with a waterproof ultrasonic sensor; design and firmware sketches in `docs/hardware/`) publishes readings over MQTT to AWS IoT Core with its own X.509 certificate, or posts signed readings over HTTPS; the rules treat it as a third evidence source beside the two forecasts. No gauge is installed yet: on the live stack the readings are simulated and labelled so (`make gauge-sim-mqtt`).
7. **Villagers report back** by voice, photo or text from any phone, even offline (the report page is ready in 4.6 s on slow 3G). Bedrock Guardrails screen the text first, so a report that tries to give the system orders is held for an officer. A verified report can raise a level on its own.
8. **Where to go.** Named safe places from OpenStreetMap, at least 15 m above the river, with slope-aware walking routes; the pradhan marks each one open, standby, full or closed, and the alert names the nearest open one. A pradhan or officer can mark a road or bridge on a route blocked, and the alert then names the next place with an open route.
9. **After the alert.** When a live warning or critical alert closes, a "Surakshit Hoon" (I am safe) roll-call asks each Telegram recipient "Are you safe?" with two buttons and shows the officer who needs help first. Every closed alert gets an after-action report in Hindi and English, stored in S3 and e-mailed by SES to verified addresses.
10. **Open and live.** Every alert that goes out is also published in a CAP 1.2 feed, the standard SACHET is built on (Pukaar does not send into SACHET yet). Open pages update within about a second through AppSync Events, and officers can approve from a Web Push notification with the console closed.

Why this design: countries with limited early-warning coverage have nearly six times the disaster mortality ratio (WMO, 2024); in Bihar, trained village volunteers made households 46.5% more likely to get a flood warning before the water arrived (Jagnani & Pande, 2024); and communities "strongly preferred voice" messages "because of easier accessibility and understanding" (Cumiskey et al., 2015). In Himachal's 2023 monsoon about 500 people died (NDMA Post Disaster Needs Assessment, reported by The Tribune, 3 Feb 2024). Sources and a comparison with SACHET, IMD, CWC and Google Flood Hub are in the README.

## What is measured, and what is design

Measured so far (23 Oct 2026): the 15-minute sweep made 479 of 480 expected forecast checks in 24 hours; 0 real alerts have gone out; 1 drill (Gohar, 11 Oct 2026) was delivered to 3 phones and none pressed "मिल गया". The river gauges are simulators; the siren nodes, rain nodes and pradhan boxes exist as firmware only, untested on hardware; voice calls are off until a DDMA registers as the DLT principal entity. Reach, confirmation rates and real-world lead time are design goals until the pre-registered 2027 pilot measures them ([docs/PILOT_PROTOCOL.md](../PILOT_PROTOCOL.md)). Cost and benefit estimates, with the low case below 1, are in [docs/BUSINESS_MODEL.md](../BUSINESS_MODEL.md).

Back-test on archived data: for 7-11 July 2023, Sujanpur reaches Critical and Gohar and Pandoh reach Warning; Gohar's first Watch (from rain) came 67 hours before the river's highest day in the window. For 30 June-1 July 2025, the global forecasts missed the Mandi cloudburst; thresholds were not tuned to fake a hit, which is why villager reports and river gauges can raise a level. Scored against a small sourced ground truth with a source ablation (docs/SCORING.md): since the river trigger moved to the 2-year flood, the Pandoh flood is caught as an alert by rain alone, 19 h ahead; the river's get-ready outlook, shown to the officer and pradhan but never an alert, was on at least 48 h ahead.

## Where AWS fits

Deployed as one AWS SAM stack (`pukaar-dev`, us-east-1); nothing runs between requests. The Terrain Tiles are a public AWS Open Data bucket, and SES addresses are verified on the account.

| Service | Role |
|---|---|
| EventBridge Scheduler | The 15-minute sweep; zero retries, dead-letter queue |
| Lambda (6 container functions) | API (FastAPI behind the Lambda Web Adapter), sweep, workflow steps, worker, gauge ingest (AWS IoT Core topic rule), a canary that checks the public site and API every 15 minutes |
| Step Functions (Standard) | One approval execution per alert: `waitForTaskToken`, next officer on timeout, critical auto-send, failsafe |
| DynamoDB | One table, sparse GSI, conditional writes (no double sends), TTL, point-in-time recovery |
| Bedrock (Amazon Nova 2 Lite via Strands Agents) | Drafts the Hindi alert and answers officers' questions; Cedar policies (the open-source Cedar engine, `cedarpy`) checked on every tool call. Model access on our account is pending, so the live stack currently sends the fixed template, labelled `rule-fallback` |
| Bedrock Guardrails | Screens every villager report before any rule or model reads it; live now, since `ApplyGuardrail` needs no model access |
| Polly (Kajal, hi-IN) | Speaks every alert; MP3 in S3 |
| Transcribe (hi-IN) | Villager voice reports |
| API Gateway HTTP API + Cognito | Every route; officer and pradhan sign-in; villagers need no account |
| S3, SSM Parameter Store, SQS | Private audio and photos; secrets; encrypted dead-letter queues |
| CloudWatch + X-Ray | Nineteen alarms, one dashboard, tracing on every function but the canary |
| Amplify Hosting | The web app (PWA) |
| AWS Open Data (Terrain Tiles) | Real Himalayan relief for the 3D map and the landing valley |
| AWS IoT Core | River gauges over MQTT with one X.509 certificate per device; a policy pinned to the device's own topic; a topic rule into the gauge-ingest Lambda |
| AppSync Events | Live push of level and alert changes to open pages: public channel on a subscribe-only API key, officer channel on Cognito, publishing by IAM only |
| SES | E-mails the after-action report (the account is in the SES sandbox, so only to verified addresses) |

Tests parse the real template and fail on any `*` IAM action, any hourly-billed resource, or a table, bucket or queue that loses its protections.

## AI tools used

Used Claude to help write code.
