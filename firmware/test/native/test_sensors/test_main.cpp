// Gauge v3 logic (2-of-3 with NaN, blind zone, sanity, bridge beacon, burst), the tipping-bucket
// counter (debounce, bounce, counter wrap, rates), the duty-cycle governor, and the peripheral
// codecs (SEN0676 Modbus, DFPlayer, E22).
#include <math.h>
#include <unity.h>

#include <utility>
#include <vector>

#include "pkr_dutycycle.h"
#include "pkr_frame.h"
#include "pkr_gauge.h"
#include "pkr_rain.h"
#include "pkr_wire.h"
#include "schema.h"

void setUp() {}
void tearDown() {}

// ---------------------------------------------------------------- 2 of 3

static void test_two_of_three_with_nan() {
  float a[3] = {NAN, 310, 305};
  TEST_ASSERT_TRUE(pkr_two_of_three(a, 300));
  float b[3] = {310, NAN, NAN};
  TEST_ASSERT_FALSE(pkr_two_of_three(b, 300));
  float c[3] = {299.9f, 300, NAN};
  TEST_ASSERT_FALSE(pkr_two_of_three(c, 300));
  float d[3] = {NAN, NAN, NAN};
  TEST_ASSERT_FALSE(pkr_two_of_three(d, 0));
  float e[3] = {1, 2, 3};
  TEST_ASSERT_EQUAL_INT(3, pkr_count_at_or_above(e, 1));
  float f[3] = {300, 301, 302};
  TEST_ASSERT_TRUE(pkr_all_three(f, 300, 1));
  float g[3] = {300, NAN, 302};
  TEST_ASSERT_FALSE(pkr_all_three(g, 300, 1));  // NaN never agrees
  float h[3] = {270, 271, 272};
  TEST_ASSERT_TRUE(pkr_all_three(h, 280, 0));
}

static pkr_gauge_cfg_t cfg() { return pkr_gauge_cfg_t{150, 250, 300, 300, 280, 150, 40000, 10, 2}; }

static pkr_gauge_decision_t step(pkr_gauge_state_t* s, float stage, uint32_t now, uint16_t dist = 2000, int blind = 0,
                                 int good = 1, uint16_t tips = 0) {
  pkr_gauge_cfg_t c = cfg();
  pkr_gauge_reading_t r{stage, dist, (uint8_t)blind, (uint8_t)good, now, tips};
  pkr_gauge_decision_t d;
  pkr_gauge_step(s, &c, &r, &d);
  return d;
}

static void test_gauge_alarm_needs_two_of_three_and_sanity() {
  pkr_gauge_state_t s;
  pkr_gauge_state_init(&s);
  uint32_t t = 1761121800;
  // straight after a reboot there is no normal reading yet: critical readings never alarm
  step(&s, 320, t);
  pkr_gauge_decision_t d = step(&s, 330, t + 60);
  TEST_ASSERT_TRUE(d.crit);
  TEST_ASSERT_FALSE(d.sane);
  TEST_ASSERT_FALSE(d.send_alarm);
  // a normal reading, then two critical ones
  pkr_gauge_state_init(&s);
  step(&s, 100, t);
  d = step(&s, 305, t + 300);
  TEST_ASSERT_FALSE(d.send_alarm);  // one of three
  TEST_ASSERT_EQUAL_INT(PKR_LEVEL_NORMAL, d.level);
  d = step(&s, NAN, t + 360, 0, 0, 0);  // a bad reading in between
  TEST_ASSERT_FALSE(d.send_alarm);
  d = step(&s, 310, t + 420);
  TEST_ASSERT_TRUE(d.send_alarm);  // 305, NaN, 310: two of three
  TEST_ASSERT_EQUAL_INT(PKR_LEVEL_CRITICAL, d.level);
  // the normal reading is more than 24 h old: not sane any more
  d = step(&s, 315, t + 86400 + 400);
  TEST_ASSERT_TRUE(d.crit);
  TEST_ASSERT_FALSE(d.send_alarm);
}

