// What a siren checks before it acts on a command: the C twin of siren_model.CommandVerifier
// (backend/src/Pukaar/services/devices/siren_model.py). In order:
//   1. a key for cmd.kid                                   else "wrong_kid"
//      the signature is valid with it                       else "bad_sig"
//   2. cmd.id is not among the last 32 ids, and cmd.ctr is above the last counter seen on the
//      same path (mqtt, sms or lora)                         else "replayed"
//   3. clock synced: now <= exp                              else "expired"
//      clock unsynced: exp within 12 h of the last known time else "exp_window"
// An accepted command (its counter, its id in the ring, the last known time) is written through
// at once, before the siren acts, and restored exactly on boot: no bump. Power lost between the
// accept and the write could let that one command be accepted again; the expiry and, once the
// write lands, the ring of recent ids bound it. The SMS path checks the sender's number hash first ("sender"), then parses
// ("malformed"), then the device id and signature ("bad_sig"); its id is "sms:<ctr>".
#pragma once

#include <stdint.h>

#include "pkr_command.h"
#include "pkr_sms.h"
#include "pkr_store.h"

namespace pkr {

enum GuardVia : uint8_t { GUARD_MQTT = 0, GUARD_SMS = 1, GUARD_LORA = 2 };

class CommandGuard {
 public:
  void load(Kv* kv);  // restores and bumps the counters (+16), the recent ids and the last known time
  // A full command (shadow, or a full command carried over LoRa). cmd.device must be this
  // device's own id: the receiver always signs over its own name.
  int accept_cmd(const pkr_cmd_t& cmd, const KeyRing& keys, uint8_t via, bool synced, uint32_t now);
  // The freshness and expiry steps (2-3) and the persist, for a command whose signature the
  // caller has already checked (the compact LoRa command).
  int accept_checked(const char* id, uint32_t ctr, uint32_t exp, uint8_t via, bool synced, uint32_t now);
  // The SMS path. kid: the key the SMS was signed with (the device's current kid).
  int accept_sms(const char* text, size_t len, bool sender_allowed, const KeyRing& keys, uint8_t kid, bool synced,
                 uint32_t now, pkr_sms_t* out);
  void note_time(uint32_t now);  // a synced clock moves the last known time on (persisted hourly)
  uint32_t last_ctr(uint8_t via) const { return last_[via]; }
  uint32_t last_known_time() const { return lkt_; }

 private:
  bool fresh(const char* id, uint32_t ctr, uint8_t via) const;
  int expiry(uint32_t exp, bool synced, uint32_t now) const;
  void accept(const char* id, uint32_t ctr, uint8_t via, bool synced, uint32_t now);
  void save();
  Kv* kv_ = nullptr;
  uint32_t last_[3] = {0, 0, 0};
  uint32_t lkt_ = 0, lkt_saved_ = 0;
  char ids_[PKR_LIMIT_RECENT_CMD_IDS][PKR_ID_MAX] = {};
  uint8_t head_ = 0;
};

// siren_model.is_verified: the amplifier current within 0.6-1.5 x its reference AND (a microphone
// rise of at least spl_rise_min_db OR a known-dead microphone). No current measured: not verified.
bool is_verified(bool has_amp, float amp_a, bool has_rise, float spl_rise_db, float amp_a_ref, float spl_rise_min_db,
                 bool mic_dead);

}  // namespace pkr
