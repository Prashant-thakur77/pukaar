/**
 * The pilot-readiness checklist (data/pilot_readiness.json, copied to /pilot_readiness.json at build).
 * The owner edits the file, not the code; this reads it defensively: an item with a missing title or an
 * unknown status is shown as "not started" rather than dropped or guessed as done.
 */

export type ReadinessStatus = 'done' | 'in_progress' | 'not_started';
export const READINESS_STATUSES: ReadinessStatus[] = ['done', 'in_progress', 'not_started'];

export type Bi = { en: string; hi: string };

export interface ReadinessItem {
  id: string;
  status: ReadinessStatus;
  title: Bi;
  why: Bi;
  owner: Bi;
  note: Bi | null;
}

export interface Readiness {
  updated: string | null;
  items: ReadinessItem[];
}

function bi(x: unknown): Bi | null {
  if (!x || typeof x !== 'object') return null;
  const o = x as Record<string, unknown>;
  const en = typeof o.en === 'string' ? o.en.trim() : '';
  const hi = typeof o.hi === 'string' ? o.hi.trim() : '';
  if (!en && !hi) return null;
  return { en: en || hi, hi: hi || en };
}

export function parseReadiness(raw: unknown): Readiness | null {
  if (!raw || typeof raw !== 'object') return null;
  const doc = raw as Record<string, unknown>;
  if (!Array.isArray(doc.items)) return null;
  const items: ReadinessItem[] = [];
  for (const x of doc.items) {
    if (!x || typeof x !== 'object') continue;
    const o = x as Record<string, unknown>;
    const title = bi(o.title);
    if (typeof o.id !== 'string' || !title) continue;
    const status = READINESS_STATUSES.includes(o.status as ReadinessStatus) ? (o.status as ReadinessStatus) : 'not_started';
    const empty = { en: '', hi: '' };
    items.push({ id: o.id, status, title, why: bi(o.why) ?? empty, owner: bi(o.owner) ?? empty, note: bi(o.note) });
  }
  return { updated: typeof doc.updated === 'string' ? doc.updated : null, items };
}

export function countByStatus(items: ReadinessItem[]): Record<ReadinessStatus, number> {
  const out: Record<ReadinessStatus, number> = { done: 0, in_progress: 0, not_started: 0 };
  for (const i of items) out[i.status] += 1;
  return out;
}