static void test_blind_zone_never_alarms() {
  pkr_gauge_state_t s;
  pkr_gauge_state_init(&s);
  uint32_t t = 1761121800;
  step(&s, 100, t);
  // a blocked face reads as the shortest distance, which is the highest "stage"
  for (int i = 1; i <= 6; i++) {
    pkr_gauge_decision_t d = step(&s, 410, t + 60u * i, 160, 1);
    TEST_ASSERT_FALSE(d.send_alarm);
    TEST_ASSERT_FALSE(d.crit);
  }
  // within 50 mm of the blind zone is not good either
  pkr_gauge_decision_t d = step(&s, 400, t + 600, 190, 0);
  d = step(&s, 400, t + 660, 199, 0);
  TEST_ASSERT_FALSE(d.crit);
  TEST_ASSERT_TRUE(isnan(s.recent[2]));
  // and 2 of the last 3 bursts touching the blind zone make the gauge not sane, even with good stages
  pkr_gauge_state_init(&s);
  step(&s, 100, t);
  step(&s, 305, t + 60, 2000, 1);
  step(&s, 306, t + 120, 2000, 0);
  d = step(&s, 307, t + 180, 2000, 1);
  TEST_ASSERT_FALSE(d.sane);
  TEST_ASSERT_FALSE(d.send_alarm);
}

static void test_bridge_beacon_latch_and_burst() {
  pkr_gauge_state_t s;
  pkr_gauge_state_init(&s);
  uint32_t t = 1761121800;
  step(&s, 100, t);
  step(&s, 301, t + 60);
  pkr_gauge_decision_t d = step(&s, 302, t + 120);
  TEST_ASSERT_FALSE(d.beacon);  // 100, 301, 302: not 3 of 3
  d = step(&s, 303, t + 180);
  TEST_ASSERT_TRUE(d.beacon);
  d = step(&s, 270, t + 240);
  TEST_ASSERT_TRUE(d.beacon);  // latched until 3 of 3 clear
  step(&s, 270, t + 300);
  d = step(&s, 270, t + 360);
  TEST_ASSERT_FALSE(d.beacon);
  // burst: a 10 cm rise over three readings, or rain at 2 tips a minute
  pkr_gauge_state_init(&s);
  step(&s, 100, t);
  step(&s, 104, t + 300);
  d = step(&s, 111, t + 600);
  TEST_ASSERT_TRUE(d.burst);
  TEST_ASSERT_EQUAL_INT16(11, d.rise_cm);
  pkr_gauge_state_init(&s);
  d = step(&s, 100, t, 2000, 0, 1, 2);
  TEST_ASSERT_TRUE(d.burst);
}

// ---------------------------------------------------------------- tipping bucket

static int poll_ms(pkr_rain_t* r, uint8_t level, uint32_t* now, uint32_t ms) {
  int tips = 0;
  for (uint32_t t = 0; t < ms; t += 5) {
    *now += 5;
    if (pkr_rain_poll(r, level, *now) == 1) tips++;
  }
  return tips;
}

static void test_rain_debounce_and_bounce() {
  pkr_rain_t r;
  r.tips_total = 0;
  pkr_rain_init(&r, 0, 1);  // reed to GND, idle high
  uint32_t now = 0;
  // a 15 ms glitch is not a tip
  poll_ms(&r, 0, &now, 15);
  poll_ms(&r, 1, &now, 100);
  TEST_ASSERT_EQUAL_UINT32(0, r.tips_total);
  // a 100 ms closure is one tip
  TEST_ASSERT_EQUAL_INT(1, poll_ms(&r, 0, &now, 100));
  poll_ms(&r, 1, &now, 100);
  TEST_ASSERT_EQUAL_UINT32(1, r.tips_total);
  // a second closure 200 ms after the first: contact bounce, counted as bounce not rain
  poll_ms(&r, 0, &now, 100);
  poll_ms(&r, 1, &now, 1000);
  TEST_ASSERT_EQUAL_UINT32(1, r.tips_total);
  TEST_ASSERT_EQUAL_UINT32(1, r.bounce);
  TEST_ASSERT_LESS_THAN_UINT32(400, r.min_tip_ms);
  // a real tip later
  poll_ms(&r, 0, &now, 100);
  poll_ms(&r, 1, &now, 100);
  TEST_ASSERT_EQUAL_UINT32(2, r.tips_total);
  pkr_rain_report_reset(&r);
  TEST_ASSERT_EQUAL_UINT32(0xFFFFFFFFu, r.min_tip_ms);
}

