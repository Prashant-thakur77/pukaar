/*
 * Satellite before/after: the shape of public/satellite/2023/scenes.json
 * (written by scripts/build_satellite.py) and the split-slider arithmetic.
 */

export type SatScene = {
  role: 'before' | 'after';
  /** Days after the flood peak on 11 July 2023 (after scenes only). */
  days_after_peak?: number;
  scene_id: string;
  datetime: string;
  date: string;
  platform?: string;
  tile_cloud_pct: number;
  crop_cloud_pct: number;
  true_colour: string;
  water: string;
  stac: string;
  /** Water area against the before scene, counted only where both are cloud-free (after scenes only). */
  water_area?: { compared_km2: number; before_km2: number; after_km2: number };
};

export type SatMarker = {
  id: string;
  name: string;
  name_hi: string;
  kind: 'dam' | 'town' | 'village';
  x: number;
  y: number;
};

export type SatMeta = {
  available: boolean;
  reason?: string;
  event: string;
  bounds: [number, number, number, number];
  size: [number, number];
  pixel_m: number;
  source: string;
  licence: string;
  licence_url: string;
  scenes?: SatScene[];
  markers: SatMarker[];
};

export const SAT_BASE = '/satellite/2023/';

export const clampPos = (p: number): number => Math.min(100, Math.max(0, Math.round(p * 10) / 10));

/** Where the divider goes for a key press, or null if the key is not ours. */
export function nextPos(pos: number, key: string, shift = false): number | null {
  const step = shift ? 10 : 2;
  switch (key) {
    case 'ArrowLeft':
    case 'ArrowDown':
      return clampPos(pos - step);
    case 'ArrowRight':
    case 'ArrowUp':
      return clampPos(pos + step);
    case 'PageDown':
      return clampPos(pos - 10);
    case 'PageUp':
      return clampPos(pos + 10);
    case 'Home':
      return 0;
    case 'End':
      return 100;
    default:
      return null;
  }
}

/** Divider position (0-100) for a pointer at clientX over a box. */
export function posFromPointer(clientX: number, left: number, width: number): number {
  if (width <= 0) return 50;
  return clampPos(((clientX - left) / width) * 100);
}

/** Labels go right of the dot, unless near the right edge or another place sits just to the right. */
export function labelLeft(m: SatMarker, all: SatMarker[]): boolean {
  if (m.x > 0.8) return true;
  return all.some((n) => n !== m && n.x > m.x && n.x - m.x < 0.12 && Math.abs(n.y - m.y) < 0.08);
}

/** The before scene and the after scenes (earliest first), or null if the bake found no usable pair. */
export function scenePair(meta: SatMeta | null | undefined): { before: SatScene; afters: SatScene[] } | null {
  if (!meta?.available || !meta.scenes) return null;
  const before = meta.scenes.find((s) => s.role === 'before');
  const afters = meta.scenes.filter((s) => s.role === 'after').sort((a, b) => a.date.localeCompare(b.date));
  return before && afters.length ? { before, afters } : null;
}
