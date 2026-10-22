// Pradhan box (key + 3 s hold, ACK retries, SMS fallback, link LED), the LoRa relay (dedupe,
// backoff, budget, beacon), the OTA job gate, and the JSON the devices publish and read.
#include <string.h>
#include <unity.h>

#include "../support/fakes.h"
#include "pkr_lora.h"

void setUp() {}
void tearDown() {}

using namespace pkr;

struct Port : BoxPort {
  struct Btn { uint8_t button, key; uint16_t hold; };
  std::vector<Btn> frames;
  uint32_t next_ctr = 40;
  bool cloud = false;
  std::vector<std::string> sms;
  uint8_t leds = 255, link = 255;
  std::vector<std::pair<uint8_t, bool>> plays;
  uint32_t lora_button(uint8_t b, uint8_t k, uint16_t h) override {
    frames.push_back({b, k, h});
    return ++next_ctr;
  }
  bool cloud_up() override { return cloud; }
  void sms_officers(const char* t) override { sms.push_back(t); }
  void level_leds(uint8_t l) override { leds = l; }
  void link_led(uint8_t c) override { link = c; }
  void play(uint8_t role, bool chime) override { plays.push_back({role, chime}); }
};

struct BoxRig {
  fk::Clock clock;
  fk::Sink sink;
  Port port;
  BoxCore box{port, clock, sink};
  BoxRig() { box.configure(PKR_SIM_VILLAGE, true); }
  void run(uint32_t ms) {
    for (uint32_t t = 0; t < ms; t += 10) {
      clock.advance(10);
      box.tick();
    }
  }
};

static void test_box_hold_logic() {
  BoxRig r;
  r.box.set_key(PKR_KEY_CRITICAL);
  r.box.set_button(BOX_C_HOLD, true);
  r.run(2900);
  r.box.set_button(BOX_C_HOLD, false);
  r.run(100);
  TEST_ASSERT_TRUE(r.port.frames.empty());  // under 3 s: nothing
  r.box.set_key(PKR_KEY_OFF);
  r.box.set_button(BOX_C_HOLD, true);
  r.run(5000);
  r.box.set_button(BOX_C_HOLD, false);
  r.run(100);
  TEST_ASSERT_TRUE(r.port.frames.empty());  // no key: nothing
  // the key turned mid-hold restarts the 3 s
  r.box.set_key(PKR_KEY_WARNING);
  r.box.set_button(BOX_C_HOLD, true);
  r.run(2000);
  r.box.set_key(PKR_KEY_CRITICAL);
  r.run(2000);
  TEST_ASSERT_TRUE(r.port.frames.empty());
  r.run(1100);
  TEST_ASSERT_EQUAL_UINT(1, r.port.frames.size());
  TEST_ASSERT_EQUAL_UINT8(PKR_BUTTON_SIREN, r.port.frames[0].button);
  TEST_ASSERT_EQUAL_UINT8(PKR_KEY_CRITICAL, r.port.frames[0].key);
  TEST_ASSERT_GREATER_OR_EQUAL_UINT16(3000, r.port.frames[0].hold);
  // the MQTT event waits for the LoRa ACK, so the cloud knows whether a siren already heard it
  TEST_ASSERT_NULL(r.sink.last(PKR_EVT_MANUAL_TRIGGER));
  r.box.on_ack(PKR_SIM_SIREN_ADDR, r.port.next_ctr);
  const Event* m = r.sink.last(PKR_EVT_MANUAL_TRIGGER);
  TEST_ASSERT_NOT_NULL(m);
  TEST_ASSERT_EQUAL_INT(PKR_PATTERN_C1, m->pattern);
  TEST_ASSERT_EQUAL_STRING("key_critical", m->button);
  TEST_ASSERT_EQUAL_STRING("critical", m->level);
  TEST_ASSERT_EQUAL_INT(1, m->lora_acked);
  TEST_ASSERT_TRUE(m->simulated);
  // holding on does not fire again
  r.run(5000);
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_MANUAL_TRIGGER));
}

