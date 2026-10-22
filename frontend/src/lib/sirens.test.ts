import { describe, expect, it } from 'vitest';
import {
  audibleAllowed,
  healthChip,
  lastTestedLine,
  measText,
  readSoundReply,
  rowTone,
  sirenText,
  smsLink,
  tierSummary,
  type VillageSirens,
} from './sirens';

const date = (iso: string) => iso.slice(0, 10);

describe('siren strings', () => {
  it('every string has Hindi and English with the same placeholders', () => {
    const vars = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort().join(',');
    for (const [k, e] of Object.entries(sirenText)) {
      expect(e.hi.trim(), k).not.toBe('');
      expect(e.en.trim(), k).not.toBe('');
      expect(vars(e.hi), k).toBe(vars(e.en));
    }
  });
});

describe('health chip', () => {
  it('only "ok" is OK; unknown, missing and unexpected values never read as OK', () => {
    expect(healthChip('ok', 'en')).toMatchObject({ ok: true, cls: 'chip-good', label: 'OK' });
    for (const h of ['unknown', null, undefined, '', 'OK', 'healthy', 'weird']) {
      const c = healthChip(h, 'en');
      expect(c.ok, String(h)).toBe(false);
      expect(c.label, String(h)).not.toBe('OK');
      expect(c.cls, String(h)).not.toBe('chip-good');
    }
    expect(healthChip(undefined, 'en').label).toBe('Unknown (never heard)');
    expect(healthChip('offline', 'hi').cls).toBe('chip-bad');
    expect(healthChip('fault', 'en').cls).toBe('chip-bad');
    expect(healthChip('degraded', 'en').cls).toBe('chip-warn');
    expect(healthChip('unknown', 'hi').label).toBe('पता नहीं (कभी सुना नहीं)');
  });
});

describe('public "siren last tested" line', () => {
  const base: VillageSirens = { count: 1, sounding: 0, last_test_at: '2026-10-20T05:30:00Z', last_test_ok: true, overdue: false };

  it('nothing when the village has no siren', () => {
    expect(lastTestedLine(null, 'en', date)).toBeNull();
    expect(lastTestedLine(undefined, 'hi', date)).toBeNull();
    expect(lastTestedLine({ ...base, count: 0 }, 'en', date)).toBeNull();
  });

  it('a passed test in English and Hindi', () => {
    expect(lastTestedLine(base, 'en', date)).toEqual({ text: 'Siren last tested 2026-10-20: passed', tone: 'good' });
    expect(lastTestedLine(base, 'hi', date)).toEqual({ text: 'सायरन आखिरी बार जाँचा गया 2026-10-20: ठीक', tone: 'good' });
  });

  it('failed, overdue and never tested are red', () => {
    expect(lastTestedLine({ ...base, last_test_ok: false }, 'en', date)).toEqual({
      text: 'Siren last tested 2026-10-20: failed',
      tone: 'bad',
    });
    expect(lastTestedLine({ ...base, overdue: true }, 'en', date)).toEqual({
      text: 'Siren last tested 2026-10-20: passed · test overdue',
      tone: 'bad',
    });
    expect(lastTestedLine({ ...base, overdue: true }, 'hi', date)?.text).toBe('सायरन आखिरी बार जाँचा गया 2026-10-20: ठीक · जाँच बाकी है');
    expect(lastTestedLine({ ...base, last_test_at: null, last_test_ok: null }, 'en', date)).toEqual({
      text: 'Siren never tested',
      tone: 'bad',
    });
    expect(lastTestedLine({ ...base, last_test_at: null, last_test_ok: null }, 'hi', date)?.text).toBe('सायरन अभी तक जाँचा नहीं गया');
  });

  it('a missing result is never shown as passed', () => {
    expect(lastTestedLine({ ...base, last_test_ok: null }, 'en', date)).toMatchObject({ tone: 'bad' });
  });

  it('says when it is sounding and when it is a simulator', () => {
    expect(lastTestedLine({ ...base, sounding: 1, simulated: true }, 'en', date)?.text).toBe(
      'Siren last tested 2026-10-20: passed · Siren sounding · Simulated',
    );
  });
});

describe('siren tier on an alert', () => {
  it('reads "Sirens v/n verified", with started while waiting', () => {
    expect(tierSummary({ sirens_total: 1, sirens_started: 1, sirens_verified: 1 }, 'en')).toBe('Sirens 1/1 verified');
    expect(tierSummary({ sirens_total: 1, sirens_started: 1, sirens_verified: 1 }, 'hi')).toBe('सायरन 1/1 पुष्टि');
    expect(tierSummary({ sirens_total: 2, sirens_started: 2, sirens_verified: 1 }, 'en')).toBe('Sirens 1/2 verified · 2 started');
    expect(tierSummary({ sirens_total: 0 }, 'en')).toBeNull();
    expect(tierSummary(null, 'en')).toBeNull();
  });

  it('formats the device evidence and the row tone', () => {
    expect(measText({ amp_a: 3.1, spl_rise_db: 24.4 })).toBe('3.1 A · +24 dB');
    expect(measText({ amp_a: 3 })).toBe('3.0 A');
    expect(measText(null)).toBe('');
    expect(rowTone('verified')).toBe('good');
    expect(rowTone('started')).toBe('pending');
    expect(rowTone('not_confirmed')).toBe('bad');
  });
});

describe('two-person reply', () => {
  it('a 202 asks for a second officer; a 200 says what was commanded', () => {
    expect(readSoundReply({ request_id: 'req_1', needs_second_officer: true, expires_at: '2026-10-22T08:33:00Z' })).toEqual({
      kind: 'needs_second',
      requestId: 'req_1',
      expiresAt: '2026-10-22T08:33:00Z',
    });
    expect(readSoundReply({ commanded: 2, cmd_ids: ['a', 'b'], pattern: 'W1' })).toEqual({ kind: 'commanded', n: 2, pattern: 'W1' });
  });
});

describe('audible window and SMS link', () => {
  it('audible tests only 09:00 to 18:00 IST', () => {
    expect(audibleAllowed(new Date('2026-10-22T03:29:00Z'))).toBe(false); // 08:59 IST
    expect(audibleAllowed(new Date('2026-10-22T03:30:00Z'))).toBe(true); // 09:00 IST
    expect(audibleAllowed(new Date('2026-10-22T12:29:00Z'))).toBe(true); // 17:59 IST
    expect(audibleAllowed(new Date('2026-10-22T12:30:00Z'))).toBe(false); // 18:00 IST
    expect(audibleAllowed(new Date('2026-10-22T20:00:00Z'))).toBe(false); // 01:30 IST
  });

  it('prefills the signed text for the siren SIM', () => {
    const text = 'PKR1 siren-thunag-01 SC 000413 TJ8K2Q 7K2QM9XA4D1F8HTP';
    expect(smsLink('+91 98123-45678', text)).toBe(`sms:+919812345678?body=${encodeURIComponent(text)}`);
    expect(smsLink(null, 'x y')).toBe('sms:?body=x%20y');
  });
});
