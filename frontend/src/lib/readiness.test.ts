import { describe, expect, it } from 'vitest';
import { canTickChecklist, isGetReady, pct, progress, withItem } from './readiness';
import { describeRule } from './rules';
import type { Checklist } from '../types';

const list: Checklist = {
  done: 1,
  total: 3,
  items: ['a', 'b', 'c'].map((item, order) => ({
    village_id: 'thunag', item, label_en: item, label_hi: item, order, done: item === 'a', done_by: null, done_at: null,
  })),
};

describe('checklist permissions mirror the Cedar policy', () => {
  it('lets officers tick any village and pradhans only their own', () => {
    expect(canTickChecklist({ username: 'o', role: 'officer', village_ids: [] }, 'gohar')).toBe(true);
    expect(canTickChecklist({ username: 'p', role: 'pradhan', village_ids: ['thunag'] }, 'thunag')).toBe(true);
    expect(canTickChecklist({ username: 'p', role: 'pradhan', village_ids: ['thunag'] }, 'gohar')).toBe(false);
    expect(canTickChecklist(null, 'thunag')).toBe(false);
  });
});

describe('readiness helpers', () => {
  it('counts progress and updates one item', () => {
    expect(progress(list)).toBeCloseTo(1 / 3);
    const next = withItem(list, 'b', true);
    expect(next.done).toBe(2);
    expect(withItem(next, 'a', false).done).toBe(1);
    expect(progress(null)).toBe(0);
  });
  it('reads the soft trigger', () => {
    expect(isGetReady({ state: 'get_ready', horizon_days: 3, peak_day: '2026-07-05', peak_vs_watch_ratio: 1.5, source: 's' })).toBe(true);
    expect(isGetReady({ state: 'none', horizon_days: null, peak_day: null, peak_vs_watch_ratio: 0.4, source: 's' })).toBe(false);
    expect(isGetReady(undefined)).toBe(false);
  });
  it('clips bar positions', () => {
    expect(pct(0.92)).toBe('92%');
    expect(pct(1.4)).toBe('100%');
    expect(pct(null)).toBe('0%');
  });
});

describe('describeRule for the soil modifier', () => {
  it('explains the lowered bands in both languages', () => {
    expect(describeRule('soil_saturated:S=0.92:bands x0.82', 'en')).toBe('Saturated soil (S = 0.92) → rain bands × 0.82');
    expect(describeRule('soil_saturated:S=0.92:bands x0.82', 'hi')).toContain('0.82');
  });
});
