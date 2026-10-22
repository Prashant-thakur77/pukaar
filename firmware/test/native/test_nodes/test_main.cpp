// The images that are not the siren: the gauge v3 wake (burst reduce, the decision with rain, what goes
// on LoRa, the sleep), the tipping-bucket counter as the ULP runs it (5 ms ticks) and as a reading
// reports it, the provisioned settings, the pradhan box's shadow (level, alert, relay_cmd), its mesh
// batch, and a cloud command carried box -> relay -> siren without being started twice.
#include <math.h>
#include <string.h>
#include <unity.h>

#include <string>
#include <vector>

#include "../support/fakes.h"
#include "pkr_codec.h"
#include "pkr_lora.h"
#include "pkr_node.h"

void setUp() {}
void tearDown() {}

using namespace pkr;

// ---------------------------------------------------------------- burst reduce (the v2 sketch's maths)

static void test_burst_reduce_matches_v2() {
  pkr_burst_t b;
  const uint16_t steady[9] = {2391, 2390, 2393, 2389, 2391, 2392, 2390, 2391, 2394};
  pkr_burst_reduce(steady, 9, 150, 40000, &b);
  TEST_ASSERT_EQUAL_UINT16(2391, b.distance_mm);
  TEST_ASSERT_EQUAL_UINT8(9, b.ok);
  TEST_ASSERT_EQUAL_UINT16(0, b.err);
  TEST_ASSERT_FALSE(b.blind_hit);
  // a debris echo far from the median is rejected; one dropout (0) is just missing
  const uint16_t spiky[9] = {2391, 0, 2390, 900, 2392, 2391, 2389, 2390, 2393};
  pkr_burst_reduce(spiky, 9, 150, 40000, &b);
  TEST_ASSERT_EQUAL_UINT16(2391, b.distance_mm);
  TEST_ASSERT_EQUAL_UINT8(7, b.ok);
  TEST_ASSERT_EQUAL_UINT16(0, b.err);
  // nothing back at all
  const uint16_t none[9] = {0};
  pkr_burst_reduce(none, 9, 150, 40000, &b);
  TEST_ASSERT_EQUAL_UINT16(0, b.distance_mm);
  TEST_ASSERT_EQUAL_UINT16(PKR_ERR_NO_ECHO, b.err);
  // a blocked face: everything inside the blind zone. Out of range, and flagged blind.
  const uint16_t blocked[9] = {120, 130, 125, 140, 120, 150, 118, 122, 131};
  pkr_burst_reduce(blocked, 9, 150, 40000, &b);
  TEST_ASSERT_EQUAL_UINT16(0, b.distance_mm);
  TEST_ASSERT_EQUAL_UINT16(PKR_ERR_SENSOR_RANGE, b.err);
  TEST_ASSERT_TRUE(b.blind_hit);
  // too few and too spread
  const uint16_t wild[9] = {1000, 1400, 1800, 2200, 0, 0, 0, 0, 0};
  pkr_burst_reduce(wild, 9, 150, 40000, &b);
  TEST_ASSERT_TRUE(b.err & PKR_ERR_FEW_SAMPLES);
  TEST_ASSERT_TRUE(b.err & PKR_ERR_HIGH_SPREAD);
}

// ---------------------------------------------------------------- the ULP tip counter

// n ULP runs (5 ms each) at one reed level; returns how many asked for the main CPU
static int ulp_run(pkr_ulp_rain_t* u, uint8_t level, uint32_t ms) {
  int wakes = 0;
  for (uint32_t t = 0; t < ms; t += PKR_RAIN_POLL_MS) wakes += pkr_ulp_rain_step(u, level, PKR_RAIN_BURST_TIPS_PER_MIN);
  return wakes;
}

