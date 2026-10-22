// What the gauge v3, the rain node, the pradhan box and the relay are told at provisioning (an NVS
// string "cfg" in namespace "pkr-cfg", written by firmware/tools/provision.py), and the gauge's
// per-wake plan (section 7.1): the reading it records, what it says on LoRa and how long it sleeps.
// Host-tested; the images only read sensors and move bytes.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "pkr_command.h"
#include "pkr_event.h"
#include "pkr_gauge.h"
#include "pkr_rain.h"

namespace pkr {

struct Downstream {
  char device[PKR_DEVICE_MAX] = {0};
  uint16_t addr = 0;
};

enum SensorKind : uint8_t { SENSOR_RADAR = 0, SENSOR_ULTRASONIC = 1, SENSOR_NONE = 2 };

// The provisioned config, every field optional (defaults below). Shape:
// {"village":"gohar","endpoint":"xxxx-ats.iot.ap-south-1.amazonaws.com","apn":"internet",
//  "sensor":"radar"|"ultrasonic"|"none","mount_height_cm":420,
//  "watch_cm":200,"warning_cm":250,"critical_cm":300,"siren_level_cm":300,"siren_clear_cm":280,
//  "blind_mm":150,"max_mm":40000,"mm_per_tip":0.2,"sleep_s":300,"burst_sleep_s":60,
//  "hibernate_mv":11800,"low_mv":12300,
//  "downstream":["siren-thunag-01", {"device":"siren-thunag-02","lora_addr":259}]}
// A downstream given as a bare id gets the default address (pkr_lora_addr). The thresholds are the
// village's (data/villages.json); the server still applies its own datum and rules to every reading.
struct NodeSettings {
  char village[24] = "unset";
  char endpoint[96] = {0};
  char apn[32] = "internet";
  uint8_t sensor = SENSOR_RADAR;
  float mount_height_cm = 420.0f;
  pkr_gauge_cfg_t gauge = {200.0f, 250.0f, 300.0f, 300.0f, 280.0f, 150, 40000, 10.0f, PKR_RAIN_BURST_TIPS_PER_MIN};
  float mm_per_tip = 0.2f;
  uint32_t sleep_s = 300, burst_sleep_s = 60, hibernate_sleep_s = 1800;
  uint16_t hibernate_mv = 11800, low_mv = 12300;  // a 12.8 V LiFePO4 pack (v3 moves to 12 V)
  Downstream downstream[4];
  uint8_t n_downstream = 0;
};
// Applies the fields present. Returns 0 or PKR_REASON_BAD_FORMAT (nothing applied on bad JSON).
int parse_node_settings(const char* json, size_t len, NodeSettings* s);

// ---------------------------------------------------------------- the gauge's wake

struct GaugeInputs {
  pkr_burst_t burst{};        // the sensor burst (n = 0 for a rain node)
  uint16_t err = 0;           // bits known before the burst: clock unsynced, low voltage, watchdog reset, overflow
  uint16_t battery_mv = 0, solar_mv = 0;
  int8_t temp_c = 0;
  uint32_t now = 0;           // unix s (the RTC keeps time across deep sleep)
  bool clock_ok = false;      // a sane time: without one nothing is recorded
  pkr_rain_report_t rain{};
  bool cloud_ok = false;      // the last PUBACK within 600 s
};

struct GaugePlan {
  GaugeRecord rec{};
  bool record = false;        // push this reading (live now, or buffered)
  float stage_cm = 0;         // NaN when there is no good reading
  pkr_gauge_decision_t d{};
  pkr_gauge_payload_t status{};  // GAUGE_STATUS, broadcast every wake; GAUGE_ALARM has the same payload
  bool alarm = false;         // GAUGE_ALARM to each downstream siren this wake
  bool radio = true;          // false in the hibernate tier: no LoRa, no modem
  uint32_t sleep_s = 300;
};

// One wake's decisions. The rain node (sensor none) never alarms and has no stage; rain alone moves
// any node to the burst cadence (2 tips a minute, about 24 mm/h at 0.2 mm) and is in GAUGE_STATUS.
void gauge_plan(pkr_gauge_state_t* st, const NodeSettings& s, const GaugeInputs& in, uint32_t seq, GaugePlan* out);

}  // namespace pkr
