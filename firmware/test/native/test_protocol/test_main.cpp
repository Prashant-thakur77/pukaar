// The signed protocol: shadow commands (canonical string, sign, verify, tamper), the compact LoRa
// command, LoRa frames (round trips, truncation, MAC), the receiver's checks and counters, and
// the SMS format.
#include <string.h>
#include <unity.h>

#include "../support/fakes.h"
#include "pkr_codec.h"
#include "pkr_lora.h"
#include "pkr_sms.h"

void setUp() {}
void tearDown() {}

using namespace pkr;

// ---------------------------------------------------------------- shadow command

static void test_canonical_string_is_the_spec_layout() {
  pkr_cmd_t c = fk::command("01JB6CMD", "W1", "warning", 412, 1761121800);
  c.cycles = 5;
  c.repeat_every_s = 900;
  c.repeat_cycles = 2;
  c.cap_on_s = 1200;
  c.kid = 2;
  char buf[PKR_CANONICAL_MAX];
  int n = pkr_cmd_canonical(&c, buf, sizeof buf);
  TEST_ASSERT_GREATER_THAN(0, n);
  TEST_ASSERT_EQUAL_STRING(
      "PKR1|01JB6CMD|siren-thunag-sim|sound|W1|thunag.warning.hi.v3|9f1c2b3a4d5e6f70|warning|01JB5ALERT0000000000000000|"
      "5|900|2|1200|100|1761121800|1761123600|412|approval|2",
      buf);
  c.alert_id[0] = 0;  // null alert -> "-"
  c.clip[0] = 0;      // and every other empty string field too
  pkr_cmd_canonical(&c, buf, sizeof buf);
  TEST_ASSERT_NOT_NULL(strstr(buf, "|warning|-|5|"));
  TEST_ASSERT_NOT_NULL(strstr(buf, "|W1|-|9f1c"));
  strcpy(c.clip, "has space");  // only visible ASCII may be signed
  TEST_ASSERT_EQUAL_INT(-1, pkr_cmd_canonical(&c, buf, sizeof buf));
  TEST_ASSERT_EQUAL_INT(PKR_CMD_FIELD_COUNT, 18);  // the schema's order is the order above
  TEST_ASSERT_EQUAL_STRING("id", PKR_CMD_FIELDS[0]);
  TEST_ASSERT_EQUAL_STRING("kid", PKR_CMD_FIELDS[17]);
}

static void test_a_bar_in_a_field_cannot_be_signed() {
  pkr_cmd_t c = fk::command("01JB6CMD", "W1", "warning", 412, 1761121800);
  strcpy(c.clip, "a|b");  // would let two different commands share one canonical string
  char buf[PKR_CANONICAL_MAX];
  TEST_ASSERT_EQUAL_INT(-1, pkr_cmd_canonical(&c, buf, sizeof buf));
  uint8_t key[32];
  fk::key_of(PKR_SIM_SIREN, key);
  TEST_ASSERT_EQUAL_INT(-1, pkr_cmd_sign(&c, key, 32));
  TEST_ASSERT_FALSE(pkr_cmd_verify(&c, key, 32));
}

