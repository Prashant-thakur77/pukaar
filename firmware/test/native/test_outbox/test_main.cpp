// The durable outbox: ordering, the alarm queue first, the telemetry cap, surviving a reboot,
// power loss at every single write step (no loss, no duplicate), corruption, and the retry policy.
#include <stdio.h>
#include <string.h>
#include <unity.h>

#include <set>
#include <string>
#include <vector>

#include "pkr_box.h"
#include "pkr_outbox.h"

void setUp() {}
void tearDown() {}

using namespace pkr;

static std::string body(uint32_t seq, size_t pad = 40) {
  char b[64];
  snprintf(b, sizeof b, "{\"seq\":%u,\"pad\":\"", (unsigned)seq);
  return std::string(b) + std::string(pad, 'x') + "\"}";
}

static std::vector<uint32_t> drain(DurableQueue& q, size_t batch = 7) {
  std::vector<uint32_t> seqs;
  OutRecord r[30];
  for (;;) {
    size_t n = q.peek(r, batch);
    if (!n) break;
    for (size_t i = 0; i < n; i++) seqs.push_back(r[i].seq);
    TEST_ASSERT_TRUE(q.ack(n));
  }
  return seqs;
}

static void test_fifo_peek_ack_and_segments() {
  MemFs fs;
  DurableQueue q;
  q.begin(&fs, "/ob/a", 0);
  for (uint32_t i = 1; i <= 200; i++) {
    std::string b = body(i);
    TEST_ASSERT_TRUE(q.append(1, i, b.data(), (uint16_t)b.size()));
  }
  TEST_ASSERT_EQUAL_UINT32(200, q.count());
  int segs = 0;
  for (auto& f : fs.files) segs += f.first.find("/ob/a/seg-") == 0;
  TEST_ASSERT_GREATER_THAN(2, segs);  // 4 KB segments
  for (auto& f : fs.files) TEST_ASSERT_LESS_OR_EQUAL(PKR_OUTBOX_SEGMENT_BYTES, (int)f.second.size());
  OutRecord r[30];
  TEST_ASSERT_EQUAL_UINT(30, q.peek(r, 30));
  TEST_ASSERT_EQUAL_UINT32(1, r[0].seq);
  TEST_ASSERT_EQUAL_STRING(body(1).c_str(), r[0].payload.c_str());
  TEST_ASSERT_EQUAL_UINT(30, q.peek(r, 30));  // peek does not consume
  TEST_ASSERT_TRUE(q.ack(30));
  TEST_ASSERT_EQUAL_UINT(1, q.peek(r, 1));
  TEST_ASSERT_EQUAL_UINT32(31, r[0].seq);
  auto rest = drain(q);
  TEST_ASSERT_EQUAL_UINT(170, rest.size());
  TEST_ASSERT_EQUAL_UINT32(200, rest.back());
  TEST_ASSERT_EQUAL_UINT32(0, q.count());
  segs = 0;
  for (auto& f : fs.files) segs += f.first.find("/ob/a/seg-") == 0;
  TEST_ASSERT_LESS_OR_EQUAL(1, segs);  // delivered segments are removed
}

static void test_survives_reboot() {
  MemFs fs;
  {
    Outbox ob;
    ob.begin(&fs);
    for (uint32_t i = 1; i <= 50; i++) {
      std::string b = body(i);
      ob.push(i % 5 ? PKR_EVT_HEARTBEAT : PKR_EVT_STARTED, 3, i, b.data(), (uint16_t)b.size());
    }
    OutRecord r[30];
    bool alarm;
    size_t n = ob.peek(r, 4, &alarm);
    TEST_ASSERT_TRUE(alarm);  // alarm events go first
    TEST_ASSERT_EQUAL_UINT32(5, r[0].seq);
    TEST_ASSERT_TRUE(ob.ack(alarm, n));
  }  // reboot
  Outbox ob;
  ob.begin(&fs);
  TEST_ASSERT_EQUAL_UINT32(6, ob.alarm().count());
  TEST_ASSERT_EQUAL_UINT32(40, ob.telemetry().count());
  auto a = drain(ob.alarm());
  TEST_ASSERT_EQUAL_UINT(6, a.size());
  TEST_ASSERT_EQUAL_UINT32(25, a[0]);
  auto t = drain(ob.telemetry());
  TEST_ASSERT_EQUAL_UINT(40, t.size());
  TEST_ASSERT_EQUAL_UINT32(1, t[0]);
}

