/* Gauge v3 decisions (section 7.1), separated from the drivers so they can be tested:
 * 2-of-3 confirmation with NaN for bad readings, blind-zone sanity, the v2 bridge-beacon latch,
 * burst mode, and whether this wake sends GAUGE_ALARM. */
#ifndef PKR_GAUGE_H
#define PKR_GAUGE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Counts how many of the last three values are >= mark; NaN never counts. */
int pkr_count_at_or_above(const float recent[3], float mark);
/* 2 of the last 3 good readings at or above mark. */
int pkr_two_of_three(const float recent[3], float mark);
/* all 3 at or above (above=1), or all 3 below (above=0); any NaN -> 0. The v2 bridge latch. */
int pkr_all_three(const float recent[3], float mark, int above);

typedef struct {
  float watch_cm, warning_cm, critical_cm;
  float siren_level_cm, siren_clear_cm;  /* bridge beacon (v2 3-of-3 latch) */
  uint16_t blind_mm, max_mm;
  float burst_rise_cm;                   /* 10 cm over 3 readings */
  uint16_t burst_tips_per_min;           /* 2 */
} pkr_gauge_cfg_t;

/* Kept in RTC memory across deep sleep (and the useful parts in NVS). */
typedef struct {
  float recent[3];          /* last three stages, newest last; NaN = not a good reading */
  uint8_t blind[3];         /* that wake's burst hit the blind zone */
  uint32_t last_normal_at;  /* unix s of the last good reading below watch (0 = never) */
  uint8_t beacon_latched;
} pkr_gauge_state_t;

typedef struct {
  float stage_cm;           /* NaN if no good reading */
  uint16_t distance_mm;     /* 0 if none */
  uint8_t blind_hit;        /* the burst saw the blind zone (a blocked face reads as "flood") */
  uint8_t good;             /* v2 good (no bad err bits) */
  uint32_t now;             /* unix s */
  uint16_t tips_last_min;   /* for the burst trigger */
} pkr_gauge_reading_t;

typedef struct {
  int level;                /* PKR_LEVEL_*: confirmed 2-of-3 */
  int crit, warn;           /* 2-of-3 at critical / warning */
  int sane;                 /* had a normal reading in 24 h and not blind in 2 of the last 3 */
  int send_alarm;           /* crit && sane: GAUGE_ALARM to the downstream sirens */
  int beacon;               /* bridge beacon latched (B1) */
  int burst;                /* next sleep is the 60 s burst cadence */
  int16_t rise_cm;          /* newest minus oldest of the last three good stages (0 if unknown) */
} pkr_gauge_decision_t;

void pkr_gauge_state_init(pkr_gauge_state_t *s);
/* Pushes the reading and decides. good readings must also clear the blind zone + 50 mm. */
void pkr_gauge_step(pkr_gauge_state_t *s, const pkr_gauge_cfg_t *cfg, const pkr_gauge_reading_t *r,
                    pkr_gauge_decision_t *d);

#ifdef __cplusplus
}
#endif
#endif
