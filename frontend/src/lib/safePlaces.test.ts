import { describe, expect, it } from 'vitest';
import type { SafePlace, SafePlacesView, ShelterLedgerState } from '../types';
import { canEditShelters, fmtDistance, namedInAlerts, routeCollection, viewPoints, walkMinutes } from './safePlaces';

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
