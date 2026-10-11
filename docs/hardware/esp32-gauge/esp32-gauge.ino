// Pukaar river gauge: ESP32-WROOM + JSN-SR04T waterproof ultrasonic sensor under a bridge deck.
//
// UNTESTED ON HARDWARE. Written against the arduino-esp32 core (2.x / 3.x) to compile in
// principle; check pins, timings and the stage arithmetic on a bench before mounting it.
//
// Every 60 s: power the sensor, take the median of 5 pings, stage = mount height - distance,
// read the battery, sync time over NTP, sign the JSON body with HMAC-SHA256 and POST it to
//   POST {API_BASE}/sensors/{VILLAGE_ID}/readings   header X-Pukaar-Signature: <hex>
// then deep sleep. A tipping-bucket rain gauge on GPIO 33 wakes the chip for each tip and is
// counted in RTC memory. See docs/hardware/README.md for wiring and the signature.

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <time.h>
#include "esp_sleep.h"
#include "mbedtls/md.h"

// ---------------------------------------------------------------- per-gauge settings
const char* WIFI_SSID = "village-wifi";
const char* WIFI_PASS = "change-me";
const char* API_BASE = "https://REPLACE.execute-api.us-east-1.amazonaws.com";  // stack output ApiUrl
const char* VILLAGE_ID = "gohar";
const char* DEVICE_ID = "gauge-gohar-01";  // must equal the village's gauge.device_id
// 64 hex chars from: python -m Pukaar.scripts.gauge_sim --print-key gauge-gohar-01
const char* DEVICE_KEY = "0000000000000000000000000000000000000000000000000000000000000000";
const float MOUNT_HEIGHT_CM = 420.0;  // sensor face above the gauge zero, measured at install
const uint32_t SLEEP_S = 60;
// Amazon Root CA 1 PEM (https://www.amazontrust.com/repository/AmazonRootCA1.pem). Leave
// nullptr only on the bench: the body is still signed, but the server is not verified.
const char* ROOT_CA = nullptr;

// ---------------------------------------------------------------- pins
const int PIN_TRIG = 5;
const int PIN_ECHO = 18;        // through a 1k/2k divider: the JSN-SR04T echo is 5 V
const int PIN_SENSOR_PWR = 25;  // gate of the P-MOSFET that powers the sensor
const int PIN_BATT = 34;        // 100k/100k divider from the 18650
const gpio_num_t PIN_RAIN = GPIO_NUM_33;  // reed switch to GND, 10k pull-up to 3.3 V
const float BATT_DIVIDER = 2.0;
const float MM_PER_TIP = 0.2794;  // check the bucket's own calibration

RTC_DATA_ATTR uint32_t rainTips = 0;  // survive deep sleep
RTC_DATA_ATTR uint32_t hourBaseTips = 0;
RTC_DATA_ATTR time_t hourStart = 0;
RTC_DATA_ATTR time_t nextMeasure = 0;

static float pingCm() {
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(5);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(20);
  digitalWrite(PIN_TRIG, LOW);
  unsigned long us = pulseIn(PIN_ECHO, HIGH, 30000UL);  // about 5 m round trip
  if (us == 0) return NAN;
  return us * 0.0343f / 2.0f;  // speed of sound at about 20 C
}

static float medianDistanceCm() {
  float v[5];
  int n = 0;
  for (int i = 0; i < 5; i++) {
    float d = pingCm();
    if (!isnan(d) && d > 20.0f && d < 600.0f) v[n++] = d;  // JSN-SR04T blind zone is about 20 cm
    delay(70);
  }
  if (n < 3) return NAN;
  for (int i = 1; i < n; i++)  // insertion sort, n <= 5
    for (int j = i; j > 0 && v[j] < v[j - 1]; j--) { float t = v[j]; v[j] = v[j - 1]; v[j - 1] = t; }
  return v[n / 2];
}

static float batteryV() {
  uint32_t mv = 0;
  for (int i = 0; i < 8; i++) mv += analogReadMilliVolts(PIN_BATT);
  return (mv / 8.0f) * BATT_DIVIDER / 1000.0f;
}

