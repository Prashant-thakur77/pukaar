// Pukaar LoRa relay (spec 3.4, 7.3): a ridge-top store-and-forward node where a valley bend blocks the
// line of sight. Heltec WiFi LoRa 32 V3 (ESP32-S3 + a bare SX1262, driven by RadioLib, MIT).
//
// *** UNTESTED ON HARDWARE. *** It compiles for the Heltec V3 (arduino-esp32 3.x). The decisions are in
// lib/pukaar_common/pkr_box.cpp (RelayCore) and tested on the host, including a cloud command carried
// box -> relay -> siren byte for byte (test_nodes).
//
//   - On every received frame that is well-formed and whose (src, ctr) it has not seen in 10 minutes,
//     it re-transmits the frame unchanged after a random 50-500 ms, within a 10 % hourly airtime budget
//     (alarm frames may use all of it, telemetry 70 %).
//   - It holds no sender keys, so it cannot check or forge a MAC: receivers check the origin's.
//   - Every 15 minutes it sends its own RELAY_BEACON (bus voltage, SoC, noise floor), signed with its
//     own key.
//   - Between frames it light-sleeps; DIO1 (packet received) wakes it.
//
// The radio plan is the schema's (865.4025 MHz, SF10, 125 kHz, CR 4/5, sync 0x12, 22 dBm). The other
// nodes use Ebyte E22 UART modules, which tune on a 1 MHz raster from 850.125 MHz and hide SF and
// bandwidth behind an "air data rate": whether a bare SX1262 and an E22 hear each other at all is the
// first bench test (firmware/README.md, open items). Until it passes, deploy relays only with nodes
// on the same radio.
#include <Arduino.h>
#include <RadioLib.h>
#include <SPI.h>
#include <esp_sleep.h>
#include <esp_task_wdt.h>
#include <time.h>

#include "pkr_box.h"
#include "pukaar_hal.h"

using namespace pkr;

#ifndef PUKAAR_FW
#define PUKAAR_FW "pukaar-relay-0.1.0"
#endif

// ---------------------------------------------------------------- Heltec WiFi LoRa 32 V3 pins
static const int PIN_LORA_NSS = 8, PIN_LORA_SCK = 9, PIN_LORA_MOSI = 10, PIN_LORA_MISO = 11;
static const int PIN_LORA_RST = 12, PIN_LORA_BUSY = 13, PIN_LORA_DIO1 = 14;
static const int PIN_VBAT = 1;       // battery through 390k / 100k
static const int PIN_ADC_CTRL = 37;  // enables that divider (its polarity differs between V3 board revisions: bench item)
static const int PIN_VEXT = 36;      // LOW powers the OLED rail: kept off
static const float VBAT_DIVIDER = 490.0f / 100.0f;

static SX1262 sx = new Module(PIN_LORA_NSS, PIN_LORA_DIO1, PIN_LORA_RST, PIN_LORA_BUSY);
static volatile bool g_rx_flag = false;

static void IRAM_ATTR on_dio1() { g_rx_flag = true; }

// RadioPort over RadioLib: transmit blocks for the airtime, then the radio listens again.
class Sx1262Radio : public RadioPort {
 public:
  bool begin() {
    SPI.begin(PIN_LORA_SCK, PIN_LORA_MISO, PIN_LORA_MOSI, PIN_LORA_NSS);
    int st = sx.begin(PKR_RADIO_FREQ_PRIMARY_HZ / 1e6f, PKR_RADIO_BW_HZ / 1e3f, PKR_RADIO_SF, PKR_RADIO_CR,
                      PKR_RADIO_SYNC_WORD, PKR_RADIO_TX_DBM, PKR_RADIO_PREAMBLE, 1.8f /* the V3's TCXO */);
    if (st != RADIOLIB_ERR_NONE) return false;
    sx.setCRC(true);
    sx.setDio1Action(on_dio1);
    return sx.startReceive() == RADIOLIB_ERR_NONE;
  }
  bool transmit(const uint8_t* buf, size_t n) override {
    int st = sx.transmit(buf, n);
    g_rx_flag = false;  // the TX-done interrupt is on DIO1 too
    sx.startReceive();
    return st == RADIOLIB_ERR_NONE;
  }
  size_t receive(uint8_t* buf, size_t cap) override {
    if (!g_rx_flag) return 0;
    g_rx_flag = false;
    size_t n = sx.getPacketLength();
    int st = (n && n <= cap) ? sx.readData(buf, n) : RADIOLIB_ERR_PACKET_TOO_LONG;
    sx.startReceive();
    return st == RADIOLIB_ERR_NONE ? n : 0;
  }
  int8_t noise_dbm() {  // the channel's instantaneous RSSI while nothing is being received
    float r = sx.getRSSI(false);
    return (int8_t)(r < -128 ? -128 : r > 0 ? 0 : r);
  }
};

