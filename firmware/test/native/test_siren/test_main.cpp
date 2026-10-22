// The siren node's state machine: the command acceptance matrix, verified sounding, priority,
// the edge-autonomy truth table, the key + 3 s hold, the pradhan box over LoRa, SMS, the silent
// test, tamper and power.
#include <string.h>
#include <unity.h>

#include "../support/fakes.h"
#include "pkr_gauge.h"
#include "pkr_sms.h"

void setUp() {}
void tearDown() {}

using namespace pkr;

static uint32_t g_ctr = 100;
static pkr_cmd_t cmd(fk::SirenRig& r, const char* pattern, const char* level, const char* src = "approval",
                     const char* action = "sound") {
  char id[32];
  snprintf(id, sizeof id, "01JBCMD%06u", (unsigned)g_ctr);
  return fk::command(id, pattern, level, ++g_ctr, r.clock.now_unix, src, action);
}

// ---------------------------------------------------------------- accepted and verified

static void test_signed_warning_sounds_and_is_verified() {
  fk::SirenRig r;
  r.cloud_ok();
  r.run(2500);  // 2 s of ambient for the microphone reference
  pkr_cmd_t c = cmd(r, "W1", "warning");
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(c, PKR_VIA_MQTT));
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_CMD_RECEIVED));
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_STARTED));
  TEST_ASSERT_EQUAL_INT(PKR_STATE_SOUNDING, r.core.state());
  TEST_ASSERT_TRUE(r.hal.k[K2_HORNS]);
  TEST_ASSERT_TRUE(r.hal.k[K1_AMP]);
  TEST_ASSERT_TRUE(r.hal.k[K4_STROBE]);
  TEST_ASSERT_EQUAL_UINT16(650, r.hal.cur_hz);
  TEST_ASSERT_TRUE(r.hal.k[K3_SIREN]);  // the electronic siren mirrors the tone
  r.run(4000);
  const Event* v = r.sink.last(PKR_EVT_VERIFIED);
  TEST_ASSERT_NOT_NULL(v);
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 3.2f, v->meas.amp_a);
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 26.0f, v->meas.spl_rise_db);
  TEST_ASSERT_EQUAL_INT(0, r.sink.count(PKR_EVT_NOT_VERIFIED));
  // the 3 s gap in "teen lambi": tone off, amp still on, K3 off
  r.run(1500);
  TEST_ASSERT_EQUAL_UINT16(0, r.hal.cur_hz);
  TEST_ASSERT_TRUE(r.hal.k[K1_AMP]);
  TEST_ASSERT_FALSE(r.hal.k[K3_SIREN]);
  TEST_ASSERT_GREATER_THAN(3, r.hal.feeds);  // the hardware max-on timers are being re-triggered
  // stop by command: everything off
  pkr_cmd_t s = cmd(r, "", "", "approval", "stop");
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(s, PKR_VIA_MQTT));
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_STOPPED));
  for (int k = 0; k < 4; k++) TEST_ASSERT_FALSE(r.hal.k[k]);
  TEST_ASSERT_EQUAL_INT(PKR_STATE_IDLE, r.core.state());
}

// ---------------------------------------------------------------- the acceptance matrix

static void expect_rejected(fk::SirenRig& r, const pkr_cmd_t& c, uint8_t reason) {
  r.sink.clear();
  TEST_ASSERT_EQUAL_INT_MESSAGE(reason, r.core.accept_command(c, PKR_VIA_MQTT), pkr_reason_name(reason));
  const Event* e = r.sink.last(PKR_EVT_REJECTED);
  TEST_ASSERT_NOT_NULL(e);
  TEST_ASSERT_EQUAL_INT(reason, e->reason);
  TEST_ASSERT_EQUAL_INT(0, r.sink.count(PKR_EVT_STARTED));
}

static void test_acceptance_matrix() {
  fk::SirenRig r;
  // tampered after signing
  pkr_cmd_t c = cmd(r, "C1", "critical");
  c.cycles = 99;
  expect_rejected(r, c, PKR_REASON_BAD_SIG);
  for (int k = 0; k < 4; k++) TEST_ASSERT_FALSE(r.hal.k[k]);
  // another device's command (signed with its own key)
  pkr_cmd_t other = fk::command("01JBOTHER", "W1", "warning", 5000, r.clock.now_unix, "approval", "sound", "siren-other-01");
  expect_rejected(r, other, PKR_REASON_BAD_SIG);  // checked as signed for this device: it is not
  // a kid this device does not hold
  pkr_cmd_t k2 = cmd(r, "W1", "warning");
  k2.kid = 2;
  expect_rejected(r, k2, PKR_REASON_WRONG_KID);
  // expired: issued an hour ago with the 30-minute window
  pkr_cmd_t old = fk::command("01JBOLD", "W1", "warning", 6000, r.clock.now_unix - 3600);
  expect_rejected(r, old, PKR_REASON_EXPIRED);
  // a drill never sounds a real pattern
  expect_rejected(r, cmd(r, "W1", "warning", "drill"), PKR_REASON_DRILL_PATTERN);
  expect_rejected(r, cmd(r, "C1", "critical", "drill"), PKR_REASON_DRILL_PATTERN);
  // a test action must be T1 or D1
  expect_rejected(r, cmd(r, "C1", "critical", "schedule", "test"), PKR_REASON_BAD_FORMAT);
  // the bridge beacon is not a siren pattern
  pkr_cmd_t b1 = cmd(r, "B1", "critical");
  expect_rejected(r, b1, PKR_REASON_BAD_FORMAT);

  // replay: the same command twice; an older ctr with a new id; a seen id with a newer ctr
  pkr_cmd_t ok = cmd(r, "W1", "warning");
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(ok, PKR_VIA_MQTT));
  expect_rejected(r, ok, PKR_REASON_REPLAYED);
  pkr_cmd_t older = fk::command("01JBNEWID", "W1", "warning", ok.ctr - 1, r.clock.now_unix);
  expect_rejected(r, older, PKR_REASON_REPLAYED);
  pkr_cmd_t same_id = fk::command(ok.id, "W1", "warning", ok.ctr + 50, r.clock.now_unix);
  expect_rejected(r, same_id, PKR_REASON_REPLAYED);
  // ... and the guard survives a reboot (persisted before acting)
  fk::SirenRig r2(false);
  r2.kv = r.kv;
  r2.start();
  expect_rejected(r2, ok, PKR_REASON_REPLAYED);
}

