#include "pkr_guard.h"

#include <stdio.h>
#include <string.h>

namespace pkr {

struct GuardBlob {
  uint32_t magic;
  uint32_t last[3];
  uint32_t lkt;
  uint8_t head;
  char ids[PKR_LIMIT_RECENT_CMD_IDS][PKR_ID_MAX];
};
static const uint32_t GUARD_MAGIC = 0x50475231u;  // "PGR1"

void CommandGuard::load(Kv* kv) {
  kv_ = kv;
  GuardBlob b;
  if (kv_ && kv_->get_blob("guard", &b, sizeof b) == sizeof b && b.magic == GUARD_MAGIC) {
    for (int i = 0; i < 3; i++) last_[i] = b.last[i];  // exactly: written through on every accept
    lkt_ = lkt_saved_ = b.lkt;
    head_ = b.head % PKR_LIMIT_RECENT_CMD_IDS;
    memcpy(ids_, b.ids, sizeof ids_);
  }
}

void CommandGuard::save() {
  if (!kv_) return;
  GuardBlob b;
  b.magic = GUARD_MAGIC;
  memcpy(b.last, last_, sizeof last_);
  b.lkt = lkt_;
  b.head = head_;
  memcpy(b.ids, ids_, sizeof ids_);
  kv_->put_blob("guard", &b, sizeof b);
  lkt_saved_ = lkt_;
}

bool CommandGuard::fresh(const char* id, uint32_t ctr, uint8_t via) const {
  for (int i = 0; i < PKR_LIMIT_RECENT_CMD_IDS; i++)
    if (ids_[i][0] && strncmp(ids_[i], id, PKR_ID_MAX) == 0) return false;
  return ctr > last_[via];
}

int CommandGuard::expiry(uint32_t exp, bool synced, uint32_t now) const {
  if (synced) return now > exp ? PKR_REASON_EXPIRED : 0;
  if ((uint64_t)exp > (uint64_t)lkt_ + PKR_SMS_UNSYNCED_EXP_WINDOW_S) return PKR_REASON_EXP_WINDOW;
  return 0;
}

void CommandGuard::accept(const char* id, uint32_t ctr, uint8_t via, bool synced, uint32_t now) {
  last_[via] = ctr;
  strncpy(ids_[head_], id, PKR_ID_MAX - 1);
  ids_[head_][PKR_ID_MAX - 1] = 0;
  head_ = (uint8_t)((head_ + 1) % PKR_LIMIT_RECENT_CMD_IDS);
  if (synced && now > lkt_) lkt_ = now;
  save();
}

void CommandGuard::note_time(uint32_t now) {
  if (now <= lkt_) return;
  lkt_ = now;
  if (lkt_ - lkt_saved_ >= 3600u) save();
}

int CommandGuard::accept_checked(const char* id, uint32_t ctr, uint32_t exp, uint8_t via, bool synced, uint32_t now) {
  if (!fresh(id, ctr, via)) return PKR_REASON_REPLAYED;
  int why = expiry(exp, synced, now);
  if (why) return why;
  accept(id, ctr, via, synced, now);
  return 0;
}

int CommandGuard::accept_cmd(const pkr_cmd_t& c, const KeyRing& keys, uint8_t via, bool synced, uint32_t now) {
  const uint8_t* key = c.kid <= 255 ? keys.self_key((uint8_t)c.kid) : nullptr;
  if (!key) return PKR_REASON_WRONG_KID;
  if (!pkr_cmd_verify(&c, key, 32)) return PKR_REASON_BAD_SIG;
  return accept_checked(c.id, c.ctr, c.exp, via, synced, now);
}

int CommandGuard::accept_sms(const char* text, size_t len, bool sender_allowed, const KeyRing& keys, uint8_t kid,
                             bool synced, uint32_t now, pkr_sms_t* out) {
  if (!sender_allowed) return PKR_REASON_SENDER;
  pkr_sms_t s;
  if (pkr_sms_parse(text, len, &s) != PKR_SMS_OK) return PKR_REASON_MALFORMED;
  if (out) *out = s;
  const uint8_t* key = keys.self_key(kid);
  if (strcmp(s.device, keys.device()) != 0 || !key || !pkr_sms_verify(&s, key, 32)) return PKR_REASON_BAD_SIG;
  char id[PKR_ID_MAX];
  snprintf(id, sizeof id, "sms:%lu", (unsigned long)s.ctr);
  return accept_checked(id, s.ctr, s.exp, GUARD_SMS, synced, now);
}

bool is_verified(bool has_amp, float amp_a, bool has_rise, float spl_rise_db, float amp_a_ref, float spl_rise_min_db,
                 bool mic_dead) {
  if (!has_amp || amp_a_ref <= 0) return false;
  if (amp_a < 0.6f * amp_a_ref || amp_a > 1.5f * amp_a_ref) return false;
  if (mic_dead) return true;
  return has_rise && spl_rise_db >= spl_rise_min_db;
}

}  // namespace pkr
