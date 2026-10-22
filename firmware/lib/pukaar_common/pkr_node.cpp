#include "pkr_node.h"

#include <ArduinoJson.h>
#include <math.h>
#include <string.h>

#include "pkr_addr.h"

namespace pkr {

static void copy_if(JsonObjectConst o, const char* key, char* out, size_t cap) {
  const char* v = o[key];
  if (v && strlen(v) < cap) strcpy(out, v);
}

template <typename T>
static void num_if(JsonObjectConst o, const char* key, T* out) {
  if (o[key].is<T>()) *out = o[key].as<T>();
}

int parse_node_settings(const char* json, size_t len, NodeSettings* s) {
  JsonDocument d;
  if (deserializeJson(d, json, len)) return PKR_REASON_BAD_FORMAT;
  JsonObjectConst o = d.as<JsonObjectConst>();
  if (o.isNull()) return PKR_REASON_BAD_FORMAT;
  copy_if(o, "village", s->village, sizeof s->village);
  copy_if(o, "endpoint", s->endpoint, sizeof s->endpoint);
  copy_if(o, "apn", s->apn, sizeof s->apn);
  const char* sensor = o["sensor"];
  if (sensor) s->sensor = !strcmp(sensor, "none") ? SENSOR_NONE : !strcmp(sensor, "ultrasonic") ? SENSOR_ULTRASONIC : SENSOR_RADAR;
  num_if(o, "mount_height_cm", &s->mount_height_cm);
  num_if(o, "watch_cm", &s->gauge.watch_cm);
  num_if(o, "warning_cm", &s->gauge.warning_cm);
  num_if(o, "critical_cm", &s->gauge.critical_cm);
  num_if(o, "siren_level_cm", &s->gauge.siren_level_cm);
  num_if(o, "siren_clear_cm", &s->gauge.siren_clear_cm);
  num_if(o, "blind_mm", &s->gauge.blind_mm);
  num_if(o, "max_mm", &s->gauge.max_mm);
  num_if(o, "burst_rise_cm", &s->gauge.burst_rise_cm);
  num_if(o, "mm_per_tip", &s->mm_per_tip);
  num_if(o, "sleep_s", &s->sleep_s);
  num_if(o, "burst_sleep_s", &s->burst_sleep_s);
  num_if(o, "hibernate_mv", &s->hibernate_mv);
  num_if(o, "low_mv", &s->low_mv);
  if (!(s->mm_per_tip > 0.0f && s->mm_per_tip <= 2.0f)) s->mm_per_tip = 0.2f;
  if (s->burst_sleep_s < 30) s->burst_sleep_s = 30;
  if (s->sleep_s < s->burst_sleep_s) s->sleep_s = s->burst_sleep_s;
  JsonArrayConst ds = o["downstream"];
  if (!ds.isNull()) {
    s->n_downstream = 0;
    for (JsonVariantConst v : ds) {
      if (s->n_downstream >= 4) break;
      Downstream& x = s->downstream[s->n_downstream];
      const char* dev = v.is<const char*>() ? v.as<const char*>() : v["device"].as<const char*>();
      if (!dev || !dev[0] || strlen(dev) >= sizeof x.device) continue;
      strcpy(x.device, dev);
      uint32_t addr = v["lora_addr"].is<uint32_t>() ? v["lora_addr"].as<uint32_t>() : pkr_lora_addr(dev);
      if (addr == 0 || addr >= PKR_FRAME_BROADCAST) continue;
      x.addr = (uint16_t)addr;
      s->n_downstream++;
    }
  }
  return 0;
}

void gauge_plan(pkr_gauge_state_t* st, const NodeSettings& s, const GaugeInputs& in, uint32_t seq, GaugePlan* p) {
  *p = GaugePlan();
  bool level_sensor = s.sensor != SENSOR_NONE;
  uint16_t err = in.err;
  if (level_sensor) err |= in.burst.err;
  if (in.battery_mv && in.battery_mv < s.low_mv) err |= PKR_ERR_LOW_VOLTAGE;
  bool good = level_sensor && in.burst.distance_mm &&
              !(err & (PKR_ERR_NO_ECHO | PKR_ERR_FEW_SAMPLES | PKR_ERR_HIGH_SPREAD | PKR_ERR_SENSOR_RANGE));
  float stage = level_sensor && in.burst.distance_mm ? s.mount_height_cm - in.burst.distance_mm / 10.0f : NAN;

  pkr_gauge_reading_t r{};
  r.stage_cm = stage;
  r.distance_mm = level_sensor ? in.burst.distance_mm : 0;
  r.blind_hit = level_sensor ? in.burst.blind_hit : 0;
  r.good = good ? 1 : 0;
  r.now = in.now;
  r.tips_last_min = in.rain.last_min;
  pkr_gauge_step(st, &s.gauge, &r, &p->d);
  if (!level_sensor) {  // a rain node: no river, so never a river level or an alarm
    p->d.level = PKR_LEVEL_NORMAL;
    p->d.crit = p->d.warn = p->d.send_alarm = p->d.beacon = 0;
    p->d.burst = in.rain.last_min >= s.gauge.burst_tips_per_min;
  }
  p->stage_cm = good ? stage : NAN;

  GaugeRecord& rec = p->rec;
  rec.at = in.now;
  rec.seq = seq;
  rec.distance_mm = level_sensor ? in.burst.distance_mm : 0;
  rec.level_mm = (level_sensor && in.burst.distance_mm) ? (int16_t)lroundf(stage * 10.0f) : 0;
  rec.battery_mv = in.battery_mv;
  rec.solar_mv = in.solar_mv;
  rec.err = err;
  rec.iqr_mm = level_sensor ? in.burst.iqr_mm : 0;
  rec.samples_ok = level_sensor ? in.burst.ok : 0;
  rec.samples_n = level_sensor ? in.burst.n : 0;
  rec.temp_c = in.temp_c;
  rec.rain_err = in.rain.err;
  rec.rain_tips_total = in.rain.tips_total;
  rec.rain_tips_window = in.rain.window;
  rec.rain_max_tips_1min = in.rain.max_1min;
  rec.rain_min_tip_ms = in.rain.min_tip_ms;
  rec.rain_bounce = in.rain.bounce;
  // no idea of the time, or a river gauge with no distance at all: nothing worth sending
  p->record = in.clock_ok && (!level_sensor || in.burst.distance_mm);

  uint8_t quality = rec.samples_n ? (uint8_t)(100u * rec.samples_ok / rec.samples_n) : (level_sensor ? 0 : 100);
  pkr_gauge_payload_from(&p->d, p->stage_cm, quality, in.cloud_ok, in.rain.rain_15min_tenths, &p->status);

  p->radio = !(in.battery_mv && in.battery_mv < s.hibernate_mv);
  p->alarm = p->radio && p->d.send_alarm && s.n_downstream > 0;
  // a Critical the siren must keep hearing forces the burst cadence (the siren's autonomy re-arms on it)
  p->sleep_s = !p->radio ? s.hibernate_sleep_s : (p->d.burst || p->d.send_alarm) ? s.burst_sleep_s : s.sleep_s;
}

}  // namespace pkr
