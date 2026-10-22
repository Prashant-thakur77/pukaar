// Golden vectors from the backend's canonical codec (backend/src/Pukaar/services/devices/protocol.py
// and siren_model.py, written by `python -m Pukaar.scripts.protocol_vectors`) at
// firmware/test/vectors/protocol_vectors.json. Every vector must pass: enums and constants, key
// derivation, command canonical strings and signatures, the sequenced acceptance matrix and the
// boot +16 rule, frame bytes and MACs, the inner LoRa command signature, the sequenced frame
// rejections, the SMS texts and the sequenced SMS checks, the sender hash, and "verified".
//
// When the file is absent every test is reported IGNORED with a message (never a silent pass).
// PUKAAR_VECTORS=/path/to/file.json points at another file.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unity.h>

#include <ArduinoJson.h>
#include <string>
#include <vector>

#include "pkr_codec.h"
#include "pkr_command.h"
#include "pkr_crypto.h"
#include "pkr_frame.h"
#include "pkr_guard.h"
#include "pkr_lora.h"
#include "pkr_pattern.h"
#include "pkr_sms.h"
#include "schema.h"

#ifndef PUKAAR_VECTORS_PATH
#define PUKAAR_VECTORS_PATH "test/vectors/protocol_vectors.json"
#endif

using namespace pkr;

void setUp() {}
void tearDown() {}

static JsonDocument g_doc;
static bool g_tried = false, g_loaded = false;
static std::string g_path;

static bool load() {
  if (g_tried) return g_loaded;
  g_tried = true;
  std::vector<std::string> paths;
  if (getenv("PUKAAR_VECTORS")) paths.push_back(getenv("PUKAAR_VECTORS"));
  paths.push_back(PUKAAR_VECTORS_PATH);
  paths.push_back(std::string("firmware/") + PUKAAR_VECTORS_PATH);
  for (auto& p : paths) {
    FILE* f = fopen(p.c_str(), "rb");
    if (!f) continue;
    std::string s;
    char buf[4096];
    size_t n;
    while ((n = fread(buf, 1, sizeof buf, f)) > 0) s.append(buf, n);
    fclose(f);
    if (deserializeJson(g_doc, s)) return false;
    g_path = p;
    g_loaded = true;
    return true;
  }
  return false;
}

#define REQUIRE_FILE()                                                                                     \
  if (!load()) {                                                                                           \
    TEST_IGNORE_MESSAGE("SKIPPED: test/vectors/protocol_vectors.json is absent or not JSON (the backend " \
                        "writes it); the self-consistency suites still run");                             \
  }

static JsonObjectConst root() { return g_doc.as<JsonObjectConst>(); }

static void key_from_hex(const char* hex, uint8_t out[32], const std::string& what) {
  TEST_ASSERT_NOT_NULL_MESSAGE(hex, (what + ": no key").c_str());
  TEST_ASSERT_EQUAL_INT_MESSAGE(32, pkr_hex_decode(hex, out, 32), (what + ": key hex").c_str());
}

static std::vector<uint8_t> from_hex(const char* hex) {
  std::vector<uint8_t> v(hex ? strlen(hex) / 2 : 0);
  if (hex && !v.empty()) TEST_ASSERT_EQUAL_INT((int)v.size(), pkr_hex_decode(hex, v.data(), v.size()));
  return v;
}

static std::string to_hex(const uint8_t* b, size_t n) {
  std::string s(n * 2 + 1, '\0');
  pkr_hex_encode(b, n, &s[0]);
  s.resize(n * 2);
  return s;
}

static const char* reason_name(int r) { return r == 0 ? "ok" : pkr_reason_name(r); }

