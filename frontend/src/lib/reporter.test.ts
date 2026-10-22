import { describe, expect, it } from 'vitest';
import { reportForm } from '../api';
import { floodCount, heldLabel, humanizeFlag } from './humanize';
import { deviceId, randomId, sessionId } from './reporter';

describe('report source ids', () => {
  it('keeps one device id per browser and one session id per tab', () => {
    const d = deviceId();
    expect(d).toMatch(/^[0-9a-f-]{16,}$/);
    expect(deviceId()).toBe(d);
    expect(sessionId()).toBe(sessionId());
    expect(sessionId()).not.toBe(d);
    expect(randomId()).not.toBe(randomId());
  });

  it('sends them with every report, so the server can tell two phones apart', () => {
    const f = reportForm({ village_id: 'thunag', text: 'pani' });
    expect(f.get('device_id')).toBe(deviceId());
    expect(f.get('session_id')).toBe(sessionId());
    const given = reportForm({ village_id: 'thunag', device_id: 'd1', session_id: 's1' });
    expect([given.get('device_id'), given.get('session_id')]).toEqual(['d1', 's1']);
  });
});

describe('report-abuse flags', () => {
  it('says why a nearby report did not confirm this one', () => {
    expect(humanizeFlag('corroboration_rejected:same_network', 'en')).toEqual({
      text: 'Not confirmed by the nearby report: same network',
      tone: 'warn',
    });
    expect(humanizeFlag('same_source', 'en').text).toBe('Same phone or network as a recent report');
    expect(humanizeFlag('same_source_as:rpt_9', 'en').reportId).toBe('rpt_9');
    expect(humanizeFlag('report_surge', 'hi').text).toBe('इस गाँव से अचानक बहुत सूचनाएँ');
  });

  it('labels a report held over a rate limit as kept, never auto-verified', () => {
    const h = heldLabel(null, 'en', 'source_rate_limit');
    expect(h?.chip).toBe('Held for review: too many reports from one source');
    expect(h?.detail).toContain('Kept, not discarded');
    expect(heldLabel(null, 'en', null)).toBeNull();
  });

  it('counts the last hour of possible duplicates or floods', () => {
    const now = Date.parse('2026-07-01T12:00:00Z');
    const r = (min: number, flags: string[], hold_reason: string | null = null) => ({
      created_at: new Date(now - min * 60_000).toISOString(),
      flags,
      hold_reason,
    });
    expect(floodCount([r(5, ['same_source']), r(10, [], 'village_surge'), r(20, ['no_gps']), r(90, ['source_flood'])], now)).toBe(2);
  });
});
