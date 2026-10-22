// Thin ESP32 drivers behind the interfaces of lib/pukaar_common. Everything with logic in it lives
// in pukaar_common and is tested on the host; what is here only moves bytes. UNTESTED ON HARDWARE.
#pragma once

#include <Arduino.h>

#include "pkr_box.h"
#include "pkr_event.h"
#include "pkr_lora.h"
#include "pkr_node.h"
#include "pkr_outbox.h"
#include "pkr_store.h"

namespace pkr {

// ---------------------------------------------------------------- storage

class NvsKv : public Kv {
 public:
  bool begin(const char* ns);
  bool get_u32(const char* key, uint32_t* out) override;
  bool put_u32(const char* key, uint32_t v) override;
  size_t get_blob(const char* key, void* buf, size_t cap) override;
  bool put_blob(const char* key, const void* data, size_t len) override;

 private:
  char ns_[16] = {0};
};

class LittleFsFs : public Fs {
 public:
  bool begin();  // mounts (formats on first use) and makes /ob/a, /ob/t
  bool read(const char* path, uint32_t off, void* buf, uint32_t len, uint32_t* got) override;
  bool append(const char* path, const void* data, uint32_t len) override;
  bool write(const char* path, const void* data, uint32_t len) override;
  int32_t size(const char* path) override;
  bool remove(const char* path) override;
  bool rename(const char* from, const char* to) override;
};

// Boot counter (a new boot number each cold start; events are unique on (device, boot, seq)).
uint32_t next_boot_number(Kv& kv);

// Keys from the provisioning NVS image (namespace "pkr-keys"): the device id, its LoRa address,
// its own keys by kid ("self<kid>", 32 bytes) and the senders it trusts ("snd<n>", a
// ProvisionedSender). Returns false when there is no key: the device then refuses every signed
// command (FAULT no_keys) but still sounds for its own key switch.
struct ProvisionedSender {
  uint16_t addr;
  uint8_t kid, roles;
  char device[40];
  uint8_t key[32];
};
bool load_provisioned_keys(KeyRing& keys, char* device_out, size_t cap);
// The provisioned settings: NVS namespace "pkr-cfg", string "cfg" (pkr_node.h has the shape).
// false (defaults kept) when there is none or it does not parse.
bool load_node_settings(NodeSettings& s);
// The officers' and pradhan's numbers (NVS "pkr-keys" sms_to0..3), never in a shadow.
void sms_numbers(void (*fn)(const char* e164, void* ctx), void* ctx);

// ---------------------------------------------------------------- time

class EspClock : public Clock {
 public:
  uint32_t ms() override { return millis(); }
  uint32_t unix_s() override;
  bool synced() override;
  void set(uint32_t unix_now);  // NTP, the modem's network time, or `>TIME` in the simulator
  bool sync_ntp(uint32_t wait_ms);

 private:
  uint32_t synced_at_ms_ = 0;
  bool ever_ = false;
};

// ---------------------------------------------------------------- LoRa

// Ebyte E22-900T22S on a UART. Transparent mode: one UART burst is one LoRa packet; a received
// packet is the bytes up to a 20 ms gap (plus the RSSI byte the config asks for, stripped here).
class E22Radio : public RadioPort {
 public:
  // configure=false: the module keeps the registers it saved (a gauge waking from deep sleep: the
  // E22's own flash is not rewritten every five minutes).
  bool begin(HardwareSerial& port, int rx, int tx, int m0, int m1, uint16_t addr, uint32_t freq_hz,
             bool configure = true);
  bool transmit(const uint8_t* buf, size_t n) override;
  size_t receive(uint8_t* buf, size_t cap) override;
  int last_rssi() const { return rssi_; }
  void sleep();  // M0 = M1 = 1: the module's own sleep (a few uA) while the ESP32 deep-sleeps

 private:
  HardwareSerial* port_ = nullptr;
  int m0_ = -1, m1_ = -1;
  uint8_t rx_[PKR_FRAME_MAX_LEN + 2];
  size_t n_ = 0;
  uint32_t last_byte_ms_ = 0;
  int rssi_ = 0;
};

// ---------------------------------------------------------------- the serial simulator link

// Wokwi has no modem and CI has no network: the *_sim envs speak lines on the serial port.
//   in:  >CMD {json}  >CFG {json}  >LORA <base64>  >SMS <from> <text>  >TIME <unix>  >CLOUD up|down
//        >FAULT <name>|none  >TEST silent  >SOC <n>  >STAGE <cm>  >TIP  >KEY off|w|c  >HOLD 0|1
//   out: READY  <EVT {json}  <LORA <base64>  <SMS <to> <text>  <PUB <topic> <bytes>  <READING {json}
class SerialConsole {
 public:
  // Returns a complete line (without the newline) or nullptr.
  const char* poll();

