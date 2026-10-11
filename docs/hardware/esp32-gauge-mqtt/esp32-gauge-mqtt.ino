// Pukaar river gauge over MQTT: ESP32-WROOM + JSN-SR04T under a bridge deck, publishing to
// AWS IoT Core with its own X.509 certificate. The recommended path (docs/hardware/README.md).
//
// UNTESTED ON HARDWARE. Written against the arduino-esp32 core (2.x / 3.x) and PubSubClient
// 2.8 (Nick O'Leary) to compile in principle; check pins, timings and the stage arithmetic on a
// bench before mounting it.
//
// Every 60 s: power the sensor, take the median of 5 pings, stage = mount height - distance,
// read the battery, join Wi-Fi, sync time over NTP (TLS needs a real clock to check the server's
// certificate, and the reading needs a true timestamp), connect to the account's ATS endpoint
// with mutual TLS on port 8883 (or 443 with ALPN "x-amzn-mqtt-ca" where 8883 is blocked), publish
// one JSON reading to
//   pukaar/gauge/{VILLAGE_ID}/{DEVICE_ID}/reading
// then deep sleep. A tipping-bucket rain gauge on GPIO 33 wakes the chip for each tip and is
// counted in RTC memory.
//
// No HMAC here: the certificate is the device's identity. The IoT policy lets it connect only
// with client id == its thing name (DEVICE_ID) and publish only to its own reading topic.
// Provision with `make gauge-provision VILLAGE=gohar`, then copy the certificate and private key
// from SSM (/pukaar/gauge/<device>/cert and /key) into the two PEM strings below. In production,
// turn on flash encryption so the private key cannot be read off the chip.

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <time.h>
#include "esp_sleep.h"

// ---------------------------------------------------------------- per-gauge settings
const char* WIFI_SSID = "village-wifi";
const char* WIFI_PASS = "change-me";
// `aws iot describe-endpoint --endpoint-type iot:Data-ATS` (printed by make gauge-provision)
const char* IOT_ENDPOINT = "REPLACE-ats.iot.us-east-1.amazonaws.com";
const char* VILLAGE_ID = "gohar";
const char* DEVICE_ID = "gauge-gohar-01";  // = the IoT thing name = the village's gauge.device_id
const float MOUNT_HEIGHT_CM = 420.0;       // sensor face above the gauge zero, measured at install
const uint32_t SLEEP_S = 60;
// Port 8883 is MQTT over TLS. Some networks block it; AWS IoT also accepts MQTT with X.509 on
// 443 when the client offers the ALPN protocol "x-amzn-mqtt-ca". 1 = try 443 if 8883 fails.
#define USE_ALPN_443_FALLBACK 1

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

// From SSM /pukaar/gauge/<device>/cert (the device certificate). PLACEHOLDER.
static const char DEVICE_CERT[] = R"PEM(
-----BEGIN CERTIFICATE-----
REPLACE WITH THE DEVICE CERTIFICATE
-----END CERTIFICATE-----
)PEM";

// From SSM /pukaar/gauge/<device>/key (the device private key). PLACEHOLDER: never commit a real key.
static const char DEVICE_KEY[] = R"PEM(
-----BEGIN RSA PRIVATE KEY-----
REPLACE WITH THE DEVICE PRIVATE KEY
-----END RSA PRIVATE KEY-----
)PEM";

// ---------------------------------------------------------------- pins (as the HTTPS sketch)
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

// Median of 5 pings; a splash, a leaf or a missed echo cannot move the reading on its own.
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

static bool wifiUp() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  return WiFi.status() == WL_CONNECTED;
}

// NTP before TLS: without a real clock the certificate check fails, and the reading's "at" must
// be true UTC (the server rejects one more than ten minutes off).
static bool ntpTime() {
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  for (int i = 0; i < 40; i++) {
    if (time(nullptr) > 1700000000) return true;
    delay(250);
  }
  return false;
}

static WiFiClientSecure net;
static PubSubClient mqtt(net);

static bool mqttConnect(uint16_t port) {
  mqtt.setServer(IOT_ENDPOINT, port);
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(30);
  mqtt.setSocketTimeout(10);
  return mqtt.connect(DEVICE_ID);  // client id must equal the thing name (IoT policy)
}

static bool connectIot() {
  net.setCACert(AWS_ROOT_CA);
  net.setCertificate(DEVICE_CERT);
  net.setPrivateKey(DEVICE_KEY);
  if (mqttConnect(8883)) return true;
#if USE_ALPN_443_FALLBACK
  // MQTT on 443 needs the ALPN protocol name; available in arduino-esp32 2.0.x and later.
  static const char* alpn[] = {"x-amzn-mqtt-ca", nullptr};
  net.stop();
  net.setAlpnProtocols(alpn);
  if (mqttConnect(443)) return true;
#endif
  return false;  // mqtt.state(): -2 network/TLS, 5 not authorised (policy or certificate)
}

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
  if (!timed || isnan(dist)) {  // no trusted clock (so no TLS either), or no echo: send nothing
    sleepUntilNext();
  }

  if (now - hourStart >= 3600) { hourStart = now; hourBaseTips = rainTips; }
  float rain1h = (rainTips - hourBaseTips) * MM_PER_TIP;
  float stage = MOUNT_HEIGHT_CM - dist;

  struct tm tm;
  gmtime_r(&now, &tm);
  char at[25];
  strftime(at, sizeof at, "%Y-%m-%dT%H:%M:%SZ", &tm);
  // No device_id or village_id in the body: the topic carries them, and the policy pins the
  // topic to this certificate. The topic rule adds both before the Lambda sees the reading.
  char body[192];
  snprintf(body, sizeof body,
           "{\"at\":\"%s\",\"water_level_cm\":%.1f,\"rain_mm_1h\":%.2f,\"battery_v\":%.2f,\"rssi\":%d}",
           at, stage, rain1h, batt, (int)WiFi.RSSI());
  char topic[128];
  snprintf(topic, sizeof topic, "pukaar/gauge/%s/%s/reading", VILLAGE_ID, DEVICE_ID);

  if (connectIot()) {
    mqtt.publish(topic, body);  // PubSubClient publishes at QoS 0: a lost reading is replaced in a minute
    for (int i = 0; i < 10; i++) { mqtt.loop(); delay(50); }  // let the TLS write drain
    mqtt.disconnect();
  }
  net.stop();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  sleepUntilNext();
}

void loop() {}  // never reached: every path ends in deep sleep
