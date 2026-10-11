import { describe, expect, it } from 'vitest';
import scenes from '../../public/satellite/2023/scenes.json';
import { clampPos, labelLeft, nextPos, posFromPointer, scenePair, type SatMeta } from './satellite';

const meta = scenes as unknown as SatMeta;

describe('satellite slider', () => {
  it('moves by keyboard and stays in range', () => {
    expect(nextPos(50, 'ArrowRight')).toBe(52);
    expect(nextPos(50, 'ArrowLeft', true)).toBe(40);
    expect(nextPos(1, 'ArrowLeft')).toBe(0);
    expect(nextPos(99, 'PageUp')).toBe(100);
    expect(nextPos(30, 'Home')).toBe(0);
    expect(nextPos(30, 'End')).toBe(100);
    expect(nextPos(30, 'a')).toBeNull();
  });

  it('maps a pointer to a position', () => {
    expect(posFromPointer(150, 100, 200)).toBe(25);
    expect(posFromPointer(0, 100, 200)).toBe(0);
    expect(posFromPointer(900, 100, 200)).toBe(100);
    expect(posFromPointer(10, 0, 0)).toBe(50);
    expect(clampPos(33.333)).toBe(33.3);
  });
});

describe('marker labels', () => {
  const mk = (id: string, x: number, y: number) => ({ id, name: id, name_hi: id, kind: 'village' as const, x, y });
  it('flips a label left near the right edge or when a neighbour sits to its right', () => {
    const a = mk('a', 0.6, 0.4);
    const b = mk('b', 0.64, 0.41);
    const c = mk('c', 0.2, 0.2);
    const d = mk('d', 0.9, 0.5);
    const all = [a, b, c, d];
    expect(labelLeft(a, all)).toBe(true);
    expect(labelLeft(b, all)).toBe(false);
    expect(labelLeft(c, all)).toBe(false);
    expect(labelLeft(d, all)).toBe(true);
  });
});

describe('baked scenes.json', () => {
  it('carries the licence and source either way', () => {
    expect(meta.licence).toBe('Contains modified Copernicus Sentinel data 2023');
    expect(meta.source).toMatch(/AWS Open Data/);
    expect(meta.bounds).toHaveLength(4);
  });

  it('is a dated pair with the after scene after the flood, or says why not', () => {
    const pair = scenePair(meta);
    if (!meta.available) {
      expect(meta.reason).toBeTruthy();
      expect(pair).toBeNull();
      return;
    }
    expect(pair).not.toBeNull();
    expect(pair!.before.date < '2023-07-09').toBe(true);
    for (const a of pair!.afters) {
      expect(a.date > '2023-07-11').toBe(true);
      expect(a.days_after_peak).toBeGreaterThan(0);
    }
    for (const s of [pair!.before, ...pair!.afters]) {
      expect(s.scene_id).toMatch(/^S2[AB]_/);
      expect(s.crop_cloud_pct).toBeGreaterThanOrEqual(0);
      expect(s.stac).toContain(s.scene_id);
    }
  });

  it('places every marker inside the picture, with the dam and Mandi among them', () => {
    for (const m of meta.markers) {
      expect(m.x).toBeGreaterThanOrEqual(0);
      expect(m.x).toBeLessThanOrEqual(1);
      expect(m.y).toBeGreaterThanOrEqual(0);
      expect(m.y).toBeLessThanOrEqual(1);
    }
    expect(meta.markers.map((m) => m.id)).toEqual(expect.arrayContaining(['pandoh-dam', 'mandi']));
  });
});
