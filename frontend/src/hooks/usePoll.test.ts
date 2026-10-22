import { describe, expect, it } from 'vitest';
import { SLOW_LINK_MIN_MS, slowLinkInterval } from './usePoll';

describe('slowLinkInterval', () => {
  it('polls at most once a minute on 2G, 3G or with Data Saver', () => {
    expect(slowLinkInterval(15000, { effectiveType: '3g' })).toBe(SLOW_LINK_MIN_MS);
    expect(slowLinkInterval(15000, { effectiveType: 'slow-2g' })).toBe(SLOW_LINK_MIN_MS);
    expect(slowLinkInterval(15000, { effectiveType: '4g', saveData: true })).toBe(SLOW_LINK_MIN_MS);
    expect(slowLinkInterval(120000, { effectiveType: '2g' })).toBe(120000);
  });
  it('leaves fast links, unknown links and disabled polling alone', () => {
    expect(slowLinkInterval(15000, { effectiveType: '4g' })).toBe(15000);
    expect(slowLinkInterval(15000, undefined)).toBe(15000);
    expect(slowLinkInterval(0, { effectiveType: '2g' })).toBe(0);
  });
});
