/* Tipping-bucket counter (section 3.2). Plain C with no libc beyond stdint, so the same code can
 * be built into the ULP-RISC-V program (firmware/ulp/rain_counter.c) and the host tests.
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

#ifdef __cplusplus
}
#endif
#endif
