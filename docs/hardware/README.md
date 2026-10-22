# River gauge for a Pukaar village

A forecast says what the river *may* do. A gauge says what it *is* doing. Each
Pukaar village can have one water-level gauge, mounted under a bridge deck, that
reports the river stage every five minutes (every minute while it rises). The
risk rules treat it as a third evidence source beside the rain forecast and the
river-discharge forecast:

- the gauge's level comes from the stage against the village's own watch,
  warning and critical marks (`gauge>=<cm>cm:<level>` in the decision trace);
- **a stage counts only when 2 of the last 3 good readings reach it**; one
  reading at warning changes nothing on its own (`gauge_unconfirmed:<level>`);
- **a sustained fast rise** (by default 30 cm or more in 30 minutes across 3 or
  more good readings) raises the gauge level by one step
  (`gauge_rising_fast:+<cm>cm/<min>min:<level>`);
- the village level is the highest of rain, river, gauge and verified reports;
- `two_sources_agree` counts the gauge, so gauge + river forecast (or gauge +
  rain) at watch or above moves the village one level up;
- a reading older than 30 minutes, a backfilled reading, or no gauge at all
  changes nothing.

Status, honestly: **no gauge is installed yet.** Every village is seeded with a
`-sim` device id and illustrative thresholds. Two labelled simulators drive it:
`make gauge-sim-mqtt` publishes over MQTT to AWS IoT Core with a real per-device
X.509 certificate (`backend/src/Pukaar/scripts/gauge_sim_mqtt.py`), and
`make gauge-sim` posts signed HTTPS (`backend/src/Pukaar/scripts/gauge_sim.py`).
Both now send payload v2 and, by default, three hours of backfill before five
live readings. Simulated readings carry `simulated: true`, add `gauge_simulated`
to the decision trace and show a "Simulated" chip on the village page; they
never raise a live village.

**Both sketches are untested on hardware.** The reference firmware v2
([esp32-gauge-mqtt.ino](esp32-gauge-mqtt/esp32-gauge-mqtt.ino)) and the minimal
v1 HTTPS example ([esp32-gauge.ino](esp32-gauge/esp32-gauge.ino)) have not been
compiled on a board, run in a river or soak-tested. Bench-test every pin,
register and the stage arithmetic before one goes under a bridge.

## Design (v2)

```
            bridge deck
  ==========================================
        |  80 GHz radar (SEN0676), lens down     [IP66 box: ESP32-S3 + Cat-1 modem,
        |    |                                     LiFePO4 cells, TP5000 charger,
        |    | distance d                          siren relay]   6 V panel on the railing
        |    v
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~  water surface
        ^
        | stage = H - d      (H, the datum, lives on the server: GaugeConfig.mount_height_cm)
        |
  ------+---------------------  gauge zero (a fixed mark: pier footing or low-water bed)
```

- **Sensor: DFRobot SEN0676**, an 80 GHz FMCW radar (0.15-40 m, ±5 mm, ±3°
  beam with its lens). Radar is not fooled by air temperature, rain or the
  condensation that blinds ultrasonic probes under a deck. Its interface is TTL
  UART carrying Modbus RTU (not RS485), at 30 mA; DFRobot states no IP rating,
  so it goes behind a radome or in the box with the lens looking down. The
  firmware reads holding register `0x0001` (distance to the water, mm).
- **Ultrasonic alternative:** a JSN-SR04T-type waterproof probe (about
  25-450 cm, 20-25 cm blind zone) or the DFRobot A02YYUW (3-450 cm, IP67, UART).
  Cheaper, but its distance depends on the speed of sound, so the firmware sends
  the enclosure temperature and the server corrects for it (below). The v2
  sketch supports the JSN-SR04T (trig/echo); the A02YYUW needs a small UART
  frame parser instead.
- **ESP32-S3** (8 MB flash, 8 MB PSRAM): deep sleep, RTC memory for the ring
  buffer, a die temperature sensor, PPP over the modem in arduino-esp32 3.x.
- **LTE Cat-1 modem** (SIMCom A7670/A7672 or SIM7670 family): far better rural
  coverage than 2G, which is being switched off. Pick a part with **band 40**
  as well as 1/3/5/8 for Indian networks: the SIM7670G and the A7672S list B40;
  the A7670E does not.