static void test_box_ack_retries_and_sms_fallback() {
  // a siren ACKs the second try
  BoxRig r;
  r.box.set_key(PKR_KEY_WARNING);
  r.box.set_button(BOX_C_HOLD, true);
  r.run(3100);
  TEST_ASSERT_TRUE(r.box.waiting_ack());
  r.run(2000);
  TEST_ASSERT_EQUAL_UINT(2, r.port.frames.size());
  r.box.on_ack(PKR_SIM_SIREN_ADDR, r.port.next_ctr);
  TEST_ASSERT_FALSE(r.box.waiting_ack());
  TEST_ASSERT_EQUAL_INT(1, r.sink.last(PKR_EVT_MANUAL_TRIGGER)->lora_acked);
  r.run(10000);
  TEST_ASSERT_EQUAL_UINT(2, r.port.frames.size());
  TEST_ASSERT_TRUE(r.port.sms.empty());
  // nobody ACKs and the cloud is down: three tries, then an SMS to the officers
  BoxRig n;
  n.box.set_key(PKR_KEY_CRITICAL);
  n.box.set_button(BOX_C_HOLD, true);
  n.run(3100);
  n.run(7000);
  TEST_ASSERT_EQUAL_UINT(3, n.port.frames.size());
  TEST_ASSERT_EQUAL_UINT(1, n.port.sms.size());
  TEST_ASSERT_EQUAL_STRING("PKR MANUAL C thunag 14:00", n.port.sms[0].c_str());
  TEST_ASSERT_EQUAL_INT(0, n.sink.last(PKR_EVT_MANUAL_TRIGGER)->lora_acked);
  // nobody ACKs but the cloud is up: no SMS (the cloud propagates it)
  BoxRig c;
  c.port.cloud = true;
  c.box.set_key(PKR_KEY_CRITICAL);
  c.box.set_button(BOX_C_HOLD, true);
  c.run(10100);
  TEST_ASSERT_EQUAL_UINT(3, c.port.frames.size());
  TEST_ASSERT_TRUE(c.port.sms.empty());
}

static void test_box_rate_limit_buttons_and_leds() {
  BoxRig r;
  r.box.set_key(PKR_KEY_WARNING);
  for (int i = 0; i < 4; i++) {
    r.box.set_button(BOX_C_HOLD, true);
    r.run(3100);
    r.box.set_button(BOX_C_HOLD, false);
    r.run(7000);
  }
  TEST_ASSERT_EQUAL_INT(3, r.sink.count(PKR_EVT_MANUAL_TRIGGER));
  TEST_ASSERT_EQUAL_INT(PKR_REASON_RATE_LIMITED, r.sink.last(PKR_EVT_REJECTED)->reason);
  // A: water rising, B: mil gaya (one event per press, a double press within 10 s is one)
  r.box.set_button(BOX_A_WATER, true);
  r.run(100);
  r.box.set_button(BOX_A_WATER, false);
  r.run(100);
  r.box.set_button(BOX_A_WATER, true);
  r.run(100);
  r.box.set_button(BOX_A_WATER, false);
  r.run(100);
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_REPORT));
  r.box.set_button(BOX_B_ACK, true);
  r.run(30);  // a 30 ms blip is not a press
  r.box.set_button(BOX_B_ACK, false);
  r.run(100);
  TEST_ASSERT_EQUAL_INT(0, r.sink.count(PKR_EVT_ACK));
  r.box.set_button(BOX_B_ACK, true);
  r.run(100);
  TEST_ASSERT_EQUAL_INT(1, r.sink.count(PKR_EVT_ACK));
  // D: stop frame
  r.box.set_button(BOX_D_STOP, true);
  r.run(100);
  TEST_ASSERT_EQUAL_UINT8(PKR_BUTTON_STOP, r.port.frames.back().button);
  // level LEDs and the indoor speaker: a chime only at Watch
  r.box.set_level(PKR_LEVEL_WATCH, CLIP_WARNING);
  TEST_ASSERT_TRUE(r.port.plays.back().second);
  r.box.set_level(PKR_LEVEL_CRITICAL, CLIP_CRITICAL);
  TEST_ASSERT_FALSE(r.port.plays.back().second);
  TEST_ASSERT_EQUAL_UINT8(PKR_LEVEL_CRITICAL, r.port.leds);
  // link LED: red (nothing), amber (LoRa only), green (cloud)
  r.run(20);
  TEST_ASSERT_EQUAL_UINT8(3, r.port.link);
  r.box.on_lora_heard();
  r.run(20);
  TEST_ASSERT_EQUAL_UINT8(2, r.port.link);
  r.port.cloud = true;
  r.run(20);
  TEST_ASSERT_EQUAL_UINT8(1, r.port.link);
}

