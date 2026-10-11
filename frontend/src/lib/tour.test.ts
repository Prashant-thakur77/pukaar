import { beforeEach, describe, expect, it } from 'vitest';
import { placePopover, scrollTargetY, TOUR_KEY, TOUR_LENGTH, TOUR_STEPS, useTour } from './tour';

const reset = () => useTour.setState({ active: false, step: 0, dir: 1, seen: false });

describe('tour steps', () => {
  it('ends with the end card and every other step names a route and bilingual words', () => {
    expect(TOUR_STEPS.at(-1)?.targets).toEqual([]);
    for (const s of TOUR_STEPS.slice(0, -1)) {
      expect(s.route).toMatch(/^\//);
      expect(s.targets.length).toBeGreaterThan(0);
      for (const t of s.targets) {
        expect(t.sel).toMatch(/^\[data-tour="[a-z-]+"\]$/);
        for (const x of [t.title, t.body]) {
          expect(x.en.trim()).not.toBe('');
          expect(x.hi).toMatch(/[ऀ-ॿ]/);
        }
      }
    }
  });

  it('walks the landing, live map, funnel, village, how and impact in order', () => {
    expect(TOUR_STEPS.map((s) => s.route ?? 'end')).toEqual(['/', '/live', '/live', '/village/gohar', '/village/gohar', '/how', '/impact', 'end']);
  });
});

describe('tour store', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    reset();
  });

  it('starts at step 1 and skips the landing intro', () => {
    useTour.getState().start();
    expect(useTour.getState()).toMatchObject({ active: true, step: 0, dir: 1 });
    expect(sessionStorage.getItem('pukaar.intro')).toBe('1');
  });

  it('moves forward and back, never before the first step', () => {
    const s = useTour.getState();
    s.start();
    s.back();
    expect(useTour.getState().step).toBe(0);
    s.next();
    s.next();
    expect(useTour.getState()).toMatchObject({ step: 2, dir: 1 });
    s.back();
    expect(useTour.getState()).toMatchObject({ step: 1, dir: -1 });
  });

  it('skips a missing target in the direction of travel', () => {
    const s = useTour.getState();
    s.start();
    s.next();
    s.next();
    s.skipMissing();
    expect(useTour.getState().step).toBe(3);
    s.back();
    s.skipMissing();
    expect(useTour.getState().step).toBe(1);
  });

  it('closes past the last step and remembers it was seen', () => {
    const s = useTour.getState();
    s.start();
    for (let i = 0; i < TOUR_LENGTH; i++) s.next();
    expect(useTour.getState()).toMatchObject({ active: false, seen: true });
    expect(localStorage.getItem(TOUR_KEY)).toBe('done');
  });

  it('remembers a skip too', () => {
    const s = useTour.getState();
    s.start();
    s.next();
    s.close();
    expect(useTour.getState()).toMatchObject({ active: false, step: 0, seen: true });
    expect(localStorage.getItem(TOUR_KEY)).toBe('done');
  });

  it('ignores moves while closed', () => {
    useTour.getState().next();
    useTour.getState().skipMissing();
    expect(useTour.getState()).toMatchObject({ active: false, step: 0 });
  });
});

describe('popover placement', () => {
  const vp = { width: 1280, height: 800 };
  const pop = { width: 340, height: 200 };

  it('goes below a short target, aligned to the ring and kept on screen', () => {
    const p = placePopover({ top: 100, left: 1100, width: 150, height: 100 }, pop, vp, 64);
    expect(p.side).toBe('below');
    expect(p.top).toBe(100 + 100 + 8 + 16);
    expect(p.left).toBe(1280 - 340 - 16);
  });

  it('goes above when there is no room below', () => {
    expect(placePopover({ top: 500, left: 40, width: 300, height: 200 }, pop, vp, 64).side).toBe('above');
  });

  it('goes beside a tall narrow target', () => {
    expect(placePopover({ top: 80, left: 40, width: 600, height: 700 }, pop, vp, 64).side).toBe('right');
  });

  it('sits over the bottom of a target that fills the screen', () => {
    const p = placePopover({ top: 80, left: 20, width: 1240, height: 900 }, pop, vp, 64);
    expect(p).toEqual({ side: 'over', top: 800 - 200 - 16, left: 1280 - 340 - 16 });
  });

  it('is centred with no target, below the header', () => {
    expect(placePopover(null, pop, vp, 64)).toEqual({ side: 'center', top: 300, left: 470 });
  });
});

describe('scroll framing', () => {
  it('centres the target and the popover room together when both fit', () => {
    // 736 px under the header; target 300 (+16 ring) + 200 popover + 16 gap leaves 204, split evenly.
    const y = scrollTargetY({ top: 1000, height: 300 }, 0, 800, 64, 200);
    expect(1000 - y).toBe(64 + 102 + 8);
  });

  it('puts a tall target just under the header', () => {
    const y = scrollTargetY({ top: 1000, height: 2000 }, 500, 800, 64, 200);
    expect(1500 - y).toBe(64 + 16 + 8);
  });

  it('never asks for a negative scroll', () => {
    expect(scrollTargetY({ top: 10, height: 100 }, 0, 800, 64, 200)).toBe(0);
  });
});