static void test_unsynced_clock_window() {
  fk::SirenRig r;
  r.run(100);  // the synced clock is noted as the last known time
  r.clock.is_synced = false;
  pkr_cmd_t far = fk::command("01JBFAR", "W1", "warning", 7000, r.clock.now_unix + 13 * 3600);
  expect_rejected(r, far, PKR_REASON_EXP_WINDOW);
  // the contract (siren_model) checks only the upper bound without a clock
  pkr_cmd_t near = fk::command("01JBNEAR", "W1", "warning", 7002, r.clock.now_unix + 3600);
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(near, PKR_VIA_MQTT));
}

static void test_tests_and_drills() {
  fk::SirenRig r;
  // 14:00 IST: a drill (D1) and a test (T1) are fine
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(cmd(r, "D1", "drill", "drill", "test"), PKR_VIA_MQTT));
  TEST_ASSERT_EQUAL_INT(PKR_STATE_TESTING, r.core.state());
  r.run(130000);  // a drill is over in under 2 minutes
  TEST_ASSERT_FALSE(r.core.order().active);
  TEST_ASSERT_NOT_NULL(r.sink.last(PKR_EVT_TEST_RESULT));
  TEST_ASSERT_EQUAL_INT(2, r.sink.last(PKR_EVT_TEST_RESULT)->test_kind);
  // 22:00 IST: no audible test (night)
  r.clock.now_unix = 1761150600;  // 2025-10-22T16:30:00Z
  TEST_ASSERT_EQUAL_INT(22 * 60, minutes_ist(r.clock.now_unix));
  expect_rejected(r, cmd(r, "T1", "test", "schedule", "test"), PKR_REASON_OUTSIDE_TEST_WINDOW);
  // but a Warning at night sounds: alarms have no quiet hours
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(cmd(r, "W1", "warning"), PKR_VIA_MQTT));
  // low battery: no audible tests below 50 %
  fk::SirenRig low;
  low.core.set_soc(40);
  expect_rejected(low, cmd(low, "T1", "test", "schedule", "test"), PKR_REASON_LOW_POWER);
  low.core.set_soc(10);
  TEST_ASSERT_EQUAL_INT(0, low.core.accept_command(cmd(low, "C1", "critical"), PKR_VIA_MQTT));  // alarms still sound
}

static void test_priority() {
  fk::SirenRig r;
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(cmd(r, "C1", "critical"), PKR_VIA_MQTT));
  r.run(1000);
  expect_rejected(r, cmd(r, "W1", "warning"), PKR_REASON_LOWER_PRIORITY);
  expect_rejected(r, cmd(r, "A1", "all_clear", "all_clear"), PKR_REASON_LOWER_PRIORITY);
  TEST_ASSERT_EQUAL_INT(PKR_PATTERN_C1, r.core.order().pattern);
  // an officer's stop still stops it
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(cmd(r, "", "", "approval", "stop"), PKR_VIA_MQTT));
  TEST_ASSERT_FALSE(r.core.order().active);
  // Warning first, then Critical pre-empts it
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(cmd(r, "W1", "warning"), PKR_VIA_MQTT));
  r.sink.clear();
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(cmd(r, "C1", "critical"), PKR_VIA_MQTT));
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_STOPPED));
  TEST_ASSERT_EQUAL_STRING("preempted", r.sink.last(PKR_EVT_STOPPED)->detail);
  TEST_ASSERT_EQUAL_INT(PKR_PATTERN_C1, r.core.order().pattern);
  // the spec's order, top to bottom
  TEST_ASSERT_TRUE(PKR_PRIO_CRITICAL > PKR_PRIO_AUTONOMY);
  TEST_ASSERT_TRUE(PKR_PRIO_AUTONOMY > PKR_PRIO_MANUAL_CRITICAL);
  TEST_ASSERT_TRUE(PKR_PRIO_MANUAL_CRITICAL > PKR_PRIO_WARNING);
  TEST_ASSERT_TRUE(PKR_PRIO_WARNING > PKR_PRIO_MANUAL_WARNING);
  TEST_ASSERT_TRUE(PKR_PRIO_MANUAL_WARNING > PKR_PRIO_ALL_CLEAR);
  TEST_ASSERT_TRUE(PKR_PRIO_ALL_CLEAR > PKR_PRIO_DRILL);
  TEST_ASSERT_TRUE(PKR_PRIO_DRILL > PKR_PRIO_TEST);
}

static void test_expiry_while_sounding_stops() {
  fk::SirenRig r;
  pkr_cmd_t c = cmd(r, "W1", "warning");
  c.exp = r.clock.now_unix + 60;
  uint8_t key[32];
  fk::key_of(PKR_SIM_SIREN, key);
  pkr_cmd_sign(&c, key, 32);
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(c, PKR_VIA_MQTT));
  r.run(62000);
  TEST_ASSERT_FALSE(r.core.order().active);
  TEST_ASSERT_EQUAL_STRING("expired", r.sink.last(PKR_EVT_FINISHED)->detail);
}