static void test_telemetry_cap_drops_oldest_alarm_never() {
  MemFs fs;
  DurableQueue tq, aq;
  tq.begin(&fs, "/ob/t", 20000);  // a small cap for the test
  aq.begin(&fs, "/ob/a", 0);
  std::string b = body(0, 300);
  for (uint32_t i = 1; i <= 300; i++) {
    TEST_ASSERT_TRUE(tq.append(1, i, b.data(), (uint16_t)b.size()));
    TEST_ASSERT_TRUE(aq.append(1, i, b.data(), (uint16_t)b.size()));
  }
  TEST_ASSERT_LESS_OR_EQUAL_UINT32(20000, tq.bytes());
  TEST_ASSERT_GREATER_THAN_UINT32(0, tq.dropped());
  auto t = drain(tq);
  TEST_ASSERT_EQUAL_UINT32(300, t.back());           // the newest survive
  TEST_ASSERT_EQUAL_UINT32(300 - t.size() + 1, t[0]); // a contiguous tail, oldest dropped
  TEST_ASSERT_EQUAL_UINT32(0, aq.dropped());
  TEST_ASSERT_EQUAL_UINT(300, drain(aq).size());      // the alarm queue keeps everything
}

// Power loss at every mutating step of a scripted run of appends and acks: after the reboot every
// record whose append returned true is either delivered before the loss or still queued; what
// is queued is in order with no duplicate seq; at most the one in-flight ack batch is sent twice.
static void test_power_loss_at_every_write_step() {
  // count the steps of a clean run first
  int total_ops;
  {
    MemFs fs;
    DurableQueue q;
    q.begin(&fs, "/ob/a", 0);
    for (uint32_t i = 1; i <= 60; i++) {
      std::string b = body(i, 100);
      q.append(1, i, b.data(), (uint16_t)b.size());
      if (i % 7 == 0) {
        OutRecord r[5];
        q.ack(q.peek(r, 5));
      }
    }
    total_ops = fs.ops;
  }
  TEST_ASSERT_GREATER_THAN(60, total_ops);
  for (int crash = 0; crash <= total_ops; crash++) {
    MemFs fs;
    fs.crash_after = crash;
    std::set<uint32_t> appended, delivered;
    std::vector<uint32_t> last_batch;
    {
      DurableQueue q;
      q.begin(&fs, "/ob/a", 0);
      for (uint32_t i = 1; i <= 60 && !fs.crashed; i++) {
        std::string b = body(i, 100);
        if (q.append(1, i, b.data(), (uint16_t)b.size())) appended.insert(i);
        if (i % 7 == 0 && !fs.crashed) {
          OutRecord r[5];
          size_t n = q.peek(r, 5);
          last_batch.clear();
          for (size_t k = 0; k < n; k++) last_batch.push_back(r[k].seq);
          if (q.ack(n))  // PUBACK received and the tail moved: delivered for good
            for (auto s : last_batch) delivered.insert(s);
        }
      }
    }
    fs.reboot();
    DurableQueue q;
    q.begin(&fs, "/ob/a", 0);
    auto after = drain(q);
    std::set<uint32_t> seen(after.begin(), after.end());
    char msg[64];
    snprintf(msg, sizeof msg, "power lost at step %d", crash);
    TEST_ASSERT_EQUAL_UINT_MESSAGE(after.size(), seen.size(), msg);  // no duplicate seq
    for (size_t i = 1; i < after.size(); i++) TEST_ASSERT_TRUE_MESSAGE(after[i - 1] < after[i], msg);  // in order
    for (auto s : appended) TEST_ASSERT_TRUE_MESSAGE(delivered.count(s) || seen.count(s), msg);       // no loss
    int twice = 0;
    for (auto s : after) twice += delivered.count(s) ? 1 : 0;
    TEST_ASSERT_EQUAL_INT_MESSAGE(0, twice, msg);  // an ack that returned true is never undone
    for (auto s : after) TEST_ASSERT_TRUE_MESSAGE(appended.count(s), msg);  // a torn append never resurfaces
    // and the queue still works after the reboot
    std::string b = body(1000);
    TEST_ASSERT_TRUE_MESSAGE(q.append(2, 1, b.data(), (uint16_t)b.size()), msg);
    OutRecord r[1];
    TEST_ASSERT_EQUAL_UINT_MESSAGE(1, q.peek(r, 1), msg);
    TEST_ASSERT_EQUAL_UINT32_MESSAGE(2, r[0].boot, msg);
  }
}

