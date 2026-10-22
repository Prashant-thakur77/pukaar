import { describe, expect, it } from 'vitest';
import { dataIssue, levelIsKnown, liveLevelIfDifferent } from './dataStatus';

describe('data status', () => {
  it('is no issue when the data is ok or the field is missing (older API)', () => {
    expect(dataIssue({ data_status: 'ok' })).toBeNull();
    expect(dataIssue({})).toBeNull();
  });

  it('reports a late or missing forecast with the time of the last good data', () => {
    expect(dataIssue({ data_status: 'stale', data_ok_at: '2026-10-22T08:00:00Z' })).toEqual({ kind: 'stale', okAt: '2026-10-22T08:00:00Z', note: '' });
    expect(dataIssue({ data_status: 'unavailable', data_note: 'rain missing' })).toEqual({ kind: 'unavailable', okAt: null, note: 'rain missing' });
  });

  it('never lets missing data read as a reassuring Normal', () => {
    expect(levelIsKnown({ level: 'normal', data_status: 'unavailable' })).toBe(false);
    expect(levelIsKnown({ level: 'normal', data_status: 'stale' })).toBe(false);
    expect(levelIsKnown({ level: 'normal', data_status: 'ok' })).toBe(true);
    // A raised level is held while data is missing: it still shows.
    expect(levelIsKnown({ level: 'warning', data_status: 'unavailable' })).toBe(true);
  });

  it('names the live level only when the page shows a different one', () => {
    expect(liveLevelIfDifferent({ level: 'critical', live_level: 'normal', replay: true })).toBe('normal');
    expect(liveLevelIfDifferent({ level: 'warning', live_level: 'warning' })).toBeNull();
    expect(liveLevelIfDifferent({ level: 'watch' })).toBeNull();
  });
});
