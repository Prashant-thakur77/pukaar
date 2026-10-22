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

void pkr_ulp_rain_init(pkr_ulp_rain_t *u, uint8_t active_level, uint8_t level_now, uint32_t tips_total) {
  u->magic = PKR_ULP_RAIN_MAGIC;
  u->tick = 0;
  u->clock_s = 0;
  u->wake_minute = 0xFFFFFFFFu;
  pkr_rain_init(&u->rain, active_level, level_now);
  u->rain.tips_total = tips_total;
  pkr_rain_minutes_init(&u->minutes);
}

static int counted(pkr_ulp_rain_t *u, uint32_t now_s, uint16_t burst) {
  pkr_rain_minutes_add(&u->minutes, now_s, 1);
  uint32_t minute = now_s / 60u;
  if (pkr_rain_minutes_sum(&u->minutes, now_s, 1) >= burst && u->wake_minute != minute) {
    u->wake_minute = minute;
    return 1;
  }
  return 0;
}

int pkr_ulp_rain_step(pkr_ulp_rain_t *u, uint8_t level, uint16_t burst) {
  u->tick++;
  u->clock_s = u->tick / (1000u / PKR_RAIN_POLL_MS);
  if (pkr_rain_poll(&u->rain, level, u->tick * PKR_RAIN_POLL_MS) != 1) return 0;
  return counted(u, u->clock_s, burst);
}

int pkr_ulp_rain_tip(pkr_ulp_rain_t *u, uint32_t now_ms, uint32_t now_s, uint16_t burst) {
  u->clock_s = now_s;
  if (pkr_rain_edge(&u->rain, now_ms) != 1) return 0;
  return counted(u, now_s, burst);
}

void pkr_rain_take_report(pkr_ulp_rain_t *u, pkr_rain_mark_t *mark, uint32_t now_s, uint16_t mm_per_tip_x1000,
                          int counter_reset, int ulp_fault, pkr_rain_report_t *out) {
  uint32_t total = u->rain.tips_total, bounce = u->rain.bounce;
  uint32_t window = 0, b = 0;
  if (mark->have) {
    window = total - mark->last_total; /* wrap-safe */
    b = bounce - mark->last_bounce;
    /* a restarted state (bounce back to 0) or a counter behind the mark: not rain */
    if (counter_reset || window > 0x7FFFFFFFu) window = 0;
    if (b > 0x7FFFFFFFu) b = 0;
  }
  unsigned since_min = 16;
  if (mark->have && now_s >= mark->last_s) {
    uint32_t m = (now_s - mark->last_s + 59u) / 60u + 1u;
    since_min = m < 16 ? (unsigned)m : 16;
  }
  out->tips_total = total;
  out->window = window > 0xFFFF ? 0xFFFF : (uint16_t)window;
  out->max_1min = pkr_rain_minutes_peak(&u->minutes, now_s, since_min);
  out->min_tip_ms = u->rain.min_tip_ms > 0xFFFE ? 0xFFFF : (uint16_t)u->rain.min_tip_ms;
  out->bounce = b > 0xFFFF ? 0xFFFF : (uint16_t)b;
  out->last_min = pkr_rain_minutes_peak(&u->minutes, now_s, 2); /* this minute or the one before */
  out->rain_15min_tenths = pkr_rain_15min_tenths(&u->minutes, now_s, mm_per_tip_x1000);
  out->err = (uint8_t)((b ? PKR_RAIN_ERR_BOUNCE : 0) | (counter_reset ? PKR_RAIN_ERR_COUNTER_RESET : 0) |
                       (ulp_fault ? PKR_RAIN_ERR_ULP_FAULT : 0));
  mark->last_total = total;
  mark->last_bounce = bounce;
  mark->last_s = now_s;
  mark->have = 1;
  pkr_rain_report_reset(&u->rain);
}

uint16_t pkr_rain_15min_tenths(const pkr_rain_minutes_t *m, uint32_t now_s, uint16_t mm_per_tip_x1000) {
  uint32_t tips = pkr_rain_minutes_sum(m, now_s, 15);
  uint32_t tenths = (tips * mm_per_tip_x1000 + 50) / 100;
  return tenths > 0xFFFF ? 0xFFFF : (uint16_t)tenths;
}