static void test_bad_crc_quarantines_segment() {
  MemFs fs;
  DurableQueue q;
  q.begin(&fs, "/ob/a", 0);
  for (uint32_t i = 1; i <= 60; i++) {
    std::string b = body(i, 100);
    q.append(1, i, b.data(), (uint16_t)b.size());
  }
  // flip a payload byte in the second record of the first segment (flash corruption)
  auto& seg = fs.files["/ob/a/seg-00000000"];
  size_t rec = PKR_OUTBOX_RECORD_HEADER + body(1, 100).size();
  seg[rec + PKR_OUTBOX_RECORD_HEADER + 3] ^= 0x20;
  DurableQueue q2;
  q2.begin(&fs, "/ob/a", 0);
  auto got = drain(q2);
  TEST_ASSERT_EQUAL_UINT32(1, got[0]);
  TEST_ASSERT_GREATER_THAN_UINT32(2, got[1]);  // the rest of the bad segment is skipped
  TEST_ASSERT_EQUAL_UINT32(60, got.back());
  TEST_ASSERT_EQUAL_UINT32(1, q2.corrupt());
  bool quarantined = false;
  for (auto& f : fs.files) quarantined |= f.first.find(".bad") != std::string::npos;
  TEST_ASSERT_TRUE(quarantined);
}

static void test_backoff_breaker_adaptive() {
  for (uint32_t n = 1; n <= 12; n++) {
    uint32_t ceiling = 2u << (n - 1);
    if (ceiling > 300) ceiling = 300;
    TEST_ASSERT_EQUAL_UINT32(0, backoff_s(n, 0));
    TEST_ASSERT_EQUAL_UINT32(ceiling, backoff_s(n, ceiling));  // full jitter: 0 .. ceiling
    for (uint32_t r = 0; r < 2000; r += 37) TEST_ASSERT_LESS_OR_EQUAL_UINT32(ceiling, backoff_s(n, r));
  }
  TEST_ASSERT_LESS_OR_EQUAL_UINT32(300, backoff_s(40, 0xFFFFFFFFu));
  Breaker b;
  TEST_ASSERT_TRUE(b.allow(0));
  b.failure(0);
  b.failure(1);
  TEST_ASSERT_TRUE(b.allow(2));
  b.failure(2);  // third in a row: open
  TEST_ASSERT_TRUE(b.open());
  TEST_ASSERT_FALSE(b.allow(30));
  TEST_ASSERT_TRUE(b.allow(62));   // half-open: one probe
  TEST_ASSERT_FALSE(b.allow(63));  // only one
  b.failure(63);                   // the probe failed: open again
  TEST_ASSERT_FALSE(b.allow(100));
  TEST_ASSERT_TRUE(b.allow(124));
  b.success();
  TEST_ASSERT_TRUE(b.allow(125));
  TEST_ASSERT_FALSE(b.open());
  TEST_ASSERT_EQUAL_UINT32(300, adaptive_interval_s(300, 10, 100));
  TEST_ASSERT_EQUAL_UINT32(150, adaptive_interval_s(300, 51, 100));
  TEST_ASSERT_EQUAL_UINT32(75, adaptive_interval_s(300, 76, 100));
  TEST_ASSERT_EQUAL_UINT32(37, adaptive_interval_s(300, 91, 100));
}

static void test_event_log_and_backfill_body() {
  MemFs fs;
  Outbox ob;
  ob.begin(&fs);
  EventLog log;
  log.begin(&ob, 12);
  Event e;
  e.type = PKR_EVT_STARTED;
  e.at = 1761121865;
  strcpy(e.cmd_id, "01JB");
  e.pattern = PKR_PATTERN_W1;
  e.via = PKR_VIA_MQTT;
  e.src = PKR_SRC_APPROVAL;
  log.emit(e);
  e.type = PKR_EVT_HEARTBEAT;
  log.emit(e);
  TEST_ASSERT_EQUAL_UINT32(1, ob.alarm().count());
  TEST_ASSERT_EQUAL_UINT32(1, ob.telemetry().count());
  OutRecord r[30];
  bool alarm;
  size_t n = ob.peek(r, 30, &alarm);
  TEST_ASSERT_EQUAL_UINT32(12, r[0].boot);
  TEST_ASSERT_EQUAL_UINT32(1, r[0].seq);
  char out[600];
  size_t len = build_backfill(r, n, out, sizeof out);
  TEST_ASSERT_GREATER_THAN(0, len);
  TEST_ASSERT_EQUAL_STRING(
      "{\"events\":[{\"v\":1,\"seq\":1,\"boot\":12,\"at\":\"2025-10-22T08:31:05Z\",\"type\":\"started\",\"cmd_id\":\"01JB\","
      "\"pattern\":\"W1\",\"via\":\"mqtt\",\"src\":\"approval\"}]}",
      out);
  TEST_ASSERT_EQUAL_UINT(0, build_backfill(r, n, out, 20));  // too small: refused, not truncated
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_fifo_peek_ack_and_segments);
  RUN_TEST(test_survives_reboot);
  RUN_TEST(test_telemetry_cap_drops_oldest_alarm_never);
  RUN_TEST(test_power_loss_at_every_write_step);
  RUN_TEST(test_bad_crc_quarantines_segment);
  RUN_TEST(test_backoff_breaker_adaptive);
  RUN_TEST(test_event_log_and_backfill_body);
  return UNITY_END();
}