static void test_ulp_tick_math_debounce_bounce_and_wake() {
  static pkr_ulp_rain_t u;
  pkr_ulp_rain_init(&u, 0, 1, 1000);  // reed to GND, idle high, 1000 tips restored from the NVS mirror
  TEST_ASSERT_EQUAL_HEX32(PKR_ULP_RAIN_MAGIC, u.magic);
  // 200 runs are one second of ULP time
  ulp_run(&u, 1, 1000);
  TEST_ASSERT_EQUAL_UINT32(200, u.tick);
  TEST_ASSERT_EQUAL_UINT32(1, pkr_ulp_rain_now_s(&u));
  // 15 ms closed is 3 samples but not 25 ms: no tip
  ulp_run(&u, 0, 15);
  ulp_run(&u, 1, 500);
  TEST_ASSERT_EQUAL_UINT32(1000, u.rain.tips_total);
  // a 100 ms closure: one tip; the first tip of a minute does not wake the CPU
  TEST_ASSERT_EQUAL_INT(0, ulp_run(&u, 0, 100));
  ulp_run(&u, 1, 2000);
  TEST_ASSERT_EQUAL_UINT32(1001, u.rain.tips_total);
  // the second tip in the same minute reaches 2 tips/min: one wake, once a minute
  TEST_ASSERT_EQUAL_INT(1, ulp_run(&u, 0, 100));
  ulp_run(&u, 1, 2000);
  TEST_ASSERT_EQUAL_INT(0, ulp_run(&u, 0, 100));  // a third: no second wake this minute
  ulp_run(&u, 1, 150);
  // chatter 150 ms after a tip: bounce, not rain
  ulp_run(&u, 0, 100);
  ulp_run(&u, 1, 2000);
  TEST_ASSERT_EQUAL_UINT32(1003, u.rain.tips_total);
  TEST_ASSERT_EQUAL_UINT32(1, u.rain.bounce);
  // the ms clock (tick x 5) wraps after 9.9 days; counting goes on across it
  u.tick = 0xFFFFFFFFu / PKR_RAIN_POLL_MS - 3;  // the debounce straddles the wrap
  u.rain.last_tip_ms = u.tick * PKR_RAIN_POLL_MS - 5000;
  u.rain.last_edge_ms = u.rain.last_tip_ms;
  ulp_run(&u, 0, 100);
  ulp_run(&u, 1, 100);
  TEST_ASSERT_EQUAL_UINT32(1004, u.rain.tips_total);
  TEST_ASSERT_EQUAL_UINT32(1, u.rain.bounce);
}

static void test_rain_report_per_reading() {
  static pkr_ulp_rain_t u;
  pkr_ulp_rain_init(&u, 0, 1, 0xFFFFFFF0u);  // about to wrap
  pkr_rain_mark_t mark{};
  pkr_rain_report_t rep;
  uint32_t t0 = 1761121800;
  pkr_rain_take_report(&u, &mark, t0, 200, 0, 0, &rep);  // the first reading: no window yet
  TEST_ASSERT_EQUAL_UINT16(0, rep.window);
  TEST_ASSERT_EQUAL_UINT16(0xFFFF, rep.min_tip_ms);
  // the wake-on-tip build: 30 tips over 5 minutes, 10 s apart, one chatter
  uint32_t ms = 1000;
  for (int i = 0; i < 30; i++) {
    uint32_t s = t0 + 10 + 10 * (uint32_t)i;
    pkr_ulp_rain_tip(&u, ms, s, PKR_RAIN_BURST_TIPS_PER_MIN);
    if (i == 5) pkr_ulp_rain_tip(&u, ms + 200, s, PKR_RAIN_BURST_TIPS_PER_MIN);
    ms += 10000;
  }
  uint32_t now = t0 + 300;
  pkr_rain_take_report(&u, &mark, now, 200, 0, 0, &rep);
  TEST_ASSERT_EQUAL_UINT32(0xFFFFFFF0u + 30u, rep.tips_total);  // wrapped past 0
  TEST_ASSERT_EQUAL_UINT16(30, rep.window);                     // wrap-safe
  TEST_ASSERT_EQUAL_UINT16(1, rep.bounce);
  TEST_ASSERT_EQUAL_UINT8(PKR_RAIN_ERR_BOUNCE, rep.err);
  TEST_ASSERT_EQUAL_UINT16(200, rep.min_tip_ms);
  TEST_ASSERT_EQUAL_UINT16(6, rep.max_1min);
  TEST_ASSERT_GREATER_OR_EQUAL_UINT16(PKR_RAIN_BURST_TIPS_PER_MIN, rep.last_min);
  TEST_ASSERT_EQUAL_UINT16(60, rep.rain_15min_tenths);  // 30 tips x 0.2 mm = 6.0 mm
  // the next reading: nothing new, min_tip restarted, no bounce bit
  pkr_rain_take_report(&u, &mark, now + 300, 200, 0, 0, &rep);
  TEST_ASSERT_EQUAL_UINT16(0, rep.window);
  TEST_ASSERT_EQUAL_UINT16(0xFFFF, rep.min_tip_ms);
  TEST_ASSERT_EQUAL_UINT8(0, rep.err);
  // a cold boot lost the RTC state: restarted from an older NVS mirror. Not rain, and flagged.
  pkr_ulp_rain_init(&u, 0, 1, 0xFFFFFFF0u + 10u);
  pkr_rain_take_report(&u, &mark, now + 600, 200, 1, 0, &rep);
  TEST_ASSERT_EQUAL_UINT16(0, rep.window);
  TEST_ASSERT_EQUAL_UINT8(PKR_RAIN_ERR_COUNTER_RESET, rep.err);
  pkr_rain_take_report(&u, &mark, now + 900, 200, 0, 1, &rep);
  TEST_ASSERT_EQUAL_UINT8(PKR_RAIN_ERR_ULP_FAULT, rep.err);
}

