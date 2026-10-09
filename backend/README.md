# Pukaar backend

FastAPI API and Lambda handlers for Pukaar. Package: `src/Pukaar/`.

| Folder | What it holds |
|---|---|
| `core/` | settings (`PUKAAR_*` env vars), injectable clock, ids, JSON logs and CloudWatch EMF metrics, SSM secrets, local mode |
| `store/` | Pydantic records and the single-table DynamoDB repo |
| `services/` | risk rules, sweep engine, Open-Meteo and replay data, report intake and auto-verification, drafting and draft checker, Ask Pukaar analyst, nowcast, action guard, S3 storage |
| `llm/` | `BedrockLLM` (Strands agents on Bedrock, typed output, region failover) and the read-only agent tools |
| `voice/` | Polly (Hindi alert audio) and Transcribe (Hindi voice reports) |
| `delivery/` | Telegram channel and the dispatcher (per-recipient deliveries, one re-send, acknowledgements) |
| `workflow/` | approval steps for Step Functions, signed one-tap links, AWS and local workflow clients |
| `policy/` | Cedar policies and the single `authorize()` guard, plus the Strands tool hook |
| `handlers/` | Lambda entry points: `sweep`, `workflow`, `worker` (the API runs `main:app` behind the Lambda Web Adapter) |
| `api/` | routes (public, reports, officer, Telegram webhook) and response shapes |
| `templates/hi.py` | fixed Hindi safety text |
| `scripts/` | `seed`, `calibrate`, `fetch_replay`, `backtest`, `reset_demo`, `smoke_bedrock` |

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
