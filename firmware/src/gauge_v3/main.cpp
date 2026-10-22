// Pukaar river gauge v3 (spec 3.2, 7.1) and, built with -DPUKAAR_RAIN_NODE=1, the rain node (spec 3.2,
// "Rain node R": the same board and firmware with no level sensor). It extends the v2 sketch in
// docs/hardware/esp32-gauge-mqtt: the same burst median and IQR rejection (now pkr_burst_reduce), err
// bits, PPP and MQTT with the device's own X.509 certificate. New in v3:
//   - a tipping bucket on an RTC GPIO, and payload v3 (rain_tips_total, _window, _max_tips_1min,
//     _min_tip_ms, _bounce, rain_err, rain_mm_per_tip: what backend/services/gauge.py reads);
//   - E22 LoRa: GAUGE_STATUS (broadcast) every wake and GAUGE_ALARM to the downstream sirens when 2 of
//     the last 3 good readings are at Critical and the gauge is sane (a blocked face is never a flood);
//   - the bridge beacon (v2's 3-of-3 latch) as a strobe and B1 chirps;
//   - the durable outbox on LittleFS instead of the RTC ring: readings survive a cold boot.
//
// *** UNTESTED ON HARDWARE. *** It compiles for the ESP32-S3 (arduino-esp32 3.x). Every decision is in
// lib/pukaar_common (pkr_node.cpp gauge_plan, pkr_gauge.c, pkr_rain.c) and tested on the host.
//
// The tip counter. The spec wants the ULP-RISC-V to count tips during deep sleep (firmware/ulp_riscv/
// rain_counter.c runs pkr_ulp_rain_step every 5 ms). Linking a ULP program needs the ESP-IDF build
// (ulp_embed_binary), which this Arduino build does not have, so THIS IMAGE WAKES ON EACH TIP (ext0 on
// the bucket's RTC GPIO), counts it with the same state and maths (pkr_ulp_rain_tip), waits for the
// reed to open and sleeps again. Each tip costs a boot (about 0.2 s at 40 mA); at 120 mm/h and 0.2 mm
// a tip that is 10 boots a minute. Bench-measure it before the monsoon.
//
// Build -DPUKAAR_SIM=1 (env gauge_v3_sim) for Wokwi: no deep sleep, no modem, no radar. The bucket is a
// pushbutton polled every 5 ms through pkr_ulp_rain_step (the ULP's own code path), the stage comes
// from `>STAGE <cm>`, LoRa frames and publishes are lines on the serial port. TEST ONLY keys.
#include <Arduino.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <esp_sleep.h>
#include <esp_task_wdt.h>
#include <sys/time.h>
#include <time.h>

#include "pkr_codec.h"
#include "pkr_node.h"
#include "pkr_pattern.h"
#include "pkr_wire.h"
#include "pukaar_hal.h"
#if PUKAAR_SIM
#include "pkr_test_keys.h"
#else
#include <driver/gpio.h>
#include <driver/rtc_io.h>
#endif

using namespace pkr;

#ifndef PUKAAR_FW
#define PUKAAR_FW "pukaar-gauge-3.0.0"
#endif
#ifndef PUKAAR_RAIN_NODE
#define PUKAAR_RAIN_NODE 0
#endif

// ---------------------------------------------------------------- pins (ESP32-S3; v2's plus the bucket,
// the beacon and the E22)
static const int PIN_BATT = 1;          // divider from the 12.8 V pack (100k / 22k), ADC1
static const int PIN_SOLAR = 2;         // divider from the panel (100k / 15k), ADC1
static const int PIN_SENSOR_PWR = 4;    // P-MOSFET gate (low = on)
static const int PIN_TRIG = 5, PIN_ECHO = 6;  // JSN-SR04T (echo through a 1k/2k divider)
static const int PIN_STROBE = 7;        // bridge beacon strobe (v2's siren output)
static const int PIN_BUCKET = 8;        // RTC GPIO: reed to GND, 10k pull-up to 3V3, 100 nF to GND
static const int PIN_CHIRP = 9;         // bridge beacon sounder (N-MOSFET)
static const int PIN_MODEM_PWR = 10, PIN_MODEM_TX = 11, PIN_MODEM_RX = 12, PIN_MODEM_RST = 13;
static const int PIN_RADAR_RX = 17, PIN_RADAR_TX = 18;  // SEN0676 (Modbus RTU over TTL)
static const int PIN_E22_M0 = 38, PIN_E22_M1 = 39;
static const int PIN_E22_TX = 47, PIN_E22_RX = 48;      // to E22 RXD / from E22 TXD
static const float BATT_DIVIDER = 122.0f / 22.0f, SOLAR_DIVIDER = 115.0f / 15.0f;
static const uint32_t WDT_TIMEOUT_S = 90;
static const int BURST_N = 9;