// ---------------------------------------------------------------- settings and the gauge's wake

static void test_node_settings() {
  NodeSettings s;
  const char* j =
      "{\"village\":\"thunag\",\"endpoint\":\"abc-ats.iot.ap-south-1.amazonaws.com\",\"apn\":\"jionet\","
      "\"sensor\":\"radar\",\"mount_height_cm\":450,\"critical_cm\":310,\"blind_mm\":200,\"mm_per_tip\":0.28,"
      "\"downstream\":[\"siren-thunag-sim\",{\"device\":\"siren-thunag-02\",\"lora_addr\":259},{\"device\":\"x\","
      "\"lora_addr\":65535}]}";
  TEST_ASSERT_EQUAL_INT(0, parse_node_settings(j, strlen(j), &s));
  TEST_ASSERT_EQUAL_STRING("thunag", s.village);
  TEST_ASSERT_EQUAL_STRING("jionet", s.apn);
  TEST_ASSERT_EQUAL_FLOAT(450, s.mount_height_cm);
  TEST_ASSERT_EQUAL_FLOAT(310, s.gauge.critical_cm);
  TEST_ASSERT_EQUAL_FLOAT(250, s.gauge.warning_cm);  // default kept
  TEST_ASSERT_EQUAL_UINT16(200, s.gauge.blind_mm);
  TEST_ASSERT_EQUAL_FLOAT(0.28f, s.mm_per_tip);
  TEST_ASSERT_EQUAL_UINT8(2, s.n_downstream);  // the broadcast address is refused
  TEST_ASSERT_EQUAL_HEX16(pkr_lora_addr("siren-thunag-sim"), s.downstream[0].addr);
  TEST_ASSERT_EQUAL_HEX16(259, s.downstream[1].addr);
  const char* rain = "{\"sensor\":\"none\",\"mm_per_tip\":9}";
  TEST_ASSERT_EQUAL_INT(0, parse_node_settings(rain, strlen(rain), &s));
  TEST_ASSERT_EQUAL_UINT8(SENSOR_NONE, s.sensor);
  TEST_ASSERT_EQUAL_FLOAT(0.2f, s.mm_per_tip);  // out of range: the default
  TEST_ASSERT_EQUAL_INT(PKR_REASON_BAD_FORMAT, parse_node_settings("{oops", 5, &s));
}

static GaugeInputs at_distance(uint16_t mm, uint32_t now) {
  GaugeInputs in;
  uint16_t v[9];
  for (int i = 0; i < 9; i++) v[i] = mm;
  pkr_burst_reduce(v, 9, 150, 40000, &in.burst);
  in.battery_mv = 13100;
  in.now = now;
  in.clock_ok = true;
  return in;
}

