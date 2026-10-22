// Pukaar river gauge, reference firmware v2: ESP32-S3 + 80 GHz radar (DFRobot SEN0676) or an
// ultrasonic probe (JSN-SR04T) under a bridge deck, LTE Cat-1 (or Wi-Fi), MQTT to AWS IoT Core
// with its own X.509 certificate. docs/hardware/README.md has the design, BOM and wiring.
//
// *** UNTESTED ON HARDWARE. *** Written against arduino-esp32 3.1+ (its PPP library for the
// Cat-1 modem, NetworkClientSecure, esp_task_wdt v5 API) and the MQTT library by Joel Gaehwiler
// (256dpi/arduino-mqtt, MIT) for QoS 1 publishes. It has not been compiled on a board, run in a
// river or soak-tested. Check every pin, timing, register and the stage arithmetic on a bench
// with a tape measure before it goes under a bridge.
//
// What one wake does (every SLEEP_NORMAL_S, every SLEEP_BURST_S while the river rises):
//   1. watchdog on (WDT_TIMEOUT_S for the whole wake: a hung modem or TLS handshake resets the
//      chip instead of draining the battery);
//   2. battery check: under HIBERNATE_MV it measures, buffers, and sleeps long with the radio off;
//   3. a burst of BURST_N samples (7-11), impossible values dropped, then a median with outlier
//      rejection around it (|x - median| > max(3 x IQR, MIN_REJECT_MM) is dropped), samples_ok,
//      samples_n and iqr_mm reported, err bits set;
//   4. the local siren: 3 of 3 readings at or above SIREN_LEVEL_CM switch the siren output on,
//      with no network needed (the all-must-agree check follows tepmachcha's validate(), MIT,
//      DAI Maker Lab); 3 of 3 below SIREN_CLEAR_CM switch it off;
//   5. the reading goes into a ring buffer in RTC memory (survives deep sleep); with a link it is
//      published live to .../reading at QoS 1, then up to BACKFILL_BATCH older buffered readings
//      go to .../backfill. A record leaves the buffer only after its PUBACK. The server stores
//      each (device, boot, seq) once, so a resend after a lost PUBACK is harmless, and backfilled
//      readings never alert;
//   6. burst mode: a rise of BURST_RISE_CM over the last BURST_WINDOW readings switches to
//      SLEEP_BURST_S (one a minute: the server keeps at most one live reading per minute).
//
// Payload v2 (the server also accepts v1):
//   {"v":2,"at":"2026-10-11T09:30:00Z","seq":1234,"boot":7,"distance_mm":2391,"water_level_cm":182.9,
//    "samples_ok":9,"samples_n":9,"iqr_mm":4,"quality":96,"err":0,"temp_c":24.5,"battery_mv":3290,
//    "solar_mv":5800,"rssi":-79,"fw":"pukaar-gauge-2.0.0","reset_cause":"deepsleep","buffered":false}
// distance_mm is raw: for an ultrasonic probe it assumes sound at 20 C; the server applies the
// temperature correction and the datum (mount height) it holds for this gauge, so a wrong
// MOUNT_HEIGHT_CM here cannot shift the stage the rules see. water_level_cm is sent for v1
// servers and for the local siren only.
//
// The ring buffer's record layout (a timestamp, then fixed fields) follows the LogBuffer class of
// EnviroDIY ModularSensors (BSD-3-Clause, Stroud Water Research Center); the code is new.

#include <Arduino.h>
#include <Network.h>
#include <NetworkClientSecure.h>
#include <PPP.h>
#include <WiFi.h>
#include <MQTT.h>  // 256dpi/arduino-mqtt (MIT)
#include <Preferences.h>
#include <esp_sleep.h>
#include <esp_task_wdt.h>
#include <time.h>

// ---------------------------------------------------------------- per-gauge settings
#define FW_VERSION "pukaar-gauge-2.0.0"
const char* VILLAGE_ID = "gohar";
const char* DEVICE_ID = "gauge-gohar-01";  // = the IoT thing name = the village's gauge.device_id
// `aws iot describe-endpoint --endpoint-type iot:Data-ATS` (printed by make gauge-provision)
const char* IOT_ENDPOINT = "REPLACE-ats.iot.ap-south-1.amazonaws.com";
const float MOUNT_HEIGHT_CM = 420.0;  // sensor face above the gauge zero (also set on the server)

