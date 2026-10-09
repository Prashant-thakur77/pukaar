# CODEMAP.md: Pukaar repository

> **Current layout: see section 10 at the end.** Sections 0-9 describe the
> code as first found and after the preparation-run cleanup; they are kept as
> history.

This map describes the code as it was when the repository was first committed
("Starting codebase", fd64bc3). Later commits remove parts of it. PROGRESS.md
and DECISIONS.md record what changed. Paths are relative to the repo root.
The Python package is `backend/src/Pukaar/` (`<pkg>` in PLAN.md).

## 0. State of the code (read this first)

- **The backend does not import.** An earlier global rename (Gemma -> "Pukaar AI",
  acuifero/vigia -> pukaar) left invalid Python:
  - `api/deps.py`, `adapters/image_assessment.py`, `adapters/video_assessment.py`,
    `adapters/text_structuring_pukaar-ai_fewshot.py`, `services/pukaar_assessment.py`
    contain identifiers with a space (`Pukaar AIImageAssessmentAdapter`,
    `Pukaar AIFewShotTextStructurer`, `OllamaPukaar AIRunner`, ...).
  - The module `adapters/text_structuring_pukaar-ai_fewshot.py` has a hyphen
    in its name, so it cannot be imported with a normal `import` statement.
  - Because `api/deps.py` fails, every router, `main.py` and 13 of 21 test
    files fail at collection.
- **The frontend does not build.** `components/CommandCenter.tsx` and
  `pages/Dashboard.tsx` declare/import `Pukaar AIReasoning` (with a space).
  `npm test` (vitest) still passes because it only loads `store.ts`.
- **The camera-node router is gone.** PLAN.md names `api/routers/acuifero.py`
  (camera analysis) and `api/routers/vigia.py` (reports). On disk there is one
  file, `api/routers/pukaar.py`, holding only the report routes. `main.py`
  imports `pukaar` twice and registers it twice. The routes
  `POST /api/node/analyze` and `POST /api/sites/{id}/sample-node-analysis`,
  which the frontend and `tests/test_api.py` call, no longer exist.
- Other renamed paths versus PLAN.md: `services/acuifero_assessment.py` ->
  `services/pukaar_assessment.py`; `adapters/text_structuring_gemma_fewshot.py`
  -> `adapters/text_structuring_pukaar-ai_fewshot.py`;
  `scripts/run_gemma_local.sh` -> `scripts/run_pukaar-ai_local.sh`;
  `run_acuifero_pi*` -> `run_pukaar_pi*`; `fixtures/kaggle_live_demo/` ->
  `fixtures/pukaar_live_demo/`; `test_vigia_*`/`test_acuifero_*` ->
  `test_pukaar_*`.
- The model names were renamed too, so they no longer name a real model:
  `pukaar-model:2b`, `pukaar-model:26b`, `pukaar-ai4:e26b` and
  `pukaar-model-2b.litertlm` were Gemma model ids.
- Language: prompts, keyword lists, few-shot examples and many UI strings are
  Rioplatense Spanish. Geography is Argentina (bounding box, SINAGIR, sample
  sites near Rosario) plus one USGS California demo site.

## 1. Backend modules (`backend/src/Pukaar/`)

