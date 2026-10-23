import { describe, expect, it } from 'vitest';
import { dailyPoints, labelTops, niceStep, riverHeadline, toPoints, trend, xTicks, yDomain, yTicks } from './riverLine';
import { levelsAt, reached, STORY_FACTS, STORY_RAIN, STORY_STEPS } from './story';

describe('river line arithmetic', () => {
  it('rounds the y range to a nice step above the highest line', () => {
    expect(niceStep(3.5)).toBe(2);
    expect(niceStep(204.5 * 1.08)).toBe(100);
    expect(yDomain([0.44, 0.45], [1.409, 2.211, 3.252])).toEqual([0, 4]);
    expect(yTicks([0, 4])).toEqual([0, 2, 4]);
  });

  it('labels whole India-time hours, with the date where the day changes', () => {
    const t0 = Date.parse('2026-10-21T22:30:00Z'); // 04:00 IST on the 22nd
    const ticks = xTicks(t0, t0 + 24 * 3_600_000, 'en');
    expect(ticks.length).toBeGreaterThan(2);
    expect(ticks.length).toBeLessThanOrEqual(5);
    expect(ticks[0].date).not.toBeNull();
    for (const k of ticks) expect(k.time).toMatch(/^\d\d:00$/);
  });

  it('never prints two line labels on top of each other', () => {
    const tops = labelTops([100, 108, 200], 24);
    const sorted = [...tops].sort((a, b) => a - b);
    for (let i = 1; i < sorted.length; i++) expect(sorted[i] - sorted[i - 1]).toBeGreaterThanOrEqual(24);
    expect(tops[2]).toBe(200 - 24 - 2);
  });

  it('reads points, forecast days and the trend', () => {
    const pts = toPoints([
      ['2026-10-22T01:00:00Z', 1],
      ['2026-10-22T00:00:00Z', 1],
      ['2026-10-22T02:00:00Z', 1.2],
    ]);
    expect(pts.map((p) => p.v)).toEqual([1, 1, 1.2]);
    expect(trend(pts)).toBe('rising');
    expect(dailyPoints([{ date: '2026-10-22', value: 1 }, { date: '2026-10-23', value: 2 }], Date.parse('2026-10-22T08:00:00Z')).length).toBe(1);
  });

  it('says what the forecast means for the next line, in Hindi and English', () => {
    const th = { watch: 1.409, warning: 2.211, critical: 3.252 };
    const obs = [{ t: 0, v: 0.44 }, { t: 1, v: 0.44 }];
    const calm = riverHeadline(obs, [{ t: 2, v: 0.42 }, { t: 3, v: 0.41 }], th, 'm³/s', 'hi');
    expect(calm.way).toBe('→ स्थिर');
    expect(calm.ahead).toBe('अगले 2 दिन सतर्क रेखा से नीचे');
    const cross = riverHeadline(obs, [{ t: Date.parse('2026-10-24T06:30:00Z'), v: 1.6 }], th, 'm³/s', 'en');
    expect(cross.ahead).toMatch(/^May cross the watch line by 24 Oct/);
  });
});

describe('the July 2023 story', () => {
  it('uses the back-test’s own hours and leads', () => {
    expect(STORY_RAIN.length).toBe(97);
    expect(STORY_STEPS.map((s) => s.id)).toEqual(['ready', 'watch', 'warning', 'peak']);
    expect(STORY_FACTS.watchLead).toBe(67);
    expect(STORY_FACTS.readyLead).toBe(96);
  });

  it('colours the five villages by the highest level reached by then', () => {
    const v = [
      { village_id: 'a', both: { first_watch: '2023-07-07T00:00:00Z', first_warning: '2023-07-07T16:00:00Z', first_critical: '2023-07-08T00:00:00Z' } },
      { village_id: 'b', both: { first_watch: null, first_warning: null, first_critical: null } },
    ];
    expect(levelsAt(v, Date.parse('2023-07-07T12:00:00Z'))).toEqual({ a: 'watch', b: 'normal' });
    expect(levelsAt(v, Date.parse('2023-07-09T00:00:00Z'))).toEqual({ a: 'critical', b: 'normal' });
    expect(reached(v, 'critical')).toBe(1);
  });
});