#define SENSOR_RADAR 1  // 1 = DFRobot SEN0676 (Modbus over TTL UART), 0 = JSN-SR04T (trig/echo)
#define USE_CELLULAR 1  // 1 = Cat-1 modem over PPP, 0 = Wi-Fi
const char* APN = "internet";  // the SIM's APN (Jio: jionet, Airtel: airtelgprs.com, BSNL: bsnlnet)
const char* WIFI_SSID = "village-wifi";
const char* WIFI_PASS = "change-me";

const uint32_t SLEEP_NORMAL_S = 300;   // one reading every 5 minutes
const uint32_t SLEEP_BURST_S = 60;     // one a minute while rising
const float BURST_RISE_CM = 10.0;      // rise over BURST_WINDOW readings that starts burst mode
const int BURST_WINDOW = 3;
const uint32_t SLEEP_HIBERNATE_S = 1800;
const uint16_t HIBERNATE_MV = 3000;    // LiFePO4: about 10 % left; radio off below this
const uint16_t LOW_VOLTAGE_MV = 3150;  // err bit "low_voltage" below this
const uint32_t WDT_TIMEOUT_S = 90;

const float SIREN_LEVEL_CM = 300.0;    // local siren: set from the village's critical stage
const float SIREN_CLEAR_CM = 280.0;
const uint32_t SIREN_ON_S = 120;       // per wake while latched (a relay to a 12 V siren)

const int BURST_N = 9;                 // samples per reading (7-11)
const uint16_t MIN_REJECT_MM = 30;
const uint16_t MAX_IQR_MM = 150;       // wider: err bit "high_spread" (the server agrees at 150 mm)
#if SENSOR_RADAR
const uint16_t BLIND_MM = 150, MAX_MM = 40000;  // SEN0676: 0.15-40 m
#else
const uint16_t BLIND_MM = 250, MAX_MM = 4500;   // JSN-SR04T: about 25-450 cm
#endif

// ---------------------------------------------------------------- pins (ESP32-S3)
const int PIN_SENSOR_PWR = 4;   // P-MOSFET gate (low = on) for the sensor
const int PIN_RADAR_RX = 17, PIN_RADAR_TX = 18;  // SEN0676 TX -> 17, RX <- 18 (3.3 V TTL)
const int PIN_TRIG = 5, PIN_ECHO = 6;            // JSN-SR04T; echo through a 1k/2k divider
const int PIN_BATT = 1;         // 100k/100k divider from the LiFePO4 cell (ADC1)
const int PIN_SOLAR = 2;        // 100k/47k divider from the panel (ADC1)
const int PIN_SIREN = 7;        // N-MOSFET or relay driver for the siren
const int PIN_MODEM_PWR = 10;   // modem power key / enable
const int PIN_MODEM_TX = 11, PIN_MODEM_RX = 12, PIN_MODEM_RST = 13;
const float BATT_DIVIDER = 2.0, SOLAR_DIVIDER = 3.128;

// Error bits: keep in step with ERR_BITS in backend/src/Pukaar/services/gauge.py.
enum : uint16_t {
  ERR_NO_ECHO = 1, ERR_FEW_SAMPLES = 2, ERR_HIGH_SPREAD = 4, ERR_CLOCK_UNSYNCED = 8,
  ERR_LOW_VOLTAGE = 16, ERR_BUFFER_OVERFLOW = 32, ERR_WATCHDOG_RESET = 64, ERR_SENSOR_RANGE = 128,
};

