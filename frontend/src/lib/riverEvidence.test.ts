import { describe, expect, it } from 'vitest';
import type { DecisionTrace, EnsembleDay, GaugeHealth, Thresholds } from '../types';
import { evidenceLines } from './evidence';
import { countedLine, healthWords, qualityWord, risingLine } from './gaugeHealth';
import { ensembleLines, ensembleNote, officialRows, outlookLine, thresholdRows } from './riverEvidence';

const TH: Thresholds = {
  watch: 366.488,
  warning: 444.65,
  critical: 546.041,
  method: 'return_period',
  return_period_years: { watch: 2, warning: 5, critical: 20 },
  early: 300.58,
};
const day = (lead: number, watch: number, warning = 0, critical = 0, members = 10): EnsembleDay => ({
  date: `2026-07-0${lead + 1}`,
  lead,
  members,
  p: { watch, warning, critical },
});

describe('ensemble odds in words', () => {
  it('counts the runs per flood level, with the lead day of the highest share', () => {
    const r = { mode: 'ensemble', members: 10, p_min: 0.3, lead_days: [day(1, 0.1), day(2, 0.3, 0.1), day(3, 0.2)] };
    const lines = ensembleLines(r, TH, 'en');
    expect(lines.map((l) => l.text)).toEqual([
      '3 of 10 forecast runs say the river passes its 2-year flood level within 2 days',
      '1 of 10 forecast runs say the river passes its 5-year flood level within 2 days',
    ]);
    expect(lines.map((l) => l.raises)).toEqual([true, false]);
    expect(ensembleLines(r, TH, 'hi')[0].text).toBe('10 में से 3 पूर्वानुमान-रन कहते हैं कि नदी 2 दिन के भीतर अपने 2 साल वाले बाढ़-स्तर से ऊपर जाएगी');
  });

  it('says when no run reaches Watch, and labels a single forecast', () => {
    expect(ensembleNote({ mode: 'ensemble', members: 51, lead_days: [day(1, 0, 0, 0, 51), day(3, 0, 0, 0, 51)] }, TH, 'en')).toBe(
      'None of the 51 forecast runs take the river past its 2-year flood level in the next 3 days',
    );
    expect(ensembleNote({ mode: 'deterministic', ensemble_status: 'unavailable' }, TH, 'en')).toBe('River: a single forecast, not the forecast runs (the ensemble is unavailable)');
    expect(ensembleNote({ mode: 'deterministic', replay: true }, TH, 'hi')).toBe('नदी: एकल पूर्वानुमान, पूर्वानुमान-रन नहीं (रीप्ले में एन्सेम्बल नहीं होता)');
    expect(ensembleLines({ mode: 'deterministic' }, TH, 'en')).toEqual([]);
  });

  it('lists the return-period lines and the get-ready line', () => {
    const rows = thresholdRows(TH, 'en');
    expect(rows.map((r) => [r.label, r.what])).toEqual([
      ['Critical', '20-year flood'],
      ['Warning', '5-year flood'],
      ['Watch', '2-year flood'],
      ['Get ready', 'the river runs this high 1 day in 10 (an outlook, never an alert)'],
    ]);
  });
});

describe('the get-ready outlook', () => {
  it('reads as an outlook, never an alert, and names its basis', () => {
    const text = outlookLine({ state: 'get_ready', line: 'early', early: 300.58, horizon_days: 7, basis: 'single_forecast' }, 'en');
    expect(text).toBe('Get ready: the river is forecast to run high. In 7 days the flow passes the 301 m³/s line (single forecast). Not an alert; it never changes the level.');
    expect(outlookLine({ state: 'none' }, 'en')).toBeNull();
    expect(outlookLine({ state: 'get_ready', early: 1.14, line: 'early', horizon_days: 1, basis: 'ensemble_median' }, 'hi')).toContain('चेतावनी नहीं');
  });
});

