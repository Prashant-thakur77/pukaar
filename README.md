# Pukaar (पुकार)

The call that reaches the village before the river does.

## The problem

In the hill districts of Himachal Pradesh, a stream can turn into a flood within hours of heavy rain, often at night. Rain and river forecasts for these places exist, but they are numbers on a website, not a message a villager hears. Even when an official sees the danger in time, there is often no quick way to send a spoken warning in Hindi to every household and know who received it.

## What it does

Pukaar is being built as a flood warning loop for Himalayan villages. A scheduled sweep will read rain and river forecasts for each village, and plain code will set a risk level: normal, watch, warning or critical. When the level rises, a model drafts a short Hindi alert from a fixed template, a district officer approves it on their phone, and villagers get it as a voice message. They tap once to confirm they heard it and can send back a voice report of what they see. Section "Current status" below says which parts exist today.

By design, the model never decides the level, never decides to send and never picks who receives an alert, and a model outage still sends a fixed Hindi template.

## Who it is for

District and block disaster officers who approve alerts, village pradhans who pass them on, and villagers who receive them and report back. Villagers need no Pukaar account; alerts are planned to reach them through Telegram.

## Target architecture on AWS

| Piece | AWS service |
|---|---|
| Sweep every 15 minutes | EventBridge Scheduler, Lambda |
| API | API Gateway HTTP API, Lambda (FastAPI) |
| Officer approval and timeouts | Step Functions |
| Hindi drafting and report structuring | Bedrock (Amazon Nova) through Strands Agents |
| Voice out | Polly, Hindi voice Kajal |
| Voice reports in | Transcribe, `hi-IN` |
| Data | DynamoDB |
| Audio and photos | S3 |
| Sign-in and roles | Cognito, Cedar policies |
| Web app hosting | Amplify Hosting |
| Logs, alarms, dashboard | CloudWatch |

Alerts reach phones through a Telegram bot. Region: `us-east-1`. Full detail is in [PLAN.md](PLAN.md).

## Current status

The repository started from an earlier flood-warning codebase built for Argentina. It has been cleaned down to the parts Pukaar keeps; nothing is deployed to AWS yet.

Works today, locally:

- A web report form (text, photo, voice note) that queues reports in the browser while offline and sends them when the connection returns.
- Report structuring with keyword rules, plus an optional local model; the more severe reading wins.
- Rain and river data from Open-Meteo, fetched on request for one site.
- Rule-based scoring of recent reports and hydromet data into four levels, with a stored decision trace and a short reasoning text that falls back to a rule summary when no model is available.
- Incident tracking (open, acknowledge, close) and CAP 1.2 XML output.
- An operator dashboard, a site page and a report queue page.
- Data in a local SQLite database; speech-to-text with faster-whisper on the server.

Still from the old codebase and due to change: report keywords, prompts and many screen labels are in Spanish, the sample sites are in Argentina, alert outputs are logging stubs, and the dashboard shows labelled sample data when there is no live alert.

Planned (see [PLAN.md](PLAN.md), milestones M1 to M10):

- DynamoDB store and the 15-minute scheduled sweep for five villages in Mandi and Hamirpur districts.
- Risk rules from IMD rain bands and each village's own river-discharge history, with hysteresis.
- Hindi alert drafting on Bedrock with a rule fallback, and a draft checker.
- Officer approval in Step Functions with signed one-tap links, timeouts and a failsafe.
- Polly voice alerts on Telegram with a one-tap acknowledgement and one automatic re-send.
- Hindi voice reports through Transcribe.
- Cognito sign-in with officer and pradhan roles, Cedar authorization and an audit log.
- A replay of the night of 30 June to 1 July 2025 in Mandi from archived data, labelled as replay everywhere.
- A public live dashboard, report tracking links, and an officer question-answering agent.

## Running the tests

Backend (Python 3.12, [uv](https://docs.astral.sh/uv/)):

```bash
cd backend
uv sync --frozen --extra dev
.venv/bin/python -m pytest -q
```

Frontend (Node 20):

```bash
cd frontend
npm ci --legacy-peer-deps
npm test
npm run build
```

Settings are read from `PUKAAR_*` environment variables; [.env.example](.env.example) lists them with their defaults. [backend/README.md](backend/README.md) shows how to run the API locally.

## More

- [PLAN.md](PLAN.md): the build plan and rules.
- [CODEMAP.md](CODEMAP.md): what each module does and how data flows.
- [PROGRESS.md](PROGRESS.md) and [DECISIONS.md](DECISIONS.md): what is done and why.