// ---------------------------------------------------------------- certificates (PLACEHOLDERS)
// Amazon Root CA 1 (https://www.amazontrust.com/repository/AmazonRootCA1.pem).
static const char AWS_ROOT_CA[] = R"PEM(
-----BEGIN CERTIFICATE-----
MIIDQTCCAimgAwIBAgITBmyfz5m/jAo54vB4ikPmljZbyjANBgkqhkiG9w0BAQsF
ADA5MQswCQYDVQQGEwJVUzEPMA0GA1UEChMGQW1hem9uMRkwFwYDVQQDExBBbWF6
b24gUm9vdCBDQSAxMB4XDTE1MDUyNjAwMDAwMFoXDTM4MDExNzAwMDAwMFowOTEL
MAkGA1UEBhMCVVMxDzANBgNVBAoTBkFtYXpvbjEZMBcGA1UEAxMQQW1hem9uIFJv
b3QgQ0EgMTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBALJ4gHHKeNXj
ca9HgFB0fW7Y14h29Jlo91ghYPl0hAEvrAIthtOgQ3pOsqTQNroBvo3bSMgHFzZM
9O6II8c+6zf1tRn4SWiw3te5djgdYZ6k/oI2peVKVuRF4fn9tBb6dNqcmzU5L/qw
IFAGbHrQgLKm+a/sRxmPUDgH3KKHOVj4utWp+UhnMJbulHheb4mjUcAwhmahRWa6
VOujw5H5SNz/0egwLX0tdHA114gk957EWW67c4cX8jJGKLhD+rcdqsq08p8kDi1L
93FcXmn/6pUCyziKrlA4b9v7LWIbxcceVOF34GfID5yHI9Y/QCB/IIDEgEw+OyQm
jgSubJrIqg0CAwEAAaNCMEAwDwYDVR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8EBAMC
AYYwHQYDVR0OBBYEFIQYzIU07LwMlJQuCFmcx7IQTgoIMA0GCSqGSIb3DQEBCwUA
A4IBAQCY8jdaQZChGsV2USggNiMOruYou6r4lK5IpDB/G/wkjUu0yKGX9rbxenDI
U5PMCCjjmCXPI6T53iHTfIUJrU6adTrCC2qJeHZERxhlbI1Bjjt/msv0tadQ1wUs
N+gDS63pYaACbvXy8MWy7Vu33PqUXHeeE6V/Uq2V8viTO96LXFvKWlJbYK8U90vv
o/ufQJVtMVT8QtPHRh8jrdkPSHCa2XV4cdFyQzR1bldZwgJcJmApzyMZFo6IQ6XU
5MsI+yMRQ+hDKXJioaldXgjUkK642M4UwtBV8ob2xJNDd2ZhwLnoQdeXeGADbkpy
rqXRfboQnoZsG4q5WTP468SQvvG5
-----END CERTIFICATE-----
)PEM";
// From SSM /pukaar/gauge/<device>/cert and /key (make gauge-provision). Never commit a real key;
// turn on flash encryption so it cannot be read off the chip.
static const char DEVICE_CERT[] = R"PEM(
-----BEGIN CERTIFICATE-----
REPLACE WITH THE DEVICE CERTIFICATE
-----END CERTIFICATE-----
)PEM";
static const char DEVICE_KEY[] = R"PEM(
-----BEGIN RSA PRIVATE KEY-----
REPLACE WITH THE DEVICE PRIVATE KEY
-----END RSA PRIVATE KEY-----
)PEM";

// ---------------------------------------------------------------- state kept across deep sleep
struct Record {          // 24 bytes
  uint32_t at;           // UTC seconds
  uint32_t seq;
  uint16_t distance_mm;  // raw (0 = no reading)
  int16_t level_mm;      // device-side stage, for the siren and v1 servers
  uint16_t battery_mv;
  uint16_t solar_mv;
  uint16_t err;
  uint16_t iqr_mm;
  uint8_t samples_ok, samples_n;
  int8_t temp_c;
  uint8_t pad;
};
const int RING_N = 240;  // 5.8 KB of the S3's 8 KB RTC slow memory: 20 h at 5 min, 4 h at 1 min
RTC_DATA_ATTR Record ring[RING_N];
RTC_DATA_ATTR int ringHead = 0, ringCount = 0;  // ring[ringHead] is the oldest unsent
RTC_DATA_ATTR bool ringOverflow = false;
RTC_DATA_ATTR uint32_t seq = 0;
RTC_DATA_ATTR uint32_t bootCount = 0;       // copied from NVS on a cold boot
RTC_DATA_ATTR uint32_t lastSync = 0;        // last NTP sync, UTC seconds
RTC_DATA_ATTR float recent[3] = {NAN, NAN, NAN};  // last three good stages, newest last
RTC_DATA_ATTR bool sirenLatched = false;

