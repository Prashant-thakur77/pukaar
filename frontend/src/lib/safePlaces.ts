import type { AuthUser, Lang } from '../store';
import type { RouteFeature, SafePlace, SafePlacesView, ShelterLedgerState, ShelterState } from '../types';
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

/**
 * The place an alert would name right now: OPEN before STANDBY, then by route rank,
 * skipping any place whose baked route a road block crosses (mirrors services/safe_places.usable).
 */
export function namedInAlerts(places: SafePlace[]): SafePlace | null {
  const usable = places.filter((p) => USABLE.includes(p.ledger.status) && !p.route_blocked);
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

/** Is this route feature the best open one? Older servers send no `best`, so rank 1 stands in. */
export function isBestRoute(f: RouteFeature): boolean {
  return f.properties.best ?? (f.properties.rank === 1 && !f.properties.blocked);
}

/**
 * The route features of several villages as one collection, drawn bottom to top:
 * blocked routes, then the other open routes by rank, then the best open route on top.
 * Each feature gets `best` and `blocked` set, so the map's style never has to guess.
 */
export function routeCollection(views: SafePlacesView[]) {
  const features = views
    .flatMap((v) => v.routes.features.filter((f) => f.properties.feature === 'route'))
    .map((f) => ({ ...f, properties: { ...f.properties, best: isBestRoute(f), blocked: Boolean(f.properties.blocked) } }));
  const layer = (f: RouteFeature) => (f.properties.blocked ? 0 : f.properties.best ? 2 : 1);
  features.sort((a, b) => layer(a) - layer(b) || (b.properties.rank ?? 9) - (a.properties.rank ?? 9));
  return { type: 'FeatureCollection' as const, features };
}

/** Active road blocks of several villages as map points. */
export function blockCollection(views: SafePlacesView[]) {
  return {
    type: 'FeatureCollection' as const,
    features: views.flatMap((v) =>
      (v.roadblocks ?? []).map((b) => ({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: [b.lon, b.lat] as [number, number] },
        properties: { id: b.id, village_id: v.village_id, note: b.note, label: b.label },
      })),
    ),
  };
}

/** Screen distance under which a safe-place pin would hide under (or on) its village's marker. */
export const FAN_MIN_PX = 48;
const FAN_RADIUS_PX = 58;
const FAN_STEP_DEG = 42;

/** A pin is 44 x 48 px with its tip at the anchor; its middle is this far above the tip. */
const PIN_MID_PX = 24;
/** Arc directions tried in turn: above the marker, below it, then to its left. */
const FAN_DIRS = [-90, 90, 180];

/**
 * Screen offsets for safe-place pins that would sit on their village marker at this zoom:
 * those pins are spread on a small arc around the marker (a leader line points back to the
 * true spot); pins far enough away keep a zero offset and sit at their real location.
 * The arc goes above the marker unless that would cover another village's marker (`avoid`)
 * or run off the top of the map (`topPx`); then below, then to the left.
 * Points are [x, y] in screen pixels; y grows downwards.
 */
export function fanOffsets(
  village: [number, number],
  pins: [number, number][],
  avoid: [number, number][] = [],
  topPx = -Infinity,
  minPx = FAN_MIN_PX,
): [number, number][] {
  const out: [number, number][] = pins.map(() => [0, 0]);
  const close = pins.flatMap((p, i) => (Math.hypot(p[0] - village[0], p[1] - village[1]) < minPx ? [i] : []));
  const n = close.length;
  if (!n) return out;
  const tips = (dir: number): [number, number][] =>
    close.map((_, k) => {
      const rad = ((dir + (k - (n - 1) / 2) * FAN_STEP_DEG) * Math.PI) / 180;
      const mx = village[0] + FAN_RADIUS_PX * Math.cos(rad);
      const my = village[1] + FAN_RADIUS_PX * Math.sin(rad);
      return [mx, my + PIN_MID_PX]; // the pin's middle sits on the arc; the anchor is its tip
    });
  const cost = (ts: [number, number][]) =>
    ts.reduce(
      (c, [x, y]) => c + avoid.filter(([ax, ay]) => Math.hypot(ax - x, ay - (y - PIN_MID_PX)) < minPx).length + (y - 2 * PIN_MID_PX < topPx ? 1 : 0),
      0,
    );
  let best = tips(FAN_DIRS[0]);
  for (const dir of FAN_DIRS.slice(1)) {
    if (cost(best) === 0) break;
    const next = tips(dir);
    if (cost(next) < cost(best)) best = next;
  }
  close.forEach((i, k) => {
    out[i] = [Math.round(best[k][0] - pins[i][0]), Math.round(best[k][1] - pins[i][1])];
  });
  return out;
}