static void test_rain_edge_path_and_counter_wrap() {
  pkr_rain_t r;
  r.tips_total = 0xFFFFFFFEu;  // restored from NVS, about to wrap
  pkr_rain_init(&r, 0, 1);
  TEST_ASSERT_EQUAL_INT(1, pkr_rain_edge(&r, 1000));
  TEST_ASSERT_EQUAL_INT(2, pkr_rain_edge(&r, 1300));  // 300 ms: bounce
  TEST_ASSERT_EQUAL_INT(1, pkr_rain_edge(&r, 1500));  // 500 ms after the last counted tip
  TEST_ASSERT_EQUAL_INT(1, pkr_rain_edge(&r, 2500));
  TEST_ASSERT_EQUAL_UINT32(1, r.tips_total);           // wrapped
  TEST_ASSERT_EQUAL_UINT32(3, pkr_rain_delta(r.tips_total, 0xFFFFFFFEu));  // wrap-safe difference
  // millisecond clock wrap too
  pkr_rain_t w;
  w.tips_total = 0;
  pkr_rain_init(&w, 0, 1);
  pkr_rain_edge(&w, 0xFFFFFF00u);
  TEST_ASSERT_EQUAL_INT(1, pkr_rain_edge(&w, 0x00000200u));  // 768 ms later across the wrap
}

static void test_rain_rates() {
  pkr_rain_minutes_t m;
  pkr_rain_minutes_init(&m);
  uint32_t t0 = 1761121800;
  // 120 mm/h at 0.2 mm a tip = 10 tips a minute for 20 minutes
  for (uint32_t s = 0; s < 1200; s += 6) pkr_rain_minutes_add(&m, t0 + s, 1);
  uint32_t now = t0 + 1199;
  TEST_ASSERT_EQUAL_UINT32(150, pkr_rain_minutes_sum(&m, now, 15));
  TEST_ASSERT_EQUAL_UINT16(10, pkr_rain_minutes_peak(&m, now, 15));
  TEST_ASSERT_EQUAL_UINT16(300, pkr_rain_15min_tenths(&m, now, 200));  // 30.0 mm in 15 min
  TEST_ASSERT_GREATER_OR_EQUAL(PKR_RAIN_BURST_TIPS_PER_MIN, pkr_rain_minutes_peak(&m, now, 1));
  // an hour later it has all aged out
  TEST_ASSERT_EQUAL_UINT32(0, pkr_rain_minutes_sum(&m, now + 3600, 15));
}

// ---------------------------------------------------------------- duty cycle

static void fill(pkr_duty_t* d, uint32_t now, uint32_t frame_ms, int alarm, uint32_t* sent_ms) {
  while (pkr_duty_can_send(d, now, frame_ms, alarm)) {
    pkr_duty_record(d, now, frame_ms);
    *sent_ms += frame_ms;
  }
}