### Entry and wiring
| File | What it does |
|---|---|
| `main.py` | FastAPI app. Lifespan: `init_db()`, creates upload and fixture dirs. CORS `*`. Mounts `/uploads` (upload dir) and `/fixtures` (repo `fixtures/`) as static files. Registers routers under `/api`; CAP router also at root; `demo_inject` only when `PUKAAR_ENABLE_DEMO_INJECT=1`. Leftover `is_online = True` alias. |
| `core/settings.py` | Frozen `Settings` dataclass read from `PUKAAR_*` env vars, cached with `lru_cache`. Holds data/upload dirs, two SQLite paths (edge, central), ffmpeg path, local LLM (Ollama/OpenAI-compatible) URL/model/key/timeout, LiteRT node provider/model/backends/tokens, multimodal settings with Raspberry Pi 8 GB / 16 GB profiles, hydromet toggle/timeout, faster-whisper ASR settings, image-assessment toggles, actuator toggle. One env name is mis-cased: `Pukaar_IMAGE_ENABLED`. |
| `db/database.py` | Two SQLModel/SQLite engines: `edge.db` (`edge_engine`, request sessions via `get_session`, `session_scope`) and `central.db` (`central_engine`, `get_central_session`). `init_db()` creates tables in both and adds missing columns (`_sync_missing_columns`). Creates data dirs at import time. |
| `api/deps.py` | Builds every model object at import time: `OpenAICompatibleLLM`, `LiteRTNodeRuntime`, few-shot structurer, LiteRT or Ollama video runner, two image assessors, `FasterWhisperASRAdapter`, `ExternalDataService`, `PukaarAssessmentEngine`. Global `is_online` flag. `get_decision_runtime()` returns the LLM client. `enqueue_entity()` writes/updates a `SyncQueueItem` for edge->central sync. **Syntax error (section 0).** |
| `api/serializers.py` | `site_payload` (adds public URLs for sample video/frame), JSON helpers, `serialize_observation` + `publicize_artifact_refs` (camera node, no remaining caller), `serialize_external_snapshot`. |
| `schemas/api.py` | Pydantic request/response models: connectivity, calibration, runtime status, recompute, historical context, site experimental settings, external snapshot. |
| `schemas/tools.py` | Strict Pydantic arg models for model tool calls `trigger_siren`, `emit_cap` (GeoJSON in WGS84 bounds), `send_lora`; `TOOL_MODELS`, `TOOL_SCHEMAS` (unused). |
| `scripts/seed.py` | Seeds three sites into edge.db (two near Rosario, Argentina; USGS Silverado CA with a sample video path under `fixtures/media/`) plus pixel calibrations. |

### Domain and decision logic
| File | What it does |
|---|---|
| `models/domain.py` | SQLModel tables (section 3). |
| `services/decision_engine.py` | Core fusion. `_collect_evidence` reads node observations, volunteer reports (+ parsed observation) and hydromet snapshots inside a 45-minute window; `temporal_weight` decays to a 0.45 floor; `_score_events` takes the strongest weighted event, adds a corroboration bonus, escalates two medium sources to orange, flags contradictions, floors critical node/volunteer rules; `level_from_score` maps to green/yellow/orange/red (0.4/0.62/0.82). `recompute_site_alert` builds the trace (`decision-trace-v2`), calls reasoning (skipped at green), upserts the `Incident`, adds a short-term forecast from node readings, writes a `FusedAlert`, then `_record_actuators` dispatches actuators for orange/red, idempotent per incident. Camera-node rules: `_node_rules`, node branch in `_collect_evidence`, `node_critical_line_crossed` floor. |
| `services/reasoning.py` | `generate_alert_reasoning`: green -> fixed text, model `rule-skip-green`; otherwise calls `llm.generate_text` with an English system prompt ("You are Pukaar AI running on the Pukaar node"), parses `Summary: ... Chain: a -> b` (`_parse_llm_output`, also Spanish `Resumen/Cadena`), falls back to `_fallback` with `reasoning_model = "rule-fallback"`. Validates `[ctx:N]` citations against historical hits. |
| `services/report_structuring.py` | `structure_report`: always runs a Spanish keyword parser (`_fallback_parse`), optionally an LLM (`structure_observation`) normalised by `_normalize_*`; merges keeping the more severe value; `parser_source` is `rules` or `llm`. |
| `services/predictive.py` | `forecast_short_term`: linear trend + clamped acceleration over water-level measurements, horizon points, uncertainty band, minutes to threshold, risk. Fed by camera `waterline_ratio` today. |
| `services/external_data.py` | `ExternalDataService`: Open-Meteo forecast (current precip, 12 h hourly precip and probability) and flood API (daily discharge, past 2 + next 7 days) -> `HydrometSnapshot` with a heuristic `signal_score`; `health()` pings the forecast API. |
| `services/historical_context.py` | Separate SQLite file `historical_context.sqlite` with an FTS5 index; seeds three hard-coded rows (Silverado "2015 flood analogue", evacuation trigger, test-site manual); `retrieve_historical_context`, `upsert_historical_context`, `render_historical_context`, `validate_context_citations`. |
| `services/actuators.py` | Actuator protocols, three stub actuators that print Spanish lines and append to `RECORDED_CALLS` (`trigger_alarm`, `send_radio_payload`, `notify_app`), a Spanish tool schema, and `dispatch_actuators` that asks LiteRT (strict JSON) or Ollama (`/api/chat` tools) which actuators to fire, filtered by an allowlist. |
| `services/action_guard.py` | `validate_tool_call`: schema validation via `schemas/tools.py`, severity must not exceed evidence, CAP area inside an **Argentina** bounding box, in-memory rate limit 6/h per zone; `guarded_model_action` retry loop. Not called by any route; only tests use it. |
| `services/cap.py` | `build_cap_xml`: CAP 1.2 XML with SINAGIR-flavoured fields, Buenos Aires default coordinates, SHA-256 signature parameter. `write_cap_sample` has no caller. |
| `services/storage.py` | Local filesystem: upload dir, fixture dir, public URL mapping for `/uploads` and `/fixtures`, `persist_upload`, `persist_json_artifact`; `persist_frame_image` has no caller. |
| `services/pukaar_assessment.py` | **Camera node.** ffmpeg frame extraction, Pillow resizing, deterministic firewall, evidence pack, `PukaarAssessmentEngine` with a fallback verdict, JSON manifest artifact. Syntax error. |
| `services/deterministic_firewall.py` | **Camera node.** Pure-PIL waterline/edge/motion metrics per frame. |
| `services/node_analysis.py` | **Camera node.** Re-export shim of `pukaar_assessment`. |
| `services/calibration.py` | **Camera node.** ROI/critical-line pixel calibration loading. Used by `routers/sites.py`. |
| `fusion/engine.py` | Older standalone node+citizen fusion (`fuse`, `Signal`, `Decision`, Spanish summaries). Only `tests/test_fusion_engine.py` imports it. |

