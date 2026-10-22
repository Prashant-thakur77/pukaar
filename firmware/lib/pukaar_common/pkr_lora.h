// LoRa frame receive checks and signed sending (section 5.3), over the C frame codec.
#pragma once

#include <stdint.h>

#include "pkr_dutycycle.h"
#include "pkr_frame.h"
#include "pkr_store.h"

namespace pkr {

struct RxResult {
  int reason = 0;  // 0 accepted, -1 not addressed to us, else PKR_REASON_*
  pkr_frame_t frame{};
  const Sender* sender = nullptr;
};

// Receiver checks, in siren_model.FrameVerifier's order: well-formed ("malformed"); [addressed to
// us or broadcast, else ignored]; src is a configured sender ("unknown_src") with the role the
// type needs ("role"); [the payload length fits the type, "malformed"]; the MAC is valid
// ("bad_mac"); ctr is above the last from that src ("replayed"; written through on accept and
// restored exactly on boot, see LazyCounter);
// if both clocks are synced, |ts - now| < 900 s ("clock_skew"). Only an accepted frame moves
// the counter on.
class FrameReceiver {
 public:
  void begin(KeyRing* keys, Kv* kv);
  RxResult receive(const uint8_t* buf, size_t n, uint32_t now_unix, bool clock_synced);
  void flush();  // power-down warning

 private:
  LazyCounter* counter_for(uint16_t addr);
  KeyRing* keys_ = nullptr;
  Kv* kv_ = nullptr;
  struct Slot { uint16_t addr; bool used; LazyCounter ctr; } slots_[16] = {};
};

// Signs and counts this device's own frames (the outer MAC uses K_self of the current kid).
class FrameSigner {
 public:
  void begin(KeyRing* keys, Kv* kv);
  // Builds a frame into out. Returns its length, or < 0 (no key, bad length).
  int build(uint8_t type, uint16_t dst, const uint8_t* payload, uint8_t len, uint32_t ts, uint8_t* out, size_t cap,
            uint32_t* ctr_out = nullptr);
  void flush() { ctr_.flush(); }
  uint32_t last_ctr() const { return ctr_.value(); }

 private:
  KeyRing* keys_ = nullptr;
  LazyCounter ctr_;
};

// Duty-cycle aware LoRa link a device's app talks to. The radio driver is behind `RadioPort`.
class RadioPort {
 public:
  virtual ~RadioPort() {}
  virtual bool transmit(const uint8_t* buf, size_t n) = 0;
  // Non-blocking: copies one received frame into buf and returns its length, 0 if none.
  virtual size_t receive(uint8_t* buf, size_t cap) = 0;
};

class LoraLink {
 public:
  void begin(RadioPort* radio, FrameSigner* signer, uint32_t budget_ms);
  // Alarm frames (GAUGE_ALARM, BUTTON, SIREN_CMD_WRAPPED, ACK) may use the whole hourly budget,
  // telemetry only 70 %. Returns false if the governor refused or the radio failed.
  bool send(uint8_t type, uint16_t dst, const uint8_t* payload, uint8_t len, uint32_t now_unix, bool clock_synced,
            uint32_t* ctr_out = nullptr);
  bool send_raw(const uint8_t* frame, size_t n, uint32_t now_unix, bool alarm);  // relay forwarding
  static bool is_alarm_type(uint8_t type);
  const pkr_duty_t& duty() const { return duty_; }
  uint32_t refused = 0;

 private:
  RadioPort* radio_ = nullptr;
  FrameSigner* signer_ = nullptr;
  pkr_duty_t duty_{};
};

}  // namespace pkr
