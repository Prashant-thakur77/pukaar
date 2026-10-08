# PUKAAR 4 + Pukaar — Project Final Push Agent Brief

## 0. Agent Brief

You are implementing the final competitive push for a flood early-warning system submitted to the **Pukaar Release, Global Resilience track**, targeting the **LiteRT Prize (USD 10,000)** for excellence in the Google AI Edge / Lite-LM ecosystem.

You are executing **inside the project folder** on the developer's local machine. The repository is already partially built. Your job is to close the gap between "working MVP" and "winning submission" over the next **28 days**.

**Read this entire brief before touching code.** Then read `plan.md` and `README.md` from the repository root. Only after that, begin.

---

## 1. Project Background (terse)

- **Product**: "Pukaar 4 + Pukaar" — hybrid flood early-warning system.
  - `Pukaar 4` = fixed-camera node, OpenCV video analysis, local actuation (LoRa / GPIO / siren simulation).
  - `Pukaar` = volunteer mobile app, offline-first, photo + voice + observation → structured JSON.
  - Both feed a single local decision engine that produces a `FusedAlert` with a transparent `decision_trace`.
- **Users**: civil defense volunteers and municipal coordinators in flood-prone towns along Argentina's Paraná, Salado, and Paraguay rivers. Non-technical. Today they coordinate via WhatsApp audios and photos.
- **Schema target**: SINAGIR (Argentina's national disaster risk management system, Ley 27.287/2016). Recent: Resolución 334/2026 approved the Plan Nacional para la Reducción del Riesgo de Desastres 2025-2029, prioritizing hydrometeorological early-warning.
- **LLM target**: Pukaar AI E4B on-device (Android, GGUF Q4_K_M) or E2B via local Ollama for backend.
- **Branches**:
  - `main` → web PWA + FastAPI backend (earlier surface).
  - `develop` → **Android migration in progress**. This is your primary working branch.

---

## 2. What Wins This Project (judging priorities)

The submission is strong on architecture and offline-first plumbing. It is **weak on demonstrating Pukaar AI doing something a CNN + cloud API could not**. Judges will ask "why not cloud GPT-4?" — your entire job is to make that question answer itself.

Four claims of novelty must be defensible in the final demo:

1. **Auditable thinking-mode chain**: Pukaar AI's reasoning about severity must be visible to the user, not a black box.
2. **Dual-input hybrid**: fixed node + volunteer reports → same `FusedAlert` schema. (Mostly done, needs polish.)
3. **Rioplatense Spanish hydrological understanding**: a volunteer says "ya tapó la calle", the system produces correct structured output where a generic cloud LLM stumbles.
4. **SINAGIR-ready multimodal on-device inference**: photo + audio + text processed locally on Android, output maps to Argentina's official schema.

The pitch video (~30 points) must show a **connectivity-loss scenario live**: wifi off → app still works → local alerts fire → wifi returns → queue drains. This is non-negotiable.

---

## 3. Hard Rules

- **Work on `develop`**. Create feature branches `feat/<priority>-<short-name>` for each priority block. Open PR into `develop`, merge yourself after CI is green.
- **Do not break existing tests**. If a task requires changing a test, fix it in the same PR as the feature.
- **Commit hygiene**: conventional commits (`feat:`, `fix:`, `docs:`, `test:`), small atomic commits.
- **Document as you go**: every priority block produces or updates a file under `docs/Project/`.
- **Honest claims**: if you cannot implement something, say so in README "Known limitations". The original `plan.md` rule stands: *Do not fake capabilities that are not implemented.*
- **Time-box aggressively**: if any single task blocks you for more than 4 hours, commit a stub with a `TODO(Project)` marker and move on.
- **No new tech stacks**: no new frameworks, no new languages, no new orchestration layers. Work within what's there.
- **Language**: all UI strings, LLM prompts, and user-facing docs in **Spanish**. Code, commits, and internal docs in **English**.
- **Ask for the developer's input only via `docs/Project/BLOCKERS.md`**. Do not pause waiting for interactive answers. Log blockers and keep moving on independent tasks.

---

## 4. Phase 0 — Reconnaissance (Day 1, non-negotiable)

Before writing any feature code, produce `docs/Project/recon.md` containing:

- Output of `git log --oneline --all -30`
- Output of `git branch -a` and `git status`
- Full tree of `develop` (use `git ls-tree -r develop --name-only`)
- **Android stack identification**: what's in `develop`? Kotlin + Jetpack Compose? Flutter? React Native? Find the build file (`build.gradle.kts`, `pubspec.yaml`, `package.json`) and report exact framework + versions.
- **Pukaar AI runtime on Android**: is there a MediaPipe LLM Inference integration? A LiteRT-LM binding? A `.task` or `.gguf` file referenced? Any model-loading code? If none, flag it as the single highest-priority gap.
- **LLM adapter interfaces**: list every adapter in `backend/src/Pukaar/adapters/`, its concrete implementations, and what calls them.
- **Current `decision_trace`**: run `pytest` or hit the API, paste a real `FusedAlert` with its `decision_trace` field verbatim.
- **Test status**: run backend tests (`pytest -q`), frontend tests (`npm test`, `npm run build`, `npm run lint`), and whatever Android tests exist. Paste results.
- **Blockers**: anything missing (Ollama not installed, model not pulled, no Android SDK) — list it in the same doc under `## Blockers`.

**Do not proceed to P1 until this doc is committed to `develop`.**

---

## 5. Priority Blocks

Execute in the order listed. Each block has goal, tasks, acceptance criteria, and day budget. Do not reorder unless P0 recon reveals a hard blocker.

### P1 — Auditable Thinking-Mode Chain (days 2-5)

**Goal**: When a `FusedAlert` is produced, the `decision_trace` must include Pukaar AI's explicit reasoning chain in Spanish, in addition to the deterministic rule firings. The UI (web and Android) must render this reasoning.

**Tasks**:

1. New service `backend/src/Pukaar/services/reasoning.py` with `generate_alert_reasoning(node_obs, volunteer_reports, fused_score, rules_fired) -> ReasoningBlock`.
2. The function calls Pukaar AI via the existing Ollama adapter with a prompt that:
   - Shows the current node observation (`waterline_ratio`, `rise_velocity`, `crossed_critical_line`, `confidence`).
   - Shows parsed volunteer reports (`water_level_category`, `trend`, detected phrases).
   - Shows the computed score and the deterministic rules that fired.
   - Asks Pukaar AI, in Spanish, to produce a 2-3 sentence auditable reasoning chain explaining *why* this severity level, referencing specific input signals by name.
3. `ReasoningBlock` has three fields: `llm_summary: str`, `llm_chain_of_thought: list[str]`, `model_name: str`.
4. Integrate into `services/alerting.py` (or wherever `FusedAlert` is produced). Reasoning runs on every alert of level yellow or higher. For green, skip (cost/latency). Deterministic explanation is always present regardless.
5. Persist the reasoning alongside the alert in SQLite. Add a migration if needed.
6. Expose via `GET /api/alerts/{id}` — response includes the reasoning block.
7. **Web UI**: collapsible "Razonamiento de Pukaar AI" section inside the alert card.
8. **Android UI**: equivalent collapsible panel in the alert detail screen.
9. **Deterministic fallback**: if Ollama is down, the reasoning is a template-based string derived from `rules_fired`. The `model_name` is `"rule-fallback"`. Never let the absence of the LLM break alert generation.

**Acceptance criteria**:

- For any non-green alert in the demo flow, clicking the alert shows a Spanish-language reasoning paragraph that references at least two specific input signals.
- Tests cover: with LLM, without LLM (fallback), and the persistence round-trip.
- `docs/Project/thinking-mode.md` contains 3 real examples (green skipped, yellow, red) with actual LLM output pasted in.

---

### P2 — Pukaar AI Multimodal on Evidence Frames (days 6-9)

**Goal**: When the fixed-node pipeline extracts an evidence frame (the most suspicious frame in the 60-second window), Pukaar AI describes what it sees. This is the single highest-signal multimodal demonstration for the LiteRT Prize.

**Tasks**:

1. New adapter `backend/src/Pukaar/adapters/image_assessment_pukaar-ai.py` implementing the existing `ImageAssessmentAdapter` interface.
2. The adapter loads the evidence frame, base64-encodes it, and calls Pukaar AI (E4B if available and fits in VRAM, E2B otherwise) via Ollama with a Spanish few-shot prompt (3 in-prompt examples) asking it to describe: visible water, infrastructure state, and any relevant hazards.
3. Return `ImageAssessmentResult`: `description_es: str`, `water_visible: bool`, `infrastructure_at_risk: bool`, `confidence: float`, `raw_model_output: str`.
4. Wire into the node analysis pipeline: every `NodeObservation` with `crossed_critical_line=True` OR `severity_score >= 0.5` also produces an image assessment. Persist it.
5. Expose via the site detail endpoint. Also expose `POST /api/node/explain-frame` accepting an arbitrary uploaded frame (useful for demo and for documentation screenshots).
6. **UI**: evidence frame thumbnail in the site detail view now has an overlay with Pukaar AI's one-line description and confidence. Click to expand full description. Works identically in web and Android.
7. **Latency budget**: <8 seconds end-to-end on the dev machine for a single frame. If E4B exceeds this, fall back to E2B automatically and log the fallback.
8. **Scoring authority**: the CV pipeline remains the authoritative signal for `severity_score`. Pukaar AI's multimodal output is *explanatory*, not *deciding*. This is critical for the "honest claims" rule and for reviewer credibility.

**Acceptance criteria**:

- Demo flow: run `sample-node-analysis`, see the evidence frame with Pukaar AI's Spanish description rendered on top.
- Works with only a local Ollama running (no internet).
- Comparison document `docs/Project/multimodal-comparison.md` with three frames, each showing: OpenCV numeric output, Pukaar AI E2B description, Pukaar AI E4B description (if runnable on dev machine).
- Tests cover: adapter output shape, fallback when Ollama is down, image encoding correctness.

---

### P3 — Connectivity-Loss Demo Flow (days 10-13, revisit day 27)

**Goal**: A scripted, repeatable, robust demo that shows `wifi-off → local operation → local siren → wifi-on → queue drain`. This is the narrative spine of the pitch video.

**Tasks**:

1. Create `scripts/demo_connectivity.py` (backend orchestrator).
2. Create `scripts/demo_connectivity_android.md` (manual-step script for the Android device).
3. The backend script:
   - Starts from a clean seeded state.
   - Fires a volunteer report (in online mode) → verifies synced to `central.db`.
   - Toggles `connectivity=offline` via the settings endpoint.
   - Fires a second volunteer report → verifies queued, not in central.
   - Triggers sample node analysis → verifies fused alert fires and local actuator log shows siren event.
   - Toggles `connectivity=online` → verifies queue drains, central now contains both reports + alert.
   - Prints a clear timeline to stdout with timestamps — screenshot-worthy.
4. `NotificationActuator` and siren WAV must actually fire. Audible sound on the demo machine. No silent simulation.
5. **Web UI**: when offline, show a persistent red banner "SIN CONECTIVIDAD — operación local activa" and a queue counter. When queue drains, a green flash "Sincronizado".
6. **Android UI**: equivalent (adapt to the stack identified in P0).
7. Record a 10-15 second screen capture of the offline transition as `docs/Project/media/connectivity_transition.mp4`. This clip is slotted into the pitch video later.

**Acceptance criteria**:

- `python scripts/demo_connectivity.py` runs end-to-end in under 90 seconds and prints a reproducible timeline.
- Audible siren plays during the offline alert.
- Web and Android banners both tested and documented with screenshots.

---

### P4 — Rioplatense Hydrological Understanding (days 14-18)

**Goal**: Demonstrate "hiperlocalización lingüística para homogeneización de datos". The system must correctly structure colloquial Litoral Spanish where a generic LLM stumbles.

**Tasks**:

1. Build a corpus at `datasets/rioplatense_hydro/corpus.jsonl`: **minimum 80 examples**, each with `transcript_es` and `structured_output`. Cover:
   - Water-level phrases: "pasó la marca", "ya toca el puente", "tapó la calle", "entró agua en las casas", "está por las rodillas", "baja despacio".
   - Trend phrases: "subiendo rápido", "estable", "bajando", "crece desde anoche", "se calmó un poco".
   - Infrastructure phrases: "el puente está tapado", "cortamos la ruta", "las casas de la costa están bajo agua".
   - Urgency cues: "vengan ya", "hay gente subida a los techos", "no podemos salir".
   - Regional variation: Corrientes, Chaco, Santa Fe, Entre Ríos, Formosa, plus Buenos Aires conurbano.
2. Split corpus: 70% train, 15% validation, 15% test.
3. **Few-shot track (must-have)**: `backend/src/Pukaar/adapters/text_structuring_pukaar-ai_fewshot.py` using Pukaar AI + 12 representative few-shot examples. This is the production path.
4. **LoRA track (stretch, only start if day 16 on schedule)**: in `training/lora_rioplatense/`, a LoRA fine-tuning script for Pukaar AI using HuggingFace PEFT. Rank 16, alpha 32, matching the original pitch. If local VRAM is insufficient, move to Google Colab and still check in the adapter weights under `training/lora_rioplatense/output/`. Production runtime must not hard-depend on LoRA — it is evidence, not critical path.
5. Create `docs/Project/rioplatense_eval.md` with a benchmark:
   - Run the held-out test set through: (a) rule-based parser baseline, (b) Pukaar AI few-shot, (c) Pukaar AI + LoRA if completed, (d) OpenAI `gpt-4o-mini` via API for reference (one-time, document the prompt).
   - Report accuracy per field (`water_level_category`, `trend`, `infrastructure_status`) and average correctness.
   - Include 5 qualitative examples where Pukaar AI + LoRA beats cloud GPT.
6. Default `TextStructuringAdapter` switches to the Pukaar AI few-shot adapter when the LLM is available.

**Acceptance criteria**:

- Corpus of 80+ labeled examples committed.
- Benchmark doc shows quantitative comparison. Pukaar AI few-shot must beat rule-based; ideally match or beat cloud baseline on regional phrases.
- If LoRA attempted: training script runs to completion (local or Colab), VRAM and wall-clock documented.
- Test suite includes 5 adversarial regional phrases that must parse correctly via the few-shot path.

---

### P5 — Click-to-Draw Calibration UI (days 19-20)

**Goal**: Replace numeric/rectangular calibration with click-to-draw on a canvas. Pure polish for demo quality.

**Tasks**:

1. Web frontend, `/sites/:id/calibrate`: render the reference frame to a `<canvas>`. User click-and-drags to define an ROI polygon (minimum 4 points), then clicks two points for the critical line.
2. Persist via the existing calibration endpoint — the API already supports polygons per `plan.md` §8.
3. Add a preview overlay (translucent fill on ROI, bold red critical line) and a "Reset" button.
4. **Android equivalent**: adapt to the native canvas/view system identified in P0 recon. If Android calibration is out of scope for time, clearly document the decision in README and ship web-only calibration.
5. Visual regression check: the Silverado demo clip must produce the same or better waterline accuracy after migrating calibration. Document in the commit message.

**Acceptance criteria**:

- Silverado demo site can be calibrated end-to-end from the web UI without typing numbers.
- Calibration persists across reloads and is correctly consumed by the node analyzer.

---

### P6 — SINAGIR Mapping Documentation (day 21)

**Goal**: Move SINAGIR compatibility from "intention" to "documented, traceable mapping". Half-day task with outsized pitch-credibility payoff.

**Tasks**:

1. Create `docs/Project/sinagir-mapping.md` with:
   - Brief context: Ley 27.287/2016 creates SINAGIR; Resolución 334/2026 (Plan Nacional para la Reducción del Riesgo de Desastres 2025-2029) prioritizes hydrometeorological early-warning systems; 60% of registered disasters in Argentina are floods.
   - A table mapping every field in our `FusedAlert` schema to the corresponding SINAME/SINAGIR concept. Link to the official portal (<https://www.argentina.gob.ar/sinagir/siname>) where possible.
   - Explicit statement of what *is* compatible today and what would need formal SINAGIR API integration (honest future work, not a current claim).
   - A sample payload in our `fused-alert.schema.json` format alongside the closest SINAGIR-equivalent structure for side-by-side comparison.
2. Add `POST /api/alerts/{id}/export-sinagir` returning the alert serialized to the documented SINAGIR-ready payload. This is a schema export, not a real SINAGIR submission — the doc must say so.
3. README gets a "SINAGIR compatibility" subsection linking to the mapping doc with an honest scope statement.

**Acceptance criteria**:

- Doc exists and is internally consistent.
- Export endpoint returns well-formed JSON that passes a JSON Schema validation test.
- README subsection published.

---

### P7 — Android-Specific Pukaar AI Integration (days 22-25)

**Goal**: The Android app from `develop` actually runs Pukaar AI locally for the volunteer report flow. This is the single highest-signal element for the LiteRT Prize. Scope adapts to P0 recon findings.

**Tasks** (adapt based on stack found in P0):

1. Confirm the Pukaar AI runtime path on Android. Preference order: MediaPipe LLM Inference API (GPU/NNAPI acceleration, ships as `.task` files), LiteRT-LM if already wired, GGUF via llama.cpp JNI as fallback.
2. Bundle or download-on-first-launch a Pukaar AI E2B `.task` (MediaPipe) or Q4_K_M `.gguf` file. Document APK size impact.
3. The volunteer report submission flow on Android calls the local model for text structuring (mirrors the backend `TextStructuringAdapter`). Reuse the few-shot prompt built in P4.
4. Image assessment on the volunteer photo — same adapter pattern, on-device.
5. Latency budget: <12 seconds for text+image combined on a mid-range Android device. If no physical device is available, use the emulator and document CPU/RAM profile.
6. UI shows a small "Analizado con Pukaar AI en este dispositivo" indicator on locally-processed reports, vs "Analizado en servidor" for any that fell back.
7. **Critical**: the Android flow must NOT silently fall back to the backend. If the on-device model fails, show an explicit error and require the user to use the backend sync path. This makes the on-device claim defensible.
8. Produce `docs/Project/android_pukaar-ai.md` describing stack, model choice, quantization, benchmarks, and limitations.

**Acceptance criteria**:

- APK installs on a physical or emulated mid-range Android device (document which).
- Cold-start Pukaar AI load time documented.
- Volunteer report with photo + voice transcript is fully processed on-device — screen recording proves it, no network calls during inference.

---

### P8 — Submission Prep & Pitch Video (days 26-28)

**Goal**: Package everything for judging.

**Tasks**:

1. **Day 26 start**: merge `develop` → `main` once all tests green. Tag `v1.0-Project-submission`. Create a GitHub release with full notes.
2. Rewrite `README.md` for the Project audience:
   - 1-paragraph product pitch.
   - "What makes this different" bullet list (the four novelty claims, linked to proof docs).
   - Setup + demo instructions that work from a clean clone.
   - Benchmarks section pulling numbers from P4 and P7 docs.
   - Honest "Limitations" section.
   - Links to all `docs/Project/` files.
3. Create `Project.md` with:
   - Judging-criteria alignment (one subsection per novelty claim, each linking to its proof doc and demo).
   - Video script (see below).
4. Pitch video (target the Project's time limit, likely 2-3 minutes):
   - Opens on the flood context for Argentina's Litoral region, referencing the Bahía Blanca 2025 local-alert gap (<https://www.meteored.com.ar/noticias/actualidad/no-es-lo-mismo-alerta-meteorologica-que-alerta-de-riesgo-local-la-diferencia-puede-ser-cuestion-de-vida-o-muerte.html>).
   - Shows the volunteer flow on Android with Pukaar AI processing fully on-device (P7).
   - Shows the fixed node analyzing the Silverado clip with the evidence frame + Pukaar AI's Spanish description (P2).
   - Shows the connectivity-loss transition live (P3 recording).
   - Shows the thinking-mode reasoning chain expanding on an alert (P1).
   - Closes on the SINAGIR mapping and Plan Nacional 2025-2029 alignment (P6).
5. Final polish pass:
   - Eliminate or clearly mark every `TODO(Project)` in the limitations section.
   - Ensure every `pytest` and `npm test` passes on a clean checkout.
   - Ensure `scripts/setup.sh` works end-to-end from a freshly cloned repo.
6. Open a GitHub issue titled "Post-Project roadmap" listing honest future work (real LoRa, real SINAGIR API, expanded corpus, real device fleet). Explicit roadmap is a judging positive.

**Acceptance criteria**:

- Fresh clone at `v1.0-Project-submission` → `./scripts/setup.sh` → `python scripts/demo_connectivity.py` works with zero extra steps.
- Pitch video rendered and uploaded; link in README and Project.md.
- Release tagged, release notes written.

---

## 6. Hard Non-Goals

Do NOT spend time on any of these:

- Real LoRa hardware, real GPIO switching, real sirens beyond WAV playback.
- Real SINAGIR production API integration.
- Maps, user auth, roles, multi-tenancy.
- Cloud deployment.
- Fine-tuning beyond rank-16 LoRA in P4. No full-parameter fine-tuning, no RLHF, no custom architectures.
- SOTA benchmark chasing. The goal is a defensible demo, not leaderboard optimization.
- Rewriting anything that already works. Specifically: the CV analyzer, the sync queue, and the IndexedDB offline store are done. Leave them alone.
- Migrating to new frameworks or porting to iOS.
- Refactoring unless a task explicitly requires it.

---

## 7. Timeline Summary

| Days | Block | Deliverable |
|---|---|---|
| 1 | P0 Recon | `docs/Project/recon.md` committed |
| 2-5 | P1 Thinking-Mode Chain | Reasoning visible in alerts (web + Android) |
| 6-9 | P2 Multimodal Evidence | Pukaar AI describes evidence frames |
| 10-13 | P3 Connectivity Demo v1 | Scripted demo + banner UI + recorded clip |
| 14-18 | P4 Rioplatense | Corpus + few-shot + (stretch) LoRA + benchmark |
| 19-20 | P5 Click-to-Draw | Calibration UI polished |
| 21 | P6 SINAGIR Docs | Mapping doc + export endpoint |
| 22-25 | P7 Android Pukaar AI | On-device inference working |
| 26-28 | P8 Submission | Merge, release, video, polish |

Buffer is **zero**. If you fall behind: compress P5 first, then P4's LoRA stretch (never P4's few-shot). **Never compress P1, P2, P3, or P7** — those are the novelty spine.

---

## 8. Definition of Done

The submission is ready only if:

- Fresh clone of `main` at `v1.0-Project-submission` builds, seeds, and runs with no manual steps beyond what's in README.
- Demo flow (connectivity-loss) is reproducible on demand with a single command.
- Android APK demonstrates on-device Pukaar AI inference, recorded on video.
- Every novelty claim in the pitch video has a corresponding doc in `docs/Project/` and a runnable demo.
- Pitch video rendered, uploaded, linked.
- README explicitly lists limitations. No claim is stronger than its evidence.
- All tests pass.
- GitHub release exists with full notes.

---

## 9. Reporting

At the end of every working session, append a dated entry to `docs/Project/log.md`:

```
## YYYY-MM-DD
- Did: <what you accomplished>
- Hit acceptance criteria: <which, from which block>
- Blocked: <blockers with file/line references>
- Days remaining: <N> / Days expected for current block: <M>
```

If any block slips past its day budget, stop and write a slip report in the same log with a proposed re-plan. Do not silently absorb slippage — the developer needs to see drift early.

If you hit a genuine blocker requiring the developer's input (credentials, decisions with tradeoffs you can't resolve autonomously, purchases), log it in `docs/Project/BLOCKERS.md` with specific questions and a default answer you'll proceed with if not addressed within 24 hours. Keep moving on parallel tasks.

---

## 10. Execute

Start with Phase 0 now. Do not ask for clarification before producing the recon doc — **the recon is itself your clarification**. Read `plan.md` and `README.md` from the repository root before writing anything else.

When P0 is committed to `develop`, proceed immediately to P1. When each block's acceptance criteria are met and the PR is merged, proceed to the next block. Do not wait for approval between blocks.
