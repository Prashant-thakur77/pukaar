# Backend

FastAPI service for Pukaar. Python package: `src/Pukaar/`.

What it does today:

- Takes villager reports (`POST /api/reports`: text, photo, audio), transcribes
  audio with faster-whisper, and structures the text with keyword rules and an
  optional local model.
- Fetches rain and river data from Open-Meteo on request
  (`POST /api/sites/{id}/external-snapshot/refresh`).
- Scores recent reports and hydromet data into a level (green, yellow,
  orange, red), writes an alert with a decision trace and a short reasoning
  summary, and records stub alert outputs.
- Stores everything in a local SQLite database through SQLModel.

PLAN.md describes the move to AWS (DynamoDB, Bedrock, Transcribe, Polly, Step
Functions); none of that is built yet.

## Run the tests

```bash
uv sync --frozen --extra dev
.venv/bin/python -m pytest -q
```

## Run locally

```bash
PYTHONPATH=src .venv/bin/python -m Pukaar.scripts.seed
PYTHONPATH=src .venv/bin/python -m uvicorn Pukaar.main:app --port 8000
```

Settings come from `PUKAAR_*` environment variables; see `../.env.example`.