// ---------------------------------------------------------------- verification

static void test_failed_check_tries_the_fallback_and_never_silences() {
  // the DFPlayer is silent: the LEDC fallback tone works
  fk::SirenRig r;
  r.hal.amp_dead_until_fallback = true;
  r.run(2500);
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(cmd(r, "C1", "critical"), PKR_VIA_MQTT));
  r.run(10000);
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_NOT_VERIFIED));
  TEST_ASSERT_TRUE(r.hal.fallback);
  const Event* v = r.sink.last(PKR_EVT_VERIFIED);
  TEST_ASSERT_NOT_NULL(v);
  TEST_ASSERT_TRUE(v->fallback);
  TEST_ASSERT_EQUAL_UINT16(0, r.core.faults() & FAULT_AMP);

  // the amplifier is dead: FAULT, but the horns and the K3 siren stay on
  fk::SirenRig d;
  d.hal.amp = 0.4f;
  d.run(2500);
  TEST_ASSERT_EQUAL_INT(0, d.core.accept_command(cmd(d, "C1", "critical"), PKR_VIA_MQTT));
  d.run(10000);
  TEST_ASSERT_EQUAL_INT(2, d.sink.count(PKR_EVT_NOT_VERIFIED));
  TEST_ASSERT_EQUAL_STRING("amp_current", d.sink.last(PKR_EVT_NOT_VERIFIED)->detail);
  TEST_ASSERT_TRUE(d.core.faults() & FAULT_AMP);
  TEST_ASSERT_TRUE(d.core.order().active);
  TEST_ASSERT_TRUE(d.hal.k[K2_HORNS]);
  TEST_ASSERT_TRUE(d.hal.k[K1_AMP]);
  TEST_ASSERT_TRUE(d.hal.k[K3_SIREN]);

  // a dead microphone: verified on current alone, and reported
  fk::SirenRig m;
  m.hal.mic_is_dead = true;
  m.hal.mic_loud = m.hal.mic_quiet;
  m.run(2500);
  TEST_ASSERT_EQUAL_INT(0, m.core.accept_command(cmd(m, "W1", "warning"), PKR_VIA_MQTT));
  m.run(6000);
  TEST_ASSERT_NOT_NULL(m.sink.last(PKR_EVT_VERIFIED));
  TEST_ASSERT_TRUE(m.core.faults() & FAULT_MIC_DEAD);

  // current fine but no sound rise (a horn cable cut after the amp): not verified
  fk::SirenRig q;
  q.hal.mic_loud = q.hal.mic_quiet + 3;
  q.run(2500);
  TEST_ASSERT_EQUAL_INT(0, q.core.accept_command(cmd(q, "W1", "warning"), PKR_VIA_MQTT));
  q.run(12000);
  TEST_ASSERT_EQUAL_STRING("no_spl_rise", q.sink.last(PKR_EVT_NOT_VERIFIED)->detail);
}

// ---------------------------------------------------------------- edge autonomy (section 7.4)

enum Cloud { NEVER, RECENT, SILENT };

static void autonomy_case(bool enabled, bool shadow, bool fast, Cloud cloud) {
  fk::SirenRig r(false);
  r.cfg.autonomy.enabled = enabled;
  r.cfg.autonomy.shadow_mode = shadow;
  r.cfg.autonomy.fast_path = fast;
  r.start();
  if (cloud != NEVER) r.cloud_ok();
  r.clock.advance(cloud == SILENT ? 601000 : 30000);
  r.core.tick();
  bool silent = cloud != RECENT;
  TEST_ASSERT_EQUAL(silent, r.core.cloud_silent());
  auto f = fk::gauge_alarm(PKR_SIM_GAUGE, 50, r.clock.now_unix);
  TEST_ASSERT_EQUAL_INT(0, r.core.on_lora(f.data(), f.size()));
  bool should_sound = enabled && !shadow && (silent || fast);
  char msg[96];
  snprintf(msg, sizeof msg, "enabled=%d shadow=%d fast=%d cloud=%d", enabled, shadow, fast, (int)cloud);
  TEST_ASSERT_EQUAL_MESSAGE(should_sound, r.core.order().active, msg);
  if (should_sound) {
    TEST_ASSERT_EQUAL_INT_MESSAGE(PKR_STATE_AUTONOMOUS, r.core.state(), msg);
    TEST_ASSERT_EQUAL_INT(PKR_PATTERN_C1, r.core.order().pattern);
    TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_AUTONOMOUS_TRIGGER));
    TEST_ASSERT_EQUAL_UINT(1, r.sms.sent.size());
    TEST_ASSERT_EQUAL_STRING("<officers>", r.sms.sent[0].first.c_str());
    TEST_ASSERT_EQUAL_STRING_LEN("PKR AUTO C thunag gauge-janjehli-sim 312cm ", r.sms.sent[0].second.c_str(), 43);
  } else {
    TEST_ASSERT_EQUAL_INT_MESSAGE(1, r.sink.count(PKR_EVT_GAUGE_ALARM_HEARD), msg);
    TEST_ASSERT_EQUAL_INT(0, r.sink.count(PKR_EVT_AUTONOMOUS_TRIGGER));
    TEST_ASSERT_TRUE(r.sms.sent.empty());
    for (int k = 0; k < 4; k++) TEST_ASSERT_FALSE(r.hal.k[k]);
    const Event* h = r.sink.last(PKR_EVT_GAUGE_ALARM_HEARD);
    if (enabled && shadow)
      TEST_ASSERT_EQUAL_INT_MESSAGE((silent || fast) ? 1 : 0, h->would_sound, msg);  // logged, never sounded
    else
      TEST_ASSERT_EQUAL_INT(-1, h->would_sound);
  }
}

