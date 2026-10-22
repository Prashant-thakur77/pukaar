import { describe, expect, it } from 'vitest';
import { addDays, approvalTimes, chainRole, emptyShifts, isCurrent, istClock, nobodyOnDuty, relayLabel, shiftWindow, todayIST, validUsername } from './roster';
import type { OnDuty, RosterDay } from '../types';

function day(date: string, entries: Partial<Record<'day' | 'night', boolean>> = {}): RosterDay {
  const next = addDays(date, 1);
  // 08:00 IST = 02:30 UTC; 20:00 IST = 14:30 UTC
  const entry = (shift: 'day' | 'night') =>
    entries[shift]
      ? { district: 'Mandi', date, shift, primary: 'officer1', backup: null, escalation: null, escalation_title: 'ADM' as const, note: '', updated_by: 'officer1', updated_at: '', taken_over_from: null, taken_over_at: null }
      : null;
  return {
    date,
    weekday: 'Wed',
    shifts: {
      day: { starts_at: `${date}T02:30:00Z`, ends_at: `${date}T14:30:00Z`, entry: entry('day') },
      night: { starts_at: `${date}T14:30:00Z`, ends_at: `${next}T02:30:00Z`, entry: entry('night') },
    },
  };
}

describe('duty roster helpers', () => {
  it('reads the date in IST, not UTC', () => {
    expect(todayIST(new Date('2026-10-22T18:29:00Z'))).toBe('2026-10-22'); // 23:59 IST
    expect(todayIST(new Date('2026-10-22T18:30:00Z'))).toBe('2026-10-23'); // 00:00 IST
  });

  it('moves dates across month ends', () => {
    expect(addDays('2026-10-30', 3)).toBe('2026-11-02');
    expect(addDays('2026-11-02', -7)).toBe('2026-10-26');
  });

  it('shows shift windows in IST', () => {
    expect(istClock('2026-10-22T14:30:00Z')).toBe('20:00');
    expect(shiftWindow('2026-10-22T14:30:00Z', '2026-10-23T02:30:00Z')).toBe('20:00–08:00 IST');
  });

  it('knows which shift is running, across midnight', () => {
    const d = day('2026-10-22');
    expect(isCurrent(d, 'night', new Date('2026-10-22T20:30:00Z'))).toBe(true); // 02:00 IST on the 23rd
    expect(isCurrent(d, 'day', new Date('2026-10-22T20:30:00Z'))).toBe(false);
    expect(isCurrent(d, 'day', new Date('2026-10-22T02:30:00Z'))).toBe(true);
  });

  it('counts the empty shifts still to come', () => {
    const week = [day('2026-10-22', { day: true }), day('2026-10-23', { day: true, night: true })];
    expect(emptyShifts(week, new Date('2026-10-22T03:00:00Z'))).toBe(1);
    expect(emptyShifts(week, new Date('2026-10-23T03:00:00Z'))).toBe(0); // last night has passed
  });

  it('names the chain roles plainly', () => {
    expect(chainRole('primary', 'en')).toBe('Primary');
    expect(chainRole('escalation (DM)', 'en')).toBe('DM');
    expect(chainRole('fallback #2', 'en')).toBe('List 2');
    expect(chainRole('backup', 'hi')).toBe('बैकअप');
    expect(relayLabel('gauge_reader', 'en')).toBe('Gauge reader');
  });

  it('treats anything but a roster row as nobody on duty', () => {
    const base = { district: 'Mandi', date: '', shift: 'day', starts_at: '', ends_at: '', chain: [], roles: [], primary: null, backup: null, escalation: null, escalation_title: null, taken_over_from: null, taken_over_at: null } as const;
    expect(nobodyOnDuty({ ...base, source: 'fallback' } as OnDuty)).toBe(true);
    expect(nobodyOnDuty({ ...base, source: 'roster' } as OnDuty)).toBe(false);
  });

  it('accepts sign-in names only', () => {
    expect(validUsername('adm_mandi')).toBe(true);
    expect(validUsername('ADM Mandi')).toBe(false);
    expect(validUsername('')).toBe(false);
  });
});

describe('approvalTimes', () => {
  it('matches the backend defaults: reminder at 3 min (2.5 for a Critical), Critical moves on at 5 min, others at 10', () => {
    expect(approvalTimes({ approval_timeout_seconds: 600 })).toEqual({ windowMin: 10, criticalWindowMin: 5, nudgeMin: 3, criticalNudgeMin: 2.5 });
  });
  it('reads the values the API sends', () => {
    expect(approvalTimes({ approval_timeout_seconds: 900, approval_timeout_critical_seconds: 600, officer_wake_seconds: 120 })).toEqual({
      windowMin: 15,
      criticalWindowMin: 10,
      nudgeMin: 2,
      criticalNudgeMin: 2,
    });
    // Wake-up call off: the reminder is half-way through the window.
    expect(approvalTimes({ approval_timeout_seconds: 600, officer_wake_seconds: 0 }).nudgeMin).toBe(5);
    // A Critical window never exceeds the general one.
    expect(approvalTimes({ approval_timeout_seconds: 240, approval_timeout_critical_seconds: 300 }).criticalWindowMin).toBe(4);
  });
});