NetworkClientSecure net;
MQTTClient mqtt(2560);
uint16_t errBits = 0;
const char* cause = "other";  // this wake's reset cause (sent with the live reading only)

// ---------------------------------------------------------------- small helpers
static int cmpU16(const void* a, const void* b) {
  return (int)*(const uint16_t*)a - (int)*(const uint16_t*)b;
}

static uint16_t quartile(const uint16_t* v, int n, int q) {  // q = 1 or 3, v sorted
  return v[(n - 1) * q / 4];
}

static uint16_t readMillivolts(int pin, float divider) {
  uint32_t mv = 0;
  for (int i = 0; i < 8; i++) mv += analogReadMilliVolts(pin);
  return (uint16_t)((mv / 8.0f) * divider);
}

static const char* resetCause() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: return "poweron";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_TASK_WDT: case ESP_RST_INT_WDT: case ESP_RST_WDT: return "wdt";
    case ESP_RST_PANIC: return "panic";
    case ESP_RST_SW: return "software";
    default: return "other";
  }
}

// ---------------------------------------------------------------- the sensor
#if SENSOR_RADAR
static uint16_t modbusCrc(const uint8_t* b, int n) {  // CRC-16/MODBUS, poly 0xA001 reflected
  uint16_t crc = 0xFFFF;
  for (int i = 0; i < n; i++) {
    crc ^= b[i];
    for (int k = 0; k < 8; k++) crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
  }
  return crc;
}

// Read one holding register (function 0x03) from the SEN0676 at address 1. Register 0x0001 is
// the distance from the sensor face to the water ("empty height"), in mm (DFRobot wiki SEN0676).
static bool radarRead(uint16_t reg, uint16_t& out) {
  uint8_t q[8] = {0x01, 0x03, (uint8_t)(reg >> 8), (uint8_t)reg, 0x00, 0x01, 0, 0};
  uint16_t c = modbusCrc(q, 6);
  q[6] = c & 0xFF; q[7] = c >> 8;
  while (Serial1.available()) Serial1.read();
  Serial1.write(q, 8);
  uint8_t r[7];
  int n = 0;
  uint32_t t0 = millis();
  while (n < 7 && millis() - t0 < 300) if (Serial1.available()) r[n++] = Serial1.read();
  if (n < 7 || r[0] != 0x01 || r[1] != 0x03 || r[2] != 2) return false;
  if (modbusCrc(r, 5) != (uint16_t)(r[5] | (r[6] << 8))) return false;
  out = (r[3] << 8) | r[4];
  return true;
}

static uint16_t sampleMm() {
  uint16_t d;
  return radarRead(0x0001, d) ? d : 0;
}
#else
static uint16_t sampleMm() {  // JSN-SR04T: echo time at 343.2 m/s (20 C); the server corrects for temp_c
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(5);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(20);
  digitalWrite(PIN_TRIG, LOW);
  unsigned long us = pulseIn(PIN_ECHO, HIGH, 30000UL);
  return us ? (uint16_t)(us * 0.3432f / 2.0f) : 0;
}
#endif

struct Burst { uint16_t distance_mm; uint8_t ok, n; uint16_t iqr_mm; };

