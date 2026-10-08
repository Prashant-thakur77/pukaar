# Backend

FastAPI service for the Pukaar backend.

## Key services

- Pukaar AI-first fixed-camera multimodal assessment through `PukaarAssessmentEngine`
- temporal frame extraction with ffmpeg and Pillow optimization; no OpenCV in the Pukaar visual decision path
- persisted audit artifact packs for node analyses
- volunteer report parsing through a local Pukaar AI-compatible endpoint with rule fallback
- live hydromet snapshots from Open-Meteo
- fused alert scoring and SQLite sync replication
- bundled sample clip analysis for the USGS Silverado demo site

## Runtime defaults

The fixed Pukaar node now defaults to a Raspberry Pi 8 GB multimodal demo profile and an
embedded LiteRT-LM runtime:

Install system ffmpeg before running video capture or sample-clip analysis:

```bash
sudo apt-get install -y ffmpeg
```

```bash
PUKAAR_NODE_PROFILE=raspberry-pi-8gb-multimodal-demo
PUKAAR_DATA_DIR=/mnt/pukaar/data
PUKAAR_NODE_PROVIDER=litert
PUKAAR_NODE_MODEL_PATH=/mnt/pukaar/data/models/pukaar-model-2b.litertlm
PUKAAR_NODE_BACKEND=gpu
PUKAAR_NODE_MULTIMODAL_BACKEND=cpu
PUKAAR_NODE_MULTIMODAL_VISION_BACKEND=cpu
PUKAAR_NODE_CACHE_DIR=/mnt/pukaar/data/litert-cache
PUKAAR_NODE_ENABLE_SPECULATIVE_DECODING=true
PUKAAR_NODE_MAX_OUTPUT_TOKENS=1024
PUKAAR_NODE_MULTIMODAL_MAX_OUTPUT_TOKENS=2048
PUKAAR_MULTIMODAL_ENABLED=true
PUKAAR_MULTIMODAL_VERIFIER_ENABLED=false
PUKAAR_MULTIMODAL_MODEL=pukaar-model-2b.litertlm
PUKAAR_MULTIMODAL_MAX_FRAMES=1
PUKAAR_MULTIMODAL_FRAME_SAMPLE_SECONDS=300
PUKAAR_MULTIMODAL_IMAGE_MAX_SIDE=512
PUKAAR_MULTIMODAL_NUM_CTX=1024
PUKAAR_MAX_CURATED_FRAMES=1
PUKAAR_ARTIFACT_RETENTION_DAYS=3
```

For this profile, Pukaar prepares one optimized frame and attempts Pukaar AI
multimodal through LiteRT-LM. On the measured Raspberry Pi 5 setup, text and
reasoning smoke inference work with `gpu` and speculative
decoding enabled. The GPU vision path fails on the software WebGPU stack, but
one-image LiteRT multimodal smoke succeeds on the Pi with the CPU multimodal
engine and a 2048-token engine budget. With 1024 or fewer multimodal tokens the
image path can fail before inference because the vision patches exceed the
token cap.
The full sample-node endpoint was also exercised on the Pi and returned
`runner.mode=litert-multimodal-temporal`, `assessment_mode=pukaar-ai4-multimodal-v1`,
and `frames_analyzed=1`. Treat this endpoint result as the full Pukaar P1
evidence; treat `scripts/litert_smoke.py --image` as a one-image runtime smoke.

`/api/settings/runtime` exposes `p1_runtime_ready=true` when the LiteRT provider
and model are ready. That is a readiness signal, not proof that an Pukaar
analysis completed; use `runner.mode=litert-multimodal-temporal` from an
analysis response for jury-facing evidence.
The Raspberry Pi 16 GB / workstation profile
uses the same path with more frames and context through
`../scripts/run_pukaar_pi16_multimodal_prod.sh`. Pukaar is treated as a
separate user/volunteer node and is not sized by this Raspberry Pi fixed-node
profile.

For local development only, the fixed node can still use Ollama by setting
`PUKAAR_NODE_PROVIDER=ollama`. That path is explicit dev mode only; LiteRT
never falls back to Ollama automatically in production.

The Pi fixed-node scripts set `PUKAAR_LLM_ENABLED=false` by default so the
fixed Pukaar profile stays LiteRT-only. If the same backend is reused for a
full integrated Pukaar demo, explicitly re-enable and configure the development
Pukaar AI endpoint for report structuring; that does not change which Pukaar
node inference counts for P1.

Download the model once before the first real run:

```bash
export REPO_DIR=/opt/Pukaar
cd "$REPO_DIR/backend"
python -m pip install -e .[dev]
cd ..
python scripts/fetch_litert_model.py
python scripts/fetch_demo_assets.py
python scripts/litert_smoke.py
```

Use `../scripts/node_guard.py` on the Pi to record short clips from
`PUKAAR_CAMERA_SOURCE` and submit them to `/api/node/analyze` on a fixed
interval. The backend extracts the configured number of frames and sends them
directly to Pukaar AI multimodal.

## Core node-assessment contract

The fixed-node pipeline now produces a node assessment package centered on:

- `assessment_level`
- `assessment_score`
- `temporal_summary`
- `reasoning_summary`
- `reasoning_steps`
- `critical_evidence`
- `runner_name`
- `runner_mode`
- `fallback_used`
- audit artifact references

The external API surface remains stable; these fields are added to the existing node-analysis responses.

## Seed and tests

```bash
PYTHONPATH=src python -m Pukaar.scripts.seed
PYTHONPATH=src pytest -q
```
