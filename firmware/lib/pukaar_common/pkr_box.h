// Pradhan box (section 7.2) and LoRa relay (section 7.3) logic, plus the event log that feeds
// the outbox and the OTA job gate (section 6.4).
#pragma once

#include <stdint.h>
#include <string.h>

#include "pkr_event.h"
#include "pkr_outbox.h"
#include "pkr_siren.h"

namespace pkr {

// ---------------------------------------------------------------- event log -> outbox

// Numbers every event (boot, seq), serialises it and queues it durably. `mirror` (optional) also
// gets every event: the simulator prints them on the serial port.
class EventLog : public EventSink {
 public:
  void begin(Outbox* ob, uint32_t boot, EventSink* mirror = nullptr);
  void emit(const Event& e) override;
  uint32_t seq() const { return seq_; }
  uint32_t boot() const { return boot_; }
  uint32_t lost = 0;  // events the outbox refused (flash full or failing)

 private:
  Outbox* ob_ = nullptr;
  EventSink* mirror_ = nullptr;
  uint32_t boot_ = 0, seq_ = 0;
};

// {"events":[<payload>,...]} from outbox records (the `backfill` topic body). Returns the length,
// or 0 if it does not fit.
size_t build_backfill(const OutRecord* recs, size_t n, char* out, size_t cap);

// ---------------------------------------------------------------- pradhan box

class BoxPort {
 public:
  virtual ~BoxPort() {}
  // LoRa BUTTON frame to the village's sirens (broadcast). Returns the frame ctr, 0 if not sent.
  virtual uint32_t lora_button(uint8_t button, uint8_t key_pos, uint16_t hold_ms) = 0;
  virtual bool cloud_up() = 0;
  virtual void sms_officers(const char* text) = 0;
  virtual void level_leds(uint8_t level) = 0;  // PKR_LEVEL_*: one of green, yellow, orange, red
  virtual void link_led(uint8_t colour) = 0;   // 0 off, 1 green blink (cloud), 2 amber (LoRa only), 3 red
  virtual void play(uint8_t clip_role, bool chime_only) = 0;
};

enum BoxButton : uint8_t { BOX_A_WATER = 0, BOX_B_ACK = 1, BOX_C_HOLD = 2, BOX_D_STOP = 3 };

class BoxCore {
 public:
  BoxCore(BoxPort& port, Clock& clock, EventSink& sink) : port_(port), clock_(clock), sink_(sink) {}
  void configure(const char* village, bool simulated) {
    strncpy(village_, village, sizeof village_ - 1);
    simulated_ = simulated;
  }
  void set_button(uint8_t b, bool pressed);  // raw level; debounced inside (50 ms)
  void set_key(uint8_t pos);
  void on_ack(uint16_t acked_src, uint32_t acked_ctr);  // an ACK frame from a siren
  void on_lora_heard();                                // any valid frame: the LoRa link works
  void set_level(uint8_t level, uint8_t clip_role);    // box shadow desired.level
  void tick();

  bool waiting_ack() const { return pending_.active; }
  uint8_t tries() const { return pending_.tries; }

 private:
  void pressed(uint8_t b);
  void fire_manual();
  void report_manual(bool acked);
  bool rate_ok();
  Event ev(uint8_t type);
  BoxPort& port_;
  Clock& clock_;
  EventSink& sink_;
  char village_[24] = {0};
  bool simulated_ = false;
  struct Btn { bool raw = false, stable = false; uint32_t since = 0; } btn_[4];
  uint8_t key_ = PKR_KEY_OFF;
  uint32_t hold_since_ = 0;
  bool hold_fired_ = false;
  uint32_t starts_[PKR_LIMIT_MANUAL_RATE_PER_HOUR] = {0};
  uint8_t n_starts_ = 0;
  struct {
    bool active = false;
    uint8_t button = 0, key_pos = 0, tries = 0;
    uint16_t hold_ms = 0;
    uint32_t ctr = 0, sent_ms = 0, at = 0;
  } pending_;
  uint32_t last_lora_ms_ = 0;
  bool lora_seen_ = false;
  uint8_t level_ = 0;
  uint32_t last_ab_ms_[2] = {0, 0};
};

// ---------------------------------------------------------------- relay

// Store-and-forward without keys (it cannot forge a frame): re-transmit every well-formed frame
// whose (src, ctr) it has not seen in 10 minutes, after a random 50-500 ms, within the 10 %
// budget. Every 15 minutes it sends its own RELAY_BEACON (signed with its own key).
class RelayCore {
 public:
  void begin(LoraLink* link, uint16_t self_addr, uint32_t (*rnd)());
  // returns true if the frame was queued for re-transmission
  bool on_rx(const uint8_t* buf, size_t n, uint32_t now_ms);
  void tick(uint32_t now_ms, uint32_t now_unix, bool synced, const pkr_beacon_payload_t& beacon);
  uint32_t forwarded = 0, duplicates = 0, malformed = 0;

 private:
  LoraLink* link_ = nullptr;
  uint16_t self_ = 0;
  uint32_t (*rnd_)() = nullptr;
  struct Seen { uint16_t src; uint32_t ctr, t; bool used; } seen_[64] = {};
  uint8_t seen_i_ = 0;
  struct Pending { bool used; uint32_t due; uint8_t n; uint8_t buf[PKR_FRAME_MAX_LEN]; bool alarm; } q_[8] = {};
  uint32_t last_beacon_ms_ = 0;
  bool beacon_sent_ = false;
};

// ---------------------------------------------------------------- OTA job gate

struct OtaJob {
  char op[8] = {0};       // "ota" | "clips"
  char fw[40] = {0};
  char url[512] = {0};
  char sha256[65] = {0};
  uint32_t size = 0;
  uint8_t min_soc = 60;
  int win_start_min = 600, win_end_min = 960;  // 10:00-16:00 IST
  bool not_if_alert = true;
};
int parse_ota_job(const char* json, size_t len, OtaJob* job);  // 0 or PKR_REASON_BAD_FORMAT
// "" if the update may run now, else why not ("low_soc", "window", "alert_active").
const char* ota_gate(const OtaJob& job, int soc, int minutes_ist_now, bool alert_active);

}  // namespace pkr
