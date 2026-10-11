import { describe, expect, it } from 'vitest';
import { buildMarks, canManageStaffGauge, classLabel, CROWDWATER, levelForMark, marksTopFirst, nearestMark, staffEvidenceLine } from './staffGauge';
import { describeRule } from './rules';

const top = { x: 0.5, y: 0.2 };
const bottom = { x: 0.5, y: 0.8 };

describe('staff gauge marks', () => {
  it('lays CrowdWater classes -5..+5 evenly from the bottom tap to the top tap', () => {
    const m = buildMarks(top, bottom, CROWDWATER);
    expect(m.map((x) => x.label)).toEqual(['-5', '-4', '-3', '-2', '-1', '0', '+1', '+2', '+3', '+4', '+5']);
    expect(m[0]).toMatchObject({ value: -5, x: 0.5, y: 0.8 });
    expect(m[10]).toMatchObject({ value: 5, y: 0.2 });
    expect(m[5].y).toBeCloseTo(0.5);
  });

  it('follows a slanted line and builds cm marks', () => {
    const m = buildMarks({ x: 0.6, y: 0.1 }, { x: 0.4, y: 0.9 }, { kind: 'cm', spanCm: 200, stepCm: 50, baseCm: 0 });
    expect(m.map((x) => x.label)).toEqual(['0 cm', '50 cm', '100 cm', '150 cm', '200 cm']);
    expect(m[2]).toMatchObject({ value: 100, height_cm: 100, x: 0.5, y: 0.5 });
    expect(buildMarks(top, bottom, { kind: 'cm', spanCm: 0, stepCm: 50, baseCm: 0 })).toEqual([]);
  });

  it('reads top first, maps marks to levels and snaps a tap to the nearest mark', () => {
    const m = buildMarks(top, bottom, CROWDWATER);
    expect(marksTopFirst(m)[0].label).toBe('+5');
    const g = { watch_at: 1, warning_at: 3, critical_at: null };
    expect([0, 1, 2, 3, 5].map((v) => levelForMark(g, v))).toEqual(['normal', 'watch', 'watch', 'warning', 'warning']);
    expect(nearestMark(m, 0.31)?.label).toBe('+3');
    expect(classLabel(0)).toBe('0');
  });

  it('lets officers and the own pradhan set one up', () => {
    expect(canManageStaffGauge({ role: 'officer', village_ids: [] }, 'gohar')).toBe(true);
    expect(canManageStaffGauge({ role: 'pradhan', village_ids: ['thunag'] }, 'thunag')).toBe(true);
    expect(canManageStaffGauge({ role: 'pradhan', village_ids: ['thunag'] }, 'gohar')).toBe(false);
    expect(canManageStaffGauge(null, 'thunag')).toBe(false);
  });

  it('writes the evidence line', () => {
    expect(staffEvidenceLine({ mark: '+3', status: 'confirmed', confirmed_by: 'officer1' }, '14:20', 'en')).toBe('Staff gauge: +3 at 14:20, confirmed by officer1');
    expect(staffEvidenceLine({ mark: '+3', status: 'unconfirmed' }, '14:20', 'en')).toMatch(/does not change the level/);
    expect(staffEvidenceLine({ mark: '+3', status: 'confirmed' }, '14:20', 'hi')).toContain('अधिकारी ने पुष्टि की');
  });

  it('describes the staff gauge rules', () => {
    expect(describeRule('staff_gauge:+3:warning', 'en')).toBe('Staff gauge: mark +3, confirmed by an officer → Warning');
    expect(describeRule('staff_gauge_confirmed:watch', 'hi')).toContain('पुष्ट');
  });
});