// ---------------------------------------------------------------- state across deep sleep
static RTC_DATA_ATTR pkr_gauge_state_t g_state;
static RTC_DATA_ATTR pkr_ulp_rain_t g_rain;
static RTC_DATA_ATTR pkr_rain_mark_t g_mark;
static RTC_DATA_ATTR uint32_t g_seq = 0, g_boot = 0, g_next_reading_at = 0, g_last_puback = 0;
#if !PUKAAR_SIM
static RTC_DATA_ATTR uint32_t g_last_sync = 0;  // last NTP sync, unix s
#endif
static RTC_DATA_ATTR uint32_t g_mirrored_tips = 0;
static RTC_DATA_ATTR bool g_init = false;
static RTC_DATA_ATTR uint16_t g_sticky_err = 0;  // reported with the next reading (watchdog reset, overflow)

static NodeSettings settings;
static NvsKv nvs;
static LittleFsFs flash;
static Outbox outbox;
static KeyRing keys;
static FrameSigner signer;
static LoraLink lora;
static Uplink uplink;
static char device[48] = {0};
static uint16_t g_err = 0;
static const char* g_cause = "other";
#if PUKAAR_SIM
static SerialConsole console;
static SerialRadio radio;
static SerialLink cloud;
static float sim_stage_cm = 100.0f;
static uint16_t sim_distance_override = 0xFFFF;  // >BLIND / >NOECHO
static uint16_t sim_batt_mv = 13200;
static bool sim_clock_set = false;
static int sim_tip_polls = 0;  // >TIP: the reed held closed for this many 5 ms polls
#else
static E22Radio radio;
static MqttLink cloud;
static HardwareSerial& E22 = Serial2;
#endif

// ---------------------------------------------------------------- time

static uint32_t now_unix() { return (uint32_t)time(nullptr); }

static bool clock_ok() {
#if PUKAAR_SIM
  return sim_clock_set;
#else
  uint32_t t = now_unix();
  return t > 1700000000u && g_last_sync && t - g_last_sync < 86400u;
#endif
}

#if !PUKAAR_SIM
static uint32_t wall_ms() {  // the RTC keeps it across deep sleep: the tip counter's ms clock
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  return (uint32_t)((uint64_t)tv.tv_sec * 1000ULL + (uint64_t)tv.tv_usec / 1000ULL);
}
#endif

// ---------------------------------------------------------------- the level sensor

#if !PUKAAR_RAIN_NODE && !PUKAAR_SIM
static uint16_t radar_mm() {  // SEN0676 register 0x0001: distance to the water in mm (pkr_wire codec)
  uint8_t q[8];
  pkr_modbus_request(0x01, 0x03, 0x0001, 1, q);
  while (Serial1.available()) Serial1.read();
  Serial1.write(q, sizeof q);
  uint8_t r[16];
  size_t n = 0;
  uint32_t t0 = millis();
  while (n < 7 && millis() - t0 < 300)
    if (Serial1.available()) r[n++] = (uint8_t)Serial1.read();
  uint16_t reg = 0;
  uint8_t exc = 0;
  return pkr_modbus_parse_read(r, n, 0x01, 1, &reg, &exc) == 0 ? reg : 0;
}

static uint16_t ultrasonic_mm() {  // echo time at 343.2 m/s (20 C); the server corrects for temp_c
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(5);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(20);
  digitalWrite(PIN_TRIG, LOW);
  unsigned long us = pulseIn(PIN_ECHO, HIGH, 30000UL);
  return us ? (uint16_t)(us * 0.3432f / 2.0f) : 0;
}
#endif

