#include "pkr_gauge.h"

#include <math.h>

#include "schema.h"

int pkr_count_at_or_above(const float recent[3], float mark) {
  int n = 0;
  for (int i = 0; i < 3; i++)
    if (!isnan(recent[i]) && recent[i] >= mark) n++;
  return n;
}

int pkr_two_of_three(const float recent[3], float mark) { return pkr_count_at_or_above(recent, mark) >= 2; }

int pkr_all_three(const float recent[3], float mark, int above) {
  for (int i = 0; i < 3; i++) {
    if (isnan(recent[i])) return 0;
    if (above ? recent[i] < mark : recent[i] >= mark) return 0;
  }
  return 1;
}

static void sort_u16(uint16_t *v, int n) { /* insertion sort: at most 16 samples */
  for (int i = 1; i < n; i++) {
    uint16_t x = v[i];
    int j = i - 1;
    while (j >= 0 && v[j] > x) {
      v[j + 1] = v[j];
      j--;
    }
    v[j + 1] = x;
  }
}

void pkr_burst_reduce(const uint16_t *samples, int n, uint16_t blind_mm, uint16_t max_mm, pkr_burst_t *out) {
  uint16_t v[16], kept[16];
  int k = 0, blind = 0, range_hit = 0;
  if (n > 16) n = 16;
  if (n < 0) n = 0;
  out->distance_mm = 0;
  out->ok = 0;
  out->n = (uint8_t)n;
  out->iqr_mm = 0;
  out->err = 0;
  for (int i = 0; i < n; i++) {
    uint16_t d = samples[i];
    if (d == 0) continue; /* no echo or no reply */
    if ((uint32_t)d <= (uint32_t)blind_mm + 50u) blind++;
    if (d <= blind_mm || d >= max_mm) range_hit = 1;
    else v[k++] = d;
  }
  out->blind_hit = (uint8_t)(n > 0 && blind * 2 >= n);
  if (k == 0) {
    out->err = range_hit ? PKR_ERR_SENSOR_RANGE : PKR_ERR_NO_ECHO;
    return;
  }
  sort_u16(v, k);
  uint16_t med = v[k / 2];
  uint16_t iqr = k >= 4 ? (uint16_t)(v[(k - 1) * 3 / 4] - v[(k - 1) / 4]) : 0;
  uint32_t limit = 3u * iqr > 30u ? 3u * iqr : 30u;
  int m = 0;
  for (int i = 0; i < k; i++) {
    int diff = (int)v[i] - (int)med;
    if ((uint32_t)(diff < 0 ? -diff : diff) <= limit) kept[m++] = v[i];
  }
  out->distance_mm = kept[m / 2]; /* still sorted */
  out->ok = (uint8_t)m;
  out->iqr_mm = iqr;
  if (m * 2 < n) out->err |= PKR_ERR_FEW_SAMPLES;
  if (iqr > 150) out->err |= PKR_ERR_HIGH_SPREAD;
}

void pkr_gauge_payload_from(const pkr_gauge_decision_t *d, float stage_cm, uint8_t quality, int cloud_ok,
                            uint16_t rain_15min_tenths, pkr_gauge_payload_t *out) {
  out->level = (uint8_t)d->level;
  out->stage_cm = isnan(stage_cm) ? 0 : (int16_t)lroundf(stage_cm < -32000 ? -32000 : stage_cm > 32000 ? 32000 : stage_cm);
  out->rise_10min_cm = d->rise_cm;
  out->quality = quality;
  out->cloud_ok = cloud_ok ? 1 : 0;
  out->rain_15min_tenths_mm = rain_15min_tenths;
}

void pkr_gauge_state_init(pkr_gauge_state_t *s) {
  for (int i = 0; i < 3; i++) {
    s->recent[i] = NAN;
    s->blind[i] = 0;
  }
  s->last_normal_at = 0;
  s->beacon_latched = 0;
}

void pkr_gauge_step(pkr_gauge_state_t *s, const pkr_gauge_cfg_t *cfg, const pkr_gauge_reading_t *r,
                    pkr_gauge_decision_t *d) {
  /* a blocked face (spider, bag, ice) reads as the shortest distance, i.e. "flood": a reading in
   * the blind zone or within 50 mm of it is never good */
  int good = r->good && !isnan(r->stage_cm) && r->distance_mm > (uint32_t)cfg->blind_mm + 50u && !r->blind_hit;
  float stage = good ? r->stage_cm : NAN;
  s->recent[0] = s->recent[1];
  s->recent[1] = s->recent[2];
  s->recent[2] = stage;
  s->blind[0] = s->blind[1];
  s->blind[1] = s->blind[2];
  s->blind[2] = r->blind_hit ? 1 : 0;
  if (good && stage < cfg->watch_cm) s->last_normal_at = r->now;

  d->crit = pkr_two_of_three(s->recent, cfg->critical_cm);
  d->warn = pkr_two_of_three(s->recent, cfg->warning_cm);
  d->level = d->crit ? PKR_LEVEL_CRITICAL
             : d->warn ? PKR_LEVEL_WARNING
             : pkr_two_of_three(s->recent, cfg->watch_cm) ? PKR_LEVEL_WATCH
                                                          : PKR_LEVEL_NORMAL;
  int blind_2of3 = (s->blind[0] + s->blind[1] + s->blind[2]) >= 2;
  int normal_24h = s->last_normal_at != 0 && r->now >= s->last_normal_at && r->now - s->last_normal_at <= 86400u;
  d->sane = normal_24h && !blind_2of3;
  d->send_alarm = d->crit && d->sane;

  if (!s->beacon_latched && pkr_all_three(s->recent, cfg->siren_level_cm, 1)) s->beacon_latched = 1;
  if (s->beacon_latched && pkr_all_three(s->recent, cfg->siren_clear_cm, 0)) s->beacon_latched = 0;
  d->beacon = s->beacon_latched;

  d->rise_cm = 0;
  if (!isnan(s->recent[0]) && !isnan(s->recent[2])) d->rise_cm = (int16_t)lroundf(s->recent[2] - s->recent[0]);
  d->burst = (d->rise_cm >= cfg->burst_rise_cm) || (r->tips_last_min >= cfg->burst_tips_per_min);
}
