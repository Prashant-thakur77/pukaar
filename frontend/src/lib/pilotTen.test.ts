import { describe, expect, it } from 'vitest';
import { floodnetReason, reasonWord, signalsLine } from './deviceHealth';
import { DASH, TEN, alertRows, gapWord, groupCell, nowCell } from './pilotTen';
import { describeRule } from './rules';
import type { AlertMetrics, TenGroup, TenMetrics } from '../types';

const empty: TenGroup = {
  alerts: 0,
  confirmed_reach: { targeted: 0, confirmed: 0, share_15: null, share_30: null, share_60: null },
  assisted_reach: { targeted: 0, confirmed: 0, share_30: null, checked_by_neighbour: 0, confirmed_or_checked_share: null },
  time_chain_median_minutes: {},
  lead_time: { measured: 0, median_minutes: null },
  outcomes: { real_flood: 0, no_flood: 0, unknown: 0, not_set: 0, false_alarm_rate: null, hit_rate: null },
  siren: { commanded: 0, verified: 0, verified_share: null },
  data_health: { alerts_with_data_ok: 0, alerts_with_status: 0, alerts_with_gauge_silent: 0 },
  protective_action: { rollcalls: 0, asked: 0, safe: 0, need_help: 0, answered_share: null },
};

const drill: TenGroup = {
  ...empty,
  alerts: 1,
  confirmed_reach: { targeted: 3, confirmed: 0, share_15: 0, share_30: 0, share_60: 0 },
  time_chain_median_minutes: { signal_to_first_delivery: 12.5, signal_to_first_ack: null },
};

const ten: TenMetrics = {
  coverage: { villages: 5, villages_with_household_list: 0, registered_phones: 3, households_listed: null, share: null },
  readiness: {
    checklist: { items: 12, done: 1, in_progress: 0, not_started: 11, updated: '2026-10-22' },
    villages_with_two_observers: 0,
    assisted_households: 0,
    assisted_without_neighbour: 0,
  },
  data_health_now: { forecast_checks_24h: 479, expected_24h: 480, share: 0.998 },
  live: empty,
  drill,
  replay: empty,
  as_of: '2026-10-23T10:00:00Z',
};

describe('the ten pilot metrics in words', () => {
  it('has ten rows in protocol order', () => {
    expect(TEN.map((t) => t.n)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  });

  it('shows a dash, never 0, where nothing was measured', () => {
    for (const key of ['reach', 'assisted', 'chain', 'lead', 'outcomes', 'siren', 'data', 'action']) {
      expect(groupCell(key, empty, 'en')).toBe(DASH);
    }
  });

  it('reports a drill with zero confirmations honestly', () => {
    expect(groupCell('reach', drill, 'en')).toBe('0% · 0% · 0% (of 3)');
    expect(groupCell('chain', drill, 'en')).toBe('signal → first send 12.5 min; → first confirmation —');
  });

  it('says coverage is not measured without a household list, and counts readiness', () => {
    expect(nowCell('coverage', ten, 'en')).toContain('no village household list');
    expect(nowCell('readiness', ten, 'en')).toBe('checklist 1 / 12 done; 0 of 5 villages with two observers');
    expect(nowCell('reach', ten, 'en')).toBeNull();
    expect(nowCell('coverage', ten, 'hi')).toContain('घरों की सूची');
  });

  it('names readiness gaps', () => {
    expect(gapWord('observers', 'en')).toBe('fewer than two observers or relays');
    expect(gapWord('unknown_gap', 'en')).toBe('unknown_gap');
  });

  it('turns one alert into ten labelled values', () => {
    const m: AlertMetrics = {
      alert_id: 'alr_1',
      kind: 'drill',
      coverage: { registered: 3, households: null, share: null, per_1000_people: null, observers: 1, targeted: 3 },
      confirmed_reach: { targeted: 3, confirmed: 1, reached: 3, confirmed_share: 0.333, within_15: 1, within_30: 1, within_60: 1, share_15: 0.333, share_30: 0.333, share_60: 0.333 },
      assisted_reach: { targeted: 0, confirmed: 0, escalated: 0, checked_by_neighbour: 0, confirmed_or_checked: 0, confirmed_or_checked_share: null },
      time_chain: { at: {}, minutes: { rule_to_asked: 0.1, asked_to_approved: 2, first_delivery_to_first_ack: 4 } },
      lead_time: { onset_at: null, from_first_delivery: null, from_first_ack: null },
      outcome: { outcome: null, recorded_at: null },
      siren: { commanded: 0, started: 0, verified: 0, verified_share: null },
      data_health: { forecast: 'ok', stale_minutes: null, gauge: 'none', unknown: [] },
      protective_action: null,
      readiness: { checklist: ten.readiness.checklist, observers: 1, observers_needed: 2, gaps: ['observers'] },
      followup: { at: null, trigger: null, sent: 0 },
    };
    const rows = alertRows(m, 'en');
    expect(rows).toHaveLength(10);
    expect(rows[1].value).toBe('33% · 33% · 33% (1 / 3)');
    expect(rows[3].value).toContain('→asked 0.1 min');
    expect(rows[4].value).toBe(DASH);
    expect(rows[7].value).toBe('ok · no gauge');
    expect(rows[9].value).toBe('1 of 2 observers; checklist 1 of 12');
  });
});

describe('FloodNet device health in words', () => {
  it('reads the three FloodNet reasons', () => {
    expect(floodnetReason('battery_empty_in_3d', 'en')).toBe('battery empty in about 3 days');
    expect(floodnetReason('battery_empty_in_0d', 'en')).toBe('battery may run out today');
    expect(floodnetReason('packet_loss_31pct', 'en')).toBe('31% of readings lost');
    expect(floodnetReason('stuck_6_readings', 'en')).toBe('same value 6 times while raining');
    expect(floodnetReason('silent', 'en')).toBeNull();
  });

  it('reads other registry reasons and keeps unknown ones visible', () => {
    expect(reasonWord('silent_120_min', 'en')).toBe('silent 120 min');
    expect(reasonWord('test_overdue', 'hi')).toBe('जाँच बाकी');
    expect(reasonWord('fault_weird_thing', 'en')).toBe('fault weird thing');
  });

  it('summarises the measured signals, or says nothing', () => {
    expect(signalsLine(null, 'en')).toBeNull();
    expect(signalsLine({ battery: null, packet_loss: { expected: 29, received: 20, loss: 0.31 } }, 'en')).toBe('31% lost (20 of 29)');
    expect(signalsLine({ battery: { unit: 'soc', latest: 42, slope_per_day: -24, days_to_empty: 1.3, samples: 49 } }, 'en')).toBe('battery -24%/day');
  });
});

describe('the silent-gauge rule in words', () => {
  it('describes it', () => {
    expect(describeRule('gauge_silent_in_rain:watch', 'en')).toBe('The river gauge went silent while it rains (over 30 min) → Watch');
    expect(describeRule('gauge_silent_in_rain_ignored:simulated', 'en')).toContain('simulator');
  });
});