- **Power: LiFePO4** (3.2 V cells) instead of Li-ion: safer in a hot box in the
  sun, far more cycles, tolerant of the monsoon's long partial charges. Charge
  it with a TP5000 set to its 3.6 V LiFePO4 mode from a 5-6 V panel (the TP5000
  takes 4.5-9 V, so not a 12 V panel). Below 3.0 V the firmware hibernates.
- **Local siren:** a relay or MOSFET output for a 12 V siren at the bridge,
  driven by the gauge itself when 3 of 3 readings are at or above
  `SIREN_LEVEL_CM`, with no network involved.

> **LoRaWAN is not a shortcut in India.** AWS IoT Core for LoRaWAN supports the
> EU863-870, US902-928, AU915 and AS923-1 frequency plans; **IN865 is not one of
> them** ([AWS docs](https://docs.aws.amazon.com/iot-wireless/latest/developerguide/lorawan-rfregion-permissions.html),
> checked 22 October 2026). A LoRa gauge in India would need its own network
> server (ChirpStack or The Things Network) bridged to Pukaar. Cat-1 avoids that.

### Bill of materials (one gauge, prices checked 22 October 2026)

"Verified" means the price was visible on the vendor page when it was checked;
"unverified" means it came from a search listing or the page could not be
loaded (robu.in returned HTTP 403). Prices move; stock was often out.

| Part | Choice | Vendor | Price | Checked |
|---|---|---|---|---|
| Radar level sensor | DFRobot SEN0676, 80 GHz, 0.15-40 m, ±5 mm | [dfrobot.com](https://www.dfrobot.com/product-2959.html) | US$59.00 (no Indian reseller found) | verified |
| or ultrasonic | DFRobot A02YYUW (SEN0311), 3-450 cm, IP67 | [dfrobot.com](https://www.dfrobot.com/product-1935.html) | US$15.90 | verified |
| or ultrasonic | JSN-SR04T-type waterproof probe (model not named on the page) | [Robocraze](https://robocraze.com/products/waterproof-ultrasonic-sensor) | ₹345 incl. GST | verified |
| MCU + Cat-1 (one board) | LilyGO T-SIM7670G S3 (ESP32-S3, SIM7670G with B40) | [lilygo.cc](https://lilygo.cc/products/t-sim-7670g-s3) | US$36.02, sold out when checked | verified |
| or MCU | Espressif ESP32-S3-DevKitC-1-N8R8 | [DigiKey India](https://www.digikey.in/en/products/detail/espressif-systems/ESP32-S3-DEVKITC-1-N8R8/15295894) | ₹1,433.25 | verified |
| or MCU | 7Semi ESP32-S3-DevKitC-1 (N8R8) | [Evelta](https://evelta.com/7semi-esp32-s3-devkitc-1-esp32-s3-wroom-wi-fi-bluetooth-5-ble-development-board/) | ₹910.96 incl. GST | verified |
| or Cat-1 module | SIMCom A7672S-FASE (B1/3/5/8/40/41), bare module | [Hubtronics](https://hubtronics.in/a7672s-fase-lte-gps-module) | ₹1,121 incl. GST, out of stock | verified |
| or MCU + Cat-1 | Waveshare ESP32-S3-A7670E-4G (no B40) | [Evelta](https://evelta.com/esp32-s3-a7670e-4g-lte-cat-1-gnss-wifi-bluetooth-development-board/) | ₹4,600.82 incl. GST | verified |
| Solar panel | DFRobot FIT0601, 5 V 1 A | [dfrobot.com](https://www.dfrobot.com/product-1774.html) | US$9.00 | verified |
| or larger panel | 10 W 12 V poly (needs a different charger) | [robu.in](https://robu.in/?p=12299) | ₹997 incl. GST | unverified |
| Battery | 2 × IFR32650 LiFePO4, 3.2 V 6 Ah, in parallel | [robu.in](https://robu.in/?p=951488) | ₹449 each | unverified |
| Charger | TP5000 module, 3.6 V LiFePO4 mode | [ThinkRobotics](https://thinkrobotics.com/products/tp5000-4-2v-3-6v-1a-lithium-battery-charging-module) | ₹99.99, sold out | verified |
| Enclosure | IP66 polycarbonate box, glands, vent, radome | local | about ₹800-1,500 | unverified estimate |
| Mount | Stainless bracket, U-bolts, cable | local | about ₹800-1,500 | unverified estimate |
| Siren | 12 V siren, relay or logic MOSFET, boost or separate 12 V supply | local | about ₹600-1,200 | unverified estimate |
| SIM | Data SIM (a few MB a day) | operator | plan-dependent | not priced |

**Rough total, radar path:** about US$110 of DFRobot and LilyGO parts plus
about ₹5,000-7,000 of local parts, so roughly ₹15,000-18,000 (US$170-210) before
shipping, import duty and the SIM. That is under the US$250-320 planning range,
which also allows for a spare and installation. The ultrasonic path saves about
US$45-55. None of this is a quotation.

Power, roughly (not measured): a Cat-1 wake every 5 minutes is about 20 s at
about 150 mA average (1-2 A peaks; a 1,000 µF capacitor at the modem), about
0.8 mAh, so about 250 mAh a day; burst mode (one a minute) is about 1,200 mAh a
day. Two 6 Ah cells give a few weeks at the normal rate and over a week of
continuous burst with no sun.

### Wiring (v2, ESP32-S3)

| From | To | Note |
|---|---|---|
| SEN0676 VCC / GND | 5 V through a P-MOSFET (gate GPIO 4, low = on) / GND | 3.7-5 V, 30 mA; off between readings |
| SEN0676 TX / RX | GPIO 17 (RX) / GPIO 18 (TX) | 3.3 V TTL UART, Modbus RTU, 115200 8N1, address 1 |
| or JSN-SR04T TRIG / ECHO | GPIO 5 / GPIO 6 via 1 kΩ / 2 kΩ divider | echo is 5 V |
| LiFePO4 + | 100 kΩ / 100 kΩ divider to GPIO 1 | ADC1 |
| Panel + | 100 kΩ / 47 kΩ divider to GPIO 2 | ADC1, `solar_mv` |
| Siren driver | GPIO 7 | relay coil or logic-level MOSFET, flyback diode |
| Modem TX / RX / RESET / PWR | GPIO 12 / 11 / 13 / 10 | PPP over UART; check the board's own pinout |

The v1 HTTPS sketch keeps the old ESP32-WROOM + JSN-SR04T + SIM800L wiring in
its header comments.

## Reference firmware v2

[esp32-gauge-mqtt/esp32-gauge-mqtt.ino](esp32-gauge-mqtt/esp32-gauge-mqtt.ino),
**untested on hardware**. One wake:

1. **Watchdog** for the whole wake (90 s): a hung modem or TLS handshake resets
   the chip; the next reading reports `reset_cause: "wdt"` and error bit 64.
2. **Battery check.** Under 3.0 V (LiFePO4) it still measures and buffers, but
   keeps the radio and the siren off and sleeps 30 minutes.
3. **A burst of 9 samples** (7-11 works). Zeros and values in the blind zone or
   beyond the range are dropped; the median of the rest is taken; samples
   further than max(3 × IQR, 30 mm) from it are rejected; the reading is the
   median of what is left. `samples_ok`, `samples_n` and `iqr_mm` go to the
   server, which treats fewer than half the samples, or a spread above 150 mm,
   as suspect.
4. **Local siren**: 3 of 3 good readings at or above `SIREN_LEVEL_CM` latch the
   siren (on for 2 minutes each wake); 3 of 3 under `SIREN_CLEAR_CM` release it.
   It needs no network. Everyone must agree before it sounds, as in
   tepmachcha's `validate()` (MIT, DAI Maker Lab).
5. **Ring buffer** of 240 readings in RTC memory (about 20 h at 5 minutes); a
   full buffer drops its oldest and sets error bit 32.
6. **Send**: this wake's reading to `.../reading` at QoS 1, then the buffered
   ones, oldest first, five per message to `.../backfill`. A reading leaves the
   buffer only after its PUBACK; a resend is harmless because the server stores
   each `(device, boot, seq)` once.
7. **Burst mode**: a rise of 10 cm over the last three readings switches the
   interval from 5 minutes to 1 minute (the server keeps at most one live
   reading a minute).

The ring buffer's record layout (a timestamp, then fixed fields) follows the
`LogBuffer` class of EnviroDIY ModularSensors (BSD-3-Clause, Stroud Water
Research Center); the code is new. FloodNet's firmware and quality-control
notebooks informed the approach only (they are CC BY-NC-SA; nothing is copied).

### Payload v2

The server accepts v1 (`at`, `water_level_cm`, `rain_mm_1h`?, `battery_v`?,
`rssi`?, `simulated`?) and v2:

| Field | Type | Meaning |
|---|---|---|
| `v` | 2 | schema version (optional; any v2 field marks v2) |
| `at` | ISO 8601 UTC | when it was measured |
| `seq`, `boot` | integers | per-boot counter and the boot number (NVS); `(device, boot, seq)` is the idempotency key |
| `distance_mm` | number | raw distance, sensor face to water (ultrasonic: at 20 C) |
| `water_level_cm` | number | the device's own stage; optional when `distance_mm` is sent and the server has the datum |
| `samples_ok`, `samples_n` | integers | samples kept of the burst |
| `iqr_mm` | number | spread of the burst |
| `quality` | 0-100 | the device's own score (under 50 is suspect) |
| `err` | bitmask | 1 no echo, 2 few samples, 4 high spread, 8 clock unsynced, 16 low voltage, 32 buffer overflow, 64 watchdog or brownout reset, 128 sensor out of range. 1, 2, 4 and 128 make a reading suspect; the rest are informational |
| `temp_c` | number | enclosure temperature |
| `battery_mv`, `solar_mv` | numbers | battery and panel voltage |
| `rssi` | dBm | link quality, when known |
| `fw`, `reset_cause` | strings | firmware version; why the chip last reset |
| `buffered` | bool | sent late from the buffer (always true on `.../backfill`) |
| `simulated` | bool | the labelled simulator only |

**The datum lives on the server.** Each gauge's `mount_height_cm` (sensor face
above the gauge zero, measured with a tape) is part of its `gauge` block in
`data/villages.json`. When a reading carries `distance_mm` and the gauge has a
datum, the server computes `stage = mount_height_cm - distance / 10` and ignores
the device's own `water_level_cm`. A wrong constant in a flashed sketch cannot
shift the stage, and a re-survey after a flood is a config change, not a site
visit. Without a datum the device's `water_level_cm` is used; `distance_mm`
alone is refused (`no_datum`).

**Temperature compensation (ultrasonic only).** The firmware converts echo time
to distance at the speed of sound at 20 C. The server corrects it with the
reading's `temp_c`:

    c(T) = 331.3 × sqrt(1 + T / 273.15) m/s,   d_true = d_reported × c(T) / c(20)

At 40 C a 3 m distance is about 10 cm longer than the 20 C figure; at 0 C
about 10 cm shorter. `temp_c` is the box's air temperature, a proxy for the air
along the beam (the beam under a deck is usually cooler than a box in the sun,
so at midday the correction may slightly overshoot). A radar gauge
(`"sensor": "radar"`) gets no correction.

## What the server does with every reading

(`backend/src/Pukaar/services/gauge.py`; every threshold is a per-gauge
`GaugeConfig` field with the default shown.)

| Check | Default | Result |
|---|---|---|
| Range: distance (sent, or implied by the stage and the datum) at or inside the blind zone, or at or beyond the maximum range | `blind_zone_mm` 250, `max_range_mm` 4500 (set 150 and 40000 for the SEN0676) | `out_of_range`, kept, never counted |
| Device diagnostics: error bits 1/2/4/128, under half the samples, `iqr_mm` over 150, `quality` under 50 | | `suspect`, kept, never counted |
| Spike: a change faster than the physical limit against the last good reading | `max_rise_cm_per_min` 30 | `spike`, kept, never counted. Two readings in a row that agree with each other are a real step: the second is good |
| Confirmation: 2 of the last 3 good, fresh, live readings at or above a stage | | `confirmed_level` |
| Rate of rise: at least `rise_cm` in `rise_minutes` across 3 or more good readings, no step down over 5 cm | 30 cm in 30 min | `rising_fast`, the level one step up (`effective_level`) |

Every reading is stored with its `quality`, `quality_reasons`, its own
`measured_level`, `confirmed_level` and `effective_level`, so officers see
what the gauge said and why it did or did not count. A change of
`effective_level` writes an audit row; an `effective_level` at watch or above
re-runs the village's rules at once (only ever to raise the level). Readings
live 14 days (DynamoDB TTL).

**Backfill.** A gauge that lost its link sends what it buffered to
`pukaar/gauge/<village>/<device>/backfill` (MQTT, `{"readings": [...]}`, up to
60) or `POST /sensors/{village}/backfill` (HTTPS, the same signature as
readings, `{"device_id", "readings": [...]}`). Each reading needs a `seq` and a
timestamp from the last 72 hours; it is stored once per `(device, boot, seq)`
(a live reading claims its `seq` too, so a reading sent live and again from the
buffer lands once). Backfilled readings are drawn on the chart and count for
health and for learning thresholds, but they **never trigger anything**: no
re-evaluation, no alert, no audit of a level change, never counted by the rules,
and never the "latest" reading a sweep reads. The live path keeps its replay
protection: at most one live reading per device per minute, never earlier than
the last, within 10 minutes (MQTT) or 5 minutes (HTTPS) of the server clock.
A reading marked `buffered: true` on the live topic or route is treated as
backfill.

**Health.** Each gauge's `last_seen` (the newest receive time, live or
backfill), battery, the share of bad-quality readings in the last 24 h and its
firmware are on the village page and the `/sensors` board (`health`). A gauge
silent for over 30 minutes, with a battery under `low_battery_mv` (default 3500,
for one Li-ion cell; set about 3100 for LiFePO4), or with half or more of at
least six readings bad is `gauge_unhealthy`. Every 15-minute sweep logs each
unhealthy gauge and emits the metric `GaugeUnhealthy` (installed gauges only,
so the seeded simulators do not page anyone). Bad readings emit
`GaugeBadReading` (by quality) and stored backfill `GaugeBackfill`.

## MQTT over AWS IoT Core (recommended)

Each gauge has its own X.509 certificate, speaks MQTT over mutual TLS to the
account's AWS IoT Core endpoint, and AWS IoT does the authentication before
Pukaar's code runs.

```
 gauge (ESP32-S3, own cert) --MQTT/TLS 8883 (or 443 + ALPN x-amzn-mqtt-ca)--> AWS IoT Core
   topics pukaar/gauge/<village>/<device>/reading and .../backfill
     -> topic rule pukaar_gauge_<stage>:
        SELECT *, topic(3) AS village_id, topic(4) AS device_id, topic(5) AS topic_kind
        FROM 'pukaar/gauge/+/+/+' WHERE topic(5) = 'reading' OR topic(5) = 'backfill'
     -> Lambda pukaar-gauge-ingest-<stage> -> gauge.ingest() / gauge.ingest_backfill() -> DynamoDB
        rule error action and Lambda failures -> SQS pukaar-worker-dlq-<stage> (alarmed)
```

**Provisioning** (one command per gauge, after `make deploy`):

```
make gauge-provision VILLAGE=gohar           # thing + certificate + policy, key into SSM
make gauge-sim-mqtt VILLAGE=gohar            # SIMULATED readings over MQTT with that certificate
make gauge-provision VILLAGE=gohar DELETE=1  # detach, deactivate and delete it all again
```

`gauge-provision` (`backend/src/Pukaar/scripts/iot_provision.py`) reads the
village's registered `gauge.device_id` from the deployed stack, then:

1. creates an IoT **thing** named after the device id;
2. creates an RSA key pair and an **active certificate**;
3. attaches the stack's policy `pukaar-gauge-<stage>` to the certificate and
   the certificate to the thing;
4. stores the private key and certificate PEM as SSM SecureString parameters
   `/pukaar/gauge/<device>/key` and `/pukaar/gauge/<device>/cert` (sent by
   boto3 straight from memory: never printed, never written to disk);
5. prints the ATS data endpoint, the client id and the two topics.

It is idempotent (a thing that already has a certificate and both parameters is
left alone) and rolls a half-made certificate back if a step fails. For a real
gauge, copy the two PEMs from SSM into the sketch once
(`aws ssm get-parameter --with-decryption --name /pukaar/gauge/<device>/key`),
and turn on flash encryption.

The body carries no device id: the topic is the identity, and the policy pins
the topic to the certificate. The ingest Lambda checks that the numbers are
JSON numbers in range, `at` is ISO 8601, the device is the village's registered
gauge, and (for a live reading) that `at` is within ten minutes of the server
clock (MQTT passes a broker and an asynchronous rule, so the window is wider
than the HTTPS path's five minutes). The stored reading records
`transport: "mqtt"`. A message that can never be stored is logged and dropped
(metric `GaugeRejected`); a storage failure goes to the dead-letter queue.

**Policy** (`PukaarGaugePolicy` in `infra/template.yaml`, checked by
`backend/tests/test_template_safety.py`):

| Action | Resource | Means |
|---|---|---|
| `iot:Connect` | `client/${iot:Connection.Thing.ThingName}`, only while the certificate is attached to that thing | a certificate can connect only as its own gauge |
| `iot:Publish` | `topic/pukaar/gauge/*/${iot:Connection.Thing.ThingName}/reading` and `.../backfill` | and publish only its own readings |

Nothing else: no subscribe, no receive, no shadows, no `iot:*`. A stolen
certificate can at worst send readings as that one gauge, and only to the
village whose registered gauge it is (the Lambda rejects any other village);
the 2-of-3 guard and the spike check still apply to what it sends. Revoking it
is `make gauge-provision DELETE=1` (or marking the certificate inactive in the
console).

**Cost.** AWS IoT Core bills per message, per connection-minute and per rule
triggered, with nothing billed by the hour. A reading every 5 minutes (one a
minute in a flood) is under 10,000 messages and rule runs a month per gauge in a
normal month: a few US cents at list prices (check the current IoT Core pricing
page), plus the Lambda invocations, which are pennies.

## How the signature works (HTTPS path)

The HTTPS routes stay for gauges that cannot hold a certificate or reach the
MQTT endpoint. The gauge has no Cognito account, so `POST /sensors/{village_id}/readings`
and `POST /sensors/{village_id}/backfill` are public at API Gateway and
authenticate each body themselves:

1. **Per-device key**, derived from the stack's existing link secret (SSM
   `link_secret`), so the server stores nothing per device:
   `device_key = hex(HMAC-SHA256(link_secret, "gauge:" + device_id))`.
   An officer prints it once when provisioning a gauge:

   ```
   eval "$(scripts/stack_env.sh)"
   cd backend && PYTHONPATH=src .venv/bin/python -m Pukaar.scripts.gauge_sim --print-key gauge-gohar-01
   ```

2. **Signature over the raw body:** `X-Pukaar-Signature: hex(HMAC-SHA256(device_key, body))`,
   with the 64 hex characters of `device_key` used as the key bytes.
3. **Body:** a reading (v1 or v2) plus `device_id`; for backfill,
   `{"device_id", "readings": [...]}` (at most 60, 32 KB).
4. The server rejects a wrong or missing signature (401), a live `at` older than
   five minutes or more than two minutes ahead (401, replay protection), and a
   `device_id` that is not the village's `gauge.device_id` (403). It stores at
   most one live reading per device per minute with a conditional write that
   also refuses an earlier or identical timestamp, so a captured body cannot be
   replayed. A replayed backfill body is idempotent. Accepted and ignored
   readings both return 202.

Rotating `link_secret` rotates every device key (and expires approval links).
Keep the key in the ESP32's flash with flash encryption on in production.

## Setting the gauge up

The seeded `watch_cm`, `warning_cm` and `critical_cm` in `data/villages.json`
are **illustrative thresholds, to be set from the gauge's own record after
installation.** After the gauge goes up:

1. Measure `H` (sensor face to gauge zero) with a tape. Put it in the gauge
   block as `mount_height_cm`, with `"sensor": "radar"` (and
   `blind_zone_mm: 150`, `max_range_mm: 40000` for the SEN0676) or
   `"sensor": "ultrasonic"`, and `low_battery_mv: 3100` for LiFePO4. Set
   `MOUNT_HEIGHT_CM` in the sketch too (it drives only the local siren). Check
   one reading by hand against a staff gauge or a marked pier.
2. Let it run for the first two to four weeks and look at the stage series
   (village page, or `list_sensor_readings`). Note the normal flow and how much
   it swings in a day; check that rain events show up as rises; look at the
   quality counts in `health`.
3. Walk the reach with the pradhan and the PWD or irrigation engineer and mark
   the stages that matter: where the ford or approach road goes under, the
   lowest house plinths, flood marks from past years on the bridge piers, and
   any CWC danger level if a station is nearby.
4. Set **watch** a clear margin above normal monsoon flow, **warning** at or a
   little below the first impact stage (road cut), **critical** below the
   lowest homes or the bridge's safe level, leaving time for people to move.
   Officers can also accept thresholds learned from the gauge's own record
   (`GET /villages/{id}/gauge/proposal`). Set `SIREN_LEVEL_CM` in the sketch at
   or near critical.
5. Check `max_rise_cm_per_min` against the fastest rise this stream has ever
   shown (flash floods in steep khads can be fast; the default 30 cm a minute is
   18 m an hour) and the rate-of-rise rule against how fast the river rose
   before past floods.
6. Put the real `device_id`, the thresholds and `"installed": true` in the
   village's `gauge` block and run `make seed`. Re-check the datum and the
   marks after the first monsoon.