static void test_edge_autonomy_truth_table() {
  for (int en = 0; en < 2; en++)
    for (int sh = 0; sh < 2; sh++)
      for (int fp = 0; fp < 2; fp++)
        for (int cl = 0; cl < 3; cl++) autonomy_case(en, sh, fp, (Cloud)cl);
}

static void test_autonomy_only_from_upstream_critical_signed_fresh() {
  fk::SirenRig r;  // enabled, not shadow, cloud never seen (silent)
  // a GAUGE_STATUS is not an alarm
  auto st = fk::gauge_alarm(PKR_SIM_GAUGE, 10, r.clock.now_unix, 312, PKR_LEVEL_CRITICAL, PKR_FT_GAUGE_STATUS);
  r.core.on_lora(st.data(), st.size());
  TEST_ASSERT_FALSE(r.core.order().active);
  // a GAUGE_ALARM that says Warning is heard, not sounded
  auto warn = fk::gauge_alarm(PKR_SIM_GAUGE, 11, r.clock.now_unix, 250, PKR_LEVEL_WARNING);
  r.core.on_lora(warn.data(), warn.size());
  TEST_ASSERT_FALSE(r.core.order().active);
  // a gauge that is a trusted sender but not this siren's upstream
  r.keys.add_sender(fk::sender("gauge-other-01", ROLE_GAUGE_ALARM));
  auto other = fk::gauge_alarm("gauge-other-01", 1, r.clock.now_unix);
  r.core.on_lora(other.data(), other.size());
  TEST_ASSERT_FALSE(r.core.order().active);
  // a forged frame
  auto forged = fk::gauge_alarm(PKR_SIM_GAUGE, 12, r.clock.now_unix);
  forged[20] ^= 4;
  TEST_ASSERT_EQUAL_INT(PKR_REASON_BAD_MAC, r.core.on_lora(forged.data(), forged.size()));
  TEST_ASSERT_FALSE(r.core.order().active);
  // a replay of a frame already heard
  r.core.on_lora(warn.data(), warn.size());
  TEST_ASSERT_FALSE(r.core.order().active);
  // the real thing
  auto ok = fk::gauge_alarm(PKR_SIM_GAUGE, 13, r.clock.now_unix);
  TEST_ASSERT_EQUAL_INT(0, r.core.on_lora(ok.data(), ok.size()));
  TEST_ASSERT_EQUAL_INT(PKR_STATE_AUTONOMOUS, r.core.state());
}

static void test_autonomy_rearm_quiet_stop_and_preemption() {
  fk::SirenRig r;
  auto f = fk::gauge_alarm(PKR_SIM_GAUGE, 1, r.clock.now_unix);
  r.core.on_lora(f.data(), f.size());
  TEST_ASSERT_TRUE(r.core.order().autonomous);
  // GAUGE_ALARM every 5 minutes keeps it armed past 15 minutes
  for (uint32_t i = 2; i <= 5; i++) {
    r.run(300000);
    auto g = fk::gauge_alarm(PKR_SIM_GAUGE, i, r.clock.now_unix);
    r.core.on_lora(g.data(), g.size());
    TEST_ASSERT_TRUE(r.core.order().autonomous);
  }
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_AUTONOMOUS_TRIGGER));  // re-armed, not restarted
  // the gauge goes quiet: stop 15 minutes after the last alarm
  r.run(899000);
  TEST_ASSERT_TRUE(r.core.order().active);
  r.run(2000);
  TEST_ASSERT_FALSE(r.core.order().active);
  TEST_ASSERT_EQUAL_STRING("no_gauge_alarm_15min", r.sink.last(PKR_EVT_FINISHED)->detail);

  // an approved Critical takes over from autonomy; an approved Warning does not
  fk::SirenRig p;
  auto a = fk::gauge_alarm(PKR_SIM_GAUGE, 1, p.clock.now_unix);
  p.core.on_lora(a.data(), a.size());
  expect_rejected(p, cmd(p, "W1", "warning"), PKR_REASON_LOWER_PRIORITY);
  TEST_ASSERT_EQUAL_INT(0, p.core.accept_command(cmd(p, "C1", "critical"), PKR_VIA_MQTT));
  TEST_ASSERT_FALSE(p.core.order().autonomous);
}