static void test_sign_verify_and_every_field_tampered() {
  uint8_t key[32], other[32];
  fk::key_of(PKR_SIM_SIREN, key);
  fk::key_of("siren-other-01", other);
  pkr_cmd_t c = fk::command("01JB6CMD", "C1", "critical", 413, 1761121800);
  TEST_ASSERT_TRUE(pkr_cmd_verify(&c, key, 32));
  TEST_ASSERT_FALSE(pkr_cmd_verify(&c, other, 32));  // another device's key
  char sig[24];
  pkr_cmd_sig_b64(&c, sig);
  TEST_ASSERT_EQUAL_UINT(22, strlen(sig));  // 16 bytes, base64url, no padding
  pkr_cmd_t d = c;
  TEST_ASSERT_EQUAL_INT(0, pkr_cmd_set_sig_b64(&d, sig));
  TEST_ASSERT_TRUE(pkr_cmd_verify(&d, key, 32));
  // each field in turn
  for (int f = 0; f < 18; f++) {
    pkr_cmd_t t = c;
    switch (f) {
      case 0: t.id[0] ^= 1; break;
      case 1: strcpy(t.device, "siren-thunag-02"); break;
      case 2: strcpy(t.action, "stop"); break;
      case 3: strcpy(t.pattern, "W1"); break;
      case 4: strcpy(t.clip, "thunag.warning.hi.v3"); break;
      case 5: t.clip_sha256_16[0] = '0'; break;
      case 6: strcpy(t.level, "warning"); break;
      case 7: t.alert_id[0] = 0; break;
      case 8: t.cycles++; break;
      case 9: t.repeat_every_s++; break;
      case 10: t.repeat_cycles++; break;
      case 11: t.cap_on_s++; break;
      case 12: t.volume--; break;
      case 13: t.iat++; break;
      case 14: t.exp += 3600; break;
      case 15: t.ctr++; break;
      case 16: strcpy(t.src, "drill"); break;
      case 17: t.kid = 2; break;
    }
    TEST_ASSERT_FALSE_MESSAGE(pkr_cmd_verify(&t, key, 32), PKR_CMD_FIELDS[f]);
  }
  // and every bit of the signature
  for (int i = 0; i < 128; i++) {
    pkr_cmd_t t = c;
    t.sig[i / 8] ^= (uint8_t)(1 << (i % 8));
    TEST_ASSERT_FALSE(pkr_cmd_verify(&t, key, 32));
  }
}

static void test_command_json_shapes() {
  pkr_cmd_t c = fk::command("01JB6CMD", "W1", "warning", 412, 1761121800);
  char sig[24];
  pkr_cmd_sig_b64(&c, sig);
  char cmd[700];
  snprintf(cmd, sizeof cmd,
           "{\"id\":\"%s\",\"device\":\"%s\",\"action\":\"sound\",\"pattern\":\"W1\",\"clip\":\"%s\",\"clip_sha256_16\":\"%s\","
           "\"level\":\"warning\",\"alert_id\":\"%s\",\"cycles\":0,\"repeat_every_s\":0,\"repeat_cycles\":0,\"cap_on_s\":0,"
           "\"volume\":100,\"iat\":%u,\"exp\":%u,\"ctr\":412,\"src\":\"approval\",\"kid\":1,\"sig\":\"%s\"}",
           c.id, c.device, c.clip, c.clip_sha256_16, c.alert_id, (unsigned)c.iat, (unsigned)c.exp, sig);
  const char* wraps[] = {"%s", "{\"cmd\":%s}", "{\"state\":{\"cmd\":%s}}", "{\"state\":{\"desired\":{\"cmd\":%s}},\"version\":7}"};
  uint8_t key[32];
  fk::key_of(PKR_SIM_SIREN, key);
  for (auto w : wraps) {
    char doc[900];
    snprintf(doc, sizeof doc, w, cmd);
    pkr_cmd_t p;
    TEST_ASSERT_EQUAL_INT(0, parse_cmd_json(doc, strlen(doc), &p));
    TEST_ASSERT_TRUE(pkr_cmd_verify(&p, key, 32));
  }
  // null alert_id, wrong types, missing fields
  pkr_cmd_t p;
  const char* bad[] = {"{}", "not json", "{\"id\":1}", "{\"cmd\":{\"id\":\"x\"}}"};
  for (auto b : bad) TEST_ASSERT_NOT_EQUAL(0, parse_cmd_json(b, strlen(b), &p));
  std::string s = cmd;
  size_t at = s.find("\"ctr\":412");
  std::string str_ctr = s.substr(0, at) + "\"ctr\":\"412\"" + s.substr(at + 9);
  TEST_ASSERT_EQUAL_INT(PKR_REASON_BAD_FORMAT, parse_cmd_json(str_ctr.c_str(), str_ctr.size(), &p));
  at = s.find("\"alert_id\":\"");
  size_t end = s.find('"', at + 12);
  std::string null_alert = s.substr(0, at) + "\"alert_id\":null" + s.substr(end + 1);
  TEST_ASSERT_EQUAL_INT(0, parse_cmd_json(null_alert.c_str(), null_alert.size(), &p));
  TEST_ASSERT_EQUAL_STRING("", p.alert_id);
}