// A command object from the vectors into the C struct; device is the receiver's id.
static pkr_cmd_t cmd_of(JsonObjectConst c, const char* device) {
  pkr_cmd_t x;
  memset(&x, 0, sizeof x);
  auto str = [&](const char* k, char* dst, size_t cap) {
    const char* v = c[k].is<const char*>() ? c[k].as<const char*>() : "";
    strncpy(dst, v, cap - 1);
  };
  str("id", x.id, sizeof x.id);
  strncpy(x.device, device, sizeof x.device - 1);
  str("action", x.action, sizeof x.action);
  str("pattern", x.pattern, sizeof x.pattern);
  str("clip", x.clip, sizeof x.clip);
  str("clip_sha256_16", x.clip_sha256_16, sizeof x.clip_sha256_16);
  str("level", x.level, sizeof x.level);
  str("alert_id", x.alert_id, sizeof x.alert_id);
  str("src", x.src, sizeof x.src);
  x.cycles = c["cycles"] | 0u;
  x.repeat_every_s = c["repeat_every_s"] | 0u;
  x.repeat_cycles = c["repeat_cycles"] | 0u;
  x.cap_on_s = c["cap_on_s"] | 0u;
  x.volume = c["volume"] | 0u;
  x.iat = c["iat"] | 0u;
  x.exp = c["exp"] | 0u;
  x.ctr = c["ctr"] | 0u;
  x.kid = c["kid"] | 0u;
  const char* sig = c["sig"];
  if (sig) pkr_cmd_set_sig_b64(&x, sig);
  return x;
}

// ---------------------------------------------------------------- enums and constants

typedef int (*from_name_fn)(const char*);

static void check_enum(const char* table, from_name_fn fn) {
  JsonObjectConst t = root()["enums"][table];
  TEST_ASSERT_FALSE_MESSAGE(t.isNull(), table);
  for (JsonPairConst kv : t) {
    char msg[96];
    snprintf(msg, sizeof msg, "enums.%s.%s", table, kv.key().c_str());
    int want = kv.value().as<int>();
    int got = (!strcmp(kv.key().c_str(), "-")) ? 0 : fn(kv.key().c_str());
    TEST_ASSERT_EQUAL_INT_MESSAGE(want, got, msg);
  }
}

static int key_pos_from_name(const char* s) {
  if (!strcmp(s, "off")) return PKR_KEY_OFF;
  if (!strcmp(s, "warning")) return PKR_KEY_WARNING;
  if (!strcmp(s, "critical")) return PKR_KEY_CRITICAL;
  return -1;
}

static int frame_type_from_name(const char* s) {
  struct { const char* n; int v; } T[] = {{"GAUGE_STATUS", PKR_FT_GAUGE_STATUS}, {"GAUGE_ALARM", PKR_FT_GAUGE_ALARM},
      {"SIREN_CMD_WRAPPED", PKR_FT_SIREN_CMD_WRAPPED}, {"SIREN_EVENT", PKR_FT_SIREN_EVENT}, {"BUTTON", PKR_FT_BUTTON},
      {"HEARTBEAT", PKR_FT_HEARTBEAT}, {"RELAY_BEACON", PKR_FT_RELAY_BEACON}, {"ACK", PKR_FT_ACK}};
  for (auto& t : T)
    if (!strcmp(s, t.n)) return t.v;
  return -1;
}