### Adapters (local models)
| File | What it does |
|---|---|
| `adapters/llm.py` | `OpenAICompatibleLLM`: `health()` (GET `/models`), `structure_observation()` (Ollama native `/api/chat` with `format: json`, else `/chat/completions`), `generate_text()`; `_extract_json`. Ollama detection by host `127.0.0.1:11434`. |
| `adapters/text_structuring_pukaar-ai_fewshot.py` | 12 Spanish few-shot examples + Spanish system prompt; class wraps any `generate_text` client and returns the same JSON dict as `structure_observation`. `PUKAAR_FEWSHOT_COUNT` env. Unimportable name. |
| `adapters/asr.py` | `AudioTranscriptionAdapter` protocol; `FasterWhisperASRAdapter` (`tiny`, `language="es"`, 30 s cap, lazy load). |
| `adapters/image_assessment.py` | `ImageAssessmentAdapter` protocol, `ImageAssessmentResult` (`description_es`, flags, confidence), Spanish few-shot prompt, `_encode_image` (resize + JPEG base64), `_parse_json_block`, Ollama `/api/chat` with image, or embedded LiteRT runtime. Syntax error. |
| `adapters/litert_node.py` | **On-device model.** `LiteRTNodeRuntime` around `litert_lm` engines (text and multimodal), JSON repair. |
| `adapters/video_assessment.py` | **Camera node.** Ollama and LiteRT video runners that produce `AssessmentVerdict`. Syntax error. |