static void test_command_enums() {
  pkr_cmd_t c = fk::command("x", "C1", "critical", 1, 1761121800);
  pkr_cmd_enums_t e;
  TEST_ASSERT_EQUAL_INT(0, pkr_cmd_enums(&c, &e));
  TEST_ASSERT_EQUAL_INT(PKR_PATTERN_C1, e.pattern);
  TEST_ASSERT_EQUAL_INT(PKR_SRC_APPROVAL, e.src);
  strcpy(c.pattern, "B1");  // the bridge beacon is never a siren command
  TEST_ASSERT_EQUAL_INT(-1, pkr_cmd_enums(&c, &e));
  strcpy(c.pattern, "Z9");
  TEST_ASSERT_EQUAL_INT(-1, pkr_cmd_enums(&c, &e));
  strcpy(c.pattern, "");
  strcpy(c.action, "stop");
  strcpy(c.level, "-");
  TEST_ASSERT_EQUAL_INT(0, pkr_cmd_enums(&c, &e));  // a stop needs no pattern or level
  strcpy(c.action, "sound");
  strcpy(c.pattern, "D1");
  strcpy(c.level, "drill");
  TEST_ASSERT_EQUAL_INT(0, pkr_cmd_enums(&c, &e));
  TEST_ASSERT_EQUAL_INT(PKR_CMDLEVEL_DRILL, e.level);
  strcpy(c.level, "normal");  // a frame level, not a command level
  TEST_ASSERT_EQUAL_INT(-1, pkr_cmd_enums(&c, &e));
}

// ---------------------------------------------------------------- compact LoRa command

static void test_wrapped_command_round_trip_and_inner_mac() {
  uint8_t key[32];
  fk::key_of(PKR_SIM_SIREN, key);
  pkr_wrapped_cmd_t w{};
  pkr_cmd_id48("01JB6CMD", w.cmd_id48);
  w.action = PKR_ACTION_SOUND;
  w.pattern = PKR_PATTERN_C1;
  w.level = PKR_CMDLEVEL_CRITICAL;
  w.cycles = 10;
  w.cap_on_s = 2700;
  w.exp = 1761123600;
  w.ctr = 414;
  pkr_wrapped_sign(&w, PKR_SIM_SIREN, key, 32);
  uint8_t bytes[36];
  pkr_wrapped_encode(&w, bytes);
  TEST_ASSERT_EQUAL_INT(PKR_FT_SIREN_CMD_WRAPPED_LEN, 36);
  pkr_wrapped_cmd_t back;
  pkr_wrapped_decode(bytes, &back);
  TEST_ASSERT_TRUE(pkr_wrapped_verify(&back, PKR_SIM_SIREN, key, 32));
  TEST_ASSERT_FALSE(pkr_wrapped_verify(&back, "siren-other-01", key, 32));
  for (int i = 0; i < 20; i++) {  // every signed byte
    uint8_t t[36];
    memcpy(t, bytes, 36);
    t[i] ^= 0x01;
    pkr_wrapped_decode(t, &back);
    TEST_ASSERT_FALSE(pkr_wrapped_verify(&back, PKR_SIM_SIREN, key, 32));
  }
}

// ---------------------------------------------------------------- LoRa frame