static void test_enums_and_constants() {
  REQUIRE_FILE();
  check_enum("frame_types", frame_type_from_name);
  check_enum("level", pkr_level_from_name);
  check_enum("action", pkr_action_from_name);
  check_enum("pattern", pkr_pattern_from_name);
  check_enum("cmd_level", pkr_cmd_level_from_name);
  check_enum("button", pkr_button_from_name);
  check_enum("key_pos", key_pos_from_name);
  check_enum("state", pkr_state_from_name);
  check_enum("event", pkr_event_from_name);
  for (JsonPairConst kv : root()["enums"]["payload_layouts"].as<JsonObjectConst>()) {
    int t = frame_type_from_name(kv.key().c_str());
    const char* st = kv.value()["struct"];
    // struct sizes: < B h H I b and 6s / 16s
    int n = 0;
    for (const char* p = st + 1; *p; p++) {
      int rep = 0;
      while (*p >= '0' && *p <= '9') rep = rep * 10 + (*p++ - '0');
      int sz = (*p == 'B' || *p == 'b' || *p == 's') ? 1 : (*p == 'h' || *p == 'H') ? 2 : (*p == 'I') ? 4 : 0;
      n += (rep ? rep : 1) * sz;
    }
    TEST_ASSERT_EQUAL_INT_MESSAGE(n, pkr_frame_payload_len(t), kv.key().c_str());
  }
  JsonObjectConst c = root()["constants"];
  TEST_ASSERT_EQUAL_STRING(PKR_PROTOCOL, c["proto"].as<const char*>());
  TEST_ASSERT_EQUAL_INT(PKR_CMD_SIG_BYTES, c["cmd_sig_bytes"].as<int>());
  TEST_ASSERT_EQUAL_INT(PKR_FRAME_MAC_LEN, c["frame_mac_bytes"].as<int>());
  TEST_ASSERT_EQUAL_INT(16, c["inner_sig_bytes"].as<int>());
  TEST_ASSERT_EQUAL_INT(PKR_SMS_SIG_BYTES, c["sms_sig_bytes"].as<int>());
  TEST_ASSERT_EQUAL_INT(PKR_FRAME_MAX_LEN, c["frame_max"].as<int>());
  TEST_ASSERT_EQUAL_INT(PKR_FRAME_MAX_PAYLOAD, c["payload_max"].as<int>());
  TEST_ASSERT_EQUAL_INT(PKR_FRAME_VERSION, c["frame_version"].as<int>());
  TEST_ASSERT_EQUAL_INT(PKR_FRAME_BROADCAST, c["broadcast"].as<int>());
  TEST_ASSERT_EQUAL_INT(PKR_LIMIT_RECENT_CMD_IDS, c["recent_ids"].as<int>());
  TEST_ASSERT_EQUAL_INT(PKR_LIMIT_CTR_BOOT_SKIP, c["send_ctr_boot_skip"].as<int>());
  TEST_ASSERT_EQUAL_INT(0, c["receive_ctr_boot_bump"].as<int>());
  TEST_ASSERT_TRUE(c["receive_ctr_boot_bump"].is<int>());
  TEST_ASSERT_EQUAL_INT(PKR_SMS_UNSYNCED_EXP_WINDOW_S, c["unsynced_exp_window_s"].as<int>());
  TEST_ASSERT_EQUAL_INT(PKR_FRAME_TS_WINDOW_S, c["frame_skew_s"].as<int>());
  TEST_ASSERT_EQUAL_INT(PKR_SMS_MAX_LEN, c["sms_max"].as<int>());
  TEST_ASSERT_EQUAL_STRING("0123456789ABCDEFGHJKMNPQRSTVWXYZ", c["crockford_alphabet"].as<const char*>());
  TEST_ASSERT_EQUAL_STRING(PKR_HKDF_SALT, c["hkdf_salt"].as<const char*>());
  // pattern defaults (the device's own tables, used when a command leaves a field at 0)
  for (JsonPairConst kv : root()["enums"]["pattern_defaults"].as<JsonObjectConst>()) {
    PlayPlan p = make_plan((uint8_t)pkr_pattern_from_name(kv.key().c_str()), false, PlanOptions());
    JsonObjectConst d = kv.value();
    TEST_ASSERT_EQUAL_UINT_MESSAGE(d["cycles"].as<unsigned>(), p.first_cycles, kv.key().c_str());
    TEST_ASSERT_EQUAL_UINT_MESSAGE(d["repeat_every_s"].as<unsigned>(), p.repeat_cycles ? p.repeat_every_s : 0, kv.key().c_str());
    TEST_ASSERT_EQUAL_UINT_MESSAGE(d["repeat_cycles"].as<unsigned>(), p.repeat_cycles, kv.key().c_str());
    TEST_ASSERT_EQUAL_UINT_MESSAGE(d["cap_on_s"].as<unsigned>(), p.cap_on_s, kv.key().c_str());
    unsigned vol = p.volume;
    for (auto& s : p.cycle)
      if (s.kind != Seg::Silence && s.volume < 100) vol = s.volume;
    TEST_ASSERT_EQUAL_UINT_MESSAGE(d["volume"].as<unsigned>(), vol, kv.key().c_str());
  }
}

static void test_key_derivation() {
  REQUIRE_FILE();
  JsonObjectConst d = root()["derivation"];
  auto rootb = from_hex(d["root_hex"]);
  int n = 0;
  for (JsonObjectConst dev : d["devices"].as<JsonArrayConst>()) {
    uint8_t k[32];
    pkr_derive_device_key(rootb.data(), rootb.size(), dev["device"], dev["kid"].as<unsigned>(), k);
    TEST_ASSERT_EQUAL_STRING_MESSAGE(dev["key_hex"].as<const char*>(), to_hex(k, 32).c_str(), dev["device"].as<const char*>());
    n++;
  }
  TEST_ASSERT_GREATER_THAN(0, n);
}

// ---------------------------------------------------------------- commands

