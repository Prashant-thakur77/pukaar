#include "pkr_event.h"

#include "pkr_store.h"

#include <ArduinoJson.h>
#include <stdio.h>
#include <string.h>

namespace pkr {

// days since 1970-01-01 -> civil date (Howard Hinnant's algorithm, public domain)
static void civil(uint32_t days, int* y, unsigned* m, unsigned* d) {
  int32_t z = (int32_t)days + 719468;
  int32_t era = z / 146097;
  uint32_t doe = (uint32_t)(z - era * 146097);
  uint32_t yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
  int32_t yy = (int32_t)yoe + era * 400;
  uint32_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
  uint32_t mp = (5 * doy + 2) / 153;
  *d = doy - (153 * mp + 2) / 5 + 1;
  *m = mp < 10 ? mp + 3 : mp - 9;
  *y = yy + (*m <= 2 ? 1 : 0);
}

void iso8601(uint32_t t_unix, char out[21]) {
  int y;
  unsigned mo, d;
  civil(t_unix / 86400u, &y, &mo, &d);
  uint32_t s = t_unix % 86400u;
  snprintf(out, 21, "%04d-%02u-%02uT%02lu:%02lu:%02luZ", y, mo, d, (unsigned long)(s / 3600), (unsigned long)(s / 60 % 60),
           (unsigned long)(s % 60));
}

int minutes_ist(uint32_t t_unix) { return (int)(((t_unix + PKR_LIMIT_IST_OFFSET_S) % 86400u) / 60u); }

void hhmm_ist(uint32_t t_unix, char out[6]) {
  unsigned m = (unsigned)minutes_ist(t_unix) % 1440u, h = m / 60u, mm = m % 60u;
  out[0] = (char)('0' + h / 10u);
  out[1] = (char)('0' + h % 10u);
  out[2] = ':';
  out[3] = (char)('0' + mm / 10u);
  out[4] = (char)('0' + mm % 10u);
  out[5] = 0;
}

static const char* via_name(uint8_t v) { return pkr_via_name(v); }

const char* fault_name(uint16_t bit) {
  switch (bit) {
    case FAULT_AMP: return "amp";
    case FAULT_MIC_DEAD: return "mic_dead";
    case FAULT_DFPLAYER: return "dfplayer";
    case FAULT_CATALOG: return "catalog";
    case FAULT_LORA: return "lora";
    case FAULT_MODEM: return "modem";
    case FAULT_NO_KEYS: return "no_keys";
    case FAULT_TAMPER: return "tamper";
    case FAULT_SIREN_LINE: return "siren_line";
    case FAULT_INA226: return "ina226";
    default: return "?";
  }
}

static float round1(float x) { return (float)((int)(x * 10.0f + (x >= 0 ? 0.5f : -0.5f))) / 10.0f; }

size_t event_to_json(const Event& e, uint32_t boot, uint32_t seq, char* out, size_t cap) {
  JsonDocument d;
  d["v"] = 1;
  d["seq"] = seq;
  d["boot"] = boot;
  if (e.at) {
    char at[21];
    iso8601(e.at, at);
    d["at"] = at;
  }
  d["type"] = pkr_event_name(e.type);
  if (e.cmd_id[0]) d["cmd_id"] = e.cmd_id;
  if (e.pattern) d["pattern"] = pkr_pattern_name(e.pattern);
  if (e.via) d["via"] = via_name(e.via);
  if (e.src) d["src"] = pkr_src_name(e.src);
  if (e.reason) d["reason"] = pkr_reason_name(e.reason);
  if (e.button[0]) d["button"] = e.button;
  if (e.level[0]) d["level"] = e.level;
  if (e.lora_acked >= 0) d["lora_acked"] = e.lora_acked == 1;
  if (e.frame_src[0]) d["frame_src"] = e.frame_src;
  if (e.has_meas) {
    JsonObject m = d["meas"].to<JsonObject>();
    if (e.meas.amp_a >= 0) m["amp_a"] = round1(e.meas.amp_a);
    if (e.meas.amp_a_ref >= 0) m["amp_a_ref"] = round1(e.meas.amp_a_ref);
    if (e.meas.siren_a >= 0) m["siren_a"] = round1(e.meas.siren_a);
    if (e.meas.spl_rise_db > -999) m["spl_rise_db"] = round1(e.meas.spl_rise_db);
    if (e.meas.ambient_db_rel > -999) m["ambient_db_rel"] = round1(e.meas.ambient_db_rel);
    if (e.meas.soc >= 0) m["soc"] = e.meas.soc;
    if (e.meas.batt_mv >= 0) m["batt_mv"] = e.meas.batt_mv;
  }
  if (e.would_sound >= 0) d["would_sound"] = e.would_sound == 1;
  if (e.test_kind) d["kind"] = e.test_kind == 1 ? "silent" : "audible";
  if (e.ok >= 0) d["ok"] = e.ok == 1;
  if (e.detail[0]) d["detail"] = e.detail;
  if (e.faults) {
    JsonArray f = d["faults"].to<JsonArray>();
    for (uint16_t bit = 1; bit && bit <= FAULT_INA226; bit <<= 1)
      if (e.faults & bit) f.add(fault_name(bit));
  }
  if (e.fallback) d["fallback"] = true;
  if (e.simulated) d["simulated"] = true;
  size_t n = serializeJson(d, out, cap);
  return n >= cap ? 0 : n;
}

size_t heartbeat_to_json(const Heartbeat& h, char* out, size_t cap) {
  JsonDocument d;
  d["v"] = 1;
  if (h.at) {
    char at[21];
    iso8601(h.at, at);
    d["at"] = at;
  }
  d["seq"] = h.seq;
  d["boot"] = h.boot;
  d["state"] = pkr_state_name(h.state);
  if (h.soc >= 0) d["soc"] = h.soc;
  if (h.batt_mv >= 0) d["batt_mv"] = h.batt_mv;
  if (h.solar_wh_today >= 0) d["solar_wh_today"] = round1(h.solar_wh_today);
  if (h.temp_c > -999) d["temp_c"] = round1(h.temp_c);
  if (h.rssi) d["rssi"] = h.rssi;
  if (h.lora_noise_dbm) d["lora_noise_dbm"] = h.lora_noise_dbm;
  d["fw"] = h.fw;
  d["clips"] = h.clips;
  d["uptime_s"] = h.uptime_s;
  d["outbox_depth"] = h.outbox_depth;
  JsonArray f = d["faults"].to<JsonArray>();
  for (uint16_t bit = 1; bit && bit <= FAULT_INA226; bit <<= 1)
    if (h.faults & bit) f.add(fault_name(bit));
  d["path"] = h.path;
  if (h.simulated) d["simulated"] = true;
  size_t n = serializeJson(d, out, cap);
  return n >= cap ? 0 : n;
}

size_t gauge_reading_json(const GaugeRecord& r, const GaugeJsonOpts& o, char* out, size_t cap) {
  JsonDocument d;
  d["v"] = 3;
  char at[21];
  iso8601(r.at, at);
  d["at"] = at;
  d["seq"] = r.seq;
  d["boot"] = o.boot;
  if (o.has_level_sensor) {
    d["distance_mm"] = r.distance_mm;
    d["water_level_cm"] = round1(r.level_mm / 10.0f);
    d["samples_ok"] = r.samples_ok;
    d["samples_n"] = r.samples_n;
    d["iqr_mm"] = r.iqr_mm;
    d["quality"] = r.samples_n ? 100u * r.samples_ok / r.samples_n : 0u;
  }
  d["err"] = r.err;
  d["temp_c"] = r.temp_c;
  d["battery_mv"] = r.battery_mv;
  d["solar_mv"] = r.solar_mv;
  d["rain_tips_total"] = r.rain_tips_total;
  d["rain_tips_window"] = r.rain_tips_window;
  d["rain_mm_per_tip"] = o.mm_per_tip;
  d["rain_max_tips_1min"] = r.rain_max_tips_1min;
  if (r.rain_min_tip_ms != 0xFFFF) d["rain_min_tip_ms"] = r.rain_min_tip_ms;
  d["rain_bounce"] = r.rain_bounce;
  d["rain_err"] = r.rain_err;
  d["fw"] = o.fw;
  if (o.reset_cause) d["reset_cause"] = o.reset_cause;
  d["buffered"] = o.buffered;
  if (o.simulated) d["simulated"] = true;
  size_t n = serializeJson(d, out, cap);
  return n >= cap ? 0 : n;
}

// ---------------------------------------------------------------- parsing

static bool copy_str(JsonVariantConst v, char* out, size_t cap, bool required, bool null_ok) {
  if (v.isNull()) {
    out[0] = 0;
    return !required || null_ok;
  }
  if (!v.is<const char*>()) return false;
  const char* s = v.as<const char*>();
  size_t n = strlen(s);
  if (n >= cap) return false;
  memcpy(out, s, n + 1);
  return true;
}

static bool copy_u32(JsonVariantConst v, uint32_t* out, bool required) {
  if (v.isNull()) {
    *out = 0;
    return !required;
  }
  if (!v.is<uint32_t>()) return false;  // a JSON integer in range; strings and floats are refused
  *out = v.as<uint32_t>();
  return true;
}

static JsonObjectConst find_cmd(JsonDocument& d) {
  JsonObjectConst root = d.as<JsonObjectConst>();
  JsonObjectConst st = root["state"];
  if (!st.isNull()) {
    JsonObjectConst des = st["desired"];
    if (!des.isNull() && !des["cmd"].isNull()) return des["cmd"];
    if (!st["cmd"].isNull()) return st["cmd"];
  }
  if (!root["cmd"].isNull()) return root["cmd"];
  return root;
}

int parse_cmd_json(const char* json, size_t len, pkr_cmd_t* c) {
  memset(c, 0, sizeof *c);
  JsonDocument d;
  if (deserializeJson(d, json, len)) return PKR_REASON_BAD_FORMAT;
  JsonObjectConst o = find_cmd(d);
  if (o.isNull()) return PKR_REASON_BAD_FORMAT;
  bool ok = copy_str(o["id"], c->id, sizeof c->id, true, false) &&
            copy_str(o["device"], c->device, sizeof c->device, true, false) &&
            copy_str(o["action"], c->action, sizeof c->action, true, false) &&
            copy_str(o["pattern"], c->pattern, sizeof c->pattern, false, true) &&
            copy_str(o["clip"], c->clip, sizeof c->clip, false, true) &&
            copy_str(o["clip_sha256_16"], c->clip_sha256_16, sizeof c->clip_sha256_16, false, true) &&
            copy_str(o["level"], c->level, sizeof c->level, false, true) &&
            copy_str(o["alert_id"], c->alert_id, sizeof c->alert_id, false, true) &&
            copy_str(o["src"], c->src, sizeof c->src, true, false) &&
            copy_u32(o["cycles"], &c->cycles, false) && copy_u32(o["repeat_every_s"], &c->repeat_every_s, false) &&
            copy_u32(o["repeat_cycles"], &c->repeat_cycles, false) && copy_u32(o["cap_on_s"], &c->cap_on_s, false) &&
            copy_u32(o["volume"], &c->volume, false) && copy_u32(o["iat"], &c->iat, true) &&
            copy_u32(o["exp"], &c->exp, true) && copy_u32(o["ctr"], &c->ctr, true) && copy_u32(o["kid"], &c->kid, true);
  if (!ok) return PKR_REASON_BAD_FORMAT;
  JsonVariantConst sig = o["sig"];
  if (!sig.is<const char*>() || pkr_cmd_set_sig_b64(c, sig.as<const char*>()) < 0) return PKR_REASON_BAD_FORMAT;
  return 0;
}

int parse_config_json(const char* json, size_t len, DeviceConfig* cfg) {
  JsonDocument d;
  if (deserializeJson(d, json, len)) return PKR_REASON_BAD_FORMAT;
  JsonObjectConst root = d.as<JsonObjectConst>();
  JsonObjectConst st = root["state"];
  if (!st.isNull()) root = !st["desired"].isNull() ? st["desired"].as<JsonObjectConst>() : st;
  JsonObjectConst lora = root["lora"];
  if (!lora.isNull()) {
    if (lora["freq_hz"].is<uint32_t>()) cfg->lora_freq_hz = lora["freq_hz"];
    if (lora["sf"].is<uint8_t>()) cfg->lora_sf = lora["sf"];
    if (lora["pwr_dbm"].is<uint8_t>()) cfg->lora_pwr_dbm = lora["pwr_dbm"];
    if (lora["apc"].is<bool>()) cfg->lora_apc = lora["apc"];
  }
  JsonObjectConst senders = root["senders"];
  if (!senders.isNull()) {
    cfg->n_senders = 0;
    for (JsonPairConst kv : senders) {
      if (cfg->n_senders >= 8) break;
      SenderConfig& s = cfg->senders[cfg->n_senders];
      if (strlen(kv.key().c_str()) >= sizeof s.device) continue;
      strcpy(s.device, kv.key().c_str());
      s.kid = kv.value()["kid"] | 1;
      const char* names[8];
      size_t n = 0;
      for (JsonVariantConst r : kv.value()["roles"].as<JsonArrayConst>())
        if (n < 8 && r.is<const char*>()) names[n++] = r.as<const char*>();
      s.roles = roles_from_names(names, n);
      cfg->n_senders++;
    }
  }
  JsonArrayConst allow = root["sms_allow_sha256"];
  if (!allow.isNull()) {
    cfg->n_sms_allow = 0;
    for (JsonVariantConst h : allow) {
      if (cfg->n_sms_allow >= 8) break;
      if (!h.is<const char*>() || strlen(h.as<const char*>()) != 64) continue;
      strcpy(cfg->sms_allow[cfg->n_sms_allow++], h.as<const char*>());
    }
  }
  JsonObjectConst a = root["autonomy"];
  if (!a.isNull()) {
    if (a["enabled"].is<bool>()) cfg->autonomy.enabled = a["enabled"];
    if (a["fast_path"].is<bool>()) cfg->autonomy.fast_path = a["fast_path"];
    if (a["shadow_mode"].is<bool>()) cfg->autonomy.shadow_mode = a["shadow_mode"];
    if (a["cloud_silence_s"].is<uint32_t>()) cfg->autonomy.cloud_silence_s = a["cloud_silence_s"];
    if (a["cap_on_s"].is<uint32_t>()) cfg->autonomy.cap_on_s = a["cap_on_s"];
    JsonArrayConst up = a["upstream"];
    if (!up.isNull()) {
      cfg->autonomy.n_upstream = 0;
      for (JsonVariantConst u : up) {
        if (cfg->autonomy.n_upstream >= 4) break;
        if (!u.is<const char*>() || strlen(u.as<const char*>()) >= PKR_DEVICE_MAX) continue;
        strcpy(cfg->autonomy.upstream[cfg->autonomy.n_upstream++], u.as<const char*>());
      }
    }
  }
  if (root["voice_slot"].is<uint8_t>()) cfg->voice_slot = root["voice_slot"].as<uint8_t>() ? 1 : 0;
  if (root["amp_a_ref"].is<float>()) cfg->amp_a_ref = root["amp_a_ref"];
  if (root["siren_a_ref"].is<float>()) cfg->siren_a_ref = root["siren_a_ref"];
  if (root["spl_rise_min_db"].is<float>()) cfg->spl_rise_min_db = root["spl_rise_min_db"];
  if (root["catalog"].is<const char*>() && strlen(root["catalog"].as<const char*>()) < sizeof cfg->catalog)
    strcpy(cfg->catalog, root["catalog"].as<const char*>());
  if (root["drill_with_c1"].is<bool>()) cfg->drill_with_c1 = root["drill_with_c1"];
  return 0;
}

}  // namespace pkr
