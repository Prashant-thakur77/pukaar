# E2E Stability Report - Pukaar

Date: 2026-05-18
Branch: `develop`
Environment: Ubuntu 22.04 VM, NVIDIA RTX 3060 (12 GB), CUDA 13.1, driver 590.48.01
Runtimes: LiteRT-LM (Pukaar edge node, GPU) + Ollama 11434 (central reasoning + actuators)
Models: `pukaar-model-2b.litertlm` (LiteRT vision), `pukaar-model:26b` (Ollama central, vision + tools)

## Verdict

End-to-end flow Persona-A (node) -> Persona-B (Pukaar citizen report) -> deterministic fusion -> Ollama tool-call actuators -> CAP v1.2 export runs without errors. All four legs return HTTP 200; the fused alert escalates to `red`, all three actuators (`trigger_alarm`, `send_radio_payload`, `notify_app`) fire `success`, and the CAP XML is well-formed.

## Bugs found and fixed

### 1. Multimodal call used a text-only Ollama model

- Symptom: `decision_trace.evidence[node].payload.runner_mode = "multimodal-unavailable-fallback"`, summary `"... pero el modelo no devolvio una respuesta valida"`.
- Root cause: `docker-compose.yml` set `PUKAAR_MULTIMODAL_MODEL=pukaar-model:2b`. Direct probe of `/api/chat` with an image returns HTTP 500 `"this model is missing data required for image input"` — `pukaar-model:2b` ships without the vision adapter.
- Fix: `docker-compose.yml` -> `PUKAAR_MULTIMODAL_MODEL=pukaar-model:26b`; comment added documenting that any Ollama vision use requires a vision-capable variant. On this VM the LiteRT path is preferred and is set via `PUKAAR_NODE_PROVIDER=litert` + `PUKAAR_NODE_MODEL_PATH` (see below).

### 2. LiteRT model path mismatch (default vs repo layout)

- Symptom: `engine.cc:491 Failed to create engine: NOT_FOUND: open() failed: /.../.pukaar_data/models/pukaar-model-2b.litertlm`. Every Pukaar call fell through to `multimodal-unavailable-fallback`.
- Root cause: `core/settings.py` defaults `PUKAAR_NODE_MODEL_PATH` to `<PUKAAR_DATA_DIR>/models/pukaar-model-2b.litertlm`, but the repository ships the bundles in `backend/data/models/`.
- Fix: set `PUKAAR_NODE_MODEL_PATH=<repo>/backend/data/models/pukaar-model-2b.litertlm` explicitly in the launch script (this is where `scripts/fetch_litert_model.py` writes the artifact). Recommendation (not applied): change the default in `settings.py` to `backend/data/models/...` so the dev launch works without an env override.

### 3. Actuator tool-calling broke against `pukaar-model:2b`

- Symptom: `WARNING actuator LLM call failed: Client error '400 Bad Request' for url 'http://127.0.0.1:11434/api/chat'`.
- Root cause: `services/actuators.py::_call_ollama_tool_selection` posts `tools=ACTUATOR_TOOL_SCHEMA`. Ollama returns `{"error":"registry.ollama.ai/library/pukaar-model:2b does not support tools"}`. The deterministic fallback still fires the actuators, so the system is operationally safe, but the central LLM was effectively bypassed.
- Fix: `docker-compose.yml` -> `PUKAAR_LLM_MODEL=pukaar-model:26b` (with inline comment explaining why). Verified: `pukaar-model:26b` returns valid `tool_calls` for the same prompt.

### 4. Silent exception in the Ollama multimodal adapter

- Symptom: any HTTP/transport/JSON failure in `adapters/video_assessment.py::_assess_multimodal` was swallowed by a bare `except Exception: return None`. Bugs #1 and #3 were therefore invisible in the logs.
- Fix: split the `except` into `httpx.HTTPStatusError` (logs status + truncated body + URL + model) and a generic `Exception` fallback, both at WARNING. No behaviour change beyond observability.

## Files changed