static void test_commands() {
  REQUIRE_FILE();
  int n = 0;
  for (JsonObjectConst v : root()["commands"].as<JsonArrayConst>()) {
    std::string nm = std::string("command ") + v["name"].as<const char*>();
    uint8_t key[32];
    key_from_hex(v["key_hex"], key, nm);
    pkr_cmd_t c = cmd_of(v["cmd"], v["device"]);
    char canon[PKR_CANONICAL_MAX];
    TEST_ASSERT_GREATER_THAN_MESSAGE(0, pkr_cmd_canonical(&c, canon, sizeof canon), nm.c_str());
    TEST_ASSERT_EQUAL_STRING_MESSAGE(v["canonical"].as<const char*>(), canon, nm.c_str());
    pkr_cmd_t s = c;
    pkr_cmd_sign(&s, key, 32);
    char sig[24];
    pkr_cmd_sig_b64(&s, sig);
    TEST_ASSERT_EQUAL_STRING_MESSAGE(v["sig"].as<const char*>(), sig, nm.c_str());
    TEST_ASSERT_TRUE_MESSAGE(pkr_cmd_verify(&c, key, 32), nm.c_str());
    c.ctr++;  // any change breaks it
    TEST_ASSERT_FALSE_MESSAGE(pkr_cmd_verify(&c, key, 32), nm.c_str());
    n++;
  }
  TEST_ASSERT_GREATER_THAN(0, n);
}

// The guard's stored state, written as the device writes it, so load() applies the boot bump.
static void store_guard(MemKv& kv, JsonObjectConst st, const KeyRing& keys) {
  CommandGuard g;
  g.load(&kv);
  (void)keys;
  struct { uint32_t magic, last[3], lkt; uint8_t head; char ids[PKR_LIMIT_RECENT_CMD_IDS][PKR_ID_MAX]; } b;
  memset(&b, 0, sizeof b);
  b.magic = 0x50475231u;
  b.last[GUARD_MQTT] = st["last_ctr"]["mqtt"] | 0u;
  b.last[GUARD_SMS] = st["last_ctr"]["sms"] | 0u;
  b.last[GUARD_LORA] = st["last_ctr"]["lora"] | 0u;
  b.lkt = st["last_known_time"] | 0u;
  int i = 0;
  for (JsonVariantConst id : st["recent_ids"].as<JsonArrayConst>())
    if (i < PKR_LIMIT_RECENT_CMD_IDS) strncpy(b.ids[i++], id.as<const char*>(), PKR_ID_MAX - 1);
  b.head = (uint8_t)(i % PKR_LIMIT_RECENT_CMD_IDS);
  kv.put_blob("guard", &b, sizeof b);
}

static void test_command_checks() {
  REQUIRE_FILE();
  int steps = 0;
  for (JsonObjectConst chk : root()["command_checks"].as<JsonArrayConst>()) {
    const char* device = chk["device"];
    KeyRing keys;
    keys.set_identity(device, 0x0101);
    for (JsonPairConst kv : chk["keys_by_kid"].as<JsonObjectConst>()) {
      uint8_t k[32];
      key_from_hex(kv.value().as<const char*>(), k, "keys_by_kid");
      keys.set_self_key((uint8_t)atoi(kv.key().c_str()), k);
    }
    if (chk["keys_by_kid"].isNull()) {  // the boot check reuses the matrix's keys
      for (JsonObjectConst dev : root()["derivation"]["devices"].as<JsonArrayConst>())
        if (!strcmp(dev["device"], device)) {
          uint8_t k[32];
          key_from_hex(dev["key_hex"], k, "derivation");
          keys.set_self_key((uint8_t)dev["kid"].as<unsigned>(), k);
        }
    }
    MemKv kv;
    JsonObjectConst stored = chk["stored_state"];
    if (!stored.isNull()) store_guard(kv, stored, keys);
    CommandGuard g;
    g.load(&kv);
    if (!stored.isNull()) {
      uint32_t bump = chk["receive_ctr_boot_bump"] | 0u;  // receive counters restore exactly
      TEST_ASSERT_EQUAL_UINT32((stored["last_ctr"]["mqtt"] | 0u) + bump, g.last_ctr(GUARD_MQTT));
    }
    for (JsonObjectConst st : chk["steps"].as<JsonArrayConst>()) {
      std::string nm = std::string(chk["name"].as<const char*>()) + ": " + st["label"].as<const char*>();
      const char* via = st["via"];
      uint8_t gv = !strcmp(via, "lora") ? GUARD_LORA : !strcmp(via, "sms") ? GUARD_SMS : GUARD_MQTT;
      bool synced = !st["now"].isNull();
      uint32_t now = st["now"] | 0u;
      pkr_cmd_t c = cmd_of(st["cmd"], device);
      int r = g.accept_cmd(c, keys, gv, synced, now);
      TEST_ASSERT_EQUAL_STRING_MESSAGE(st["reason"].as<const char*>(), reason_name(r), nm.c_str());
      TEST_ASSERT_EQUAL_MESSAGE(st["accept"].as<bool>(), r == 0, nm.c_str());
      steps++;
    }
  }
  TEST_ASSERT_GREATER_THAN(0, steps);
}

