import { describe, expect, it } from 'vitest';
import type { ReportScreen } from '../types';
import { heldLabel, humanizeFlag, humanizeSummary, maskedNotes, screenReason } from './humanize';

describe('report flag humanizer', () => {
  it('turns known flags into plain words', () => {
    expect(humanizeFlag('possible_duplicate', 'en').text).toBe('Possible duplicate of a nearby report');
    expect(humanizeFlag('no_gps', 'en').text).toBe('No location');
    expect(humanizeFlag('transcription_unavailable', 'en').text).toBe('Voice not transcribed (kept)');
    expect(humanizeFlag('corroborated', 'en')).toMatchObject({ text: 'Confirmed by a second report', tone: 'good' });
    expect(humanizeFlag('verified_by_photo', 'en').text).toBe('Photo matches');
    expect(humanizeFlag('no_gps', 'hi').text).toBe('जगह नहीं मिली');
  });

  it('links duplicate_of to the other report', () => {
    expect(humanizeFlag('duplicate_of:rep_123', 'en')).toEqual({ text: 'see report', reportId: 'rep_123', tone: 'muted' });
  });

  it('passes unknown flags through without underscores', () => {
    expect(humanizeFlag('some_new_flag', 'en').text).toBe('some new flag');
  });
});

describe('report summary humanizer', () => {
  it('rewrites parser summaries in the current language', () => {
    expect(humanizeSummary('other (low) reported', 'en')).toBe('Other reported · severity low');
    expect(humanizeSummary('road cut (high) reported', 'en')).toBe('Road cut reported · severity high');
    expect(humanizeSummary('road cut (high) reported', 'hi')).toBe('सड़क टूटी की सूचना · ख़तरा: ज़्यादा');
  });

  it('keeps free-text summaries', () => {
    expect(humanizeSummary('Water over the Thunag bridge deck', 'en')).toBe('Water over the Thunag bridge deck');
  });
});

describe('guardrail screen labels', () => {
  const held: ReportScreen = {
    allowed: false, action: 'GUARDRAIL_INTERVENED', reasons: ['prompt_attack'], engine: 'bedrock-guardrail', at: '2026-10-11T00:00:00Z', field: 'text',
  };

  it('labels a prompt attack as a possible instruction to the system, in both languages', () => {
    expect(heldLabel(held, 'en')?.chip).toBe('Held for review: possible instruction to the system');
    expect(heldLabel(held, 'hi')?.chip).toBe('जाँच के लिए रोकी गई: सिस्टम को आदेश देने की कोशिश हो सकती है');
    expect(heldLabel(held, 'en')?.detail).toContain('Screened by Bedrock Guardrails');
    expect(heldLabel(held, 'en')?.detail).toContain('tries to override the system’s rules');
  });

  it('names the local check and abusive language', () => {
    const h = heldLabel({ ...held, reasons: ['insults'], engine: 'local-heuristic', action: 'HEURISTIC_BLOCKED' }, 'en');
    expect(h?.chip).toBe('Held for review: abusive or harmful language');
    expect(h?.detail).toContain('local check');
  });

  it('is null for allowed or unscreened reports, and lists masking notes', () => {
    expect(heldLabel(null, 'en')).toBeNull();
    expect(heldLabel(undefined, 'en')).toBeNull();
    const masked = { ...held, allowed: true, action: 'GUARDRAIL_INTERVENED', reasons: ['pii:phone'] };
    expect(heldLabel(masked, 'en')).toBeNull();
    expect(maskedNotes(masked, 'en')).toEqual(['phone number hidden']);
    expect(maskedNotes(held, 'en')).toEqual([]);
  });

  it('passes unknown reason codes through as words', () => {
    expect(screenReason('topic:Something else', 'en')).toBe('Something else');
    expect(screenReason('pii:name', 'en')).toBe('pii name');
  });
});
