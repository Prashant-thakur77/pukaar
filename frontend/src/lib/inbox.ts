import { levelRank } from './levels';
import type { Alert, Level } from '../types';

/*
 * The console inbox (spec 4.9): what needs a decision, in the order it needs it, and the alerts an officer set
 * aside for ten minutes. Pure functions, so the order and the snooze rules are tested on their own.
 */

/** Most severe first; within a level, the one waiting longest first. */
export function sortQueue<T extends Pick<Alert, 'level' | 'created_at'>>(alerts: T[]): T[] {
  return [...alerts].sort((a, b) => levelRank(b.level) - levelRank(a.level) || a.created_at.localeCompare(b.created_at));
}

/** Whole minutes an alert has waited. */
export function waitedMinutes(createdAt: string, now = Date.now()): number {
  const t = new Date(createdAt).getTime();
  return Number.isNaN(t) ? 0 : Math.max(0, Math.floor((now - t) / 60000));
}

/** The next or previous id in a list (J/K), staying put at either end. */
export function step(ids: string[], current: string | null, dir: 1 | -1): string | null {
  if (!ids.length) return null;
  const i = current ? ids.indexOf(current) : -1;
  if (i < 0) return ids[dir === 1 ? 0 : ids.length - 1];
  return ids[Math.min(ids.length - 1, Math.max(0, i + dir))];
}

/* ---------- snooze: kept on this phone, per officer ---------- */

export interface Snooze {
  until: number;
  /** The level when it was set aside: a new level wakes it at once ("wakes on new data"). */
  level: Level;
  /** The alert's last update then: a new draft or escalation wakes it too. */
  updated: string;
}
export type Snoozes = Record<string, Snooze>;

const KEY = 'pukaar.snoozed';

export function readSnoozes(): Snoozes {
  try {
    const raw = localStorage.getItem(KEY);
    const v = raw ? (JSON.parse(raw) as Snoozes) : {};
    return v && typeof v === 'object' ? v : {};
  } catch {
    return {};
  }
}

export function writeSnoozes(s: Snoozes): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* storage blocked: the snooze lasts for this page only */
  }
}

/** Is this alert still set aside? Not once the time is up, the level changed or the alert moved on. */
export function isSnoozed(a: Pick<Alert, 'id' | 'level' | 'updated_at'>, s: Snoozes, now = Date.now()): boolean {
  const z = s[a.id];
  return Boolean(z && z.until > now && z.level === a.level && z.updated === a.updated_at);
}

/** Drops snoozes that are over or whose alert is no longer pending. */
export function pruneSnoozes(s: Snoozes, pendingIds: Set<string>, now = Date.now()): Snoozes {
  const out: Snoozes = {};
  for (const [id, z] of Object.entries(s)) if (z.until > now && pendingIds.has(id)) out[id] = z;
  return out;
}

/** Keys typed into a field never trigger a shortcut. */
export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  return el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.closest?.('dialog[open]') != null;
}
