# Pukaar alarm-layer firmware

Firmware for the hardware alarm layer: the village siren node, the river gauge v3, the rain node,
the pradhan box and the LoRa relay.

**Status: untested on hardware.** Nothing here has run on a board, a bench kit or a mast. What is
verified: every image compiles for its board, the shared logic runs in host unit tests
(`pio test -e native`, 101 cases) including every golden vector from the backend's canonical codec,
and the provisioning tool derives keys exactly as the backend does.

| Image (env) | Board | Builds | Host-tested logic | Simulator | On hardware |
|---|---|---|---|---|---|
| siren node (`siren_node`) | ESP32-S3 (LilyGO T-SIM7670G-S3) | yes | SirenCore, guard, patterns, outbox | `siren_node_sim` + 10 Wokwi scenarios (not run) | untested |
| gauge v3 (`gauge_v3`) | ESP32-S3 | yes | gauge_plan, burst reduce, 2 of 3, rain counter and report | `gauge_v3_sim` + 3 Wokwi scenarios (not run) | untested |
| rain node (`rain_node`) | ESP32-S3 | yes | the gauge's, with no level sensor | (the gauge's) | untested |
| pradhan box (`pradhan_box`) | ESP32-S3 (LilyGO T-SIM7670G-S3) | yes | BoxCore, box shadow, relay_cmd, mesh batch | none | untested |
| LoRa relay (`lora_relay`) | Heltec WiFi LoRa 32 V3 | yes | RelayCore, box -> relay -> siren end to end | none | untested |
| ULP tip counter (`ulp_riscv/rain_counter.c`) | ESP32-S3 ULP-RISC-V | **no** (needs the ESP-IDF build) | pkr_ulp_rain_step, tick by tick | the gauge sim polls the same step | untested |

Every pin, relay, current reading, radio setting and timing still has to be checked on a bench
before a horn goes on a mast. This is the same standard as the gauge sketches in
[`docs/hardware`](../docs/hardware/README.md).

## Layout

```
firmware/
  platformio.ini             envs: siren_node, siren_node_sim, gauge_v3, gauge_v3_sim, rain_node,
                             pradhan_box, lora_relay, native
  schema/devices.yaml        the one source for wire values: frame types, levels, patterns, events, reasons, limits
  tools/gen_schema.py        devices.yaml -> lib/pukaar_common/schema.h (`--check` in CI)
  tools/provision.py         a device's id, keys, senders and settings -> its NVS partition (`--self-test` in CI)
  tools/gen_wokwi.py         the Wokwi scenarios, signed by the backend's codec with TEST ONLY keys (`--check` in CI)
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
    pkr_box     pradhan box (key + 3 s hold, the box shadow, relay_cmd, mesh batch), LoRa relay, event log, OTA job gate
    pkr_gauge   gauge v3 decisions (2 of 3, blind zone, sanity, bridge beacon, burst) and the v2 burst reduce
    pkr_node    provisioned settings, and the gauge's per-wake plan (record, LoRa frames, sleep)
    pkr_rain    tipping-bucket counter (debounce, bounce, wrap), the ULP state and the per-reading report; plain C
    pkr_dutycycle  the G.S.R. 853(E) airtime budget
    pkr_wire    SEN0676 Modbus, DFPlayer and E22 byte codecs
    pkr_test_keys.h  TEST ONLY keys for the tests and the simulator
  lib/pukaar_hal/            thin ESP32 drivers: NVS, LittleFS, E22 UART, PPP + TLS + MQTT, the serial simulator link
  src/siren_node/main.cpp    the siren node (and, with PUKAAR_SIM, its Wokwi build)
  src/gauge_v3/main.cpp      the gauge v3 (PUKAAR_SIM: its Wokwi build; PUKAAR_RAIN_NODE: the rain node)
  src/pradhan_box/main.cpp   the pradhan box
  src/lora_relay/main.cpp    the relay (RadioLib on the Heltec's SX1262)
  ulp_riscv/rain_counter.c   the ULP-RISC-V tip counter (not linked by these images: see below)
  wokwi/<target>/            diagram.json, wokwi.toml, scenarios/*.yaml (siren_node, gauge_v3)
  test/native/test_*/        Unity suites (crypto, protocol, siren, pattern, outbox, sensors, box, nodes, vectors)
  test/vectors/              protocol_vectors.json comes from the backend (python -m Pukaar.scripts.protocol_vectors)
```

## Build and test

```
python -m venv .venv && .venv/bin/pip install platformio==6.2.0 pyyaml==6.0.3
.venv/bin/pio test -e native               # host tests; no board needed
.venv/bin/pio run -e siren_node -j 2        # one device image; build them one at a time
.venv/bin/pio run -e gauge_v3_sim -j 2      # a simulator image (TEST ONLY keys)
.venv/bin/python tools/gen_schema.py       # after editing schema/devices.yaml
.venv/bin/python tools/gen_wokwi.py        # after a protocol change (CI checks it)
```

