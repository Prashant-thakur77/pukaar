import { describe, expect, it } from 'vitest';
import type { SafePlace, SafePlacesView, ShelterLedgerState } from '../types';
import {
  blockCollection,
  canEditShelters,
  FAN_MIN_PX,
  fanOffsets,
  fmtDistance,
  namedInAlerts,
  routeCollection,
  routeMidpoint,
  snapToRoute,
  viewPoints,
  walkMinutes,
} from './safePlaces';

function place(id: string, rank: number, status: ShelterLedgerState): SafePlace {
  return {
    id, osm_url: '', name: id, name_hi: id, kind: 'school', kind_en: 'School', kind_hi: 'विद्यालय', lat: 31.5, lon: 77.1,
    elevation_m: 1900, headroom_m: 40, route_length_m: 900, off_network_m: 0, climb_m: 30, max_grade: 0.1, steep_m: 0,
    near_water_m: 0, walk_min: 18, rank,
    ledger: { status, capacity: null, note: '', updated_by: null, updated_at: null },
  };
}

describe('safe places', () => {
  it('walks at 3 km/h and rounds up', () => {
    expect(walkMinutes(900)).toBe(18);
    expect(walkMinutes(901)).toBe(19);
    expect(fmtDistance(840, 'en')).toBe('840 m');
    expect(fmtDistance(1250, 'en')).toBe('1.3 km');
  });

  it('names an OPEN place before a nearer STANDBY one, and never an unconfirmed, full or closed one', () => {
    expect(namedInAlerts([place('a', 1, 'UNCONFIRMED'), place('b', 2, 'FULL'), place('c', 3, 'CLOSED')])).toBeNull();
    expect(namedInAlerts([place('a', 1, 'STANDBY'), place('b', 2, 'OPEN')])?.id).toBe('b');
    expect(namedInAlerts([place('a', 2, 'STANDBY'), place('b', 1, 'STANDBY')])?.id).toBe('b');
  });

  it('lets officers edit any village and pradhans only their own', () => {
    expect(canEditShelters(null, 'thunag')).toBe(false);
    expect(canEditShelters({ username: 'o', role: 'officer', village_ids: [] }, 'gohar')).toBe(true);
    expect(canEditShelters({ username: 'p', role: 'pradhan', village_ids: ['thunag'] }, 'thunag')).toBe(true);
    expect(canEditShelters({ username: 'p', role: 'pradhan', village_ids: ['thunag'] }, 'gohar')).toBe(false);
  });

  it('collects every point and draws the best route last', () => {
    const view: SafePlacesView = {
      village_id: 'thunag', available: true, places: [place('a', 1, 'OPEN')], notes: [], attribution: null,
      limits_en: '', limits_hi: '',
      routes: {
        type: 'FeatureCollection',
        features: [
          { type: 'Feature', geometry: { type: 'LineString', coordinates: [[77, 31], [77.1, 31.1]] }, properties: { feature: 'route', rank: 1, steep: false } },
          { type: 'Feature', geometry: { type: 'LineString', coordinates: [[77, 31], [77.2, 31.2]] }, properties: { feature: 'route', rank: 2, steep: true } },
          { type: 'Feature', geometry: { type: 'Point', coordinates: [77, 31] }, properties: { feature: 'start' } },
        ],
      },
    };
    expect(viewPoints([view])).toHaveLength(6);
    const ranks = routeCollection([view]).features.map((f) => f.properties.rank);
    expect(ranks).toEqual([2, 1]);
  });
});