static void test_frame_round_trip_every_type() {
  uint8_t key[32];
  fk::key_of(PKR_SIM_GAUGE, key);
  const uint8_t types[] = {PKR_FT_GAUGE_STATUS, PKR_FT_GAUGE_ALARM, PKR_FT_SIREN_CMD_WRAPPED, PKR_FT_SIREN_EVENT,
                           PKR_FT_BUTTON,       PKR_FT_HEARTBEAT,   PKR_FT_RELAY_BEACON,      PKR_FT_ACK};
  for (uint8_t t : types) {
    pkr_frame_t f{};
    f.ver = 1;
    f.type = t;
    f.src = 0x1234;
    f.dst = 0xFFFF;
    f.ctr = 0xA1B2C3D4;
    f.ts = 1761121800;
    f.len = (uint8_t)pkr_frame_payload_len(t);
    for (int i = 0; i < f.len; i++) f.payload[i] = (uint8_t)(i * 7 + t);
    uint8_t buf[64];
    int n = pkr_frame_encode(&f, key, 32, buf, sizeof buf);
    TEST_ASSERT_EQUAL_INT(15 + f.len + 8, n);
    TEST_ASSERT_LESS_OR_EQUAL(64, n);
    // little-endian header as the spec draws it
    TEST_ASSERT_EQUAL_HEX8(0x01, buf[0]);
    TEST_ASSERT_EQUAL_HEX8(t, buf[1]);
    TEST_ASSERT_EQUAL_HEX8(0x34, buf[2]);
    TEST_ASSERT_EQUAL_HEX8(0x12, buf[3]);
    TEST_ASSERT_EQUAL_HEX8(0xD4, buf[6]);
    TEST_ASSERT_EQUAL_HEX8(0xA1, buf[9]);
    TEST_ASSERT_EQUAL_HEX8(f.len, buf[14]);
    pkr_frame_t g;
    TEST_ASSERT_EQUAL_INT(PKR_FRAME_OK, pkr_frame_parse(buf, (size_t)n, &g));
    TEST_ASSERT_EQUAL_UINT32(f.ctr, g.ctr);
    TEST_ASSERT_EQUAL_MEMORY(f.payload, g.payload, f.len);
    TEST_ASSERT_TRUE(pkr_frame_mac_ok(buf, (size_t)n, key, 32));
    // truncation at every length is refused, never read past the end
    for (int k = 0; k < n; k++) TEST_ASSERT_NOT_EQUAL(PKR_FRAME_OK, pkr_frame_parse(buf, (size_t)k, &g));
    // any flipped byte breaks the MAC
    for (int k = 0; k < n; k++) {
      uint8_t c[64];
      memcpy(c, buf, (size_t)n);
      c[k] ^= 0x80;
      TEST_ASSERT_FALSE(pkr_frame_mac_ok(c, (size_t)n, key, 32));
    }
  }
}

static void test_frame_structure_errors() {
  uint8_t key[32] = {0};
  pkr_frame_t f{};
  f.ver = 1;
  f.type = PKR_FT_BUTTON;
  f.len = 5;  // BUTTON is 4 bytes
  uint8_t buf[64];
  TEST_ASSERT_EQUAL_INT(PKR_FRAME_E_TYPE_LEN, pkr_frame_encode(&f, key, 32, buf, sizeof buf));
  f.len = 4;
  int n = pkr_frame_encode(&f, key, 32, buf, sizeof buf);
  pkr_frame_t g;
  buf[0] = 2;
  TEST_ASSERT_EQUAL_INT(PKR_FRAME_E_VERSION, pkr_frame_parse(buf, (size_t)n, &g));
  buf[0] = 1;
  buf[1] = 0x55;  // an unknown type parses (as protocol.decode_frame); the receiver's role check refuses it
  TEST_ASSERT_EQUAL_INT(PKR_FRAME_OK, pkr_frame_parse(buf, (size_t)n, &g));
  TEST_ASSERT_EQUAL_INT(PKR_FRAME_E_TYPE, pkr_frame_type_len_ok(0x55, 4));
  TEST_ASSERT_EQUAL_INT(PKR_FRAME_E_TYPE_LEN, pkr_frame_type_len_ok(PKR_FT_BUTTON, 5));
  buf[1] = PKR_FT_BUTTON;
  buf[14] = 41;
  TEST_ASSERT_EQUAL_INT(PKR_FRAME_E_LEN, pkr_frame_parse(buf, (size_t)n, &g));
  buf[14] = 4;
  TEST_ASSERT_EQUAL_INT(PKR_FRAME_E_LEN, pkr_frame_parse(buf, (size_t)n + 1, &g));  // trailing byte
  TEST_ASSERT_EQUAL_INT(PKR_FRAME_E_CAP, pkr_frame_encode(&f, key, 32, buf, 20));
}

static void test_payload_codecs() {
  pkr_gauge_payload_t g{PKR_LEVEL_CRITICAL, -12, -300, 96, 1, 655};
  uint8_t p[9];
  pkr_gauge_payload_encode(&g, p);
  pkr_gauge_payload_t h;
  pkr_gauge_payload_decode(p, &h);
  TEST_ASSERT_EQUAL_INT16(-12, h.stage_cm);
  TEST_ASSERT_EQUAL_INT16(-300, h.rise_10min_cm);
  TEST_ASSERT_EQUAL_UINT16(655, h.rain_15min_tenths_mm);
  pkr_beacon_payload_t b{132, 45, 88, -117}, b2;
  uint8_t q[6];
  pkr_beacon_payload_encode(&b, q);
  pkr_beacon_payload_decode(q, &b2);
  TEST_ASSERT_EQUAL_INT8(-117, b2.noise_dbm);
  pkr_heartbeat_payload_t hb{3, 86, 131, 0x0201, 17}, hb2;
  uint8_t r[8];
  pkr_heartbeat_payload_encode(&hb, r);
  pkr_heartbeat_payload_decode(r, &hb2);
  TEST_ASSERT_EQUAL_UINT16(0x0201, hb2.faults);
  pkr_siren_event_payload_t se{PKR_EVT_VERIFIED, {1, 2, 3, 4, 5, 6}, 1, 31, 24}, se2;
  uint8_t s[10];
  pkr_siren_event_payload_encode(&se, s);
  pkr_siren_event_payload_decode(s, &se2);
  TEST_ASSERT_EQUAL_UINT8(31, se2.amp_a_x10);
  TEST_ASSERT_EQUAL_UINT8(6, se2.cmd_id48[5]);
}