// A flood cuts the power: the siren reboots and must sound on its gauge's very next GAUGE_ALARM.
static void test_reboot_then_the_next_gauge_alarm_sounds() {
  fk::SirenRig r;  // autonomy on, no cloud contact (silent)
  uint32_t ctr = 0;
  for (int i = 0; i < 3; i++) {  // the gauge was alarming before the power cut
    auto f = fk::gauge_alarm(PKR_SIM_GAUGE, ++ctr, r.clock.now_unix);
    TEST_ASSERT_EQUAL_INT(0, r.core.on_lora(f.data(), f.size()));
  }
  TEST_ASSERT_TRUE(r.core.order().autonomous);
  auto last = fk::gauge_alarm(PKR_SIM_GAUGE, ctr, r.clock.now_unix);
  // reboot: a new core on the same NVS, everything else lost
  fk::SirenRig b(false);
  b.kv = r.kv;
  b.clock = r.clock;
  b.start();
  TEST_ASSERT_FALSE(b.core.order().active);
  TEST_ASSERT_EQUAL_INT(PKR_REASON_REPLAYED, b.core.on_lora(last.data(), last.size()));  // a replay
  TEST_ASSERT_FALSE(b.core.order().active);
  auto next = fk::gauge_alarm(PKR_SIM_GAUGE, ctr + 1, b.clock.now_unix);
  TEST_ASSERT_EQUAL_INT(0, b.core.on_lora(next.data(), next.size()));  // accepted at once, no +16 gap
  TEST_ASSERT_EQUAL_INT(PKR_STATE_AUTONOMOUS, b.core.state());
  TEST_ASSERT_TRUE(b.hal.k[K2_HORNS]);
  TEST_ASSERT_EQUAL_INT(PKR_REASON_REPLAYED, b.core.on_lora(next.data(), next.size()));
  // commands are restored exactly too: the next shadow command after a reboot is accepted
  pkr_cmd_t c1 = cmd(b, "C1", "critical");
  TEST_ASSERT_EQUAL_INT(0, b.core.accept_command(c1, PKR_VIA_MQTT));
  fk::SirenRig c(false);
  c.kv = b.kv;
  c.start();
  expect_rejected(c, c1, PKR_REASON_REPLAYED);
  pkr_cmd_t c2 = fk::command("01JBAFTER", "C1", "critical", c1.ctr + 1, c.clock.now_unix);
  TEST_ASSERT_EQUAL_INT(0, c.core.accept_command(c2, PKR_VIA_MQTT));
}

static void test_autonomy_cap_is_30_minutes_of_sound() {
  fk::SirenRig r;
  uint32_t ctr = 1;
  auto f = fk::gauge_alarm(PKR_SIM_GAUGE, ctr++, r.clock.now_unix);
  r.core.on_lora(f.data(), f.size());
  for (int i = 0; i < 20 && r.core.order().active; i++) {  // keep the gauge alarming
    r.run(240000);
    auto g = fk::gauge_alarm(PKR_SIM_GAUGE, ctr++, r.clock.now_unix);
    r.core.on_lora(g.data(), g.size());
  }
  TEST_ASSERT_LESS_OR_EQUAL_UINT32(1800u * 1000u + 40, r.core.player().sound_on_ms());
  const Event* fin = r.sink.last(PKR_EVT_FINISHED);
  TEST_ASSERT_NOT_NULL(fin);
  TEST_ASSERT_EQUAL_STRING("cap", fin->detail);  // then a cloud or human decision
}

static void test_gauge_logic_to_siren_end_to_end() {
  fk::SirenRig r;
  pkr_gauge_cfg_t cfg{150, 250, 300, 300, 280, 150, 40000, 10, 2};
  pkr_gauge_state_t st;
  pkr_gauge_state_init(&st);
  pkr_gauge_decision_t d;
  uint32_t now = r.clock.now_unix, ctr = 0;
  float stages[] = {120, 130, 305, 280, 310};
  bool sent[5];
  for (int i = 0; i < 5; i++) {
    pkr_gauge_reading_t rd{stages[i], 2000, 0, 1, now + i * 60u, 0};
    pkr_gauge_step(&st, &cfg, &rd, &d);
    sent[i] = d.send_alarm;
    if (d.send_alarm) {
      auto f = fk::gauge_alarm(PKR_SIM_GAUGE, ++ctr, r.clock.now_unix, (int16_t)stages[i]);
      r.core.on_lora(f.data(), f.size());
    }
  }
  // 305 alone is one of three; 305 + 310 (with 280 between) is two of three
  TEST_ASSERT_FALSE(sent[2]);
  TEST_ASSERT_FALSE(sent[3]);
  TEST_ASSERT_TRUE(sent[4]);
  TEST_ASSERT_EQUAL_INT(PKR_STATE_AUTONOMOUS, r.core.state());
}

// ---------------------------------------------------------------- manual: key + 3 s hold

static void test_key_and_three_second_hold() {
  fk::SirenRig r;
  r.core.set_key(PKR_KEY_CRITICAL);
  r.core.set_hold(true);
  r.run(2000);  // a 2 s hold does nothing
  r.core.set_hold(false);
  r.run(100);
  TEST_ASSERT_FALSE(r.core.order().active);
  TEST_ASSERT_EQUAL_INT(0, r.sink.count(PKR_EVT_MANUAL_TRIGGER));
  // HOLD without the key does nothing
  r.core.set_key(PKR_KEY_OFF);
  r.core.set_hold(true);
  r.run(4000);
  r.core.set_hold(false);
  TEST_ASSERT_FALSE(r.core.order().active);
  // key at C, hold 3 s: manual Critical
  r.core.set_key(PKR_KEY_CRITICAL);
  r.core.set_hold(true);
  r.run(3100);
  TEST_ASSERT_TRUE(r.core.order().active);
  TEST_ASSERT_EQUAL_INT(PKR_STATE_MANUAL, r.core.state());
  TEST_ASSERT_EQUAL_INT(PKR_PATTERN_C1, r.core.order().pattern);
  const Event* m = r.sink.last(PKR_EVT_MANUAL_TRIGGER);
  TEST_ASSERT_NOT_NULL(m);
  TEST_ASSERT_EQUAL_INT(PKR_SRC_KEY_SWITCH, m->src);
  TEST_ASSERT_EQUAL_STRING("key_critical", m->button);
  TEST_ASSERT_EQUAL_STRING("critical", m->level);
  r.core.set_hold(false);
  // key off stops the node's own manual sound
  r.core.set_key(PKR_KEY_OFF);
  TEST_ASSERT_FALSE(r.core.order().active);
  TEST_ASSERT_EQUAL_STRING("key_off", r.sink.last(PKR_EVT_STOPPED)->detail);
}

