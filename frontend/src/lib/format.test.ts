import { describe, expect, it } from 'vitest';
import { expiryMs, fmtAgo } from './format';

describe('expiryMs', () => {
  it('reads epoch seconds, epoch ms and ISO strings', () => {
    expect(expiryMs(1791532326)).toBe(1791532326000);
    expect(expiryMs('1791532326')).toBe(1791532326000);
    expect(expiryMs(1791532326000)).toBe(1791532326000);
    expect(expiryMs('2026-10-09T08:00:00Z')).toBe(Date.parse('2026-10-09T08:00:00Z'));
    expect(expiryMs(null)).toBeNull();
  });
});

describe('fmtAgo', () => {
  const now = new Date('2026-10-11T02:00:00Z').getTime();
  it('names the year for a date in another year', () => {
    expect(fmtAgo('2023-07-10T02:00:00Z', 'en', now)).toContain('2023');
  });
  it('leaves the year out for an older date this year', () => {
    expect(fmtAgo('2026-07-10T02:00:00Z', 'en', now)).not.toContain('2026');
  });
});