static void test_airtime() {
  // the well-known LoRaWAN figure: 13 bytes at SF7/125 kHz, CR 4/5, 8 preamble = 46.3 ms
  TEST_ASSERT_EQUAL_UINT32(47, pkr_lora_airtime_ms(13, 7, 125000, 5, 8, 1, 1));
  // a 32-byte gauge frame at SF10/125 kHz: 453 ms (the spec's "about 370 ms" is low)
  TEST_ASSERT_EQUAL_UINT32(453, pkr_lora_airtime_ms(32, 10, 125000, 5, 8, 1, 1));
  // SF12 turns on low data rate optimisation
  TEST_ASSERT_GREATER_THAN(1000, pkr_lora_airtime_ms(32, 12, 125000, 5, 8, 1, 1));
}

// ---------------------------------------------------------------- receiver checks

struct RxRig {
  MemKv kv;
  KeyRing keys;
  FrameReceiver rx;
  RxRig() {
    keys.set_identity(PKR_SIM_SIREN, PKR_SIM_SIREN_ADDR);
    keys.add_sender(fk::sender(PKR_SIM_GAUGE, ROLE_GAUGE_STATUS | ROLE_GAUGE_ALARM));
    keys.add_sender(fk::sender(PKR_SIM_BOX, ROLE_BUTTON));
    rx.begin(&keys, &kv);
  }
};

static void test_receiver_checks() {
  RxRig r;
  uint32_t now = 1761121800;
  auto a = fk::gauge_alarm(PKR_SIM_GAUGE, 5, now);
  TEST_ASSERT_EQUAL_INT(0, r.rx.receive(a.data(), a.size(), now, true).reason);
  TEST_ASSERT_EQUAL_INT(PKR_REASON_REPLAYED, r.rx.receive(a.data(), a.size(), now, true).reason);
  auto older = fk::gauge_alarm(PKR_SIM_GAUGE, 4, now);
  TEST_ASSERT_EQUAL_INT(PKR_REASON_REPLAYED, r.rx.receive(older.data(), older.size(), now, true).reason);
  // a box may not send gauge alarms (role), an unknown device is unknown
  auto fake = fk::gauge_alarm(PKR_SIM_BOX, 9, now);
  TEST_ASSERT_EQUAL_INT(PKR_REASON_ROLE, r.rx.receive(fake.data(), fake.size(), now, true).reason);
  auto stranger = fk::gauge_alarm("gauge-elsewhere-01", 9, now);
  TEST_ASSERT_EQUAL_INT(PKR_REASON_UNKNOWN_SRC, r.rx.receive(stranger.data(), stranger.size(), now, true).reason);
  // a forged MAC
  auto forged = fk::gauge_alarm(PKR_SIM_GAUGE, 6, now);
  forged[16] ^= 1;
  TEST_ASSERT_EQUAL_INT(PKR_REASON_BAD_MAC, r.rx.receive(forged.data(), forged.size(), now, true).reason);
  // stale timestamp when both clocks are synced; ignored when ours is not (or theirs is 0)
  auto stale = fk::gauge_alarm(PKR_SIM_GAUGE, 7, now - 900);
  TEST_ASSERT_EQUAL_INT(PKR_REASON_CLOCK_SKEW, r.rx.receive(stale.data(), stale.size(), now, true).reason);
  TEST_ASSERT_EQUAL_INT(0, r.rx.receive(stale.data(), stale.size(), now, false).reason);
  auto unsynced = fk::gauge_alarm(PKR_SIM_GAUGE, 8, 0);
  TEST_ASSERT_EQUAL_INT(0, r.rx.receive(unsynced.data(), unsynced.size(), now, true).reason);
  // addressed to someone else: not for us
  pkr_gauge_payload_t g{3, 300, 0, 90, 0, 0};
  uint8_t p[9];
  pkr_gauge_payload_encode(&g, p);
  auto other = fk::frame(PKR_SIM_GAUGE, PKR_FT_GAUGE_ALARM, 0x0505, 20, now, p, 9);
  TEST_ASSERT_EQUAL_INT(-1, r.rx.receive(other.data(), other.size(), now, true).reason);
  // noise
  uint8_t junk[30] = {1, 2, 3};
  TEST_ASSERT_EQUAL_INT(PKR_REASON_MALFORMED, r.rx.receive(junk, sizeof junk, now, true).reason);
}

