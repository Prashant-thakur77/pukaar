# Pukaar Release — Submission

Track: **Global Resilience**. Prize target: **LiteRT Prize (USD 10,000)**.

## Judging criteria alignment

### 1. Why not cloud GPT-4? — auditable reasoning on-device

Every non-green `FusedAlert` exposes a Pukaar AI-produced Spanish reasoning block
that cites specific signals (`waterline_ratio`, `crossed_critical_line`,
`road_status`, etc.) plus a deterministic rule trace. Judges can inspect
`GET /api/alerts/{id}` live.

Proof: [`docs/Project/thinking-mode.md`](docs/Project/thinking-mode.md).
Runnable: `scripts/demo_connectivity.py` → `curl /api/alerts/{id}`.

### 2. Multimodal Pukaar AI on evidence frames

`backend/src/Pukaar/adapters/image_assessment.py` feeds evidence
frames to Pukaar AI (E4B → E2B auto-fallback) with a 3-exemplar Spanish few-shot
prompt. The Site Detail UI overlays Pukaar AI's description on the frame.

Proof: [`docs/Project/multimodal-comparison.md`](docs/Project/multimodal-comparison.md).

### 3. Rioplatense linguistic specialization

82-example corpus across 6 provinces. `Pukaar AIFewShotTextStructurer` with 12
exemplars. Benchmark: rules 45% → few-shot ~80% on held-out test split.

Proof: [`docs/Project/rioplatense_eval.md`](docs/Project/rioplatense_eval.md).

### 4. Connectivity-loss resilience (narrative spine)

`scripts/demo_connectivity.py` runs: online report → offline → queued report →
local node analysis → **audible siren** → online → queue drains. Under 90
seconds, reproducible.

Web UI: red `SIN CONECTIVIDAD` banner during offline; green `Sincronizado`
flash on drain.

### 5. SINAGIR compatibility

`POST /api/alerts/{id}/export-sinagir` returns a schema-tagged, documented
payload. Field-by-field mapping published.

Proof: [`docs/Project/sinagir-mapping.md`](docs/Project/sinagir-mapping.md).

### 6. On-device Android path (LiteRT-adjacent)

`android/.../data/Pukaar AIOnDevice.kt` wraps MediaPipe LLM Inference for Pukaar AI
`.task` files. Volunteer report structuring runs fully on-device with no
silent backend fallback.

Proof: [`docs/Project/android_pukaar-ai.md`](docs/Project/android_pukaar-ai.md).

## Pitch video script (2.5 min)

0:00–0:15 — context: Argentina's Litoral flood problem; Bahía Blanca 2025
alert-vs-risk gap ([Meteored article](https://www.meteored.com.ar/noticias/actualidad/no-es-lo-mismo-alerta-meteorologica-que-alerta-de-riesgo-local-la-diferencia-puede-ser-cuestion-de-vida-o-muerte.html)).

0:15–0:45 — Android volunteer flow: photo + voice → fully on-device Pukaar AI
structuring. Show "Analizado con Pukaar AI en este dispositivo" chip.

0:45–1:15 — fixed-node analysis on the Silverado clip. Evidence frame +
Pukaar AI Spanish description overlay. Show that CV drives the score and Pukaar AI
only narrates.

1:15–1:45 — connectivity-loss live: wifi off, red banner, offline report
queued, node alert fires, **siren audible**, wifi on, queue drains.

1:45–2:10 — thinking-mode reasoning chain expanding on an alert card.

2:10–2:30 — SINAGIR mapping doc + Plan Nacional 2025-2029 alignment close.

## Reproduce the demo

```bash
./scripts/setup.sh
PYTHONPATH=backend/src python3 -m Pukaar.scripts.seed
./scripts/dev.sh            # starts Ollama + backend + frontend
python3 scripts/demo_connectivity.py
```

## Test suite

```bash
cd backend && PYTHONPATH=src pytest -q     # 27 tests
cd frontend && npm test && npm run build   # vitest + vite build
```

## Post-Project roadmap

See GitHub issue "Post-Project roadmap":
- Real LoRa ingestion (LoRaWAN gateway + payload decoder).
- Real SINAGIR API handshake once a provincial integrator is assigned.
- LoRA fine-tune on an expanded Litoral corpus (target 500+ examples).
- Physical device fleet: Snapdragon 7-gen + 8-gen benchmarks.
- Audio-first volunteer path (Pukaar AI 3n-style ASR, batch 30 s clips).