// ---------------------------------------------------------------- relay

struct Radio : RadioPort {
  std::vector<std::vector<uint8_t>> tx;
  bool transmit(const uint8_t* b, size_t n) override {
    tx.push_back(std::vector<uint8_t>(b, b + n));
    return true;
  }
  size_t receive(uint8_t*, size_t) override { return 0; }
};

static uint32_t g_rnd = 0;
static uint32_t rnd() { return g_rnd; }

static void test_relay_forwards_once_after_backoff_without_keys() {
  MemKv kv;
  KeyRing keys;  // the relay's own key only, to sign its beacon
  keys.set_identity(PKR_SIM_RELAY, PKR_SIM_RELAY_ADDR);
  uint8_t k[32];
  fk::key_of(PKR_SIM_RELAY, k);
  keys.set_self_key(1, k);
  FrameSigner signer;
  signer.begin(&keys, &kv);
  Radio radio;
  LoraLink link;
  link.begin(&radio, &signer, PKR_DUTY_RELAY_BUDGET_MS);
  RelayCore relay;
  relay.begin(&link, keys.addr(), rnd);
  pkr_beacon_payload_t beacon{132, 40, 90, -118};
  uint32_t now = 1000, unix_now = 1761121800;
  relay.tick(now, unix_now, true, beacon);  // the first beacon goes out at once
  TEST_ASSERT_EQUAL_UINT(1, radio.tx.size());
  pkr_frame_t bf;
  TEST_ASSERT_EQUAL_INT(PKR_FRAME_OK, pkr_frame_parse(radio.tx[0].data(), radio.tx[0].size(), &bf));
  TEST_ASSERT_EQUAL_HEX8(PKR_FT_RELAY_BEACON, bf.type);
  TEST_ASSERT_TRUE(pkr_frame_mac_ok(radio.tx[0].data(), radio.tx[0].size(), k, 32));
  // a gauge alarm heard: forwarded unchanged after the random backoff (it holds no gauge key)
  auto f = fk::gauge_alarm(PKR_SIM_GAUGE, 77, unix_now);
  g_rnd = 300;
  TEST_ASSERT_TRUE(relay.on_rx(f.data(), f.size(), now));
  relay.tick(now + 349, unix_now, true, beacon);
  TEST_ASSERT_EQUAL_UINT(1, radio.tx.size());  // 50 + 300 ms not yet
  relay.tick(now + 350, unix_now, true, beacon);
  TEST_ASSERT_EQUAL_UINT(2, radio.tx.size());
  TEST_ASSERT_EQUAL_MEMORY(f.data(), radio.tx[1].data(), f.size());  // byte for byte
  // the same (src, ctr) again, e.g. echoed by another relay: not forwarded
  TEST_ASSERT_FALSE(relay.on_rx(f.data(), f.size(), now + 1000));
  TEST_ASSERT_EQUAL_UINT32(1, relay.duplicates);
  // ... unless 10 minutes have passed
  TEST_ASSERT_TRUE(relay.on_rx(f.data(), f.size(), now + 601000));
  // noise is not forwarded
  uint8_t junk[20] = {9, 9};
  TEST_ASSERT_FALSE(relay.on_rx(junk, sizeof junk, now));
  TEST_ASSERT_EQUAL_UINT32(1, relay.malformed);
  // the beacon every 15 minutes
  size_t before = radio.tx.size();
  relay.tick(now + 900000, unix_now + 900, true, beacon);
  TEST_ASSERT_GREATER_THAN(before, radio.tx.size());
}