static Sx1262Radio radio;
static NvsKv nvs;
static KeyRing keys;
static FrameSigner signer;
static LoraLink lora;
static RelayCore relay;
static char device[48] = {0};

static uint32_t rnd() { return esp_random(); }

// No clock on a ridge (no modem, no Wi-Fi): seconds since boot drive the airtime window, and the
// relay's own beacons carry ts 0 ("unsynced"). Forwarded frames keep their sender's ts.
static uint32_t now_s() { return millis() / 1000u; }

static pkr_beacon_payload_t beacon_now() {
  digitalWrite(PIN_ADC_CTRL, HIGH);
  delay(5);
  uint32_t mv = 0;
  for (int i = 0; i < 8; i++) mv += analogReadMilliVolts(PIN_VBAT);
  digitalWrite(PIN_ADC_CTRL, LOW);
  float v = mv / 8.0f * VBAT_DIVIDER / 1000.0f;  // a 1S Li-ion or the 12.8 V pack through its own divider: bench
  pkr_beacon_payload_t b{};
  b.bus_dv = (uint16_t)(v * 10.0f);
  b.bus_ma = 0;  // no current sensor on the board (an INA226 on the bus is the upgrade)
  b.soc = (uint8_t)(v >= 4.1f ? 100 : v <= 3.3f ? 0 : (v - 3.3f) / 0.8f * 100.0f);
  b.noise_dbm = radio.noise_dbm();
  return b;
}

void setup() {
  pinMode(PIN_VEXT, OUTPUT);
  digitalWrite(PIN_VEXT, HIGH);  // OLED rail off
  pinMode(PIN_ADC_CTRL, OUTPUT);
  digitalWrite(PIN_ADC_CTRL, LOW);
  Serial.begin(115200);
  esp_task_wdt_config_t wdt = {30000, 0, true};
  esp_task_wdt_reconfigure(&wdt);
  esp_task_wdt_add(nullptr);
  nvs.begin("pukaar");
  load_provisioned_keys(keys, device, sizeof device);  // its own key only: it never holds a sender's
  signer.begin(&keys, &nvs);
  bool ok = radio.begin();
  Serial.printf("pukaar relay %s %s radio=%s\n", PUKAAR_FW, device, ok ? "ok" : "FAILED");
  lora.begin(&radio, &signer, PKR_DUTY_RELAY_BUDGET_MS);
  relay.begin(&lora, keys.addr(), rnd);
  gpio_wakeup_enable((gpio_num_t)PIN_LORA_DIO1, GPIO_INTR_HIGH_LEVEL);
  esp_sleep_enable_gpio_wakeup();
}

void loop() {
  uint8_t buf[PKR_FRAME_MAX_LEN];
  size_t n = radio.receive(buf, sizeof buf);
  if (n) relay.on_rx(buf, n, millis());
  static pkr_beacon_payload_t beacon = beacon_now();
  static uint32_t last_measure = 0;
  if (millis() - last_measure > 60000u) {
    last_measure = millis();
    beacon = beacon_now();
  }
  relay.tick(millis(), now_s(), false, beacon);
  esp_task_wdt_reset();
  // light sleep until the radio has a packet (DIO1) or the next forward is due (at most 50 ms away
  // once one is queued; otherwise a second, so the beacon and the watchdog keep their time)
  if (!g_rx_flag) {
    esp_sleep_enable_timer_wakeup(relay.pending() ? 20000ULL : 1000000ULL);
    esp_light_sleep_start();
  }
}
