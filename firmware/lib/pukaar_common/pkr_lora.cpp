#include "pkr_lora.h"

#include <stdio.h>
#include <string.h>

namespace pkr {

void FrameReceiver::begin(KeyRing* keys, Kv* kv) {
  keys_ = keys;
  kv_ = kv;
  for (auto& s : slots_) s.used = false;
}

LazyCounter* FrameReceiver::counter_for(uint16_t addr) {
  for (auto& s : slots_)
    if (s.used && s.addr == addr) return &s.ctr;
  for (auto& s : slots_)
    if (!s.used) {
      s.used = true;
      s.addr = addr;
      char key[16];
      snprintf(key, sizeof key, "rx%04x", addr);
      s.ctr.load_receive(kv_, key);
      return &s.ctr;
    }
  return nullptr;
}

RxResult FrameReceiver::receive(const uint8_t* buf, size_t n, uint32_t now_unix, bool clock_synced) {
  RxResult r;
  if (pkr_frame_parse(buf, n, &r.frame) != PKR_FRAME_OK) {
    r.reason = PKR_REASON_MALFORMED;
    return r;
  }
  const pkr_frame_t& f = r.frame;
  if (f.dst != PKR_FRAME_BROADCAST && f.dst != keys_->addr()) {
    r.reason = -1;
    return r;
  }
  const Sender* s = keys_->sender(f.src);
  if (!s) {
    r.reason = PKR_REASON_UNKNOWN_SRC;
    return r;
  }
  r.sender = s;
  uint8_t need = role_for_frame_type(f.type);
  if (!need || !(s->roles & need)) {
    r.reason = PKR_REASON_ROLE;
    return r;
  }
  if (pkr_frame_type_len_ok(f.type, f.len) != PKR_FRAME_OK) {
    r.reason = PKR_REASON_MALFORMED;
    return r;
  }
  if (!pkr_frame_mac_ok(buf, n, s->key, sizeof s->key)) {
    r.reason = PKR_REASON_BAD_MAC;
    return r;
  }
  LazyCounter* c = counter_for(f.src);
  if (!c || f.ctr <= c->value()) {
    r.reason = PKR_REASON_REPLAYED;
    return r;
  }
  if (clock_synced && f.ts != 0) {
    uint32_t d = f.ts > now_unix ? f.ts - now_unix : now_unix - f.ts;
    if (d >= PKR_FRAME_TS_WINDOW_S) {
      r.reason = PKR_REASON_CLOCK_SKEW;
      return r;
    }
  }
  c->observe(f.ctr);  // written through to NVS before the caller acts on the frame
  r.reason = 0;
  return r;
}

void FrameReceiver::flush() {
  for (auto& s : slots_)
    if (s.used) s.ctr.flush();
}

void FrameSigner::begin(KeyRing* keys, Kv* kv) {
  keys_ = keys;
  ctr_.load_send(kv, "txctr");
}

int FrameSigner::build(uint8_t type, uint16_t dst, const uint8_t* payload, uint8_t len, uint32_t ts, uint8_t* out,
                       size_t cap, uint32_t* ctr_out) {
  const uint8_t* key = keys_->self_key(keys_->current_kid());
  if (!key) return -100;
  if (len > PKR_FRAME_MAX_PAYLOAD) return PKR_FRAME_E_LEN;
  pkr_frame_t f{};
  f.ver = PKR_FRAME_VERSION;
  f.type = type;
  f.src = keys_->addr();
  f.dst = dst;
  f.ctr = ctr_.next();
  f.ts = ts;
  f.len = len;
  memcpy(f.payload, payload, len);
  if (ctr_out) *ctr_out = f.ctr;
  return pkr_frame_encode(&f, key, 32, out, cap);
}

void LoraLink::begin(RadioPort* radio, FrameSigner* signer, uint32_t budget_ms) {
  radio_ = radio;
  signer_ = signer;
  pkr_duty_init(&duty_, budget_ms, PKR_DUTY_TELEMETRY_STOP_PCT);
}

bool LoraLink::is_alarm_type(uint8_t type) {
  return type == PKR_FT_GAUGE_ALARM || type == PKR_FT_BUTTON || type == PKR_FT_SIREN_CMD_WRAPPED || type == PKR_FT_ACK ||
         type == PKR_FT_SIREN_EVENT;
}

static uint32_t airtime_for(size_t n) {
  return pkr_lora_airtime_ms((unsigned)n, PKR_RADIO_SF, PKR_RADIO_BW_HZ, PKR_RADIO_CR, PKR_RADIO_PREAMBLE, 1, 1);
}

bool LoraLink::send(uint8_t type, uint16_t dst, const uint8_t* payload, uint8_t len, uint32_t now_unix,
                    bool clock_synced, uint32_t* ctr_out) {
  size_t n = PKR_FRAME_HEADER_LEN + len + PKR_FRAME_MAC_LEN;
  if (!pkr_duty_can_send(&duty_, now_unix, airtime_for(n), is_alarm_type(type))) {
    refused++;
    return false;
  }
  uint8_t buf[PKR_FRAME_MAX_LEN];
  int k = signer_->build(type, dst, payload, len, clock_synced ? now_unix : 0, buf, sizeof buf, ctr_out);
  if (k < 0) return false;
  pkr_duty_record(&duty_, now_unix, airtime_for((size_t)k));
  return radio_->transmit(buf, (size_t)k);
}

bool LoraLink::send_raw(const uint8_t* frame, size_t n, uint32_t now_unix, bool alarm) {
  if (!pkr_duty_can_send(&duty_, now_unix, airtime_for(n), alarm)) {
    refused++;
    return false;
  }
  pkr_duty_record(&duty_, now_unix, airtime_for(n));
  return radio_->transmit(frame, n);
}

}  // namespace pkr
