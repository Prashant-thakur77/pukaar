#include "pkr_store.h"

#include <string.h>

namespace pkr {

bool MemKv::get_u32(const char* key, uint32_t* out) {
  auto it = data.find(key);
  if (it == data.end() || it->second.size() != 4) return false;
  memcpy(out, it->second.data(), 4);
  return true;
}

bool MemKv::put_u32(const char* key, uint32_t v) {
  writes++;
  data[key] = std::vector<uint8_t>((uint8_t*)&v, (uint8_t*)&v + 4);
  return true;
}

size_t MemKv::get_blob(const char* key, void* buf, size_t cap) {
  auto it = data.find(key);
  if (it == data.end() || it->second.size() > cap) return 0;
  memcpy(buf, it->second.data(), it->second.size());
  return it->second.size();
}

bool MemKv::put_blob(const char* key, const void* d, size_t len) {
  writes++;
  data[key] = std::vector<uint8_t>((const uint8_t*)d, (const uint8_t*)d + len);
  return true;
}

void LazyCounter::load_receive(Kv* kv, const char* key) {
  kv_ = kv;
  strncpy(key_, key, sizeof key_ - 1);
  write_through_ = true;
  uint32_t stored = 0;
  v_ = kv_->get_u32(key_, &stored) ? stored : 0;  // exactly: it was written when it was accepted
  persisted_ = v_;
}

void LazyCounter::load_send(Kv* kv, const char* key) {
  kv_ = kv;
  strncpy(key_, key, sizeof key_ - 1);
  write_through_ = false;
  uint32_t stored = 0;
  if (kv_->get_u32(key_, &stored)) {
    v_ = stored + PKR_LIMIT_CTR_BOOT_SKIP;
    kv_->put_u32(key_, v_);  // a second reset before the next write skips again, never repeats
  } else {
    v_ = 0;
  }
  persisted_ = v_;
}

void LazyCounter::maybe_persist() {
  if (kv_ && (write_through_ || v_ - persisted_ >= PKR_LIMIT_CTR_PERSIST_EVERY)) flush();
}

uint32_t LazyCounter::next() {
  v_++;
  maybe_persist();
  return v_;
}

void LazyCounter::observe(uint32_t v) {
  if (v <= v_) return;
  v_ = v;
  maybe_persist();
}

void LazyCounter::flush() {
  if (!kv_ || persisted_ == v_) return;
  kv_->put_u32(key_, v_);
  persisted_ = v_;
}

uint8_t role_for_frame_type(uint8_t type) {
  switch (type) {
    case PKR_FT_GAUGE_STATUS: return ROLE_GAUGE_STATUS;
    case PKR_FT_GAUGE_ALARM: return ROLE_GAUGE_ALARM;
    case PKR_FT_SIREN_CMD_WRAPPED: return ROLE_RELAY_CMD;
    case PKR_FT_SIREN_EVENT: return ROLE_SIREN_EVENT;
    case PKR_FT_BUTTON: return ROLE_BUTTON;
    case PKR_FT_HEARTBEAT: return ROLE_HEARTBEAT;
    case PKR_FT_RELAY_BEACON: return ROLE_BEACON;
    case PKR_FT_ACK: return ROLE_ACK;
    default: return 0;
  }
}

uint8_t roles_from_names(const char* const* names, size_t n) {
  static const struct { const char* name; uint8_t bit; } T[] = {
      {"gauge_status", ROLE_GAUGE_STATUS}, {"gauge_alarm", ROLE_GAUGE_ALARM}, {"relay_cmd", ROLE_RELAY_CMD},
      {"siren_event", ROLE_SIREN_EVENT},   {"button", ROLE_BUTTON},           {"heartbeat", ROLE_HEARTBEAT},
      {"beacon", ROLE_BEACON},             {"ack", ROLE_ACK}};
  uint8_t r = 0;
  for (size_t i = 0; i < n; i++)
    for (auto& t : T)
      if (!strcmp(names[i], t.name)) r |= t.bit;
  return r;
}

void KeyRing::set_identity(const char* device, uint16_t lora_addr) {
  strncpy(device_, device, sizeof device_ - 1);
  addr_ = lora_addr;
}

bool KeyRing::set_self_key(uint8_t kid, const uint8_t key[32]) {
  for (uint8_t i = 0; i < n_self_; i++)
    if (self_[i].kid == kid) {
      memcpy(self_[i].key, key, 32);
      return true;
    }
  if (n_self_ >= 4) return false;
  self_[n_self_].kid = kid;
  memcpy(self_[n_self_].key, key, 32);
  n_self_++;
  return true;
}

const uint8_t* KeyRing::self_key(uint8_t kid) const {
  for (uint8_t i = 0; i < n_self_; i++)
    if (self_[i].kid == kid) return self_[i].key;
  return nullptr;
}

bool KeyRing::add_sender(const Sender& s) {
  for (uint8_t i = 0; i < n_senders_; i++)
    if (senders_[i].addr == s.addr) {
      senders_[i] = s;
      return true;
    }
  if (n_senders_ >= sizeof senders_ / sizeof senders_[0]) return false;
  senders_[n_senders_++] = s;
  return true;
}

const Sender* KeyRing::sender(uint16_t addr) const {
  for (uint8_t i = 0; i < n_senders_; i++)
    if (senders_[i].addr == addr) return &senders_[i];
  return nullptr;
}

const Sender* KeyRing::sender_by_name(const char* device) const {
  for (uint8_t i = 0; i < n_senders_; i++)
    if (!strcmp(senders_[i].device, device)) return &senders_[i];
  return nullptr;
}

}  // namespace pkr