static void test_gauge_v3_decision_with_rain() {
  NodeSettings s;  // mount 420 cm: stage = 420 - distance/10; critical 300 cm
  s.downstream[0].addr = PKR_SIM_SIREN_ADDR;
  strcpy(s.downstream[0].device, PKR_SIM_SIREN);
  s.n_downstream = 1;
  pkr_gauge_state_t st;
  pkr_gauge_state_init(&st);
  uint32_t t = 1761121800;
  GaugePlan p;
  // a calm river: normal cadence, a GAUGE_STATUS only
  gauge_plan(&st, s, at_distance(3000, t), 1, &p);
  TEST_ASSERT_TRUE(p.record);
  TEST_ASSERT_FALSE(p.alarm);
  TEST_ASSERT_EQUAL_UINT32(300, p.sleep_s);
  TEST_ASSERT_EQUAL_INT16(120, p.status.stage_cm);
  TEST_ASSERT_EQUAL_INT16(1200, p.rec.level_mm);
  // heavy rain over a calm river: burst cadence, the rain in GAUGE_STATUS and the record, still no alarm
  GaugeInputs in = at_distance(3000, t + 300);
  in.rain.last_min = 3;
  in.rain.window = 12;
  in.rain.tips_total = 4012;
  in.rain.rain_15min_tenths = 24;
  in.cloud_ok = true;
  gauge_plan(&st, s, in, 2, &p);
  TEST_ASSERT_FALSE(p.alarm);
  TEST_ASSERT_EQUAL_UINT32(60, p.sleep_s);
  TEST_ASSERT_EQUAL_UINT16(24, p.status.rain_15min_tenths_mm);
  TEST_ASSERT_EQUAL_UINT8(1, p.status.cloud_ok);
  TEST_ASSERT_EQUAL_UINT16(12, p.rec.rain_tips_window);
  TEST_ASSERT_EQUAL_UINT32(4012, p.rec.rain_tips_total);
  // the river comes up: 2 of 3 at critical (and a normal reading within 24 h) sends GAUGE_ALARM
  gauge_plan(&st, s, at_distance(1100, t + 360), 3, &p);  // 310 cm
  TEST_ASSERT_FALSE(p.alarm);                               // 1 of 3
  gauge_plan(&st, s, at_distance(1050, t + 420), 4, &p);  // 315 cm
  TEST_ASSERT_TRUE(p.alarm);
  TEST_ASSERT_EQUAL_UINT8(PKR_LEVEL_CRITICAL, p.status.level);
  TEST_ASSERT_EQUAL_UINT32(60, p.sleep_s);  // the siren keeps hearing it every minute
  // no clock: nothing recorded (the server could not place it), but the alarm still goes
  GaugeInputs noclock = at_distance(1040, t + 480);
  noclock.clock_ok = false;
  gauge_plan(&st, s, noclock, 5, &p);
  TEST_ASSERT_FALSE(p.record);
  TEST_ASSERT_TRUE(p.alarm);
  // a flat battery: hibernate, no radio at all
  GaugeInputs flat = at_distance(1040, t + 540);
  flat.battery_mv = 11500;
  gauge_plan(&st, s, flat, 6, &p);
  TEST_ASSERT_FALSE(p.radio);
  TEST_ASSERT_FALSE(p.alarm);
  TEST_ASSERT_EQUAL_UINT32(1800, p.sleep_s);
  TEST_ASSERT_TRUE(p.rec.err & PKR_ERR_LOW_VOLTAGE);
  // a blocked face is never a flood
  pkr_gauge_state_t st2;
  pkr_gauge_state_init(&st2);
  gauge_plan(&st2, s, at_distance(3000, t), 1, &p);
  for (int i = 1; i <= 3; i++) gauge_plan(&st2, s, at_distance(120, t + 60u * i), 1 + i, &p);
  TEST_ASSERT_FALSE(p.alarm);
}