static void test_duty_cycle_node_and_relay() {
  uint32_t frame = pkr_lora_airtime_ms(32, 10, 125000, 5, 8, 1, 1);
  pkr_duty_t d;
  pkr_duty_init(&d, PKR_DUTY_NODE_BUDGET_MS, PKR_DUTY_TELEMETRY_STOP_PCT);
  uint32_t t = 1761121800, sent = 0;
  fill(&d, t, frame, 0, &sent);
  TEST_ASSERT_LESS_OR_EQUAL_UINT32(90000 * 70 / 100, sent);  // telemetry stops at 70 %
  TEST_ASSERT_GREATER_THAN_UINT32(90000 * 70 / 100 - frame, sent);
  fill(&d, t + 10, frame, 1, &sent);
  TEST_ASSERT_LESS_OR_EQUAL_UINT32(90000, sent);  // alarm frames may use the rest, never more
  TEST_ASSERT_FALSE(pkr_duty_can_send(&d, t + 3599, frame, 1));
  // an hour (and a minute of margin) later the budget is back
  TEST_ASSERT_TRUE(pkr_duty_can_send(&d, t + 3600 + 61, frame, 1));
  // sliding: spread sends over two hours; no 3600 s window ever holds more than 2.5 %
  pkr_duty_init(&d, PKR_DUTY_NODE_BUDGET_MS, PKR_DUTY_TELEMETRY_STOP_PCT);
  std::vector<std::pair<uint32_t, uint32_t>> sends;
  for (uint32_t s = 0; s < 7200; s += 7)
    if (pkr_duty_can_send(&d, t + s, frame, 1)) {
      pkr_duty_record(&d, t + s, frame);
      sends.push_back({t + s, frame});
    }
  for (uint32_t w = 0; w < 7200; w += 13) {
    uint32_t sum = 0;
    for (auto& e : sends)
      if (e.first >= t + w && e.first < t + w + 3600) sum += e.second;
    TEST_ASSERT_LESS_OR_EQUAL_UINT32(90000, sum);
  }
  // relay: 10 %
  pkr_duty_init(&d, PKR_DUTY_RELAY_BUDGET_MS, PKR_DUTY_TELEMETRY_STOP_PCT);
  sent = 0;
  fill(&d, t, frame, 1, &sent);
  TEST_ASSERT_LESS_OR_EQUAL_UINT32(360000, sent);
  TEST_ASSERT_GREATER_THAN_UINT32(360000 - frame, sent);
}

// ---------------------------------------------------------------- SEN0676, DFPlayer, E22

static void test_modbus_codec() {
  uint8_t q[8];
  pkr_modbus_request(0x01, 0x03, 0x0001, 0x0001, q);
  const uint8_t want[8] = {0x01, 0x03, 0x00, 0x01, 0x00, 0x01, 0xD5, 0xCA};  // CRC low byte first
  TEST_ASSERT_EQUAL_HEX8_ARRAY(want, q, 8);
  // a reply: 2391 mm
  uint8_t r[7] = {0x01, 0x03, 0x02, 0x09, 0x57, 0, 0};
  uint16_t c = pkr_modbus_crc(r, 5);
  r[5] = (uint8_t)c;
  r[6] = (uint8_t)(c >> 8);
  uint16_t reg;
  uint8_t ex = 0;
  TEST_ASSERT_EQUAL_INT(PKR_MB_OK, pkr_modbus_parse_read(r, 7, 1, 1, &reg, &ex));
  TEST_ASSERT_EQUAL_UINT16(2391, reg);
  r[4] ^= 1;
  TEST_ASSERT_EQUAL_INT(PKR_MB_E_CRC, pkr_modbus_parse_read(r, 7, 1, 1, &reg, &ex));
  r[4] ^= 1;
  TEST_ASSERT_EQUAL_INT(PKR_MB_E_SHORT, pkr_modbus_parse_read(r, 6, 1, 1, &reg, &ex));
  TEST_ASSERT_EQUAL_INT(PKR_MB_E_ADDR, pkr_modbus_parse_read(r, 7, 2, 1, &reg, &ex));
  uint8_t two[2];
  (void)two;
  TEST_ASSERT_EQUAL_INT(PKR_MB_E_COUNT, pkr_modbus_parse_read(r, 7, 1, 2, &reg, &ex));
  // exception replies 0x83 (read) and 0x86 (write)
  uint8_t e[5] = {0x01, 0x83, 0x02, 0, 0};
  c = pkr_modbus_crc(e, 3);
  e[3] = (uint8_t)c;
  e[4] = (uint8_t)(c >> 8);
  TEST_ASSERT_EQUAL_INT(PKR_MB_E_EXCEPTION, pkr_modbus_parse_read(e, 5, 1, 1, &reg, &ex));
  TEST_ASSERT_EQUAL_HEX8(0x02, ex);
  uint8_t w[8];
  pkr_modbus_request(0x01, 0x06, PKR_SEN0676_REG_INSTALL_HEIGHT_CM, 420, w);
  TEST_ASSERT_EQUAL_INT(PKR_MB_OK, pkr_modbus_parse_write(w, 8, w, &ex));  // the echo
  uint8_t e6[5] = {0x01, 0x86, 0x03, 0, 0};
  c = pkr_modbus_crc(e6, 3);
  e6[3] = (uint8_t)c;
  e6[4] = (uint8_t)(c >> 8);
  TEST_ASSERT_EQUAL_INT(PKR_MB_E_EXCEPTION, pkr_modbus_parse_write(e6, 5, w, &ex));
  TEST_ASSERT_EQUAL_HEX8(0x03, ex);
  uint8_t other[8];
  pkr_modbus_request(0x01, 0x06, PKR_SEN0676_REG_INSTALL_HEIGHT_CM, 421, other);
  TEST_ASSERT_EQUAL_INT(PKR_MB_E_ECHO, pkr_modbus_parse_write(other, 8, w, &ex));
}

