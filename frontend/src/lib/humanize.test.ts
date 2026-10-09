import { describe, expect, it } from 'vitest';
import { humanizeFlag, humanizeSummary } from './humanize';

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
