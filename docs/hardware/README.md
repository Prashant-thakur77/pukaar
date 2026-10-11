# River gauge for a Pukaar village

A forecast says what the river *may* do. A gauge says what it *is* doing. Each
Pukaar village can have one low-cost water-level gauge, mounted under a bridge
deck, that posts the river stage every minute. The risk rules treat it as a
third evidence source beside the rain forecast and the river-discharge
forecast:

- the gauge's level comes from the stage against the village's own watch,
  warning and critical marks (`gauge>=<cm>cm:<level>` in the decision trace);
- the village level is the highest of rain, river, gauge and verified reports;
- `two_sources_agree` counts the gauge, so gauge + river forecast (or gauge +
  rain) at watch or above moves the village one level up;
- a reading older than 30 minutes, or no gauge at all, changes nothing.

Status, honestly: **no gauge is installed yet.** Every village is seeded with a
`-sim` device id and illustrative thresholds, and `make gauge-sim` drives a
labelled simulator (`backend/src/Pukaar/scripts/gauge_sim.py`). Simulated
readings carry `simulated: true`, add `gauge_simulated` to the decision trace
and show a "Simulated" chip on the village page. The sketch below is
**untested on hardware**.

## Design

```
            bridge deck
  ==========================================
        |  JSN-SR04T probe, face down
        |    |                    [IP65 box: ESP32, 18650, TP4056, SIM800L]
        |    | distance d                       6 V solar panel on the railing
        |    v
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~  water surface
        ^
        | stage = H - d
        |
  ------+---------------------  gauge zero (a fixed mark: pier footing or low-water bed)
```

- **ESP32-WROOM-32** dev board: Wi-Fi, deep sleep at about 10 µA, enough RTC
  memory to count rain tips while asleep.
- **JSN-SR04T** waterproof ultrasonic probe (about 25-450 cm range, 20 cm blind
  zone) pointing straight down at open water, away from the pier's eddies.
  `H` is the probe face's height above the gauge zero, measured with a tape at
  installation. Bridges higher than about 4 m need a longer-range sensor (an
  A02YYUW or a 24/60 GHz radar level sensor) with the same wiring idea.
- Optional **tipping-bucket rain gauge** (0.2794 mm per tip is common; check
  yours). Each tip wakes the ESP32 for a few milliseconds.
- **Power:** one or two 18650 cells, a protected TP4056 charger fed by a 6 V,
  2-3 W panel, an MT3608 boost to 5 V for the probe (switched off between
  readings by a P-MOSFET), the dev board's regulator for the ESP32.
- **SIM800L** GSM as a fallback where there is no Wi-Fi. It is 2G only and its
  own TLS is old, so a production build should do TLS on the ESP32 (for
  example BearSSL over the modem's TCP socket) or use a 4G module (SIM7600).
  The sketch leaves this path as a clearly marked stub.

### Wiring

| From | To | Note |
|---|---|---|
| JSN-SR04T VCC | 5 V (MT3608 out) through P-MOSFET (AO3401) | gate on ESP32 GPIO 25, low = on |
| JSN-SR04T GND | GND | |
| JSN-SR04T TRIG | GPIO 5 | 3.3 V trigger is enough |
| JSN-SR04T ECHO | GPIO 18 via 1 kΩ / 2 kΩ divider | echo is 5 V; the ESP32 is not 5 V tolerant |
| Rain gauge reed switch | GPIO 33 and GND, 10 kΩ pull-up to 3.3 V | RTC pin: wakes from deep sleep (ext0) |
| 18650 + | 100 kΩ / 100 kΩ divider to GPIO 34 | battery voltage (ADC1, works with Wi-Fi on) |
| Solar panel 6 V | TP4056 IN+ / IN- | protected module (DW01 + 8205A) |
| TP4056 OUT+ / OUT- | 18650 holder, MT3608 IN, ESP32 VIN (via 3.3 V LDO such as HT7333 for low quiescent) | |
| SIM800L VCC | 18650 + directly (3.7-4.2 V), 1000 µF cap across | draws 2 A bursts |
| SIM800L TXD / RXD | GPIO 16 (RX2) / GPIO 17 (TX2) | |

### Rough bill of materials

**Approximate, check local prices** (online retail in India, late 2026, one unit):

| Item | INR |
|---|---|
| ESP32-WROOM-32 dev board | 400-550 |
| JSN-SR04T waterproof ultrasonic module | 550-800 |
| Tipping-bucket rain gauge (optional) | 1,500-3,000 |
| 2 × 18650 cells + holder | 450-700 |
| TP4056 protected charger, MT3608 boost, HT7333 LDO | 100-150 |
| 6 V 2-3 W solar panel | 350-600 |
| SIM800L module + antenna (optional) | 300-450 |
| IP65 enclosure, cable glands, conformal coat | 350-600 |
| Stainless bracket, U-bolts, cable, sundries | 400-800 |
| **Total** | **about 3,000 without rain gauge or GSM; 5,000-7,500 with both** |

Power, roughly: a Wi-Fi reading every minute costs 3-5 s awake at about
120 mA, about 8 mA on average, about 200 mAh a day. Two 3,000 mAh cells give
roughly three weeks without sun; the panel covers it on most days. In the dry
season the interval can stretch to 10 minutes (keep it under the 30-minute
freshness window).

## How the signature works

The gauge has no Cognito account, so the route `POST /sensors/{village_id}/readings`
is public at API Gateway and authenticates each body itself:

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
3. **Body:** `{"device_id", "at" (ISO 8601 UTC from NTP), "water_level_cm",
   "rain_mm_1h"?, "battery_v"?, "rssi"?}`.
4. The server rejects a wrong or missing signature (401), an `at` older than
   five minutes or more than two minutes ahead (401, replay protection), and a
   `device_id` that is not the village's `gauge.device_id` (403). It stores at
   most one reading per device per minute with a conditional write that also
   refuses an earlier or identical timestamp, so a captured body cannot be
   replayed. Accepted and ignored readings both return 202.
5. Readings live 14 days (DynamoDB TTL). A change of gauge level writes an
   audit row; a reading at watch or above re-runs the village's rules at once
   (only ever to raise the level, so the one-minute cadence never speeds up
   the three-sweep calm-down).

Rotating `link_secret` rotates every device key (and expires approval links).
Keep the key in the ESP32's flash with flash encryption on in production.

## Setting the thresholds

The seeded `watch_cm`, `warning_cm` and `critical_cm` in `data/villages.json`
are **illustrative thresholds, to be set from the gauge's own record after
installation.** After the gauge goes up:

1. Measure `H` (probe face to gauge zero) with a tape and set `MOUNT_HEIGHT_CM`.
   Check one reading by hand against a staff gauge or a marked pier.
2. Let it run for the first two to four weeks and look at the stage series
   (village page, or `list_sensor_readings`). Note the normal flow and how much
   it swings in a day; check that rain events show up as rises.
3. Walk the reach with the pradhan and the PWD or irrigation engineer and mark
   the stages that matter: where the ford or approach road goes under, the
   lowest house plinths, flood marks from past years on the bridge piers, and
   any CWC danger level if a station is nearby.
4. Set **watch** a clear margin above normal monsoon flow, **warning** at or a
   little below the first impact stage (road cut), **critical** below the
   lowest homes or the bridge's safe level, leaving time for people to move.
5. Put the real `device_id`, the thresholds and `"installed": true` in the
   village's `gauge` block in `data/villages.json` and run `make seed`.
   Re-check the marks after the first monsoon.
