import type { Counters } from '../types';

/**
 * The landing page's counters, in order: what the system has done, each counted from stored
 * records (backend api/views.py counters()). Real flood alerts, drills and replays are kept apart,
 * so a drill is never shown as a flood warning sent.
 */
export const LANDING_COUNTERS = [
  'villages_watched',
  'forecast_checks_24h',
  'alerts_sent',
  'drills_delivered',
  'replay_alerts_approved',
  'reports_received',
] as const satisfies readonly (keyof Counters)[];
