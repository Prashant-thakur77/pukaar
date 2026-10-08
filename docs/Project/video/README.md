# `docs/Project/video/` — pitch video production

Self-contained production package for the Pukaar Release pitch.
Framing: **MVP demo, not benchmark video.**

## Production stack

- `DESIGN.md` is the single visual/editorial contract for all agents.
- HyperFrames renders programmatic motion graphics: maps, edge architecture,
  JSON panels, alert trail, and wifi off -> sync scenes.
- Playwright + FFmpeg captures reproducible product screencasts.
- Veo/Flow/Nano Banana assets are illustrative support only, never evidence.
- ElevenLabs Scribe v2 is the default timestamping path; `whisper-timestamped`
  is the offline fallback.
- `video-use` assembles `preview.mp4`, `final.mp4`, `edl.json`, subtitles, and
  QC notes.
- Brainiac QA is optional internal thumbnail/visual-dip review. Do not make
  neuroscience claims.
- FFmpeg owns reproducible exports, cuts, overlays, audio mix, and subtitle burn.

## Agent chain

Use bounded roles with checkable handoffs:

- `roles/director.md`
- `roles/visual_designer.md`
- `roles/renderer_hyperframes.md`
- `roles/screencast_operator.md`
- `roles/editor.md`
- `roles/claims_auditor.md`

Handoffs live in `handoffs/01_script.md` through `handoffs/06_claims_qc.md`.

## Layout

```
video/
├─ README.md                  # this file
├─ agent_brief.md             # drop-in prompt for orchestration agent
├─ timeline.md                # 3:00 timeline, block by block
├─ narration.md               # EN VO + ES subs
├─ shot_list.md               # raw assets needed
├─ captions.srt               # EN/ES sidecar subs
├─ screen_text.md             # every overlay / lower-third / watermark
├─ visual_prompts.md          # AI B-roll prompts + style rules
├─ claims_guardrail.md        # what we can / cannot claim
├─ ui_scenes/                 # static HTML mockups (1920x1080)
│   ├─ _shared.css
│   ├─ 01_title_card.html
│   ├─ 02_volunteer_report_input.html
│   ├─ 03_volunteer_report_json.html
│   ├─ 04_fixed_node_evidence_pack.html
│   ├─ 05_alert_reasoning_chain.html
│   ├─ 06_sinagir_export.html
│   └─ 07_offline_queue.html
├─ hyperframes/               # animated compositions (one per hf_*.mp4)
│   ├─ README.md
│   ├─ pukaar/
│   ├─ evidence_pack/
│   ├─ reasoning_chain/
│   └─ sinagir_export/
├─ scripts/
│   ├─ screenshot_scenes.py            # render each ui_scenes/*.html to PNG
│   ├─ build_hyperframes.py            # scaffold the 4 HF projects
│   ├─ check_hyperframes.py            # verify timelines + hero frames
│   └─ capture_demo_connectivity.py    # Playwright screencast of B05 flow
├─ raw/                       # captured / generated assets land here
└─ edit/
    ├─ project.md             # brief for `video-use` agent
    └─ edl.json               # machine EDL scaffold
```

## Generators

```bash
# 1. Sanity-check static mockups (PNG screenshots at 1920x1080)
python3 docs/Project/video/scripts/screenshot_scenes.py

# 2. Scaffold + verify HyperFrames projects
python3 docs/Project/video/scripts/build_hyperframes.py
python3 docs/Project/video/scripts/check_hyperframes.py

# 3. Lint each HF project (warnings → fix; errors → block render)
for p in title_card pukaar evidence_pack reasoning_chain sinagir_export end_card litoral_map; do
  (cd docs/Project/video/hyperframes/$p && npx hyperframes lint)
done

# 4. Render HF clips → docs/Project/video/raw/hf_*.mp4
for p in title_card pukaar evidence_pack reasoning_chain sinagir_export end_card litoral_map; do
  (cd docs/Project/video/hyperframes/$p \
     && npx hyperframes render --quality high --fps 30 \
        --output ../../raw/hf_${p}.mp4)
done

# 4b. TTS narration draft (Kokoro, ~310MB model first run)
#     Requires: pip install kokoro-onnx soundfile
python3 docs/Project/video/scripts/extract_narration.py
npx hyperframes tts docs/Project/video/raw/narration/_combined_en.txt \
  --voice af_nova \
  --output docs/Project/video/raw/narration.wav

# 5. Capture B05 screencast (requires backend + frontend running)
./scripts/setup.sh
PYTHONPATH=backend/src python3 -m Pukaar.scripts.seed
./scripts/dev.sh &        # backend :8000, frontend :5173
python3 docs/Project/video/scripts/capture_demo_connectivity.py
```

## Workflow (recommended)

1. **Render UI scenes via HyperFrames.** Each `ui_scenes/*.html` is a 1920x1080
   composition. Animate sub-elements (JSON unfold, banner flip, line-by-line
   reveal) inside HyperFrames; export to `raw/hf_*.mp4`.
2. **Capture live screencast.** Use Playwright + FFmpeg to drive the real
   frontend through:
   - `screencast_node_analysis.mp4` — node-analysis page on Silverado clip.
   - `screencast_wifi_off_to_sync.mp4` — `scripts/demo_connectivity.py` end to end.
3. **Record talking head and B-roll.** Per `shot_list.md`. Generate AI B-roll
   from `visual_prompts.md`.
4. **Hand the folder to `video-use`.** Pass `edit/project.md` as the brief and
   `edit/edl.json` as the EDL scaffold. The agent should produce
   `edit/preview.mp4` first, then `edit/final.mp4` once approved.
5. **Run claims QC.** The agent must emit `edit/claims_qc.md`. Block render if
   any line falls in class B or C of `claims_guardrail.md`.

## Honesty constraints (must hold across every artifact)

- No accuracy / lead-time / "deployed" claims.
- "MVP demo on public/simulated scenarios" appears at least once spoken and
  visibly on every UI-heavy block.
- Roadmap line on end card: `MVP today · Public-data evaluation next · Real local data after that`.

## Quick previews

Open any UI scene directly in a browser (1920x1080 viewport):

```bash
# from repo root
xdg-open docs/Project/video/ui_scenes/04_fixed_node_evidence_pack.html
```

Or render the whole set with HyperFrames once a composition file exists at
`tools/hyperframes/...` — see `tools/hyperframes/README.md`.