// ---------------------------------------------------------------- frames

static std::vector<uint8_t> payload_from_fields(int type, JsonObjectConst f) {
  std::vector<uint8_t> out(PKR_FRAME_MAX_PAYLOAD);
  int n = pkr_frame_payload_len(type);
  out.resize(n > 0 ? (size_t)n : 0);
  switch (type) {
    case PKR_FT_GAUGE_STATUS:
    case PKR_FT_GAUGE_ALARM: {
      pkr_gauge_payload_t g{f["level"].as<uint8_t>(), f["stage_cm"].as<int16_t>(), f["rise_10min_cm"].as<int16_t>(),
                            f["quality"].as<uint8_t>(), f["cloud_ok"].as<uint8_t>(), f["rain_15min_tenths_mm"].as<uint16_t>()};
      pkr_gauge_payload_encode(&g, out.data());
      break;
    }
    case PKR_FT_BUTTON: {
      pkr_button_payload_t b{f["button"].as<uint8_t>(), f["key_pos"].as<uint8_t>(), f["hold_ms"].as<uint16_t>()};
      pkr_button_payload_encode(&b, out.data());
      break;
    }
    case PKR_FT_HEARTBEAT: {
      pkr_heartbeat_payload_t h{f["state"].as<uint8_t>(), f["soc"].as<uint8_t>(), f["batt_dv"].as<uint16_t>(),
                                f["faults"].as<uint16_t>(), f["outbox"].as<uint16_t>()};
      pkr_heartbeat_payload_encode(&h, out.data());
      break;
    }
    case PKR_FT_RELAY_BEACON: {
      pkr_beacon_payload_t b{f["bus_dv"].as<uint16_t>(), f["bus_ma"].as<uint16_t>(), f["soc"].as<uint8_t>(),
                             f["noise_dbm"].as<int8_t>()};
      pkr_beacon_payload_encode(&b, out.data());
      break;
    }
    case PKR_FT_ACK: {
      pkr_ack_payload_t a{f["acked_src"].as<uint16_t>(), f["acked_ctr"].as<uint32_t>()};
      pkr_ack_payload_encode(&a, out.data());
      break;
    }
    case PKR_FT_SIREN_EVENT: {
      pkr_siren_event_payload_t e{};
      e.type = f["type"];
      auto id = from_hex(f["cmd_id48"]);
      memcpy(e.cmd_id48, id.data(), 6);
      e.verified = f["verified"];
      e.amp_a_x10 = f["amp_a_x10"];
      e.spl_rise = f["spl_rise_db"];
      pkr_siren_event_payload_encode(&e, out.data());
      break;
    }
    case PKR_FT_SIREN_CMD_WRAPPED: {
      pkr_wrapped_cmd_t w{};
      auto id = from_hex(f["cmd_id48"]);
      memcpy(w.cmd_id48, id.data(), 6);
      w.action = f["action"];
      w.pattern = f["pattern"];
      w.level = f["level"];
      w.cycles = f["cycles"];
      w.cap_on_s = f["cap_on_s"];
      w.exp = f["exp"];
      w.ctr = f["ctr"];
      auto sig = from_hex(f["sig16"]);
      memcpy(w.sig16, sig.data(), 16);
      pkr_wrapped_encode(&w, out.data());
      break;
    }
    default: TEST_FAIL_MESSAGE("unknown frame type in the vectors");
  }
  return out;
}

