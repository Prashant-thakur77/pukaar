import { describe, expect, it } from 'vitest';
import { describeRule, parseBurstTag } from './rules';

describe('describeRule for the river gauge', () => {
  it('reads the gauge band rule in both languages', () => {
    expect(describeRule('gauge>=200cm:warning', 'en')).toBe('River gauge ≥ 200 cm → Warning');
    expect(describeRule('gauge>=200cm:warning', 'hi')).toContain('200 सेमी');
  });
  it('labels simulated readings honestly', () => {
    expect(describeRule('gauge_simulated', 'en')).toMatch(/simulator, not real hardware/);
  });
});

describe('describeRule for the heavy-burst rule', () => {
  it('reads the rain_intensity tag instead of showing it raw', () => {
    expect(describeRule('rain_intensity:3h=48>=45mm+rain_24h:warning', 'en')).toBe(
      'Heavy burst forecast: up to 48 mm in 3 hours (limit 45 mm), with the 24 h rain already over a band → Warning',
    );
    expect(describeRule('rain_intensity:1h=21.5>=20mm:watch', 'en')).toBe('Heavy burst forecast: up to 21.5 mm in 1 hour (limit 20 mm) → Watch');
    const hi = describeRule('rain_intensity:6h=52>=50mm+soil_saturated:warning', 'hi');
    expect(hi).toContain('भारी बौछार का पूर्वानुमान');
    expect(hi).toContain('मिट्टी');
    expect(hi).not.toMatch(/rain_intensity|>=/);
  });
  it('parses the tag', () => {
    expect(parseBurstTag('rain_intensity:3h=48>=45mm+rain_24h:warning')).toEqual({ hours: 3, mm: 48, threshold: 45, reason: '24h', level: 'warning' });
    expect(parseBurstTag('rain_24h>=64.5mm:watch')).toBeNull();
  });
});
