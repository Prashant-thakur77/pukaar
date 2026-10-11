import { describe, expect, it } from 'vitest';
import { exceedanceX, niceStep } from './gaugeLearn';

describe('gauge proposal chart helpers', () => {
  it('spreads the high percentiles on an exceedance axis', () => {
    expect(exceedanceX(0)).toBeCloseTo(0);
    expect(exceedanceX(90)).toBeCloseTo(1);
    expect(exceedanceX(99)).toBeCloseTo(2);
    expect(exceedanceX(99.5)).toBeCloseTo(2.301, 3);
    expect(exceedanceX(100)).toBeGreaterThan(exceedanceX(99.5));
  });
  it('picks round grid steps', () => {
    expect(niceStep(100)).toBe(20);
    expect(niceStep(37)).toBe(10);
    expect(niceStep(0)).toBe(1);
  });
});
