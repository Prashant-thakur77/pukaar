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

// {"events":[<payload>,...]} from outbox records (the `backfill` topic body; a gauge's is "readings").
// Returns the length, or 0 if it does not fit.
size_t build_backfill(const OutRecord* recs, size_t n, char* out, size_t cap, const char* key = "events");

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
  // SIREN_CMD_WRAPPED to one siren, the payload exactly as the shadow gave it (an alarm frame).
  virtual bool lora_wrapped(uint16_t dst, const uint8_t* payload, uint8_t len) { return false; }
};

enum BoxButton : uint8_t { BOX_A_WATER = 0, BOX_B_ACK = 1, BOX_C_HOLD = 2, BOX_D_STOP = 3 };

// ---------------------------------------------------------------- the box's "siren" shadow

// desired.relay_cmd.<siren> (backend protocol.relay_cmd): a compact command already signed with the
// siren's own key, which the box sends once, before exp, as a frame of its own.
struct RelayCmd {
  char siren[PKR_DEVICE_MAX] = {0};
  char cmd_id[PKR_ID_MAX] = {0};
  uint16_t dst = 0;
  uint32_t exp = 0;
  uint8_t payload[PKR_FT_SIREN_CMD_WRAPPED_LEN] = {0};
};

struct BoxShadow {
  bool has_level = false;
  uint8_t level = PKR_LEVEL_NORMAL;
  bool has_alert = false;
  char alert_id[PKR_ID_MAX] = {0};
  uint8_t clip_role = 0;  // CLIP_* from the clip name; 0 none
  RelayCmd relay[4];
  uint8_t n_relay = 0;
  uint8_t bad_relay = 0;  // entries that did not parse (skipped)
};
// From the shadow document ({"state":{"desired":{...}}}), a delta ({"state":{...}}) or the bare
// object. Returns 0 or PKR_REASON_BAD_FORMAT.
int parse_box_shadow(const char* json, size_t len, BoxShadow* out);
// "<village>.warning.hi.v1" -> CLIP_WARNING ... "chime" -> CLIP_NONE (the chime is the speaker's own)
uint8_t clip_role_from_name(const char* clip);

enum RelayResult : uint8_t { RELAY_SENT = 0, RELAY_DUPLICATE = 1, RELAY_EXPIRED = 2, RELAY_FAILED = 3 };

// Heard LoRa frames, batched for the cloud (pukaar/mesh/<village>/<box>/relay, {"frames":[base64]}):
// well-formed, not the box's own, each (src, ctr) once in 10 minutes, at most 30 a message. The
// cloud checks every inner MAC with the origin's key: the box vouches for nothing.
class MeshBatch {
 public:
  static const uint8_t MAX = 30;
  void begin(uint16_t self_addr) { self_ = self_addr; }
  bool add(const uint8_t* buf, size_t n, uint32_t now_ms);
  bool due(uint32_t now_ms) const { return n_ && (n_ >= MAX || now_ms - first_ms_ >= 30000u); }
  size_t build(char* out, size_t cap) const;  // 0 if it does not fit
  void clear() { n_ = 0; }
  uint8_t count() const { return n_; }

 private:
  uint16_t self_ = 0;
  struct Seen { uint16_t src; uint32_t ctr, t; bool used; } seen_[32] = {};
  uint8_t seen_i_ = 0;
  uint8_t buf_[MAX][PKR_FRAME_MAX_LEN];
  uint8_t len_[MAX] = {0};
  uint8_t n_ = 0;
  uint32_t first_ms_ = 0;
};

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
  void set_alert(const char* alert_id);                // what button B ("mil gaya") acknowledges
  // The shadow: LEDs and the indoor clip when the level or the alert changes, then every relay_cmd.
  void apply_shadow(const BoxShadow& s);
  RelayResult relay(const RelayCmd& c);
  uint32_t relayed = 0;
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
  bool level_known_ = false;
  char alert_[PKR_ID_MAX] = {0};
  char sent_ids_[8][PKR_ID_MAX] = {};
  uint8_t sent_i_ = 0;
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
  bool pending() const {  // a frame waits for its backoff (the image does not sleep long then)
    for (const auto& p : q_)
      if (p.used) return true;
    return false;
  }
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