static void test_dfplayer_frame() {
  uint8_t f[10];
  pkr_df_frame(PKR_DF_PLAY_FOLDER_FILE, 0x0101, 0, f);  // folder 01, file 001
  const uint8_t want[10] = {0x7E, 0xFF, 0x06, 0x0F, 0x00, 0x01, 0x01, 0xFE, 0xEA, 0xEF};
  TEST_ASSERT_EQUAL_HEX8_ARRAY(want, f, 10);
  uint8_t cmd;
  uint16_t p;
  TEST_ASSERT_EQUAL_INT(0, pkr_df_parse(f, &cmd, &p));
  TEST_ASSERT_EQUAL_HEX8(0x0F, cmd);
  TEST_ASSERT_EQUAL_HEX16(0x0101, p);
  f[6] ^= 1;
  TEST_ASSERT_EQUAL_INT(-1, pkr_df_parse(f, &cmd, &p));
}

static void test_e22_channel_raster() {
  // the spec's 865.4025 MHz is not on the E22 raster (850.125 + n MHz): nearest is CH 15
  TEST_ASSERT_EQUAL_INT(15, pkr_e22_channel_for(PKR_RADIO_FREQ_PRIMARY_HZ));
  TEST_ASSERT_EQUAL_UINT32(865125000u, pkr_e22_channel_hz(15));
  TEST_ASSERT_EQUAL_INT(16, pkr_e22_channel_for(PKR_RADIO_FREQ_SECONDARY_HZ));  // 866.125, the secondary moves too
  TEST_ASSERT_EQUAL_INT(-1, pkr_e22_channel_for(433000000u));
  uint8_t c[12];
  pkr_e22_config(0x1234, 0, 15, 2, 0, c);
  TEST_ASSERT_EQUAL_HEX8(0xC0, c[0]);
  TEST_ASSERT_EQUAL_HEX8(0x12, c[3]);
  TEST_ASSERT_EQUAL_HEX8(15, c[8]);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_two_of_three_with_nan);
  RUN_TEST(test_gauge_alarm_needs_two_of_three_and_sanity);
  RUN_TEST(test_blind_zone_never_alarms);
  RUN_TEST(test_bridge_beacon_latch_and_burst);
  RUN_TEST(test_rain_debounce_and_bounce);
  RUN_TEST(test_rain_edge_path_and_counter_wrap);
  RUN_TEST(test_rain_rates);
  RUN_TEST(test_duty_cycle_node_and_relay);
  RUN_TEST(test_modbus_codec);
  RUN_TEST(test_dfplayer_frame);
  RUN_TEST(test_e22_channel_raster);
  return UNITY_END();
}