static void test_manual_stops_itself_after_10_minutes_and_is_rate_limited() {
  fk::SirenRig r;
  r.core.set_key(PKR_KEY_WARNING);
  for (int i = 0; i < 3; i++) {
    r.core.set_hold(true);
    r.run(3100);
    r.core.set_hold(false);
    TEST_ASSERT_TRUE(r.core.order().active);
    r.run(600000);
    TEST_ASSERT_FALSE(r.core.order().active);
  }
  TEST_ASSERT_EQUAL_STRING("manual_cap", r.sink.last(PKR_EVT_FINISHED)->detail);
  TEST_ASSERT_EQUAL_INT(3, r.sink.count(PKR_EVT_MANUAL_TRIGGER));
  // a fourth within the hour is refused
  r.core.set_hold(true);
  r.run(3100);
  r.core.set_hold(false);
  TEST_ASSERT_FALSE(r.core.order().active);
  TEST_ASSERT_EQUAL_INT(PKR_REASON_RATE_LIMITED, r.sink.last(PKR_EVT_REJECTED)->reason);
}

// ---------------------------------------------------------------- the pradhan box over LoRa

static void test_box_button_frame() {
  fk::SirenRig r;
  uint32_t t = r.clock.now_unix;
  auto shortf = fk::button(PKR_SIM_BOX, 1, t, PKR_BUTTON_SIREN, PKR_KEY_CRITICAL, 2000);
  TEST_ASSERT_EQUAL_INT(0, r.core.on_lora(shortf.data(), shortf.size()));
  TEST_ASSERT_FALSE(r.core.order().active);  // under 3 s
  TEST_ASSERT_EQUAL_UINT(1, r.lora.sent.size());  // but heard, so ACKed
  auto f = fk::button(PKR_SIM_BOX, 2, t, PKR_BUTTON_SIREN, PKR_KEY_CRITICAL, 3200);
  TEST_ASSERT_EQUAL_INT(0, r.core.on_lora(f.data(), f.size()));
  TEST_ASSERT_TRUE(r.core.order().active);
  TEST_ASSERT_EQUAL_INT(PKR_SRC_PRADHAN_BOX, r.core.order().src);
  const Event* m = r.sink.last(PKR_EVT_MANUAL_TRIGGER);
  TEST_ASSERT_EQUAL_STRING(PKR_SIM_BOX, m->frame_src);
  TEST_ASSERT_EQUAL_INT(1, m->lora_acked);  // this siren heard the box
  // the ACK goes back to the box with the ctr it acknowledges
  auto& ack = r.lora.sent.back();
  TEST_ASSERT_EQUAL_HEX8(PKR_FT_ACK, ack.type);
  TEST_ASSERT_EQUAL_HEX16(PKR_SIM_BOX_ADDR, ack.dst);
  pkr_ack_payload_t a;
  pkr_ack_payload_decode(ack.payload.data(), &a);
  TEST_ASSERT_EQUAL_UINT32(2, a.acked_ctr);
  // the same box's stop button
  auto stop = fk::button(PKR_SIM_BOX, 3, t, PKR_BUTTON_STOP, PKR_KEY_OFF, 0);
  r.core.on_lora(stop.data(), stop.size());
  TEST_ASSERT_FALSE(r.core.order().active);
  // a box's button cannot stop an officer-approved alarm
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(cmd(r, "W1", "warning"), PKR_VIA_MQTT));
  auto stop2 = fk::button(PKR_SIM_BOX, 4, t, PKR_BUTTON_STOP, PKR_KEY_OFF, 0);
  r.core.on_lora(stop2.data(), stop2.size());
  TEST_ASSERT_TRUE(r.core.order().active);
}

static std::vector<uint8_t> wrapped(fk::SirenRig& r, const char* forwarder, const char* signer, uint8_t pattern, uint8_t level,
                                    uint32_t ctr, uint32_t fctr) {
  uint8_t key[32];
  fk::key_of(signer, key);
  pkr_wrapped_cmd_t w{};
  pkr_cmd_id48("01JBWRAP", w.cmd_id48);
  w.action = PKR_ACTION_SOUND;
  w.pattern = pattern;
  w.level = level;
  w.cycles = 5;
  w.cap_on_s = 1200;
  w.exp = r.clock.now_unix + 1800;
  w.ctr = ctr;
  pkr_wrapped_sign(&w, PKR_SIM_SIREN, key, 32);
  uint8_t p[36];
  pkr_wrapped_encode(&w, p);
  return fk::frame(forwarder, PKR_FT_SIREN_CMD_WRAPPED, PKR_SIM_SIREN_ADDR, fctr, r.clock.now_unix, p, 36);
}

static void test_lora_wrapped_command() {
  fk::SirenRig r;
  // a box forwards the cloud's command, but cannot forge one: the inner MAC is the siren's key
  auto forged = wrapped(r, PKR_SIM_BOX, PKR_SIM_BOX, PKR_PATTERN_C1, PKR_CMDLEVEL_CRITICAL, 900, 1);
  TEST_ASSERT_EQUAL_INT(PKR_REASON_BAD_SIG, r.core.on_lora(forged.data(), forged.size()));
  TEST_ASSERT_FALSE(r.core.order().active);
  auto ok = wrapped(r, PKR_SIM_BOX, PKR_SIM_SIREN, PKR_PATTERN_W1, PKR_CMDLEVEL_WARNING, 900, 2);
  TEST_ASSERT_EQUAL_INT(0, r.core.on_lora(ok.data(), ok.size()));
  TEST_ASSERT_TRUE(r.core.order().active);
  TEST_ASSERT_EQUAL_INT(PKR_VIA_LORA, r.core.order().via);
  // the same command again through the gauge: replayed on the LoRa path
  auto again = wrapped(r, PKR_SIM_GAUGE, PKR_SIM_SIREN, PKR_PATTERN_W1, PKR_CMDLEVEL_WARNING, 900, 1);
  TEST_ASSERT_EQUAL_INT(PKR_REASON_REPLAYED, r.core.on_lora(again.data(), again.size()));
  // each path keeps its own counter (siren_model: mqtt, sms, lora): the shadow is not blocked by LoRa
  pkr_cmd_t c = fk::command("01JBSHADOW", "W1", "warning", 900, r.clock.now_unix);
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(c, PKR_VIA_MQTT));
  TEST_ASSERT_EQUAL_UINT32(900, r.core.guard().last_ctr(GUARD_LORA));
  TEST_ASSERT_EQUAL_UINT32(900, r.core.guard().last_ctr(GUARD_MQTT));
}