describe('official sources', () => {
  it('words each source and reads unavailable as saying nothing', () => {
    const rows = officialRows(
      [
        { source: 'cwc', name: 'CWC', status: 'ok', level: 'normal', stations_above_warning: 11, matched: [], mapped: false },
        { source: 'imd', name: 'IMD', status: 'ok', level: 'warning', colour: 'orange' },
        { source: 'flood_hub', name: 'Flood Hub', status: 'off' },
        { source: 'bipad', name: 'BIPAD', status: 'unavailable', error: 'timeout' },
      ],
      'en',
    );
    expect(rows.map((r) => `${r.label}: ${r.text}`)).toEqual([
      'CWC river stations: 11 stations above warning in India; 0 on this river (no station codes mapped to this village yet)',
      'IMD district colour: orange for today and tomorrow (every weather hazard, not floods alone)',
      'Google Flood Hub: switched off',
      'BIPAD (Nepal): unavailable (says nothing)',
    ]);
    expect(rows[1].level).toBe('warning');
    expect(rows[0].level).toBeUndefined();
  });
});

describe('console evidence carries the odds, the outlook and the sources', () => {
  it('adds the river runs, the get-ready line and the official rows', () => {
    const trace: DecisionTrace = {
      level: 'watch',
      raw_level: 'watch',
      rules_fired: ['river_ensemble:P(watch)=0.3>=0.3:watch'],
      evidence: [
        { kind: 'reading', discharge_peak: 380, river_level: 'watch', thresholds: TH },
        { kind: 'river', mode: 'ensemble', members: 10, p_min: 0.3, lead_days: [day(2, 0.3)] },
        { kind: 'outlook', state: 'get_ready', line: 'early', early: 300.58, horizon_days: 1, basis: 'ensemble_median' },
        { kind: 'official', items: [{ source: 'imd', name: 'IMD', status: 'unavailable' }] },
      ],
    };
    const lines = evidenceLines(trace, 'en');
    const texts = lines.map((l) => l.text);
    expect(texts[0]).toBe('River peak 380 m³/s ≥ its 2-year flood level 366.49 m³/s (Watch)');
    expect(texts).toContain('3 of 10 forecast runs say the river passes its 2-year flood level within 2 days');
    expect(lines.find((l) => l.kind === 'outlook')?.text).toMatch(/^Get ready: the river is forecast to run high/);
    expect(texts).toContain('Unavailable, so saying nothing: IMD district colour');
  });
});

describe('gauge health in words', () => {
  const h: GaugeHealth = {
    status: 'gauge_unhealthy',
    unhealthy: true,
    reasons: ['silent', 'low_battery'],
    last_seen: null,
    minutes_since: null,
    battery_v: 3.3,
    battery_low: true,
    readings_24h: 40,
    bad_24h: 3,
    bad_share_24h: 0.075,
  };
  it('names the reasons and the bad-reading share', () => {
    expect(healthWords(h, 'en')).toEqual({ ok: false, status: 'Unhealthy: silent, low battery', badShare: '3 of 40 (7.5%)' });
    expect(healthWords({ ...h, unhealthy: false, reasons: [], readings_24h: 0, bad_share_24h: null }, 'hi')).toEqual({ ok: true, status: 'ठीक', badShare: '—' });
  });
  it('says counted against measured, quality and rising fast', () => {
    expect(countedLine('watch', 'warning', 'en')).toBe('The newest reading alone is at Warning; the rules count Watch (2 of the last 3 good readings must agree)');
    expect(countedLine('warning', 'watch', 'en')).toBe('The newest reading alone is at Watch; the rules count Warning (rising fast, so one level up)');
    expect(countedLine('watch', 'watch', 'en')).toBeNull();
    expect(qualityWord('spike', 'en')).toBe('spike, not counted');
    expect(risingLine(true, 12, 'en')).toBe('Rising fast (+12 cm): counted one level up');
    expect(risingLine(false, 12, 'en')).toBeNull();
  });
});