/* ---------- geometry on a local flat projection (metres; fine over a few km) ---------- */

const M_PER_DEG = 111_320;

function toXY(lon: number, lat: number, lat0: number): [number, number] {
  return [lon * M_PER_DEG * Math.cos((lat0 * Math.PI) / 180), lat * M_PER_DEG];
}

function fromXY(x: number, y: number, lat0: number): [number, number] {
  return [x / (M_PER_DEG * Math.cos((lat0 * Math.PI) / 180)), y / M_PER_DEG];
}

function routeLines(view: SafePlacesView, placeId?: string): [number, number][][] {
  return view.routes.features
    .filter((f) => f.properties.feature === 'route' && f.geometry.type === 'LineString' && (!placeId || f.properties.place_id === placeId))
    .map((f) => f.geometry.coordinates as [number, number][]);
}

/** The nearest point on the village's baked routes (or one place's route) to a tapped point, and how far it was. */
export function snapToRoute(
  view: SafePlacesView,
  lon: number,
  lat: number,
  placeId?: string,
): { lon: number; lat: number; distance_m: number } | null {
  const [px, py] = toXY(lon, lat, lat);
  let best: { lon: number; lat: number; distance_m: number } | null = null;
  for (const line of routeLines(view, placeId)) {
    for (let i = 0; i < line.length - 1; i++) {
      const [ax, ay] = toXY(line[i][0], line[i][1], lat);
      const [bx, by] = toXY(line[i + 1][0], line[i + 1][1], lat);
      const dx = bx - ax;
      const dy = by - ay;
      const seg = dx * dx + dy * dy;
      const t = seg === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / seg));
      const sx = ax + t * dx;
      const sy = ay + t * dy;
      const d = Math.hypot(sx - px, sy - py);
      if (!best || d < best.distance_m) {
        const [slon, slat] = fromXY(sx, sy, lat);
        best = { lon: slon, lat: slat, distance_m: d };
      }
    }
  }
  return best;
}

/** The point halfway along a place's baked route, by length (the keyboard way to mark a route blocked). */
export function routeMidpoint(view: SafePlacesView, placeId: string): { lon: number; lat: number } | null {
  const lines = routeLines(view, placeId);
  if (!lines.length) return null;
  const lat0 = lines[0][0][1];
  const segs: { a: [number, number]; b: [number, number]; len: number }[] = [];
  for (const line of lines) {
    for (let i = 0; i < line.length - 1; i++) {
      const a = toXY(line[i][0], line[i][1], lat0);
      const b = toXY(line[i + 1][0], line[i + 1][1], lat0);
      segs.push({ a, b, len: Math.hypot(b[0] - a[0], b[1] - a[1]) });
    }
  }
  const total = segs.reduce((s, x) => s + x.len, 0);
  if (total === 0) return { lon: lines[0][0][0], lat: lines[0][0][1] };
  let left = total / 2;
  for (const s of segs) {
    if (left <= s.len) {
      const t = s.len ? left / s.len : 0;
      const [lon, lat] = fromXY(s.a[0] + t * (s.b[0] - s.a[0]), s.a[1] + t * (s.b[1] - s.a[1]), lat0);
      return { lon, lat };
    }
    left -= s.len;
  }
  const last = lines.at(-1)!.at(-1)!;
  return { lon: last[0], lat: last[1] };
}
