// Pattern tables (section 4.1) and the player: timings, caps, the 10-minute continuous limit,
// voice slots, and the drill pattern never mapping to a real alert pattern.
#include <unity.h>

#include <vector>

#include "pkr_pattern.h"

void setUp() {}
void tearDown() {}

using namespace pkr;

struct Trace {
  std::vector<Output> out;  // one per 100 ms
  uint32_t step = 100;
  bool tone_at(uint32_t ms) const { return ms / step < out.size() && out[ms / step].tone; }
  bool clip_at(uint32_t ms) const { return ms / step < out.size() && out[ms / step].clip_playing; }
  uint16_t hz_at(uint32_t ms) const { return ms / step < out.size() ? out[ms / step].freq_hz : 0; }
  uint32_t length_ms() const { return (uint32_t)out.size() * step; }
  std::vector<uint32_t> clip_starts() const {
    std::vector<uint32_t> v;
    for (size_t i = 0; i < out.size(); i++)
      if (out[i].clip_start) v.push_back((uint32_t)i * step);
    return v;
  }
};

static Trace play(const PlayPlan& p, uint32_t max_ms, uint32_t step = 100) {
  PatternPlayer pl;
  Trace t;
  t.step = step;
  uint32_t now = 5000;
  pl.start(p, now);
  t.out.push_back(pl.output());
  while (pl.active() && t.length_ms() < max_ms) {
    now += step;
    t.out.push_back(pl.tick(now));
  }
  if (!t.out.empty() && !t.out.back().active) t.out.pop_back();
  return t;
}

static void test_w1_three_long() {
  PlayPlan p = make_plan(PKR_PATTERN_W1, false, PlanOptions());
  TEST_ASSERT_EQUAL_UINT32(57000, cycle_ms(p));  // 3 x (5 + 3) + 18 clip + 15 silence, "about 60 s"
  TEST_ASSERT_EQUAL_UINT16(5, p.first_cycles);
  TEST_ASSERT_EQUAL_UINT32(900, p.repeat_every_s);
  TEST_ASSERT_EQUAL_UINT16(2, p.repeat_cycles);
  TEST_ASSERT_EQUAL_UINT32(1200, p.cap_on_s);
  TEST_ASSERT_EQUAL_UINT8(STROBE_AMBER, p.strobe);
  Trace t = play(p, 70000);
  for (uint32_t ms : {0u, 2500u, 4900u, 8000u, 12900u, 16000u, 20900u}) {
    TEST_ASSERT_TRUE(t.tone_at(ms));
    TEST_ASSERT_EQUAL_UINT16(650, t.hz_at(ms));
  }
  for (uint32_t ms : {5000u, 7900u, 13000u, 21000u, 23900u}) TEST_ASSERT_FALSE(t.tone_at(ms));
  TEST_ASSERT_TRUE(t.clip_at(24000));
  TEST_ASSERT_TRUE(t.clip_at(41900));
  TEST_ASSERT_FALSE(t.clip_at(42000));
  TEST_ASSERT_FALSE(t.tone_at(50000));  // 15 s silence
  TEST_ASSERT_TRUE(t.tone_at(57000));   // the next cycle
  TEST_ASSERT_EQUAL_UINT32(24000, t.clip_starts()[0]);
}

static void test_w1_first_burst_then_repeats_and_cap() {
  PlayPlan p = make_plan(PKR_PATTERN_W1, false, PlanOptions());
  Trace t = play(p, 6 * 3600 * 1000u, 500);  // the 20-minute sound cap is reached after about 4.6 h
  // 5 cycles, then silence for 15 minutes, then 2 cycles
  TEST_ASSERT_TRUE(t.tone_at(4 * 57000 + 1000));
  TEST_ASSERT_FALSE(t.tone_at(5 * 57000 + 1000));
  TEST_ASSERT_FALSE(t.out[(5 * 57000 + 60000) / 500].in_block);
  TEST_ASSERT_TRUE(t.tone_at(5 * 57000 + 900000 + 1000));
  // the per-alert cap: 20 minutes of sound, then it ends
  uint32_t sound = 0;
  for (auto& o : t.out) sound += (o.tone || o.clip_playing) ? 500 : 0;
  TEST_ASSERT_UINT32_WITHIN(1000, 1200000, sound);
}

