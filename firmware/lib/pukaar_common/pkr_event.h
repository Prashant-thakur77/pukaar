// Device events (section 5.1 envelope) and the JSON the device publishes and reads.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "pkr_command.h"
#include "schema.h"

namespace pkr {

struct Meas {
  float amp_a = -1, amp_a_ref = -1, siren_a = -1, spl_rise_db = -999, ambient_db_rel = -999;
  int soc = -1, batt_mv = -1;
};

struct Event {
  uint8_t type = 0;          // PKR_EVT_*
  uint32_t at = 0;           // unix s (0 = clock unsynced: "at" omitted, the server stamps it)
  char cmd_id[PKR_ID_MAX] = {0};
  uint8_t pattern = 0;       // PKR_PATTERN_* (0 omitted)
  uint8_t via = 0;           // PKR_VIA_*
  uint8_t src = 0;           // PKR_SRC_*
  uint8_t reason = 0;        // PKR_REASON_*
  char button[16] = {0};     // key_critical | key_warning | water_rising | ack | stop
  char level[12] = {0};      // manual_trigger: warning | critical
  int8_t lora_acked = -1;    // manual_trigger from a box: a siren ACKed the LoRa frame (0/1)
  uint16_t faults = 0;       // FAULT_* bits, sent as a list of names
  char frame_src[PKR_DEVICE_MAX] = {0};
  char alert_id[PKR_ID_MAX] = {0};  // a box "ack": the alert its shadow showed
  bool has_meas = false;
  Meas meas;
  int8_t would_sound = -1;   // shadow-mode autonomy: 0/1, -1 omitted
  uint8_t test_kind = 0;     // 1 silent, 2 audible
  int8_t ok = -1;            // test_result: 0/1
  char detail[96] = {0};
  bool fallback = false;     // verification after switching to the LEDC tone
  bool simulated = false;
};

// iso8601 "YYYY-MM-DDTHH:MM:SSZ" (21 bytes incl. NUL) without relying on the libc's gmtime.
void iso8601(uint32_t t_unix, char out[21]);
// HH:MM in IST, for the SMS texts officers read.
void hhmm_ist(uint32_t t_unix, char out[6]);
// Minutes since midnight IST.
int minutes_ist(uint32_t t_unix);

// One event as the `event` topic body (and an element of `backfill`). Returns the length or 0.
size_t event_to_json(const Event& e, uint32_t boot, uint32_t seq, char* out, size_t cap);

struct Heartbeat {
  uint32_t at = 0, seq = 0, boot = 0, uptime_s = 0;
  uint8_t state = 0;
  int soc = -1, batt_mv = -1, rssi = 0, lora_noise_dbm = 0;
  float solar_wh_today = -1, temp_c = -999;
  const char* fw = "";
  const char* clips = "";
  uint32_t outbox_depth = 0;
  uint16_t faults = 0;
  const char* path = "cell";
  bool simulated = false;
};
size_t heartbeat_to_json(const Heartbeat& h, char* out, size_t cap);

// Fault bits (heartbeat `faults` names, and the HEARTBEAT frame's u16).
enum : uint16_t {
  FAULT_AMP = 1,
  FAULT_MIC_DEAD = 2,
  FAULT_DFPLAYER = 4,
  FAULT_CATALOG = 8,
  FAULT_LORA = 16,
  FAULT_MODEM = 32,
  FAULT_NO_KEYS = 64,
  FAULT_TAMPER = 128,
  FAULT_SIREN_LINE = 256,
  FAULT_INA226 = 512,
};
const char* fault_name(uint16_t bit);

// ---- gauge payload v3 (section 5.6): payload v2 plus the rain fields ----
struct GaugeRecord {        // 40 bytes, kept in RTC memory across deep sleep
  uint32_t at, seq;
  uint16_t distance_mm;     // 0 = no reading (or a rain node)
  int16_t level_mm;
  uint16_t battery_mv, solar_mv, err, iqr_mm;
  uint8_t samples_ok, samples_n;
  int8_t temp_c;
  uint8_t rain_err;
  uint32_t rain_tips_total;     // cumulative, never cleared
  uint16_t rain_tips_window;    // since the previous reading
  uint16_t rain_max_tips_1min;
  uint16_t rain_min_tip_ms;     // 0xFFFF = no two tips in the interval
  uint16_t rain_bounce;
};
struct GaugeJsonOpts {
  uint32_t boot = 0;
  float mm_per_tip = 0.2f;
  const char* fw = "";
  const char* reset_cause = nullptr;  // live reading only
  bool buffered = false;
  bool has_level_sensor = true;       // false: a rain node (no distance, no stage)
  bool simulated = false;
};
size_t gauge_reading_json(const GaugeRecord& r, const GaugeJsonOpts& o, char* out, size_t cap);

// ---- parsing what the cloud sends ----
// A siren command from any of: the shadow document {"state":{"desired":{"cmd":{...}}}}, a delta
// {"state":{"cmd":{...}}}, {"cmd":{...}}, or the bare cmd object. Returns 0, or a PKR_REASON_*
// (bad_format) if a field is missing, of the wrong type or too long.
int parse_cmd_json(const char* json, size_t len, pkr_cmd_t* out);

struct AutonomyConfig {
  bool enabled = false, fast_path = false, shadow_mode = true;
  char upstream[4][PKR_DEVICE_MAX] = {};
  uint8_t n_upstream = 0;
  uint32_t cloud_silence_s = PKR_LIMIT_CLOUD_SILENCE_S;
  uint32_t cap_on_s = PKR_LIMIT_AUTONOMY_CAP_S;
};

struct SenderConfig {
  char device[PKR_DEVICE_MAX] = {0};
  uint8_t kid = 1;
  uint8_t roles = 0;
};

// The `config` named shadow (section 5.1) as the siren and box use it.
struct DeviceConfig {
  uint32_t lora_freq_hz = PKR_RADIO_FREQ_PRIMARY_HZ;
  uint8_t lora_sf = PKR_RADIO_SF;
  uint8_t lora_pwr_dbm = PKR_RADIO_TX_DBM;
  bool lora_apc = true;
  SenderConfig senders[8];
  uint8_t n_senders = 0;
  char sms_allow[8][65] = {};
  uint8_t n_sms_allow = 0;
  AutonomyConfig autonomy;
  uint8_t voice_slot = 0;
  float amp_a_ref = 3.3f, siren_a_ref = 1.5f, spl_rise_min_db = 15.0f;
  char catalog[24] = {0};
  bool drill_with_c1 = false;
};
// Applies the fields present in a config document ({"state":{"desired":{...}}}, a delta or the
// bare object) on top of `cfg`. Returns 0 or PKR_REASON_BAD_FORMAT.
int parse_config_json(const char* json, size_t len, DeviceConfig* cfg);

}  // namespace pkr
