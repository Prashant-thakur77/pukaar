# Shot list — assets needed for `final.mp4`

Each row maps to a clip filename in `raw/`. `video-use` consumes these.

| ID  | Block | Source                      | Filename                                | Notes                                                                                |
| --- | ----- | --------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------ |
| S01 | B01   | Generated/stock B-roll      | `raw/broll_river_storm_01.mp4`          | 12 s, river under stormy sky, no text, no people close-up.                           |
| S02 | B02   | Talking head                | `raw/talking_head_prashant_take1.mp4`      | 18–25 s, neutral wall, soft side light, lavalier mic.                                |
| S03 | B02   | B-roll cutaway              | `raw/broll_litoral_town_01.mp4`         | 5 s wedge, riverside town, daytime, calm, used as cutaway under VO.                  |
| S04 | B03   | HyperFrames scene           | `raw/hf_pukaar.mp4`                      | Render of `ui_scenes/02_volunteer_report_input.html` -> `03_volunteer_report_json`.   |
| S05 | B03   | Phone-in-hand B-roll        | `raw/broll_volunteer_phone_01.mp4`      | 6 s, hand holding phone in light rain, no readable UI on device.                     |
| S06 | B04   | Playwright screencast       | `raw/screencast_node_analysis.mp4`      | Real frontend node-analysis page on Silverado demo clip, narrated cursor moves.      |
| S07 | B04   | HyperFrames scene           | `raw/hf_evidence_pack.mp4`              | Render of `ui_scenes/04_fixed_node_evidence_pack.html` with timeline animation.      |
| S08 | B05   | Playwright + phone capture  | `raw/screencast_wifi_off_to_sync.mp4`   | The hero moment. Real demo, not mock, end-to-end.                                    |
| S09 | B05   | Phone close-up              | `raw/broll_airplane_mode_toggle.mp4`    | 3 s, finger flips airplane-mode toggle. Use as cutaway.                              |
| S10 | B05   | Audio                       | `raw/sfx_siren_short.wav`               | Short, non-aggressive emergency tone, ducked under VO.                               |
| S11 | B06   | HyperFrames scene           | `raw/hf_reasoning_chain.mp4`            | Render of `ui_scenes/05_alert_reasoning_chain.html`, lines reveal sequentially.      |
| S12 | B07   | HyperFrames scene           | `raw/hf_sinagir_export.mp4`             | Render of `ui_scenes/06_sinagir_export.html`, JSON unfolds, "EXPORT" pulse.          |
| S13 | B07   | HyperFrames map             | `raw/hf_litoral_map.mp4`                | Argentina → Litoral zoom with node markers and Plan Nacional caption strip.          |
| S14 | B08   | End card                    | `raw/hf_end_card.mp4`                   | Logo, repo URL, MVP-roadmap line, music tail.                                        |
| A01 | All   | Music bed                   | `raw/music_bed.wav`                     | Sober, low-string-pad, no melodic hooks. Ducked under VO.                            |
| A02 | All   | Narration master            | `raw/narration.wav`                     | Final VO take, EN. ES subtitles burned later.                                        |

## Asset acceptance checks

- All UI captures show the watermark `MVP DEMO — public/simulated scenario` in the bottom-right.
- No real PII in any volunteer report (use the canned Rioplatense line).
- No municipal logos visible in talking-head wall.
- Siren in S10 is short — under 1.2 s loud — so VO stays intelligible.
- No on-screen accuracy or "X% better" text anywhere.