### Routers (all under `/api` unless noted)
| File | Routes |
|---|---|
| `routers/runtime.py` | `GET /health`; `GET /settings/runtime` (LLM, LiteRT node, hydromet status); `GET`/`POST /settings/connectivity` (toggle the in-process `is_online` flag). |
| `routers/sites.py` | `GET /sites`, `POST /sites`, `GET /sites/{id}`, `GET`/`POST /sites/{id}/calibration`, `GET`/`PUT /sites/{id}/experimental-settings`, `GET`/`POST /sites/{id}/historical-context`, `GET /sites/{id}/forecast` (from node observations), `GET /sites/{id}/external-snapshot`, `POST /sites/{id}/external-snapshot/refresh` (fetch Open-Meteo, store, recompute alert with the LiteRT runtime). |
| `routers/pukaar.py` (was `vigia.py`) | `POST /reports` (multipart: site_id, reporter_name/role, transcript_text, offline_created, photo, audio -> ASR if no text -> structure -> recompute -> background image description), `GET /reports`. |
| `routers/alerts.py` | `GET /alerts?historical_context=`, `GET /alerts/{id}` (parsed chain/trace, incident, actuations), `POST /alerts/{id}/export-sinagir` (national-schema export), `GET /sites/{id}/operator-summary`, `GET /incidents/{id}/timeline`, `POST /incidents/{id}/ack`, `POST /incidents/{id}/close`, `POST /alerts/recompute`. |
| `routers/sync.py` | **Edge sync.** `POST /sync/flush` (copy pending `SyncQueueItem` entities edge.db -> central.db), `GET /sync/status`. |
| `routers/cap.py` | `POST /cap/emit` (also at `/cap/emit` without prefix) -> CAP XML. Spanish/Buenos Aires defaults. |
| `routers/demo_inject.py` | Env-gated `POST /demo/inject-node-observation`, `POST /demo/inject-volunteer-report`: synthetic rows + recompute. PLAN: becomes `replay`. |
| static | `/uploads/*`, `/fixtures/*` |

## 2. End-to-end data flow (as designed; currently broken at import)

**Report in:** browser `Report.tsx` -> IndexedDB queue (`lib/idb.ts`) -> `store.flushQueue` -> `POST /api/reports` (multipart) -> `persist_upload` to local disk -> if no text and audio present: faster-whisper (`es`) -> `structure_report` (Spanish keywords + optional local LLM few-shot) -> `VolunteerReport` + `ParsedObservation` -> `recompute_site_alert` -> `FusedAlert` (+ `Incident`, + `ActuationRecord`s for orange/red via stub actuators) -> each row queued as `SyncQueueItem` -> background task appends a local-model photo description to the parsed trace. Then the frontend calls `POST /api/sync/flush` (edge.db -> central.db).

**Data refresh:** `SiteDetail.tsx` "Refresh" -> `POST /api/sites/{id}/external-snapshot/refresh` -> Open-Meteo forecast + flood -> `HydrometSnapshot` -> `recompute_site_alert`. **There is no scheduler**; refresh is manual only.

**Camera node (broken):** `SiteDetail.tsx` upload -> `POST /api/node/analyze` (route missing) -> ffmpeg frames -> firewall -> LiteRT/Ollama verdict -> `NodeObservation` + `PukaarAssessmentArtifact` -> recompute.

**Alert out:** there is no approval and no delivery. "Outputs" are `print()` stubs recorded in `ActuationRecord`. CAP XML is generated on request only.

## 3. Database tables

Two SQLite files with the same SQLModel schema (`edge.db`, `central.db`), plus
`historical_context.sqlite` (raw sqlite3 + FTS5).

| Table | Written by | Read by |
|---|---|---|
| `site` | `seed.py`, `POST /sites` | most routers, decision engine (via site_id) |
| `sitecalibration` | `seed.py`, `POST /sites/{id}/calibration` | `GET .../calibration`, camera node |
| `siteexperimentalsettings` | `GET`/`PUT .../experimental-settings` (create on read) | sites router (forecast horizon, historical toggle) |
| `nodeobservation` | camera node (route missing), `demo_inject` | decision engine, forecast route, operator summary, sync |
| `volunteerreport` | `POST /reports`, `demo_inject` | decision engine, `GET /reports`, operator summary, sync |
| `parsedobservation` | `POST /reports`, `demo_inject`, image enrichment task | decision engine, operator summary, sync |
| `hydrometsnapshot` | `external-snapshot/refresh` | decision engine, `GET external-snapshot`, operator summary, sync |
| `fusedalert` | `recompute_site_alert` | alerts router, sync |
| `incident` | `_upsert_incident`, ack/close routes | alerts router, decision engine, sync |
| `actuationrecord` | `_record_actuators` | alerts router, decision engine (idempotency), sync |
| `pukaarassessmentartifact` | camera node | sync, tests |
| `syncqueueitem` | `enqueue_entity` | `sync.py`, operator summary |
| `historical_context` (+ `_fts`) | `ensure_context_db` seed rows, `POST .../historical-context` | decision engine (opt-in), alerts router, sites router |

