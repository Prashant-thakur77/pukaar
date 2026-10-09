# DECISIONS.md

Choices made without the human, and why. Newest sections at the bottom.

## Plan versus code (preparation run)

PLAN.md section 5 names files that exist on disk under other names. The code
wins (PLAN.md section 1); the mapping is:

| PLAN.md says | On disk |
|---|---|
| `services/acuifero_assessment.py` | `services/pukaar_assessment.py` |
| `api/routers/vigia.py` | `api/routers/pukaar.py` (report routes) |
| `api/routers/acuifero.py` | does not exist; its camera routes (`/node/analyze`, `/sites/{id}/sample-node-analysis`) are gone, but the frontend and `test_api.py` still call them |
| `adapters/text_structuring_gemma_fewshot.py` | was `adapters/text_structuring_pukaar-ai_fewshot.py`; now `adapters/text_structuring_fewshot.py` (see below) |
| `scripts/run_gemma_local.sh` | `scripts/run_pukaar-ai_local.sh` |
| `scripts/run_acuifero_pi8_multimodal_demo.sh`, `..._pi16_...` | `scripts/run_pukaar_pi8_multimodal_demo.sh`, `scripts/run_pukaar_pi16_multimodal_prod.sh` |
| `fixtures/kaggle_live_demo/` | `fixtures/pukaar_live_demo/` |
| `HACKATHON.md` | does not exist |
| Settings prefixes `ACUIFERO_*` | `PUKAAR_*` (`PUKAAR_LLM_*`, `PUKAAR_NODE_*`, `PUKAAR_MULTIMODAL_*`, `PUKAAR_ASR_*`) |
| `assessment_mode = "temporal-gemma-v1"` | `"temporal-pukaar-ai-v1"` |
| Line counts in section 5 | differ slightly; not relied on |

## Fixes to the starting code

The starting code did not run: 13 of 21 backend test files failed to import
and the frontend did not build. The human asked for broken things to be
corrected, so these fixes land before the cleanup, each in its own commit:

- Python class names containing a space, and a module file name containing a
  hyphen, made `api/deps.py` (and everything importing it) a SyntaxError. Fixed
  by joining the names (`PukaarAI...`). The few-shot adapter took the name
  PLAN.md 5a already asks for: `adapters/text_structuring_fewshot.py`, class
  `FewShotTextStructurer`.
- The same problem in `Pukaar AIReasoning` broke `tsc -b` and `npm run build`.
- `tests/test_cap_emit.py` expected Spanish CAP values (`es-AR`,
  `SINAGIR/SINAME sitio`) that the code no longer emits; the test now matches
  the code. CAP is a stretch item and will move to Hindi later.
- `main.py` imported and registered the reports router twice.
- Tests are run against the versions pinned in `backend/uv.lock`
  (`uv sync --frozen --extra dev`). Unpinned latest versions (sqlmodel 0.0.48)
  reject naive datetimes and fail 14 more tests; the lock pins 0.0.38.

Still failing after the fixes, all removed by cleanup group (a):
`test_deterministic_firewall::test_elevated_without_crossing`,
`test_pukaar_provider::test_deps_select_litert_decision_runtime`, and
`test_api.py` (imports the missing `analyze_node`).

Not fixed: `npm run lint` reports 7 `no-explicit-any` errors in
`pages/Dashboard.tsx` that predate this run. That code is the hard-coded demo
dashboard PLAN.md M7 rebuilds; the build and tests do not depend on lint.

## Cleanup step 3

Rule applied: something goes only if PLAN.md section 5 says delete it, or a
search shows nothing left references it and PLAN.md has no use for it.
Anything PLAN.md section 5 or 5a says to keep or adapt stays, even when it
still holds local-model code that a later milestone replaces.

### Group (a): PLAN.md section 5 "Delete" list

Committed as several commits, each leaving the tests green:

1. **Camera-node pipeline, backend.** Delete `services/pukaar_assessment.py`,
   `services/deterministic_firewall.py`, `services/node_analysis.py`,
   `services/calibration.py`, `adapters/video_assessment.py`, `fusion/`, and
   their tests (`test_pukaar_assessment.py`, `test_deterministic_firewall.py`,
   `test_fusion_engine.py`). Drop the camera tables PLAN.md names
   (`NodeObservation`, `SiteCalibration`, `PukaarAssessmentArtifact`) and the
   `Site` sample-video fields. Remove the camera-node rules from
   `decision_engine.py` (PLAN.md 5 "Remove the camera-node rules"), the
   calibration routes, and the `/sites/{id}/forecast` route, whose only input
   was camera water-level readings (`services/predictive.py` itself stays; M2
   feeds it discharge). Camera tests in `test_api.py` go; decision-engine tests
   that used camera readings to reach red or orange now use volunteer reports
   that reach the same level. `demo_inject`'s camera endpoint goes (the router
   becomes `replay` later). Seed drops the USGS camera site and calibrations.