describe('road blocks', () => {
  // School route east (rank 1), temple route north (rank 2), both from the same start.
  function routed(blockedRank?: number): SafePlacesView {
    const r = (rank: number, pid: string, coordinates: [number, number][]) => ({
      type: 'Feature' as const,
      geometry: { type: 'LineString' as const, coordinates },
      properties: {
        feature: 'route' as const, rank, place_id: pid, steep: false,
        blocked: blockedRank === rank, best: blockedRank === undefined ? rank === 1 : rank !== blockedRank && rank === (blockedRank === 1 ? 2 : 1),
      },
    });
    return {
      village_id: 'thunag', available: true, notes: [], attribution: null, limits_en: '', limits_hi: '',
      places: [
        { ...place('school', 1, 'OPEN'), route_blocked: blockedRank === 1, best_open_route: blockedRank !== 1 },
        { ...place('temple', 2, 'OPEN'), route_blocked: blockedRank === 2, best_open_route: blockedRank === 1 },
      ],
      routes: {
        type: 'FeatureCollection',
        features: [r(1, 'school', [[77.17, 31.56], [77.172, 31.56], [77.174, 31.56]]), r(2, 'temple', [[77.17, 31.56], [77.17, 31.565]])],
      },
      roadblocks: blockedRank
        ? [{ id: 'rb1', lat: 31.56, lon: 77.1715, label: 'Khad bridge', note: 'Washed away', created_by: 'officer1', created_at: '', renewed_by: null, renewed_at: null, expires_at: '', place_ids: ['school'] }]
        : [],
    };
  }

  it('never names a place whose route is blocked, and falls back to the next open one', () => {
    expect(namedInAlerts(routed().places)?.id).toBe('school');
    expect(namedInAlerts(routed(1).places)?.id).toBe('temple');
    const all = routed(1).places.map((p) => ({ ...p, route_blocked: true }));
    expect(namedInAlerts(all)).toBeNull();
  });

  it('draws blocked routes at the bottom and the promoted route on top', () => {
    const order = routeCollection([routed(1)]).features.map((f) => [f.properties.place_id, f.properties.blocked, f.properties.best]);
    expect(order).toEqual([
      ['school', true, false],
      ['temple', false, true],
    ]);
    // An older server sends no best/blocked: rank 1 stands in as the best.
    const old = routed();
    old.routes.features.forEach((f) => {
      delete f.properties.best;
      delete f.properties.blocked;
    });
    expect(routeCollection([old]).features.map((f) => f.properties.best)).toEqual([false, true]);
    expect(blockCollection([routed(1)]).features[0].geometry.coordinates).toEqual([77.1715, 31.56]);
  });

  it('snaps a tap to the nearest route and finds the halfway point of a route', () => {
    const v = routed();
    const snap = snapToRoute(v, 77.171, 31.5602)!;
    expect(snap.lat).toBeCloseTo(31.56, 6);
    expect(snap.lon).toBeCloseTo(77.171, 6);
    expect(snap.distance_m).toBeGreaterThan(20);
    expect(snap.distance_m).toBeLessThan(25);
    // Only the temple route when asked for it.
    expect(snapToRoute(v, 77.171, 31.5602, 'temple')!.lon).toBeCloseTo(77.17, 6);
    const mid = routeMidpoint(v, 'school')!;
    expect(mid.lon).toBeCloseTo(77.172, 5);
    expect(mid.lat).toBeCloseTo(31.56, 6);
    expect(routeMidpoint(v, 'nowhere')).toBeNull();
  });
});

describe('fanning safe-place pins off their village marker', () => {
  it('leaves far pins alone and spreads close pins on an arc above the marker', () => {
    const village: [number, number] = [200, 200];
    const offs = fanOffsets(village, [
      [400, 400],
      [202, 198],
      [199, 203],
    ]);
    expect(offs[0]).toEqual([0, 0]);
    const placed = [1, 2].map((i) => [[202, 198], [199, 203]][i - 1].map((c, k) => c + offs[i][k]));
    for (const [x, y] of placed) {
      // Each pin's middle (24 px above its tip) now sits clear of the 44 px village marker, and above it.
      expect(Math.hypot(x - village[0], y - 24 - village[1])).toBeGreaterThanOrEqual(FAN_MIN_PX);
      expect(y).toBeLessThan(village[1] - 20);
    }
    // Two pins never land on the same spot.
    expect(placed[0]).not.toEqual(placed[1]);
  });

  it('fans below instead when above would cover another village or run under the legend', () => {
    const village: [number, number] = [200, 200];
    const pins: [number, number][] = [[201, 199]];
    const tipY = (o: [number, number][]) => pins[0][1] + o[0][1];
    expect(tipY(fanOffsets(village, pins))).toBeLessThan(200);
    // Another village's marker sits just above this one.
    expect(tipY(fanOffsets(village, pins, [[200, 140]]))).toBeGreaterThan(240);
    // The legend covers the top 170 px of the map.
    expect(tipY(fanOffsets(village, pins, [], 170))).toBeGreaterThan(240);
  });
});
