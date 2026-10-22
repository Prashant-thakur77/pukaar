// Fakes for the host tests: a clock you move by hand, a siren HAL that records what the relays
// and audio did, an event sink, SMS and LoRa ports that capture what was sent.
#pragma once

#include <string.h>

#include <string>
#include <vector>

#include "pkr_addr.h"
#include "pkr_box.h"
#include "pkr_siren.h"
#include "pkr_sms.h"
#include "pkr_test_keys.h"

namespace fk {

struct Clock : pkr::Clock {
  uint32_t now_ms = 1000;
  uint32_t now_unix = 1761121800;  // 2025-10-22T08:30:00Z = 14:00 IST (the spec examples use this iat)
  bool is_synced = true;
  uint32_t ms() override { return now_ms; }
  uint32_t unix_s() override { return now_unix; }
  bool synced() override { return is_synced; }
  void advance(uint32_t ms_) {
    now_ms += ms_;
    unix_acc += ms_;
    now_unix += unix_acc / 1000;
    unix_acc %= 1000;
  }
  uint32_t unix_acc = 0;
};

struct Hal : pkr::SirenHal {
  bool k[4] = {false, false, false, false};
  bool k2_ever_horns_in_test = false;
  std::vector<std::pair<uint16_t, uint8_t>> tones;
  std::vector<uint8_t> clips;
  int feeds = 0;
  bool fallback = false;
  float amp = 3.2f, amp_test = 1.0f, siren = 1.5f, mic_quiet = -40.0f, mic_loud = -14.0f;
  bool mic_is_dead = false;
  bool amp_dead_until_fallback = false;  // DFPlayer silent: the LEDC fallback works
  uint16_t self_faults = 0;
  uint16_t cur_hz = 0;
  uint8_t cur_vol = 0;
  void relay(uint8_t r, bool on) override { k[r] = on; }
  void tone(uint16_t hz, uint8_t vol, bool) override {
    cur_hz = hz;
    cur_vol = vol;
    tones.push_back({hz, vol});
  }
  void clip(uint8_t role, const char*, uint8_t) override { clips.push_back(role); }
  void audio_off() override { cur_hz = 0; }
  void fallback_source(bool on) override { fallback = on; }
  void feed_oneshot() override { feeds++; }
  float amp_a() override {
    if (!k[pkr::K1_AMP]) return 0.05f;
    if (amp_dead_until_fallback && !fallback) return 0.1f;
    return k[pkr::K2_HORNS] ? amp : amp_test;
  }
  float siren_a() override { return k[pkr::K3_SIREN] ? siren : 0.0f; }
  float mic_db() override { return (k[pkr::K1_AMP] && k[pkr::K2_HORNS] && cur_hz && amp_a() > 1.0f) ? mic_loud : mic_quiet; }
  bool mic_dead() override { return mic_is_dead; }
  uint16_t selftest_faults() override { return self_faults; }
};

struct Sink : pkr::EventSink {
  std::vector<pkr::Event> ev;
  void emit(const pkr::Event& e) override { ev.push_back(e); }
  int count(uint8_t type) const {
    int n = 0;
    for (auto& e : ev) n += e.type == type;
    return n;
  }
  const pkr::Event* last(uint8_t type) const {
    for (auto it = ev.rbegin(); it != ev.rend(); ++it)
      if (it->type == type) return &*it;
    return nullptr;
  }
  void clear() { ev.clear(); }
};

struct Sms : pkr::SmsPort {
  std::vector<std::pair<std::string, std::string>> sent;
  void send(const char* to, const char* text) override { sent.push_back({to ? to : "<officers>", text}); }
};

struct Frames : pkr::FramePort {
  struct F { uint8_t type; uint16_t dst; std::vector<uint8_t> payload; };
  std::vector<F> sent;
  bool send(uint8_t type, uint16_t dst, const uint8_t* p, uint8_t len) override {
    sent.push_back({type, dst, std::vector<uint8_t>(p, p + len)});
    return true;
  }
};

// ---------------------------------------------------------------- keys and frames

inline void key_of(const char* device, uint8_t out[32], unsigned kid = 1) { pkr_test_only_device_key(device, kid, out); }

inline pkr::Sender sender(const char* device, uint8_t roles, unsigned kid = 1) {
  pkr::Sender s;
  s.addr = pkr_sim_addr(device);
  strncpy(s.device, device, sizeof s.device - 1);
  s.kid = (uint8_t)kid;
  s.roles = roles;
  key_of(device, s.key, kid);
  return s;
}

// A signed frame as `device` would send it.
inline std::vector<uint8_t> frame(const char* device, uint8_t type, uint16_t dst, uint32_t ctr, uint32_t ts,
                                  const uint8_t* payload, uint8_t len) {
  pkr_frame_t f{};
  f.ver = PKR_FRAME_VERSION;
  f.type = type;
  f.src = pkr_sim_addr(device);
  f.dst = dst;
  f.ctr = ctr;
  f.ts = ts;
  f.len = len;
  memcpy(f.payload, payload, len);
  uint8_t key[32];
  key_of(device, key);
  std::vector<uint8_t> out(PKR_FRAME_MAX_LEN);
  int n = pkr_frame_encode(&f, key, 32, out.data(), out.size());
  out.resize(n > 0 ? (size_t)n : 0);
  return out;
}

inline std::vector<uint8_t> gauge_alarm(const char* gauge, uint32_t ctr, uint32_t ts, int16_t stage = 312,
                                        uint8_t level = PKR_LEVEL_CRITICAL, uint8_t type = PKR_FT_GAUGE_ALARM) {
  pkr_gauge_payload_t g{level, stage, 25, 96, 0, 120};
  uint8_t p[PKR_FT_GAUGE_STATUS_LEN];
  pkr_gauge_payload_encode(&g, p);
  return frame(gauge, type, PKR_FRAME_BROADCAST, ctr, ts, p, sizeof p);
}

inline std::vector<uint8_t> button(const char* box, uint32_t ctr, uint32_t ts, uint8_t btn, uint8_t key_pos, uint16_t hold) {
  pkr_button_payload_t b{btn, key_pos, hold};
  uint8_t p[PKR_FT_BUTTON_LEN];
  pkr_button_payload_encode(&b, p);
  return frame(box, PKR_FT_BUTTON, PKR_FRAME_BROADCAST, ctr, ts, p, sizeof p);
}

// A signed shadow command for the simulated siren.
inline pkr_cmd_t command(const char* id, const char* pattern, const char* level, uint32_t ctr, uint32_t iat,
                         const char* src = "approval", const char* action = "sound", const char* device = PKR_SIM_SIREN) {
  pkr_cmd_t c;
  memset(&c, 0, sizeof c);
  strcpy(c.id, id);
  strcpy(c.device, device);
  strcpy(c.action, action);
  strcpy(c.pattern, pattern);
  snprintf(c.clip, sizeof c.clip, "thunag.%s.hi.v3", level);
  strcpy(c.clip_sha256_16, "9f1c2b3a4d5e6f70");
  strcpy(c.level, level);
  strcpy(c.alert_id, "01JB5ALERT0000000000000000");
  strcpy(c.src, src);
  c.cycles = 0;
  c.repeat_every_s = 0;
  c.repeat_cycles = 0;
  c.cap_on_s = 0;
  c.volume = 100;
  c.iat = iat;
  c.exp = iat + 1800;
  c.ctr = ctr;
  c.kid = 1;
  uint8_t key[32];
  key_of(device, key);
  pkr_cmd_sign(&c, key, 32);
  return c;
}

// The simulated Thunag siren, configured as the tests expect.
struct SirenRig {
  Clock clock;
  Hal hal;
  pkr::MemKv kv;
  pkr::KeyRing keys;
  Sink sink;
  Sms sms;
  Frames lora;
  pkr::DeviceConfig cfg;
  pkr::SirenSettings set;
  pkr::SirenCore core{hal, clock, kv, keys, sink, &sms, &lora};

