# Pukaar (पुकार)

**The call that reaches the village before the river does.**

Pukaar is a flood-warning loop for Himalayan villages, built on AWS. A
15-minute sweep watches rain and river forecasts. Plain code sets a risk
level. A Bedrock agent drafts a Hindi alert (on the live stack, until Bedrock
model access is granted, the fixed Hindi template labelled `rule-fallback`),
and a district officer approves it with one tap. Villagers then hear the alert as a spoken message on their
phones, tap "मिल गया" (got it), and can report back by voice.

Built for Environmental Hacks (WeMakeDevs x AWS), Heat and Water track.

**Live:** https://main.d15r7ktz99l46x.amplifyapp.com · deployed on AWS (`us-east-1`, stack `pukaar-dev`) · public pages need no sign-in.

**Demo video (2:41):** [![Pukaar demo video: the 3D architecture scene](docs/media/pukaar-demo-poster.png)](docs/media/pukaar-demo.mp4)
[Watch the demo](docs/media/pukaar-demo.mp4) · [35-second trailer](docs/media/pukaar-trailer.mp4) · [script, chapters and captions](docs/submission/demo-script.md) · [submission writeup](docs/submission/writeup.md). The live scenes are recorded from the deployed site during a labelled replay on AWS, and the Hindi voice is the real Polly output. The video pipeline is in [video/](video/).

| Landing | Officer console | Villager report (phone) |
|---|---|---|
| ![Landing page](docs/screens/landing-1440-dark.png) | ![Officer console during a replay](docs/screens/console-1440-light.png) | ![Hindi-first report page](docs/screens/report-390-light.png) |

## The problem