static void test_rain_node_never_alarms() {
  NodeSettings s;
  s.sensor = SENSOR_NONE;
  s.n_downstream = 1;
  s.downstream[0].addr = PKR_SIM_SIREN_ADDR;
  pkr_gauge_state_t st;
  pkr_gauge_state_init(&st);
  GaugeInputs in;
  in.now = 1761121800;
  in.clock_ok = true;
  in.battery_mv = 13000;
  in.rain.last_min = 10;
  in.rain.rain_15min_tenths = 300;
  GaugePlan p;
  gauge_plan(&st, s, in, 1, &p);
  TEST_ASSERT_TRUE(p.record);
  TEST_ASSERT_FALSE(p.alarm);
  TEST_ASSERT_EQUAL_UINT8(PKR_LEVEL_NORMAL, p.status.level);
  TEST_ASSERT_EQUAL_UINT16(300, p.status.rain_15min_tenths_mm);
  TEST_ASSERT_EQUAL_UINT8(100, p.status.quality);
  TEST_ASSERT_EQUAL_UINT32(60, p.sleep_s);
  GaugeJsonOpts o;
  o.has_level_sensor = false;
  o.fw = "pukaar-rain-0.1.0";
  char out[600];
  TEST_ASSERT_GREATER_THAN(0, gauge_reading_json(p.rec, o, out, sizeof out));
  TEST_ASSERT_NULL(strstr(out, "distance_mm"));
  TEST_ASSERT_NOT_NULL(strstr(out, "\"rain_tips_total\":0"));
}

// ---------------------------------------------------------------- the pradhan box

struct RelayPort : BoxPort {
  std::vector<std::pair<uint16_t, std::vector<uint8_t>>> wrapped;
  std::vector<std::pair<uint8_t, bool>> plays;
  bool radio_ok = true;
  uint32_t lora_button(uint8_t, uint8_t, uint16_t) override { return 1; }
  bool cloud_up() override { return true; }
  void sms_officers(const char*) override {}
  void level_leds(uint8_t) override {}
  void link_led(uint8_t) override {}
  void play(uint8_t role, bool chime) override { plays.push_back({role, chime}); }
  bool lora_wrapped(uint16_t dst, const uint8_t* p, uint8_t n) override {
    if (!radio_ok) return false;
    wrapped.push_back({dst, std::vector<uint8_t>(p, p + n)});
    return true;
  }
};

static std::string b64url(const uint8_t* p, size_t n) {
  char out[80];
  pkr_b64url_encode(p, n, out, sizeof out);
  return out;
}

