# Pukaar alarm-layer firmware

Firmware for the hardware alarm layer: the village siren node first, with the gauge v3, rain
node, pradhan box and LoRa relay logic already in the shared library.

**Status: untested on hardware.** Nothing here has run on a board, a bench kit or a mast. What is
verified:

- the shared logic runs in host unit tests (`pio test -e native`), including every golden vector
  from the backend's canonical codec;
- the siren images compile for the ESP32-S3 (`siren_node`, `siren_node_sim`).

Every pin, relay, current reading, radio setting and timing still has to be checked on a bench
before a horn goes on a mast. This is the same standard as the gauge sketches in
[`docs/hardware`](../docs/hardware/README.md).

## Layout

```
firmware/
  platformio.ini             envs: siren_node, siren_node_sim, native
  schema/devices.yaml        the one source for wire values: frame types, levels, patterns, events, reasons, limits
  tools/gen_schema.py        devices.yaml -> lib/pukaar_common/schema.h (`--check` in CI)
  lib/pukaar_common/         all the logic, plain C/C++, host-tested
    pkr_crypto  SHA-256, HMAC, HKDF (the device-key derivation), CRC-32
    pkr_codec   hex, base64url, Crockford base32, base36
    pkr_command signed shadow commands; the compact LoRa command (SIREN_CMD_WRAPPED)
    pkr_frame   the LoRa frame, payloads, airtime
    pkr_sms     the signed SMS
    pkr_guard   command acceptance (the twin of the backend's siren_model.CommandVerifier), "verified"
    pkr_lora    frame receive checks (FrameVerifier's order), signing, the duty-cycle-aware link
    pkr_store   key-value store, frame counters (receive: written through, restored exactly; send: +16 on boot), the key ring
    pkr_pattern alarm patterns W1 C1 A1 T1 D1 B1 and the player (caps, 10-minute limit, voice slots)
    pkr_siren   the siren node's state machine (commands, verification, priority, autonomy, manual, tests)
    pkr_outbox  the durable outbox (two queues, 4 KB segments, CRC, atomic meta, backoff, breaker)
    pkr_box     pradhan box (key + 3 s hold), LoRa relay, event log, OTA job gate
    pkr_gauge   gauge v3 decisions (2 of 3, blind zone, sanity, bridge beacon, burst)
    pkr_rain    tipping-bucket counter (debounce, bounce, wrap), plain C for the ULP
    pkr_dutycycle  the G.S.R. 853(E) airtime budget
    pkr_wire    SEN0676 Modbus, DFPlayer and E22 byte codecs
    pkr_test_keys.h  TEST ONLY keys for the tests and the simulator
  lib/pukaar_hal/            thin ESP32 drivers: NVS, LittleFS, E22 UART, PPP + TLS + MQTT, the serial simulator link
  src/siren_node/main.cpp    the siren node (and, with PUKAAR_SIM, its Wokwi build)
  test/native/test_*/        Unity suites (crypto, protocol, siren, pattern, outbox, sensors, box, vectors)
  test/vectors/              protocol_vectors.json comes from the backend (python -m Pukaar.scripts.protocol_vectors)
```

## Build and test

```
python -m venv .venv && .venv/bin/pip install platformio==6.2.0 pyyaml==6.0.3
.venv/bin/pio test -e native              # host tests; no board needed
.venv/bin/pio run -e siren_node -j 2       # the device image
.venv/bin/pio run -e siren_node_sim -j 2   # the simulator image (TEST ONLY keys)
.venv/bin/python tools/gen_schema.py       # after editing schema/devices.yaml
```

The ESP32 envs use arduino-esp32 3.3 (ESP-IDF 5.5), as the gauge v2 sketch does. They are pinned
to a pioarduino platform release: the official `espressif32` 6.x platform the spec names still
ships arduino-esp32 2.x. CI (`.github/workflows/firmware.yml`) checks the header, runs the native
tests and builds both siren envs on every firmware change, and nightly.

## The protocol: the backend's codec is the contract

The device matches `backend/src/Pukaar/services/devices/protocol.py` and `siren_model.py` byte for
byte; `test_vectors` checks every vector, including the sequenced acceptance matrix, the boot
bump, the frame rejections and the SMS checks. Where these differ from the spec, the code wins:

