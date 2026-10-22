#include "pkr_rain.h"

#include "schema.h"

void pkr_rain_init(pkr_rain_t *r, uint8_t active_level, uint8_t idle_level_now) {
  /* tips_total is deliberately not touched by a re-init: the caller restores it from RTC/NVS */
  r->bounce = 0;
  r->last_tip_ms = r->last_edge_ms = 0;
  r->min_tip_ms = 0xFFFFFFFFu;
  r->have_tip = r->have_edge = 0;
  r->active_level = active_level;
  r->stable = r->cand = idle_level_now;
  r->cand_n = 0;
  r->cand_since_ms = 0;
  r->debounce_ms = PKR_RAIN_DEBOUNCE_MS;
  r->min_tip_interval_ms = PKR_RAIN_MIN_TIP_MS;
}

int pkr_rain_edge(pkr_rain_t *r, uint32_t now_ms) {
  if (r->have_edge) {
    uint32_t gap = now_ms - r->last_edge_ms;
    if (gap < r->min_tip_ms) r->min_tip_ms = gap;
  }
  r->have_edge = 1;
  r->last_edge_ms = now_ms;
  if (r->have_tip && (uint32_t)(now_ms - r->last_tip_ms) < r->min_tip_interval_ms) {
    r->bounce++;
    return 2;
  }
  r->have_tip = 1;
  r->last_tip_ms = now_ms;
  r->tips_total++;
  return 1;
}

int pkr_rain_poll(pkr_rain_t *r, uint8_t level, uint32_t now_ms) {
  level = level ? 1 : 0;
  if (level == r->stable) {
    r->cand = level;
    r->cand_n = 0;
    return 0;
  }
  if (level != r->cand || r->cand_n == 0) {
    r->cand = level;
    r->cand_n = 1;
    r->cand_since_ms = now_ms;
    return 0;
  }
  if (r->cand_n < 255) r->cand_n++;
  if (r->cand_n >= PKR_RAIN_DEBOUNCE_SAMPLES && (uint32_t)(now_ms - r->cand_since_ms) >= r->debounce_ms) {
    r->stable = level;
    r->cand_n = 0;
    if (level == r->active_level) return pkr_rain_edge(r, now_ms);
  }
  return 0;
}

void pkr_rain_report_reset(pkr_rain_t *r) { r->min_tip_ms = 0xFFFFFFFFu; }

void pkr_rain_minutes_init(pkr_rain_minutes_t *m) {
  for (int i = 0; i < 16; i++) {
    m->minute[i] = 0xFFFFFFFFu;
    m->count[i] = 0;
  }
}

void pkr_rain_minutes_add(pkr_rain_minutes_t *m, uint32_t now_s, uint16_t tips) {
  uint32_t minute = now_s / 60;
  int slot = (int)(minute % 16);
  if (m->minute[slot] != minute) {
    m->minute[slot] = minute;
    m->count[slot] = 0;
  }
  uint32_t c = (uint32_t)m->count[slot] + tips;
  m->count[slot] = c > 0xFFFF ? 0xFFFF : (uint16_t)c;
}

uint32_t pkr_rain_minutes_sum(const pkr_rain_minutes_t *m, uint32_t now_s, unsigned minutes) {
  uint32_t now_min = now_s / 60, sum = 0;
  if (minutes > 16) minutes = 16;
  for (int i = 0; i < 16; i++)
    if (m->minute[i] != 0xFFFFFFFFu && now_min - m->minute[i] < minutes) sum += m->count[i];
  return sum;
}

uint16_t pkr_rain_minutes_peak(const pkr_rain_minutes_t *m, uint32_t now_s, unsigned minutes) {
  uint32_t now_min = now_s / 60;
  uint16_t peak = 0;
  if (minutes > 16) minutes = 16;
  for (int i = 0; i < 16; i++)
    if (m->minute[i] != 0xFFFFFFFFu && now_min - m->minute[i] < minutes && m->count[i] > peak) peak = m->count[i];
  return peak;
}

uint16_t pkr_rain_15min_tenths(const pkr_rain_minutes_t *m, uint32_t now_s, uint16_t mm_per_tip_x1000) {
  uint32_t tips = pkr_rain_minutes_sum(m, now_s, 15);
  uint32_t tenths = (tips * mm_per_tip_x1000 + 50) / 100;
  return tenths > 0xFFFF ? 0xFFFF : (uint16_t)tenths;
}
