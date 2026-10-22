import type { DataStatus, Level } from '../types';

export type DataIssue = { kind: 'stale' | 'unavailable'; okAt: string | null; note: string };

type WithData = { data_status?: DataStatus; data_ok_at?: string | null; data_note?: string };
type WithLevels = { level: Level; live_level?: Level; replay?: boolean };

/** Forecast data that is late or missing, or null when the last sweep had complete data. */
export function dataIssue(v: WithData): DataIssue | null {
  if (v.data_status !== 'stale' && v.data_status !== 'unavailable') return null;
  return { kind: v.data_status, okAt: v.data_ok_at ?? null, note: v.data_note ?? '' };
}

/**
 * Whether the level can be shown as plain "Normal". With late or missing data it cannot: Normal
 * then means "no data says otherwise", never "safe".
 */
export function levelIsKnown(v: WithLevels & WithData): boolean {
  return !(v.level === 'normal' && dataIssue(v));
}

/**
 * The live level when the page is showing something else (a replay's level over a Normal live
 * village), so both can be said plainly. Null when the shown level is the live one.
 */
export function liveLevelIfDifferent(v: WithLevels): Level | null {
  if (!v.live_level || v.live_level === v.level) return null;
  return v.live_level;
}