static void test_relay_budget_keeps_room_for_alarms() {
  MemKv kv;
  KeyRing keys;
  keys.set_identity(PKR_SIM_RELAY, PKR_SIM_RELAY_ADDR);
  uint8_t k[32];
  fk::key_of(PKR_SIM_RELAY, k);
  keys.set_self_key(1, k);
  FrameSigner signer;
  signer.begin(&keys, &kv);
  Radio radio;
  LoraLink link;
  link.begin(&radio, &signer, PKR_DUTY_RELAY_BUDGET_MS);
  uint32_t t = 1761121800;
  uint8_t hb[PKR_FT_HEARTBEAT_LEN] = {0};
  int tele = 0;
  while (link.send(PKR_FT_HEARTBEAT, 0xFFFF, hb, sizeof hb, t, true)) tele++;
  TEST_ASSERT_GREATER_THAN(0, tele);
  auto alarm = fk::gauge_alarm(PKR_SIM_GAUGE, 1, t);
  TEST_ASSERT_TRUE(link.send_raw(alarm.data(), alarm.size(), t, true));    // alarms still go
  TEST_ASSERT_FALSE(link.send_raw(alarm.data(), alarm.size(), t, false));  // telemetry does not
  TEST_ASSERT_LESS_OR_EQUAL_UINT32(PKR_DUTY_RELAY_BUDGET_MS, pkr_duty_used_ms(&link.duty(), t));
}

// ---------------------------------------------------------------- OTA gate

static void test_ota_job_gate() {
  const char* doc =
      "{\"op\":\"ota\",\"fw\":\"pukaar-siren-1.1.0\",\"url\":\"https://bucket.s3.ap-south-1.amazonaws.com/fw.bin?X-Amz=1\","
      "\"sha256\":\"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\",\"size\":1234567,"
      "\"min_soc\":60,\"window\":[\"10:00\",\"16:00\"],\"not_if_alert\":true}";
  OtaJob j;
  TEST_ASSERT_EQUAL_INT(0, parse_ota_job(doc, strlen(doc), &j));
  TEST_ASSERT_EQUAL_UINT32(1234567, j.size);
  TEST_ASSERT_EQUAL_STRING("", ota_gate(j, 80, 11 * 60, false));
  TEST_ASSERT_EQUAL_STRING("alert_active", ota_gate(j, 80, 11 * 60, true));
  TEST_ASSERT_EQUAL_STRING("low_soc", ota_gate(j, 50, 11 * 60, false));
  TEST_ASSERT_EQUAL_STRING("window", ota_gate(j, 80, 9 * 60, false));
  TEST_ASSERT_EQUAL_STRING("window", ota_gate(j, 80, 16 * 60, false));
  const char* http = "{\"op\":\"ota\",\"fw\":\"x\",\"url\":\"http://plain\",\"sha256\":\"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\"}";
  TEST_ASSERT_EQUAL_INT(PKR_REASON_BAD_FORMAT, parse_ota_job(http, strlen(http), &j));
  const char* nosha = "{\"op\":\"ota\",\"fw\":\"x\",\"url\":\"https://a\",\"sha256\":\"00\"}";
  TEST_ASSERT_EQUAL_INT(PKR_REASON_BAD_FORMAT, parse_ota_job(nosha, strlen(nosha), &j));
  const char* sound = "{\"op\":\"sound\"}";  // Jobs never sound a siren
  TEST_ASSERT_EQUAL_INT(PKR_REASON_BAD_FORMAT, parse_ota_job(sound, strlen(sound), &j));
}

// ---------------------------------------------------------------- JSON

