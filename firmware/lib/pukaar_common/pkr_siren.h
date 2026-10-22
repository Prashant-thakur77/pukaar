// The siren node's state machine (sections 6.2 and 7.4), with every hardware and network edge
// behind an interface so all of it runs in the host tests.
//
// STATE in {BOOT, SELFCHECK, IDLE, SOUNDING, TESTING, MANUAL, AUTONOMOUS, FAULT, LOW_POWER}
//
// A command (shadow, LoRa or SMS) passes the CommandGuard first (pkr_guard.h, the twin of
// siren_model.CommandVerifier: key, signature, replay per path, expiry; persisted), and only then
// is acted on: stop; a drill that is not D1 is refused; T1 at volume 0 is the silent test; an
// audible test in the low-power tiers or outside 09:00-18:00 IST is refused; a lower priority
// never interrupts a higher one.
// Every sound is verified in the first tone (3-8 s): amp current within 60-150 % of the
// reference AND a microphone rise of at least spl_rise_min_db (or a known-dead mic). A failed
// check switches to the LEDC tone and re-measures once, then flags FAULT. The horns stay on
// whatever the check says: a failed check never silences a real alarm.
#pragma once

#include <stdint.h>

#include "pkr_event.h"
#include "pkr_guard.h"
#include "pkr_lora.h"
#include "pkr_pattern.h"
#include "pkr_store.h"

namespace pkr {

enum RelayId : uint8_t { K1_AMP = 0, K2_HORNS = 1, K3_SIREN = 2, K4_STROBE = 3 };

class SirenHal {
 public:
  virtual ~SirenHal() {}
  virtual void relay(uint8_t k, bool on) = 0;             // K2: true = horns, false = dummy load
  virtual void tone(uint16_t hz, uint8_t volume, bool sweep) = 0;  // 0 Hz = off; sweep = C1's rise and fall
  virtual void clip(uint8_t role, const char* name, uint8_t volume) = 0;
  virtual void audio_off() = 0;
  virtual void fallback_source(bool on) = 0;              // LEDC tone instead of the DFPlayer
  virtual void feed_oneshot() = 0;                        // re-trigger the hardware max-on timers
  virtual float amp_a() = 0;                              // INA226 #1, amp rail
  virtual float siren_a() = 0;                            // INA226 #2, K3 line
  virtual float mic_db() = 0;                             // relative dB
  virtual bool mic_dead() = 0;
  virtual uint16_t selftest_faults() = 0;                 // DFPlayer reply, catalog digest, modem, LoRa loop, siren line
};

class Clock {
 public:
  virtual ~Clock() {}
  virtual uint32_t ms() = 0;
  virtual uint32_t unix_s() = 0;  // best estimate even when unsynced
  virtual bool synced() = 0;
};

class EventSink {
 public:
  virtual ~EventSink() {}
  virtual void emit(const Event& e) = 0;
};

class SmsPort {
 public:
  virtual ~SmsPort() {}
  // to = nullptr: the allow-listed officer and pradhan numbers the comms layer holds
  virtual void send(const char* to, const char* text) = 0;
};

class FramePort {
 public:
  virtual ~FramePort() {}
  virtual bool send(uint8_t type, uint16_t dst, const uint8_t* payload, uint8_t len) = 0;
};

struct SirenSettings {
  char village[24] = {0};
  float amp_a_test_ref = -1;  // silent test into the dummy load at 30 %; default 0.3 x amp_a_ref
  bool simulated = false;
  char sms_salt[33] = {0};
};

struct Order {
  bool active = false;
  uint8_t pattern = 0, prio = 0, src = 0, via = 0;
  char cmd_id[PKR_ID_MAX] = {0};
  char alert_id[PKR_ID_MAX] = {0};
  char clip[PKR_CLIP_MAX] = {0};
  uint32_t exp = 0;              // 0 = local order, no expiry
  uint16_t manual_source = 0xFFFF;  // 0 = this node's key switch; else the box's LoRa address
  uint32_t manual_until_ms = 0;
  bool autonomous = false;
  bool audible_test = false;
  uint32_t started_ms = 0;
  char sms_reply_to[24] = {0};
  bool sms_replied = false;
};

// A command id and its LoRa form (12 hex chars of cmd_id48) name the same command.
bool same_command(const char* a, const char* b);

class SirenCore {
 public:
  SirenCore(SirenHal& hal, Clock& clock, Kv& kv, KeyRing& keys, EventSink& sink, SmsPort* sms, FramePort* lora);

  void begin();  // BOOT: relays off, counters loaded, SELFCHECK -> IDLE
  void configure(const DeviceConfig& cfg, const SirenSettings& s);

