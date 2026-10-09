# Pukaar (पुकार)

**The call that reaches the village before the river does.**

Pukaar is a flood-warning loop for Himalayan villages, built on AWS. A
15-minute sweep watches rain and river forecasts. Plain code sets a risk
level. A Bedrock agent drafts a Hindi alert, and a district officer approves
it with one tap. Villagers then hear the alert as a spoken message on their
phones, tap "मिल गया" (got it), and can report back by voice.

Built for Environmental Hacks (WeMakeDevs x AWS), Heat and Water track.

## The problem

In the hill districts of Himachal Pradesh a mountain stream can become a
flood within hours, often at night. Forecasts exist, but they are numbers on
a website, not a warning a villager hears. Even when an official sees the
danger in time, there is no quick way to send a spoken Hindi warning to every
household and know who heard it.

## Who it is for

- **District and block disaster officers**: they approve every alert on their
  phone and see who acknowledged it.
- **Village pradhans**: they see their own village's reports and alerts.
- **Villagers**: they need no account. They hear alerts on Telegram, tap
  once to confirm, and report from any phone browser, even offline.

## What happens, moment by moment

| Moment | What Pukaar does | AWS service |
|---|---|---|
| Every 15 minutes | For five villages, read forecast rain (next 24 h) and river discharge (next days) | EventBridge Scheduler -> Lambda `sweep` |
| A threshold is crossed | Code sets the level: IMD rain bands, each village's own 1984-2024 discharge percentiles, two-source agreement, verified reports; hysteresis on the way down | Lambda, DynamoDB (conditional writes, dedupe per 15-minute window) |
| The level rises | An approval workflow starts, one per alert | Step Functions (Standard, `waitForTaskToken`) |
| Drafting | A Strands agent reads the decision trace through read-only tools and fills a fixed Hindi template; a checker rejects any number or place not in the trace | Bedrock (Amazon Nova) via Strands Agents; Cedar hook on every tool call |
| Voice | The Hindi text becomes speech | Polly (Kajal, hi-IN), MP3 in S3 |
| Approval | The officer gets a signed one-tap link (30 min, single use) and a console entry; no answer moves to the next officer; a critical alert with no answer goes out unapproved and is flagged | Step Functions timeouts, Cognito, Cedar |
| Delivery | Spoken alert plus text and a "मिल गया" button; one automatic re-send to anyone who has not acknowledged | Lambda, Telegram Bot API |
| A villager reports | Voice, photo or text, from any phone; queued offline; a tracking code back | API Gateway, S3, Transcribe (hi-IN), Bedrock |
| Verification | Code verifies a report when GPS is inside the village and a second report agrees nearby, or the photo matches | Lambda |
| An officer asks | "Which villages need attention?" gets an answer, a chart and a map built from tool data | Bedrock agent with read-only tools |
| Every decision | Allow or deny, with the policy and reason, in an append-only audit log | Cedar (`cedarpy`), DynamoDB |
| Operations | Alarms on model errors, failover, workflow failures, DLQs, a missing sweep heartbeat, delivery failures and unacknowledged alerts; one dashboard | CloudWatch (embedded metric format) |

Three rules hold everywhere:
- **Code decides, the model words.** The model never sets a level, never decides to send and never picks who receives an alert.
- **A model outage still alerts.** If Bedrock is down, the fixed Hindi template goes out and the alert records `rule-fallback`.
- **Replay is always labelled.** Replay data is real archived data, it carries `replay: true` everywhere, and it never reaches a real phone.

## Architecture

![Pukaar architecture on AWS](docs/architecture.svg)

<details><summary>Text version</summary>

```
 EventBridge Scheduler ──15 min──> Lambda sweep ──> DynamoDB (one table, sparse GSI)
        Open-Meteo forecasts ─────┘      │ level rises
                                         v
                      Step Functions approval workflow ──> Lambda workflow steps
              draft (Bedrock agent + checker + Polly) -> ask officer (task token,
              signed link) -> deliver (Cedar + action guard) -> wait -> re-send -> close
                    timeout -> next officer -> critical auto-send | expire
                    any error -> failsafe
                                         │
 Officer phone / console (Amplify) <── API Gateway HTTP API + Cognito ──> Lambda api (FastAPI)
 Villager phone: Telegram voice alert, "मिल गया"  <── Telegram Bot API
 Villager report: web form -> S3 -> Lambda worker (Transcribe, Bedrock) -> verify -> sweep
```

</details>

