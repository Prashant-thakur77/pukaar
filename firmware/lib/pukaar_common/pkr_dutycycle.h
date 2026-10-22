/* Duty-cycle governor (section 3.5, G.S.R. 853(E) Table II): a sliding one-hour airtime budget,
 * 90 s for nodes (2.5 %) and 360 s for the relay (10 %). Telemetry stops at 70 % of the budget so
 * the rest is kept for alarm frames.
 *
 * Airtime is kept in one-minute buckets. A frame is charged to the minute it starts in, and the
 * window counts the current minute plus the previous 60 whole minutes: a superset of the true
 * last 3600 s, so the sum can only over-count (by at most one minute's worth). Over-counting is
 * the safe direction for a legal limit. */
#ifndef PKR_DUTYCYCLE_H
#define PKR_DUTYCYCLE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
  uint32_t budget_ms;
  uint8_t telemetry_pct;
  uint32_t minute[64];
  uint32_t used_ms[64];
} pkr_duty_t;

void pkr_duty_init(pkr_duty_t *d, uint32_t budget_ms, uint8_t telemetry_pct);
uint32_t pkr_duty_used_ms(const pkr_duty_t *d, uint32_t now_s);
/* 1 if a frame of airtime_ms may start now. Alarm frames may use the whole budget, telemetry
 * only telemetry_pct of it. */
int pkr_duty_can_send(const pkr_duty_t *d, uint32_t now_s, uint32_t airtime_ms, int is_alarm);
void pkr_duty_record(pkr_duty_t *d, uint32_t now_s, uint32_t airtime_ms);

#ifdef __cplusplus
}
#endif
#endif