static void test_event_envelope_json() {
  Event e;
  e.type = PKR_EVT_VERIFIED;
  e.at = 1761121865;
  strcpy(e.cmd_id, "01JB6");
  e.pattern = PKR_PATTERN_W1;
  e.via = PKR_VIA_SMS;
  e.src = PKR_SRC_APPROVAL;
  e.has_meas = true;
  e.meas.amp_a = 3.14f;
  e.meas.amp_a_ref = 3.3f;
  e.meas.spl_rise_db = 24.46f;
  char out[400];
  size_t n = event_to_json(e, 12, 881, out, sizeof out);
  TEST_ASSERT_GREATER_THAN(0, n);
  TEST_ASSERT_EQUAL_STRING(
      "{\"v\":1,\"seq\":881,\"boot\":12,\"at\":\"2025-10-22T08:31:05Z\",\"type\":\"verified\",\"cmd_id\":\"01JB6\","
      "\"pattern\":\"W1\",\"via\":\"sms\",\"src\":\"approval\",\"meas\":{\"amp_a\":3.1,\"amp_a_ref\":3.3,\"spl_rise_db\":24.5}}",
      out);
  Event r;
  r.type = PKR_EVT_GAUGE_ALARM_HEARD;
  strcpy(r.frame_src, "gauge-janjehli-01");
  r.would_sound = 1;
  r.simulated = true;
  event_to_json(r, 1, 2, out, sizeof out);  // no clock: "at" left for the server
  TEST_ASSERT_EQUAL_STRING(
      "{\"v\":1,\"seq\":2,\"boot\":1,\"type\":\"gauge_alarm_heard\",\"frame_src\":\"gauge-janjehli-01\",\"would_sound\":true,"
      "\"simulated\":true}",
      out);
  char t[21], hm[6];
  iso8601(0, t);
  TEST_ASSERT_EQUAL_STRING("1970-01-01T00:00:00Z", t);
  iso8601(1709251199, t);  // the last second of a leap-year February
  TEST_ASSERT_EQUAL_STRING("2024-02-29T23:59:59Z", t);
  hhmm_ist(1761121800, hm);
  TEST_ASSERT_EQUAL_STRING("14:00", hm);
  hhmm_ist(1761157800 - 60, hm);  // 23:59 IST
  TEST_ASSERT_EQUAL_STRING("23:59", hm);
}

static void test_heartbeat_json() {
  Heartbeat h;
  h.at = 1761121800;
  h.seq = 5;
  h.boot = 2;
  h.state = PKR_STATE_IDLE;
  h.soc = 86;
  h.batt_mv = 13180;
  h.fw = "pukaar-siren-0.1.0";
  h.clips = "catalog-v3";
  h.faults = FAULT_MIC_DEAD | FAULT_TAMPER;
  h.outbox_depth = 3;
  h.uptime_s = 600;
  char out[400];
  TEST_ASSERT_GREATER_THAN(0, heartbeat_to_json(h, out, sizeof out));
  TEST_ASSERT_NOT_NULL(strstr(out, "\"faults\":[\"mic_dead\",\"tamper\"]"));
  TEST_ASSERT_NOT_NULL(strstr(out, "\"state\":\"idle\""));
  TEST_ASSERT_NOT_NULL(strstr(out, "\"path\":\"cell\""));
}