  explicit SirenRig(bool begin_now = true) {
    keys.set_identity(PKR_SIM_SIREN, PKR_SIM_SIREN_ADDR);
    uint8_t k[32];
    key_of(PKR_SIM_SIREN, k);
    keys.set_self_key(1, k);
    keys.set_current_kid(1);
    keys.add_sender(sender(PKR_SIM_GAUGE, pkr::ROLE_GAUGE_STATUS | pkr::ROLE_GAUGE_ALARM | pkr::ROLE_RELAY_CMD));
    keys.add_sender(sender(PKR_SIM_BOX, pkr::ROLE_BUTTON | pkr::ROLE_HEARTBEAT | pkr::ROLE_RELAY_CMD));
    cfg.autonomy.enabled = true;
    cfg.autonomy.shadow_mode = false;
    cfg.autonomy.fast_path = false;
    strcpy(cfg.autonomy.upstream[0], PKR_SIM_GAUGE);
    cfg.autonomy.n_upstream = 1;
    cfg.amp_a_ref = 3.3f;
    cfg.spl_rise_min_db = 15;
    pkr_sms_sender_hash(PKR_SIM_SMS_SALT, PKR_SIM_OFFICER_E164, cfg.sms_allow[0]);
    cfg.n_sms_allow = 1;
    strcpy(set.village, PKR_SIM_VILLAGE);
    strcpy(set.sms_salt, PKR_SIM_SMS_SALT);
    set.amp_a_test_ref = 1.0f;
    if (begin_now) start();
  }
  void start() {
    core.configure(cfg, set);
    core.begin();
    core.set_soc(90);
    sink.clear();
  }
  // run the core for ms milliseconds in 20 ms steps
  void run(uint32_t ms) {
    for (uint32_t t = 0; t < ms; t += 20) {
      clock.advance(20);
      core.tick();
    }
  }
  void cloud_ok() {
    core.set_cloud_link(true);
    core.cloud_contact();
  }
};

}  // namespace fk
