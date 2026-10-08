# Pukaar + Pukaar Pukaar Live Demo Fixtures

This folder contains the small fixture pack for the public Pukaar hardware replay
notebook. It is intentionally safe to publish and does not connect judges to a
live Raspberry Pi.

Contents:

- `manifest.json`: fixture inventory and required CSV columns.
- `sensor_readings.csv`: synthetic-safe Pukaar node readings.
- `pukaar_reports.jsonl`: replay Pukaar citizen reports.
- `frames/*.jpg`: synthetic-safe visual states for nominal, vigilance, urgent,
  and critical water levels.
- `transcripts/report_01.txt`: transcript used instead of audio for reliability.
- `expected_outputs/alert_trace.json`: golden fixture output used by default.

Default notebook mode is `RUN_PUKAAR_AI = False`, so the notebook demonstrates the
same data contract, same prompt contract, and same alert orchestration without
running live LiteRT-LM or Pukaar AI inference. The real Raspberry Pi 5 + LiteRT-LM
evidence is documented separately in the repo docs, benchmark card, and demo
video artifacts.

The SINAGIR/CAP-shaped output in this fixture pack is a preview only. It is not
submitted to SINAGIR production endpoints.