static void test_frames() {
  REQUIRE_FILE();
  int n = 0;
  for (JsonObjectConst v : root()["frames"].as<JsonArrayConst>()) {
    std::string nm = std::string("frame ") + v["name"].as<const char*>();
    uint8_t key[32];
    key_from_hex(v["key_hex"], key, nm);
    JsonObjectConst h = v["header"];
    int type = h["type"];
    auto payload = payload_from_fields(type, v["payload_fields"]);
    TEST_ASSERT_EQUAL_STRING_MESSAGE(v["payload_hex"].as<const char*>(), to_hex(payload.data(), payload.size()).c_str(),
                                     (nm + ": payload").c_str());
    pkr_frame_t f{};
    f.ver = h["ver"];
    f.type = (uint8_t)type;
    f.src = h["src"];
    f.dst = h["dst"];
    f.ctr = h["ctr"];
    f.ts = h["ts"];
    f.len = h["len"];
    memcpy(f.payload, payload.data(), payload.size());
    uint8_t buf[PKR_FRAME_MAX_LEN];
    int len = pkr_frame_encode(&f, key, 32, buf, sizeof buf);
    TEST_ASSERT_GREATER_THAN_MESSAGE(0, len, nm.c_str());
    TEST_ASSERT_EQUAL_STRING_MESSAGE(v["frame_hex"].as<const char*>(), to_hex(buf, (size_t)len).c_str(), nm.c_str());
    TEST_ASSERT_EQUAL_STRING_MESSAGE(v["mac_hex"].as<const char*>(), to_hex(f.mac, 8).c_str(), (nm + ": mac").c_str());
    pkr_frame_t g;
    TEST_ASSERT_EQUAL_INT_MESSAGE(PKR_FRAME_OK, pkr_frame_parse(buf, (size_t)len, &g), nm.c_str());
    TEST_ASSERT_TRUE_MESSAGE(pkr_frame_mac_ok(buf, (size_t)len, key, 32), nm.c_str());
    JsonObjectConst in = v["inner"];
    if (!in.isNull()) {  // the compact command and the siren's own 16-byte signature
      uint8_t sk[32];
      key_from_hex(in["siren_key_hex"], sk, nm + " inner");
      pkr_wrapped_cmd_t w;
      pkr_wrapped_decode(payload.data(), &w);
      std::string signed_bytes = std::string("PKR1C|") + in["device"].as<const char*>() + "|";
      std::string sb_hex = to_hex((const uint8_t*)signed_bytes.data(), signed_bytes.size()) + to_hex(payload.data(), 20);
      TEST_ASSERT_EQUAL_STRING_MESSAGE(in["signed_bytes_hex"].as<const char*>(), sb_hex.c_str(), (nm + ": inner bytes").c_str());
      TEST_ASSERT_TRUE_MESSAGE(pkr_wrapped_verify(&w, in["device"], sk, 32), (nm + ": inner sig").c_str());
      pkr_wrapped_cmd_t mine = w;
      memset(mine.sig16, 0, 16);
      pkr_wrapped_sign(&mine, in["device"], sk, 32);
      TEST_ASSERT_EQUAL_MEMORY_MESSAGE(w.sig16, mine.sig16, 16, (nm + ": inner sign").c_str());
      // the fields, from the full command it was made from
      JsonObjectConst fc = in["from_cmd"];
      uint8_t id48[6];
      pkr_cmd_id48(fc["id"], id48);
      TEST_ASSERT_EQUAL_MEMORY_MESSAGE(id48, w.cmd_id48, 6, (nm + ": cmd_id48").c_str());
      TEST_ASSERT_EQUAL_INT(pkr_action_from_name(fc["action"]), w.action);
      TEST_ASSERT_EQUAL_INT(pkr_pattern_from_name(fc["pattern"]), w.pattern);
      TEST_ASSERT_EQUAL_INT(pkr_cmd_level_from_name(fc["level"]), w.level);
      w.cap_on_s++;
      TEST_ASSERT_FALSE(pkr_wrapped_verify(&w, in["device"], sk, 32));
    }
    n++;
  }
  TEST_ASSERT_GREATER_THAN(0, n);
}

