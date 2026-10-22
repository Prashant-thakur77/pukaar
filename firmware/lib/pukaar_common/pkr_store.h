// Small persistent state behind a key-value interface (NVS on the device, a map in the tests):
// counters that survive reboots, the command replay guard, and the key ring.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include <map>
#include <string>
#include <vector>

#include "pkr_command.h"
#include "schema.h"

namespace pkr {

class Kv {
 public:
  virtual ~Kv() {}
  virtual bool get_u32(const char* key, uint32_t* out) = 0;
  virtual bool put_u32(const char* key, uint32_t v) = 0;
  virtual size_t get_blob(const char* key, void* buf, size_t cap) = 0;  // 0 if missing
  virtual bool put_blob(const char* key, const void* data, size_t len) = 0;
};

// RAM-backed Kv for tests and the simulator. `writes` counts flash writes (NVS wear).
class MemKv : public Kv {
 public:
  bool get_u32(const char* key, uint32_t* out) override;
  bool put_u32(const char* key, uint32_t v) override;
  size_t get_blob(const char* key, void* buf, size_t cap) override;
  bool put_blob(const char* key, const void* data, size_t len) override;
  int writes = 0;
  std::map<std::string, std::vector<uint8_t>> data;
};

// A frame counter in NVS, in one of two modes (siren_model.py):
//
// SEND (load_send, next): this device's own outgoing ctr. Written lazily, at most once every
// PKR_LIMIT_CTR_PERSIST_EVERY steps plus flush() at the power-down warning, so on boot
// PKR_LIMIT_CTR_BOOT_SKIP (16) is added to the stored value (and written back): a counter is never
// reused after an unclean shutdown.
//
// RECEIVE (load_receive, observe): the last ctr accepted from one sender. Written through to NVS
// when a frame is accepted, before anything acts on it, and restored EXACTLY on boot, with no
// bump. A bump would make a siren that rebooted (floods cut power) refuse its gauge's next
// GAUGE_ALARM frames, exactly when edge autonomy matters. The one gap: power lost after the
// accept but before the NVS write can let that one frame be accepted a second time, which the
// frame's 900 s time window bounds (and a re-heard GAUGE_ALARM only re-arms an alarm that is
// already sounding). NVS wear: one small entry per accepted frame; the NVS log spreads it over
// the partition's pages.
class LazyCounter {
 public:
  void load_send(Kv* kv, const char* key);
  void load_receive(Kv* kv, const char* key);
  uint32_t value() const { return v_; }
  uint32_t next();
  void observe(uint32_t v);
  void flush();

 private:
  void maybe_persist();
  Kv* kv_ = nullptr;
  char key_[16] = {0};
  uint32_t v_ = 0, persisted_ = 0;
  bool write_through_ = false;
};

// Role bits a sender may hold (config.senders[].roles), one per frame type, named as in
// siren_model.ROLE_FOR_TYPE. A frame type nobody may send (unknown) needs role 0: always refused.
enum : uint8_t {
  ROLE_GAUGE_STATUS = 1,  // "gauge_status"  GAUGE_STATUS
  ROLE_GAUGE_ALARM = 2,   // "gauge_alarm"   GAUGE_ALARM
  ROLE_RELAY_CMD = 4,     // "relay_cmd"     SIREN_CMD_WRAPPED (the outer MAC: a forwarder)
  ROLE_SIREN_EVENT = 8,   // "siren_event"   SIREN_EVENT
  ROLE_BUTTON = 16,       // "button"        BUTTON
  ROLE_HEARTBEAT = 32,    // "heartbeat"     HEARTBEAT
  ROLE_BEACON = 64,       // "beacon"        RELAY_BEACON
  ROLE_ACK = 128,         // "ack"           ACK
};
uint8_t role_for_frame_type(uint8_t type);  // 0 for an unknown type
uint8_t roles_from_names(const char* const* names, size_t n);

struct Sender {
  uint16_t addr = 0;
  char device[PKR_DEVICE_MAX] = {0};
  uint8_t kid = 0;
  uint8_t roles = 0;
  uint8_t key[32] = {0};
};

// This device's own keys (by kid) and the senders it trusts. Keys are flashed at provisioning or
// delivered by a Job over TLS; they never travel in a shadow.
class KeyRing {
 public:
  void set_identity(const char* device, uint16_t lora_addr);
  bool set_self_key(uint8_t kid, const uint8_t key[32]);
  const uint8_t* self_key(uint8_t kid) const;
  void set_current_kid(uint8_t kid) { current_kid_ = kid; }
  uint8_t current_kid() const { return current_kid_; }
  bool has_self_key() const { return n_self_ > 0; }
  bool add_sender(const Sender& s);
  const Sender* sender(uint16_t addr) const;
  const Sender* sender_by_name(const char* device) const;
  const char* device() const { return device_; }
  uint16_t addr() const { return addr_; }

 private:
  char device_[PKR_DEVICE_MAX] = {0};
  uint16_t addr_ = 0;
  struct SelfKey { uint8_t kid; uint8_t key[32]; } self_[4] = {};
  uint8_t n_self_ = 0;
  uint8_t current_kid_ = 1;
  Sender senders_[16];
  uint8_t n_senders_ = 0;
};

}  // namespace pkr
