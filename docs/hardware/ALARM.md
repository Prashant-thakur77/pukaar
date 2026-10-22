# The alarm layer: sirens, rain nodes and pradhan boxes

Phones and village relays (the pradhan, the gauge reader, the task force) are how Pukaar warns people
today. This page is the design for the part that has to work when the towers are down: a battery and
solar siren in each hamlet cluster, a rain gauge in each khad's catchment, an indoor box in the
pradhan's house, and a short LoRa link from the upstream gauge to the downstream siren.

**Nothing on this page has been tested on hardware.** No siren node, rain node, pradhan box, relay or
firmware has been built, bench-tested or installed. The cloud side exists (below) and is tested
against a Python siren simulator. Every price is a quote to re-check before buying, marked:

- **V**: read on the vendor page on 22 October 2026;
- **S**: from a search-index copy of the seller page (real, may be stale);
- **U**: an estimate, or no Indian listing found.

## What exists today (slice S)

Software only, demonstrable with no kit:

- a device registry (sirens, gauges, pradhan boxes, relays, rain nodes) with last seen, tests, health
  and firmware, in the single DynamoDB table;
- per-device signing keys and one codec for the cloud command (MQTT named shadow), the LoRa frame and the
  signed SMS (`backend/src/Pukaar/services/devices/protocol.py`), with golden test vectors for the
  future firmware at `firmware/test/vectors/protocol_vectors.json` (TEST ONLY keys);
- AWS IoT Core things, policies scoped to each thing, named shadows and topic rules into device ingest;
- a `SoundSirens` step in the approval workflow after approval (it never blocks or fails delivery), the
  recall, failsafe and all-clear hooks, and the siren tier on each alert ("Sirens 1/1 verified");
- the siren check and three alarms: `siren-offline`, `siren-test-failed`, `siren-unconfirmed`
  (docs/RUNBOOK.md);
- observed rain (`rain_obs`) in the risk rules, fed by tipping-bucket fields in the gauge payload;
- two labelled simulators: `make siren-sim VILLAGE=thunag` (a terminal siren node on the real IoT Core
  that verifies the signed command, prints the pattern and reports "verified 3.1 A +24 dB") and
  `make gauge-sim-mqtt VILLAGE=gohar RAIN=120` (a 120 mm/h burst). Everything they send carries
  `simulated: true`; a simulated reading never raises a live village.

Not built: firmware, PCBs, Wokwi scenarios, the audio clips, LoRa and SMS on a real modem, the KMS key.
The build order is S (this), then M (firmware on a bench kit, 3-5 weeks), then L (a field pilot of the
Janjehli to Thunag pair before a monsoon).

## In short

1. **A siren is an attention device for a hamlet, not for a valley.** A Kobe/TOA study (Applied
   Acoustics 2021) of 125 dB at 1 m outdoor speakers found speech coverage (6 dB over noise) fell from
   0.3-1.7 km in dry weather to about 0.15-0.4 km in 160 mm/h rain. River and rain noise by a Himalayan
   khad in spate is perhaps 70-80 dBA (U: measure it). At FEMA's 10 dB over ambient, a 130 dB at 1 m
   horn covers roughly 100-200 m by the river and 300-500 m away from it. So: one node per hamlet
   cluster, always a tone then a Hindi voice, phones and relays stay primary, and an indoor speaker in
   the pradhan's house (Japan's lesson: outdoor speakers fail in heavy rain).
2. **Sirens fail when the power fails** (Larji 2014: hooters "cannot be sounded during power failure";
   Nepal 2006/07 replaced electric sirens with hand sirens; Palu 2018; the Ahr 2021). Every Pukaar
   sounder runs 7 days on battery and solar, and every sound is **verified** (amplifier current plus a
   microphone), not just "dispatched".
3. **Observed rain closes the cloudburst gap.** No hourly gauge record was found for Seraj, Thunag or
   Gohar in the 2025 Mandi cloudbursts. A tipping bucket on gauge v3 and a cheap rain-only node in each
   khad's upper catchment feed `rain_obs`: it raises a level and never lowers one, needs 2 of the last 3
   evaluations, is capped at Warning on its own, and has stuck-bucket and chatter guards.