static void test_box_shadow_level_alert_and_relay_cmd() {
  fk::Clock clock;
  fk::Sink sink;
  RelayPort port;
  BoxCore box(port, clock, sink);
  box.configure(PKR_SIM_VILLAGE, true);
  uint8_t payload[36];
  for (int i = 0; i < 36; i++) payload[i] = (uint8_t)i;
  char doc[700];
  snprintf(doc, sizeof doc,
           "{\"state\":{\"desired\":{\"level\":\"warning\",\"alert_id\":\"alr_1\",\"clip\":\"thunag.warning.hi.v1\","
           "\"relay_cmd\":{\"siren-thunag-sim\":{\"cmd_id\":\"cmd_a\",\"dst\":257,\"exp\":%u,\"payload\":\"%s\"},"
           "\"siren-thunag-02\":{\"cmd_id\":\"cmd_b\",\"dst\":259,\"exp\":%u,\"payload\":\"short\"}}}}}",
           (unsigned)(clock.now_unix + 1800), b64url(payload, 36).c_str(), (unsigned)(clock.now_unix + 1800));
  BoxShadow s;
  TEST_ASSERT_EQUAL_INT(0, parse_box_shadow(doc, strlen(doc), &s));
  TEST_ASSERT_TRUE(s.has_level);
  TEST_ASSERT_EQUAL_UINT8(PKR_LEVEL_WARNING, s.level);
  TEST_ASSERT_EQUAL_STRING("alr_1", s.alert_id);
  TEST_ASSERT_EQUAL_UINT8(CLIP_WARNING, s.clip_role);
  TEST_ASSERT_EQUAL_UINT8(1, s.n_relay);
  TEST_ASSERT_EQUAL_UINT8(1, s.bad_relay);  // a payload that is not 36 bytes is skipped
  TEST_ASSERT_EQUAL_HEX16(257, s.relay[0].dst);
  box.apply_shadow(s);
  TEST_ASSERT_EQUAL_UINT(1, port.plays.size());
  TEST_ASSERT_EQUAL_UINT(1, port.wrapped.size());
  TEST_ASSERT_EQUAL_MEMORY(payload, port.wrapped[0].second.data(), 36);
  // the same document again (a shadow get on every reconnect): no clip replayed, nothing sent twice
  box.apply_shadow(s);
  TEST_ASSERT_EQUAL_UINT(1, port.plays.size());
  TEST_ASSERT_EQUAL_UINT(1, port.wrapped.size());
  TEST_ASSERT_EQUAL_INT(RELAY_DUPLICATE, box.relay(s.relay[0]));
  // past its exp it is not sent; a radio failure is tried again next time
  RelayCmd old = s.relay[0];
  strcpy(old.cmd_id, "cmd_old");
  old.exp = clock.now_unix - 1;
  TEST_ASSERT_EQUAL_INT(RELAY_EXPIRED, box.relay(old));
  RelayCmd fresh = s.relay[0];
  strcpy(fresh.cmd_id, "cmd_c");
  port.radio_ok = false;
  TEST_ASSERT_EQUAL_INT(RELAY_FAILED, box.relay(fresh));
  port.radio_ok = true;
  TEST_ASSERT_EQUAL_INT(RELAY_SENT, box.relay(fresh));
  // button B acknowledges the alert the box shows
  box.set_button(BOX_B_ACK, true);
  for (int i = 0; i < 10; i++) {
    clock.advance(10);
    box.tick();
  }
  const Event* ack = sink.last(PKR_EVT_ACK);
  TEST_ASSERT_NOT_NULL(ack);
  TEST_ASSERT_EQUAL_STRING("alr_1", ack->alert_id);
  char json[400];
  TEST_ASSERT_GREATER_THAN(0, event_to_json(*ack, 1, 9, json, sizeof json));
  TEST_ASSERT_NOT_NULL(strstr(json, "\"type\":\"ack\""));
  TEST_ASSERT_NOT_NULL(strstr(json, "\"alert_id\":\"alr_1\""));
  // a delta that clears the alert and returns to normal
  const char* calm = "{\"state\":{\"level\":\"normal\",\"alert_id\":null,\"clip\":null}}";
  TEST_ASSERT_EQUAL_INT(0, parse_box_shadow(calm, strlen(calm), &s));
  TEST_ASSERT_TRUE(s.has_alert);
  TEST_ASSERT_EQUAL_STRING("", s.alert_id);
  TEST_ASSERT_EQUAL_UINT8(PKR_LEVEL_NORMAL, s.level);
  TEST_ASSERT_EQUAL_UINT8(CLIP_NONE, clip_role_from_name("chime"));
  TEST_ASSERT_EQUAL_UINT8(CLIP_ALL_CLEAR, clip_role_from_name("thunag.allclear.hi.v1"));
  TEST_ASSERT_EQUAL_UINT8(CLIP_TEST, clip_role_from_name("test.hi.v1"));
}

