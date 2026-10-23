import { describe, expect, it } from 'vitest';
import type { DecisionTrace } from '../types';
import { evidenceLines, holdLine, shortReason } from './evidence';

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
  describe('heavy burst of rain', () => {
    const burst = {
      kind: 'rain_intensity',
      level: 'warning',
      burst: true,
      combine: 'max',
      reason: '24h',
      windows_mm: { '1': 20, '3': 45, '6': 50 },
      models: { best_match: { '1': 18, '3': 48, '6': 49 }, icon_seamless: { '1': 9, '3': 20, '6': 30 }, gfs_seamless: { '1': 5, '3': 12, '6': 20 } },
      maxima: { '1': { mm: 18, model: 'best_match' }, '3': { mm: 48, model: 'best_match' }, '6': { mm: 49, model: 'best_match' } },
      hit: [{ hours: 3, mm: 48, threshold_mm: 45, model: 'best_match', start_hour: 4 }],
    };
    it('writes a readable line in English and Hindi, and the 24 h line keeps its own level', () => {
      const trace: DecisionTrace = {
        level: 'warning',
        rules_fired: ['rain_24h>=64.5mm:watch', 'rain_intensity:3h=48>=45mm+rain_24h:warning'],
        evidence: [reading({ rain_24h_mm: 70, rain_level: 'warning', rain_24h_level: 'watch', discharge_peak: 0.3, river_level: 'normal' }), burst],
      };
      const en = evidenceLines(trace, 'en');
      expect(en[0].text).toBe('Heavy burst forecast: up to 48 mm in 3 hours, highest of 3 models (limit 45 mm), with the 24 h rain already over a band → Warning');
      expect(en[0].level).toBe('warning');
      expect(en.map((l) => l.text)).toContain('Rain next 24 h 70 mm ≥ 64.5 mm (IMD watch band)');
      const hi = evidenceLines(trace, 'hi').map((l) => l.text).join(' ');
      expect(hi).toContain('भारी बौछार का पूर्वानुमान: 3 घंटे में 48 मिमी तक');
      expect(hi).toContain('3 मॉडलों में सबसे ज़्यादा');
      expect([...en.map((l) => l.text), hi].join(' ')).not.toMatch(/rain_intensity|>=/);
    });
    it('falls back to the rule tag when the trace has no burst evidence', () => {
      const lines = evidenceLines({ rules_fired: ['rain_intensity:1h=22>=20mm:watch'], evidence: [] }, 'en').map((l) => l.text);
      expect(lines).toContain('Heavy burst forecast: up to 22 mm in 1 hour (limit 20 mm) → Watch');
    });
    it('says how far off a burst is when none is forecast', () => {
      const calm = { ...burst, level: 'normal', burst: false, reason: null, hit: [], maxima: { '1': { mm: 4 }, '3': { mm: 30 }, '6': { mm: 31 } } };
      const lines = evidenceLines({ evidence: [reading({ rain_24h_mm: 20, rain_level: 'normal', discharge_peak: 0.3, river_level: 'normal' }), calm] }, 'en').map((l) => l.text);
      expect(lines).toContain('No heavy burst: at most 30 mm in 3 hours, below the 45 mm limit');
    });
  });
});

describe('shortReason', () => {
  it('names the rule that raised the level most, in words, never as an id', () => {
    expect(shortReason(['rain_24h>=64.5mm:watch'], 'hi')).toBe('अगले 24 घंटे में बारिश 64.5 मिमी से ज़्यादा');
    expect(shortReason(['rain_24h>=64.5mm:watch'], 'en')).toBe('Rain next 24 h over 64.5 mm');
    expect(shortReason(['rain_24h>=115.6mm:warning', 'discharge>=4.619:critical', 'two_sources_agree:+1'], 'en')).toBe('River flow over 4.62 m³/s');
    expect(shortReason(['gauge_unconfirmed:warning', 'rain_intensity:3h=48>=45mm+rain_24h:warning'], 'en')).toBe('Heavy burst: 48 mm in 3 h');
    expect(shortReason(['river_ensemble:P(warning)=0.4>=0.3:warning'], 'hi')).toBe('नदी: 40% पूर्वानुमान चेतावनी रेखा पार');
    expect(shortReason(['official:CWC+IMD:warning'], 'en')).toBe('Official: CWC, IMD');
  });
  it('says nothing rather than show an unknown id', () => {
    expect(shortReason(['something_new:watch'], 'en')).toBeNull();
    expect(shortReason([], 'en')).toBeNull();
    expect(shortReason(undefined, 'hi')).toBeNull();
  });
});