static void test_frame_rejects() {
  REQUIRE_FILE();
  int n = 0;
  for (JsonObjectConst fr : root()["frame_rejects"].as<JsonArrayConst>()) {
    const char* receiver = fr["receiver"];
    KeyRing keys;
    uint16_t self_addr = 0x0101;
    for (JsonObjectConst v : root()["frames"].as<JsonArrayConst>())  // the receiver's address from the frames
      if (!strcmp(v["src_device"], receiver)) self_addr = v["header"]["src"].as<uint16_t>();
    keys.set_identity(receiver, self_addr);
    uint8_t siren_key[32] = {0};
    for (JsonObjectConst dev : root()["derivation"]["devices"].as<JsonArrayConst>())
      if (!strcmp(dev["device"], receiver) && dev["kid"].as<int>() == 1) key_from_hex(dev["key_hex"], siren_key, "receiver");
    for (JsonPairConst kv : fr["senders"].as<JsonObjectConst>()) {
      Sender s;
      s.addr = (uint16_t)strtoul(kv.key().c_str(), nullptr, 0);
      strncpy(s.device, kv.value()["device"], sizeof s.device - 1);
      key_from_hex(kv.value()["key_hex"], s.key, s.device);
      const char* names[8];
      size_t k = 0;
      for (JsonVariantConst r : kv.value()["roles"].as<JsonArrayConst>())
        if (k < 8) names[k++] = r.as<const char*>();
      s.roles = roles_from_names(names, k);
      keys.add_sender(s);
    }
    MemKv kv;
    FrameReceiver rx;
    rx.begin(&keys, &kv);
    uint32_t now = root()["constants"]["now"];
    auto first = from_hex(fr["accepted_first"]["frame_hex"]);
    TEST_ASSERT_EQUAL_INT_MESSAGE(0, rx.receive(first.data(), first.size(), now, true).reason, "accepted_first");
    for (JsonObjectConst c : fr["cases"].as<JsonArrayConst>()) {
      std::string nm = std::string("frame_rejects ") + c["name"].as<const char*>();
      auto data = from_hex(c["frame_hex"]);
      bool synced = !c["now"].isNull();
      RxResult r = rx.receive(data.data(), data.size(), c["now"] | 0u, synced);
      const char* want = c["expect_reason"];
      if (!strcmp(want, "ok_outer_bad_inner")) {
        TEST_ASSERT_EQUAL_INT_MESSAGE(0, r.reason, (nm + ": outer").c_str());
        pkr_wrapped_cmd_t w;
        pkr_wrapped_decode(r.frame.payload, &w);
        TEST_ASSERT_FALSE_MESSAGE(pkr_wrapped_verify(&w, receiver, siren_key, 32), (nm + ": inner").c_str());
      } else {
        TEST_ASSERT_EQUAL_STRING_MESSAGE(want, reason_name(r.reason), nm.c_str());
      }
      n++;
    }
    // a reboot: the receiver's counters as the device wrote them (through, on accept), then the cases
    JsonObjectConst ar = fr["after_reboot"];
    TEST_ASSERT_FALSE_MESSAGE(ar.isNull(), "frame_rejects.after_reboot");
    MemKv kv2;
    for (JsonPairConst s : ar["stored_last_ctr"].as<JsonObjectConst>()) {
      char k[16];
      snprintf(k, sizeof k, "rx%04x", (unsigned)strtoul(s.key().c_str(), nullptr, 0));
      kv2.put_u32(k, s.value().as<uint32_t>());
    }
    FrameReceiver rebooted;
    rebooted.begin(&keys, &kv2);
    int accepted = 0;
    for (JsonObjectConst c : ar["cases"].as<JsonArrayConst>()) {
      std::string nm = std::string("after_reboot ") + c["name"].as<const char*>();
      auto data = from_hex(c["frame_hex"]);
      RxResult r = rebooted.receive(data.data(), data.size(), c["now"] | 0u, !c["now"].isNull());
      TEST_ASSERT_EQUAL_STRING_MESSAGE(c["expect_reason"].as<const char*>(), reason_name(r.reason), nm.c_str());
      accepted += r.reason == 0;
      n++;
    }
    TEST_ASSERT_EQUAL_INT_MESSAGE(1, accepted, "after a reboot the gauge's next frame is accepted once");
  }
  TEST_ASSERT_GREATER_THAN(0, n);
}

// ---------------------------------------------------------------- SMS

static char sms_letter(const char* table, const char* name) {
  const char* v = root()["enums"][table][name];
  return v ? v[0] : 0;
}