// BURST_N samples; drop impossible ones; median; drop samples far from it; median of the rest.
static Burst measure() {
  uint16_t v[16];
  int n = 0;
  bool rangeHit = false;
  for (int i = 0; i < BURST_N; i++) {
    uint16_t d = sampleMm();
    if (d == 0) { /* no echo or no reply */ }
    else if (d <= BLIND_MM || d >= MAX_MM) rangeHit = true;
    else v[n++] = d;
    delay(SENSOR_RADAR ? 120 : 70);
    esp_task_wdt_reset();
  }
  Burst b = {0, 0, (uint8_t)BURST_N, 0};
  if (n == 0) {
    errBits |= rangeHit ? ERR_SENSOR_RANGE : ERR_NO_ECHO;
    return b;
  }
  qsort(v, n, sizeof v[0], cmpU16);
  uint16_t med = v[n / 2];
  uint16_t iqr = n >= 4 ? quartile(v, n, 3) - quartile(v, n, 1) : 0;
  uint16_t limit = max<uint16_t>(MIN_REJECT_MM, 3 * iqr);
  uint16_t kept[16];
  int k = 0;
  for (int i = 0; i < n; i++) if (abs((int)v[i] - (int)med) <= limit) kept[k++] = v[i];
  b.distance_mm = kept[k / 2];  // kept is still sorted
  b.ok = k;
  b.iqr_mm = iqr;
  if (k * 2 < BURST_N) errBits |= ERR_FEW_SAMPLES;
  if (iqr > MAX_IQR_MM) errBits |= ERR_HIGH_SPREAD;
  return b;
}

// ---------------------------------------------------------------- ring buffer
static void ringPush(const Record& r) {
  if (ringCount == RING_N) {  // full: drop the oldest, say so
    ringHead = (ringHead + 1) % RING_N;
    ringCount--;
    ringOverflow = true;
  }
  ring[(ringHead + ringCount) % RING_N] = r;
  ringCount++;
}

static void isoTime(uint32_t t, char* out, size_t len) {
  time_t tt = t;
  struct tm tm;
  gmtime_r(&tt, &tm);
  strftime(out, len, "%Y-%m-%dT%H:%M:%SZ", &tm);
}

// One payload-v2 reading. The live one also carries this wake's reset cause and, on Wi-Fi, the RSSI.
static int recordJson(const Record& r, bool buffered, char* out, size_t len) {
  char at[25];
  isoTime(r.at, at, sizeof at);
  uint8_t quality = r.samples_n ? (uint8_t)(100 * r.samples_ok / r.samples_n) : 0;
  char extra[64] = "";
  if (!buffered) {
#if USE_CELLULAR
    snprintf(extra, sizeof extra, ",\"reset_cause\":\"%s\"", cause);
#else
    snprintf(extra, sizeof extra, ",\"reset_cause\":\"%s\",\"rssi\":%d", cause, (int)WiFi.RSSI());
#endif
  }
  return snprintf(out, len,
      "{\"v\":2,\"at\":\"%s\",\"seq\":%lu,\"boot\":%lu,\"distance_mm\":%u,\"water_level_cm\":%.1f,"
      "\"samples_ok\":%u,\"samples_n\":%u,\"iqr_mm\":%u,\"quality\":%u,\"err\":%u,\"temp_c\":%d,"
      "\"battery_mv\":%u,\"solar_mv\":%u,\"fw\":\"%s\",\"buffered\":%s%s}",
      at, (unsigned long)r.seq, (unsigned long)bootCount, r.distance_mm, r.level_mm / 10.0f, r.samples_ok,
      r.samples_n, r.iqr_mm, quality, r.err, r.temp_c, r.battery_mv, r.solar_mv, FW_VERSION,
      buffered ? "true" : "false", extra);
}

// ---------------------------------------------------------------- the link
static bool linkUp() {
#if USE_CELLULAR
  pinMode(PIN_MODEM_PWR, OUTPUT);
  digitalWrite(PIN_MODEM_PWR, HIGH);
  PPP.setApn(APN);
  PPP.setResetPin(PIN_MODEM_RST, false, 200);
  PPP.setPins(PIN_MODEM_TX, PIN_MODEM_RX);
  if (!PPP.begin(PPP_MODEM_SIM7600)) return false;  // the A76xx speak the SIM7600 AT set
  for (int i = 0; i < 60 && !PPP.attached(); i++) { delay(500); esp_task_wdt_reset(); }
  if (!PPP.attached()) return false;
  PPP.mode(ESP_MODEM_MODE_CMUX);
  for (int i = 0; i < 60 && !PPP.connected(); i++) { delay(500); esp_task_wdt_reset(); }
  return PPP.connected();
#else
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) { delay(250); esp_task_wdt_reset(); }
  return WiFi.status() == WL_CONNECTED;