2. **Camera-node screens, frontend.** `pages/Calibration.tsx` and its route,
   the video-analysis and calibration panels of `SiteDetail.tsx`, the camera
   tile and evidence frames on the dashboard, `public/demo_persona_c/` (camera
   frames shown only by that panel), the store's `fetchSiteForecast`.
3. **On-device model (LiteRT).** `adapters/litert_node.py`,
   `test_litert_node.py`, `test_litert_benchmark.py`, `test_pukaar_provider.py`
   (provider selection between LiteRT and Ollama, and the Pi scripts), the
   LiteRT branch of `services/actuators.py` and of
   `adapters/image_assessment.py`, the node section of `/settings/runtime` and
   of `pages/Settings.tsx`, the `PUKAAR_NODE_*` settings and Pi profiles, and
   `litert-lm-api` from `pyproject.toml` (with `uv.lock` regenerated). The
   Ollama paths stay: PLAN.md 5a replaces them with Bedrock in M4 and keeps the
   method names.
4. **Edge sync.** `api/routers/sync.py`, `SyncQueueItem`, `enqueue_entity`
   (PLAN.md 5a "the sync-queue helper"), the second SQLite database
   (`central.db`), `sync_status` columns, the frontend sync flush/status calls
   and the sync panel in Settings; the sync parts of `test_api.py` and
   `test_decision_engine.py`.
5. **Android app.** `android/`.
6. **Demo artifacts, notebooks, datasets.** `demo-artifacts/`, `notebooks/`,
   `datasets/` with `test_rioplatense.py` and `scripts/eval_rioplatense.py`,
   which only exist to test the Spanish dialect corpus. PLAN.md 5 replaces the
   dialect test with a Hindi report set; that is new work for a later
   milestone, not part of this cleanup.
7. **Local-model and camera scripts.** `scripts/run_pukaar-ai_local.sh`,
   `install_ollama_local.sh`, `fetch_litert_model.py`, `litert_benchmark.py`,
   `litert_smoke.py`, `run_pukaar_pi8_multimodal_demo.sh`,
   `run_pukaar_pi16_multimodal_prod.sh`, `demo_persona_c/`, and the camera-node
   scripts that call the deleted routes: `node_guard.py`, `pi_pukaar_node.py`,
   `demo.py` + `demo.ps1`, `demo_connectivity.py` +
   `demo_connectivity_android.md`, `fetch_demo_assets.py`. `docker-compose.yml`
   (backend + Ollama). `scripts/dev.sh` and `scripts/setup.sh` lose their calls
   to the deleted scripts; their full rewrite is later work.
8. **Duplicate and old folders.** `shared/` (three empty files),
   `fixtures/pukaar_live_demo/` (notebook fixtures), `fixtures/audio/siren.wav`
   (only `demo_connectivity.py` used it), `.design_pkg/`, `.rtk/`, and the old
   contents of `docs/`.

#### Group (a) as carried out

- The LiteRT-only scripts (`litert_benchmark.py`, `litert_smoke.py`,
  `fetch_litert_model.py`, `run_pukaar_pi8_multimodal_demo.sh`,
  `run_pukaar_pi16_multimodal_prod.sh`) went out with the LiteRT runtime
  (part 3) rather than in part 7, because they import or configure it.
- `test_pukaar_provider.py` went with the camera pipeline (part 1): it tested
  selection between the LiteRT and Ollama camera runners.
- The image-description settings kept the values the default Pi 8 GB profile
  gave them (512 px, 1024 context, 300 s). The default multimodal model was the
  LiteRT file name `pukaar-model-2b.litertlm`, which the remaining Ollama path
  cannot load; it is now `pukaar-model:2b`, the model the adapter already fell
  back to.
- Report refresh and `/alerts/recompute` used the LiteRT runtime for reasoning;
  they now use the same runtime as `POST /reports` (`get_decision_runtime()`).