static pkr_burst_t measure() {
  pkr_burst_t b{};
  if (settings.sensor == SENSOR_NONE) return b;
  uint16_t v[BURST_N];
#if PUKAAR_SIM
  for (int i = 0; i < BURST_N; i++) {
    float d = (settings.mount_height_cm - sim_stage_cm) * 10.0f;
    v[i] = sim_distance_override != 0xFFFF ? sim_distance_override : (uint16_t)(d < 0 ? 0 : d);
  }
#else
  pinMode(PIN_SENSOR_PWR, OUTPUT);
  digitalWrite(PIN_SENSOR_PWR, LOW);  // sensor on
  bool radar = settings.sensor == SENSOR_RADAR;
  if (radar) Serial1.begin(115200, SERIAL_8N1, PIN_RADAR_RX, PIN_RADAR_TX);
  else {
    pinMode(PIN_TRIG, OUTPUT);
    pinMode(PIN_ECHO, INPUT);
  }
  delay(radar ? 1500 : 300);  // start-up
  for (int i = 0; i < BURST_N; i++) {
#if PUKAAR_RAIN_NODE
    v[i] = 0;
#else
    v[i] = radar ? radar_mm() : ultrasonic_mm();
#endif
    delay(radar ? 120 : 70);
    esp_task_wdt_reset();
  }
  digitalWrite(PIN_SENSOR_PWR, HIGH);  // sensor off
#endif
  pkr_burst_reduce(v, BURST_N, settings.gauge.blind_mm, settings.gauge.max_mm, &b);
  return b;
}

static uint16_t read_mv(int pin, float divider) {
#if PUKAAR_SIM
  (void)divider;
  return pin == PIN_BATT ? sim_batt_mv : 6000;
#else
  uint32_t mv = 0;
  for (int i = 0; i < 8; i++) mv += analogReadMilliVolts(pin);
  return (uint16_t)((mv / 8.0f) * divider);
#endif
}

// ---------------------------------------------------------------- the bucket

static uint16_t mm_per_tip_x1000() { return (uint16_t)lroundf(settings.mm_per_tip * 1000.0f); }

// A cold boot (power cut, brownout) clears RTC memory: restart the counter from the NVS mirror and
// say so (rain_err counter_reset), so the server never reads the jump as rain.
static int restore_rain() {
  if (g_rain.magic == PKR_ULP_RAIN_MAGIC) return 0;
  Preferences p;
  uint32_t mirror = 0;
  bool had = false;
  if (p.begin("pukaar", true)) {
    had = p.isKey("tips");
    mirror = p.getUInt("tips", 0);
    p.end();
  }
  pkr_ulp_rain_init(&g_rain, 0 /* reed closes to GND */, digitalRead(PIN_BUCKET) ? 1 : 0, mirror);
  g_mirrored_tips = mirror;
  memset(&g_mark, 0, sizeof g_mark);
  return had ? 1 : 0;
}

static void mirror_rain() {  // NVS mirror on every reading (spec: hourly and every wake)
  if (g_rain.rain.tips_total == g_mirrored_tips) return;
  Preferences p;
  if (p.begin("pukaar", false)) {
    p.putUInt("tips", g_rain.rain.tips_total);
    p.end();
    g_mirrored_tips = g_rain.rain.tips_total;
  }
}

// ---------------------------------------------------------------- LoRa

static void lora_out(const GaugePlan& plan) {
  if (!plan.radio || !keys.has_self_key()) return;
  uint8_t p[PKR_FT_GAUGE_STATUS_LEN];
  pkr_gauge_payload_encode(&plan.status, p);
  uint32_t t = now_unix();
  bool synced = clock_ok();
  // the alarm first: it is the frame that matters, and it may use the whole airtime budget
  if (plan.alarm)
    for (uint8_t i = 0; i < settings.n_downstream; i++)
      lora.send(PKR_FT_GAUGE_ALARM, settings.downstream[i].addr, p, sizeof p, t, synced);
  lora.send(PKR_FT_GAUGE_STATUS, PKR_FRAME_BROADCAST, p, sizeof p, t, synced);
  // a 2 s receive window: an ACK addressed to the gauge (adaptive power control is a bench item)
  uint32_t t0 = millis();
  uint8_t buf[PKR_FRAME_MAX_LEN];
  while (millis() - t0 < 2000) {
    size_t n = radio.receive(buf, sizeof buf);
    pkr_frame_t f;
    if (n && pkr_frame_parse(buf, n, &f) == PKR_FRAME_OK && f.type == PKR_FT_ACK && f.dst == keys.addr()) {
#if PUKAAR_SIM
      Serial.println("<ACK heard");
#endif
      break;
    }
    delay(10);
  }
  signer.flush();
}

// ---------------------------------------------------------------- the bridge beacon (B1)

