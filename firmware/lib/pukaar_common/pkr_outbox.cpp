#include "pkr_outbox.h"

#include <stdio.h>
#include <string.h>

#include "pkr_codec.h"
#include "pkr_crypto.h"

namespace pkr {

// ---------------------------------------------------------------- MemFs

int MemFs::allow(uint32_t len) {
  if (crashed) return -1;
  ops++;
  if (crash_after < 0) return (int)len;
  if (crash_after == 0) {
    crashed = true;
    return (int)(len / 2);  // a torn write: only a prefix reaches the flash
  }
  crash_after--;
  return (int)len;
}

bool MemFs::read(const char* path, uint32_t off, void* buf, uint32_t len, uint32_t* got) {
  *got = 0;
  if (crashed) return false;
  auto it = files.find(path);
  if (it == files.end()) return false;
  if (off >= it->second.size()) return true;
  uint32_t n = (uint32_t)it->second.size() - off;
  if (n > len) n = len;
  memcpy(buf, it->second.data() + off, n);
  *got = n;
  return true;
}

bool MemFs::append(const char* path, const void* data, uint32_t len) {
  int n = allow(len);
  if (n < 0) return false;
  auto& f = files[path];
  f.insert(f.end(), (const uint8_t*)data, (const uint8_t*)data + n);
  return !crashed;
}

bool MemFs::write(const char* path, const void* data, uint32_t len) {
  int n = allow(len);
  if (n < 0) return false;
  files[path] = std::vector<uint8_t>((const uint8_t*)data, (const uint8_t*)data + n);
  return !crashed;
}

int32_t MemFs::size(const char* path) {
  if (crashed) return -1;
  auto it = files.find(path);
  return it == files.end() ? -1 : (int32_t)it->second.size();
}

bool MemFs::remove(const char* path) {
  if (allow(0) < 0 || crashed) return false;  // the crash happens before an atomic op takes effect
  files.erase(path);
  return true;
}

bool MemFs::rename(const char* from, const char* to) {
  if (allow(0) < 0 || crashed) return false;
  auto it = files.find(from);
  if (it == files.end()) return false;
  files[to] = it->second;
  files.erase(from);
  return true;
}

// ---------------------------------------------------------------- DurableQueue

static const uint32_t SEG = PKR_OUTBOX_SEGMENT_BYTES;
static const uint32_t HDR = PKR_OUTBOX_RECORD_HEADER;

void DurableQueue::seg_path(uint32_t seg, char* out, size_t cap) const {
  snprintf(out, cap, "%s/seg-%08lx", dir_, (unsigned long)seg);
}

struct Meta {
  uint32_t magic, tail_seg, tail_off, crc;
};

bool DurableQueue::write_meta() {
  Meta m{0x4D4B5031u, tail_.seg, tail_.off, 0};
  m.crc = pkr_crc32(0, &m, 12);
  char tmp[40], path[40];
  snprintf(tmp, sizeof tmp, "%s/meta.tmp", dir_);
  snprintf(path, sizeof path, "%s/meta", dir_);
  if (!fs_->write(tmp, &m, sizeof m)) return false;
  return fs_->rename(tmp, path);
}

int DurableQueue::read_at(Pos p, OutRecord* r, uint32_t* total) {
  char path[40];
  seg_path(p.seg, path, sizeof path);
  uint8_t h[HDR];
  uint32_t got = 0;
  if (!fs_->read(path, p.off, h, HDR, &got) || got == 0) return 0;
  if (got < HDR) return 0;  // cut short by a power loss: the end of this segment
  if (pkr_get_u16(h) != PKR_OUTBOX_RECORD_MAGIC) return got ? -1 : 0;
  uint16_t len = pkr_get_u16(h + 2);
  if (len > PKR_OUTBOX_MAX_PAYLOAD) return -1;
  std::string payload(len, '\0');
  if (len && (!fs_->read(path, p.off + HDR, &payload[0], len, &got) || got < len)) return 0;  // torn
  uint32_t crc = pkr_crc32(0, h + 4, 8);
  crc = pkr_crc32(crc, payload.data(), len);
  if (crc != pkr_get_u32(h + 12)) return -1;
  if (r) {
    r->boot = pkr_get_u32(h + 4);
    r->seq = pkr_get_u32(h + 8);
    r->payload.swap(payload);
  }
  *total = HDR + len;
  return 1;
}

bool DurableQueue::advance(Pos* p, OutRecord* r, bool deliver) {
  for (;;) {
    if (p->seg > head_seg_) return false;
    if (p->seg == head_seg_ && p->off >= head_off_) return false;
    uint32_t total = 0;
    int k = read_at(*p, r, &total);
    if (k == 1) {
      p->off += total;
      return true;
    }
    if (k < 0 && deliver) {
      // a complete record with a bad CRC. Stop in front of it so the good records before it
      // can be acked; once it is the next to deliver, quarantine the rest of its segment.
      if (p->seg != tail_.seg || p->off != tail_.off) return false;
      char path[40], bad[48];
      seg_path(p->seg, path, sizeof path);
      snprintf(bad, sizeof bad, "%s.bad", path);
      fs_->rename(path, bad);
      corrupt_++;
      tail_ = {p->seg + 1, 0};
      write_meta();
      if (p->seg == head_seg_) {
        head_dirty_ = true;
        return false;
      }
      *p = tail_;
      continue;
    }
    if (p->seg == head_seg_) {
      head_dirty_ = true;  // a torn or bad record ends the head segment: never append after it
      return false;
    }
    p->seg++;  // the end of a segment (or, while counting, the rest of a bad one)
    p->off = 0;
  }
}

void DurableQueue::begin(Fs* fs, const char* dir, uint32_t cap_bytes) {
  fs_ = fs;
  strncpy(dir_, dir, sizeof dir_ - 1);
  cap_ = cap_bytes;
  tail_ = {0, 0};
  char path[40];
  snprintf(path, sizeof path, "%s/meta", dir_);
  Meta m;
  uint32_t got = 0;
  if (fs_->read(path, 0, &m, sizeof m, &got) && got == sizeof m && m.magic == 0x4D4B5031u &&
      m.crc == pkr_crc32(0, &m, 12)) {
    tail_ = {m.tail_seg, m.tail_off};
  } else {
    // no meta (first boot, or lost between remove and rename): start at the oldest segment on flash
    for (uint32_t s = 0; s < 1024; s++) {
      seg_path(s, path, sizeof path);
      if (fs_->size(path) >= 0) {
        tail_ = {s, 0};
        break;
      }
    }
  }
  // segments below the tail are already delivered (a reset between meta and remove leaves them)
  for (uint32_t s = tail_.seg; s > 0;) {
    s--;
    seg_path(s, path, sizeof path);
    if (fs_->size(path) < 0) break;
    fs_->remove(path);
  }
  // the head is the last segment that exists
  head_seg_ = tail_.seg;
  for (;;) {
    seg_path(head_seg_ + 1, path, sizeof path);
    if (fs_->size(path) < 0) break;
    head_seg_++;
  }
  seg_path(head_seg_, path, sizeof path);
  int32_t sz = fs_->size(path);
  head_off_ = sz < 0 ? 0 : (uint32_t)sz;
  head_dirty_ = false;
  // count what is pending, and find where the valid data in the head segment ends
  count_ = bytes_ = 0;
  Pos p = tail_;
  OutRecord r;
  uint32_t real_head_off = (tail_.seg == head_seg_) ? tail_.off : 0;
  while (advance(&p, &r, false)) {
    count_++;
    bytes_ += HDR + (uint32_t)r.payload.size();
    if (p.seg == head_seg_) real_head_off = p.off;
  }
  if (real_head_off != head_off_) head_dirty_ = true;  // a torn record at the end
  head_off_ = real_head_off;
}

bool DurableQueue::append(uint32_t boot, uint32_t seq, const char* payload, uint16_t len) {
  if (len > PKR_OUTBOX_MAX_PAYLOAD) return false;
  uint32_t total = HDR + len;
  if (head_dirty_ || (head_off_ && head_off_ + total > SEG)) {
    head_seg_++;
    head_off_ = 0;
    head_dirty_ = false;
  }
  std::vector<uint8_t> rec(total);
  pkr_put_u16(&rec[0], PKR_OUTBOX_RECORD_MAGIC);
  pkr_put_u16(&rec[2], len);
  pkr_put_u32(&rec[4], boot);
  pkr_put_u32(&rec[8], seq);
  memcpy(&rec[HDR], payload, len);
  uint32_t crc = pkr_crc32(0, &rec[4], 8);
  crc = pkr_crc32(crc, payload, len);
  pkr_put_u32(&rec[12], crc);
  char path[40];
  seg_path(head_seg_, path, sizeof path);
  if (!fs_->append(path, rec.data(), total)) {
    head_dirty_ = true;  // whatever reached the flash is garbage now
    return false;
  }
  head_off_ += total;
  count_++;
  bytes_ += total;
  while (cap_ && bytes_ > cap_ && tail_.seg < head_seg_) drop_oldest_segment();
  return true;
}

void DurableQueue::drop_oldest_segment() {
  Pos p = tail_;
  OutRecord r;
  uint32_t n = 0, b = 0;
  while (p.seg == tail_.seg && advance(&p, &r, false)) {
    if (p.seg != tail_.seg) break;
    n++;
    b += HDR + (uint32_t)r.payload.size();
  }
  uint32_t old = tail_.seg;
  tail_ = {old + 1, 0};
  if (!write_meta()) return;
  char path[40];
  seg_path(old, path, sizeof path);
  fs_->remove(path);
  count_ -= n;
  bytes_ -= b;
  dropped_ += n;
}

size_t DurableQueue::peek(OutRecord* out, size_t max) {
  Pos p = tail_;
  size_t n = 0;
  while (n < max && advance(&p, &out[n], true)) n++;
  return n;
}

bool DurableQueue::ack(size_t n) {
  Pos p = tail_;
  OutRecord r;
  uint32_t b = 0;
  size_t k = 0;
  while (k < n && advance(&p, &r, true)) {
    k++;
    b += HDR + (uint32_t)r.payload.size();
  }
  uint32_t old = tail_.seg;
  Pos before = tail_;
  tail_ = p;
  if (!write_meta()) {
    tail_ = before;
    return false;
  }
  for (uint32_t s = old; s < tail_.seg; s++) {  // fully delivered segments
    char path[40];
    seg_path(s, path, sizeof path);
    fs_->remove(path);
  }
  count_ = count_ >= k ? count_ - (uint32_t)k : 0;
  bytes_ = bytes_ >= b ? bytes_ - b : 0;
  return true;
}

// ---------------------------------------------------------------- retry policy

uint32_t backoff_s(uint32_t attempt, uint32_t rnd) {
  if (attempt == 0) return 0;
  uint64_t ceiling = (uint64_t)PKR_OUTBOX_BACKOFF_BASE_S << (attempt - 1 > 20 ? 20 : attempt - 1);
  if (ceiling > PKR_OUTBOX_BACKOFF_CAP_S) ceiling = PKR_OUTBOX_BACKOFF_CAP_S;
  return (uint32_t)(rnd % (ceiling + 1));
}

bool Breaker::allow(uint32_t now_s) {
  if (state_ == 0) return true;
  if (state_ == 1 && now_s - opened_at_ >= PKR_OUTBOX_BREAKER_OPEN_S) {
    state_ = 2;  // one probe
    return true;
  }
  return false;
}

void Breaker::success() {
  state_ = 0;
  fails_ = 0;
}

void Breaker::failure(uint32_t now_s) {
  if (state_ == 2 || ++fails_ >= PKR_OUTBOX_BREAKER_FAILURES) {
    state_ = 1;
    opened_at_ = now_s;
    fails_ = 0;
  }
}

uint32_t adaptive_interval_s(uint32_t base_s, uint32_t used, uint32_t cap) {
  if (!cap) return base_s;
  uint64_t pct = (uint64_t)used * 100u / cap;
  if (pct > 90) return base_s / 8 ? base_s / 8 : 1;
  if (pct > 75) return base_s / 4 ? base_s / 4 : 1;
  if (pct > 50) return base_s / 2 ? base_s / 2 : 1;
  return base_s;
}

// ---------------------------------------------------------------- Outbox

void Outbox::begin(Fs* fs) {
  alarm_.begin(fs, "/ob/a", 0);
  telemetry_.begin(fs, "/ob/t", PKR_OUTBOX_TELEMETRY_CAP_BYTES);
}

bool Outbox::push(uint8_t event_type, uint32_t boot, uint32_t seq, const char* json, uint16_t len) {
  return pkr_event_is_alarm(event_type) ? alarm_.append(boot, seq, json, len) : telemetry_.append(boot, seq, json, len);
}

size_t Outbox::peek(OutRecord* out, size_t max, bool* from_alarm) {
  size_t n = alarm_.peek(out, max);
  *from_alarm = n > 0;
  if (n) return n;
  return telemetry_.peek(out, max);
}

bool Outbox::ack(bool from_alarm, size_t n) { return from_alarm ? alarm_.ack(n) : telemetry_.ack(n); }

}  // namespace pkr
