import { levelWord } from '../i18n';
import type { Lang } from '../store';
import { fmtNumber } from './format';

/*
 * The arithmetic behind the river line (S1, components/RiverLine.tsx): scales, the y ticks, the two-line x ticks
 * in India time, and where the threshold labels sit so two close lines never print on top of each other.
 * Pure functions, so they are tested without a DOM.
 */

export interface RLPoint {
  /** Epoch milliseconds. */
  t: number;
  v: number | null;
}

/** [string ISO time, value] pairs (the /now endpoint's river.points) as points, oldest first. */
export function toPoints(pairs: [string, number | null][] | null | undefined): RLPoint[] {
  return (pairs ?? [])
    .map(([at, v]) => ({ t: Date.parse(at), v }))
    .filter((p) => Number.isFinite(p.t))
    .sort((a, b) => a.t - b.t);
}

/** A daily forecast ({date: "2026-10-23", value}) placed at noon India time, after `after`. */
export function dailyPoints(days: { date: string; value: number | null }[] | null | undefined, after = -Infinity): RLPoint[] {
  return (days ?? [])
    .map((d) => ({ t: Date.parse(`${d.date}T12:00:00+05:30`), v: d.value }))
    .filter((p) => Number.isFinite(p.t) && p.t > after);
}

/** A round step so that about `n` ticks cover [0, hi]: 1, 2 or 5 times a power of ten. */
export function niceStep(hi: number, n = 3): number {
  if (!(hi > 0)) return 1;
  const raw = hi / n;
  const p = 10 ** Math.floor(Math.log10(raw));
  const m = raw / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
}

/** The y range: from zero (flow and rain are never negative) to a little over the highest line or value. */
export function yDomain(values: number[], lines: number[]): [number, number] {
  // A fifth of headroom: the top line's word sits clear of the "now" label above the plot.
  const top = Math.max(0, ...values, ...lines) * 1.2;
  const step = niceStep(top || 1);
  return [0, Math.max(step, Math.ceil(top / step) * step)];
}

export function yTicks([lo, hi]: [number, number], n = 3): number[] {
  const step = niceStep(hi - lo, n);
  const out: number[] = [];
  for (let v = lo; v <= hi + step / 1e6; v += step) out.push(Math.round(v * 1e6) / 1e6);
  return out;
}

const HOUR = 3_600_000;
const IST = 5.5 * HOUR;

/**
 * x ticks on whole India-time hours: the step (3, 6, 12, 24 or 48 h) that gives at most `max` ticks. Each tick
 * says its time, and the date under it where the day changes (or on the first tick).
 */
export function xTicks(t0: number, t1: number, lang: Lang, max = 5): { t: number; time: string; date: string | null }[] {
  if (!(t1 > t0)) return [];
  const span = (t1 - t0) / HOUR;
  const step = [3, 6, 12, 24, 48, 96].find((h) => span / h <= max - 0.5) ?? 96;
  const first = Math.ceil((t0 + IST) / (step * HOUR)) * step * HOUR - IST;
  const loc = lang === 'hi' ? 'hi-IN' : 'en-IN';
  const time = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });
  const date = new Intl.DateTimeFormat(loc, { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short' });
  const out: { t: number; time: string; date: string | null }[] = [];
  let lastDay = '';
  for (let t = first; t <= t1; t += step * HOUR) {
    const d = date.format(t);
    out.push({ t, time: time.format(t), date: d !== lastDay ? d : null });
    lastDay = d;
  }
  return out;
}

/**
 * Label positions (px from the top) for lines at `ys` (px), each label `h` tall above its line: a label that would
 * overlap the one above it (or the row above `minTop`, where the "now" label is) moves down, under its line.
 */
export function labelTops(ys: number[], h: number, minTop = 0): number[] {
  const order = ys.map((y, i) => ({ y, i })).sort((a, b) => a.y - b.y);
  const tops: number[] = new Array(ys.length);
  let floor = minTop;
  for (const { y, i } of order) {
    let top = y - h - 2;
    if (top < floor) top = y + 3;
    if (top < floor) top = floor;
    tops[i] = Math.max(0, top);
    floor = tops[i] + h;
  }
  return tops;
}

/** "rising", "falling" or "steady" from the last observed values (a change under 3 % is steady). */
export function trend(points: RLPoint[], n = 4): 'rising' | 'falling' | 'steady' {
  const vs = points.map((p) => p.v).filter((v): v is number => v != null).slice(-n);
  if (vs.length < 2) return 'steady';
  const a = vs[0];
  const b = vs[vs.length - 1];
  const rel = (b - a) / Math.max(Math.abs(a), 1e-6);
  return rel > 0.03 ? 'rising' : rel < -0.03 ? 'falling' : 'steady';
}

/* ---------- the headline over the river line ---------- */

export type RiverLines = { watch: number; warning: number; critical: number; return_period_years?: { watch: number; warning: number; critical: number } | null };
export const RIVER_KEYS = ['watch', 'warning', 'critical'] as const;

export const riverNum = (v: number, lang: Lang) => fmtNumber(v, lang, v < 10 ? 2 : v < 100 ? 1 : 0);

function dayWord(t: number, lang: Lang): string {
  return new Intl.DateTimeFormat(lang === 'hi' ? 'hi-IN' : 'en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short' }).format(t);
}

/** "0.44 m³/s · → स्थिर · अगले 4 दिन सतर्क रेखा से नीचे" in parts, so the number can be set large. */
export function riverHeadline(obs: RLPoint[], fc: RLPoint[], th: RiverLines | null, unit: string, lang: Lang) {
  const hi = lang === 'hi';
  const vs = obs.filter((p) => p.v != null) as { t: number; v: number }[];
  const now = vs[vs.length - 1] ?? null;
  const dir = trend(obs);
  const way = { rising: hi ? '↑ बढ़ रही' : '↑ rising', falling: hi ? '↓ घट रही' : '↓ falling', steady: hi ? '→ स्थिर' : '→ steady' }[dir];
  let ahead: string | null = null;
  if (th && now) {
    const over = [...RIVER_KEYS].reverse().find((k) => now.v >= th[k]);
    const next = RIVER_KEYS.find((k) => now.v < th[k]);
    const line = (k: (typeof RIVER_KEYS)[number]) => (hi ? `${levelWord(k, lang)} रेखा` : `the ${levelWord(k, lang).toLowerCase()} line`);
    const cross = next ? fc.find((p) => p.v != null && p.v >= th[next]) : undefined;
    if (cross) ahead = hi ? `${dayWord(cross.t, lang)} तक ${line(next!)} पार कर सकती है` : `may cross ${line(next!)} by ${dayWord(cross.t, lang)}`;
    else if (over) ahead = hi ? `${line(over)} से ऊपर` : `above ${line(over)}`;
    else if (fc.length) ahead = hi ? `अगले ${fmtNumber(fc.length, lang)} दिन ${line('watch')} से नीचे` : `below ${line('watch')} for the next ${fc.length} days`;
  }
  // On its own line in English the sentence starts with a capital.
  if (ahead && !hi) ahead = ahead[0].toUpperCase() + ahead.slice(1);
  return { value: now ? `${riverNum(now.v, lang)} ${unit}` : '—', way, ahead };
}

