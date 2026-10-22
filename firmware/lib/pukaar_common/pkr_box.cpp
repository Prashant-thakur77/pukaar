#include "pkr_box.h"

#include <ArduinoJson.h>
#include <stdio.h>
#include <string.h>

namespace pkr {

// ---------------------------------------------------------------- event log

void EventLog::begin(Outbox* ob, uint32_t boot, EventSink* mirror) {
  ob_ = ob;
  boot_ = boot;
  seq_ = 0;
  mirror_ = mirror;
}

void EventLog::emit(const Event& e) {
  seq_++;
  char buf[PKR_OUTBOX_MAX_PAYLOAD];
  size_t n = event_to_json(e, boot_, seq_, buf, sizeof buf);
  if (!n || !ob_ || !ob_->push(e.type, boot_, seq_, buf, (uint16_t)n)) lost++;
  if (mirror_) mirror_->emit(e);
}

size_t build_backfill(const OutRecord* recs, size_t n, char* out, size_t cap) {
  size_t len = 0;
  const char* head = "{\"events\":[";
  size_t hl = strlen(head);
  if (cap < hl + 3) return 0;
  memcpy(out, head, hl);
  len = hl;
  for (size_t i = 0; i < n; i++) {
    size_t pl = recs[i].payload.size();
    if (len + pl + 3 > cap) return 0;
    if (i) out[len++] = ',';
    memcpy(out + len, recs[i].payload.data(), pl);
    len += pl;
  }
  out[len++] = ']';
  out[len++] = '}';
  out[len] = 0;
  return len;
}

// ---------------------------------------------------------------- pradhan box

Event BoxCore::ev(uint8_t type) {
  Event e;
  e.type = type;
  e.at = clock_.unix_s();  // required by the cloud; the best estimate when unsynced
  e.simulated = simulated_;
  return e;
}

void BoxCore::set_button(uint8_t b, bool level) {
  if (b > 3) return;
  Btn& x = btn_[b];
  if (level != x.raw) {
    x.raw = level;
    x.since = clock_.ms();
  }
}

void BoxCore::set_key(uint8_t pos) {
  if (pos == key_) return;
  key_ = pos;
  hold_since_ = clock_.ms();  // turning the key mid-hold restarts the 3 s
  hold_fired_ = false;
}

void BoxCore::pressed(uint8_t b) {
  uint32_t now = clock_.ms();
  if (b == BOX_A_WATER || b == BOX_B_ACK) {
    // a second press within 10 s is the same report
    if (last_ab_ms_[b] && now - last_ab_ms_[b] < 10000u) return;
    last_ab_ms_[b] = now;
    Event e = ev(b == BOX_A_WATER ? PKR_EVT_REPORT : PKR_EVT_ACK);
    strcpy(e.button, b == BOX_A_WATER ? "water_rising" : "ack");
    e.src = PKR_SRC_PRADHAN_BOX;
    sink_.emit(e);
  } else if (b == BOX_D_STOP) {
    port_.lora_button(PKR_BUTTON_STOP, PKR_KEY_OFF, 0);
    if (pending_.active) report_manual(false);
    Event e = ev(PKR_EVT_STOPPED);
    strcpy(e.button, "stop");
    e.src = PKR_SRC_PRADHAN_BOX;
    sink_.emit(e);
  } else if (b == BOX_C_HOLD) {
    hold_since_ = now;
    hold_fired_ = false;
  }
}

bool BoxCore::rate_ok() {
  uint32_t now = clock_.ms();
  uint8_t live = 0;
  for (uint8_t i = 0; i < n_starts_; i++)
    if (now - starts_[i] < 3600000u) starts_[live++] = starts_[i];
  n_starts_ = live;
  if (live >= PKR_LIMIT_MANUAL_RATE_PER_HOUR) return false;
  starts_[n_starts_++] = now;
  return true;
}

// The MQTT event, once the LoRa ACK wait is over: lora_acked tells the cloud whether a siren
// already heard the box. If none did, the cloud sounds the village's sirens itself
// (system-propagate-pradhan-siren, own village only).
void BoxCore::report_manual(bool acked) {
  pending_.active = false;
  Event e = ev(PKR_EVT_MANUAL_TRIGGER);
  strcpy(e.button, pending_.key_pos == PKR_KEY_CRITICAL ? "key_critical" : "key_warning");
  strcpy(e.level, pending_.key_pos == PKR_KEY_CRITICAL ? "critical" : "warning");
  e.lora_acked = acked ? 1 : 0;
  e.src = PKR_SRC_PRADHAN_BOX;
  e.pattern = pending_.key_pos == PKR_KEY_CRITICAL ? PKR_PATTERN_C1 : PKR_PATTERN_W1;
  e.at = pending_.at;
  sink_.emit(e);
}

void BoxCore::fire_manual() {
  if (!rate_ok()) {
    Event e = ev(PKR_EVT_REJECTED);
    e.reason = PKR_REASON_RATE_LIMITED;
    strcpy(e.button, key_ == PKR_KEY_CRITICAL ? "key_critical" : "key_warning");
    e.src = PKR_SRC_PRADHAN_BOX;
    sink_.emit(e);
    return;
  }
  uint16_t hold = (uint16_t)(clock_.ms() - hold_since_);
  pending_.active = true;
  pending_.button = PKR_BUTTON_SIREN;
  pending_.key_pos = key_;
  pending_.hold_ms = hold;
  pending_.tries = 1;
  pending_.sent_ms = clock_.ms();
  pending_.at = clock_.unix_s();
  pending_.ctr = port_.lora_button(PKR_BUTTON_SIREN, key_, hold);
}

void BoxCore::on_ack(uint16_t, uint32_t acked_ctr) {
  on_lora_heard();
  if (pending_.active && acked_ctr == pending_.ctr) report_manual(true);
}

void BoxCore::on_lora_heard() {
  lora_seen_ = true;
  last_lora_ms_ = clock_.ms();
}

void BoxCore::set_level(uint8_t level, uint8_t clip_role) {
  level_ = level;
  port_.level_leds(level);
  if (level >= PKR_LEVEL_WATCH) port_.play(clip_role, level == PKR_LEVEL_WATCH);  // a chime only at Watch
}

void BoxCore::tick() {
  uint32_t now = clock_.ms();
  for (uint8_t b = 0; b < 4; b++) {
    Btn& x = btn_[b];
    if (x.raw != x.stable && now - x.since >= 50u) {
      x.stable = x.raw;
      if (x.stable) pressed(b);
    }
  }
  if (btn_[BOX_C_HOLD].stable && key_ != PKR_KEY_OFF && !hold_fired_ && now - hold_since_ >= PKR_LIMIT_HOLD_MS) {
    hold_fired_ = true;
    fire_manual();
  }
  if (pending_.active && now - pending_.sent_ms >= PKR_LIMIT_BOX_ACK_WAIT_MS) {
    if (pending_.tries < PKR_LIMIT_BOX_ACK_TRIES) {
      pending_.tries++;
      pending_.sent_ms = now;
      pending_.ctr = port_.lora_button(pending_.button, pending_.key_pos, pending_.hold_ms);
    } else {
      report_manual(false);
      if (!port_.cloud_up()) {
        char t[64], hm[6];
        hhmm_ist(clock_.unix_s(), hm);
        snprintf(t, sizeof t, "PKR MANUAL %c %s %s", pending_.key_pos == PKR_KEY_CRITICAL ? 'C' : 'W', village_, hm);
        port_.sms_officers(t);
      }
    }
  }
  bool lora_ok = lora_seen_ && now - last_lora_ms_ < 900000u;
  port_.link_led(port_.cloud_up() ? 1 : lora_ok ? 2 : 3);
}

// ---------------------------------------------------------------- relay

void RelayCore::begin(LoraLink* link, uint16_t self_addr, uint32_t (*rnd)()) {
  link_ = link;
  self_ = self_addr;
  rnd_ = rnd;
}

bool RelayCore::on_rx(const uint8_t* buf, size_t n, uint32_t now_ms) {
  pkr_frame_t f;
  if (pkr_frame_parse(buf, n, &f) != PKR_FRAME_OK) {
    malformed++;
    return false;
  }
  if (f.src == self_) return false;
  for (auto& s : seen_)
    if (s.used && s.src == f.src && s.ctr == f.ctr && now_ms - s.t < PKR_LIMIT_RELAY_DEDUPE_S * 1000u) {
      duplicates++;
      return false;
    }
  Seen& s = seen_[seen_i_];
  seen_i_ = (uint8_t)((seen_i_ + 1) % 64);
  s = {f.src, f.ctr, now_ms, true};
  for (auto& p : q_)
    if (!p.used) {
      p.used = true;
      uint32_t span = PKR_LIMIT_RELAY_BACKOFF_MAX_MS - PKR_LIMIT_RELAY_BACKOFF_MIN_MS;
      p.due = now_ms + PKR_LIMIT_RELAY_BACKOFF_MIN_MS + (rnd_ ? rnd_() % (span + 1) : 0);
      p.n = (uint8_t)n;
      memcpy(p.buf, buf, n);
      p.alarm = LoraLink::is_alarm_type(f.type);
      return true;
    }
  return false;  // queue full: drop (the sender retries alarm frames)
}

void RelayCore::tick(uint32_t now_ms, uint32_t now_unix, bool synced, const pkr_beacon_payload_t& beacon) {
  for (auto& p : q_)
    if (p.used && (int32_t)(now_ms - p.due) >= 0) {
      if (link_->send_raw(p.buf, p.n, now_unix, p.alarm)) forwarded++;
      p.used = false;
    }
  if (!beacon_sent_ || now_ms - last_beacon_ms_ >= PKR_LIMIT_RELAY_BEACON_S * 1000u) {
    beacon_sent_ = true;
    last_beacon_ms_ = now_ms;
    uint8_t b[PKR_FT_RELAY_BEACON_LEN];
    pkr_beacon_payload_encode(&beacon, b);
    link_->send(PKR_FT_RELAY_BEACON, PKR_FRAME_BROADCAST, b, sizeof b, now_unix, synced);
  }
}

// ---------------------------------------------------------------- OTA gate

static int hhmm_to_min(const char* s) {
  int h = 0, m = 0;
  if (!s || sscanf(s, "%d:%d", &h, &m) != 2 || h < 0 || h > 24 || m < 0 || m > 59) return -1;
  return h * 60 + m;
}

int parse_ota_job(const char* json, size_t len, OtaJob* j) {
  *j = OtaJob();
  JsonDocument d;
  if (deserializeJson(d, json, len)) return PKR_REASON_BAD_FORMAT;
  JsonObjectConst o = d.as<JsonObjectConst>();
  const char* op = o["op"];
  if (!op || (strcmp(op, "ota") && strcmp(op, "clips"))) return PKR_REASON_BAD_FORMAT;
  strcpy(j->op, op);
  const char* fw = o["fw"] | "";
  const char* url = o["url"] | "";
  const char* sha = o["sha256"] | "";
  if (!strcmp(op, "ota")) {
    if (!fw[0] || !url[0] || strlen(sha) != 64 || strlen(url) >= sizeof j->url || strlen(fw) >= sizeof j->fw)
      return PKR_REASON_BAD_FORMAT;
    if (strncmp(url, "https://", 8)) return PKR_REASON_BAD_FORMAT;  // never plain HTTP
  }
  strncpy(j->fw, fw, sizeof j->fw - 1);
  strncpy(j->url, url, sizeof j->url - 1);
  strncpy(j->sha256, sha, sizeof j->sha256 - 1);
  j->size = o["size"] | 0u;
  j->min_soc = o["min_soc"] | 60;
  JsonArrayConst w = o["window"];
  if (w.size() == 2) {
    int a = hhmm_to_min(w[0]), b = hhmm_to_min(w[1]);
    if (a < 0 || b < 0) return PKR_REASON_BAD_FORMAT;
    j->win_start_min = a;
    j->win_end_min = b;
  }
  j->not_if_alert = o["not_if_alert"] | true;
  return 0;
}

const char* ota_gate(const OtaJob& j, int soc, int now_min, bool alert_active) {
  if (j.not_if_alert && alert_active) return "alert_active";
  if (soc < j.min_soc) return "low_soc";
  if (now_min < j.win_start_min || now_min >= j.win_end_min) return "window";
  return "";
}

}  // namespace pkr