static String hmacHex(const char* key, const String& body) {
  unsigned char out[32];
  const mbedtls_md_info_t* info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  mbedtls_md_hmac(info, (const unsigned char*)key, strlen(key), (const unsigned char*)body.c_str(), body.length(), out);
  char hex[65];
  for (int i = 0; i < 32; i++) sprintf(hex + 2 * i, "%02x", out[i]);
  hex[64] = 0;
  return String(hex);
}

static bool wifiUp() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  return WiFi.status() == WL_CONNECTED;
}

static bool ntpTime() {
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  for (int i = 0; i < 40; i++) {
    if (time(nullptr) > 1700000000) return true;
    delay(250);
  }
  return false;
}

static int postReading(const String& body) {
  WiFiClientSecure tls;
  if (ROOT_CA) tls.setCACert(ROOT_CA); else tls.setInsecure();
  HTTPClient http;
  String url = String(API_BASE) + "/sensors/" + VILLAGE_ID + "/readings";
  if (!http.begin(tls, url)) return -1;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Pukaar-Signature", hmacHex(DEVICE_KEY, body));
  int code = http.POST(body);
  http.end();
  return code;  // 202 accepted or ignored; 401 bad key or clock; 403 wrong device
}

// GSM fallback (SIM800L on UART2, see README) is not written yet: return false so the
// reading is simply skipped. Without Wi-Fi there is no NTP time either, so a GSM build
// must take its clock from the modem (AT+CCLK? after AT+CLTS=1) before signing.
static bool postViaGsm(const String& body) { (void)body; return false; }

static void sleepUntilNext() {
  time_t now = time(nullptr);
  long left = (long)(nextMeasure - now);
  if (left < 1 || left > (long)SLEEP_S) left = SLEEP_S;
  esp_sleep_enable_timer_wakeup((uint64_t)left * 1000000ULL);
  esp_sleep_enable_ext0_wakeup(PIN_RAIN, 0);  // a bucket tip pulls the pin low
  esp_deep_sleep_start();
}

void setup() {
  if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0) {
    rainTips++;
    pinMode(PIN_RAIN, INPUT);
    for (int i = 0; i < 40 && digitalRead(PIN_RAIN) == LOW; i++) delay(10);  // debounce the reed
    sleepUntilNext();
  }

  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  pinMode(PIN_SENSOR_PWR, OUTPUT);
  digitalWrite(PIN_SENSOR_PWR, LOW);  // P-MOSFET on
  delay(300);
  float dist = medianDistanceCm();
  digitalWrite(PIN_SENSOR_PWR, HIGH);  // sensor off
  float batt = batteryV();

  bool online = wifiUp();
  bool timed = online && ntpTime();
  time_t now = time(nullptr);
  nextMeasure = now + SLEEP_S;
  if (!timed || isnan(dist)) {  // no trusted timestamp, or no echo: send nothing
    sleepUntilNext();
  }

  if (now - hourStart >= 3600) { hourStart = now; hourBaseTips = rainTips; }
  float rain1h = (rainTips - hourBaseTips) * MM_PER_TIP;
  float stage = MOUNT_HEIGHT_CM - dist;

  struct tm tm;
  gmtime_r(&now, &tm);
  char at[25];
  strftime(at, sizeof at, "%Y-%m-%dT%H:%M:%SZ", &tm);
  char buf[256];
  snprintf(buf, sizeof buf,
           "{\"device_id\":\"%s\",\"at\":\"%s\",\"water_level_cm\":%.1f,\"rain_mm_1h\":%.2f,\"battery_v\":%.2f,\"rssi\":%d}",
           DEVICE_ID, at, stage, rain1h, batt, (int)WiFi.RSSI());
  String body(buf);

  if (postReading(body) < 0) postViaGsm(body);  // TLS or connection failure
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  sleepUntilNext();
}

void loop() {}  // never reached: every path ends in deep sleep