  // commands; each returns 0 if accepted or the PKR_REASON_* it was rejected with
  int accept_command(const pkr_cmd_t& cmd, uint8_t via);
  int on_lora(const uint8_t* frame, size_t n);
  int on_sms(const char* from_e164, const char* text, size_t len);

  // local controls on the siren itself
  void set_key(uint8_t pos);    // PKR_KEY_*
  void set_hold(bool pressed);  // the HOLD button
  void set_door(bool open);     // tamper switch

  // health and links
  void set_soc(uint8_t soc);
  void cloud_contact();         // any message from the cloud (shadow, PUBACK, ping)
  void set_cloud_link(bool up);
  void run_silent_test(const char* cmd_id = "");  // also what a T1 command at volume 0 runs
  void power_down_warning();    // flush lazily-persisted counters

  void tick();

  uint8_t state() const;
  uint8_t tier() const { return tier_; }
  uint16_t faults() const { return faults_; }
  const Order& order() const { return order_; }
  const PatternPlayer& player() const { return player_; }
  uint32_t last_cmd_ctr() const { return guard_.last_ctr(GUARD_MQTT); }
  const CommandGuard& guard() const { return guard_; }
  bool cloud_silent() const;
  bool relay_state(uint8_t k) const { return relays_[k]; }
  bool testing() const { return test_.active; }

 private:
  struct Request {
    uint8_t action = 0, pattern = 0, level = 0, src = 0, via = 0;
    char id[PKR_ID_MAX] = {0};
    char alert_id[PKR_ID_MAX] = {0};
    char clip[PKR_CLIP_MAX] = {0};
    uint32_t cycles = 0, repeat_every_s = 0, repeat_cycles = 0, cap_on_s = 0, volume = 0, exp = 0, ctr = 0;
    bool has_volume = false;
    char sms_from[24] = {0};
  };
  int act(const Request& r);
  int reject(uint8_t reason, const char* id, uint8_t via, const char* frame_src = nullptr);
  void start(const Request& r, bool autonomous, uint16_t manual_source, uint32_t cap_on_s);
  void stop_order(uint8_t evt, const char* detail);
  void handle_gauge_alarm(const RxResult& rx);
  void handle_button(const RxResult& rx);
  int handle_wrapped(const RxResult& rx);
  void manual(uint8_t level, uint8_t src, uint16_t source, const char* frame_src);
  bool rate_ok(uint16_t source);
  void apply_outputs(const Output& o);
  void set_relay(uint8_t k, bool on);
  void all_off();
  void verify_step(const Output& o);
  void silent_test_step();
  void send_sms_reply(bool ok, const char* detail);
  Event make_event(uint8_t type);
  uint8_t priority_of(uint8_t pattern, uint8_t src) const;
  bool is_upstream(const char* device) const;
  void note_time();

  SirenHal& hal_;
  Clock& clock_;
  Kv& kv_;
  KeyRing& keys_;
  EventSink& sink_;
  SmsPort* sms_;
  FramePort* lora_;
  DeviceConfig cfg_;
  SirenSettings set_;
  CommandGuard guard_;
  FrameReceiver rx_;
  PatternPlayer player_;
  Order order_;
  uint8_t base_state_ = PKR_STATE_BOOT;
  bool relays_[4] = {false, false, false, false};
  uint16_t last_hz_ = 0;
  uint8_t last_vol_ = 0;
  uint32_t last_feed_ms_ = 0;
  // verification
  uint8_t verify_stage_ = 0;  // 0 idle, 1 first check pending, 2 fallback check pending, 3 done
  uint32_t verify_at_ms_ = 0;
  bool verified_ = false;
  float pre_db_ = 0, mic_ring_[20] = {0};
  uint8_t mic_n_ = 0, mic_i_ = 0;
  uint32_t mic_last_ms_ = 0;
  Meas last_meas_;
  // links and health
  bool ever_contact_ = false, link_up_ = false;
  uint32_t last_contact_ms_ = 0;
  uint8_t tier_ = 0;
  bool tier_known_ = false;
  uint16_t faults_ = 0;
  bool door_open_ = false;
  // local key switch
  uint8_t key_ = PKR_KEY_OFF;
  bool hold_ = false, hold_fired_ = false;
  uint32_t hold_since_ms_ = 0;
  // manual rate limit: 3 an hour per source
  struct RateSlot { uint16_t source; uint32_t t[PKR_LIMIT_MANUAL_RATE_PER_HOUR]; uint8_t n; } rate_[6] = {};
  // autonomy
  uint32_t last_gauge_alarm_ms_ = 0;
  // silent test
  struct { bool active = false; uint32_t start_ms = 0; float amp = -1; char cmd_id[PKR_ID_MAX] = {0}; } test_;
  uint32_t last_rx_reject_event_ms_ = 0;
  bool rx_reject_event_any_ = false;
};

}  // namespace pkr
