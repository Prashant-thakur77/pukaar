import { describe, expect, it } from 'vitest';
import { expiryMs } from './format';

describe('expiryMs', () => {
  it('reads epoch seconds, epoch ms and ISO strings', () => {
    expect(expiryMs(1791532326)).toBe(1791532326000);
    expect(expiryMs('1791532326')).toBe(1791532326000);
    expect(expiryMs(1791532326000)).toBe(1791532326000);
    expect(expiryMs('2026-10-09T08:00:00Z')).toBe(Date.parse('2026-10-09T08:00:00Z'));
    expect(expiryMs(null)).toBeNull();
  });
});
