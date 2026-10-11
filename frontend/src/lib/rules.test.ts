import { describe, expect, it } from 'vitest';
import { describeRule } from './rules';

describe('describeRule for the river gauge', () => {
  it('reads the gauge band rule in both languages', () => {
    expect(describeRule('gauge>=200cm:warning', 'en')).toBe('River gauge ≥ 200 cm → Warning');
    expect(describeRule('gauge>=200cm:warning', 'hi')).toContain('200 सेमी');
  });
  it('labels simulated readings honestly', () => {
    expect(describeRule('gauge_simulated', 'en')).toMatch(/simulator, not real hardware/);
  });
});