static void beacon(bool latched, uint16_t battery_mv) {
#if PUKAAR_SIM
  (void)battery_mv;
  digitalWrite(PIN_STROBE, latched ? HIGH : LOW);
  Serial.printf("<BEACON %s\n", latched ? "on" : "off");
#else
  if (!latched || (battery_mv && battery_mv < settings.hibernate_mv)) return;
  // B1: 1.5 s chirps every 10 s for 2 minutes, strobe on throughout (this alarm is for people on the
  // bank, not the village siren)
  PatternPlayer player;
  PlanOptions po;
  player.start(make_plan(PKR_PATTERN_B1, false, po), millis());
  ledcAttach(PIN_CHIRP, 1200, 8);
  digitalWrite(PIN_STROBE, HIGH);
  while (player.active()) {
    const Output& o = player.tick(millis());
    ledcWriteTone(PIN_CHIRP, o.tone ? o.freq_hz : 0);
    delay(20);
    esp_task_wdt_reset();
  }
  ledcWriteTone(PIN_CHIRP, 0);
  digitalWrite(PIN_STROBE, LOW);
#endif
}

// ---------------------------------------------------------------- the cloud

static void publish_reading(const GaugePlan& plan) {
  GaugeJsonOpts o;
  o.boot = g_boot;
  o.mm_per_tip = settings.mm_per_tip;
  o.fw = PUKAAR_FW;
  o.has_level_sensor = settings.sensor != SENSOR_NONE;
#if PUKAAR_SIM
  o.simulated = true;
#endif
  char body[640];
  char topic[128];
  snprintf(topic, sizeof topic, "pukaar/gauge/%s/%s/reading", settings.village, device);
  bool sent = false;
  if (cloud.connected()) {
    o.reset_cause = g_cause;
    size_t n = gauge_reading_json(plan.rec, o, body, sizeof body);
#if PUKAAR_SIM
    if (n) Serial.printf("<READING %s\n", body);
#endif
    sent = n && cloud.publish(topic, body, n);
    if (sent) g_last_puback = now_unix();
  }
  if (!sent) {  // history now: the server takes a buffered reading on either topic as backfill
    o.reset_cause = nullptr;
    o.buffered = true;
    size_t n = gauge_reading_json(plan.rec, o, body, sizeof body);
    if (n && !outbox.push(PKR_EVT_HEARTBEAT /* telemetry queue */, g_boot, plan.rec.seq, body, (uint16_t)n))
      g_sticky_err |= PKR_ERR_BUFFER_OVERFLOW;
  }
}

static void cloud_session(const GaugePlan* plan) {
#if PUKAAR_SIM
  if (plan && plan->record) publish_reading(*plan);
  for (int i = 0; i < 4 && cloud.connected() && outbox.depth(); i++) uplink.loop(now_unix());
#else
  if (!settings.endpoint[0]) {  // not provisioned: keep the reading for later
    if (plan && plan->record) publish_reading(*plan);
    return;
  }
  cloud.begin(device, settings.endpoint, settings.apn,
              MqttLink::Pins{PIN_MODEM_TX, PIN_MODEM_RX, PIN_MODEM_RST, PIN_MODEM_PWR});
  uint32_t t0 = millis(), kick = 0;
  while (!cloud.connected() && millis() - t0 < 60000) {
    if (millis() - kick > 2000) {
      cloud.retry_now();
      kick = millis();
    }
    cloud.loop();
    delay(100);
    esp_task_wdt_reset();
  }
  if (cloud.connected() && (!g_last_sync || now_unix() - g_last_sync > 3600)) {
    EspClock c;
    if (c.sync_ntp(5000)) g_last_sync = now_unix();
  }
  if (plan && plan->record) publish_reading(*plan);
  t0 = millis();
  while (cloud.connected() && !uplink.idle() && millis() - t0 < 30000) {
    uplink.loop(now_unix());
    cloud.loop();
    esp_task_wdt_reset();
  }
  cloud.end();
#endif
}

// ---------------------------------------------------------------- one wake

