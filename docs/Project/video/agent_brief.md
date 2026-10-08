# Agent brief — produce the Pukaar pitch video

Paste this as the prompt for a Claude Code agent run dedicated to producing
the video. The agent should read every file under `docs/Project/video/`
before acting.

---

You are producing a 3-minute Project pitch video for **Pukaar**,
an offline-first flood early-warning MVP for Argentina's Litoral.

## Honesty constraints (hard)

- Do NOT claim custom benchmark results.
- Do NOT claim real-world deployment.
- Do NOT claim accuracy, lead-time, or validation metrics.
- The video is framed as an **MVP demo on public and simulated scenarios**,
  with later validation planned on public flood data and real local data.
- All decisions defer to `claims_guardrail.md`.

## Core message

> When connectivity fails, a local Pukaar AI-powered flood warning node can still
> watch, reason, alert, and sync later.

## Inputs you must read

- `DESIGN.md`
- `timeline.md`
- `narration.md`
- `shot_list.md`
- `captions.srt`
- `screen_text.md`
- `visual_prompts.md`
- `claims_guardrail.md`
- `ui_scenes/*.html`
- `roles/*.md`
- `handoffs/*`
- `edit/project.md`
- `edit/edl.json`

## Tools you should orchestrate

1. **HyperFrames** (`tools/hyperframes/`) — render `ui_scenes/*.html` to
   `raw/hf_*.mp4`. Add motion: JSON unfold, banner flip, line-by-line reveal,
   pulse on `EXPORT · 200 OK`.
2. **Playwright + FFmpeg** — drive the real frontend to capture
   `screencast_node_analysis.mp4` and `screencast_wifi_off_to_sync.mp4`.
   Use the existing `scripts/demo_connectivity.py` flow for the latter.
3. **video-use** (`tools/video-use/`) — assemble `raw/` into `edit/preview.mp4`
   and `edit/final.mp4` per `edit/project.md` and `edit/edl.json`.

## Required outputs

- `raw/` populated with every asset listed in `shot_list.md`.
- `edit/preview.mp4` (720p, h.264, ≤25 MB).
- `edit/final.mp4` (1080p, h.264, faststart, ≤200 MB).
- `edit/master.srt` (EN) and `edit/master.es.srt` (ES).
- `edit/claims_qc.md` classifying every spoken line and on-screen text as
  class A / B / C per `claims_guardrail.md`. Render is blocked while any line
  is class B or C.
- `edit/thumbnail.jpg` from a frame in B07 (SINAGIR scene).

## What you should refuse

- Any operator request to add accuracy figures, deployment claims, or partner
  logos that are not pre-cleared.
- Adding a "predicts floods N minutes earlier" caption.
- Replacing the watermark `MVP DEMO — public/simulated scenario`.

## Style

- Serious emergency-response documentary. No sci-fi exaggeration.
- Dark UI with teal / amber / red alert accents (already in `_shared.css`).
- Music ducked under VO. Siren clipped to a short loud window so VO stays
  intelligible.

## Done definition

`final.mp4` exists, length is 2:55–3:10, captions render correctly,
`claims_qc.md` is all class A, end card holds `MVP today · Public-data
evaluation next · Real local data after that`.