4. **The river talks to the village.** The upstream gauge sends signed LoRa frames straight to the
   downstream siren (Janjehli to Thunag is about 7 km): no tower, no cloud. Edge autonomy sounds only
   when the cloud has been unreachable for 600 s and 2 of 3 good readings are at or above critical; a
   per-village fast path is off by default, needs DDMA sign-off and a monsoon in shadow mode first.
5. **Check Pandoh first.** BBMB tendered a 6-site warning system at Pandoh Dam (tender
   08/BBMB/CS/C-201, 24 Sep 2025: 120 dB at 30 m, Hindi/Punjabi/English voice, 3-day solar). Map what was
   installed before putting a Pukaar siren there, ingest BBMB release notices as `official` evidence and
   align the tones.
6. **Cost per village:** about Rs 1.6 lakh capex and Rs 30,000 a year (below).

## Field research (sources in the spec)

**Siren systems in the region.**
- Odisha EWDS: 122 towers within 1.5 km of the coast, 1,205 villages; in Cyclone Yaas sirens sounded
  hourly and 267 live announcements went out at half-hour intervals: siren then voice, repeated.
- Kerala KaWaCHaM (2025): 126 siren-strobe units planned, 91 working at launch; Idukki dam sirens
  Rs 77,000 each.
- Uttarakhand: the Rishiganga alarm failed in 2021; SDRF later put sirens at Raini.
- India Civil Defence: warning is about 2 minutes of rising and falling tone; all-clear a steady tone of
  1-2 minutes. A flood signal must not sound exactly like the air-raid wail and must carry Hindi voice.