static void reading(int counter_reset) {
  g_err = g_sticky_err;
  g_sticky_err = 0;
  if (!clock_ok()) g_err |= PKR_ERR_CLOCK_UNSYNCED;
  GaugeInputs in;
  in.battery_mv = read_mv(PIN_BATT, BATT_DIVIDER);
  in.solar_mv = read_mv(PIN_SOLAR, SOLAR_DIVIDER);
  in.burst = measure();
  in.now = now_unix();
  in.clock_ok = clock_ok();
#if PUKAAR_SIM
  in.temp_c = 25;
#else
  in.temp_c = (int8_t)temperatureRead();  // the S3's die: a rough proxy (a DS18B20 in the box is better)
#endif
  in.cloud_ok = g_last_puback && in.now - g_last_puback < PKR_LIMIT_GAUGE_CLOUD_OK_S;
#if PUKAAR_SIM
  uint32_t rain_now = pkr_ulp_rain_now_s(&g_rain);  // the ULP path: its own clock
#else
  uint32_t rain_now = in.now;  // the wake-on-tip path counts on the wall clock
#endif
  pkr_rain_take_report(&g_rain, &g_mark, rain_now, mm_per_tip_x1000(), counter_reset, 0, &in.rain);
  in.err = g_err;
  GaugePlan plan;
  gauge_plan(&g_state, settings, in, ++g_seq, &plan);
#if PUKAAR_SIM
  Serial.printf("<WAKE level=%d alarm=%d sleep=%lu stage=%.1f rain15=%u record=%d\n", plan.d.level, plan.alarm ? 1 : 0,
                (unsigned long)plan.sleep_s, isnan(plan.stage_cm) ? -1.0 : (double)plan.stage_cm,
                plan.status.rain_15min_tenths_mm, plan.record ? 1 : 0);
#endif
  lora_out(plan);
  beacon(plan.d.beacon, in.battery_mv);
  if (plan.radio) cloud_session(&plan);
  else if (plan.record) publish_reading(plan);  // hibernate tier: buffer only, radio off
  mirror_rain();
  g_next_reading_at = in.now + plan.sleep_s;
#if !PUKAAR_SIM
  radio.sleep();
  gpio_hold_en((gpio_num_t)PIN_E22_M0);
  gpio_hold_en((gpio_num_t)PIN_E22_M1);
  gpio_deep_sleep_hold_en();
  pinMode(PIN_STROBE, OUTPUT);
  digitalWrite(PIN_STROBE, LOW);
  // wake on the timer, or on the next tip (unless the reed is stuck closed: then the timer only)
  esp_sleep_enable_timer_wakeup((uint64_t)plan.sleep_s * 1000000ULL);
  if (digitalRead(PIN_BUCKET)) esp_sleep_enable_ext0_wakeup((gpio_num_t)PIN_BUCKET, 0);
  esp_deep_sleep_start();
#endif
}

static void load_identity() {
#if PUKAAR_SIM
  // *** TEST ONLY KEYS *** (pkr_test_keys.h): the simulator is a public, labelled fake
  const char* id = PUKAAR_RAIN_NODE ? "rain-janjehli-sim" : PKR_SIM_GAUGE;
  strcpy(device, id);
  keys.set_identity(id, pkr_sim_addr(id));
  uint8_t k[32];
  pkr_test_only_device_key(id, 1, k);
  keys.set_self_key(1, k);
  keys.set_current_kid(1);
  const char* sim_cfg =
      "{\"village\":\"janjehli\",\"mount_height_cm\":420,\"watch_cm\":200,\"warning_cm\":250,\"critical_cm\":300,"
      "\"siren_level_cm\":300,\"siren_clear_cm\":280,\"blind_mm\":150,\"downstream\":[{\"device\":\"" PKR_SIM_SIREN
      "\",\"lora_addr\":257}]}";
  parse_node_settings(sim_cfg, strlen(sim_cfg), &settings);
#else
  load_provisioned_keys(keys, device, sizeof device);
  load_node_settings(settings);
#endif
#if PUKAAR_RAIN_NODE
  settings.sensor = SENSOR_NONE;
#endif
}

static const char* reset_cause() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: return "poweron";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_TASK_WDT:
    case ESP_RST_INT_WDT:
    case ESP_RST_WDT: return "wdt";
    case ESP_RST_PANIC: return "panic";
    case ESP_RST_SW: return "software";
    default: return "other";
  }
}