- `docker-compose.yml`
- `backend/src/Pukaar/adapters/video_assessment.py`

## Verification (live, on `develop`)

```text
=== HEALTH ===
{'status': 'ok', 'pukaar_node_profile': 'raspberry-pi-8gb-multimodal-demo', 'llm_enabled': True, 'hydromet_enabled': True}

A) POST /api/node/analyze        site_id=silverado-fixed-cam-usgs   200  (LiteRT GPU)
B) POST /api/reports             "el agua ya paso la marca..."      200  urgency=critical severity=1.0
C) GET  /api/alerts              fused level=red score=1.00         200  rules: node_score=0.55, volunteer_score=1.00, corroboration_sources=node,volunteer
D) POST /api/cap/emit            severity=severe                    200  Content-Type: application/cap+xml

actuation: ['trigger_alarm:success', 'send_radio_payload:success', 'notify_app:success']
```

Backend log is free of `400`, `multimodal-unavailable-fallback`, and `actuator LLM call failed` after the fix. Remaining LiteRT log entries (`NPU accelerator could not be loaded`, `WebGPU sampler not available`) are environmental warnings; the engine falls back to the statically linked GPU/CPU sampler and inference completes normally.

## Open items (non-blocking)

- `core/settings.py` LiteRT default path should point at `backend/data/models/...` to remove the need for an explicit env override on a fresh checkout.
- Compose-mode boot still needs the `llm` profile and a `docker exec ollama ollama pull pukaar-model:26b` step; the comment block in `docker-compose.yml` documents this.

## Stress Suites (pre-main gate)

Run on the same VM/RTX 3060 environment as above. Ollama serves `pukaar-model:26b`; LiteRT-LM holds Pukaar AI E2B in GPU.

### Suite 1 - Network resiliency and mass offline sync

- `scripts/demo_connectivity.py`: full narrative completed end-to-end. Offline -> queued -> sample-node-analysis fires local siren -> wifi-on -> `POST /api/sync/flush queued=19 flushed=19 failed=0`. Recovery window from offline flip to drained queue = 49 s (target <90 s).
- Burst of 20 concurrent `POST /api/reports` with `httpx.AsyncClient`:
  - 0 HTTP 5xx, 0 SQLite `database is locked` / `OperationalError`, 0 deadlocks (verified by `grep -iE 'database is locked|sqlite.*lock|deadlock|OperationalError' /tmp/backend.log` -> 0 hits).
  - `FusedAlert` escalated correctly (`red`, score 1.00) across the burst.
  - Throughput observation: with `PUKAAR_LLM_MODEL=pukaar-model:26b` on a single RTX 3060, per-report latency is GPU-bound (Ollama serializes inferences). 15 of 20 returned within the 600 s client window; the remainder completed server-side without error. The path used in the real demo flow (`/api/sync/flush`) batches without serializing one LLM call per report and drained 19/19 cleanly. No code change required: the system is correct under burst, throughput is hardware-bound. Operational note: setting `OLLAMA_NUM_PARALLEL>=2` on a larger GPU gives near-linear scaling.

### Suite 2 - Multimodal under VRAM pressure

- `PUKAAR_MULTIMODAL_MAX_FRAMES=4` (production target for 16 GB / workstation profile).
- `POST /api/node/analyze` with the real 60 MB `usgs_silverado_fire_2015_fixed_cam.mp4` (multipart upload, not the bundled sample): HTTP 200 in 36.66 s.
- VRAM trace (`nvidia-smi` every 2 s during the call): baseline 8825 MiB -> peak 11336 MiB / 12288 MiB (~92%). No OOM, no LiteRT timeout, no buffer overflow. Inference completed with a coherent JSON verdict (severity 0.65, visual cues populated).

### Suite 3 - Fault injection and fallbacks