#endif
}

static void linkDown() {
  mqtt.disconnect();
  net.stop();
#if USE_CELLULAR
  PPP.end();
  digitalWrite(PIN_MODEM_PWR, LOW);
#else
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
#endif
}

static bool syncClock() {  // TLS needs a true clock, and so does every reading's "at"
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  for (int i = 0; i < 40; i++) {
    if (time(nullptr) > 1700000000) { lastSync = time(nullptr); return true; }
    delay(250);
  }
  return false;
}

static bool iotUp() {
  net.setCACert(AWS_ROOT_CA);
  net.setCertificate(DEVICE_CERT);
  net.setPrivateKey(DEVICE_KEY);
  mqtt.begin(IOT_ENDPOINT, 8883, net);
  mqtt.setOptions(30, true, 10000);  // keep-alive s, clean session, command timeout ms
  return mqtt.connect(DEVICE_ID);    // client id must equal the thing name (IoT policy)
}

static bool publishQos1(const char* kind, const char* body) {
  char topic[128];
  snprintf(topic, sizeof topic, "pukaar/gauge/%s/%s/%s", VILLAGE_ID, DEVICE_ID, kind);
  bool ok = mqtt.publish(topic, body, false, 1);  // returns after the PUBACK
  esp_task_wdt_reset();
  return ok;
}

// Live first (this wake's record, if there is one), then backfill in batches, oldest first. A
// record leaves the buffer only after its PUBACK. An older record is never sent as live: the
// server refuses a live timestamp more than ten minutes old, and it would be lost.
static void sendAll(bool liveThisWake) {
  static char body[2400];
  if (ringCount == 0) return;
  if (liveThisWake) {
    int newest = (ringHead + ringCount - 1) % RING_N;
    recordJson(ring[newest], false, body, sizeof body);
    if (!publishQos1("reading", body)) return;
    ringCount--;  // the newest is out; the oldest-first order of the rest is unchanged
  }
  const int BACKFILL_BATCH = 5;  // about 1.6 KB per message, well inside body[] and the MQTT buffer
  while (ringCount > 0) {
    int n = min(BACKFILL_BATCH, ringCount);
    int len = snprintf(body, sizeof body, "{\"readings\":[");
    for (int i = 0; i < n; i++) {
      if (i) body[len++] = ',';
      len += recordJson(ring[(ringHead + i) % RING_N], true, body + len, sizeof body - len - 4);
    }
    snprintf(body + len, sizeof body - len, "]}");
    if (!publishQos1("backfill", body)) return;  // try again next wake
    ringHead = (ringHead + n) % RING_N;
    ringCount -= n;
  }
  ringOverflow = false;
}

// ---------------------------------------------------------------- siren and burst mode
static void remember(float stage) {
  recent[0] = recent[1];
  recent[1] = recent[2];
  recent[2] = stage;
}

static bool allThree(bool above, float mark) {
  for (int i = 0; i < 3; i++) {
    if (isnan(recent[i])) return false;
    if (above ? recent[i] < mark : recent[i] >= mark) return false;
  }
  return true;
}

static void siren(uint16_t batteryMv) {
  if (!sirenLatched && allThree(true, SIREN_LEVEL_CM)) sirenLatched = true;   // 3 of 3 at or above
  if (sirenLatched && allThree(false, SIREN_CLEAR_CM)) sirenLatched = false;  // 3 of 3 clear
  if (!sirenLatched || batteryMv < HIBERNATE_MV) return;
  digitalWrite(PIN_SIREN, HIGH);
  for (uint32_t s = 0; s < SIREN_ON_S; s++) { delay(1000); esp_task_wdt_reset(); }
  digitalWrite(PIN_SIREN, LOW);
}

