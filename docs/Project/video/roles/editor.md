# editor.md

Owns preview and final video assembly.

## Inputs

- `../DESIGN.md`
- `../edit/project.md`
- `../edit/edl.json`
- `../raw/`
- `../captions.srt`
- `../claims_guardrail.md`

## Responsibilities

- Use `video-use` as the main edit agent when available.
- Follow EDL block boundaries and avoid timeline improvisation.
- Integrate HyperFrames, Playwright screencasts, talking head, B-roll, narration, subtitles, and credits.
- Export reproducible preview/final files with FFmpeg-compatible settings.

## Outputs

- `../edit/preview.mp4`
- `../edit/final.mp4`
- `../edit/edl.json`
- `../edit/master.srt`
- `../edit/master.es.srt`
- `../edit/thumbnail.jpg`

## Done

- Final length is 3:00 target, max 3:10.
- Credits include third-party footage and generated/illustrative assets where relevant.
- Audio is intelligible without headphones.
