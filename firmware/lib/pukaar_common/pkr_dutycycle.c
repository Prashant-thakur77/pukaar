#include "pkr_dutycycle.h"

void pkr_duty_init(pkr_duty_t *d, uint32_t budget_ms, uint8_t telemetry_pct) {
  d->budget_ms = budget_ms;
  d->telemetry_pct = telemetry_pct;
  for (int i = 0; i < 64; i++) {
    d->minute[i] = 0xFFFFFFFFu;
    d->used_ms[i] = 0;
  }
}

uint32_t pkr_duty_used_ms(const pkr_duty_t *d, uint32_t now_s) {
  uint32_t now_min = now_s / 60, sum = 0;
  for (int i = 0; i < 64; i++)
    if (d->minute[i] != 0xFFFFFFFFu && now_min - d->minute[i] <= 60u) sum += d->used_ms[i];
  return sum;
}

int pkr_duty_can_send(const pkr_duty_t *d, uint32_t now_s, uint32_t airtime_ms, int is_alarm) {
  uint64_t limit = is_alarm ? d->budget_ms : (uint64_t)d->budget_ms * d->telemetry_pct / 100u;
  return (uint64_t)pkr_duty_used_ms(d, now_s) + airtime_ms <= limit;
}

void pkr_duty_record(pkr_duty_t *d, uint32_t now_s, uint32_t airtime_ms) {
  uint32_t minute = now_s / 60;
  int slot = (int)(minute % 64);
  if (d->minute[slot] != minute) {
    d->minute[slot] = minute;
    d->used_ms[slot] = 0;
  }
  d->used_ms[slot] += airtime_ms;
}