static void test_mesh_batch() {
  MeshBatch m;
  m.begin(PKR_SIM_BOX_ADDR);
  uint32_t t = 1761121800;
  auto g = fk::gauge_alarm(PKR_SIM_GAUGE, 10, t);
  auto own = fk::button(PKR_SIM_BOX, 4, t, PKR_BUTTON_SIREN, PKR_KEY_WARNING, 3200);
  TEST_ASSERT_TRUE(m.add(g.data(), g.size(), 1000));
  TEST_ASSERT_FALSE(m.add(g.data(), g.size(), 2000));      // the same (src, ctr): once
  TEST_ASSERT_FALSE(m.add(own.data(), own.size(), 2000));  // its own frames: never
  uint8_t junk[5] = {1, 2, 3, 4, 5};
  TEST_ASSERT_FALSE(m.add(junk, sizeof junk, 2000));
  TEST_ASSERT_FALSE(m.due(20000));
  TEST_ASSERT_TRUE(m.due(31000));  // the oldest waited 30 s
  char out[4096];
  size_t n = m.build(out, sizeof out);
  TEST_ASSERT_GREATER_THAN(0, n);
  char b64[100];
  pkr_b64_encode(g.data(), g.size(), b64, sizeof b64);  // standard base64: what the cloud decodes
  std::string want = std::string("{\"frames\":[\"") + b64 + "\"]}";
  TEST_ASSERT_EQUAL_STRING(want.c_str(), out);
  m.clear();
  for (uint32_t c = 100; c < 100 + MeshBatch::MAX; c++) {
    auto f = fk::gauge_alarm(PKR_SIM_GAUGE, c, t);
    m.add(f.data(), f.size(), 5000);
  }
  TEST_ASSERT_TRUE(m.due(5000));  // 30 frames: send now
  TEST_ASSERT_GREATER_THAN(0, m.build(out, sizeof out));
  TEST_ASSERT_EQUAL_UINT(0, m.build(out, 100));  // does not fit: nothing half-written is sent
}

// ---------------------------------------------------------------- box -> relay -> siren

struct Air : RadioPort {
  std::vector<std::vector<uint8_t>> tx;
  bool transmit(const uint8_t* b, size_t n) override {
    tx.push_back(std::vector<uint8_t>(b, b + n));
    return true;
  }
  size_t receive(uint8_t*, size_t) override { return 0; }
};

// The compact form of a shadow command, as the cloud puts it in the box's relay_cmd.
static std::vector<uint8_t> compact_of(const pkr_cmd_t& c) {
  pkr_wrapped_cmd_t w{};
  pkr_cmd_id48(c.id, w.cmd_id48);
  w.action = PKR_ACTION_SOUND;
  w.pattern = PKR_PATTERN_W1;
  w.level = PKR_CMDLEVEL_WARNING;
  w.cycles = (uint8_t)c.cycles;
  w.cap_on_s = (uint16_t)c.cap_on_s;
  w.exp = c.exp;
  w.ctr = c.ctr;
  uint8_t key[32];
  fk::key_of(PKR_SIM_SIREN, key);
  pkr_wrapped_sign(&w, PKR_SIM_SIREN, key, 32);
  std::vector<uint8_t> p(36);
  pkr_wrapped_encode(&w, p.data());
  return p;
}