// ---------------------------------------------------------------- SMS

static std::string sms_text(uint8_t action, char level, uint32_t ctr, uint32_t exp, const char* signer = PKR_SIM_SIREN) {
  uint8_t key[32];
  fk::key_of(signer, key);
  pkr_sms_t s{};
  strcpy(s.device, PKR_SIM_SIREN);
  s.action = pkr_sms_letter_from_action(action);
  s.level = level;
  s.ctr = ctr;
  s.exp = exp;
  char t[170];
  pkr_sms_format(&s, key, 32, t, sizeof t);
  return t;
}

static void test_sms_fallback() {
  fk::SirenRig r;
  r.run(2500);
  uint32_t exp = r.clock.now_unix + 1800;
  // a stranger: refused without a reply (no SMS spent on strangers)
  std::string t = sms_text(PKR_ACTION_SOUND, 'C', 10, exp);
  TEST_ASSERT_EQUAL_INT(PKR_REASON_SENDER, r.core.on_sms("+919999999999", t.data(), t.size()));
  TEST_ASSERT_TRUE(r.sms.sent.empty());
  // wrong key: refused with a reply
  std::string bad = sms_text(PKR_ACTION_SOUND, 'C', 11, exp, "siren-other-01");
  TEST_ASSERT_EQUAL_INT(PKR_REASON_BAD_SIG, r.core.on_sms(PKR_SIM_OFFICER_E164, bad.data(), bad.size()));
  TEST_ASSERT_EQUAL_STRING("PUKAAR REJECT bad_sig", r.sms.sent.back().second.c_str());
  // the officer's signed SMS: sounds, and the reply carries the verification
  TEST_ASSERT_EQUAL_INT(0, r.core.on_sms(PKR_SIM_OFFICER_E164, t.data(), t.size()));
  TEST_ASSERT_EQUAL_INT(PKR_VIA_SMS, r.core.order().via);
  r.run(6000);
  TEST_ASSERT_EQUAL_STRING(PKR_SIM_OFFICER_E164, r.sms.sent.back().first.c_str());
  TEST_ASSERT_EQUAL_STRING("PUKAAR OK SC siren-thunag-sim 14:00 3.2A +26dB", r.sms.sent.back().second.c_str());
  // a replayed SMS
  TEST_ASSERT_EQUAL_INT(PKR_REASON_REPLAYED, r.core.on_sms(PKR_SIM_OFFICER_E164, t.data(), t.size()));
  TEST_ASSERT_EQUAL_STRING("PUKAAR REJECT replayed", r.sms.sent.back().second.c_str());
  // SMS keeps its own counter: a shadow command with a far higher ctr does not block it
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(fk::command("01JBHIGH", "C1", "critical", 99999, r.clock.now_unix),
                                                 PKR_VIA_MQTT));
  std::string stop = sms_text(PKR_ACTION_STOP, 'C', 12, exp);
  TEST_ASSERT_EQUAL_INT(0, r.core.on_sms(PKR_SIM_OFFICER_E164, stop.data(), stop.size()));
  TEST_ASSERT_FALSE(r.core.order().active);
  // garbage from an allowed number gets a format reply
  TEST_ASSERT_EQUAL_INT(PKR_REASON_MALFORMED, r.core.on_sms(PKR_SIM_OFFICER_E164, "hello", 5));
  TEST_ASSERT_EQUAL_STRING("PUKAAR REJECT malformed", r.sms.sent.back().second.c_str());
}

// ---------------------------------------------------------------- silent test, tamper, power

struct K2Watch : fk::Hal {
  bool horns_during_test = false;
  pkr::SirenCore* core = nullptr;
  void relay(uint8_t r, bool on) override {
    fk::Hal::relay(r, on);
    if (core && core->testing() && k[K2_HORNS]) horns_during_test = true;
  }
};

