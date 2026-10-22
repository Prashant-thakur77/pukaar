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