- Device keys are HKDF-SHA256(root, salt `pukaar-device-root-v1`, info `pukaar-dev|<device>|<kid>`)
  (the spec's KMS GenerateMac is the documented production upgrade).
- In the canonical command string every empty string field is `-`. The receiver always signs
  over its own device id.
- The compact LoRa command is one frame. Its inner 16-byte signature is the siren's key over
  `PKR1C|<device>|<20-byte body>`; its level is a command level (warning 2 ... drill 6).
- Replay is checked per path (mqtt, sms and lora each have a counter), with the last 32 ids.
  Receive counters (commands, and frames per sender) are written through to NVS when a message
  is accepted, before the device acts on it, and restored exactly on boot. A siren that loses
  power in a flood therefore takes its gauge's very next GAUGE_ALARM. Only send counters (a
  device's own frame ctr, batched) skip 16 on boot so they are never reused. Without a clock, only
  the upper bound is checked: exp must be within 12 h of the last known time.
- The SMS device id is matched exactly. Words are separated by single spaces.
- Reason names are the model's: `wrong_kid`, `sender`, `malformed`, `unknown_src`, `role`,
  `bad_mac` and `clock_skew`.
- A silent test is the command T1 at volume 0. It plays into the dummy load at any hour and is
  never audible.

## Siren node pin map (ESP32-S3 DevKitC bench kit; check against the T-SIM7670G-S3)

| GPIO | Use | GPIO | Use |
|---|---|---|---|
| 1, 2, 3 | INMP441 SCK, WS, SD | 15 | LEDC fallback tone -> RC low-pass -> amp IN |
| 4 | K2 horns (on) / dummy load (off) | 16 | HOLD button to GND |
| 5 | K1 24 V boost + amp, via the hardware one-shot | 17, 21 | key switch W, C to GND |
| 6 | K3 12 V electronic siren, via the one-shot | 18 | door switch (open = tamper) |
| 7 | K4 strobe | 38, 39 | E22 M0, M1 |
| 8, 9 | I2C: INA226 0x40 amp, 0x41 siren, 0x44 battery | 40 | one-shot re-trigger pulse |
| 10-13 | modem PWR, TX, RX, RST | 41, 42 | DFPlayer RX, TX |
| 14 | status LED | 46 | TPL5010 DONE (strapping pin: 10k pull-down) |
| | | 47, 48 | E22 RXD, TXD |

Every relay input is pulled down, so a reset means silence. The firmware feeds the 555
one-shots, so a hang cannot leave the siren blaring. DFPlayer SD layout: folder `01` holds the
clips (001 warning, 002 critical, 003 auto, 004 all-clear, 005 test, 006 drill, 007 drill end);
folder `02` holds the tones (001 650 Hz, 002 the 500-1050 Hz sweep, 003 900 Hz, 004 1200 Hz).

Provisioning writes an NVS namespace `pkr-keys`:

- `dev` and `addr`;
- `self<kid>` (32 bytes) and `kid`;
- `snd<n>` (address, kid, role bits, device id, key);
- `sms_salt` and `sms_to0..3`.

It also writes LittleFS `/certs/{ca,device,key}.pem`. The provisioning script for this is not
written yet.

## The simulator build (Wokwi, coming next)

`siren_node_sim` speaks lines on the serial port instead of a modem and a radio.

- In: `>CMD {json}`, `>CFG {json}`, `>LORA <b64>`, `>SMS <from> <text>`, `>TIME <unix>`,
  `>CLOUD up|down`, `>FAULT amp_open|mic_dead|none`, `>TEST silent`, `>SOC <n>`, `>KEY off|w|c`,
  `>HOLD 0|1`.
- Out: `READY`, `<EVT {json}`, `<LORA <b64>`, `<SMS <to> <text>`, `<PUB <topic> <bytes>`,
  `<CLIP <role>`.

The `diagram.json`, `wokwi.toml` and scenarios of spec 8.2 are the next pass. So is the optional
CI job that runs them when a `WOKWI_CLI_TOKEN` secret exists.

## Open items found while building it

- **E22 channel raster.** The E22-900T22S UART module tunes to 850.125 MHz + n MHz, so the
  spec's 865.4025 and 865.985 MHz are not reachable: CH 15 (865.125 MHz) and CH 16 are nearest.
  It also hides SF and bandwidth behind an "air data rate". Use a bare SX1262 (RadioLib) to hit
  the radio plan exactly, and bench-check that E22 modules and the relay's bare SX1262 can hear
  each other at all.
- **Sync word.** The spec's 0x34 is the LoRaWAN public word; schema.h uses 0x12 (private).
- **Airtime.** A 32-byte frame at SF10/125 kHz is 453 ms, not about 370 ms (the test checks the
  formula against the known 46.3 ms LoRaWAN figure). The 90 s budget is about 198 such frames
  an hour.
- **Box events.** Buttons A and B (water rising, mil gaya) are `report` and `ack` events, which
  the backend's `EVENT_CODES` does not have yet. The box's `relay_cmd` (forwarding a compact
  command over LoRa) has no backend format yet.
- **Still to build:**
  - the gauge v3, rain node, pradhan box and relay images (their logic is in the library and
    tested);
  - the ULP-RISC-V tip counter (the Arduino build would count by waking on each tip);
  - OTA download and rollback (the job gate is tested; the download is not written);
  - Wokwi.

## Sources and licences

- The durable outbox follows FloodNet's node-red-contrib-durable-outbox (MIT): dedupe, PUBACK
  before the tail moves, full-jitter backoff and the circuit breaker. The code is new.
- FloodNet's sensor and gateway firmware (CC BY-NC-SA) informed ideas only (fail-loud sensor
  signatures, power beacons); nothing is copied.
- The SEN0676 Modbus codec is clean-room from the public register map (the third-party library
  has no licence). The DFPlayer frame is written from the published protocol.
- The buffer and the battery tiers follow EnviroDIY ModularSensors' patterns (BSD-3); the code is
  new.
- Libraries:
  - ArduinoJson (MIT);
  - 256dpi/arduino-mqtt (MIT);
  - Unity (MIT), for the tests;
  - arduino-esp32 (LGPL-2.1, linked as the framework).
- The date algorithm in `pkr_event.cpp` is Howard Hinnant's (public domain).