static void test_silent_test_is_never_audible() {
  fk::SirenRig r;
  r.core.run_silent_test();
  TEST_ASSERT_TRUE(r.core.testing());
  TEST_ASSERT_FALSE(r.hal.k[K2_HORNS]);  // into the dummy load
  TEST_ASSERT_TRUE(r.hal.k[K1_AMP]);
  TEST_ASSERT_FALSE(r.hal.k[K3_SIREN]);
  TEST_ASSERT_EQUAL_UINT8(30, r.hal.cur_vol);
  for (int i = 0; i < 200 && r.core.testing(); i++) {
    r.run(20);
    TEST_ASSERT_FALSE(r.hal.k[K2_HORNS]);
    TEST_ASSERT_FALSE(r.hal.k[K3_SIREN]);
  }
  const Event* t = r.sink.last(PKR_EVT_TEST_RESULT);
  TEST_ASSERT_NOT_NULL(t);
  TEST_ASSERT_EQUAL_INT(1, t->test_kind);
  TEST_ASSERT_EQUAL_INT(1, t->ok);
  for (int k = 0; k < 4; k++) TEST_ASSERT_FALSE(r.hal.k[k]);

  // INA226 reads nothing on the amp rail: the test fails, and says why
  fk::SirenRig f;
  f.hal.amp_test = 0.05f;
  f.hal.self_faults = FAULT_DFPLAYER;
  f.core.run_silent_test();
  f.run(4000);
  t = f.sink.last(PKR_EVT_TEST_RESULT);
  TEST_ASSERT_EQUAL_INT(0, t->ok);
  TEST_ASSERT_NOT_NULL(strstr(t->detail, "amp=bad"));
  TEST_ASSERT_NOT_NULL(strstr(t->detail, "dfplayer"));
  TEST_ASSERT_TRUE(f.core.faults() & FAULT_AMP);
  TEST_ASSERT_EQUAL_INT(PKR_STATE_FAULT, f.core.state());
  // FAULT still accepts commands
  TEST_ASSERT_EQUAL_INT(0, f.core.accept_command(cmd(f, "C1", "critical"), PKR_VIA_MQTT));

  // a command during the silent test pre-empts it
  fk::SirenRig p;
  p.core.run_silent_test();
  p.run(1000);
  TEST_ASSERT_EQUAL_INT(0, p.core.accept_command(cmd(p, "W1", "warning"), PKR_VIA_MQTT));
  TEST_ASSERT_EQUAL_STRING("preempted", p.sink.last(PKR_EVT_TEST_RESULT)->detail);
  TEST_ASSERT_TRUE(p.hal.k[K2_HORNS]);
}

// DESIGN-S: a silent test is the command T1 at volume 0. Into the dummy load, at any hour.
static void test_silent_test_by_command() {
  fk::SirenRig r;
  r.clock.now_unix = 1761150600;  // 22:00 IST: an audible test would be refused
  pkr_cmd_t c = cmd(r, "T1", "test", "officer_manual", "test");
  c.volume = 0;
  uint8_t key[32];
  fk::key_of(PKR_SIM_SIREN, key);
  pkr_cmd_sign(&c, key, 32);
  TEST_ASSERT_EQUAL_INT(0, r.core.accept_command(c, PKR_VIA_MQTT));
  TEST_ASSERT_TRUE(r.core.testing());
  TEST_ASSERT_EQUAL_INT(PKR_STATE_TESTING, r.core.state());
  for (int i = 0; i < 200 && r.core.testing(); i++) {
    r.run(20);
    TEST_ASSERT_FALSE(r.hal.k[K2_HORNS]);  // never the horns
  }
  const Event* t = r.sink.last(PKR_EVT_TEST_RESULT);
  TEST_ASSERT_NOT_NULL(t);
  TEST_ASSERT_EQUAL_STRING(c.id, t->cmd_id);  // the cloud matches it to the command
  TEST_ASSERT_EQUAL_INT(1, t->test_kind);
  TEST_ASSERT_EQUAL_INT(1, t->ok);
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_CMD_RECEIVED));
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_STARTED));
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_FINISHED));
  // an audible test (T1 at 50 %) at the same hour is refused
  expect_rejected(r, cmd(r, "T1", "test", "officer_manual", "test"), PKR_REASON_OUTSIDE_TEST_WINDOW);
}

static void test_tamper_and_power_tiers() {
  fk::SirenRig r;
  r.core.set_door(true);
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_TAMPER));
  r.core.set_door(true);
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_TAMPER));  // once per opening
  TEST_ASSERT_TRUE(r.core.faults() & FAULT_TAMPER);
  r.core.set_door(false);
  TEST_ASSERT_FALSE(r.core.faults() & FAULT_TAMPER);
  r.core.set_soc(45);
  TEST_ASSERT_EQUAL_INT(PKR_TIER_NO_AUDIBLE_TESTS, r.core.tier());
  r.core.set_soc(20);
  TEST_ASSERT_EQUAL_INT(PKR_TIER_ALARM_RESERVE, r.core.tier());
  r.core.set_soc(10);
  TEST_ASSERT_EQUAL_INT(PKR_TIER_ALARM_ONLY, r.core.tier());
  TEST_ASSERT_EQUAL_INT(PKR_STATE_LOW_POWER, r.core.state());
  TEST_ASSERT_EQUAL_INT(3, r.sink.count(PKR_EVT_POWER));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_signed_warning_sounds_and_is_verified);
  RUN_TEST(test_acceptance_matrix);
  RUN_TEST(test_unsynced_clock_window);
  RUN_TEST(test_tests_and_drills);
  RUN_TEST(test_priority);
  RUN_TEST(test_expiry_while_sounding_stops);
  RUN_TEST(test_failed_check_tries_the_fallback_and_never_silences);
  RUN_TEST(test_edge_autonomy_truth_table);
  RUN_TEST(test_autonomy_only_from_upstream_critical_signed_fresh);
  RUN_TEST(test_autonomy_rearm_quiet_stop_and_preemption);
  RUN_TEST(test_reboot_then_the_next_gauge_alarm_sounds);
  RUN_TEST(test_autonomy_cap_is_30_minutes_of_sound);
  RUN_TEST(test_gauge_logic_to_siren_end_to_end);
  RUN_TEST(test_key_and_three_second_hold);
  RUN_TEST(test_manual_stops_itself_after_10_minutes_and_is_rate_limited);
  RUN_TEST(test_box_button_frame);
  RUN_TEST(test_lora_wrapped_command);
  RUN_TEST(test_sms_fallback);
  RUN_TEST(test_silent_test_is_never_audible);
  RUN_TEST(test_silent_test_by_command);
  RUN_TEST(test_tamper_and_power_tiers);
  return UNITY_END();
}
