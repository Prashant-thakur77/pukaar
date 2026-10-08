# renderer_hyperframes.md

Owns programmatic motion graphics renders.

## Inputs

- `../DESIGN.md`
- `../hyperframes/`
- `../ui_scenes/`
- `../timeline.md`

## Responsibilities

- Lint HyperFrames projects before render.
- Render all `hf_*.mp4` assets into `../raw/`.
- Verify scene duration, text readability, watermark presence, and nonblank frames.
- Keep motion factual: maps, architecture, JSON, alert trails, and sync states.

## Commands

```bash
python3 docs/Project/video/scripts/check_hyperframes.py
for p in title_card pukaar evidence_pack reasoning_chain sinagir_export end_card litoral_map; do
  (cd docs/Project/video/hyperframes/$p && npx hyperframes lint)
done
for p in title_card pukaar evidence_pack reasoning_chain sinagir_export end_card litoral_map; do
  (cd docs/Project/video/hyperframes/$p && npx hyperframes render --quality high --fps 30 --output ../../raw/hf_${p}.mp4)
done
```

## Outputs

- `../raw/hf_title_card.mp4`
- `../raw/hf_pukaar.mp4`
- `../raw/hf_evidence_pack.mp4`
- `../raw/hf_reasoning_chain.mp4`
- `../raw/hf_sinagir_export.mp4`
- `../raw/hf_litoral_map.mp4`
- `../raw/hf_end_card.mp4`

## Done

- Renders exist and match `../edit/edl.json` names or the EDL is updated.
- QC notes are captured in `../handoffs/03_scene_manifest.json`.