## 4. Frontend (`frontend/`, React 19 + Vite + zustand + react-router)

| File | Role and API calls |
|---|---|
| `src/main.tsx`, `src/App.tsx` | Mount; routes `/` Dashboard, `/report`, `/queue`, `/sites/:id`, `/sites/:id/calibrate`, `/settings`, all inside `Layout`. |
| `src/store.ts` | zustand store. `API_BASE` = `VITE_API_BASE` or `http://localhost:8000/api`. Calls: `GET /sites`, `GET /alerts[?historical_context=true]`, `GET`/`PUT /sites/{id}/experimental-settings`, `GET /sites/{id}/historical-context`, `GET /sites/{id}/forecast`, `GET /settings/connectivity`, `POST /reports` (queue flush), `POST /sync/flush`, `GET /sync/status`, `POST /cap/emit`. |
| `src/lib/idb.ts` | IndexedDB offline report queue (`Pukaar-db`). `clearOfflineReports` unused. |
| `src/hooks/useMediaRecorder.ts` | Mic recording to webm/opus. |
| `src/components/Layout.tsx` | Header, online/offline toggle (`POST /settings/connectivity`), connectivity poll every 10 s, bottom nav. |
| `src/components/CommandCenter.tsx` | Presentational panels for the dashboard. `NodeProfileCard` (defaults `pukaar-model:2b`, `LiteRT-LM`), `NodeMetricsCard`, `HandoffNote` are exported but not used anywhere. Syntax error at `Pukaar AIReasoning`. |
| `src/pages/Dashboard.tsx` | "Command center". Uses store data, **falls back to hard-coded demo data** (`DEMO_SITE`, `DEMO_ALERT`, `DEMO_FUSION`, `DEMO_AUDIT`, timeline, CAP receipt), hard-coded evidence images `/demo_persona_c/*.png` and descriptions per level, `CENTRAL_NODE_MODEL = 'pukaar-ai4:e26b'`, per-source model labels, a demo forecast, two hard-coded historical-context rows, and action buttons that only log locally. Calls via store: sites, alerts, experimental settings, forecast, historical context. |
| `src/pages/SiteDetail.tsx` | Site page: `GET /sites/{id}`, `GET /sites/{id}/calibration`, `GET /sites/{id}/external-snapshot`, `POST .../external-snapshot/refresh`, `POST /node/analyze` (**missing route**), `POST /sites/{id}/sample-node-analysis` (**missing route**), `POST /alerts/{id}/export-sinagir`, `POST /cap/emit`; siren/LoRa/notify buttons are simulated. |
| `src/pages/Calibration.tsx` | Camera ROI/line drawing: `GET /sites/{id}`, `GET`/`POST /sites/{id}/calibration`. |
| `src/pages/Report.tsx` | Report form (site select, name, role, text, mic, photo, audio) -> IndexedDB -> flush. |
| `src/pages/Queue.tsx` | Lists/deletes queued reports, "Sync now". |
| `src/pages/Settings.tsx` | `GET /settings/runtime`, sync status, LiteRT/Ollama panel and a hard-coded env-var block. |
| `src/index.css` | Hand-written utility classes (Tailwind-like names) and `cc-*` command-center styles. Tailwind is **not** wired into Vite. |
| `src/App.css`, `src/assets/{hero.png,react.svg,vite.svg}` | Not imported anywhere (Vite template leftovers). |
| `public/` | `favicon.svg`, `manifest.webmanifest` (used by `index.html`); `sw.js` and `icons.svg` not referenced (vite-plugin-pwa generates its own service worker); `demo_persona_c/*.png` (10 MB screenshots used by Dashboard). |
| `_persona_c_preview.html` | Stand-alone design preview, not referenced. |
| `vite.config.ts` | React + `vite-plugin-pwa` (Spanish description). |
| `bun.lock` | Lock file for Bun; every script uses npm and `package-lock.json`. |
| `README.md` | Unmodified Vite template README. |

## 5. Tests

Backend (`backend/tests/`, pytest, `conftest.py` adds `src` to `sys.path`).
Most use the real SQLite engines from `settings` and wipe tables per test.