static uint32_t nextSleep() {
  if (isnan(recent[0]) || isnan(recent[2])) return SLEEP_NORMAL_S;
  return recent[2] - recent[0] >= BURST_RISE_CM ? SLEEP_BURST_S : SLEEP_NORMAL_S;
}

static void sleepFor(uint32_t s) {
  pinMode(PIN_SIREN, OUTPUT);
  digitalWrite(PIN_SIREN, LOW);
  esp_sleep_enable_timer_wakeup((uint64_t)s * 1000000ULL);
  esp_deep_sleep_start();
}

// ---------------------------------------------------------------- one wake
void setup() {
  esp_task_wdt_config_t wdt = {WDT_TIMEOUT_S * 1000, 0, true};  // timeout, no idle cores, panic -> reset
  esp_task_wdt_reconfigure(&wdt);
  esp_task_wdt_add(nullptr);

  cause = resetCause();
  if (esp_reset_reason() != ESP_RST_DEEPSLEEP) {  // cold boot: new boot number, seq starts again
    Preferences p;
    p.begin("pukaar", false);
    bootCount = p.getUInt("boot", 0) + 1;
    p.putUInt("boot", bootCount);
    p.end();
    seq = 0;
    if (!strcmp(cause, "wdt") || !strcmp(cause, "brownout")) errBits |= ERR_WATCHDOG_RESET;
  }
  pinMode(PIN_SIREN, OUTPUT);
  digitalWrite(PIN_SIREN, LOW);

  uint16_t batt = readMillivolts(PIN_BATT, BATT_DIVIDER);
  uint16_t solar = readMillivolts(PIN_SOLAR, SOLAR_DIVIDER);
  if (batt < LOW_VOLTAGE_MV) errBits |= ERR_LOW_VOLTAGE;

  pinMode(PIN_SENSOR_PWR, OUTPUT);
  digitalWrite(PIN_SENSOR_PWR, LOW);  // sensor on
#if SENSOR_RADAR
  Serial1.begin(115200, SERIAL_8N1, PIN_RADAR_RX, PIN_RADAR_TX);
  delay(1500);  // radar start-up
#else
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  delay(300);
#endif
  Burst b = measure();
  digitalWrite(PIN_SENSOR_PWR, HIGH);  // sensor off

  time_t now = time(nullptr);  // the RTC keeps time across deep sleep
  if (lastSync == 0 || (uint32_t)now - lastSync > 86400) errBits |= ERR_CLOCK_UNSYNCED;
  if (ringOverflow) errBits |= ERR_BUFFER_OVERFLOW;

  Record r = {};
  r.at = (uint32_t)now;
  r.seq = ++seq;
  r.distance_mm = b.distance_mm;
  r.level_mm = b.distance_mm ? (int16_t)((MOUNT_HEIGHT_CM * 10.0f) - b.distance_mm) : 0;
  r.battery_mv = batt;
  r.solar_mv = solar;
  r.err = errBits;
  r.samples_ok = b.ok;
  r.samples_n = b.n;
  r.iqr_mm = b.iqr_mm;
  r.temp_c = (int8_t)temperatureRead();  // the S3's die temperature: a rough proxy; a DS18B20 in the box is better
  bool good = b.distance_mm && !(errBits & (ERR_NO_ECHO | ERR_FEW_SAMPLES | ERR_HIGH_SPREAD | ERR_SENSOR_RANGE));
  if (good) remember(r.level_mm / 10.0f);
  bool pushed = now > 1700000000 && b.distance_mm;  // no stage, or no idea of the time: nothing to send
  if (pushed) ringPush(r);

  siren(batt);  // works with no network at all

  if (batt < HIBERNATE_MV) sleepFor(SLEEP_HIBERNATE_S);  // radio off; the buffer keeps the record

  if (linkUp() && (time(nullptr) > 1700000000 || syncClock())) {
    if ((uint32_t)time(nullptr) - lastSync > 3600) syncClock();
    if (iotUp()) sendAll(pushed);
  }
  linkDown();
  sleepFor(nextSleep());
}

void loop() {}  // never reached: every path ends in deep sleep