| AWS service | Used for |
|---|---|
| Lambda (4 container-image functions) | API (FastAPI behind the Lambda Web Adapter), sweep, workflow steps, worker |
| API Gateway HTTP API | Routes, Cognito JWT authorizer, CORS, throttling |
| Step Functions | Approval with callbacks, timeouts, officer escalation, failsafe |
| EventBridge Scheduler | The 15-minute sweep (no retries, dead-letter queue) |
| DynamoDB | All state, conditional writes, TTL, point-in-time recovery |
| Bedrock (Amazon Nova) + Strands Agents | Drafting, report structuring, photo description, Ask Pukaar |
| Polly | Hindi speech for every alert |
| Transcribe | Hindi voice reports |
| Cognito | Officer and pradhan sign-in, groups |
| S3 | Audio, photos (presigned URLs) |
| SSM Parameter Store | Bot token and signing keys (SecureString) |
| SQS | Dead-letter queues |
| CloudWatch | Logs, metrics, alarms, dashboard |
| Amplify Hosting | The web app |

Infrastructure as code: [infra/template.yaml](infra/template.yaml) (AWS SAM),
state machine [infra/approval.asl.json](infra/approval.asl.json).

## Built versus planned

| Piece | State |
|---|---|
| Sweep, risk rules, hysteresis, dedupe | Built and tested offline |
| Approval workflow (approve, decline, timeout, next officer, critical auto-send, failsafe) | Built; state machine path-tested offline |
| Bedrock drafting with checker and rule fallback | Built; tested with a scripted model |
| Polly voice, Telegram delivery, acknowledgement, re-send | Built; needs a bot token for a real phone |
| Voice and photo reports, Transcribe, auto-verification, tracking | Built |
| Cedar roles, audit log, agent tool guard | Built and tested |
| Ask Pukaar analyst agent | Built (falls back to a keyword router without a model) |
| Replay and back-test on archived data | Built ([data/backtest.json](data/backtest.json)) |
| Web app: landing, live map, officer console, village, report, track, approve, impact | Built (see `frontend/`) |
| Deployed stack on AWS | **Not yet**: steps in [docs/DEPLOY.md](docs/DEPLOY.md) |
| Spoken approval, grounded voice Q&A, safe-places map, AgentCore, CAP export | Planned (stretch) |

## What the back-test shows (and what it does not)

The replay runs archived hours through the same code. Rain is the archived
forecast (Open-Meteo historical forecast API). Discharge is the archived
GloFAS series from the Open-Meteo flood API.

- **7-11 July 2023:** Sujanpur, Gohar and Pandoh reach critical, and Thunag
  and Janjehli reach watch.
- **30 June to 1 July 2025, Mandi:** the archived forecasts gave at most
  14-34 mm in 24 hours at four of the villages, and discharge never crossed
  even the 90th percentile at four of five villages. **The global models
  missed the cloudburst.** Thresholds were not tuned to fake a hit. This is
  why a verified villager report can raise a level on its own.

Not yet measured:
- Real-world lead time. Replay discharge stands in for a perfect forecast, so
  the replay's lead times are optimistic.
- Delivery and acknowledgement rates on real phones.
- Transcribe accuracy on Himachali Hindi.
- False-alarm rate over a full monsoon.

## Data sources

- Village coordinates: Open-Meteo geocoding (GeoNames). Not verified on the ground.
- Rain forecasts: Open-Meteo forecast API and historical forecast API.
- River discharge and its 1984-2024 history: Open-Meteo flood API (GloFAS).
- Rain bands: India Meteorological Department 24-hour categories (64.5, 115.6 and 204.5 mm).

No populations, casualty figures or other numbers are invented. Unknown
values stay empty.

## Run it locally (no AWS account needed)

```bash
make install   # uv + npm
make local     # API on :8000 (local mode: in-process AWS mock), web on :5173
```

Open http://localhost:5173. Sign in as `officer1` and press "Start replay".
Local mode runs the whole loop with an in-process mock of DynamoDB and S3 and
a threaded copy of the state machine. Bedrock, Polly and Transcribe are not
mocked, so you see the rule fallbacks.

Tests:

```bash
make test      # backend pytest (offline) + frontend vitest + build
```

Deploy to AWS: [docs/DEPLOY.md](docs/DEPLOY.md).

## More

- [DEMO.md](DEMO.md): the demo click path, with a fallback for each risk.
- [docs/RESILIENCE.md](docs/RESILIENCE.md): what happens when each part fails.
- [docs/CONTRACT.md](docs/CONTRACT.md): API routes and shapes.
- [PLAN.md](PLAN.md), [PROGRESS.md](PROGRESS.md), [DECISIONS.md](DECISIONS.md), [SCORECARD.md](SCORECARD.md), [CODEMAP.md](CODEMAP.md).

## AI tools used

Built with Claude Code (Anthropic). Claude wrote most of the code under
human direction; reviewer agents with no memory of the build graded each
piece (SCORECARD.md).

## Acknowledgements

<!-- To be written by the team before submission. -->

Emergency number in India: **112**.