| File | Covers | Baseline |
|---|---|---|
| `test_decision_engine.py` | thresholds, temporal weight, two-medium escalation, stale evidence, incident reuse + actuator idempotency, LiteRT actuator fallback paths, edge->central sync | collection error |
| `test_report_structuring.py` | LLM payload normalisation, LLM+rules merge, conservative backfill | 3 pass |
| `test_reasoning.py` | green skip, fallback paths, LLM output parsing, model name, chain roundtrip, alert persists reasoning via `POST /reports` | collection error |
| `test_predictive.py` | trend, acceleration, insufficient data, gaps | 4 pass |
| `test_actuators.py` | dispatch disabled, Ollama/LiteRT tool selection, unknown/duplicate tools, malformed JSON, transport errors | collection error |
| `test_tools_guard.py` | guard rejects ungrounded siren, retry then human review | 2 pass |
| `test_cap_emit.py` | CAP XML required fields, `/cap/emit` endpoint | collection error |
| `test_api.py` | health, connectivity toggle, report + sync, uploads persisted, camera node analysis (calls the missing `analyze_node`), sample node route, hydromet refresh, experimental settings + forecast | collection error |
| `test_asr.py` | faster-whisper adapter missing file, report uses ASR when text empty | collection error |
| `test_historical_context.py` | sqlite retrieval and FTS ingest | 2 pass |
| `test_image_assessment.py` | JSON block parsing, Ollama image adapter, embedded runtime path | collection error |
| `test_pukaar_image.py` | background photo enrichment of reports | collection error |
| `test_rioplatense.py` | Spanish dialect corpus (`datasets/rioplatense_hydro/corpus.jsonl`) and few-shot wiring | collection error |
| `test_sinagir_export.py` | SINAGIR export shape | collection error |
| `test_fusion_engine.py` | `fusion/engine.py` | 4 pass |
| `test_deterministic_firewall.py` | camera firewall | 3 pass, 1 fail (`test_elevated_without_crossing`: returns `critical`) |
| `test_litert_node.py` | LiteRT runtime | collection error |
| `test_litert_benchmark.py` | `scripts/litert_benchmark.py` | 4 pass |
| `test_pukaar_assessment.py` | camera evidence builder, ffmpeg extraction, Ollama runner | collection error |
| `test_pukaar_provider.py` | LiteRT/Ollama provider selection in deps, runtime status, Pi scripts | collection error |

Frontend: `src/store.test.ts` (vitest + jsdom): queue flush with attachments,
offline no-op, webm audio, experimental settings, historical context +
forecast. 5 pass.

## 6. Where local models, speech models and SQLite are touched

- Ollama / OpenAI-compatible HTTP: `adapters/llm.py`, `adapters/image_assessment.py`, `adapters/video_assessment.py`, `services/actuators.py`, `api/deps.py`, `api/routers/runtime.py`, `docker-compose.yml`, `scripts/install_ollama_local.sh`, `scripts/run_pukaar-ai_local.sh`, `scripts/dev.sh`, `scripts/demo_persona_c/*`.
- LiteRT-LM: `adapters/litert_node.py`, `adapters/video_assessment.py`, `adapters/image_assessment.py` (embedded), `services/actuators.py`, `api/deps.py`, `api/routers/runtime.py`, `core/settings.py`, `scripts/fetch_litert_model.py`, `litert_benchmark.py`, `litert_smoke.py`, `run_pukaar_pi*.sh`, `pyproject.toml` (`litert-lm-api`).
- faster-whisper: `adapters/asr.py`, `core/settings.py`, `pyproject.toml`.
- SQLite: `db/database.py` (SQLModel), `services/historical_context.py` (sqlite3 + FTS5), every router and the decision engine through sessions.
- Frontend labels: `Dashboard.tsx` (`CENTRAL_NODE_MODEL`, per-source models), `CommandCenter.tsx` (`NodeProfileCard` defaults), `Settings.tsx` (LiteRT/Ollama panel), `SiteDetail.tsx` ("Pukaar AI reasoning").

## 7. Hard-coded, mocked, stubbed or unused

