#include "pkr_siren.h"

#include <stdio.h>
#include <string.h>

#include "pkr_codec.h"
#include "pkr_guard.h"
#include "pkr_sms.h"

namespace pkr {

static void scopy(char* dst, size_t cap, const char* src) {
  if (!src) src = "";
  strncpy(dst, src, cap - 1);
  dst[cap - 1] = 0;
}
#define SCOPY(dst, src) scopy(dst, sizeof(dst), src)

static bool hex12(const char* s) {
  if (strlen(s) != 12) return false;
  for (const char* p = s; *p; p++)
    if (!((*p >= '0' && *p <= '9') || (*p >= 'a' && *p <= 'f'))) return false;
  return true;
}

// The cloud's command id and its LoRa form (12 hex chars of cmd_id48, as handle_wrapped names it)
// are the same command: the shadow and a box's relay_cmd copy of it must not start it twice.
bool same_command(const char* a, const char* b) {
  if (!a || !b || !a[0] || !b[0]) return false;
  if (!strcmp(a, b)) return true;
  bool ha = hex12(a), hb = hex12(b);
  if (ha == hb) return false;
  uint8_t id48[6];
  char x[13];
  pkr_cmd_id48(ha ? b : a, id48);
  pkr_hex_encode(id48, 6, x);
  return !strcmp(x, ha ? a : b);
}

SirenCore::SirenCore(SirenHal& hal, Clock& clock, Kv& kv, KeyRing& keys, EventSink& sink, SmsPort* sms, FramePort* lora)
    : hal_(hal), clock_(clock), kv_(kv), keys_(keys), sink_(sink), sms_(sms), lora_(lora) {}

void SirenCore::begin() {
  base_state_ = PKR_STATE_BOOT;
  for (uint8_t k = 0; k < 4; k++) {
    relays_[k] = true;  // force a write
    set_relay(k, false);
  }
  hal_.audio_off();
  guard_.load(&kv_);
  rx_.begin(&keys_, &kv_);
  base_state_ = PKR_STATE_SELFCHECK;
  if (!keys_.has_self_key()) faults_ |= FAULT_NO_KEYS;
  base_state_ = PKR_STATE_IDLE;
}

void SirenCore::configure(const DeviceConfig& cfg, const SirenSettings& s) {
  cfg_ = cfg;
  set_ = s;
  if (set_.amp_a_test_ref < 0) set_.amp_a_test_ref = 0.3f * cfg_.amp_a_ref;
}

// ---------------------------------------------------------------- helpers

Event SirenCore::make_event(uint8_t type) {
  Event e;
  e.type = type;
  e.at = clock_.unix_s();  // required by the cloud; the best estimate when the clock is not synced
  e.simulated = set_.simulated;
  return e;
}

uint8_t SirenCore::priority_of(uint8_t pattern, uint8_t src) const {
  bool manual = src == PKR_SRC_KEY_SWITCH || src == PKR_SRC_PRADHAN_BOX;
  switch (pattern) {
    case PKR_PATTERN_C1:
      if (src == PKR_SRC_AUTONOMY) return PKR_PRIO_AUTONOMY;
      return manual ? PKR_PRIO_MANUAL_CRITICAL : PKR_PRIO_CRITICAL;
    case PKR_PATTERN_W1: return manual ? PKR_PRIO_MANUAL_WARNING : PKR_PRIO_WARNING;
    case PKR_PATTERN_A1: return PKR_PRIO_ALL_CLEAR;
    case PKR_PATTERN_D1: return PKR_PRIO_DRILL;
    default: return PKR_PRIO_TEST;
  }
}

bool SirenCore::cloud_silent() const {
  // section 4.3: "the siren has had no cloud contact for 600 s" (and none at all since boot
  // counts as no contact). A connected MQTT session refreshes contact with every message and
  // keep-alive, so a link that is up is never silent.
  if (!ever_contact_) return true;
  return clock_.ms() - last_contact_ms_ > cfg_.autonomy.cloud_silence_s * 1000u;
}

bool SirenCore::is_upstream(const char* device) const {
  for (uint8_t i = 0; i < cfg_.autonomy.n_upstream; i++)
    if (!strcmp(cfg_.autonomy.upstream[i], device)) return true;
  return false;
}

void SirenCore::note_time() {
  if (clock_.synced()) guard_.note_time(clock_.unix_s());
}

uint8_t SirenCore::state() const {
  if (base_state_ == PKR_STATE_BOOT || base_state_ == PKR_STATE_SELFCHECK) return base_state_;
  if (test_.active || (order_.active && order_.audible_test)) return PKR_STATE_TESTING;
  if (order_.active) {
    if (order_.autonomous) return PKR_STATE_AUTONOMOUS;
    if (order_.manual_source != 0xFFFF) return PKR_STATE_MANUAL;
    return PKR_STATE_SOUNDING;
  }
  if (faults_ & ~(uint16_t)FAULT_TAMPER) return PKR_STATE_FAULT;
  if (tier_ >= PKR_TIER_ALARM_ONLY) return PKR_STATE_LOW_POWER;
  return PKR_STATE_IDLE;
}

int SirenCore::reject(uint8_t reason, const char* id, uint8_t via, const char* frame_src) {
  Event e = make_event(PKR_EVT_REJECTED);
  e.reason = reason;
  e.via = via;
  SCOPY(e.cmd_id, id);
  SCOPY(e.frame_src, frame_src);
  sink_.emit(e);
  return reason;
}

// ---------------------------------------------------------------- commands

int SirenCore::accept_command(const pkr_cmd_t& in, uint8_t via) {
  note_time();
  if (!keys_.has_self_key()) return reject(PKR_REASON_NO_KEYS, in.id, via);
  pkr_cmd_t c = in;
  SCOPY(c.device, keys_.device());  // a command is always checked as signed for this device
  int why = guard_.accept_cmd(c, keys_, via == PKR_VIA_LORA ? GUARD_LORA : GUARD_MQTT, clock_.synced(), clock_.unix_s());
  if (why) return reject((uint8_t)why, c.id, via);
  pkr_cmd_enums_t en;
  if (pkr_cmd_enums(&c, &en) < 0) return reject(PKR_REASON_BAD_FORMAT, c.id, via);
  Request r;
  r.action = (uint8_t)en.action;
  r.pattern = (uint8_t)en.pattern;
  r.level = (uint8_t)en.level;
  r.src = (uint8_t)en.src;
  r.via = via;
  SCOPY(r.id, c.id);
  SCOPY(r.alert_id, c.alert_id);
  SCOPY(r.clip, c.clip);
  r.cycles = c.cycles;
  r.repeat_every_s = c.repeat_every_s;
  r.repeat_cycles = c.repeat_cycles;
  r.cap_on_s = c.cap_on_s;
  r.volume = c.volume;
  r.has_volume = true;
  r.exp = c.exp;
  r.ctr = c.ctr;
  return act(r);
}

// After the guard accepted (and persisted) a command: what it asks for.
int SirenCore::act(const Request& r) {
  if (r.action == PKR_ACTION_STOP) {
    Event e = make_event(PKR_EVT_CMD_RECEIVED);
    SCOPY(e.cmd_id, r.id);
    e.via = r.via;
    e.src = r.src;
    sink_.emit(e);
    bool match = order_.active && (!r.alert_id[0] || !strcmp(r.alert_id, order_.alert_id));
    if (match) stop_order(PKR_EVT_STOPPED, "stop_command");
    if (r.sms_from[0] && sms_) {
      char t[96];
      char hm[6];
      hhmm_ist(clock_.unix_s(), hm);
      char L = pkr_sms_letter_from_pattern(r.pattern);
      snprintf(t, sizeof t, "PUKAAR OK X%c %s %s", L ? L : 'W', keys_.device(), hm);
      sms_->send(r.sms_from, t);
    }
    return 0;
  }
  // already sounding this very command, which came again by a second path (shadow, then the box's LoRa copy)
  if (order_.active && same_command(order_.cmd_id, r.id)) return 0;
  // a drill plays D1 only: whatever else a drill command asks for, it never sounds a real pattern
  if (r.src == PKR_SRC_DRILL && r.pattern != PKR_PATTERN_D1) return reject(PKR_REASON_DRILL_PATTERN, r.id, r.via);
  if (r.action == PKR_ACTION_TEST && r.pattern != PKR_PATTERN_T1 && r.pattern != PKR_PATTERN_D1)
    return reject(PKR_REASON_BAD_FORMAT, r.id, r.via);
  // a silent test is T1 at volume 0 (DESIGN-S): into the dummy load, never audible, any hour
  if (r.action == PKR_ACTION_TEST && r.pattern == PKR_PATTERN_T1 && r.has_volume && r.volume == 0) {
    if (order_.active || test_.active) return reject(PKR_REASON_LOWER_PRIORITY, r.id, r.via);
    Event e = make_event(PKR_EVT_CMD_RECEIVED);
    SCOPY(e.cmd_id, r.id);
    e.pattern = r.pattern;
    e.via = r.via;
    e.src = r.src;
    sink_.emit(e);
    run_silent_test(r.id);
    return 0;
  }
  bool audible_test = r.pattern == PKR_PATTERN_T1 || r.pattern == PKR_PATTERN_D1;
  if (audible_test) {
    if (tier_ >= PKR_TIER_NO_AUDIBLE_TESTS) return reject(PKR_REASON_LOW_POWER, r.id, r.via);
    if (clock_.synced()) {
      int m = minutes_ist(clock_.unix_s());
      if (m < PKR_LIMIT_TEST_WINDOW_START_MIN_IST || m >= PKR_LIMIT_TEST_WINDOW_END_MIN_IST)
        return reject(PKR_REASON_OUTSIDE_TEST_WINDOW, r.id, r.via);
    }
  }
  uint8_t prio = priority_of(r.pattern, r.src);
  if (order_.active && prio < order_.prio) return reject(PKR_REASON_LOWER_PRIORITY, r.id, r.via);
  {
    Event e = make_event(PKR_EVT_CMD_RECEIVED);
    SCOPY(e.cmd_id, r.id);
    e.pattern = r.pattern;
    e.via = r.via;
    e.src = r.src;
    sink_.emit(e);
  }
  start(r, false, 0xFFFF, r.cap_on_s);
  order_.audible_test = audible_test;
  if (r.sms_from[0]) SCOPY(order_.sms_reply_to, r.sms_from);
  return 0;
}

void SirenCore::start(const Request& r, bool autonomous, uint16_t manual_source, uint32_t cap_on_s) {
  uint32_t now = clock_.ms();
  if (test_.active) {
    test_.active = false;
    all_off();
    Event t = make_event(PKR_EVT_TEST_RESULT);
    SCOPY(t.cmd_id, test_.cmd_id);
    t.test_kind = 1;
    t.ok = 0;
    SCOPY(t.detail, "preempted");
    sink_.emit(t);
  }
  if (order_.active) stop_order(PKR_EVT_STOPPED, "preempted");
  order_ = Order();
  order_.active = true;
  order_.pattern = r.pattern;
  order_.src = r.src;
  order_.via = r.via;
  order_.prio = priority_of(r.pattern, r.src);
  SCOPY(order_.cmd_id, r.id);
  SCOPY(order_.alert_id, r.alert_id);
  SCOPY(order_.clip, r.clip);
  order_.exp = r.exp;
  order_.autonomous = autonomous;
  order_.manual_source = manual_source;
  order_.started_ms = now;
  if (manual_source != 0xFFFF) order_.manual_until_ms = now + PKR_LIMIT_MANUAL_CAP_S * 1000u;

  PlanOptions po;
  po.voice_slot = cfg_.voice_slot;
  po.drill_with_c1 = cfg_.drill_with_c1;
  po.cycles = (uint16_t)r.cycles;
  po.repeat_every_s = r.repeat_every_s;
  po.repeat_cycles = (uint16_t)r.repeat_cycles;
  po.cap_on_s = cap_on_s;
  po.volume = r.has_volume ? (uint8_t)(r.volume > 100 ? 100 : (r.volume ? r.volume : 1)) : 0;
  PlayPlan plan = make_plan(r.pattern, autonomous, po);
  player_.start(plan, now);
  // the 2 s before the start is the ambient reference for the microphone rise
  float sum = 0;
  for (uint8_t i = 0; i < mic_n_; i++) sum += mic_ring_[i];
  pre_db_ = mic_n_ ? sum / mic_n_ : hal_.mic_db();
  verify_stage_ = 1;
  verified_ = false;
  hal_.fallback_source(false);
  set_relay(K2_HORNS, true);

  Event e = make_event(PKR_EVT_STARTED);
  SCOPY(e.cmd_id, r.id);
  e.pattern = r.pattern;
  e.via = r.via;
  e.src = r.src;
  sink_.emit(e);
  apply_outputs(player_.tick(now));
}

void SirenCore::stop_order(uint8_t evt, const char* detail) {
  if (!order_.active) return;
  player_.stop();
  all_off();
  Event e = make_event(evt);
  SCOPY(e.cmd_id, order_.cmd_id);
  e.pattern = order_.pattern;
  e.src = order_.src;
  e.via = order_.via;
  SCOPY(e.detail, detail);
  sink_.emit(e);
  if (order_.audible_test) {
    Event t = make_event(PKR_EVT_TEST_RESULT);
    t.test_kind = 2;
    t.ok = verified_ ? 1 : 0;
    SCOPY(t.cmd_id, order_.cmd_id);
    t.has_meas = true;
    t.meas = last_meas_;
    SCOPY(t.detail, detail);
    sink_.emit(t);
  }
  if (order_.sms_reply_to[0] && !order_.sms_replied) send_sms_reply(verified_, nullptr);
  order_ = Order();
  verify_stage_ = 0;
}

void SirenCore::send_sms_reply(bool ok, const char* detail) {
  if (!sms_ || !order_.sms_reply_to[0] || order_.sms_replied) return;
  order_.sms_replied = true;
  char t[120], hm[6];
  hhmm_ist(clock_.unix_s(), hm);
  char L = pkr_sms_letter_from_pattern(order_.pattern);
  if (ok)
    snprintf(t, sizeof t, "PUKAAR OK S%c %s %s %.1fA %+.0fdB", L ? L : '?', keys_.device(), hm, last_meas_.amp_a,
             last_meas_.spl_rise_db);
  else
    snprintf(t, sizeof t, "PUKAAR OK S%c %s %s NOT VERIFIED%s%s", L ? L : '?', keys_.device(), hm, detail ? " " : "",
             detail ? detail : "");
  sms_->send(order_.sms_reply_to, t);
}

// ---------------------------------------------------------------- LoRa

int SirenCore::on_lora(const uint8_t* frame, size_t n) {
  note_time();
  RxResult rx = rx_.receive(frame, n, clock_.unix_s(), clock_.synced());
  if (rx.reason == -1 || rx.reason == PKR_REASON_MALFORMED) return rx.reason;  // not for us, or noise
  if (rx.reason) {
    // at most one event a minute for refused frames, so a jammer cannot fill the outbox
    uint32_t now = clock_.ms();
    if (!rx_reject_event_any_ || now - last_rx_reject_event_ms_ >= 60000u) {
      rx_reject_event_any_ = true;
      last_rx_reject_event_ms_ = now;
      char src[PKR_DEVICE_MAX];
      if (rx.sender) SCOPY(src, rx.sender->device);
      else snprintf(src, sizeof src, "lora:%04x", rx.frame.src);
      reject((uint8_t)rx.reason, "", PKR_VIA_LORA, src);
    }
    return rx.reason;
  }
  switch (rx.frame.type) {
    case PKR_FT_GAUGE_ALARM: handle_gauge_alarm(rx); return 0;
    case PKR_FT_BUTTON: handle_button(rx); return 0;
    case PKR_FT_SIREN_CMD_WRAPPED: return handle_wrapped(rx);
    default: return 0;  // status, heartbeats, beacons and acks: the comms layer forwards them
  }
}

void SirenCore::handle_gauge_alarm(const RxResult& rx) {
  pkr_gauge_payload_t g;
  pkr_gauge_payload_decode(rx.frame.payload, &g);
  Event heard = make_event(PKR_EVT_GAUGE_ALARM_HEARD);
  SCOPY(heard.frame_src, rx.sender->device);
  if (!is_upstream(rx.sender->device) || g.level != PKR_LEVEL_CRITICAL || !cfg_.autonomy.enabled) {
    sink_.emit(heard);
    return;
  }
  last_gauge_alarm_ms_ = clock_.ms();
  bool silent = cloud_silent();
  if (cfg_.autonomy.shadow_mode) {
    heard.would_sound = (silent || cfg_.autonomy.fast_path) ? 1 : 0;
    sink_.emit(heard);
    return;
  }
  if (!(silent || cfg_.autonomy.fast_path)) {
    sink_.emit(heard);  // the cloud path (officer approval) handles it
    return;
  }
  if (order_.active && order_.autonomous) return;  // re-armed: last_gauge_alarm_ms_ moved on
  if (order_.active && order_.prio > PKR_PRIO_AUTONOMY) {
    sink_.emit(heard);  // already sounding an approved Critical
    return;
  }
  Request r;
  r.action = PKR_ACTION_SOUND;
  r.pattern = PKR_PATTERN_C1;
  r.level = PKR_LEVEL_CRITICAL;
  r.src = PKR_SRC_AUTONOMY;
  r.via = PKR_VIA_LORA;
  snprintf(r.id, sizeof r.id, "auto-%.22s-%lu", rx.sender->device, (unsigned long)rx.frame.ctr);
  start(r, true, 0xFFFF, cfg_.autonomy.cap_on_s);
  Event e = make_event(PKR_EVT_AUTONOMOUS_TRIGGER);
  SCOPY(e.cmd_id, r.id);
  e.pattern = PKR_PATTERN_C1;
  e.src = PKR_SRC_AUTONOMY;
  e.via = PKR_VIA_LORA;
  SCOPY(e.frame_src, rx.sender->device);
  snprintf(e.detail, sizeof e.detail, "stage_cm=%d", g.stage_cm);
  sink_.emit(e);
  if (sms_) {
    char t[100], hm[6];
    hhmm_ist(clock_.unix_s(), hm);
    snprintf(t, sizeof t, "PKR AUTO C %s %s %dcm %s", set_.village, rx.sender->device, g.stage_cm, hm);
    sms_->send(nullptr, t);
  }
}

bool SirenCore::rate_ok(uint16_t source) {
  uint32_t now = clock_.ms();
  RateSlot* slot = nullptr;
  for (auto& s : rate_)
    if (s.n && s.source == source) slot = &s;
  if (!slot)
    for (auto& s : rate_)
      if (!s.n) {
        slot = &s;
        s.source = source;
        break;
      }
  if (!slot) slot = &rate_[0];
  uint8_t live = 0;
  uint32_t keep[PKR_LIMIT_MANUAL_RATE_PER_HOUR];
  for (uint8_t i = 0; i < slot->n; i++)
    if (now - slot->t[i] < 3600000u) keep[live++] = slot->t[i];
  if (live >= PKR_LIMIT_MANUAL_RATE_PER_HOUR) {
    memcpy(slot->t, keep, sizeof(uint32_t) * live);
    slot->n = live;
    return false;
  }
  keep[live++] = now;
  memcpy(slot->t, keep, sizeof(uint32_t) * live);
  slot->n = live;
  return true;
}

void SirenCore::manual(uint8_t level, uint8_t src, uint16_t source, const char* frame_src) {
  uint8_t pattern = level == PKR_LEVEL_CRITICAL ? PKR_PATTERN_C1 : PKR_PATTERN_W1;
  uint8_t prio = priority_of(pattern, src);
  uint8_t via = src == PKR_SRC_KEY_SWITCH ? PKR_VIA_LOCAL : PKR_VIA_LORA;
  if (order_.active && order_.manual_source == source && order_.pattern == pattern) {
    order_.manual_until_ms = clock_.ms() + PKR_LIMIT_MANUAL_CAP_S * 1000u;  // held again: 10 more minutes
    return;
  }
  if (order_.active && prio < order_.prio) {
    reject(PKR_REASON_LOWER_PRIORITY, "", via, frame_src);
    return;
  }
  if (!rate_ok(source)) {
    reject(PKR_REASON_RATE_LIMITED, "", via, frame_src);
    return;
  }
  Request r;
  r.action = PKR_ACTION_SOUND;
  r.pattern = pattern;
  r.level = level;
  r.src = src;
  r.via = via;
  snprintf(r.id, sizeof r.id, "manual-%.24s-%lu", frame_src && frame_src[0] ? frame_src : "key",
           (unsigned long)(clock_.ms() / 1000u));
  start(r, false, source, PKR_LIMIT_MANUAL_CAP_S);
  Event e = make_event(PKR_EVT_MANUAL_TRIGGER);
  SCOPY(e.cmd_id, r.id);
  e.pattern = pattern;
  e.src = src;
  e.via = via;
  SCOPY(e.button, level == PKR_LEVEL_CRITICAL ? "key_critical" : "key_warning");
  SCOPY(e.level, level == PKR_LEVEL_CRITICAL ? "critical" : "warning");
  e.lora_acked = src == PKR_SRC_PRADHAN_BOX ? 1 : -1;  // the siren heard the box and ACKed it
  SCOPY(e.frame_src, frame_src);
  sink_.emit(e);
}

void SirenCore::handle_button(const RxResult& rx) {
  pkr_button_payload_t b;
  pkr_button_payload_decode(rx.frame.payload, &b);
  if (lora_) {
    pkr_ack_payload_t a = {rx.frame.src, rx.frame.ctr};
    uint8_t p[PKR_FT_ACK_LEN];
    pkr_ack_payload_encode(&a, p);
    lora_->send(PKR_FT_ACK, rx.frame.src, p, sizeof p);
  }
  if (b.button == PKR_BUTTON_STOP) {
    if (order_.active && order_.manual_source == rx.frame.src) stop_order(PKR_EVT_STOPPED, "pradhan_stop");
    return;
  }
  if (b.button != PKR_BUTTON_SIREN) return;  // water_rising and ack are for the cloud (the box sends them)
  if (b.hold_ms < PKR_LIMIT_HOLD_MS || (b.key_pos != PKR_KEY_WARNING && b.key_pos != PKR_KEY_CRITICAL)) return;
  uint8_t level = b.key_pos == PKR_KEY_CRITICAL ? PKR_LEVEL_CRITICAL : PKR_LEVEL_WARNING;
  manual(level, PKR_SRC_PRADHAN_BOX, rx.frame.src, rx.sender->device);
}

int SirenCore::handle_wrapped(const RxResult& rx) {
  pkr_wrapped_cmd_t w;
  pkr_wrapped_decode(rx.frame.payload, &w);
  char id[16];
  pkr_hex_encode(w.cmd_id48, 6, id);
  const uint8_t* key = keys_.self_key(keys_.current_kid());
  if (!key) return reject(PKR_REASON_NO_KEYS, id, PKR_VIA_LORA, rx.sender->device);
  // the outer MAC was the forwarder's; this one is the siren's own key: a box or relay cannot forge it
  if (!pkr_wrapped_verify(&w, keys_.device(), key, 32)) return reject(PKR_REASON_BAD_SIG, id, PKR_VIA_LORA, rx.sender->device);
  // the compact form carries no volume, so a T1 on LoRa could never be the silent test: tests come by
  // the shadow or SMS only (the cloud never relays one)
  if (w.action == PKR_ACTION_TEST && w.pattern == PKR_PATTERN_T1)
    return reject(PKR_REASON_BAD_FORMAT, id, PKR_VIA_LORA, rx.sender->device);
  int why = guard_.accept_checked(id, w.ctr, w.exp, GUARD_LORA, clock_.synced(), clock_.unix_s());
  if (why) return reject((uint8_t)why, id, PKR_VIA_LORA, rx.sender->device);
  bool level_ok = w.level == 0 || pkr_cmd_level_name(w.level)[0] != '?';
  if (w.action < PKR_ACTION_SOUND || w.action > PKR_ACTION_TEST || w.pattern == PKR_PATTERN_B1 || w.pattern > PKR_PATTERN_D1 ||
      !level_ok || ((w.pattern == PKR_PATTERN_NONE || w.level == 0) && w.action != PKR_ACTION_STOP))
    return reject(PKR_REASON_BAD_FORMAT, id, PKR_VIA_LORA, rx.sender->device);
  Request r;
  r.action = w.action;
  r.pattern = w.pattern;
  r.level = w.level;
  r.src = w.pattern == PKR_PATTERN_D1 ? PKR_SRC_DRILL : PKR_SRC_APPROVAL;
  r.via = PKR_VIA_LORA;
  SCOPY(r.id, id);
  r.cycles = w.cycles;
  r.cap_on_s = w.cap_on_s;
  r.exp = w.exp;
  r.ctr = w.ctr;
  return act(r);
}

// ---------------------------------------------------------------- SMS

int SirenCore::on_sms(const char* from, const char* text, size_t len) {
  note_time();
  // the sender must be allow-listed (a salted hash: no number is stored on the device)
  char h[65];
  pkr_sms_sender_hash(set_.sms_salt, from, h);
  bool allowed = false;
  for (uint8_t i = 0; i < cfg_.n_sms_allow; i++)
    if (!strcmp(cfg_.sms_allow[i], h)) allowed = true;
  pkr_sms_t s;
  memset(&s, 0, sizeof s);
  int why = guard_.accept_sms(text, len, allowed, keys_, keys_.current_kid(), clock_.synced(), clock_.unix_s(), &s);
  char id[PKR_ID_MAX];
  snprintf(id, sizeof id, "sms:%lu", (unsigned long)s.ctr);
  if (why) {
    if (why != PKR_REASON_SENDER && sms_) {  // no SMS spent on strangers
      char reply[64];
      snprintf(reply, sizeof reply, "PUKAAR REJECT %s", pkr_reason_name(why));
      sms_->send(from, reply);
    }
    return reject((uint8_t)why, why == PKR_REASON_SENDER || why == PKR_REASON_MALFORMED ? "" : id, PKR_VIA_SMS);
  }
  Request r;
  r.action = (uint8_t)pkr_sms_action_from_letter(s.action);
  r.pattern = (uint8_t)pkr_sms_pattern_from_letter(s.level);
  r.level = (uint8_t)pkr_pattern_cmd_level(r.pattern);
  r.src = r.pattern == PKR_PATTERN_D1 ? PKR_SRC_DRILL : r.pattern == PKR_PATTERN_T1 ? PKR_SRC_SCHEDULE : PKR_SRC_APPROVAL;
  r.via = PKR_VIA_SMS;
  SCOPY(r.id, id);
  r.exp = s.exp;
  r.ctr = s.ctr;
  SCOPY(r.sms_from, from);
  int rc = act(r);
  if (rc && sms_) {
    char reply[64];
    snprintf(reply, sizeof reply, "PUKAAR REJECT %s", pkr_reason_name(rc));
    sms_->send(from, reply);
  }
  return rc;
}

// ---------------------------------------------------------------- local controls

void SirenCore::set_key(uint8_t pos) {
  if (pos == key_) return;
  key_ = pos;
  hold_since_ms_ = clock_.ms();  // a key turned mid-hold restarts the 3 s
  hold_fired_ = false;
  if (pos == PKR_KEY_OFF && order_.active && order_.manual_source == 0) stop_order(PKR_EVT_STOPPED, "key_off");
}

void SirenCore::set_hold(bool pressed) {
  if (pressed == hold_) return;
  hold_ = pressed;
  if (pressed) {
    hold_since_ms_ = clock_.ms();
    hold_fired_ = false;
  }
}

void SirenCore::set_door(bool open) {
  if (open == door_open_) return;
  door_open_ = open;
  if (open) {
    faults_ |= FAULT_TAMPER;
    sink_.emit(make_event(PKR_EVT_TAMPER));
  } else {
    faults_ &= (uint16_t)~FAULT_TAMPER;
  }
}

void SirenCore::set_soc(uint8_t soc) {
  uint8_t t = soc >= PKR_TIER_NORMAL_MIN_SOC              ? PKR_TIER_NORMAL
              : soc >= PKR_TIER_NO_AUDIBLE_TESTS_MIN_SOC ? PKR_TIER_NO_AUDIBLE_TESTS
              : soc >= PKR_TIER_ALARM_RESERVE_MIN_SOC    ? PKR_TIER_ALARM_RESERVE
                                                         : PKR_TIER_ALARM_ONLY;
  if (tier_known_ && t == tier_) return;
  tier_known_ = true;
  tier_ = t;
  Event e = make_event(PKR_EVT_POWER);
  e.has_meas = true;
  e.meas.soc = soc;
  snprintf(e.detail, sizeof e.detail, "tier=%u", t);
  sink_.emit(e);
}

void SirenCore::cloud_contact() {
  ever_contact_ = true;
  last_contact_ms_ = clock_.ms();
}

void SirenCore::set_cloud_link(bool up) {
  link_up_ = up;
  if (up) cloud_contact();
}

void SirenCore::power_down_warning() { rx_.flush(); }

// ---------------------------------------------------------------- outputs

void SirenCore::set_relay(uint8_t k, bool on) {
  if (relays_[k] == on) return;
  relays_[k] = on;
  hal_.relay(k, on);
}

void SirenCore::all_off() {
  hal_.audio_off();
  last_hz_ = 0;
  last_vol_ = 0;
  for (uint8_t k = 0; k < 4; k++) set_relay(k, false);
}

void SirenCore::apply_outputs(const Output& o) {
  set_relay(K1_AMP, o.in_block);  // the 24 V boost and amp only while a block sounds
  set_relay(K3_SIREN, o.k3);
  set_relay(K4_STROBE, o.strobe);
  if (o.tone) {
    if (o.freq_hz != last_hz_ || o.volume != last_vol_) hal_.tone(o.freq_hz, o.volume, o.sweep);
    last_hz_ = o.freq_hz;
    last_vol_ = o.volume;
  } else if (last_hz_) {
    hal_.tone(0, 0, false);
    last_hz_ = 0;
  }
  if (o.clip_start) {
    const char* name = (o.clip == CLIP_WARNING || o.clip == CLIP_CRITICAL || o.clip == CLIP_ALL_CLEAR) ? order_.clip : "";
    hal_.clip(o.clip, name, o.volume);
  }
  uint32_t now = clock_.ms();
  if ((relays_[K1_AMP] || relays_[K3_SIREN]) && now - last_feed_ms_ >= 1000u) {
    hal_.feed_oneshot();
    last_feed_ms_ = now;
  }
}

void SirenCore::verify_step(const Output& o) {
  if (verify_stage_ == 0 || verify_stage_ == 3) return;
  uint32_t now = clock_.ms();
  bool long_tone = o.tone && o.tone_seg_ms >= 4000u;
  if (verify_stage_ == 1) {
    if (!(long_tone && o.tone_seg_elapsed_ms >= PKR_LIMIT_VERIFY_WINDOW_START_MS &&
          o.tone_seg_elapsed_ms <= PKR_LIMIT_VERIFY_WINDOW_END_MS))
      return;
  } else if (!(o.tone && now >= verify_at_ms_)) {
    return;
  }
  Meas m;
  m.amp_a = hal_.amp_a();
  m.amp_a_ref = cfg_.amp_a_ref;
  m.siren_a = hal_.siren_a();
  float mic = hal_.mic_db();
  m.spl_rise_db = mic - pre_db_;
  m.ambient_db_rel = pre_db_;
  bool mic_dead = hal_.mic_dead();
  bool amp_ok = is_verified(true, m.amp_a, false, 0, cfg_.amp_a_ref, 0, true);
  bool ok = is_verified(true, m.amp_a, true, m.spl_rise_db, cfg_.amp_a_ref, cfg_.spl_rise_min_db, mic_dead);
  bool spl_ok = ok || !amp_ok;
  last_meas_ = m;
  if (mic_dead) faults_ |= FAULT_MIC_DEAD;
  Event e = make_event(ok ? PKR_EVT_VERIFIED : PKR_EVT_NOT_VERIFIED);
  SCOPY(e.cmd_id, order_.cmd_id);
  e.pattern = order_.pattern;
  e.via = order_.via;
  e.src = order_.src;
  e.has_meas = true;
  e.meas = m;
  e.fallback = verify_stage_ == 2;
  if (mic_dead) e.faults = FAULT_MIC_DEAD;  // the cloud re-checks "verified" with the device's faults
  if (!amp_ok) SCOPY(e.detail, "amp_current");
  else if (!spl_ok) SCOPY(e.detail, "no_spl_rise");
  sink_.emit(e);
  if (ok) {
    verified_ = true;
    faults_ &= (uint16_t)~FAULT_AMP;
    verify_stage_ = 3;
    send_sms_reply(true, nullptr);
  } else if (verify_stage_ == 1) {
    hal_.fallback_source(true);  // DFPlayer silent? try the LEDC tone, then check once more
    verify_stage_ = 2;
    verify_at_ms_ = now + 3000u;
  } else {
    faults_ |= FAULT_AMP;  // the horns stay on: a failed check never silences an alarm
    verify_stage_ = 3;
    send_sms_reply(false, e.detail);
  }
}

// ---------------------------------------------------------------- silent test

void SirenCore::run_silent_test(const char* cmd_id) {
  if (order_.active || test_.active) return;  // never interrupts a sound; the schedule retries
  test_.active = true;
  SCOPY(test_.cmd_id, cmd_id);
  if (cmd_id && cmd_id[0]) {
    Event e = make_event(PKR_EVT_STARTED);
    SCOPY(e.cmd_id, cmd_id);
    e.pattern = PKR_PATTERN_T1;
    sink_.emit(e);
  }
  test_.start_ms = clock_.ms();
  test_.amp = -1;
  set_relay(K2_HORNS, false);  // dummy load: a silent test is never audible
  set_relay(K3_SIREN, false);
  set_relay(K1_AMP, true);
  hal_.fallback_source(false);
  hal_.tone(900, 30, false);
  last_hz_ = 900;
}

void SirenCore::silent_test_step() {
  if (!test_.active) return;
  uint32_t el = clock_.ms() - test_.start_ms;
  if (el >= 2500u && test_.amp < 0) test_.amp = hal_.amp_a();
  if (el < 3000u) {
    if (relays_[K1_AMP] && clock_.ms() - last_feed_ms_ >= 1000u) {
      hal_.feed_oneshot();
      last_feed_ms_ = clock_.ms();
    }
    return;
  }
  all_off();
  test_.active = false;
  uint16_t f = hal_.selftest_faults();
  float ref = set_.amp_a_test_ref;
  bool amp_ok = test_.amp >= ref * PKR_LIMIT_VERIFY_AMP_LO_PCT / 100.0f && test_.amp <= ref * PKR_LIMIT_VERIFY_AMP_HI_PCT / 100.0f;
  bool mic_ok = !hal_.mic_dead();
  if (!amp_ok) f |= FAULT_AMP;
  if (!mic_ok) f |= FAULT_MIC_DEAD;
  uint16_t mask = FAULT_AMP | FAULT_MIC_DEAD | FAULT_DFPLAYER | FAULT_CATALOG | FAULT_LORA | FAULT_MODEM | FAULT_SIREN_LINE |
                  FAULT_INA226;
  faults_ = (uint16_t)((faults_ & ~mask) | f);
  Event e = make_event(PKR_EVT_TEST_RESULT);
  SCOPY(e.cmd_id, test_.cmd_id);
  e.test_kind = 1;
  e.ok = f ? 0 : 1;
  e.faults = f;
  e.has_meas = true;
  e.meas.amp_a = test_.amp;
  e.meas.amp_a_ref = ref;
  int n = snprintf(e.detail, sizeof e.detail, "amp=%s", amp_ok ? "ok" : "bad");
  for (uint16_t bit = FAULT_MIC_DEAD; bit && bit <= FAULT_INA226; bit <<= 1)
    if ((f & bit) && n > 0 && (size_t)n < sizeof e.detail)
      n += snprintf(e.detail + n, sizeof e.detail - (size_t)n, ",%s", fault_name(bit));
  sink_.emit(e);
  if (test_.cmd_id[0]) {
    Event fin = make_event(PKR_EVT_FINISHED);
    SCOPY(fin.cmd_id, test_.cmd_id);
    fin.pattern = PKR_PATTERN_T1;
    sink_.emit(fin);
  }
}

// ---------------------------------------------------------------- tick

void SirenCore::tick() {
  uint32_t now = clock_.ms();
  note_time();
  // ambient microphone level while quiet, sampled every 100 ms over the last 2 s
  if (!order_.active && !test_.active && now - mic_last_ms_ >= 100u) {
    mic_last_ms_ = now;
    mic_ring_[mic_i_] = hal_.mic_db();
    mic_i_ = (uint8_t)((mic_i_ + 1) % 20);
    if (mic_n_ < 20) mic_n_++;
  }
  silent_test_step();

  // the local key switch: key at W or C and HOLD held for 3 s
  if (hold_ && key_ != PKR_KEY_OFF && !hold_fired_ && now - hold_since_ms_ >= PKR_LIMIT_HOLD_MS) {
    hold_fired_ = true;
    manual(key_ == PKR_KEY_CRITICAL ? PKR_LEVEL_CRITICAL : PKR_LEVEL_WARNING, PKR_SRC_KEY_SWITCH, 0, "");
  }

  if (!order_.active) return;
  if (order_.manual_source != 0xFFFF && (int32_t)(now - order_.manual_until_ms) >= 0) {
    stop_order(PKR_EVT_FINISHED, "manual_cap");
    return;
  }
  if (order_.autonomous && now - last_gauge_alarm_ms_ >= PKR_LIMIT_AUTONOMY_QUIET_STOP_S * 1000u) {
    stop_order(PKR_EVT_FINISHED, "no_gauge_alarm_15min");
    return;
  }
  if (order_.exp && clock_.synced() && clock_.unix_s() > order_.exp) {
    stop_order(PKR_EVT_FINISHED, "expired");
    return;
  }
  const Output& o = player_.tick(now);
  if (!o.active) {
    stop_order(PKR_EVT_FINISHED, player_.ended_by_cap() ? "cap" : "done");
    return;
  }
  apply_outputs(o);
  verify_step(o);
}

}  // namespace pkr
