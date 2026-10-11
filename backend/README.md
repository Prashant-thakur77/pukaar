# Pukaar backend

FastAPI API and Lambda handlers for Pukaar. Package: `src/Pukaar/`.

| Folder | What it holds |
|---|---|
| `core/` | settings (`PUKAAR_*` env vars), injectable clock, ids, JSON logs and CloudWatch EMF metrics, SSM secrets, local mode |
| `store/` | Pydantic records and the single-table DynamoDB repo |
| `services/` | risk rules, sweep engine, Open-Meteo and replay data, soil moisture and readiness, report intake and auto-verification, drafting and draft checker, Ask Pukaar analyst, nowcast, river gauges and learned thresholds, virtual staff gauges, safe places and road blocks, roll-call, after-action reports, CAP feed, live-push events, officer Web Push, agent registry, model-access probe, action guard, S3 storage |
| `llm/` | `BedrockLLM` (Strands agents on Bedrock, typed output, region failover), the read-only agent tools and the Bedrock Guardrails screen |
| `voice/` | Polly (Hindi alert audio) and Transcribe (Hindi voice reports) |
| `delivery/` | Telegram channel, the dispatcher (per-recipient deliveries, one re-send, acknowledgements) and Web Push (RFC 8291 encryption and VAPID, `webpush.py`) |
| `workflow/` | approval steps for Step Functions, signed one-tap links, AWS and local workflow clients |
| `policy/` | Cedar policies and the single `authorize()` guard, plus the Strands tool hook |
| `handlers/` | Lambda entry points: `sweep`, `workflow`, `worker`, `gauge_ingest` (the API runs `main:app` behind the Lambda Web Adapter) |
| `api/` | routes (public, reports, officer, roll-call, gauges, sensors, agents, Web Push, Telegram webhook) and response shapes |
| `templates/hi.py` | fixed Hindi safety text |
| `scripts/` | `seed`, `calibrate`, `fetch_replay`, `backtest`, `score`, `story`, `reset_demo`, `drill`, `smoke_bedrock`, `vapid_keys`, `iot_provision`, `gauge_sim`, `gauge_sim_mqtt` |

## Run locally (no AWS account needed)

```bash
uv sync --frozen --extra dev
PUKAAR_MODE=local .venv/bin/python -m uvicorn Pukaar.main:app --app-dir src --port 8000
```

Local mode starts an in-process AWS mock (moto) with the table and bucket,
seeds the five villages, and runs the approval workflow in background
threads. Bedrock, Polly and Transcribe are not mocked: health reports them as
unavailable and the rule fallbacks run, exactly as they would in an outage.
Sign in with `POST /auth/dev-login {"username": "officer1"}` (also `officer2`,
`pradhan_thunag`).

## Tests

```bash
.venv/bin/python -m pytest -q
```

All tests run offline (moto, frozen clock, fake workflow and model).
