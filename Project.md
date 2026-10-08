# Pukaar Release - Submission

Track: **Global Resilience**. Prize target: **LiteRT Prize (USD 10,000)**.

> **For technical judges.** This file maps the submission to each judging
> criterion with one short claim and a link to the file that proves it.
> For the product narrative (problem framing, demo storyboard, novelty
> assessment), see [`MAIN_IDEA.md`](MAIN_IDEA.md). For step-by-step
> reproducibility, see [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).

## Judging criteria alignment

### 1. Why not cloud GPT-4? - Pukaar AI decides locally on the node

`Pukaar` is no longer "OpenCV plus explanation". The fixed node now builds a
temporal evidence pack and asks Pukaar AI to produce the node assessment package:
`assessment_level`, `assessment_score`, `temporal_summary`,
`reasoning_summary`, `reasoning_steps`, and `critical_evidence`.

Proof: backend node-analysis endpoints and [`docs/architecture.md`](docs/architecture.md).

### 2. Auditable reasoning instead of a black box

Every non-green `FusedAlert` exposes a Pukaar AI-produced Spanish reasoning block
that cites specific signals plus a deterministic rule trace. Judges can inspect
`GET /api/alerts/{id}` live.

Proof: [`docs/Project/thinking-mode.md`](docs/Project/thinking-mode.md).

### 3. Multimodal temporal evidence, not just a single frame

The demo node assessment now persists a rich audit pack with curated frames,
evidence imagery, runner metadata, and fallback status. The evidence-frame
description remains in the UI, but the architectural claim is temporal Pukaar AI
reasoning over a curated sequence.

Proof: [`docs/Project/multimodal-comparison.md`](docs/Project/multimodal-comparison.md).

### 4. Rioplatense linguistic specialization

82-example corpus across 6 provinces. `Pukaar AIFewShotTextStructurer` with 12
exemplars. Benchmark: rules 45% -> few-shot ~80% on held-out test split.

Proof: [`docs/Project/rioplatense_eval.md`](docs/Project/rioplatense_eval.md).

### 5. Connectivity-loss resilience

`scripts/demo_connectivity.py` runs: online report -> offline -> queued report
-> local node analysis -> **audible siren** -> online -> queue drains.

Actuator continuity note: in LiteRT production mode, the backend no longer calls
Ollama for actuator selection. It asks LiteRT for strict JSON tool selection and
falls back to deterministic recommended actuators for orange/red alerts if model
selection returns no valid tools or times out.

Proof: [`docs/Project/pukaar.md`](docs/Project/pukaar.md).

### 6. SINAGIR compatibility

`POST /api/alerts/{id}/export-sinagir` returns a schema-tagged, documented
payload. Field-by-field mapping published.

Proof: [`docs/Project/sinagir-mapping.md`](docs/Project/sinagir-mapping.md).

### 7. On-device Android path

`android/.../data/Pukaar AIOnDevice.kt` wraps LiteRT-LM Android
(`com.google.ai.edge.litertlm:litertlm-android`) and loads
`pukaar-model-2b.litertlm` — the same artifact the backend uses.
Volunteer report structuring runs fully on-device with no silent
backend fallback. MediaPipe `.task` was the original plan; Google has
not shipped a Pukaar AI `.task`, so the Android tier moved to LiteRT-LM.

Proof: [`docs/Project/android_pukaar-ai.md`](docs/Project/android_pukaar-ai.md).

## Pitch video script

0:00-0:15 - context: Argentina's Litoral flood problem; local-alert gap under connectivity loss.

0:15-0:45 - Android volunteer flow: photo + voice -> fully on-device Pukaar AI structuring.

0:45-1:20 - fixed-node analysis on the Silverado clip. Show the curated evidence sequence, `temporal_summary`, runner mode, and resulting alert.

1:20-1:45 - evidence frame overlay plus Pukaar AI's Spanish description as a supporting view, not as the main architectural claim.

1:45-2:05 - connectivity-loss live: wifi off, red banner, offline report queued, node alert fires, **siren audible**, wifi on, queue drains.

2:05-2:25 - alert card with the reasoning chain expanding on screen.

2:25-2:40 - SINAGIR mapping and Plan Nacional 2025-2029 alignment close.

## Reproduce the demo

```bash
./scripts/setup.sh
PYTHONPATH=backend/src python3 -m Pukaar.scripts.seed
./scripts/dev.sh
python3 scripts/demo_connectivity.py
```

## Test suite

```bash
cd backend && PYTHONPATH=src pytest -q
cd frontend && npm test && npm run build
```

## LiteRT benchmark evidence and asterisks

- Pi 5 8 GB E2B measurements, including wall-clock/RSS and unmeasured
  TTFT/decode tok/s rationale: [`docs/Project/benchmark-card.md`](docs/Project/benchmark-card.md).
- E2B vs E4B ablation: [`docs/Project/e2b-e4b-ablation.md`](docs/Project/e2b-e4b-ablation.md).
  E2B remains the Pi 5 8 GB operating profile. E4B GPU text/reasoning failed on
  this hardware with WebGPU buffer/command errors; E4B CPU and multimodal CPU/CPU
  are recorded as fallback/candidate measurements, not the main Pi profile.
- LiteRT GPU text-engine reuse is mitigated by one engine-reset retry. The
  mitigation preserves backend continuity, but retry calls can be slower and use
  more RSS because the engine is recreated.