- `backend/Dockerfile` is kept (see "Unsure, kept").
- Two commit mistakes, left in history because history is not rewritten:
  `8821524` also added `backend/data/historical_context.sqlite`, a file the
  tests generate; `69a3e6e` removes it and ignores `*.sqlite` there, but also
  picked up the already-staged deletion of `api/routers/sync.py`, so the tree
  at `69a3e6e` does not import. The next commit (`Remove edge-to-central
  sync`) completes that change.

### Group (b): dead code

Each item below has no reference left in the repo (checked with a full-text
search) and PLAN.md has no use for it:

- `api/serializers.parse_json_object` (its only caller was the camera
  serializer).
- `services/storage`: `public_asset_url_for_path`, `resolve_local_asset_path`,
  `persist_frame_image`, `persist_json_artifact`, `get_fixture_dir`, and the
  `/fixtures` static mount in `main.py` (the `fixtures/` folder is gone and no
  page asks for `/fixtures/*`).
- `services/cap.write_cap_sample` (no caller; `build_cap_xml` stays).
- `schemas/tools.TOOL_SCHEMAS` (no caller; the argument models stay, the
  action guard uses them).
- `schemas/api.CalibrationPayload` (calibration routes removed).
- `main.is_online` ("backward-compatible alias"; every caller uses
  `deps.is_online`).
- Frontend: `lib/idb.clearOfflineReports`, and `store.emitCap` with its
  `CapEmitRequest` type (the only caller was the removed site-page button; the
  backend CAP route stays as a PLAN.md stretch item).

Kept although only tests or nothing call them, because PLAN.md keeps them:
the actuator and adapter protocols (`AlarmActuator`, `RadioActuator`,
`NotificationActuator`, `AudioTranscriptionAdapter`, `ImageAssessmentAdapter`),
`services/predictive.forecast_short_term` (M2 feeds it discharge), and the API
route handlers (registered by decorator).

### Group (c): unused files

No reference in `index.html`, `src/`, the build configs or any script:
`frontend/src/App.css`, `frontend/src/assets/{hero.png,react.svg,vite.svg}`
(Vite template leftovers), `frontend/public/sw.js` (vite-plugin-pwa generates
its own service worker at build time), `frontend/public/icons.svg`,
`frontend/_persona_c_preview.html`, `frontend/bun.lock` (a Bun lock file;
every script and the setup use npm with `package-lock.json`), and
`backend/data/.gitkeep` (the backend creates `data/` at start-up). Media,
screenshots, notebooks, editor folders and build output were already removed
in group (a) or were never tracked.

### Group (d): unused dependencies

Removed (no remaining file imports them):
- Python runtime: `litert-lm-api` (LiteRT runtime removed), `aiofiles` (never
  imported; PLAN.md 5a also drops it).
- Python dev: `pytest-asyncio`, `trio` (no async test functions remain; the
  tests drive coroutines with `anyio.run`, which FastAPI already installs).
- npm: `zod`, `tailwindcss`, `@tailwindcss/vite` (Tailwind was never wired into
  Vite; `index.css` defines its own classes), `vitest-fetch-mock`,
  `@testing-library/react`, `@testing-library/dom`.

Kept: `lxml` and `orjson` are not imported, but PLAN.md 5a lists both under
"Keep". `uvicorn` and `python-multipart` are not imported but are used at run
time (server command; FastAPI form parsing). `faster-whisper` and `sqlmodel`
are still imported; M4 and M1 replace them. `@types/node` is used through
`tsconfig.node.json`.

### Group (e): unused settings and environment variables

Removed (read into settings but never used):
- `Settings.project_root`, `Settings.backend_root` (the latter stays as a local
  default for `PUKAAR_DATA_DIR`).
- `Settings.image_max_tokens` / `PUKAAR_IMAGE_MAX_TOKENS` and
  `Settings.image_timeout_seconds` / `PUKAAR_IMAGE_TIMEOUT_SECONDS`; the image
  adapter uses the `PUKAAR_MULTIMODAL_*` values.
- Per-site `forecast_enabled`, `forecast_horizon_minutes`,
  `forecast_critical_threshold` (table columns, request schema, frontend type):
  their only consumer was the `/sites/{id}/forecast` route removed in group
  (a). `historical_context_enabled` stays; the dashboard toggle uses it.
- `.env.example` held `GMAIL_USER` and `GMAIL_APP_PASSWORD`, which no code
  reads. It now lists the variables the code does read. PLAN.md 5 asks for a
  Pukaar `.env.example`; the `PUKAAR_*` AWS settings arrive with M1-M4.

