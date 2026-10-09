import { describe, expect, it } from 'vitest';
import type { DecisionTrace } from '../types';
import { evidenceLines, holdLine } from './evidence';

const reading = (over: Record<string, unknown> = {}) => ({
  kind: 'reading',
  rain_24h_mm: 126.8,
  rain_level: 'warning',
  rain_bands_mm: { watch: 64.5, warning: 115.6, critical: 204.5 },
  discharge_peak: 7.3,
  river_level: 'critical',
  thresholds: { watch: 1.7, warning: 3.224, critical: 4.619 },
  ...over,
});

describe('evidence formatter', () => {
  it('writes river and rain evidence against their thresholds, highest first', () => {
    const trace: DecisionTrace = {
      level: 'critical',
      raw_level: 'critical',
      rules_fired: ['rain_24h>=115.6mm:warning', 'discharge>=4.619:critical', 'two_sources_agree:+1'],
      evidence: [reading()],
    };
    const lines = evidenceLines(trace, 'en').map((l) => l.text);
    expect(lines[0]).toBe('River peak 7.3 m³/s ≥ critical threshold 4.62 m³/s');
    expect(lines[1]).toBe('Rain next 24 h 126.8 mm ≥ 115.6 mm (IMD warning band)');
    expect(lines).toContain('Two sources agree: +1 level');
    expect(lines.join(' ')).not.toMatch(/>=|:warning|_24h/);
  });

  it('says when a signal is below its threshold', () => {
    const lines = evidenceLines({ evidence: [reading({ rain_24h_mm: 27.6, rain_level: 'normal', discharge_peak: 0.3, river_level: 'normal' })] }, 'en').map((l) => l.text);
    expect(lines).toContain('River peak 0.3 m³/s, below the watch threshold 1.7 m³/s');
    expect(lines).toContain('Rain next 24 h 27.6 mm, below the watch band 64.5 mm');
  });

  it('describes verified reports and leaves unverified ones out of the level', () => {
    const trace: DecisionTrace = {
      rules_fired: ['verified_reports:warning'],
      evidence: [
        { kind: 'report', type: 'landslide', severity: 'high', verified: true },
        { kind: 'report', type: 'road_cut', severity: 'low', verified: false },
      ],
    };
    const lines = evidenceLines(trace, 'en').map((l) => l.text);
    expect(lines).toContain('1 verified village report: Landslide (High) → Warning');
    expect(lines).toContain('1 unverified report (cannot raise the level)');
  });

  it('explains hysteresis when the level is held above the raw level', () => {
    const trace: DecisionTrace = { level: 'warning', raw_level: 'watch', hysteresis: { calm_sweeps: 1, needed_to_drop: 3 } };
    expect(holdLine(trace, 'en')?.text).toBe('Holding at Warning: levels drop one step only after 3 calm sweeps (1 of 3 so far)');
    expect(holdLine({ level: 'warning', raw_level: 'critical' }, 'en')).toBeNull();
  });
});
