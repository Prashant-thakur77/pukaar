# Timeline — Pukaar pitch (3:00 target, max 3:10)

Track: Pukaar Release — Global Resilience / LiteRT Prize.
Framing: **MVP demo, not benchmark video.** Public/simulated scenarios only.

| Block | Time        | Section            | Duration | Primary visual                                           | Audio source        |
| ----- | ----------- | ------------------ | -------- | -------------------------------------------------------- | ------------------- |
| B01   | 0:00–0:12   | Hook               | 12 s     | Cinematic river / storm B-roll, no people close          | Music swell + amb.  |
| B02   | 0:12–0:30   | Problem statement  | 18 s     | prashant talking head + light Litoral B-roll cutaway        | prashant VO            |
| B03   | 0:30–0:55   | Pukaar volunteer    | 25 s     | Smartphone PWA mock, Spanish voice→JSON transition       | prashant VO + tap SFX  |
| B04   | 0:55–1:30   | Pukaar fixed node| 35 s     | Dashboard `node-analysis`, curated frames, Pukaar AI output  | prashant VO            |
| B05   | 1:30–2:00   | Connectivity loss  | 30 s     | Live screencast: wifi off → queued → siren → wifi on     | prashant VO + siren    |
| B06   | 2:00–2:25   | Audit trail        | 25 s     | Reasoning chain panel + rule trace + evidence thumbs     | prashant VO            |
| B07   | 2:25–2:48   | SINAGIR + impact   | 23 s     | JSON export panel + Litoral map + Plan Nacional caption  | prashant VO            |
| B08   | 2:48–3:00   | Close              | 12 s     | Logo card + repo URL + roadmap line                      | Music tail          |

## Cut style

- B01, B08: full-bleed cinematic, no UI.
- B02, B05: human (talking head or hand on device), grounded.
- B03, B04, B06, B07: dashboard / HTML scenes rendered via HyperFrames; held no longer than 6 s before motion.
- All UI-heavy blocks carry a **persistent corner watermark**: `MVP DEMO — public/simulated scenario`.

## Beat-level cues

- 0:00–0:03: title card fade-in `Pukaar` then dissolve to river.
- 0:25: cut to Pukaar mock on the word "volunteer".
- 0:42: JSON appears on the same line that VO says "structures that into evidence".
- 1:08: dashboard pulses red on `assessment_level: red`.
- 1:35: phone modem icon flips to airplane in same frame as `NETWORK OFFLINE` banner.
- 1:48: siren beep; on-screen: `local alert (no cloud)`.
- 1:58: `sync complete` toast with green check.
- 2:12: highlight rule trace one line at a time.
- 2:32: zoom on `sinagir_payload.json`.
- 2:55: end card holds 5 s before fade.

## Production order

1. Render HyperFrames scenes (B03, B04, B06, B07 panels).
2. Capture Playwright/FFmpeg screencast (B05 hero moment from real frontend).
3. Record talking head (B02 plus pickups for B03/B05/B07 if needed).
4. Drop B-roll (B01, B08 transitions).
5. Hand the `raw/` folder to `video-use` to assemble `final.mp4` per `edit/project.md`.