In the hill districts of Himachal Pradesh a mountain stream can become a
flood within hours, often at night. On the night of 30 June to 1 July 2025,
cloudbursts struck Mandi district; early official figures were at least 10
people dead and 34 missing
([Down To Earth](https://www.downtoearth.org.in/natural-disasters/cloudbursts-devastate-himachals-mandi-at-least-10-dead-34-missing-after-1900-excess-rain-on-july-1)).

Forecasts exist, but they are numbers on a website, not a warning a villager
hears. Even when an official sees the danger in time, there is no quick way to
send a spoken Hindi warning to every household and know who heard it. Pukaar
is built around the gaps between a forecast and a family moving to high ground:

| Gap | What Pukaar does about it |
|---|---|
| The forecast never becomes a decision for one village | Every 15 minutes, code turns rain and river forecasts into a level per village, from IMD rain bands and that village's own 1984-2024 river record |
| A text message can be missed, unread or in the wrong language | The alert is spoken Hindi (Polly), delivered to the phone with the text |
| A broadcast never says who heard it | Each phone taps "मिल गया"; anyone who has not is sent the alert again, and the live page shows the funnel from draft to acknowledgement |
| An AI could invent a number or a place in a warning | Code sets the level and the recipients; the model only fills a fixed Hindi template, and a checker rejects any number or place not in the decision trace |
| The one officer on duty may be asleep | Unanswered approvals move to the next officer; a critical alert with nobody answering goes out with the fixed template and is flagged unapproved |
| Global models can miss a cloudburst (they did in the 2025 back-test below) | A verified villager report can raise a level on its own |

Try it in two minutes: open the [live page](https://main.d15r7ktz99l46x.amplifyapp.com), scroll the landing page through "the night the river rose" (Gohar, July 2023, replayed through the real rules), then open **Live** for the 3D village map.

## Research and evidence

![Six sourced numbers on early warning, Himachal and Hindi](docs/charts/evidence.svg)

**Early warning works, when it reaches people.**
- Countries with less comprehensive multi-hazard early warning systems have a disaster-related mortality ratio "nearly six times higher" than countries with substantial to comprehensive coverage, and "nearly four times more disaster-affected people" ([WMO, *Global Status of MHEWS 2024*](https://wmo.int/publication-series/global-status-of-multi-hazard-early-warning-systems-2024)).
- "Just 24 hours warning of a coming storm or heat wave can cut the ensuing damage by 30 percent", and early warning systems "save lives and assets worth at least ten times their cost" ([Global Commission on Adaptation, *Adapt Now*, 2019, p.13](https://gca.org/wp-content/uploads/2019/09/GlobalCommission_Report_FINAL.pdf)).
- The UN's [Early Warnings for All](https://www.un.org/en/climatechange/early-warnings-for-all) initiative aims to protect everyone on Earth with early warning systems by the end of 2027.

**The last mile is where warnings fail.** The research Pukaar is built on:
- "A warning cannot be considered effective until it is received, understood and responded to by those at risk." In the same study, communities "strongly preferred voice short messaging service (SMS) and interactive voice response (IVR) because of easier accessibility and understanding of the message" (Cumiskey et al., 2015, *Int. J. Disaster Resilience in the Built Environment* 6(1), [doi:10.1108/IJDRBE-08-2014-0062](https://doi.org/10.1108/IJDRBE-08-2014-0062)). This is why Pukaar speaks the alert and asks for "मिल गया".
- "Early warnings do not always translate into an emergency response from all individuals at risk" (Perera et al., 2020, *IJDRR* 50, [doi:10.1016/j.ijdrr.2020.101794](https://doi.org/10.1016/j.ijdrr.2020.101794)).
- People-centred systems need local knowledge, a move "from the traditional expert-driven approach to one … driven by the vulnerable communities" (Baudoin et al., 2016, *Int. J. Disaster Risk Science*, [doi:10.1007/s13753-016-0085-6](https://doi.org/10.1007/s13753-016-0085-6); Hermans et al., 2022, *Natural Hazards*, [doi:10.1007/s11069-022-05468-8](https://doi.org/10.1007/s11069-022-05468-8)). This is why a verified villager report can raise a level on its own.
- Integrating crowdsourced observations improves flood forecasts in model studies (Mazzoleni et al., 2018, *HESS* 22, [doi:10.5194/hess-22-391-2018](https://doi.org/10.5194/hess-22-391-2018); their citizen observations were synthetic).

**Himachal is where it matters.**
- In the 2023 monsoon, "more than 500 people lost their lives" in Himachal Pradesh, with "45 Cloudburst and 83 flash floods" and recovery needs for sectoral damage of ₹8,667.66 crore ([Govt of Himachal Pradesh / HPSDMA, *Post Disaster Needs Assessment*, 2024](https://recovery.preventionweb.net/publication/report-post-disaster-needs-assessment-himachal-pradesh-monsoon-2023-floods-cloudbursts)).
- On 30 June to 1 July 2025, Mandi received 140.7 mm of rain, against an average of 6.9 mm ([Down To Earth](https://www.downtoearth.org.in/natural-disasters/cloudbursts-devastate-himachals-mandi-at-least-10-dead-34-missing-after-1900-excess-rain-on-july-1)).
- Cloudbursts in the Himalaya "have been increasing in both their frequency and intensity" (Kumar et al., 2018, *Polar Science*, [doi:10.1016/j.polar.2018.08.004](https://doi.org/10.1016/j.polar.2018.08.004)), and predicting them accurately "is a difficult task", with model resolution "one of the most important factors" (Chaudhuri et al., 2015, *Annales Geophysicae* 33, [doi:10.5194/angeo-33-671-2015](https://doi.org/10.5194/angeo-33-671-2015)).
- 85.9% of Himachal Pradesh's people are Hindi speakers in the Census 2011 language group (5,895,529 of 6,864,602; [Census of India 2011, C-16](https://censusindia.gov.in/nada/index.php/catalog/42458)), and Himachal has 9.45 million mobile subscribers ([TRAI, Aug 2026 data](https://trai.gov.in/sites/default/files/2026-09/PR_No125of2026_0.pdf)).

**What already exists, and where Pukaar fits.** Each cell below is only what the system's own public source states; "not stated" means the source is silent, not that the feature is missing.

| | Per-village thresholds | Spoken alert | Per-person acknowledgement | Human approval per alert | Villager reports back |
|---|---|---|---|---|---|
| [SACHET / CAP](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2257102) (NDMA): SMS and cell broadcast to geo-targeted areas, 19+ languages | not stated | not stated | not stated | not stated | not stated |
| [IMD warnings](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2247523): district impact-based colour warnings, Gram Panchayat-level forecasts | not stated | not stated | not stated | not stated | not stated |
| [CWC](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2247523): flood forecasts at identified locations when a threshold is reached; C-FLOOD inundation to village level | at identified river stations | not stated | not stated | not stated | not stated |
| [Google Flood Hub](https://sites.research.google/floodforecasting/): river forecasts up to 7 days, flash floods on a 20 km grid | not stated | not stated | not stated | not stated | not stated |
| **Pukaar** | yes (each village's own 1984-2024 river record) | yes (Polly, Hindi) | yes ("मिल गया") | yes (Step Functions) | yes (voice, photo, text) |

Pukaar is built to sit beside these, not replace them: their forecasts are its inputs, and it carries the last mile to a phone and back.

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
| Drafting | A Strands agent reads the decision trace through read-only tools and fills a fixed Hindi template; a checker rejects any number or place not in the trace. The live stack currently uses the fixed Hindi template labelled `rule-fallback` until Bedrock model access is granted | Bedrock (Amazon Nova) via Strands Agents; Cedar hook on every tool call |
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

### AWS in depth

Every row is deployed in stack `pukaar-dev` (`us-east-1`) and defined in
[infra/template.yaml](infra/template.yaml).

| Service | What it does in Pukaar | How it is set up | Code |
|---|---|---|---|
| **EventBridge Scheduler** | Runs the sweep every 15 minutes | `rate(15 minutes)`, `MaximumRetryAttempts: 0` (a late sweep is useless; the next one comes), dead-letter queue `pukaar-sweep-dlq-dev` | `infra/template.yaml` (`SweepSchedule`) |
| **Lambda** (4 functions, container images from one Dockerfile) | `pukaar-api-dev` (FastAPI behind the Lambda Web Adapter, 2048 MB, 29 s), `pukaar-sweep-dev`, `pukaar-workflow-dev` (one function, dispatch on `step`), `pukaar-worker-dev` (Transcribe, replay) | X-Ray tracing on every function, one IAM role per function, 30-day log retention | `backend/Dockerfile`, `backend/src/Pukaar/handlers/` |
| **API Gateway HTTP API** | Every route | Cognito JWT authorizer on the catch-all route; an explicit short list of public routes (health, overview, report, acknowledgement, signed approval link, Telegram webhook); CORS limited to the web origin; stage throttling 20 req/s, burst 50 | `infra/template.yaml` (`HttpApi`) |
| **Step Functions** (Standard) | One approval execution per alert: draft, ask officer, deliver, wait, re-send, close | `waitForTaskToken` callbacks with the timeout as a deploy parameter; `States.Timeout` moves to the next officer; `States.ALL` on every task goes to a failsafe; 2-hour execution limit; error-level logging; X-Ray | [infra/approval.asl.json](infra/approval.asl.json), `backend/src/Pukaar/workflow/steps.py` |
| **DynamoDB** | All state in one table | On-demand, `pk`/`sk`, one sparse GSI used as the open-work queue, TTL, point-in-time recovery, conditional writes for sweep dedupe and single-use approval tokens; audit rows are append-only | `backend/src/Pukaar/store/repo.py` |
| **Bedrock** (Amazon Nova 2 Lite, via Strands Agents) | Drafts the Hindi alert, structures reports, describes photos, answers officers ("Ask Pukaar") | Typed output, at most 4 turns, a fresh agent per call; whole-call retry in `us-west-2` on throttling, 5xx or timeouts; every tool call passes a Cedar hook; any failure returns `None` and the rule fallback runs. The live stack currently runs on that fallback (fixed Hindi template, labelled `rule-fallback`) until Bedrock model access is granted | `backend/src/Pukaar/llm/bedrock.py`, `backend/src/Pukaar/llm/tools.py` |
| **Polly** | Speaks every approved alert in Hindi | Voice Kajal, `hi-IN`, generative engine with a logged fallback to neural, MP3 stored in S3 under the alert id | `backend/src/Pukaar/voice/polly.py` |
| **Transcribe** | Turns villager voice reports into text | `hi-IN` batch job; the audio stays in S3 next to the transcript, so a failed transcription never loses a report | `backend/src/Pukaar/voice/transcribe.py` |
| **Cognito** | Officer and pradhan sign-in | User pool with groups `officer` and `pradhan` and a `village_ids` attribute; villagers need no account | `infra/template.yaml`, `scripts/seed_users.py` |
| **S3** | Alert audio, report photos and audio | Private, all public access blocked, SSE-S3, TLS-only bucket policy, presigned URLs | `backend/src/Pukaar/services/storage.py` |
| **SSM Parameter Store** | Telegram token, webhook secret, approval-link signing key | SecureString, read at start-up, never in an environment variable or the template | `scripts/put_secrets.sh` |
| **SQS** | Dead-letter queues for the sweep and the worker | SSE-SQS, 14-day retention, each with an alarm | `infra/template.yaml` |
| **CloudWatch** | Logs, metrics, nine alarms, one dashboard | Embedded metric format; alarms for model errors, model failover, API 5xx, failed approvals, both DLQs, a missing sweep heartbeat, failed deliveries and unacknowledged alerts; SNS topic for alarm e-mail | dashboard `pukaar-dev` |
| **Amplify Hosting** | Serves the web app | Manual deploy of the Vite build with the stack's outputs baked in | `scripts/deploy_web.sh` |
| **AWS Open Data (Terrain Tiles on S3)** | Real Himalayan relief for the 3D map and the landing-page valley | Terrarium tiles from `s3://elevation-tiles-prod`; the landing heightmap is baked once from them | `frontend/src/components/VillageMap.tsx`, `backend/src/Pukaar/scripts/story.py`, `scripts/build_hero_dem.py` |
| **AWS Budgets** | Keeps the hackathon cheap | Monthly cost budget with e-mail alerts at 80% actual and 100% forecast | account level |

### Guarantees the tests enforce

[backend/tests/test_template_safety.py](backend/tests/test_template_safety.py)
parses the real template on every test run and fails if:
- any IAM statement allows `*` or a whole service (`s3:*`);
- any statement grants a `"*"` resource for an action AWS allows to be scoped;
- the template contains anything billed by the hour (NAT gateway, EC2, RDS, OpenSearch, Kendra, load balancers and more);
- the table loses point-in-time recovery, TTL or on-demand billing; a log group loses its retention; the bucket stops being private, encrypted and TLS-only; a queue loses encryption; or the sweep schedule starts retrying.

[backend/tests/test_asl.py](backend/tests/test_asl.py) checks the state
machine itself: approve, decline, timeout to the next officer, critical
auto-send and a forced error into the failsafe.

### What it costs

Nothing runs between requests: no servers, no NAT gateway, no database
instance. At demo traffic the stack stays almost entirely inside the AWS free
tier. The parts that cost money even when small are Bedrock tokens (no model
call at level Normal), Polly and Transcribe after their free tiers, and ECR
storage for the two container images. A monthly budget alarm watches the
account.

Infrastructure as code: [infra/template.yaml](infra/template.yaml) (AWS SAM),
state machine [infra/approval.asl.json](infra/approval.asl.json).

## Built for cheap phones (measured)

The villager report page on the live site, first visit with an empty cache,
390 px phone screen, CPU slowed 4x (Chrome DevTools emulation, 11 Oct 2026):

| Network | Ready to record (the Hindi "बोलें" button is on screen) | Downloaded |
|---|---|---|
| Slow 3G (400 kbit/s, 400 ms latency) | 4.6 s | 129 kB |
| Fast 3G (1.6 Mbit/s, 150 ms latency) | 1.5 s | 129 kB |

After the first visit the page is cached by a service worker and opens with no
network; reports made offline are queued in the browser and sent when the
phone reconnects. The 3D map and the 3D landing scene are never downloaded on
this page, and are skipped on phones with data saver or under 4 GB of memory.

## Try it from your terminal (no sign-in)

These call the live API on AWS (API Gateway -> Lambda -> DynamoDB):

```bash
API=https://362iqe4oae.execute-api.us-east-1.amazonaws.com

curl -s $API/health                 # which AWS services the stack is using right now
curl -s $API/public/overview        # village levels, counters, recent alerts with delivery status
curl -s $API/villages/gohar         # one village: readings, alerts with Hindi text, nowcast, past events
curl -s $API/replay/status          # whether an archived-flood replay is running (always labelled replay)
curl -s -o /dev/null -w '%{http_code}\n' $API/me   # 401: officer routes need a Cognito token
```

Officer routes (approve, decline, start a replay, Ask Pukaar) need a Cognito
sign-in; the demo accounts are in [DEMO.md](DEMO.md).

## Built versus planned

| Piece | State |
|---|---|
| Sweep, risk rules, hysteresis, dedupe | Built and tested offline |
| Approval workflow (approve, decline, timeout, next officer, critical auto-send, failsafe) | Built; state machine path-tested offline |
| Bedrock drafting with checker and rule fallback | Built; tested with a scripted model |
| Polly voice, Telegram delivery, acknowledgement, re-send | Built; Telegram is live on the deployed stack (below) |
| Voice and photo reports, Transcribe, auto-verification, tracking | Built |
| Cedar roles, audit log, agent tool guard | Built and tested |
| Ask Pukaar analyst agent | Built (falls back to a keyword router without a model) |
| Replay and back-test on archived data | Built ([data/backtest.json](data/backtest.json)) |
| Web app: landing, live map, officer console, village, report, track, approve, impact | Built (see `frontend/`) |
| Deployed stack on AWS | **Live** since 11 Oct 2026: stack `pukaar-dev`, web app on Amplify. Checked live: Cognito sign-in, a replay on AWS starting real Step Functions approval executions, an officer approval moving an alert to delivered, and Polly writing the Hindi MP3 to S3. Steps: [docs/DEPLOY.md](docs/DEPLOY.md) |
| Bedrock on the live stack | **Pending.** Account model access has not been granted yet (AWS support case filed). Until it is, every live draft is the fixed Hindi template, labelled `rule-fallback` in the console and the audit trail, and Ask Pukaar uses its keyword router |
| Telegram on the live stack | **Live.** Bot [@PukaarRescuebot](https://t.me/PukaarRescuebot), webhook set; `/health` reports `telegram: configured`. Anyone who sends `/start <village id>` gets approved live alerts with the "मिल गया" button. Replay alerts never go to Telegram: they use the stub channel |
| Drill alert to a real phone (`make drill`) | Built: a labelled test alert ("अभ्यास (DRILL), असली चेतावनी नहीं") through the real approval workflow to registered phones; the village's level is untouched |
| Outbound voice call with "press 1" to acknowledge (Amazon Connect, playing the Polly clip) | Planned: reaches basic phones and people who cannot read |
| SMS copy of every approved alert (Amazon SNS, transactional) | Planned: the account starts in the SNS SMS sandbox, so only verified numbers until production access |
| River gauges over AWS IoT Core (MQTT, X.509 per device, topic rule into the same ingestion) | Planned: the HTTP ingestion with per-device signatures is the first step |
| Safe places and evacuation routes on the map; spoken approval; grounded voice Q&A; AgentCore; CAP export | Planned (stretch) |

## What the back-test shows (and what it does not)

![Gohar, July 2023: the 24-hour rain forecast against IMD's bands, with the level Pukaar's rules set each hour](docs/charts/gohar-2023.svg)

| ![Hours of warning before the river's peak day, per village, July 2023](docs/charts/backtest-lead.svg) | ![Peak forecast rain per village, July 2023 against 30 June 2025](docs/charts/two-monsoons.svg) |
|---|---|

The three charts are built from [data/backtest.json](data/backtest.json) and the Gohar replay by [scripts/build_charts.py](scripts/build_charts.py); no number in them is typed by hand.

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
