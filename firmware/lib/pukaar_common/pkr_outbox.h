// Durable outbox (section 6.3), a device-side port of the ideas in FloodNet's
// node-red-contrib-durable-outbox (MIT): dedupe on a stable key, leased delivery that advances
// only after the broker's ack, full-jitter exponential backoff and a circuit breaker.
//
//  - Two queues: `alarm` (started, verified, manual, autonomous, rejected, tamper, ...): never
//    dropped, always sent first; `telemetry` (heartbeats and the rest): capped at 512 KB, the
//    oldest segment is dropped when full.
//  - Storage: append-only 4 KB segment files /ob/<q>/seg-XXXXXXXX; each record is
//    {magic u16, len u16, boot u32, seq u32, crc32 u32, payload}; /ob/<q>/meta holds the read
//    position {tail_seg, tail_off}, written to meta.tmp and renamed (atomic on LittleFS). The
//    write position is recovered by scanning the last segment, so an append costs one write.
//  - A record cut short by a power loss ends its segment (the next append starts a new one); a
//    complete record with a bad CRC quarantines the rest of its segment (renamed .bad).
//  - The tail advances only after PUBACK, so delivery is at-least-once; the server stores each
//    (device, boot, seq) once, which makes it effectively once.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include <map>
#include <string>
#include <vector>

#include "schema.h"

namespace pkr {

class Fs {
 public:
  virtual ~Fs() {}
  virtual bool read(const char* path, uint32_t off, void* buf, uint32_t len, uint32_t* got) = 0;
  virtual bool append(const char* path, const void* data, uint32_t len) = 0;
  virtual bool write(const char* path, const void* data, uint32_t len) = 0;  // create or truncate
  virtual int32_t size(const char* path) = 0;                                // -1 if missing
  virtual bool remove(const char* path) = 0;
  virtual bool rename(const char* from, const char* to) = 0;                 // atomic, replaces `to`
};

// RAM filesystem for the tests and the simulator, with power-loss injection: after
// `crash_after` more mutating operations the next one is cut short (append/write keep only a
// prefix) and every operation after it fails until reboot().
class MemFs : public Fs {
 public:
  bool read(const char* path, uint32_t off, void* buf, uint32_t len, uint32_t* got) override;
  bool append(const char* path, const void* data, uint32_t len) override;
  bool write(const char* path, const void* data, uint32_t len) override;
  int32_t size(const char* path) override;
  bool remove(const char* path) override;
  bool rename(const char* from, const char* to) override;
  void reboot() { crashed = false; crash_after = -1; }
  int crash_after = -1;
  bool crashed = false;
  int ops = 0;
  std::map<std::string, std::vector<uint8_t>> files;

 private:
  int allow(uint32_t len);  // bytes this op may write, -1 if the device is down
};

struct OutRecord {
  uint32_t boot = 0, seq = 0;
  std::string payload;
};

class DurableQueue {
 public:
  // cap_bytes = 0: never drop (the alarm queue)
  void begin(Fs* fs, const char* dir, uint32_t cap_bytes);
  bool append(uint32_t boot, uint32_t seq, const char* payload, uint16_t len);
  // Up to max records from the tail, oldest first. Does not consume them.
  size_t peek(OutRecord* out, size_t max);
  // Consume the first n records (after the broker acked them).
  bool ack(size_t n);
  uint32_t count() const { return count_; }
  uint32_t bytes() const { return bytes_; }
  uint32_t dropped() const { return dropped_; }
  uint32_t corrupt() const { return corrupt_; }

 private:
  struct Pos { uint32_t seg, off; };
  void seg_path(uint32_t seg, char* out, size_t cap) const;
  // reads the record header at p; 1 ok (fills len, total), 0 end of segment, -1 corrupt
  int read_at(Pos p, OutRecord* r, uint32_t* total);
  // next record from p, crossing segments; false at the end. deliver=false only counts.
  bool advance(Pos* p, OutRecord* r, bool deliver);
  bool write_meta();
  void drop_oldest_segment();
  Fs* fs_ = nullptr;
  char dir_[16] = {0};
  uint32_t cap_ = 0;
  Pos tail_{0, 0};
  uint32_t head_seg_ = 0, head_off_ = 0;
  bool head_dirty_ = false;
  uint32_t count_ = 0, bytes_ = 0, dropped_ = 0, corrupt_ = 0;
};

// Full-jitter exponential backoff: rand(0, min(cap, base * 2^(n-1))) seconds for attempt n >= 1.
uint32_t backoff_s(uint32_t attempt, uint32_t rnd);

// Circuit breaker: 3 consecutive failures open it for 60 s, then one half-open probe.
class Breaker {
 public:
  bool allow(uint32_t now_s);
  void success();
  void failure(uint32_t now_s);
  bool open() const { return state_ == 1; }

 private:
  uint8_t state_ = 0;  // 0 closed, 1 open, 2 half-open (probe in flight)
  uint8_t fails_ = 0;
  uint32_t opened_at_ = 0;
};

// Adaptive flush (after ModularSensors): the fuller the queue, the sooner the next reconnect.
uint32_t adaptive_interval_s(uint32_t base_s, uint32_t used, uint32_t cap);

class Outbox {
 public:
  void begin(Fs* fs);
  bool push(uint8_t event_type, uint32_t boot, uint32_t seq, const char* json, uint16_t len);
  // the next batch: alarm records first; *from_alarm says which queue to ack
  size_t peek(OutRecord* out, size_t max, bool* from_alarm);
  bool ack(bool from_alarm, size_t n);
  uint32_t depth() const { return alarm_.count() + telemetry_.count(); }
  DurableQueue& alarm() { return alarm_; }
  DurableQueue& telemetry() { return telemetry_; }

 private:
  DurableQueue alarm_, telemetry_;
};

}  // namespace pkr