- Hard-coded: seed sites in Argentina and California; Argentina bounding box (`action_guard.py`); Buenos Aires CAP defaults (`cap.py`, `routers/cap.py`); SINAGIR fields; three historical-context seed rows; Dashboard demo alert, fusion, audit, timeline, CAP receipt, evidence images, model labels, forecast; Settings env-var block; `pukaar-model:2b` fallback in image assessor.
- Stubbed: all actuators (`print` + `RECORDED_CALLS`); Siren/LoRa/Notify buttons in SiteDetail and Dashboard; connectivity "offline" is a server-side flag, not real.
- Mocked in tests: `deps.llm_client.structure_observation` patched to `None`; fake LiteRT runtimes; fake httpx clients.
- Unused or unreachable: `fusion/engine.py` (tests only); `services/node_analysis.py`; `schemas/tools.TOOL_SCHEMAS`; `serializers.serialize_observation`/`publicize_artifact_refs`/`parse_json_list` (camera only); `storage.persist_frame_image`; `cap.write_cap_sample`; `main.is_online`; `CommandCenter` `NodeProfileCard`/`NodeMetricsCard`/`HandoffNote`; `idb.clearOfflineReports`; frontend `App.css`, `assets/*`, `public/sw.js`, `public/icons.svg`, `_persona_c_preview.html`; `shared/schemas/*.json` (empty files); npm packages `zod`, `tailwindcss`, `@tailwindcss/vite`, `vitest-fetch-mock`, `@testing-library/react`, `@testing-library/dom` (no imports); `bun.lock`.
- `services/action_guard.validate_tool_call` is real but no route calls it.

## 8. Other top-level folders

| Path | Contents |
|---|---|
| `android/` | Kotlin/Compose volunteer app with on-device model (`Pukaar AIOnDevice.kt`), Room queue, Gradle wrapper and a committed `.gradle/` cache (ignored). |
| `demo-artifacts/` | Old demo pack: zip of a built dashboard (10.6 MB), mp4 river clips, screenshots, LiteRT/model configs, logs, `pack.ps1`. |
| `notebooks/` | Kaggle-style hardware replay notebook (HF_TOKEN from env). |
| `datasets/rioplatense_hydro/` | 82-line Spanish corpus used by `test_rioplatense.py` and `eval_rioplatense.py`. |
| `fixtures/` | `pukaar_live_demo/` (notebook fixture pack), `audio/siren.wav` (used by `scripts/demo_connectivity.py`). Served at `/fixtures`. |
| `shared/schemas/` | Three empty JSON files. |
| `docs/` | Old submission docs, Pi/LiteRT benchmarks, video production pipeline (mp4, wav, screenshots, HTML scenes, scripts), Spanish PDFs, Argentina compliance. |
| `.design_pkg/` | Old design-system bundle (copies of frontend/android sources, previews, a PDF). |
| `.rtk/` | Template config for an "RTK" CLI filter tool; only comments. |
| `scripts/` | dev/setup (sh + ps1), seed.ps1, demo scripts, Pi node scripts (`node_guard.py`, `pi_pukaar_node.py`), local-model scripts, demo_persona_c recording scripts. |
| root | `PLAN.md`, `MAIN_IDEA.md` (Spanish pitch), `Project.md` (old submission criteria), `LICENSE` (CC BY 4.0), `docker-compose.yml` (backend + Ollama), `.env.example` (Gmail placeholders), `.gitignore`. `backend/uv.lock` locks the current Python deps. |

## 9. After the preparation run

Sections 0-8 describe the code as found. After the fixes and cleanup recorded
in PROGRESS.md and DECISIONS.md, the repository holds:

- `backend/src/Pukaar/`: `main.py`; `core/settings.py` (local model,
  photo description, ASR, hydromet, actuators, data paths; no node, Pi or sync
  settings); `db/database.py` (one SQLite database); `models/domain.py`
  (`Site`, `SiteExperimentalSettings` with `historical_context_enabled` only,
  `VolunteerReport`, `ParsedObservation`, `HydrometSnapshot`, `FusedAlert`,
  `Incident`, `ActuationRecord`); `adapters/` (`llm.py`, `asr.py`,
  `image_assessment.py` Ollama path only, `text_structuring_fewshot.py` with
  `FewShotTextStructurer`); `services/` (`decision_engine` without camera
  rules, `reasoning` without `node_obs`, `report_structuring`, `predictive`
  (no caller yet), `external_data`, `historical_context`, `actuators` Ollama
  selection only, `action_guard`, `cap`, `storage` uploads only); routers
  `runtime`, `sites`, `pukaar` (reports), `alerts`, `cap`, `demo_inject`
  (report injection only).