The ESP32 envs use arduino-esp32 3.3 (ESP-IDF 5.5), as the gauge v2 sketch does. They are pinned
to a pioarduino platform release: the official `espressif32` 6.x platform the spec names still
ships arduino-esp32 2.x. The toolchain is about 5.4 GB once unpacked: give `PLATFORMIO_CORE_DIR` a
real disk, not a small tmpfs. CI (`.github/workflows/firmware.yml`) checks the header, the Wokwi
scenarios and the provisioning tool, runs the native tests and builds every env on every firmware
change, and nightly; the Wokwi scenarios run only when the repository has a `WOKWI_CLI_TOKEN` secret.

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

The gauge, the box and the relay list their pins at the top of their `main.cpp`.

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

## Provisioning

`tools/provision.py` writes what `lib/pukaar_hal/hal_storage.cpp` reads:

- NVS namespace `pkr-keys`: `dev` and `addr`; `self<kid>` (32 bytes) and `kid`; `snd<n>` (a
  ProvisionedSender: address, kid, role bits, device id, key, 76 bytes); `sms_salt` and `sms_to0..3`;
- NVS namespace `pkr-cfg`: `cfg`, a JSON string (village, IoT endpoint, APN, thresholds, mm per tip,
  the downstream sirens; `lib/pukaar_common/pkr_node.h` has the shape).

It writes the esp-idf NVS CSV, turns it into a partition image with `esp-idf-nvs-partition-gen` and,
with `--port`, flashes it at 0x9000 (the NVS partition of `default_8MB.csv`). A real device's key and
each sender's key come from files, never the command line; `--test-only` derives from the public test
root and is refused for any id that does not end in `-sim`. The CSV and the image hold keys: delete
them once flashed. The MQTT certificate and key go to LittleFS `/certs/{ca,device,key}.pem`
(`pio run -t uploadfs` from a `data/` folder kept out of git). The gauge and the rain node read their
thresholds and downstream sirens from `cfg`: the gauge's IoT policy allows only its reading topics, so
it never asks for a config shadow.

## The gauge v3 and the rain node

One wake (`src/gauge_v3/main.cpp`; the decisions are `gauge_plan` in `pkr_node.cpp`):

1. a tip woke it: count it (`pkr_ulp_rain_tip`), wait for the reed to open, and sleep again unless a
   reading is due or the minute reached the burst rate;
2. a burst of 9 samples (SEN0676 radar or JSN-SR04T), reduced as v2 does (`pkr_burst_reduce`);
3. the rain since the last reading (`pkr_rain_take_report`: window, busiest minute, shortest gap,
   bounce, `rain_err`; a cold boot that lost the count sets counter_reset and reports no rain for it);
4. `gauge_plan`: 2 of the last 3 good readings at Critical and sane (a normal reading within 24 h, the
   blind zone not hit in 2 of 3) sends GAUGE_ALARM to each downstream siren; GAUGE_STATUS goes out every
   wake with the 15-minute rain; rain alone never alarms (the siren's autonomy is the river's) but at
   2 tips a minute it moves the gauge to the 60 s cadence, as a Critical does;
5. the bridge beacon (B1 chirps and the strobe) while v2's 3-of-3 latch holds;
6. PPP and MQTT: the reading live on `/reading`; if the link fails it goes to the outbox as
   `buffered: true` and later out in `{"readings": [...]}` batches;
7. the NVS mirror of the tip count, the E22 to its own sleep mode, deep sleep with the timer and the tip.

The rain node is the same image with `-DPUKAAR_RAIN_NODE=1` (no level sensor, `rain-<village>-NN`,
the gauge topic, which the backend routes to observed rain).

**The ULP tip counter is written but not linked.** The spec counts tips on the ULP-RISC-V during deep
sleep. `ulp_riscv/rain_counter.c` is that program: one `pkr_ulp_rain_step` per 5 ms run on state in RTC
memory, asking for the main CPU when a minute reaches the burst rate. The step function is host-tested
tick by tick, and the gauge simulator polls the same function every 5 ms. But a ULP program is linked
into an image by the ESP-IDF build (`ulp_embed_binary`), which the PlatformIO Arduino build does not
have, so the `gauge_v3` image wakes the main CPU on each tip instead. The file's header has the
ESP-IDF build steps.

## The pradhan box and the relay

The box (`src/pradhan_box/main.cpp`) runs BoxCore in its own task (a blocking modem call never delays
the 3 s hold or the 2 s ACK wait); its events reach the outbox through a queue. It applies its `siren`
shadow (level LEDs, the clip on the I2S amp, a chime only at Watch, no replay on a reconnect's shadow
get), sends each `relay_cmd` once before its exp, and batches every frame it hears to
`pukaar/mesh/<village>/<box>/relay`. Clips are 16 kHz 16-bit mono WAV files on LittleFS
`/clips/<role>.wav`; without one it beeps.

The relay (`src/lora_relay/main.cpp`) is RelayCore on a Heltec V3: RadioLib drives the bare SX1262,
light sleep between frames with DIO1 as the wake, no clock (seconds since boot drive the airtime
window), a RELAY_BEACON every 15 minutes with the battery voltage and the channel's noise.

## The simulator builds (Wokwi)

