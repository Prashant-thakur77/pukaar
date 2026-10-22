import { ACTIONS, MEANS, NO_DATA, type ActionLine } from './actions';
import { levelIsKnown } from './dataStatus';
import { readLS, writeLS } from '../store';
import type { DataStatus, Level, VillageDetail } from '../types';

/**
 * GET /public/villages/{id}/now: the village page's first answer (about 2 kB). The page paints it at once,
 * keeps the last copy on the phone (localStorage), and paints that copy instantly on the next visit or
 * with no signal, stamped with the time it was checked.
 */
export interface SafePlaceNow {
  id: string;
  name: string | null;
  name_hi: string | null;
  kind_en: string | null;
  kind_hi: string | null;
  walk_min: number | null;
  route_length_m: number | null;
  headroom_m: number | null;
  status: string;
  route_blocked: boolean;
}

export interface VillageNow {
  id: string;
  name: string;
  name_hi: string;
  district: string;
  level: Level;
  level_since: string | null;
  live_level?: Level;
  replay?: boolean;
  level_known: boolean;
  data_status: DataStatus;
  data_ok_at: string | null;
  checked_at: string | null;
  means: ActionLine;
  actions: ActionLine[];
  safe_place: SafePlaceNow | null;
  river?: { unit: string; thresholds: { watch: number; warning: number; critical: number } | null; points: [string, number | null][] };
  generated_at?: string;
}

/** A copy kept on the phone, with when this phone last got it. */
export interface CachedNow {
  now: VillageNow;
  fetchedAt: number;
}

const KEY = (id: string) => `pukaar.now.${id}`;
export const LAST_VILLAGE_KEY = 'pukaar.lastVillage';

export function readCachedNow(id: string): CachedNow | null {
  const raw = readLS(KEY(id));
  if (!raw) return null;
  try {
    const c = JSON.parse(raw) as CachedNow;
    return c?.now?.id === id && typeof c.fetchedAt === 'number' && Array.isArray(c.now.actions) ? c : null;
  } catch {
    return null;
  }
}

export function writeCachedNow(now: VillageNow, fetchedAt = Date.now()): void {
  writeLS(KEY(now.id), JSON.stringify({ now, fetchedAt } satisfies CachedNow));
  writeLS(LAST_VILLAGE_KEY, now.id);
}

/** The same answer built from the full detail: before the API has /now, or when only the detail came back. */
export function nowFromDetail(d: VillageDetail): VillageNow {
  const v = d.village;
  const known = levelIsKnown(v);
  const readings = d.readings.filter((r) => Boolean(r.replay) === Boolean(v.replay));
  const newest = readings.reduce<string | null>((m, r) => (m && m >= r.at ? m : r.at), null);
  return {
    id: v.id,
    name: v.name,
    name_hi: v.name_hi,
    district: v.district,
    level: v.level,
    level_since: v.level_since,
    live_level: v.live_level,
    replay: v.replay,
    level_known: known,
    data_status: v.data_status ?? 'ok',
    data_ok_at: v.data_ok_at ?? null,
    checked_at: newest ?? v.latest_reading?.at ?? null,
    means: MEANS[v.level],
    actions: known ? ACTIONS[v.level] : NO_DATA,
    safe_place: null,
  };
}

/** "03:10 IST": the clock time in India, whatever the phone's own time zone. */
export function istClock(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const hm = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false }).format(d);
  return `${hm} IST`;
}

/** Minutes since a time, or null. */
export function minutesSince(iso: string | null | undefined, now = Date.now()): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? null : Math.max(0, Math.round((now - t) / 60000));
}

/** Older than an hour: the page says so instead of letting an old Normal look current. */
export const STALE_MINUTES = 60;

export function isStale(iso: string | null | undefined, now = Date.now()): boolean {
  const m = minutesSince(iso, now);
  return m != null && m > STALE_MINUTES;
}

const DISTRICT_HI: Record<string, string> = { Mandi: 'मंडी', Hamirpur: 'हमीरपुर', Kullu: 'कुल्लू', Kangra: 'काँगड़ा' };

/** "ज़िला मंडी" / "Mandi district". */
export function districtLine(district: string, lang: 'hi' | 'en'): string {
  return lang === 'hi' ? `ज़िला ${DISTRICT_HI[district] ?? district}` : `${district} district`;
}

/** The shelter ledger's word for a place: open, ready, full, closed, or not yet checked. */
export function shelterWord(status: string, lang: 'hi' | 'en'): string {
  const w: Record<string, [string, string]> = {
    OPEN: ['खुला', 'Open'],
    STANDBY: ['तैयार', 'Ready'],
    FULL: ['भरा हुआ', 'Full'],
    CLOSED: ['बंद', 'Closed'],
  };
  const [hi, en] = w[status] ?? ['जाँच बाक़ी', 'Not yet checked'];
  return lang === 'hi' ? hi : en;
}

/** "अस्पताल, 25 मिनट" from the nearest open place. */
export function placeLine(p: SafePlaceNow | null, lang: 'hi' | 'en'): string | null {
  if (!p) return null;
  const kind = lang === 'hi' ? p.kind_hi || p.kind_en : p.kind_en || p.kind_hi;
  const mins = p.walk_min != null ? (lang === 'hi' ? `${p.walk_min} मिनट` : `${p.walk_min} min`) : null;
  return [kind, mins].filter(Boolean).join(', ') || null;
}

/** Position on the four-step scale, 1 to 4. */
export function levelStep(level: Level): number {
  return { normal: 1, watch: 2, warning: 3, critical: 4 }[level];
}
