# DESIGN.md - Pukaar + Pukaar video contract

Single visual and editorial contract for all video agents. If another brief conflicts with this file, this file wins.

## Positioning

- Format: 3-minute Project pitch video.
- Tone: serious emergency-response documentary, not startup hype.
- Claim posture: MVP demo on public and simulated scenarios. No fake metrics, no fake deployment, no fake validation.
- Core line: "When connectivity fails, a local Pukaar AI-powered flood warning node can still watch, reason, alert, and sync later."

## Visual System

- Base: dark operational UI, high contrast, grounded field footage.
- Palette:
  - Background: `#071114`, `#0b161a`, `#101820`
  - Text: `#e6f2ef`, `#9fb5b0`
  - Teal signal: `#28d7c4`
  - Amber caution: `#ffb84d`
  - Red alert: `#ff4d5a`
  - Map/river blue: `#4aa3ff`
- Typography: system sans or Inter-like sans. No decorative fonts.
- Layout: dense operational panels, maps, JSON, evidence thumbnails, rule traces. Avoid marketing cards.
- Watermark: every UI-heavy block must show `MVP DEMO - public/simulated scenario`.

## Motion Language

- Use HyperFrames for programmatic motion graphics.
- Preferred patterns:
  - JSON unfold line by line.
  - Alert trail with one highlighted state at a time.
  - Map pulse from fixed node to backend to SINAGIR export.
  - Wifi off -> local queue -> siren -> sync complete.
  - Evidence frames slide in as a temporal pack.
- Timing: hold every important text state long enough to read. No flash cuts for claims or disclaimers.
- Transitions: clean cuts, short dissolves, dashboard reveals. No sci-fi glitch language.

## Asset Rules

- Real incident footage may be used only as contextual B-roll with visible credit.
- AI-generated B-roll from Veo/Flow/Nano Banana is allowed only as illustrative support, never as evidence of a real flood.
- Generated stills must avoid identifiable real people, agency logos, or fabricated emergency scenes that look like documentary proof.
- Playwright screencasts are the preferred proof layer for product behavior.
- HyperFrames scenes are the preferred explanation layer for architecture, data flow, CAP/SINAGIR, and alert reasoning.

## Audio And Captions

- Narration stays intelligible above all other audio.
- Music: duck under VO, never drive the edit.
- Siren: short, loud enough to understand local actuation, never masks narration.
- STT default: ElevenLabs Scribe v2 if API key is available.
- Offline fallback: `whisper-timestamped`.
- Subtitle outputs:
  - `docs/Project/video/edit/master.srt`
  - `docs/Project/video/edit/master.es.srt`
  - `docs/Project/video/handoffs/05_subtitles.ass` if burned subtitles are needed.

## Claims Rules

- Source of truth: `claims_guardrail.md`.
- Allowed: architecture, MVP behavior, public/simulated demo status, roadmap.
- Forbidden in video: accuracy percentages, lead-time numbers, real deployment, partner operation, real local validation.
- Any metric must be either shown as measured in repo artifacts or labeled clearly as pending validation. Do not invent numbers.

## Deliverable Gates

- `edit/preview.mp4`: rough cut for QC.
- `edit/final.mp4`: 1080p H.264, faststart.
- `edit/edl.json`: final edit decisions.
- `edit/claims_qc.md`: all spoken/on-screen lines class A.
- `edit/thumbnail.jpg`: frame from B07 SINAGIR/map sequence.
- Final length target: 3:00. Max: 3:10 unless Project rules say otherwise.