- Himachal: the Larji 2014 inquiry found no SOP, hooters dead for months, 2 of 3 silent in power cuts,
  one around a bend 1 km away. A 2023 audit found 21 of 23 hydel projects non-compliant ("tailor-made
  voice messages, besides siren"). BBMB put 6 units below Pong in April 2026. No village-level siren
  warning system was found in Mandi or Kullu.
- Nepal: gauge readers phone a cascade; Birendranagar has a siren triggered by rain at 60 mm/h; many
  2016 sirens have "fallen into disrepair". Bangladesh CPP: 37-43% heard the warning from a volunteer in
  person against 25-29% by radio: a trusted voice beats codes. Japan: outdoor speakers inaudible in the
  2018 rains and Hagibis; overlapping speech from neighbouring speakers. Philippines (Haiyan): people
  did not understand "storm surge"; say the impact in local words.

**Acoustics.** 6 dB per doubling of distance to 30 m, then 10 dB per doubling (FEMA CPG 1-17); target
10 dB over ambient (NUREG-0654); rain noise 53-70 dBA at 40 mm/h and 61-73 dBA at 160 mm/h; the Beas in
spate 70-85 dBA at the bank (U, measure); 500-700 Hz carries round terrain better; valleys echo and
gorge bends shadow.

**Rain gauges.** A 0.2 mm bucket at 120 mm/h tips every 6 s and loses about 5% to a 300 ms tip; a
0.25 mm bucket read about 10% low at 200 mm/h; a dynamic correction curve brings the error under 1%.
Davis-type gauges are rated to 100 mm/h, exactly IMD's cloudburst rate. BIS IS 18627:2024 covers
tipping buckets.

**Radio.** G.S.R. 853(E) (10 Dec 2021) Table II: at most 500 mW ERP, adaptive power control, duty cycle
2.5% for nodes and 10% for access points, 200 kHz bandwidth, type approval. AWS IoT Core for LoRaWAN does
not support IN865, hence LoRa point to point.

## Device family

Ranked by value for cost. All firmware targets the ESP32-S3 (arduino-esp32 3.x / ESP-IDF 5, PlatformIO).

| Rank | Device | Purpose | Approx. INR | Why this rank |
|---|---|---|---|---|
| 1 | **R: rain add-on / rain node** | Observed rain in the catchment, the cloudburst gap | +8-12k on gauge v3; 18-25k standalone | Cheapest fix for the 0-of-3 miss |
| 2 | **S: siren and loudspeaker node** | Tone plus Hindi voice when phones and towers fail; verified sounding | 77-90k installed | The last mile that survives an outage |
| 3 | **G: gauge v3** | v2 radar gauge plus rain, LoRa to the downstream siren, bridge beacon, edge autonomy | 30-38k | Lead time without the cloud |
| 4 | **P: pradhan box** | Indoor speaker, level LEDs, "water rising" report, ack, guarded manual siren | 11-15k | Indoor receiver plus a manual trigger |
| 5 | **L: LoRa relay** | Ridge-top store and forward where a bend blocks line of sight | 15-19k | Only where a link test fails |
| 6 (later) | **H: household receiver** | LoRa listen-only buzzer, LED and 3 W speaker | 2-3k | After the pilot proves the mesh |

### Siren node S (`siren-<village>-NN`)

```
12.8V 50Ah LiFePO4 (BMS, low-temp charge cut-off) <- MPPT 75/15 <- 100 W panel (PV SPD Type 2)
 |-- fuse -- buck 12->5V 3A -- LilyGO T-SIM7670G-S3 (ESP32-S3 + SIM7670G, GNSS)
 |                              |-UART1-- E22-900T22S (SX1262, 22 dBm) -- N arrestor -- 3.5 dBi fibreglass 865
 |                              |-UART2-- DFPlayer Mini (microSD: tones + Hindi clips) --> amp IN
 |                              |-LEDC--RC low-pass--> amp IN (fallback tone generator)
 |                              |-I2C--- INA226 x3 (amp rail, siren rail, battery shunt for SoC)
 |                              |-I2S--- INMP441 mic (behind a port inside the box; relative dB only)
 |                              |-GPIO-- K1 boost/amp enable, K2 horns or 8 ohm dummy load, K3 12 V siren,
 |                              |        K4 strobe; door tamper; key switch; HOLD button; TPL5010 watchdog
 |-- fuse -- boost 12->24V 10A (K1) -- TPA3116D2 mono BTL -- K2 -- 2 x horn (8 ohm each, 4 ohm parallel)
 |-- fuse -- K3 -- 12 V multi-tone electronic siren (independent sounder)
 |-- fuse -- K4 -- 12 V red/amber LED strobe
 + hand-crank siren hung inside the panchayat (last resort, Nepal's lesson)
```

Safety rules: K1 and K3 go through a hardware one-shot (about 12 minutes) that firmware must re-trigger,
so a hung firmware cannot leave the siren blaring; every relay input is pulled down (reset means
silent); the TPL5010 resets the S3 if not fed for 60 s; the 24 V boost is on only while sounding (a
TPA3116 gives about 15 W into 4 ohm at 12 V); check the chip marking (some boards ship a TPA3118).

**Bill of materials**

| Part | Choice | INR | Source | Mark |
|---|---|---|---|---|
| MCU + Cat-1 | LilyGO T-SIM7670G-S3 (A7670G class, has B40/B41; the A7670E does not) | 4,599-6,263 | robu, hubtronics.in; lilygo.cc US$36 | S/V |
| LoRa | Ebyte E22-900T22S (SX1262, UART) | 920 | hubtronics.in | S |
| LoRa antenna | 3.5 dBi fibreglass, N, 865-867 | 2,199 | india-shop.clodpi.io | S |
| Audio source | DFPlayer Mini (genuine) + 16 GB industrial microSD | 629 + ~600 | robu.in | S/U |
| Amplifier | TPA3116D2 mono board (verify chip) | 700-1,000 | amazon.in | U |
| Boost | 12 to 24 V 10 A | ~900 | local | U |
| Horns | 2 x Ahuja SUH-40XT class (40 W, IP) | 2,547-3,596 each | GeM 909354 | S |
| Electronic siren | Qutak 12 V multi-tone | 5,700 | indiamart | S |
| Strobe | 12 V LED beacon red/amber | 380-1,550 | indiamart | S |
| Sensing | 3 x INA226, INMP441 | ~800 | robu, probots | S |
| Relays | 12 V 4-channel opto relay module | 142-155 | quartzcomponents, probots | S |
| Dummy load | 8 ohm 50 W aluminium resistor | ~300 | local | U |
| Supervisor | TPL5010 + 555 one-shot parts | ~250 | local | U |
| Controls | IP65 key switch, mushroom HOLD button, door microswitch | ~650 | local | U |
| Battery | 12.8 V 42-50 Ah LiFePO4, BMS, low-temp cut-off | 11,149 (42 Ah) to ~14,000 | flipkart | S/U |
| Panel | 100 W mono PERC + mount | 4,299 + ~1,500 | magicdrop.in | S/U |
| Charge controller | Victron SmartSolar 75/15 (or EPEver 1210AN ~6k) | ~8,006 | price-history.in | S/U |
| Enclosure | IP66 polycarbonate 400x300x150, Gore vent, glands, silica gel | ~3,000 | indiamart | U |
| Surge and earthing | Type 2 PV SPD, 2 N-coax GDT arrestors, 12 V TVS/SPD, earthing kit, Cu cable | ~6,500 | indiamart, aajjo | S/U |
| Mast | 6 m GI pole, clamps, foundation | 8,000-12,000 | local | U |
| Backup | Hand-crank siren | 2,500-4,000 | local | U |
| Misc | Fuses, DIN, wiring | ~2,000 | - | U |
| **Total** | | **about 77k + 8-10k installation** | | |

**Power.** Idle about 0.8 W at 12 V (about 19 Wh a day). A Critical activation (45 minutes sound-on)
is about 57 Wh, a Warning (20 minutes) about 25 Wh. Design case: 7 sunless days plus 2 Critical and 2
Warning activations, about 300 Wh, so at least 33 Ah usable: choose 50 Ah. NASA POWER for Mandi gives a
worst 7-day mean of 2.63-3.87 kWh/m2/day (2019-2025); designed at 2.0, about 55 W is needed: use 100 W.
State of charge comes from coulomb counting on the battery shunt (LiFePO4 voltage is flat).

| SoC | Behaviour |
|---|---|
| 50% or more | Normal |
| 30-50% | No audible tests; heartbeat every 15 minutes |
| 15-30% | Alarm reserve: energy held for 2 Critical activations; modem wakes every 5 minutes; LoRa RX on |
| under 15% | Alarm only: LoRa RX, local buttons, SMS |

### Gauge v3 G and rain node R

Changes from v2 (docs/hardware/README.md): 12 V power (12.8 V 20 Ah LiFePO4, 30-50 W panel, buck to
5 V 3 A); a tipping bucket counted by the ULP-RISC-V in deep sleep (poll 5 ms, debounce 25 ms, minimum
tip interval 400 ms, anything shorter counted as bounce, a cumulative counter never cleared, mirrored to
NVS); an E22 LoRa transmitter with a 2 s ack window; v2's 3-of-3 bridge siren latch kept as a strobe and
short chirps (B1) for people at the riverbank, not a village alarm.

| Rain gauge | Price | Mark | Note |
|---|---|---|---|
| Pilot: DFRobot SEN0575, 0.28 mm | 3,599 (evelta) | V | Hobby grade; under-reads above about 50-100 mm/h |
| Production: Micro Technologies TBRG 0.2 mm | 12,000 (dial4trade) | S | - |
| Production: Davis 6465M, 0.2 mm, +/-4% to 100 mm/h | 20,000 (indiamart) | S | - |
| Optional second sensor: Hydreon RG-15 optical | US$99 | U | Corroborates, guards against a stuck bucket |

Bench-calibrate each bucket with a peristaltic pump at 20, 60, 120 and 200 mm/h; keep `mm_per_tip` and
the correction coefficient on the server. The rain node is the same board and firmware with no radar
and no siren: about Rs 18-25k with a 6 Ah battery, 10 W panel, IP65 box and a 2 m pole. Put it in the
upper catchment, in the open (at least twice an obstacle's height from it), rim 0.3-1 m above ground,
never on a roof.

### Pradhan box P and relay L

**Box** (`box-<village>-NN`, about Rs 11-15k): ESP32-S3 + SIM7670G, E22 LoRa, a 3 W indoor speaker, four
level LEDs and a link LED. Buttons: **A "पानी बढ़ रहा है"** (a water-rising report), **B "मिल गया"**
(acknowledges the pradhan's own alert), **C "सायरन"** (key switch Warning/Critical plus a 3-second hold),
**D "बंद"** (stops the pradhan's own manual siren). Mains plus 12.8 V 6 Ah battery (about 3.5 days). It
plays the alert clip indoors at every level (only a chime at Watch) and forwards LoRa frames.

**Relay** (`relay-<area>-NN`, about Rs 15-19k; Heltec WiFi LoRa 32 V3 at Rs 2,499-2,568, S; not the
433 MHz variant): stores and forwards signed frames without being able to forge them (it holds no keys),
sends a power beacon every 15 minutes, 10% duty-cycle budget. Only where a link test fails.

**Radio plan:** 865.4025 MHz primary, 865.9850 MHz secondary, 125 kHz, SF10, CR 4/5, private sync word;
22 dBm + 3.5 dBi - 1 dB cable is about 22.4 dBm ERP, under the 27 dBm ERP limit; adaptive power control;
a firmware duty-cycle governor (90 s an hour for nodes, 360 s for relays; telemetry stops at 70% so the
rest is kept for alarm frames). Type approval (WPC ETA) for the E22 and Heltec boards is not verified.

## Alarm patterns

| Level | Pattern | Tone | Then | First burst | Repeats | Cap per alert | Strobe |
|---|---|---|---|---|---|---|---|
| Watch | none | **No outdoor sound.** Box: 3 soft chimes and the clip indoors | - | - | - | - | - |
| Warning | **W1 "तीन लंबी"** | 3 x (5 s steady 650 Hz, 3 s off), the Beas dam-release hooter convention | Hindi warning clip, 15 s silence | 5 cycles (5 min) | 2 cycles every 15 min | 20 min sound-on | amber |
| Critical | **C1 "लहर"** | 60 s rising and falling 500-1,050 Hz (Civil Defence "danger", shortened) | Hindi critical clip, 10 s silence | 10 cycles (15 min) | 3 cycles every 10 min | 45 min sound-on | red |
| All-clear | **A1 "स्थिर"** | 30 s steady 650 Hz | all-clear clip | once, again after 5 min | - | 2 min | green 30 s |
| Test | **T1** | 3 x 0.3 s beeps at 900 Hz, half volume | test clip, 5 s steady at half volume | once | - | 30 s | 3 flashes |
| Drill | **D1** | drill clip first, one W1 cycle (C1 only at the pre-monsoon drill, with DDMA consent), then "यह अभ्यास था" | - | once | - | 2 min | amber |
| Gauge autonomy | **C1 + auto clip** | as C1 | auto clip | 10 cycles | while 2-of-3 holds, every 15 min | 30 min, then a cloud or human decision | red |
| Bridge hazard | **B1** | 1.5 s chirps at 1,200 Hz every 10 s (gauge, riverbank only) | - | while latched | - | 2 min per wake | red |

Rules for every pattern: at most 10 minutes continuous sound-on then 2 minutes rest; priority Critical >
autonomy > manual Critical > Warning > manual Warning > all-clear > drill > test (a lower one never
interrupts a higher one); Warning and Critical have no quiet hours, tests run only 09:00-18:00 IST; where
two nodes overlap, the second (`voice_slot` 1) starts its voice 25 s later so speech never overlaps;
never C1 in a monthly test.

**Voice clips** (Polly Kajal hi-IN, 0.9x rate, pauses of a second or more for valley echo; a recorded
Pahari version per village later; every text through the existing draft checker, so it names no number
or place not in village data):
- W: "ध्यान दें, ध्यान दें। {गाँव} में बाढ़ की चेतावनी है। नदी-नालों से दूर रहें। ज़रूरी सामान तैयार रखें और ऊँची जगह जाने को तैयार रहें। फ़ोन पर पुकार का संदेश सुनें।"
- C: "ख़तरा! ख़तरा! {गाँव} में बाढ़ आ रही है। अभी ऊँची जगह जाएँ: {सुरक्षित जगह}। नदी-नाला पार न करें। बच्चों, बुज़ुर्गों और बीमारों को साथ लें।"
- Auto: "ख़तरा! ऊपर नदी का पानी ख़तरे के निशान से ऊपर है। अभी नदी-नालों से दूर ऊँची जगह जाएँ। यह स्वचालित चेतावनी है।"
- A: "ख़तरा टल गया है। {गाँव} की बाढ़ चेतावनी हटा ली गई है। फिर भी नदी-नालों से दूर रहें और प्रधान की बात सुनें।"
- T: "यह सायरन का परीक्षण है। कोई ख़तरा नहीं है।"
- D: "अभ्यास (DRILL), असली चेतावनी नहीं।"

## Who can sound a siren

| Trigger | Conditions | Audit and notice |
|---|---|---|
| Officer-approved alert (`SoundSirens` step) | Warning or Critical, approved (or the flagged critical auto-send). C1 needs machine evidence at Critical in the trace (a confirmed gauge, the river, official data, or observed rain plus a second source) or a second officer within 120 s; without either the siren plays W1, never silence. A replay reaches only `-sim` devices; a drill plays D1 only | Audit row (no audit, no sound); siren tier rows; timeline |
| Failsafe | Critical, or already approved | Same |
| Officer by hand (an evacuate directive) | Warning from one officer; Critical needs two different officers | Audit; officers on duty told |
| Pradhan local (key switch, or box key + 3 s hold) | Physical, works offline; at most 3 an hour per box, each stops after 10 minutes unless held again; the cloud propagates it to the village's other sirens only | Audit; the duty officer told at once; a report, capped at Warning |
| Edge autonomy | 2 of 3 good upstream readings at or above critical, sensor sane, and no cloud contact for 600 s; the fast path is off by default | The officers and pradhan by SMS; an alert for an officer to confirm; no CAP until confirmed |
| External CAP (SACHET, IMD, BBMB) | **Never sounds a siren.** It is `official` evidence only | - |

Every command is signed for one device, carries a counter and expires within 30 minutes
(docs/SECURITY.md, "Device signing"). A device writes the counters it has accepted to flash before it
acts, and restores them exactly after a reboot: a siren that lost power in a flood sounds on its
gauge's very next alarm, with no gap. Sounding is **verified**: during the first tone the node measures
the amplifier current against its reference and the microphone's sound rise; a failed check never
silences a real alarm. A command not verified in 180 s is `not_confirmed`: the duty officer is told to
phone the pradhan and can send the same signed command by SMS from the console.

## Field operations

**Siting a siren:** the central high point of the hamlet cluster, horns 6-12 m up and tilted 5-10
degrees down, facing away from the river towards the houses, no gorge bend between node and houses.

**Acceptance before the monsoon:** measure ambient noise in real rain (a Class 2 meter, or a calibrated
phone app); measure A1 and C1 at the farthest house to be covered: at least ambient + 10 dB, otherwise
that house is "phone and relay only" on the coverage map. Record `coverage_m` and the current
references. No install at Pandoh until the BBMB system is mapped.

**Lightning and surge:** a Franklin rod above the mast on its own down-conductor; chemical earthing at
10 ohm or less, measured; one earth bar bonding everything; Type 2 SPD on the PV string, TVS on the 12 V
bus and the gauge cable, GDT arrestors on the antennas at the box entry; drip loops, fibreglass antennas,
UV-stable boxes with vents and silica gel; a low-temperature charge cut-off at Janjehli (about 2,100 m).

**Maintenance:** automatic weekly silent test and heartbeats; monthly an audible T1 or D1 at the drill,
the box buttons and the rain pour test (200 ml into a 200 mm funnel is 6.37 mm, about 32 tips at
0.2 mm; record +/-10%); quarterly clean panels and funnel, check earth resistance and mounts, a
30-minute battery capacity test; a full service and SPL re-test by 15 May; spares per district: one
controller kit, one battery, two horns. Before any visit, check whether every device in the area is
offline: then it is the tower or a relay, not the node.

## Cost per village per year (indicative, INR)

| Item | Capex | Opex a year |
|---|---|---|
| Siren node x1 | 85,000 | battery and parts reserve 6,000 |
| Gauge v3 x1 | 35,000 | 2,500 |
| Rain node x1 | 22,000 | 1,500 |
| Pradhan box x1 | 14,000 | 1,000 |
| Relay (about a 0.4 share) | 7,000 | 500 |
| SIMs (4 data + SMS) | - | ~8,000 (U) |
| Visits (quarterly + pre-monsoon) | - | ~10,000 |
| AWS IoT, Lambda, scheduler (no KMS key today) | - | under 500 |
| **Total** | **about 1.63 lakh** | **about 30,000** |

Each extra siren node in a dispersed village adds about Rs 85k capex and Rs 8k a year. A five-village
pilot is about Rs 8-10 lakh capex and Rs 1.5-2 lakh a year. BBMB-class 120 dB at 30 m sites cost several
lakh each (U).

## Where Pukaar goes beyond each reference

| Reference (licence) | What it does | What Pukaar takes | How Pukaar goes further |
|---|---|---|---|
| tepmachcha (MIT) | Per-zone latch, confirmation, SMS clear, IVR trigger, low-battery lockout | Confirmation before alarm, near-field ignore, modem power gating, SMS control | Correct 2-of-3 median; state in NVS; signed commands with counters and expiry; a real siren with verified sounding; all-clear |
| FloodNet sensor (BY-NC-SA, ideas) | Diagnostic signatures, downlink config, maintenance playbook | Fail-loud signatures, boot config, triage tree, kit list | Radar, not drifting sonar; config shadow; durable buffer; OTA with rollback |
| FloodNet gateway (BY-NC-SA, ideas) | 3-layer watchdog, power beacon | Relay and modem watchdogs, power beacon | Beacons over LoRa into the same health model and alarms |
| durable-outbox (MIT) | Leased, deduped, breaker-protected outbox | Algorithm, backoff, breaker, dedupe | On-device port with an alarm queue never dropped |
| Saafwater (Apache) | Offline classification, cloud-to-LED command | Edge fallback, indicator command | One threshold source pushed to the device; TLS; heartbeat |
| Mayfly (BSD-3 / CERN-OHL) | Power path, switched rails, ESD, battery gate | Power design | 7-day LiFePO4 sizing from Mandi data; SoC by coulomb counting |
| ModularSensors (BSD-3) | Battery tiers, fast first cadence, WDT, CI matrix | All of these | Durable buffer; shadows and Jobs; an alarm-reserve tier |
| IOT_Cooper (none, ideas) | Clamps errors into "safe" values | One schema for firmware and server constants | Errors are explicit; unknown never means OK |
| SEN0676 library (none) | Modbus registers | Clean-room driver | Exception handling; read-before-write |
| AcuIfero (CC BY) | Actuator protocol, per-incident idempotency, unused action guard | Idempotency, allowed actions, 6/h rate limit | Dispatched versus verified; stop and all-clear; the guard enforced (Cedar) |
| OpenFloodAI (MIT intent) | UNKNOWN_DEGRADED, fails closed | Health states that fail closed | Applied to sirens and rain (stuck bucket) |
| SURGE (MIT) | All-clear cancels by id | All-clear names the sounded alert | A1 only on sirens that started |
| open-ews (MIT) | Area-targeted audio broadcast | Siren as an area audio channel | Device acknowledgement and verification |
| somleng (MIT) | Keepalive with a grace period | Presence plus re-check | Any-path presence (cell, LoRa, SMS) |
| RapidPro (BSL, ideas) | Silence incident that closes itself | Same for sirens (OK actions) | - |
| Newfies (MPL) | Sent / answered / completed tiers | Commanded / started / verified | Physical evidence (amps, dB) |
| cap-composer (MIT), cap-library (Apache) | Test/Exercise, references, resources | Audio resource with digest | Exercise note kept |
| IBF (Apache) | Forecast versus user trigger | Trigger source on every sound | - |
| Practical Action / DHM Nepal | Gauge-reader cascade, 60 mm/h rain siren, hand sirens | rain_obs, hand-crank backup | Signed LoRa "river talks to village"; tests and health |
| BBMB Pandoh tender | 120 dB at 30 m, Hindi voice, 3-day solar | Spec benchmark | 7-day autonomy, verified sounding, signing, CAP, phones in the same loop |
| Odisha EWDS, Yaas | Siren plus repeated live announcements | Repeat schedule | Automated, signed, verified, logged |
| Larji 2014 | Hooters dead in power cuts, inaudible round a bend | - | Battery, verification, SPL acceptance, weekly tests |
| Japan FDMA / MIC | Outdoor speakers fail in rain; overlapping speech | Indoor box, voice slots | - |

## Open items

Decisions for the owner or the DDMA: the fast-path autonomy policy; the tones (W1 like the dam hooter,
C1 a shortened Civil Defence wail); the audible-test cadence; the SMS route (officer phone versus a DLT
template); whether to install at Pandoh. To verify before relying on them: every S or U price, SEN0676
power and IP rating, ETA for the E22 and Heltec boards, G.S.R. 564(E) of 2008 against 853(E), the Beas
spate noise, the BBMB award and sites, IMD's cloudburst wording, the Janjehli to Thunag travel time,
the INMP441 overload point, the TPA3116 chip on the board bought.