static void test_counter_persistence_and_boot_skip() {
  MemKv kv;
  {
    LazyCounter c;
    c.load_send(&kv, "txctr");
    TEST_ASSERT_EQUAL_UINT32(0, c.value());
    int w0 = kv.writes;
    for (int i = 0; i < 25; i++) c.next();
    TEST_ASSERT_EQUAL_INT(w0 + 2, kv.writes);  // at 10 and 20: at most once every 10
    uint32_t stored;
    kv.get_u32("txctr", &stored);
    TEST_ASSERT_EQUAL_UINT32(20, stored);
  }  // reset without a power-down warning: 21-25 were sent but never stored
  LazyCounter c;
  c.load_send(&kv, "txctr");
  TEST_ASSERT_EQUAL_UINT32(36, c.value());  // 20 + 16 > 25: never repeats a sent ctr
  TEST_ASSERT_GREATER_THAN(25, c.next());
  // a second reset straight away skips again (the bumped value was written at load)
  LazyCounter d;
  d.load_send(&kv, "txctr");
  TEST_ASSERT_EQUAL_UINT32(52, d.value());
  d.flush();
}

static void test_receiver_counters_restore_exactly() {
  uint32_t now = 1761121800;
  MemKv kv;
  KeyRing keys;
  keys.set_identity(PKR_SIM_SIREN, PKR_SIM_SIREN_ADDR);
  keys.add_sender(fk::sender(PKR_SIM_GAUGE, ROLE_GAUGE_ALARM));
  {
    FrameReceiver rx;
    rx.begin(&keys, &kv);
    for (uint32_t ctr = 1; ctr <= 12; ctr++) {
      auto f = fk::gauge_alarm(PKR_SIM_GAUGE, ctr, now);
      TEST_ASSERT_EQUAL_INT(0, rx.receive(f.data(), f.size(), now, true).reason);
    }
  }  // the siren resets: every accepted counter was written through, the last is 12
  uint32_t stored = 0;
  TEST_ASSERT_TRUE(kv.get_u32("rx0201", &stored));
  TEST_ASSERT_EQUAL_UINT32(12, stored);
  FrameReceiver rx;
  rx.begin(&keys, &kv);
  // no +16 gap: 12 and below are replays, 13 (the gauge's next frame) is accepted at once
  for (uint32_t ctr : {1u, 11u, 12u}) {
    auto f = fk::gauge_alarm(PKR_SIM_GAUGE, ctr, now);
    TEST_ASSERT_EQUAL_INT(PKR_REASON_REPLAYED, rx.receive(f.data(), f.size(), now, true).reason);
  }
  auto f13 = fk::gauge_alarm(PKR_SIM_GAUGE, 13, now);
  TEST_ASSERT_EQUAL_INT(0, rx.receive(f13.data(), f13.size(), now, true).reason);
  TEST_ASSERT_EQUAL_INT(PKR_REASON_REPLAYED, rx.receive(f13.data(), f13.size(), now, true).reason);
  // a refused frame never moves the stored counter; an accepted one moves it before return
  kv.get_u32("rx0201", &stored);
  TEST_ASSERT_EQUAL_UINT32(13, stored);
}

// ---------------------------------------------------------------- SMS