static void test_cloud_command_box_relay_siren_once() {
  // 1. The siren has lost its cell link: the box's copy, through the relay, starts it.
  fk::SirenRig r;
  pkr_cmd_t c = fk::command("cmd_01relaytest", "W1", "warning", 501, r.clock.now_unix);
  auto payload = compact_of(c);
  auto box_frame = fk::frame(PKR_SIM_BOX, PKR_FT_SIREN_CMD_WRAPPED, PKR_SIM_SIREN_ADDR, 31, r.clock.now_unix,
                             payload.data(), 36);
  MemKv kv;
  KeyRing rk;
  rk.set_identity(PKR_SIM_RELAY, PKR_SIM_RELAY_ADDR);
  uint8_t k[32];
  fk::key_of(PKR_SIM_RELAY, k);
  rk.set_self_key(1, k);
  FrameSigner signer;
  signer.begin(&rk, &kv);
  Air air;
  LoraLink link;
  link.begin(&air, &signer, PKR_DUTY_RELAY_BUDGET_MS);
  RelayCore relay;
  relay.begin(&link, PKR_SIM_RELAY_ADDR, nullptr);
  pkr_beacon_payload_t beacon{132, 40, 90, -118};
  relay.tick(0, r.clock.now_unix, true, beacon);  // its first beacon
  TEST_ASSERT_TRUE(relay.on_rx(box_frame.data(), box_frame.size(), 10));
  relay.tick(60, r.clock.now_unix, true, beacon);
  TEST_ASSERT_EQUAL_UINT(2, air.tx.size());
  const auto& heard = air.tx[1];  // byte for byte the box's frame: the relay holds no key to change it
  TEST_ASSERT_EQUAL_INT(0, r.core.on_lora(heard.data(), heard.size()));
  TEST_ASSERT_TRUE(r.core.order().active);
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_STARTED));
  char hex[13];
  pkr_hex_encode(payload.data(), 6, hex);
  TEST_ASSERT_EQUAL_STRING(hex, r.core.order().cmd_id);
  // the link comes back and the shadow delivers the same command: accepted, not started again
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(c, PKR_VIA_MQTT));
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_STARTED));
  TEST_ASSERT_EQUAL_INT(0, r.sink.count(PKR_EVT_STOPPED));

  // 2. The other order: the shadow first, then the box's LoRa copy.
  fk::SirenRig r2;
  pkr_cmd_t c2 = fk::command("cmd_01relaytest2", "W1", "warning", 502, r2.clock.now_unix);
  TEST_ASSERT_EQUAL_INT(0, r2.core.accept_command(c2, PKR_VIA_MQTT));
  auto p2 = compact_of(c2);
  auto f2 = fk::frame(PKR_SIM_BOX, PKR_FT_SIREN_CMD_WRAPPED, PKR_SIM_SIREN_ADDR, 32, r2.clock.now_unix, p2.data(), 36);
  r2.run(2000);
  TEST_ASSERT_EQUAL_INT(0, r2.core.on_lora(f2.data(), f2.size()));
  TEST_ASSERT_EQUAL_INT(1, r2.sink.count(PKR_EVT_STARTED));
  TEST_ASSERT_EQUAL_INT(0, r2.sink.count(PKR_EVT_STOPPED));
  TEST_ASSERT_EQUAL_STRING("cmd_01relaytest2", r2.core.order().cmd_id);

  // 3. A T1 on LoRa could never be the silent test (the compact form has no volume): refused, nothing sounds.
  fk::SirenRig r3;
  pkr_wrapped_cmd_t t{};
  pkr_cmd_id48("cmd_01silenttest", t.cmd_id48);
  t.action = PKR_ACTION_TEST;
  t.pattern = PKR_PATTERN_T1;
  t.level = PKR_CMDLEVEL_TEST;
  t.cycles = 1;
  t.cap_on_s = 30;
  t.exp = r3.clock.now_unix + 1800;
  t.ctr = 503;
  uint8_t sk[32], tp[36];
  fk::key_of(PKR_SIM_SIREN, sk);
  pkr_wrapped_sign(&t, PKR_SIM_SIREN, sk, 32);
  pkr_wrapped_encode(&t, tp);
  auto tf = fk::frame(PKR_SIM_BOX, PKR_FT_SIREN_CMD_WRAPPED, PKR_SIM_SIREN_ADDR, 33, r3.clock.now_unix, tp, 36);
  TEST_ASSERT_EQUAL_INT(PKR_REASON_BAD_FORMAT, r3.core.on_lora(tf.data(), tf.size()));
  r3.run(2000);
  TEST_ASSERT_FALSE(r3.core.order().active);
  TEST_ASSERT_FALSE(r3.hal.k[K1_AMP]);
  TEST_ASSERT_FALSE(r3.hal.k[K2_HORNS]);

  // the names agree only for the same command
  TEST_ASSERT_TRUE(same_command("cmd_01relaytest", hex));
  TEST_ASSERT_TRUE(same_command(hex, "cmd_01relaytest"));
  TEST_ASSERT_FALSE(same_command("cmd_other", hex));
  TEST_ASSERT_FALSE(same_command(hex, "abcdefabcdef"));
  TEST_ASSERT_FALSE(same_command("", ""));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_burst_reduce_matches_v2);
  RUN_TEST(test_ulp_tick_math_debounce_bounce_and_wake);
  RUN_TEST(test_rain_report_per_reading);
  RUN_TEST(test_node_settings);
  RUN_TEST(test_gauge_v3_decision_with_rain);
  RUN_TEST(test_rain_node_never_alarms);
  RUN_TEST(test_box_shadow_level_alert_and_relay_cmd);
  RUN_TEST(test_mesh_batch);
  RUN_TEST(test_cloud_command_box_relay_siren_once);
  return UNITY_END();
}