static void test_sms() {
  REQUIRE_FILE();
  JsonObjectConst sms = root()["sms"];
  uint8_t key[32] = {0};
  const char* device = nullptr;
  int n = 0;
  for (JsonObjectConst v : sms["good"].as<JsonArrayConst>()) {
    std::string nm = std::string("sms ") + v["name"].as<const char*>();
    key_from_hex(v["key_hex"], key, nm);
    device = v["device"];
    pkr_sms_t s{};
    strncpy(s.device, device, sizeof s.device - 1);
    s.action = sms_letter("sms_action", v["action"]);
    s.level = sms_letter("sms_level", v["level"]);
    s.ctr = v["ctr"];
    s.exp = v["exp"];
    char ss[128];
    pkr_sms_signed_string(&s, ss, sizeof ss);
    TEST_ASSERT_EQUAL_STRING_MESSAGE(v["signing_string"].as<const char*>(), ss, nm.c_str());
    char text[170];
    int len = pkr_sms_format(&s, key, 32, text, sizeof text);
    TEST_ASSERT_EQUAL_STRING_MESSAGE(v["text"].as<const char*>(), text, nm.c_str());
    TEST_ASSERT_EQUAL_INT_MESSAGE(v["length"].as<int>(), len, nm.c_str());
    pkr_sms_t p;
    TEST_ASSERT_EQUAL_INT_MESSAGE(PKR_SMS_OK, pkr_sms_parse(text, (size_t)len, &p), nm.c_str());
    TEST_ASSERT_TRUE_MESSAGE(pkr_sms_verify(&p, key, 32), nm.c_str());
    n++;
  }
  TEST_ASSERT_GREATER_THAN(0, n);
  // the sequenced checks, as siren_model.CommandVerifier.accept_sms
  KeyRing keys;
  keys.set_identity(device, 0x0101);
  keys.set_self_key(1, key);
  MemKv kv;
  CommandGuard g;
  g.load(&kv);
  uint32_t now = root()["constants"]["now"];
  const char* first = sms["checks"]["first_accepted"];
  TEST_ASSERT_EQUAL_INT(0, g.accept_sms(first, strlen(first), true, keys, 1, true, now, nullptr));
  for (JsonObjectConst c : sms["checks"]["cases"].as<JsonArrayConst>()) {
    std::string nm = std::string("sms check ") + c["name"].as<const char*>();
    const char* text = c["text"];
    bool synced = !c["now"].isNull();
    int r;
    if (!strcmp(c["name"], "case_insensitive_prefix")) {  // the generator runs this one on a fresh verifier
      MemKv kv2;
      CommandGuard fresh;
      fresh.load(&kv2);
      r = fresh.accept_sms(text, strlen(text), c["sender_allowed"].as<bool>(), keys, 1, synced, c["now"] | 0u, nullptr);
    } else {
      r = g.accept_sms(text, strlen(text), c["sender_allowed"].as<bool>(), keys, 1, synced, c["now"] | 0u, nullptr);
    }
    TEST_ASSERT_EQUAL_STRING_MESSAGE(c["reason"].as<const char*>(), reason_name(r), nm.c_str());
    TEST_ASSERT_EQUAL_MESSAGE(c["accept"].as<bool>(), r == 0, nm.c_str());
  }
  JsonObjectConst sh = sms["sender_hash"];
  char h[65];
  pkr_sms_sender_hash(sh["salt"], sh["e164"], h);
  TEST_ASSERT_EQUAL_STRING(sh["sha256_hex"].as<const char*>(), h);
}

// ---------------------------------------------------------------- verified

static void test_verification() {
  REQUIRE_FILE();
  int n = 0;
  for (JsonObjectConst v : root()["verification"].as<JsonArrayConst>()) {
    JsonObjectConst m = v["meas"];
    bool mic_dead = false;
    for (JsonVariantConst f : v["faults"].as<JsonArrayConst>())
      if (!strcmp(f.as<const char*>(), "mic_dead")) mic_dead = true;
    bool got = is_verified(!m["amp_a"].isNull(), m["amp_a"] | 0.0f, !m["spl_rise_db"].isNull(), m["spl_rise_db"] | 0.0f,
                           v["amp_a_ref"] | 0.0f, v["spl_rise_min_db"] | 0.0f, mic_dead);
    TEST_ASSERT_EQUAL_MESSAGE(v["verified"].as<bool>(), got, v["name"].as<const char*>());
    n++;
  }
  TEST_ASSERT_GREATER_THAN(0, n);
  char msg[200];
  snprintf(msg, sizeof msg, "golden vectors matched: %s", g_path.c_str());
  TEST_MESSAGE(msg);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_enums_and_constants);
  RUN_TEST(test_key_derivation);
  RUN_TEST(test_commands);
  RUN_TEST(test_command_checks);
  RUN_TEST(test_frames);
  RUN_TEST(test_frame_rejects);
  RUN_TEST(test_sms);
  RUN_TEST(test_verification);
  return UNITY_END();
}
