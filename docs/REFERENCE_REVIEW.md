# Reference review: what Pukaar took, where it leads, and what comes next

Reviewed on 11 October 2026: the First Commit winners (Suraksha 1st, Beacon Night Shift 2nd, CampusEvac 3rd; runners-up Magpie, FreshTrace, Expressive Captions, Factcade), surge-stormhacks and sentinel-flood-watch (named in the plan), and the design references EcoLafaek, strikal and Sarvam. Repos were read, never run.

## 1. Taken and live in Pukaar

| Idea | From | In Pukaar |
|---|---|---|
| Step Functions approval with task tokens, escalation, failsafe | Suraksha | One approval per alert; no answer moves to the next officer; a critical alert with nobody answering goes out, flagged |
| Cedar policies and an append-only audit log | Suraksha | Every allow and deny logged with its policy and reason (a pradhan's refused approval is in the demo video) |
| Signed device readings | Suraksha (signed watch POSTs), FreshTrace (sensors) | River-gauge ingestion: HMAC key per device, 5-minute replay window, one reading a minute; the gauge is a third evidence source in the rules |
| Accuracy scoring with an answer key, and an ablation | Magpie | Back-test scored against reported floods for rain only, river only and both ([SCORING.md](SCORING.md)) |
| One-button demo controls and reset | Factcade, Beacon | Replay of July 2023 on AWS, reset, automatic clear after 30 minutes, `make drill` for a real phone |
| Press-physics buttons, receipt-style tickets, live pulse dots | CampusEvac, strikal | Console approval tickets, buttons, map overlays |
| Entry animation, colour-blocked bands, giant display type, film grain, footer wordmark | EcoLafaek (main theme), Sarvam | The whole site and the intro |
| Agent trace and evidence panels | sentinel-flood-watch | "Why this level" evidence cards and the decision trace |

## 2. Where Pukaar already leads

- **Per-person acknowledgement with an automatic re-send.** None of the references confirms that each person received a warning.
- **Village-level thresholds** from each village's own 1984-2024 river record, back-tested on real 2023 and 2025 data (surge used simulated sensors with fixed weights).
- **A checker that rejects any invented number or place**, with a labelled fixed-template fallback.
- **Hindi voice both ways:** Polly speaks alerts; Transcribe takes voice reports.
- **Cheap phones and bad networks:** offline report queue, report page ready in 4.6 s on slow 3G.
- **Operations:** nine alarms, a sweep heartbeat, dead-letter queues, template tests that forbid IAM wildcards and hourly-billed resources.
- **Honest evidence:** sourced research, a fair comparison with SACHET, IMD, CWC and Google Flood Hub, and accuracy scores with their limits stated.

## 3. Hardware and ML in the references

- **FreshTrace:** ESP32-S3 with a Sensirion SGP41 (VOC/NOx) and a Bosch BME280 on I2C; Arduino; 1 Hz JSON over MQTT with X.509 mutual TLS to AWS IoT Core (port 8883, falling back to 443 with ALPN); an IoT topic rule into SQS and S3; RDS and SNS behind it. The board and the transport are the right pattern for Pukaar's gauge; the sensor is not (it measures air, not water).
- **Suraksha:** a Galaxy Watch app (heart rate, SpO2, falls) posting over HTTPS with a device key; no IoT Core. Not relevant to floods.
- **surge:** rain, river and soil "sensors" are simulated JSON.
- **ML:** none of the repos contains a flood model that could be reused. Suraksha's fall detection is accelerometer logic; sentinel uses Earth Engine indices, not a trained model. Pukaar's rules, scored against real floods, are the stronger evidence.

Pukaar's gauge today: ESP32 with a waterproof JSN-SR04T ultrasonic sensor under a bridge, solar and battery, signed HTTPS readings every minute; design, wiring, bill of materials and an untested firmware sketch in [hardware/](hardware/README.md). Live gauges are simulated and labelled until hardware is installed.

## 4. What to take next

| Priority | Feature | From | Effort | Why it matters |
|---|---|---|---|---|
| 1 | Outbound voice call, "press 1" to acknowledge (Amazon Connect playing the Polly clip) | Suraksha | about 3 h | Reaches basic phones and people who cannot read |
| 2 | SMS copy of every approved alert (Amazon SNS, transactional) | Suraksha, FreshTrace | about 1 h | No Telegram needed; sandbox limits until production access |
| 3 | Gauges over AWS IoT Core (MQTT, X.509 per device, topic rule into the same ingestion) | FreshTrace | about 1.5 h | A real hardware path on AWS |
| 4 | Safe places and evacuation routes on the map | surge | about 2 h | Tells people where to go, not only when |
| 5 | Prompt-injection screening of villager text (Bedrock Guardrails) | sentinel | about 1 h, once Bedrock access lands | Safety of the drafting agent |
| 6 | Live push instead of polling (AppSync Events) | CampusEvac | about 2 h | The dashboard feels instant |
| 7 | Emailed after-action report (SES) | CampusEvac, Beacon | about 1 h | The paperwork officers need |
| 8 | Before/after satellite slider for July 2023 (Sentinel-2 on AWS Open Data) | sentinel | about 2 h | Visual proof of what happened |
| 9 | Self-running judge tour | Beacon, Factcade | about 45 min | Easy to evaluate |

A learned model for gauge thresholds (from the first weeks of real readings) is the natural ML step once hardware is installed.