static void test_c1_lahar_and_ten_minute_rest() {
  PlayPlan p = make_plan(PKR_PATTERN_C1, false, PlanOptions());
  TEST_ASSERT_EQUAL_UINT32(90000, cycle_ms(p));
  TEST_ASSERT_EQUAL_UINT16(10, p.first_cycles);
  TEST_ASSERT_EQUAL_UINT32(2700, p.cap_on_s);
  Trace t = play(p, 30 * 60 * 1000u);
  // rising and falling 500 <-> 1050 Hz with a 6 s period
  TEST_ASSERT_EQUAL_UINT16(500, t.hz_at(0));
  TEST_ASSERT_UINT16_WITHIN(5, 1050, t.hz_at(3000));
  TEST_ASSERT_UINT16_WITHIN(5, 775, t.hz_at(1500));
  TEST_ASSERT_EQUAL_UINT16(500, t.hz_at(6000));
  TEST_ASSERT_TRUE(t.clip_at(60000));
  TEST_ASSERT_FALSE(t.clip_at(80000) || t.tone_at(80000));
  // 10 minutes of continuous sounding, then a 2-minute rest with the amp off, then it resumes
  TEST_ASSERT_TRUE(t.out[599000 / 100].in_block);
  for (uint32_t ms = 600100; ms < 720000; ms += 1000) {
    TEST_ASSERT_TRUE(t.out[ms / 100].resting);
    TEST_ASSERT_FALSE(t.tone_at(ms) || t.clip_at(ms));
  }
  TEST_ASSERT_TRUE(t.out[720100 / 100].in_block);
  // never more than 10 minutes without a 2-minute break, anywhere in the run
  uint32_t run = 0, quiet = 0;
  for (auto& o : t.out) {
    if (o.in_block) {
      run += 100;
      quiet = 0;
    } else {
      quiet += 100;
      if (quiet >= 120000) run = 0;
    }
    TEST_ASSERT_LESS_OR_EQUAL_UINT32(600000, run);
  }
}

static void test_a1_once_and_once_more() {
  PlayPlan p = make_plan(PKR_PATTERN_A1, false, PlanOptions());
  Trace t = play(p, 3600 * 1000u);
  TEST_ASSERT_TRUE(t.tone_at(0));
  TEST_ASSERT_EQUAL_UINT16(650, t.hz_at(1000));
  TEST_ASSERT_TRUE(t.tone_at(29900));
  TEST_ASSERT_TRUE(t.clip_at(30000));
  TEST_ASSERT_TRUE(t.out[1000 / 100].strobe);
  TEST_ASSERT_FALSE(t.out[31000 / 100].strobe);  // green for 30 s, then off
  TEST_ASSERT_EQUAL_UINT8(STROBE_GREEN, t.out[0].strobe_colour);
  size_t starts = t.clip_starts().size();
  TEST_ASSERT_EQUAL_UINT(2, starts);  // once, then once more after 5 minutes
  TEST_ASSERT_TRUE(t.tone_at(50000 + 300000 + 1000));
  TEST_ASSERT_LESS_THAN_UINT32(50000 * 2 + 300000 + 1000, t.length_ms());
}

static void test_t1_is_short_and_quiet() {
  PlayPlan p = make_plan(PKR_PATTERN_T1, false, PlanOptions());
  Trace t = play(p, 120000);
  TEST_ASSERT_LESS_OR_EQUAL_UINT32(30000, t.length_ms());
  int beeps = 0;
  bool prev = false;
  for (uint32_t ms = 0; ms < 2000; ms += 100) {
    bool on = t.tone_at(ms);
    if (on && !prev) beeps++;
    prev = on;
  }
  TEST_ASSERT_EQUAL_INT(3, beeps);
  TEST_ASSERT_EQUAL_UINT16(900, t.hz_at(0));
  for (auto& o : t.out)
    if (o.tone || o.clip_playing) TEST_ASSERT_LESS_OR_EQUAL_UINT8(50, o.volume);
  TEST_ASSERT_FALSE(p.k3_mirror);  // the electronic siren has no 50 %
}

static void test_drill_never_maps_to_a_real_alert_pattern() {
  for (int c1 = 0; c1 < 2; c1++) {
    PlanOptions o;
    o.drill_with_c1 = c1;
    PlayPlan p = make_plan(PKR_PATTERN_D1, false, o);
    // the drill clip FIRST, the "it was a drill" clip LAST, once, under 2 minutes
    TEST_ASSERT_TRUE(p.cycle.front().kind == Seg::Clip);
    TEST_ASSERT_EQUAL_UINT8(CLIP_DRILL, p.cycle.front().clip);
    TEST_ASSERT_EQUAL_UINT8(CLIP_DRILL_END, p.cycle.back().clip);
    TEST_ASSERT_EQUAL_UINT16(1, p.max_blocks);
    TEST_ASSERT_EQUAL_UINT16(0, p.repeat_cycles);
    Trace t = play(p, 600000);
    TEST_ASSERT_LESS_OR_EQUAL_UINT32(120000, t.length_ms());
    TEST_ASSERT_TRUE(t.clip_at(0));
    TEST_ASSERT_FALSE(t.tone_at(0));
    // never a real alert's voice clip
    for (auto& o : t.out) {
      if (o.clip_playing) TEST_ASSERT_TRUE(o.clip == CLIP_DRILL || o.clip == CLIP_DRILL_END);
    }
    auto starts = t.clip_starts();
    TEST_ASSERT_EQUAL_UINT(2, starts.size());
  }
  // and the ids and SMS letters are distinct from W1 and C1
  TEST_ASSERT_NOT_EQUAL(PKR_PATTERN_D1, PKR_PATTERN_W1);
  TEST_ASSERT_NOT_EQUAL(PKR_PATTERN_D1, PKR_PATTERN_C1);
  TEST_ASSERT_EQUAL_INT(PKR_CMDLEVEL_DRILL, pkr_pattern_cmd_level(PKR_PATTERN_D1));
  TEST_ASSERT_EQUAL_INT(PKR_CMDLEVEL_WARNING, pkr_pattern_cmd_level(PKR_PATTERN_W1));
  TEST_ASSERT_EQUAL_INT(PKR_CMDLEVEL_CRITICAL, pkr_pattern_cmd_level(PKR_PATTERN_C1));
  TEST_ASSERT_NOT_EQUAL(PKR_SMS_PATTERN_D1, PKR_SMS_PATTERN_W1);
  TEST_ASSERT_NOT_EQUAL(PKR_SMS_PATTERN_D1, PKR_SMS_PATTERN_C1);
}