static void test_sms_format_parse_verify() {
  uint8_t key[32];
  fk::key_of("siren-thunag-01", key);
  pkr_sms_t s{};
  strcpy(s.device, "siren-thunag-01");
  s.action = 'S';
  s.level = 'C';
  s.ctr = 413;
  s.exp = 1761123600;
  char text[170];
  int n = pkr_sms_format(&s, key, 32, text, sizeof text);
  TEST_ASSERT_GREATER_THAN(0, n);
  TEST_ASSERT_LESS_OR_EQUAL(160, n);
  TEST_ASSERT_EQUAL_STRING_LEN("PKR1 siren-thunag-01 SC 000413 T4IZO0 ", text, 38);
  // a U in the signature is not Crockford: it parses (as the backend's regex) and fails the signature
  std::string u = std::string(text, 38) + "7K2QM9XA4D1F8HTU";
  pkr_sms_t pu;
  TEST_ASSERT_EQUAL_INT(PKR_SMS_OK, pkr_sms_parse(u.data(), u.size(), &pu));
  TEST_ASSERT_FALSE(pkr_sms_verify(&pu, key, 32));
  TEST_ASSERT_EQUAL_INT(38 + 16, n);
  char signed_str[96];
  pkr_sms_signed_string(&s, signed_str, sizeof signed_str);
  TEST_ASSERT_EQUAL_STRING("PKR1|siren-thunag-01|S|C|413|1761123600", signed_str);
  pkr_sms_t p;
  TEST_ASSERT_EQUAL_INT(PKR_SMS_OK, pkr_sms_parse(text, (size_t)n, &p));
  TEST_ASSERT_EQUAL_UINT32(413, p.ctr);
  TEST_ASSERT_EQUAL_UINT32(1761123600u, p.exp);
  TEST_ASSERT_TRUE(pkr_sms_verify(&p, key, 32));
  // tampering with any field breaks it
  pkr_sms_t t = p;
  t.level = 'W';
  TEST_ASSERT_FALSE(pkr_sms_verify(&t, key, 32));
  t = p;
  t.ctr++;
  TEST_ASSERT_FALSE(pkr_sms_verify(&t, key, 32));
  t = p;
  t.exp += 60;
  TEST_ASSERT_FALSE(pkr_sms_verify(&t, key, 32));
}

static void test_sms_parser_case_rules() {
  uint8_t key[32];
  fk::key_of("siren-thunag-01", key);
  pkr_sms_t s{};
  strcpy(s.device, "siren-thunag-01");
  s.action = 'X';
  s.level = 'W';
  s.ctr = 9;
  s.exp = 1761123600;
  char text[170];
  int n = pkr_sms_format(&s, key, 32, text, sizeof text);
  std::string t(text, (size_t)n);
  // the prefix, the codes and the encodings in any case
  std::string lower = t;
  for (size_t i = 0; i < lower.size(); i++)
    if (i < 4 || i > 4 + strlen("siren-thunag-01")) lower[i] = (char)tolower(lower[i]);
  pkr_sms_t p;
  TEST_ASSERT_EQUAL_INT(PKR_SMS_OK, pkr_sms_parse(lower.data(), lower.size(), &p));
  TEST_ASSERT_TRUE(pkr_sms_verify(&p, key, 32));
  TEST_ASSERT_EQUAL_CHAR('X', p.action);
  // a modem's trailing CR LF is fine
  std::string crlf = t + "\r\n";
  TEST_ASSERT_EQUAL_INT(PKR_SMS_OK, pkr_sms_parse(crlf.data(), crlf.size(), &p));
  // the device id is exact: a capitalised id parses but is another device (bad signature)
  std::string cap = t;
  cap[5] = 'S';
  TEST_ASSERT_EQUAL_INT(PKR_SMS_OK, pkr_sms_parse(cap.data(), cap.size(), &p));
  TEST_ASSERT_FALSE(pkr_sms_verify(&p, key, 32));
  // single spaces only
  std::string two = t;
  two.insert(4, " ");
  TEST_ASSERT_EQUAL_INT(PKR_SMS_E_FIELDS, pkr_sms_parse(two.data(), two.size(), &p));
}

