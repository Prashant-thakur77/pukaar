import story from '../data/story-gohar-2023.json';
import { levelRank } from './levels';
import type { RLPoint } from './riverLine';
import type { Level } from '../types';

/*
 * "The night the river rose" (S3): the July 2023 back-test for Gohar, every number from scripts/story.py's output
 * (data/story-gohar-2023.json) and the scores (data/scores.json). Nothing here is typed by hand except the words.
 */

const HOUR = 3_600_000;
const at = (iso: string) => Date.parse(iso);

/** Gohar's 24-hour rain forecast, hour by hour, 7 to 11 July 2023. */
export const STORY_RAIN: RLPoint[] = story.points.map((p) => ({ t: at(p.at), v: p.rain_24h_mm }));
export const STORY_BANDS = story.imd_bands_mm;
export const STORY_FIRST = story.first;
export const STORY_SOURCES = story.sources;
/** A little room before the first hour, so the first step's marker and its words are not on the edge. */
export const STORY_DOMAIN: [number, number] = [STORY_RAIN[0].t - 8 * HOUR, STORY_RAIN[STORY_RAIN.length - 1].t];
export const STORY_PEAK_RAIN = Math.max(...story.points.map((p) => p.rain_24h_mm));

export interface StoryStep {
  id: 'ready' | 'watch' | 'warning' | 'peak';
  t: number;
  level: Level;
}

export const STORY_STEPS: StoryStep[] = [
  { id: 'ready', t: at(story.first.get_ready), level: 'normal' },
  { id: 'watch', t: at(story.first.watch), level: 'watch' },
  { id: 'warning', t: at(story.first.warning!), level: 'warning' },
  { id: 'peak', t: at(`${story.peak_discharge_day}T00:00:00Z`), level: 'warning' },
];

export const STORY_FACTS = {
  readyLead: story.lead_hours_get_ready_to_peak_day,
  watchLead: story.lead_hours_watch_to_peak_day,
  readyLine: story.get_ready_trigger.line_cms,
  readyDaysAhead: story.get_ready_trigger.days_ahead,
  peakFlow: story.peak_discharge,
  peakDay: story.peak_discharge_day,
  watchLine: story.discharge_thresholds.watch,
  river: story.discharge_thresholds.river,
};

type Firsts = { first_watch: string | null; first_warning: string | null; first_critical: string | null };

/** The highest level each village had reached by time t in the same back-test (the five on the small valley). */
export function levelsAt(villages: { village_id: string; both: Firsts }[], t: number): Record<string, Level> {
  const out: Record<string, Level> = {};
  for (const v of villages) {
    let lv: Level = 'normal';
    if (v.both.first_watch && at(v.both.first_watch) <= t) lv = 'watch';
    if (v.both.first_warning && at(v.both.first_warning) <= t) lv = 'warning';
    if (v.both.first_critical && at(v.both.first_critical) <= t) lv = 'critical';
    out[v.village_id] = lv;
  }
  return out;
}

/** How many of the villages reached `level` at some point. */
export function reached(villages: { both: Firsts }[], level: Level): number {
  return villages.filter((v) => {
    const top = v.both.first_critical ? 'critical' : v.both.first_warning ? 'warning' : v.both.first_watch ? 'watch' : 'normal';
    return levelRank(top) >= levelRank(level);
  }).length;
}
