import { beforeEach, describe, expect, it } from 'vitest';
import { isSnoozed, isTyping, pruneSnoozes, readSnoozes, sortQueue, step, waitedMinutes, writeSnoozes } from './inbox';

const a = (id: string, level: 'normal' | 'watch' | 'warning' | 'critical', created_at: string, updated_at = created_at) => ({ id, level, created_at, updated_at });

describe('the inbox order (spec 4.9)', () => {
  it('puts the most severe first, then the one waiting longest', () => {
    const q = sortQueue([a('w1', 'watch', '2026-10-22T03:00:00Z'), a('c1', 'critical', '2026-10-22T03:06:00Z'), a('w0', 'watch', '2026-10-22T02:00:00Z'), a('x', 'warning', '2026-10-22T03:10:00Z')]);
    expect(q.map((x) => x.id)).toEqual(['c1', 'x', 'w0', 'w1']);
  });

  it('counts the wait in whole minutes and steps through the list without falling off', () => {
    expect(waitedMinutes('2026-10-22T03:00:00Z', Date.parse('2026-10-22T03:04:59Z'))).toBe(4);
    expect(step(['a', 'b', 'c'], 'b', 1)).toBe('c');
    expect(step(['a', 'b', 'c'], 'c', 1)).toBe('c');
    expect(step(['a', 'b', 'c'], 'a', -1)).toBe('a');
    expect(step(['a', 'b', 'c'], null, 1)).toBe('a');
    expect(step([], 'a', 1)).toBeNull();
  });
});

describe('snooze: ten minutes, sooner on new data', () => {
  beforeEach(() => localStorage.clear());
  const now = Date.parse('2026-10-22T03:10:00Z');
  const alert = a('alr_1', 'warning', '2026-10-22T03:00:00Z', '2026-10-22T03:00:00Z');
  const s = { alr_1: { until: now + 10 * 60000, level: 'warning' as const, updated: '2026-10-22T03:00:00Z' } };

  it('holds until the time is up', () => {
    expect(isSnoozed(alert, s, now)).toBe(true);
    expect(isSnoozed(alert, s, now + 10 * 60000 + 1)).toBe(false);
  });

  it('wakes at once when the level changes or the alert moves on', () => {
    expect(isSnoozed({ ...alert, level: 'critical' }, s, now)).toBe(false);
    expect(isSnoozed({ ...alert, updated_at: '2026-10-22T03:12:00Z' }, s, now)).toBe(false);
  });

  it('is kept on the phone and forgets alerts that were decided', () => {
    writeSnoozes(s);
    expect(readSnoozes()).toEqual(s);
    expect(pruneSnoozes(s, new Set(), now)).toEqual({});
    expect(pruneSnoozes(s, new Set(['alr_1']), now)).toEqual(s);
  });

  it('never fires a shortcut while typing', () => {
    const input = document.createElement('input');
    expect(isTyping(input)).toBe(true);
    expect(isTyping(document.body)).toBe(false);
  });
});