static void test_config_shadow_json() {
  const char* doc =
      "{\"state\":{\"desired\":{\"lora\":{\"freq_hz\":865402500,\"sf\":9,\"bw_khz\":125,\"pwr_dbm\":20,\"apc\":true},"
      "\"senders\":{\"gauge-janjehli-01\":{\"kid\":1,\"roles\":[\"gauge_alarm\"]},\"box-thunag-01\":{\"kid\":2,\"roles\":[\"button\"]}},"
      "\"sms_allow_sha256\":[\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"short\"],"
      "\"autonomy\":{\"enabled\":true,\"fast_path\":false,\"shadow_mode\":true,\"upstream\":[\"gauge-janjehli-01\"],"
      "\"cloud_silence_s\":600,\"cap_on_s\":1800},\"tests\":{\"silent\":\"SUN 11:00\",\"audible\":null},"
      "\"voice_slot\":1,\"amp_a_ref\":3.3,\"siren_a_ref\":1.5,\"spl_rise_min_db\":15,\"catalog\":\"catalog-v3\"}}}";
  DeviceConfig c;
  TEST_ASSERT_EQUAL_INT(0, parse_config_json(doc, strlen(doc), &c));
  TEST_ASSERT_EQUAL_UINT8(9, c.lora_sf);
  TEST_ASSERT_EQUAL_UINT8(2, c.n_senders);
  TEST_ASSERT_EQUAL_STRING("box-thunag-01", c.senders[1].device);
  TEST_ASSERT_EQUAL_UINT8(2, c.senders[1].kid);
  TEST_ASSERT_EQUAL_UINT8(ROLE_BUTTON, c.senders[1].roles);
  TEST_ASSERT_EQUAL_UINT8(1, c.n_sms_allow);  // a malformed hash is skipped
  TEST_ASSERT_TRUE(c.autonomy.enabled);
  TEST_ASSERT_TRUE(c.autonomy.shadow_mode);
  TEST_ASSERT_EQUAL_STRING("gauge-janjehli-01", c.autonomy.upstream[0]);
  TEST_ASSERT_EQUAL_UINT8(1, c.voice_slot);
  TEST_ASSERT_EQUAL_STRING("catalog-v3", c.catalog);
  // a delta with one field changes only that field
  const char* delta = "{\"state\":{\"autonomy\":{\"shadow_mode\":false}}}";
  TEST_ASSERT_EQUAL_INT(0, parse_config_json(delta, strlen(delta), &c));
  TEST_ASSERT_FALSE(c.autonomy.shadow_mode);
  TEST_ASSERT_TRUE(c.autonomy.enabled);
  TEST_ASSERT_EQUAL_UINT8(2, c.n_senders);
  // defaults are the safe side: autonomy off, shadow mode on
  DeviceConfig d;
  TEST_ASSERT_FALSE(d.autonomy.enabled);
  TEST_ASSERT_TRUE(d.autonomy.shadow_mode);
  TEST_ASSERT_FALSE(d.autonomy.fast_path);
}

static void test_gauge_payload_v3() {
  GaugeRecord r{};
  r.at = 1761121800;
  r.seq = 7;
  r.distance_mm = 2391;
  r.level_mm = 1829;
  r.samples_ok = 9;
  r.samples_n = 9;
  r.battery_mv = 13200;
  r.rain_tips_total = 4294967290u;
  r.rain_tips_window = 12;
  r.rain_max_tips_1min = 4;
  r.rain_min_tip_ms = 0xFFFF;
  r.rain_bounce = 1;
  r.rain_err = PKR_RAIN_ERR_BOUNCE;
  GaugeJsonOpts o;
  o.boot = 3;
  o.fw = "pukaar-gauge-3.0.0";
  o.reset_cause = "deepsleep";
  char out[600];
  TEST_ASSERT_GREATER_THAN(0, gauge_reading_json(r, o, out, sizeof out));
  TEST_ASSERT_NOT_NULL(strstr(out, "\"v\":3,\"at\":\"2025-10-22T08:30:00Z\",\"seq\":7,\"boot\":3,\"distance_mm\":2391,\"water_level_cm\":182.9"));
  TEST_ASSERT_NOT_NULL(strstr(out, "\"rain_tips_total\":4294967290,\"rain_tips_window\":12,\"rain_mm_per_tip\":0.2"));
  TEST_ASSERT_NULL(strstr(out, "rain_min_tip_ms"));  // no two tips in the interval
  TEST_ASSERT_NOT_NULL(strstr(out, "\"rain_err\":1"));
  TEST_ASSERT_NOT_NULL(strstr(out, "\"reset_cause\":\"deepsleep\""));
  o.has_level_sensor = false;  // a rain node
  o.buffered = true;
  o.reset_cause = nullptr;
  gauge_reading_json(r, o, out, sizeof out);
  TEST_ASSERT_NULL(strstr(out, "distance_mm"));
  TEST_ASSERT_NOT_NULL(strstr(out, "\"buffered\":true"));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_box_hold_logic);
  RUN_TEST(test_box_ack_retries_and_sms_fallback);
  RUN_TEST(test_box_rate_limit_buttons_and_leds);
  RUN_TEST(test_relay_forwards_once_after_backoff_without_keys);
  RUN_TEST(test_relay_budget_keeps_room_for_alarms);
  RUN_TEST(test_ota_job_gate);
  RUN_TEST(test_event_envelope_json);
  RUN_TEST(test_heartbeat_json);
  RUN_TEST(test_config_shadow_json);
  RUN_TEST(test_gauge_payload_v3);
  return UNITY_END();
}
