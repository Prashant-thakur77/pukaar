/* Tipping-bucket counter (section 3.2). Plain C with no libc beyond stdint, so the same code can
 * be built into the ULP-RISC-V program (firmware/ulp_riscv/rain_counter.c) and the host tests.
 *
 *  - poll every 5 ms; a new level counts only after 3 equal samples AND 25 ms stable;
 *  - a tip is the debounced edge into the active level (reed closed);
 *  - two tips closer than 400 ms: the second is bounce (bounce++, no rain);
 *  - tips_total is a cumulative u32, never cleared; consumers take wrap-safe differences. */
#ifndef PKR_RAIN_H
#define PKR_RAIN_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
  uint32_t tips_total;
  uint32_t bounce;
  uint32_t last_tip_ms;   /* last counted tip */
  uint32_t last_edge_ms;  /* last debounced edge, counted or not */
  uint32_t min_tip_ms;    /* shortest edge-to-edge interval since pkr_rain_report_reset; 0xFFFFFFFF none */
  uint8_t have_tip, have_edge;
  uint8_t active_level;   /* level when the reed is closed (0 for a reed to GND with a pull-up) */
  uint8_t stable, cand, cand_n;
  uint32_t cand_since_ms;
  uint16_t debounce_ms, min_tip_interval_ms;
} pkr_rain_t;

void pkr_rain_init(pkr_rain_t *r, uint8_t active_level, uint8_t idle_level_now);
/* One 5 ms poll of the reed level. Returns 1 if a tip was counted, 2 if it was bounce, else 0. */
int pkr_rain_poll(pkr_rain_t *r, uint8_t level, uint32_t now_ms);
/* An already-debounced activation (interrupt or wake-on-tip path). Same return values. */
int pkr_rain_edge(pkr_rain_t *r, uint32_t now_ms);
void pkr_rain_report_reset(pkr_rain_t *r);
static inline uint32_t pkr_rain_delta(uint32_t now_total, uint32_t prev_total) { return now_total - prev_total; }

/* Per-minute tip counts for the last 16 minutes: the 15-minute total, the peak minute and the
 * burst trigger (>= 2 tips a minute, about 24 mm/h at 0.2 mm a tip). */
typedef struct {
  uint32_t minute[16];
  uint16_t count[16];
} pkr_rain_minutes_t;

void pkr_rain_minutes_init(pkr_rain_minutes_t *m);
void pkr_rain_minutes_add(pkr_rain_minutes_t *m, uint32_t now_s, uint16_t tips);
uint32_t pkr_rain_minutes_sum(const pkr_rain_minutes_t *m, uint32_t now_s, unsigned minutes);
uint16_t pkr_rain_minutes_peak(const pkr_rain_minutes_t *m, uint32_t now_s, unsigned minutes);
/* 15-minute rain in tenths of a mm (the GAUGE_STATUS field), saturating at 65535. */
uint16_t pkr_rain_15min_tenths(const pkr_rain_minutes_t *m, uint32_t now_s, uint16_t mm_per_tip_x1000);

/* ---- the counter as one block of state, kept in RTC memory across deep sleep ----
 *
 * The ULP-RISC-V program (firmware/ulp_riscv/rain_counter.c) runs every PKR_RAIN_POLL_MS from its own timer:
 * one pkr_ulp_rain_step per run. It has no clock, so its time is its own run count: `tick` 5 ms polls
 * (ms = tick * 5, wrap-safe like every pkr_rain time; seconds = tick / 200, which lasts 248 days). It
 * asks for the main CPU (returns 1) the first time a minute reaches the burst rate, so heavy rain moves
 * the gauge to the 60 s cadence without waiting for the 300 s timer.
 *
 * The Arduino build cannot link a ULP program (that needs the ESP-IDF ULP build), so it wakes on each
 * tip instead and calls pkr_ulp_rain_tip itself, with the wall clock: the same state, the same math. */
#define PKR_ULP_RAIN_MAGIC 0x504B5231u /* "PKR1": the state survived (a cold boot clears RTC memory) */

typedef struct {
  uint32_t magic;
  uint32_t tick;          /* ULP runs (the wake-on-tip build leaves it at 0) */
  uint32_t clock_s;       /* the counter's time in s: tick / 200 on the ULP, the wall clock otherwise */
  uint32_t wake_minute;   /* the minute that last asked for the main CPU (0xFFFFFFFF none) */
  pkr_rain_t rain;
  pkr_rain_minutes_t minutes;
} pkr_ulp_rain_t;

void pkr_ulp_rain_init(pkr_ulp_rain_t *u, uint8_t active_level, uint8_t level_now, uint32_t tips_total);
/* One ULP run: polls the reed level. Returns 1 when the main CPU should wake now (burst rate reached). */
int pkr_ulp_rain_step(pkr_ulp_rain_t *u, uint8_t level, uint16_t burst_tips_per_min);
/* A debounced tip seen by the main CPU (wake-on-tip build), at wall-clock ms and s. Same return as step. */
int pkr_ulp_rain_tip(pkr_ulp_rain_t *u, uint32_t now_ms, uint32_t now_s, uint16_t burst_tips_per_min);
/* The counter's own "now" in seconds (what pkr_rain_take_report wants on the ULP build). */
static inline uint32_t pkr_ulp_rain_now_s(const pkr_ulp_rain_t *u) { return u->clock_s; }

/* What one reading reports (payload v3 rain fields), since the previous reading. */
typedef struct {
  uint32_t last_total;    /* tips_total at the previous reading */
  uint32_t last_bounce;
  uint32_t last_s;        /* counter time of the previous reading (0 = none) */
  uint8_t have;
} pkr_rain_mark_t;

typedef struct {
  uint32_t tips_total;
  uint16_t window;        /* tips since the previous reading (saturating) */
  uint16_t max_1min;      /* busiest minute since then (at most the last 16 minutes) */
  uint16_t min_tip_ms;    /* shortest edge-to-edge gap since then, 0xFFFF none */
  uint16_t bounce;        /* bounces since then */
  uint16_t last_min;      /* tips in the current minute (the burst trigger) */
  uint16_t rain_15min_tenths;
  uint8_t err;            /* PKR_RAIN_ERR_* */
} pkr_rain_report_t;

/* Reads the state for a reading at counter time now_s, moves the mark on and restarts min_tip_ms.
 * counter_reset: the state was lost (cold boot, magic gone) and restarted from the NVS mirror;
 * ulp_fault: the ULP stopped running (tick did not move). */
void pkr_rain_take_report(pkr_ulp_rain_t *u, pkr_rain_mark_t *mark, uint32_t now_s, uint16_t mm_per_tip_x1000,
                          int counter_reset, int ulp_fault, pkr_rain_report_t *out);

#ifdef __cplusplus
}
#endif
#endif