static void test_sms_parser_rejects_malformed() {
  pkr_sms_t p;
  const char* bad[] = {
      "",
      "PKR1 siren-thunag-01 SC 000413 T4IZO0",                         // 5 fields
      "PKR1 siren-thunag-01 SC 000413 T4IZO0 7K2QM9XA4D1F8HTP extra",  // 7 fields
      "PKR2 siren-thunag-01 SC 000413 T4IZO0 7K2QM9XA4D1F8HTP",        // prefix
      "PKR1 siren/thunag SC 000413 T4IZO0 7K2QM9XA4D1F8HTP",           // device chars
      "PKR1 siren-thunag-01 QC 000413 T4IZO0 7K2QM9XA4D1F8HTP",        // action
      "PKR1 siren-thunag-01 SZ 000413 T4IZO0 7K2QM9XA4D1F8HTP",        // level
      "PKR1 siren-thunag-01 SCC 000413 T4IZO0 7K2QM9XA4D1F8HTP",       // A+L length
      "PKR1 siren-thunag-01 SC 0004l3 T4IZO0 7K2QM9XA4D1F8HTP",        // ctr digit
      "PKR1 siren-thunag-01 SC 99999999999 T4IZO0 7K2QM9XA4D1F8HTP",   // ctr overflow
      "PKR1 siren-thunag-01 SC 000413 T4-ZO0 7K2QM9XA4D1F8HTP",        // exp
      "PKR1 siren-thunag-01 SC 000413 T4IZO0 7K2QM9XA4D1F8HT",         // sig 15 chars
      "PKR1 siren-thunag-01 SC 000413 T4IZO0 7K2QM9XA4D1F8HT-",        // sig character
      "PKR1 si SC 000413 T4IZO0 7K2QM9XA4D1F8HTP",                     // device under 3
  };
  for (auto b : bad) TEST_ASSERT_NOT_EQUAL_MESSAGE(PKR_SMS_OK, pkr_sms_parse(b, strlen(b), &p), b);
  // Unicode (a UCS-2 SMS decoded to UTF-8): refused, not mangled
  const char* hindi = "PKR1 siren-thunag-01 SC 000413 T4IZO0 7K2QM9XA4D1F8HTP \xe0\xa4\xb8";
  TEST_ASSERT_EQUAL_INT(PKR_SMS_E_NON_ASCII, pkr_sms_parse(hindi, strlen(hindi), &p));
  // over 160 characters
  std::string longer = "PKR1 siren-thunag-01 SC 000413 T4IZO0 7K2QM9XA4D1F8HTP" + std::string(120, ' ') + "x";
  TEST_ASSERT_EQUAL_INT(PKR_SMS_E_TOO_LONG, pkr_sms_parse(longer.data(), longer.size(), &p));
  // the spec's example has the right shape (its signature is illustrative, not valid)
  const char* ex = "PKR1 siren-thunag-01 SC 000413 TJ8K2Q 7K2QM9XA4D1F8HTP";
  TEST_ASSERT_EQUAL_INT(PKR_SMS_OK, pkr_sms_parse(ex, strlen(ex), &p));
  uint8_t key[32];
  fk::key_of("siren-thunag-01", key);
  TEST_ASSERT_FALSE(pkr_sms_verify(&p, key, 32));
}

static void test_sms_sender_hash() {
  char h[65];
  pkr_sms_sender_hash("salt", "+919876543210", h);
  uint8_t want[32];
  const char* m = "salt+919876543210";
  pkr_sha256(m, strlen(m), want);
  char hex[65];
  pkr_hex_encode(want, 32, hex);
  TEST_ASSERT_EQUAL_STRING(hex, h);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_canonical_string_is_the_spec_layout);
  RUN_TEST(test_a_bar_in_a_field_cannot_be_signed);
  RUN_TEST(test_sign_verify_and_every_field_tampered);
  RUN_TEST(test_command_json_shapes);
  RUN_TEST(test_command_enums);
  RUN_TEST(test_wrapped_command_round_trip_and_inner_mac);
  RUN_TEST(test_frame_round_trip_every_type);
  RUN_TEST(test_frame_structure_errors);
  RUN_TEST(test_payload_codecs);
  RUN_TEST(test_airtime);
  RUN_TEST(test_receiver_checks);
  RUN_TEST(test_counter_persistence_and_boot_skip);
  RUN_TEST(test_receiver_counters_restore_exactly);
  RUN_TEST(test_sms_format_parse_verify);
  RUN_TEST(test_sms_parser_case_rules);
  RUN_TEST(test_sms_parser_rejects_malformed);
  RUN_TEST(test_sms_sender_hash);
  return UNITY_END();
}