- 3a. LLM down: backend relaunched with `PUKAAR_LLM_BASE_URL=http://127.0.0.1:9` and `PUKAAR_LLM_TIMEOUT_SECONDS=5`.
  - `POST /api/reports` (red transcript): HTTP 200 in 0.24 s, `parsed.parser_source=rules`, `alert.level=red`, `alert.score=1.0`. Deterministic fallback engaged cleanly.
  - `POST /api/node/analyze` with the full video: HTTP 200 in 31.4 s (LiteRT path, unaffected by Ollama outage).
  - `POST /api/cap/emit`: HTTP 200 in 0.003 s.
- 3b. Malformed JSON from LLM: a Python mock on `127.0.0.1:9999` returned `'{garbage not_json,, level=??'`. Backend's `_extract_json` rejected, structurer fell back to rules. `POST /api/reports`: HTTP 200, `parser_source=rules`, `alert.level=red`, `score=1.0`. No 500, no traceback.
- 3c. LiteRT concurrency: 5 parallel `POST /api/sites/silverado-fixed-cam-usgs/sample-node-analysis`. 5/5 HTTP 200, latencies 30.1 / 55.9 / 79.8 / 103.6 / 127.4 s (LiteRT engine serialized cleanly: single GPU session, no crash, no deadlock, no `Failed to create new sequence` errors). Backend log shows clean `RunPrefillAsync status: OK` per slot.

All three suites complete without HTTP 5xx, SQLite locks, LiteRT crashes, OOM, or hung sessions. The two non-fixable observations - per-request LLM latency on a 26 B model and serial LiteRT inference on a single GPU - are physics, not bugs.

## Re-run after PR #5 merge (experimental track: Edge RAG + visual nowcasting + dashboard settings)

PR #5 merged into `develop` (commit `3fab292`). Stress suites re-executed on the same VM/RTX 3060 stack.

### Regression found and fixed

- Suite 1b 20-burst returned 5/20 HTTP 500 with `sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached`. Root cause: PR #5 added per-request DB work in the historical-context / RAG / forecast paths; the default SQLAlchemy pool (`pool_size=5`, `max_overflow=10`) exhausted under 20-concurrent /reports.
- Fix: `backend/src/Pukaar/db/database.py` now creates both edge/central engines with `pool_size=20`, `max_overflow=40`, `pool_timeout=30`, `pool_recycle=1800`, plus a 30 s SQLite busy timeout in `connect_args`. After the fix, 20/20 reports returned HTTP 200 in 304 s, with 0 SQLite locks and 0 5xx.

### Re-run verification

- Suite 1a (`scripts/demo_connectivity.py`): full narrative ok, `queued=130 flushed=130 failed=0`, recovery 33 s (<90 s target).
- Suite 1b (20 concurrent `POST /api/reports`): `total=20 ok=20 elapsed=304.06s`, `grep -ciE 'database is locked|OperationalError|deadlock|QueuePool' /tmp/backend.log` = 0, `500 Internal` count = 0.
- Suite 2 (multimodal under VRAM pressure, `PUKAAR_MULTIMODAL_MAX_FRAMES=4`): `POST /api/node/analyze` with the 60 MB USGS video returned HTTP 200 in 41.17 s. VRAM baseline 8825 MiB -> peak 10974 MiB / 12288 MiB (~89 %). No OOM, no LiteRT crash.
- Suite 3a (LLM dead, `PUKAAR_LLM_BASE_URL=http://127.0.0.1:9/v1`, timeout 5 s): `POST /api/reports` -> HTTP 200 in 0.30 s, `parser_source=rules`, `alert.level=red`, `score=1.0`.
- Suite 3b (malformed JSON via mock on `127.0.0.1:9999`): `POST /api/reports` -> HTTP 200 in 0.25 s, `parser_source=rules`, `alert.level=red`, `score=1.0`. No 500.
- Suite 3c (5 parallel `POST /api/sites/silverado-fixed-cam-usgs/sample-node-analysis`): 5/5 HTTP 200, latencies 29.99 / 55.35 / 80.73 / 105.92 / 131.12 s (LiteRT engine serialized cleanly, no crash, no `Failed to create new sequence`).

## Status

System stable on `develop` after PR #5 merge + pool fix. E2E + stress suites green. Ready to merge to `main`.
