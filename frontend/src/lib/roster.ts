// Duty roster helpers (GET /roster). Shifts are in IST: day 08:00-20:00, night 20:00-08:00, dated the day they start.
import type { Lang } from '../store';
import type { OnDuty, RelayRole, RosterDay, ShiftId } from '../types';

const IST_OFFSET_MIN = 330;

/** YYYY-MM-DD of this moment in IST. */
export function todayIST(now: Date = new Date()): string {
  return new Date(now.getTime() + IST_OFFSET_MIN * 60_000).toISOString().slice(0, 10);
}

/** A YYYY-MM-DD date moved by n days (calendar arithmetic, no time zone involved). */
export function addDays(date: string, n: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** "20:00" in IST, for a UTC timestamp. */
export function istClock(iso: string): string {
  const d = new Date(new Date(iso).getTime() + IST_OFFSET_MIN * 60_000);
  return d.toISOString().slice(11, 16);
}

/** "20:00–08:00 IST" */
export function shiftWindow(startsAt: string, endsAt: string): string {
  return `${istClock(startsAt)}–${istClock(endsAt)} IST`;
}

/** "Thu 23 Oct" (or the Hindi equivalent), read as a calendar date. */
export function dayLabel(date: string, lang: Lang): string {
  return new Intl.DateTimeFormat(lang === 'hi' ? 'hi-IN' : 'en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  }).format(new Date(`${date}T00:00:00Z`));
}

/** Is this the shift running at `now`? */
export function isCurrent(day: RosterDay, shift: ShiftId, now: Date = new Date()): boolean {
  const s = day.shifts[shift];
  const t = now.getTime();
  return new Date(s.starts_at).getTime() <= t && t < new Date(s.ends_at).getTime();
}

/** How many shifts of the week have nobody rostered (from now on). */
export function emptyShifts(days: RosterDay[], now: Date = new Date()): number {
  let n = 0;
  for (const d of days) {
    for (const s of ['day', 'night'] as ShiftId[]) {
      if (!d.shifts[s].entry && new Date(d.shifts[s].ends_at).getTime() > now.getTime()) n += 1;
    }
  }
  return n;
}

const ROLE_WORDS: Record<string, { en: string; hi: string }> = {
  primary: { en: 'Primary', hi: 'मुख्य' },
  backup: { en: 'Backup', hi: 'बैकअप' },
};

/** "primary" -> "Primary"; "escalation (ADM)" -> "ADM"; "fallback #1" -> "Fallback 1". */
export function chainRole(role: string, lang: Lang): string {
  if (ROLE_WORDS[role]) return ROLE_WORDS[role][lang];
  const esc = /^escalation \((\w+)\)$/.exec(role);
  if (esc) return esc[1];
  const fb = /^fallback #(\d+)$/.exec(role);
  if (fb) return lang === 'hi' ? `सूची ${fb[1]}` : `List ${fb[1]}`;
  return role;
}

/** The on-duty summary is a gap the control room must fill. */
export function nobodyOnDuty(d: OnDuty): boolean {
  return d.source !== 'roster';
}

const RELAY_WORDS: Record<RelayRole, { en: string; hi: string }> = {
  pradhan: { en: 'Pradhan', hi: 'प्रधान' },
  gauge_reader: { en: 'Gauge reader', hi: 'गेज रीडर' },
  task_force: { en: 'Task force', hi: 'टास्क फ़ोर्स' },
};

export function relayLabel(role: RelayRole, lang: Lang): string {
  return RELAY_WORDS[role]?.[lang] ?? role;
}

/** A sign-in name as the API accepts it (services/roster.py USERNAME). */
export function validUsername(v: string): boolean {
  return /^[A-Za-z0-9_.@-]{1,64}$/.test(v.trim());
}