static void test_autonomy_variant_and_b1() {
  PlayPlan a = make_plan(PKR_PATTERN_C1, true, PlanOptions());
  TEST_ASSERT_EQUAL_UINT8(CLIP_AUTO, a.cycle[1].clip);
  TEST_ASSERT_EQUAL_UINT32(1800, a.cap_on_s);
  TEST_ASSERT_EQUAL_UINT32(900, a.repeat_every_s);
  TEST_ASSERT_EQUAL_UINT16(10, a.repeat_cycles);
  PlayPlan b = make_plan(PKR_PATTERN_B1, false, PlanOptions());
  Trace t = play(b, 600000);
  TEST_ASSERT_UINT32_WITHIN(100, 120000, t.length_ms());  // 2 minutes per wake, as v2
  TEST_ASSERT_TRUE(t.tone_at(0));
  TEST_ASSERT_TRUE(t.tone_at(1400));
  TEST_ASSERT_FALSE(t.tone_at(1500));
  TEST_ASSERT_TRUE(t.tone_at(10000));
  TEST_ASSERT_EQUAL_UINT16(1200, t.hz_at(10000));
}

static void test_voice_slot_one_speaks_25_s_later() {
  for (uint8_t pat : {(uint8_t)PKR_PATTERN_W1, (uint8_t)PKR_PATTERN_C1}) {
    PlanOptions s0, s1;
    s1.voice_slot = 1;
    Trace a = play(make_plan(pat, false, s0), 400000);
    Trace b = play(make_plan(pat, false, s1), 400000);
    auto ca = a.clip_starts(), cb = b.clip_starts();
    TEST_ASSERT_TRUE(ca.size() >= 3 && cb.size() >= 3);
    for (size_t i = 0; i < 3; i++) TEST_ASSERT_EQUAL_UINT32(ca[i] + 25000, cb[i]);  // stays 25 s apart
    // slot 1 plays tone, not silence, while slot 0 speaks
    TEST_ASSERT_TRUE(b.tone_at(ca[0] + 1000) || b.tone_at(ca[0] + 4000));
    // and their voices never overlap
    for (uint32_t ms = 0; ms < 300000; ms += 100) TEST_ASSERT_FALSE(a.clip_at(ms) && b.clip_at(ms));
  }
}

static void test_command_overrides_and_unknown() {
  PlanOptions o;
  o.cycles = 2;
  o.cap_on_s = 60;
  o.volume = 40;
  PlayPlan p = make_plan(PKR_PATTERN_W1, false, o);
  TEST_ASSERT_EQUAL_UINT16(2, p.first_cycles);
  Trace t = play(p, 3600000);
  uint32_t sound = 0;
  for (auto& x : t.out) {
    sound += (x.tone || x.clip_playing) ? 100 : 0;
    if (x.tone) TEST_ASSERT_EQUAL_UINT8(40, x.volume);
  }
  TEST_ASSERT_UINT32_WITHIN(200, 60000, sound);
  TEST_ASSERT_TRUE(make_plan(99, false, PlanOptions()).cycle.empty());
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_w1_three_long);
  RUN_TEST(test_w1_first_burst_then_repeats_and_cap);
  RUN_TEST(test_c1_lahar_and_ten_minute_rest);
  RUN_TEST(test_a1_once_and_once_more);
  RUN_TEST(test_t1_is_short_and_quiet);
  RUN_TEST(test_drill_never_maps_to_a_real_alert_pattern);
  RUN_TEST(test_autonomy_variant_and_b1);
  RUN_TEST(test_voice_slot_one_speaks_25_s_later);
  RUN_TEST(test_command_overrides_and_unknown);
  return UNITY_END();
}
