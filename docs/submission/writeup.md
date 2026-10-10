# Pukaar (पुकार): submission writeup

**The call that reaches the village before the river does.**

- Live app: https://main.d15r7ktz99l46x.amplifyapp.com (public pages need no sign-in)
- Code: https://github.com/Prashant-thakur77/pukaar
- Demo video (under 3 minutes): _YouTube link to be added at upload_
- Track: Heat and Water (floods, monsoon)

## The problem

In the hill districts of Himachal Pradesh a mountain stream can become a flood within hours, often at night. On the night of 30 June to 1 July 2025, cloudbursts struck Mandi district; early official figures were at least 10 people dead and 34 missing ([Down To Earth](https://www.downtoearth.org.in/natural-disasters/cloudbursts-devastate-himachals-mandi-at-least-10-dead-34-missing-after-1900-excess-rain-on-july-1)).

Forecasts exist, but they are numbers on a website, not a warning a villager hears. Even when an official sees the danger in time, there is no quick way to send a spoken Hindi warning to every household and know who heard it.

## What we built

A loop from forecast to a confirmed warning, for five villages in Mandi district:

1. **Every 15 minutes** the sweep reads rain and river forecasts for each village.
2. **Code sets the level, never a model**: IMD rain bands (64.5 / 115.6 / 204.5 mm in 24 h), each village's own 1984-2024 river percentiles, two-source agreement, verified villager reports, and hysteresis on the way down.
3. **A Hindi alert is drafted** into a fixed template; a checker rejects any number or place not in the decision trace. If the model is unavailable, the fixed template goes out and is labelled `rule-fallback`.
4. **A district officer approves in one tap** (console or a signed single-use link). No answer moves to the next officer; a critical alert with nobody answering goes out with the template and is flagged unapproved.
5. **Polly speaks it** in Hindi, and every registered phone gets the voice and a "मिल गया" (got it) button on Telegram. Anyone who has not confirmed is sent it again. The app times each alert from the level rising to the first confirmation.
6. **Villagers report back** by voice, photo or text from any phone, even offline (the report page is ready in 4.6 s on slow 3G). A verified report can raise a level on its own.

Back-test on archived data: for 7-11 July 2023, Gohar, Pandoh and Sujanpur reach Critical; Gohar's first Watch came 72 hours before the river's peak day. For 30 June-1 July 2025, the global forecasts missed the Mandi cloudburst; thresholds were not tuned to fake a hit, which is why villager reports can raise a level.

## Where AWS fits

Deployed as one AWS SAM stack (`pukaar-dev`, us-east-1); nothing runs between requests.

| Service | Role |
|---|---|
| EventBridge Scheduler | The 15-minute sweep; zero retries, dead-letter queue |
| Lambda (4 container functions) | API (FastAPI behind the Lambda Web Adapter), sweep, workflow steps, worker |
| Step Functions (Standard) | One approval execution per alert: `waitForTaskToken`, next officer on timeout, critical auto-send, failsafe |
| DynamoDB | One table, sparse GSI, conditional writes (no double sends), TTL, point-in-time recovery |
| Bedrock (Amazon Nova via Strands Agents) | Drafts the Hindi alert and answers officers' questions; Cedar hook on every tool call. Model access on our account is pending, so the live stack currently sends the fixed template, labelled |
| Polly (Kajal, hi-IN) | Speaks every alert; MP3 in S3 |
| Transcribe (hi-IN) | Villager voice reports |
| API Gateway HTTP API + Cognito | Every route; officer and pradhan sign-in; villagers need no account |
| S3, SSM Parameter Store, SQS | Private audio and photos; secrets; encrypted dead-letter queues |
| CloudWatch + X-Ray | Nine alarms, one dashboard, tracing on every function |
| Amplify Hosting | The web app (PWA) |
| AWS Open Data (Terrain Tiles) | Real Himalayan relief for the 3D map and the landing valley |

Tests parse the real template and fail on any `*` IAM action, any hourly-billed resource, or a table, bucket or queue that loses its protections.

## AI tools used

Claude Code (Anthropic) wrote most of the code under human direction; separate reviewer agents graded each piece. The demo video's narration is Chatterbox TTS (open source) with its built-in synthetic voice.
