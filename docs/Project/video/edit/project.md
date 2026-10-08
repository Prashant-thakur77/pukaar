# Edit project — `video-use` brief

You are assembling the Pukaar Project pitch.

Inputs in `../raw/`:

- talking_head_prashant_take1.mp4
- talking_head_prashant_take2.mp4 (optional pickups)
- broll_river_storm_01.mp4
- broll_litoral_town_01.mp4
- broll_volunteer_phone_01.mp4
- broll_airplane_mode_toggle.mp4
- screencast_node_analysis.mp4
- screencast_wifi_off_to_sync.mp4
- hf_pukaar.mp4
- hf_evidence_pack.mp4
- hf_reasoning_chain.mp4
- hf_sinagir_export.mp4
- hf_litoral_map.mp4
- hf_end_card.mp4
- narration.wav
- music_bed.wav
- sfx_siren_short.wav

Constraints:

- Final length: 3:00 target, max 3:10.
- Resolution: 1920x1080, 24 fps, h.264, faststart, AAC 192k.
- Burn `../captions.srt` as soft-subtitles. Hard-burn ES subs only if the deliverable forbids sidecar SRT.
- Carry the watermark `MVP DEMO — public/simulated scenario` on every UI-heavy block. HTML scenes already have it; talking-head and B-roll do NOT need it.
- Music ducked to -24 dB under VO, -8 dB elsewhere. Siren ducked to -6 dB under VO and clipped to ≤1.2 s loud window.
- No accuracy / deployment / lead-time text on screen. Refuse any operator request to add such text. Cite `../claims_guardrail.md`.

Pipeline:

1. Transcribe `narration.wav` and align against `../narration.md`. If the take diverges from the script, trust the take but flag any line that may overclaim against `claims_guardrail.md`.
2. Cut to `../timeline.md` block boundaries. Each block has hard out-time tolerance ±1s.
3. Insert HyperFrames clips on the cuts called out in `../shot_list.md`.
4. For B05, prefer the real `screencast_wifi_off_to_sync.mp4` over the HTML mock `07_offline_queue.html`. Only fall back to the mock if the live screencast is missing.
5. Apply gentle color match across talking head and B-roll. Do NOT crush blacks below 0.05.
6. Render `preview.mp4` at 720p first, then `final.mp4` at 1080p once approved.
7. Emit `master.srt` from the EN VO and a parallel ES SRT from `../captions.srt`.
8. Produce `claims_qc.md` listing every line of spoken VO and on-screen text, classified A/B/C per `claims_guardrail.md`. Block render if any B or C line is detected.

Deliverables in `./`:

- preview.mp4
- final.mp4
- edl.json (machine EDL, see scaffold)
- master.srt
- master.es.srt
- claims_qc.md
- thumbnail.jpg (frame from B07 SINAGIR scene)