Kept: `PUKAAR_FEWSHOT_COUNT` (read by the few-shot adapter),
`PUKAAR_ENABLE_DEMO_INJECT` (gates the demo router that becomes `replay`).

### Group (f): old documentation

- `MAIN_IDEA.md`: Spanish pitch for the Argentina LiteRT/Raspberry Pi product.
  PLAN.md 5 allows removing it. Removed.
- `frontend/README.md`: the unmodified Vite template README. Removed.
- `backend/README.md`: described the Raspberry Pi camera node, LiteRT
  profiles and deleted scripts. `pyproject.toml` declares it as the package
  readme, so it is rewritten to describe what the backend is today.
- The root `README.md` is written in step 5.
- `Project.md` is equally out of date (old submission criteria, links to
  deleted docs), but PLAN.md does not name it, so rule 11 keeps it. Listed
  under "Unsure, kept".

### Group (g): stale comments

Comment and docstring text that described removed code: the "Persona C"
recording notes and Spanish layout diagram on the dashboard, the database pool
comment citing the offline sync and forecast paths, the Dockerfile's
`docker compose` notes, and the notifier docstring naming the Android client.
No TODO or FIXME comments referred to removed code. The Spanish prompts and
keyword lists are code, not comments, and PLAN.md M4 replaces them.

### Follow-up: national-schema export route

PLAN.md 5 ("Keep and adapt", `api/routers/alerts.py`) says to remove the
national-schema export route. `POST /alerts/{id}/export-sinagir` lost its only
caller (the site page button) in group (a), so it and
`tests/test_sinagir_export.py` are removed. The CAP builder keeps its
SINAGIR-named fields until CAP moves to Hindi/India (stretch).

## Unsure, kept

Kept because PLAN.md does not say to delete them and something still uses
them, or because removing them is a decision for the human or a later
milestone:

| Item | Why kept |
|---|---|
| `backend/Dockerfile` | Dev image, still valid. PLAN.md 4a builds a two-target Lambda Dockerfile in M2 that may replace or adapt it. |
| `scripts/dev.sh`, `dev.ps1`, `setup.sh`, `setup.ps1`, `seed.ps1` | Still work. PLAN.md asks for `dev.sh` to be rewritten and for `make` targets; that is milestone work. |
| `/api/settings/connectivity` and `deps.is_online` | PLAN.md 5 drops the connectivity routes, but `Layout.tsx` uses them to decide online/offline. Removing them needs the UI change in M7. |
| `/api/settings/runtime` | Reports local-model and Open-Meteo status for the Settings page. PLAN.md 5a replaces it with `/health` service checks in M4. |
| `lxml`, `orjson` | Not imported, but PLAN.md 5a lists both under "Keep". |
| `services/reasoning.deserialize_chain`, `services/action_guard.guarded_model_action` | Only tests call them; both belong to modules PLAN.md keeps. |
| `services/predictive.forecast_short_term` | No caller after the camera removal; PLAN.md 5 keeps it for the discharge forecast. |
| `api/routers/demo_inject.py` | PLAN.md 5 turns it into `replay`. |
| `services/historical_context.py` (SQLite FTS, three seed rows about Silverado CA and a test site) | PLAN.md 5 keeps `validate_context_citations` and moves past events to DynamoDB. |
| Hard-coded demo data in `pages/Dashboard.tsx` (`DEMO_ALERT` still mentions a critical line, LoRa, sirens) | PLAN.md 5a/M7 removes it when the console is rebuilt; removing it now leaves the page empty. |
| Spanish prompts, keyword lists, few-shot examples and UI strings | PLAN.md M4/M6 translates or replaces them. |
| Argentina bounding box in `services/action_guard.py`, Buenos Aires CAP defaults | PLAN.md M8 and the CAP stretch adapt them. |
| `/uploads` static mount | Serves stored report media; PLAN.md moves storage to S3 later. |
| `frontend/public/manifest.webmanifest` | Referenced by `index.html`; overlaps with the manifest vite-plugin-pwa generates. |
| `docs/Project/video/raw/screenshots/` on the local disk | Git-ignored old media, never committed. Left on disk; it never reaches the remote. |

## Human decisions

- 2026-10-09: the human chose to delete `Project.md` and `LICENSE` (CC BY 4.0).
  The repository now has no licence file; add one before making it public if
  the event requires an open-source licence.