`siren_node_sim` and `gauge_v3_sim` speak lines on the serial port instead of a modem and a radio.

- Siren in: `>CMD {json}`, `>CFG {json}`, `>LORA <b64>`, `>SMS <from> <text>`, `>TIME <unix>`,
  `>CLOUD up|down`, `>FAULT amp_open|mic_dead|none`, `>TEST silent`, `>SOC <n>`, `>KEY off|w|c`,
  `>HOLD 0|1`. Out: `READY`, `<EVT {json}`, `<LORA <b64>`, `<SMS <to> <text>`, `<PUB <topic> <bytes>`,
  `<CLIP <role>`.
- Gauge in: `>TIME <unix>`, `>STAGE <cm>`, `>BLIND`, `>NOECHO`, `>BATT <mv>`, `>TIP`, `>WAKE`,
  `>CLOUD up|down`, `>LORA <b64>`; the RAIN TIP pushbutton. Out: `READY`, `<WAKE level=.. alarm=..
  sleep=..`, `<READING {json}`, `<LORA <b64>`, `<PUB ...>`, `<BEACON on|off`, `<RAINWAKE`.

`wokwi/siren_node` and `wokwi/gauge_v3` hold the diagrams, `wokwi.toml` and 13 scenarios: a signed
Warning sounds and verifies, a bad signature, a replay and an expired command are refused, Critical
pre-empts Warning, key + 3 s hold gives MANUAL and a 2 s hold nothing, cloud silence plus a signed
GAUGE_ALARM gives AUTONOMOUS and shadow mode only logs, the silent test fails on an amp fault; 2 of 3
at Critical sends GAUGE_ALARM, a blocked face never alarms, two tips in a minute set the burst
cadence. `tools/gen_wokwi.py` writes them (commands and frames signed by the backend's codec with
TEST ONLY keys). **They have not been run**: the CI job needs a `WOKWI_CLI_TOKEN` secret. Not covered
yet: the tamper switch, the hardware max-on one-shot (it is hardware), an INA226 custom chip (the sim
models the currents in firmware). The images load as `firmware.bin` with Wokwi's own partition table;
if LittleFS does not mount there the outbox stays empty, but the `<EVT` lines still print.

## Open items found while building it

- **Fixed: the shadow command had no `device`.** The cloud's `desired.cmd` carries no device id
  (the receiver signs over its own name), but `parse_cmd_json` required one, so a real siren would
  have dropped every shadow command without a word. `device` is optional now, and `test_vectors`
  parses each golden command as the shadow carries it.
- **Fixed: a backfill body could outgrow the MQTT buffer.** The outbox drain built up to 4.8 KB
  bodies for a 4 KB client buffer; it now caps them at 3.8 KB (a body that never fits would have
  tripped the breaker on every try).
- **Fixed: one command, two paths.** The cloud's command arrives by the shadow and, through the box's
  `relay_cmd`, on LoRa. The siren now treats the second copy of the command it is already sounding
  as the same command (the cloud's id and its 12-hex cmd_id48), and the backend maps a cmd_id48
  back to the command.
- **Fixed before it could happen: a silent test on LoRa.** The compact LoRa command has no volume,
  so a relayed silent test (T1 at volume 0) would have played aloud. The cloud relays only sound and
  stop commands to the boxes, and a siren refuses a T1 that comes on LoRa.
- **E22 channel raster.** The E22-900T22S UART module tunes to 850.125 MHz + n MHz, so the
  spec's 865.4025 and 865.985 MHz are not reachable: CH 15 (865.125 MHz) and CH 16 are nearest.
  It also hides SF and bandwidth behind an "air data rate". The relay's bare SX1262 uses the
  schema's radio plan exactly; whether it and an E22 hear each other at all is the first bench test.
  Until then, deploy a relay only with nodes on the same radio.
- **Sync word.** The spec's 0x34 is the LoRaWAN public word; schema.h uses 0x12 (private).
- **Airtime.** A 32-byte frame at SF10/125 kHz is 453 ms, not about 370 ms (the test checks the
  formula against the known 46.3 ms LoRaWAN figure). The 90 s budget is about 198 such frames
  an hour. The gauge counts its budget per wake (it deep-sleeps); at most two frames a minute keeps
  it under 2.5 %.
- **Box events and relay_cmd** now have a backend format (`report`, `ack` with `alert_id`, the box
  shadow's `relay_cmd`; docs/CONTRACT.md).
- **Still to build:** the ULP tip counter in an ESP-IDF build; OTA download and rollback (the job
  gate is tested; the download is not written); adaptive LoRa power (the gauge's 2 s ACK window
  listens but does not adjust); the gauge's config shadow (its IoT policy would need shadow access);
  coulomb counting for SoC (voltage is the fallback in every image).

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
  - RadioLib (MIT), for the relay's SX1262;
  - esp-idf-nvs-partition-gen (Apache-2.0), run by the provisioning tool;
  - Unity (MIT), for the tests;
  - arduino-esp32 (LGPL-2.1, linked as the framework).
- The date algorithm in `pkr_event.cpp` is Howard Hinnant's (public domain).