- Routes: `GET /api/health`, `GET /api/settings/runtime`,
  `GET|POST /api/settings/connectivity`, `GET|POST /api/sites`,
  `GET /api/sites/{id}`, `GET|PUT /api/sites/{id}/experimental-settings`,
  `GET|POST /api/sites/{id}/historical-context`,
  `GET /api/sites/{id}/external-snapshot`,
  `POST /api/sites/{id}/external-snapshot/refresh`, `POST|GET /api/reports`,
  `GET /api/alerts`, `GET /api/alerts/{id}`,
  `GET /api/sites/{id}/operator-summary`, `GET /api/incidents/{id}/timeline`,
  `POST /api/incidents/{id}/ack`, `POST /api/incidents/{id}/close`,
  `POST /api/alerts/recompute`, `POST /api/cap/emit` (and `/cap/emit`),
  env-gated `POST /api/demo/inject-volunteer-report`, static `/uploads`.
  Gone: camera analysis, calibration, forecast, sync, SINAGIR export,
  `/fixtures`.
- Frontend pages: Dashboard (reports + hydromet tiles, reasoning, audit,
  hard-coded demo fallback), Report, Queue, SiteDetail (hydromet panel only),
  Settings (model and hydromet status). Calibration page gone. No call to a
  missing route remains.
- Tests: backend 53 (all collect and pass), frontend 5.
- Folders gone: `android/`, `demo-artifacts/`, `notebooks/`, `datasets/`,
  `shared/`, `fixtures/`, `.design_pkg/`, `.rtk/`, old `docs/`,
  `docker-compose.yml`, `MAIN_IDEA.md`.

## 10. After the build run (current)

The backend was rebuilt into the PLAN.md 4a layout (DECISIONS.md "Build run").
`backend/README.md` lists each folder. Flow:

- **Sweep** (EventBridge Scheduler, 15 min) -> `handlers/sweep.py` ->
  `services/decision_engine.sweep_all` -> per village: claim the 15-minute
  window (conditional put) -> `external_data.fetch_live` (Open-Meteo) ->
  `risk_rules.assess` -> `apply_hysteresis` -> on a rise: new `Alert`
  (status drafting, versioned trace) -> Step Functions execution (name =
  alert id); or escalate the alert that is still awaiting approval.
- **Approval** (`infra/approval.asl.json` -> `handlers/workflow.py` ->
  `workflow/steps.py`): draft (Strands drafting agent with read-only tools
  behind the Cedar hook, draft checker, fixed Hindi template on failure,
  Polly MP3 to S3) -> ask officer (task token + signed one-tap link, Telegram
  if the officer linked a chat) -> approved: deliver (Cedar + action guard,
  Telegram `sendAudio` with a "मिल गया" button, stub channel otherwise) ->
  wait -> recall once -> close; declined: close; timeout: next officer, then
  critical auto-send or expire; any error: failsafe.
- **Reports**: `POST /reports` -> `services/reports.intake` (S3 media, keyword
  reading, duplicate pin check, tracking code) -> worker Lambda
  `process_report` (Transcribe batch, model structuring, photo description,
  auto-verification) -> recompute the village.
- **Replay**: `POST /replay/start` -> worker `replay` task walks the archived
  hours in `data/replay/<scenario>/scenario.json` through the same
  `recompute_village` with a simulated clock; everything is `replay: true`.
- **Ask Pukaar**: `POST /ask/officer` -> `services/analyst.ask` (Strands
  analyst agent over read-only tools; charts built by code from tool data;
  keyword router without a model).

Data: one DynamoDB table (`store/repo.py` docstring lists every key), S3 for
audio, photos; `data/` holds villages, thresholds, replay scenarios, the
back-test result and API probes. Routes: `docs/CONTRACT.md`. Tests:
`backend/tests/` (all offline).
