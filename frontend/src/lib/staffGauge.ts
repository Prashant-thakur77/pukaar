import type { Level, StaffGauge, StaffMark, StaffPoint } from '../types';

/**
 * Virtual staff gauge helpers (CrowdWater pattern). Coordinates are normalised to the photo:
 * 0..1 across and down, so a scale drawn on one screen size reads the same on any other.
 */

export type Scheme = { kind: 'class'; lo: number; hi: number } | { kind: 'cm'; spanCm: number; stepCm: number; baseCm: number };

export const CROWDWATER: Scheme = { kind: 'class', lo: -5, hi: 5 };

/** "+3", "0", "-5": CrowdWater-style relative classes. */
export function classLabel(v: number): string {
  return v > 0 ? `+${v}` : String(v);
}

const round4 = (n: number) => Math.round(n * 1e4) / 1e4;

/**
 * Marks evenly spaced along the drawn line, bottom (lowest value) to top (highest).
 * class: one mark per whole class lo..hi. cm: base, base+step, ... base+span.
 */
export function buildMarks(top: StaffPoint, bottom: StaffPoint, scheme: Scheme): StaffMark[] {
  const at = (f: number) => ({ x: round4(bottom.x + (top.x - bottom.x) * f), y: round4(bottom.y + (top.y - bottom.y) * f) });
  if (scheme.kind === 'class') {
    const lo = Math.round(Math.min(scheme.lo, scheme.hi));
    const hi = Math.round(Math.max(scheme.lo, scheme.hi));
    if (hi === lo) return [];
    const out: StaffMark[] = [];
    for (let v = lo; v <= hi; v++) out.push({ label: classLabel(v), value: v, ...at((v - lo) / (hi - lo)) });
    return out;
  }
  const { spanCm, stepCm, baseCm } = scheme;
  if (!(spanCm > 0) || !(stepCm > 0)) return [];
  const n = Math.floor(spanCm / stepCm + 1e-9);
  const out: StaffMark[] = [];
  for (let i = 0; i <= n; i++) {
    const h = baseCm + i * stepCm;
    out.push({ label: `${h} cm`, value: h, height_cm: h, ...at((i * stepCm) / spanCm) });
  }
  return out;
}

/** Highest first: the order a person reads a staff gauge, top to bottom. */
export function marksTopFirst(marks: StaffMark[]): StaffMark[] {
  return [...marks].sort((a, b) => b.value - a.value);
}

/** The level a mark means on this gauge, as services/staff_gauge.level_for. */
export function levelForMark(g: Pick<StaffGauge, 'watch_at' | 'warning_at' | 'critical_at'>, value: number): Level {
  let level: Level = 'normal';
  if (g.watch_at != null && value >= g.watch_at) level = 'watch';
  if (g.warning_at != null && value >= g.warning_at) level = 'warning';
  if (g.critical_at != null && value >= g.critical_at) level = 'critical';
  return level;
}

/** The mark nearest a tap on the photo (by height along the scale). */
export function nearestMark(marks: StaffMark[], y: number): StaffMark | null {
  let best: StaffMark | null = null;
  for (const m of marks) if (!best || Math.abs(m.y - y) < Math.abs(best.y - y)) best = m;
  return best;
}

/** One evidence line: "Staff gauge: +3 at 14:20, confirmed by officer1". */
export function staffEvidenceLine(
  e: Record<string, unknown>,
  time: string,
  lang: 'hi' | 'en',
): string {
  const mark = String(e.mark ?? '');
  if (e.status === 'confirmed') {
    const by = e.confirmed_by ? String(e.confirmed_by) : lang === 'hi' ? 'अधिकारी' : 'an officer';
    return lang === 'hi' ? `पैमाना: ${time} पर ${mark}, ${by} ने पुष्टि की` : `Staff gauge: ${mark} at ${time}, confirmed by ${by}`;
  }
  if (e.status === 'unreadable') return lang === 'hi' ? `पैमाना: ${time} की फ़ोटो पढ़ी नहीं जा सकी` : `Staff gauge: photo at ${time} could not be read`;
  return lang === 'hi'
    ? `पैमाना: ${time} पर गाँव वाले ने ${mark} चुना (जाँच बाकी, स्तर नहीं बदलता)`
    : `Staff gauge: villager chose ${mark} at ${time} (not yet checked; does not change the level)`;
}

/** Same rule as Cedar: officers anywhere, a pradhan in their own village. The server decides. */
export function canManageStaffGauge(user: { role: string; village_ids: string[] } | null | undefined, villageId: string): boolean {
  if (!user) return false;
  return user.role === 'officer' || (user.role === 'pradhan' && user.village_ids.includes(villageId));
}