 private:
  char line_[1024];
  size_t n_ = 0;
};

class SerialRadio : public RadioPort {
 public:
  bool transmit(const uint8_t* buf, size_t n) override;
  size_t receive(uint8_t* buf, size_t cap) override;
  void inject(const char* b64);  // a `>LORA` line

 private:
  uint8_t q_[4][PKR_FRAME_MAX_LEN];
  size_t qn_[4] = {0, 0, 0, 0};
  uint8_t head_ = 0, count_ = 0;
};

// Prints every event as `<EVT {json}` (the EventLog's mirror in the simulator).
class SerialEventMirror : public EventSink {
 public:
  void emit(const Event& e) override;
};

// ---------------------------------------------------------------- the cloud

using MessageFn = void (*)(const char* topic, const char* payload, size_t len);
using SmsFn = void (*)(const char* from, const char* text);

class CloudLink {
 public:
  virtual ~CloudLink() {}
  virtual void loop() = 0;
  virtual bool connected() = 0;
  virtual bool publish(const char* topic, const char* payload, size_t len) = 0;  // QoS 1: true after PUBACK
  virtual void subscribe(const char* topic) = 0;
  virtual bool sms(const char* to, const char* text) = 0;
  virtual void poll_sms(SmsFn fn) = 0;
  virtual int rssi() { return 0; }
  void on_message(MessageFn fn) { msg_ = fn; }
  void on_connect(void (*fn)()) { conn_ = fn; }

 protected:
  MessageFn msg_ = nullptr;
  void (*conn_)() = nullptr;
};

// LTE Cat-1 (SIM7670G / A76xx) over PPP (arduino-esp32 3.x), TLS with the device's own X.509
// certificate, MQTT 3.1.1 to AWS IoT Core (256dpi/arduino-mqtt, MIT). The certificate and key
// are files on LittleFS (/certs/ca.pem, device.pem, key.pem) written at provisioning; with flash
// encryption on they cannot be read off the chip.
class MqttLink : public CloudLink {
 public:
  struct Pins { int tx, rx, rst, pwr; };
  bool begin(const char* thing, const char* endpoint, const char* apn, Pins pins);
  void loop() override;
  bool connected() override;
  bool publish(const char* topic, const char* payload, size_t len) override;
  void subscribe(const char* topic) override;
  bool sms(const char* to, const char* text) override;
  void poll_sms(SmsFn fn) override;
  int rssi() override;
  static void dispatch(const char* topic, const char* payload, int len);
  // A gauge's short wake: try again now instead of after the backoff, and power the modem down
  // before deep sleep.
  void retry_now() { next_try_ms_ = 0; }
  void end();

 private:
  bool bring_up();
  Pins pins_{-1, -1, -1, -1};
  char thing_[48] = {0};
  char endpoint_[96] = {0};
  uint32_t next_try_ms_ = 0, fails_ = 0, last_sms_poll_ms_ = 0;
  char subs_[8][128];
  uint8_t n_subs_ = 0;
};

class SerialLink : public CloudLink {
 public:
  void loop() override {}
  bool connected() override { return up_; }
  bool publish(const char* topic, const char* payload, size_t len) override;
  void subscribe(const char*) override {}
  bool sms(const char* to, const char* text) override;
  void poll_sms(SmsFn) override {}
  void set_up(bool up);

 private:
  bool up_ = true;
};

// Drains the outbox to the cloud: one record on `event`, more as {"events":[...]} on `backfill`
// (up to 30), the alarm queue first; the tail moves only after PUBACK; full-jitter backoff and the
// circuit breaker on failures (section 6.3).
class Uplink {
 public:
  // live: the single-record topic ("event"; a gauge's "reading", where a buffered:true record is
  // history to the server); key: the backfill list ("events"; a gauge's "readings").
  void begin(Outbox* ob, CloudLink* link, const char* kind, const char* village, const char* device,
             const char* live = "event", const char* key = "events");
  void loop(uint32_t now_s);
  bool idle() const { return !ob_ || !ob_->depth() || breaker_.open(); }

 private:
  Outbox* ob_ = nullptr;
  CloudLink* link_ = nullptr;
  char t_event_[128], t_backfill_[128];
  char key_[12] = "events";
  Breaker breaker_;
  uint32_t attempt_ = 0, next_at_ = 0;
};

// Shadow and job topics for a thing (section 5.1).
void shadow_topic(char* out, size_t cap, const char* thing, const char* shadow, const char* suffix);

}  // namespace pkr
