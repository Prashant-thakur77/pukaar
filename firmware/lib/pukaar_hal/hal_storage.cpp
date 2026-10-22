// NVS, LittleFS, the clock and the provisioned keys. UNTESTED ON HARDWARE.
#include <LittleFS.h>
#include <Preferences.h>
#include <sys/time.h>
#include <time.h>

#include "pukaar_hal.h"

namespace pkr {

bool NvsKv::begin(const char* ns) {
  strncpy(ns_, ns, sizeof ns_ - 1);
  Preferences p;
  bool ok = p.begin(ns_, false);
  p.end();
  return ok;
}

bool NvsKv::get_u32(const char* key, uint32_t* out) {
  Preferences p;
  if (!p.begin(ns_, true)) return false;
  bool has = p.isKey(key);
  if (has) *out = p.getUInt(key, 0);
  p.end();
  return has;
}

bool NvsKv::put_u32(const char* key, uint32_t v) {
  Preferences p;
  if (!p.begin(ns_, false)) return false;
  bool ok = p.putUInt(key, v) == sizeof v;
  p.end();
  return ok;
}

size_t NvsKv::get_blob(const char* key, void* buf, size_t cap) {
  Preferences p;
  if (!p.begin(ns_, true)) return 0;
  size_t n = p.isKey(key) ? p.getBytesLength(key) : 0;
  if (n && n <= cap) n = p.getBytes(key, buf, cap);
  else n = 0;
  p.end();
  return n;
}

bool NvsKv::put_blob(const char* key, const void* data, size_t len) {
  Preferences p;
  if (!p.begin(ns_, false)) return false;
  bool ok = p.putBytes(key, data, len) == len;
  p.end();
  return ok;
}

uint32_t next_boot_number(Kv& kv) {
  uint32_t b = 0;
  kv.get_u32("boot", &b);
  kv.put_u32("boot", ++b);
  return b;
}

bool LittleFsFs::begin() {
  if (!LittleFS.begin(true)) return false;
  LittleFS.mkdir("/ob");
  LittleFS.mkdir("/ob/a");
  LittleFS.mkdir("/ob/t");
  return true;
}

bool LittleFsFs::read(const char* path, uint32_t off, void* buf, uint32_t len, uint32_t* got) {
  *got = 0;
  File f = LittleFS.open(path, "r");
  if (!f) return false;
  if (off >= f.size()) {
    f.close();
    return true;
  }
  f.seek(off);
  *got = (uint32_t)f.read((uint8_t*)buf, len);
  f.close();
  return true;
}

bool LittleFsFs::append(const char* path, const void* data, uint32_t len) {
  File f = LittleFS.open(path, "a");
  if (!f) return false;
  size_t n = f.write((const uint8_t*)data, len);
  f.close();  // LittleFS commits on close: a power loss before it leaves the old file intact
  return n == len;
}

bool LittleFsFs::write(const char* path, const void* data, uint32_t len) {
  File f = LittleFS.open(path, "w");
  if (!f) return false;
  size_t n = f.write((const uint8_t*)data, len);
  f.close();
  return n == len;
}

int32_t LittleFsFs::size(const char* path) {
  if (!LittleFS.exists(path)) return -1;
  File f = LittleFS.open(path, "r");
  if (!f) return -1;
  int32_t n = (int32_t)f.size();
  f.close();
  return n;
}

bool LittleFsFs::remove(const char* path) { return LittleFS.remove(path); }

bool LittleFsFs::rename(const char* from, const char* to) {
  // lfs_rename replaces `to` atomically. If the VFS layer refuses an existing target, the
  // fallback removes it first; a power loss in that gap leaves no meta, and the outbox then
  // starts from the oldest segment still on flash (DurableQueue::begin): records are re-sent,
  // never lost (at-least-once; the server stores each (device, boot, seq) once).
  if (LittleFS.rename(from, to)) return true;
  LittleFS.remove(to);
  return LittleFS.rename(from, to);
}

bool load_provisioned_keys(KeyRing& keys, char* device_out, size_t cap) {
  Preferences p;
  if (!p.begin("pkr-keys", true)) return false;
  String dev = p.getString("dev", "");
  uint16_t addr = (uint16_t)p.getUInt("addr", 0);
  uint8_t kid = (uint8_t)p.getUInt("kid", 1);
  strncpy(device_out, dev.c_str(), cap - 1);
  keys.set_identity(dev.c_str(), addr);
  keys.set_current_kid(kid);
  bool any = false;
  for (uint8_t k = 1; k <= 4; k++) {
    char name[8];
    snprintf(name, sizeof name, "self%u", k);
    uint8_t key[32];
    if (p.isKey(name) && p.getBytes(name, key, sizeof key) == sizeof key) {
      keys.set_self_key(k, key);
      any = true;
    }
    memset(key, 0, sizeof key);
  }
  for (uint8_t i = 0; i < 16; i++) {
    char name[8];
    snprintf(name, sizeof name, "snd%u", i);
    ProvisionedSender ps;
    if (!p.isKey(name) || p.getBytes(name, &ps, sizeof ps) != sizeof ps) continue;
    Sender s;
    s.addr = ps.addr;
    s.kid = ps.kid;
    s.roles = ps.roles;
    strncpy(s.device, ps.device, sizeof s.device - 1);
    memcpy(s.key, ps.key, 32);
    keys.add_sender(s);
  }
  p.end();
  return any && dev.length() > 0;
}

uint32_t EspClock::unix_s() { return (uint32_t)time(nullptr); }

bool EspClock::synced() {
  // a sync in the last 48 h: the RTC drifts a few seconds a day, well inside every window we check
  return ever_ && time(nullptr) > 1700000000 && millis() - synced_at_ms_ < 48u * 3600u * 1000u;
}

void EspClock::set(uint32_t unix_now) {
  struct timeval tv = {(time_t)unix_now, 0};
  settimeofday(&tv, nullptr);
  ever_ = true;
  synced_at_ms_ = millis();
}

bool EspClock::sync_ntp(uint32_t wait_ms) {
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  uint32_t t0 = millis();
  while (millis() - t0 < wait_ms) {
    if (time(nullptr) > 1700000000) {
      ever_ = true;
      synced_at_ms_ = millis();
      return true;
    }
    delay(100);
  }
  return false;
}

}  // namespace pkr
