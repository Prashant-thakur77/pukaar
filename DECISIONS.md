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
