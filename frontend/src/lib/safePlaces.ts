import type { AuthUser, Lang } from '../store';
import type { SafePlace, SafePlacesView, ShelterLedgerState, ShelterState } from '../types';
import { fmtNumber } from './format';

/** Hill walking pace used for every time shown (3 km/h = 50 m a minute), as in scripts/build_safe_places.py. */
export const WALK_M_PER_MIN = 50;
export const SHELTER_STATES: ShelterState[] = ['OPEN', 'STANDBY', 'FULL', 'CLOSED'];
/** States an alert may name, best first (mirrors services/safe_places.USABLE). */
const USABLE: ShelterLedgerState[] = ['OPEN', 'STANDBY'];

export function walkMinutes(metres: number): number {
  return Math.ceil(Math.max(0, metres) / WALK_M_PER_MIN);
}

export function fmtDistance(metres: number, lang: Lang): string {
  if (metres < 1000) return `${fmtNumber(Math.round(metres / 10) * 10, lang)} m`;
  return `${fmtNumber(metres / 1000, lang, 1)} km`;
}

export function fmtGrade(grade: number, lang: Lang): string {
  return `${fmtNumber(Math.round(grade * 100), lang)}%`;
}

/** Officers may update any village's shelters; a pradhan only their own (the Cedar policy decides; this only hides buttons). */
export function canEditShelters(user: AuthUser | null, villageId: string): boolean {
  if (!user) return false;
  if (user.role === 'officer') return true;
  return user.role === 'pradhan' && user.village_ids.includes(villageId);
}

/** The place an alert would name right now: OPEN before STANDBY, then by route rank. */
export function namedInAlerts(places: SafePlace[]): SafePlace | null {
  const usable = places.filter((p) => USABLE.includes(p.ledger.status));
  usable.sort((a, b) => USABLE.indexOf(a.ledger.status) - USABLE.indexOf(b.ledger.status) || a.rank - b.rank);
  return usable[0] ?? null;
}

/** Every coordinate of the places and routes, for fitting the map. */
export function viewPoints(views: SafePlacesView[]): [number, number][] {
  const pts: [number, number][] = [];
  for (const v of views) {
    for (const p of v.places) pts.push([p.lon, p.lat]);
    for (const f of v.routes.features) {
      if (f.geometry.type === 'LineString') pts.push(...f.geometry.coordinates);
      else pts.push(f.geometry.coordinates);
    }
  }
  return pts;
}

/** The route features of several villages as one collection, rank 1 drawn last (on top). */
export function routeCollection(views: SafePlacesView[]) {
  const features = views.flatMap((v) => v.routes.features.filter((f) => f.properties.feature === 'route'));
  features.sort((a, b) => (b.properties.rank ?? 9) - (a.properties.rank ?? 9));
  return { type: 'FeatureCollection' as const, features };
}