void setup() {
  esp_task_wdt_config_t wdt = {WDT_TIMEOUT_S * 1000, 0, true};
  esp_task_wdt_reconfigure(&wdt);
  esp_task_wdt_add(nullptr);
  pinMode(PIN_BUCKET, INPUT_PULLUP);
  pinMode(PIN_STROBE, OUTPUT);
  digitalWrite(PIN_STROBE, LOW);
  Serial.begin(115200);
  g_cause = reset_cause();
  bool cold = esp_reset_reason() != ESP_RST_DEEPSLEEP || !g_init;
#if !PUKAAR_SIM
  // a tip woke us: count it, wait for the reed to open, and go back to sleep unless a reading is due
  // or the burst rate was reached
  if (!cold && esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0) {
    bool now_reading = pkr_ulp_rain_tip(&g_rain, wall_ms(), now_unix(), settings.gauge.burst_tips_per_min) == 1;
    uint32_t t0 = millis(), high_since = 0;
    while (millis() - t0 < 2000) {  // debounce: open for 25 ms
      if (digitalRead(PIN_BUCKET)) {
        if (!high_since) high_since = millis() | 1;
        if (millis() - high_since >= PKR_RAIN_DEBOUNCE_MS) break;
      } else high_since = 0;
      delay(2);
    }
    uint32_t t = now_unix();
    if (!now_reading && g_next_reading_at > t + 2) {
      esp_sleep_enable_timer_wakeup((uint64_t)(g_next_reading_at - t) * 1000000ULL);
      if (digitalRead(PIN_BUCKET)) esp_sleep_enable_ext0_wakeup((gpio_num_t)PIN_BUCKET, 0);
      esp_deep_sleep_start();
    }
  }
  gpio_hold_dis((gpio_num_t)PIN_E22_M0);
  gpio_hold_dis((gpio_num_t)PIN_E22_M1);
#endif
  if (cold) {  // a new boot number; seq starts again (the server keys readings on (device, boot, seq))
    Preferences p;
    if (p.begin("pukaar", false)) {
      g_boot = p.getUInt("boot", 0) + 1;
      p.putUInt("boot", g_boot);
      p.end();
    }
    g_seq = 0;
    pkr_gauge_state_init(&g_state);
    g_init = true;
  }
  int counter_reset = restore_rain();
  if (cold && (!strcmp(g_cause, "wdt") || !strcmp(g_cause, "brownout"))) g_sticky_err |= PKR_ERR_WATCHDOG_RESET;
  nvs.begin("pukaar");
  flash.begin();
  outbox.begin(&flash);
  load_identity();
#if PUKAAR_SIM
  Serial.println("READY");
#else
  radio.begin(E22, PIN_E22_RX, PIN_E22_TX, PIN_E22_M0, PIN_E22_M1, keys.addr(), PKR_RADIO_FREQ_PRIMARY_HZ, cold);
#endif
  signer.begin(&keys, &nvs);
  lora.begin(&radio, &signer, PKR_DUTY_NODE_BUDGET_MS);
  uplink.begin(&outbox, &cloud, "gauge", settings.village, device, "reading", "readings");
#if !PUKAAR_SIM
  reading(counter_reset);  // ends in deep sleep
#else
  (void)counter_reset;
#endif
}

#if PUKAAR_SIM
static void sim_line(const char* l) {
  if (!strncmp(l, ">TIME ", 6)) {
    struct timeval tv = {(time_t)strtoul(l + 6, nullptr, 10), 0};
    settimeofday(&tv, nullptr);
    sim_clock_set = true;
  } else if (!strncmp(l, ">STAGE ", 7)) {
    sim_stage_cm = (float)atof(l + 7);
    sim_distance_override = 0xFFFF;
  } else if (!strcmp(l, ">BLIND")) {
    sim_distance_override = 120;  // a spider on the radar face: the shortest distance, "flood"
  } else if (!strcmp(l, ">NOECHO")) {
    sim_distance_override = 0;
  } else if (!strncmp(l, ">BATT ", 6)) {
    sim_batt_mv = (uint16_t)atoi(l + 6);
  } else if (!strncmp(l, ">CLOUD ", 7)) {
    cloud.set_up(!strcmp(l + 7, "up"));
  } else if (!strcmp(l, ">TIP")) {
    sim_tip_polls = 20;  // 100 ms closed, as a real tip
  } else if (!strcmp(l, ">WAKE")) {
    reading(0);
  } else if (!strncmp(l, ">LORA ", 6)) {
    radio.inject(l + 6);
  }
}

void loop() {
  if (const char* l = console.poll()) sim_line(l);
  // the bucket pushbutton through the ULP's own code path: one pkr_ulp_rain_step every 5 ms
  static uint32_t last_poll = 0;
  if (millis() - last_poll >= PKR_RAIN_POLL_MS) {
    last_poll = millis();
    uint8_t level = sim_tip_polls > 0 ? 0 : (digitalRead(PIN_BUCKET) ? 1 : 0);
    if (sim_tip_polls > 0) sim_tip_polls--;
    if (pkr_ulp_rain_step(&g_rain, level, settings.gauge.burst_tips_per_min))
      Serial.println("<RAINWAKE");
  }
  esp_task_wdt_reset();
  delay(1);
}
#else
void loop() {}  // never reached: every path ends in deep sleep
#endif
