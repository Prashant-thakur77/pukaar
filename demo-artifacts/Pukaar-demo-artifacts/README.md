# Pukaar — Demo Artifacts

Reproducible demo package for the Pukaar Pukaar Release submission.

The production deployment runs on a Raspberry Pi 4/5 camera node plus the Pukaar
Android app. This package lets a judge verify the full alerting pipeline
**without** owning the physical hardware: captured node inputs, citizen audio
reports, telemetry logs, model and runtime configuration, expected outputs, and
demo builds for the dashboard and mobile app.

## Contents

```
Pukaar-demo-artifacts/
  README.md                  - this file
  DEMO.md                    - step-by-step reproduction guide
  manifest.json              - machine-readable index of every artifact

  inputs/                    - what the Raspberry Pi node / Pukaar app captured
    video/                   - water-level evidence (nominal / warning / critical)
    audio/                   - resident voice reports
    reports/                 - .txt transcripts (skip STT if needed)

  outputs/                   - what the system produced from those inputs
    logs/                    - JSONL telemetry from each node run
    alerts/                  - final alert payloads
    screenshots/             - dashboard + mobile UI evidence

  app/                       - installable demo builds (optional)
    pukaar-demo.apk           - Android Pukaar build (demo mode)
    pukaar-dashboard-demo.zip - static dashboard build

  config/                    - everything needed to prove the run is real
    model_config.json        - Pukaar AI three-tier model setup (E4B node / E2B mobile / 26B-A4B central)
    thresholds.json          - water-level / severity thresholds
    runtime_config.yaml      - node + backend runtime config
    lite_rt_config.json      - on-device LiteRT config
    prompt_templates.md      - exact prompts used by Pukaar / Pukaar

  eval/                      - reproducibility evidence
    expected_outputs.json    - canonical outputs per case
    replay_results.json      - what this package's replay produced
```

## How to verify the demo

See `DEMO.md`. Two paths:

- **Option A — replay without hardware**: run the Pukaar Notebook linked from
  the submission. It loads the files in `inputs/` and produces the artifacts
  shown in `outputs/`.
- **Option B — real Raspberry Pi deployment**: clone the repo, follow the
  hardware deployment section.

## Notes

- Pukaar AI weights are **not** bundled. The system runs three Pukaar AI variants,
  one per tier (see `config/model_config.json`):
  - `google/pukaar-model-4b` on the Pukaar Raspberry Pi camera node (LiteRT, int4)
  - `google/pukaar-model-2b` on the Pukaar Android app (LiteRT, int4)
  - `google/pukaar-model-26b` on the central server (Ollama, q4_K_M)
  The package ships configuration and prompts only.
- All inputs are real captures from the Pukaar node and Pukaar app, not
  synthetic. Filenames map 1:1 to entries in `manifest.json`.
