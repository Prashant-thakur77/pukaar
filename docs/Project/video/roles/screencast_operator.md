# screencast_operator.md

Owns reproducible product screencasts with Playwright and FFmpeg.

## Inputs

- `../DESIGN.md`
- `../timeline.md`
- `../../../demo-script.md`
- `../../../../scripts/demo_connectivity.py`
- `../scripts/capture_demo_connectivity.py`

## Responsibilities

- Start backend/frontend/demo data.
- Capture B05 wifi off -> queue -> local alert -> sync flow.
- Capture dashboard/node-analysis proof if available.
- Keep notifications, personal data, terminals, and unrelated browser tabs out of frame.

## Preferred Command Path

```bash
./scripts/setup.sh
PYTHONPATH=backend/src python3 -m Pukaar.scripts.seed
./scripts/dev.sh
python3 docs/Project/video/scripts/capture_demo_connectivity.py
```

## Outputs

- `../raw/screencast_wifi_off_to_sync.mp4`
- `../raw/screencast_node_analysis.mp4` if available
- Capture notes in `../handoffs/03_scene_manifest.json`

## Done

- Screencast shows real UI state changes.
- CAP/export/action-guard evidence is visible or covered by a HyperFrames fallback.
- Audio is either clean or intentionally muted for edit.
