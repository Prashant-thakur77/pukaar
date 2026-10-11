import type { AuthUser } from '../store';
import type { Checklist, ChecklistItem, Readiness } from '../types';

/** Same rule as the Cedar policy: any officer, or the pradhan of this village. The server decides. */
export function canTickChecklist(user: AuthUser | null | undefined, villageId: string): boolean {
  if (!user) return false;
  if (user.role === 'officer') return true;
  return user.role === 'pradhan' && user.village_ids.includes(villageId);
}

export function isGetReady(r: Readiness | null | undefined): boolean {
  return r?.state === 'get_ready';
}

/** Fraction done, 0..1, for the progress ring. */
export function progress(c: Checklist | null | undefined): number {
  if (!c || c.total <= 0) return 0;
  return Math.min(1, Math.max(0, c.done / c.total));
}

/** Replace one item in a checklist and recount (optimistic update before the server answers). */
export function withItem(c: Checklist, item: string, done: boolean): Checklist {
  const items: ChecklistItem[] = c.items.map((i) => (i.item === item ? { ...i, done } : i));
  return { ...c, items, done: items.filter((i) => i.done).length };
}

/** Position of a 0..1 value on a bar, as a CSS percentage. */
export function pct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '0%';
  return `${Math.round(Math.min(1, Math.max(0, v)) * 1000) / 10}%`;
}
