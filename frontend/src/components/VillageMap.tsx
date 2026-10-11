import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ExpressionSpecification, Map as MlMap, Marker } from 'maplibre-gl';
import { Tent } from 'lucide-react';
import { dict, useT } from '../i18n';
import { LEVEL_ICON, levelRank } from '../lib/levels';
import { fanOffsets, routeCollection, viewPoints } from '../lib/safePlaces';
import { fmtNumber } from '../lib/format';
import { prefersReducedMotion } from '../hooks/useMotion';
import { usePrefs } from '../store';
import type { Level, SafePlace, SafePlacesView } from '../types';

export interface MapVillage {
  id: string;
  name: string;
  name_hi: string;
  lat: number;
  lon: number;
  level: Level;
  coords_verified: boolean;
}

interface Props {
  villages: MapVillage[];
  highlight?: string[];
  points?: { lat: number; lon: number; label: string }[];
  onSelect?: (id: string) => void;
  className?: string;
  /** Fit to these ids instead of all villages. */
  focus?: string[];
  compact?: boolean;
  /** Small caption over the map, e.g. "Current levels". */
  caption?: string;
  /** Safe places and walking routes to draw (one view per village). */
  safe?: SafePlacesView[];
  /** Fit the camera to the safe places and routes too (the village page). */
  fitSafe?: boolean;
  /** When set, the map shows a "Safe places" layer switch (the live map). */
  safeToggle?: { on: boolean; onChange: (on: boolean) => void };
  onSafeSelect?: (placeId: string, villageId: string) => void;
  /** Tapping a walking route calls this with the tapped point (the village page's "Mark blocked"). */
  onRouteSelect?: (sel: { placeId: string; villageId: string | null; lon: number; lat: number }) => void;
}

// Stable defaults: a fresh `[]` on every render would retrigger the marker
// effect (which sets state) and loop forever.
const NO_IDS: string[] = [];
const NO_POINTS: { lat: number; lon: number; label: string }[] = [];
const NO_SAFE: SafePlacesView[] = [];

/** River blue for the walking routes; MapLibre paints on the canvas, so these are literal colours. */
const ROUTE_BLUE = '#1f8fd6';
const ROUTE_GLOW = '#4fb3ff';
/** A blocked route is crossed out in crimson. */
const ROUTE_BLOCKED = '#c8102e';
const SAFE_SOURCE = 'safe-routes';
const SAFE_LAYERS = ['safe-route-glow', 'safe-route-casing', 'safe-route-solid', 'safe-route-steep', 'safe-route-blocked', 'safe-route-hit'];
/** The best open route (or, from an older server, rank 1) is drawn strongest. */
const byBest = (best: number, other: number): ExpressionSpecification => ['case', ['==', ['get', 'best'], true], best, other];
const OPEN: ExpressionSpecification = ['!=', ['get', 'blocked'], true];

/** Glow, white casing, then the line: solid on easy ground, dashed where the grade is over 20 %, crimson where blocked. */
function addRouteLayers(m: MlMap) {
  const width = (lo: number, hi: number): ExpressionSpecification => ['interpolate', ['linear'], ['zoom'], 10, lo, 16, hi];
  m.addLayer({
    id: 'safe-route-glow', type: 'line', source: SAFE_SOURCE, filter: OPEN,
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': ROUTE_GLOW, 'line-width': width(8, 18), 'line-blur': 6, 'line-opacity': byBest(0.6, 0.25) },
  });
  m.addLayer({
    id: 'safe-route-casing', type: 'line', source: SAFE_SOURCE,
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#ffffff', 'line-width': width(4, 9), 'line-opacity': byBest(0.95, 0.6) },
  });
  m.addLayer({
    id: 'safe-route-solid', type: 'line', source: SAFE_SOURCE, filter: ['all', ['!', ['get', 'steep']], OPEN],
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': ROUTE_BLUE, 'line-width': width(2.5, 5.5), 'line-opacity': byBest(1, 0.65) },
  });
  m.addLayer({
    id: 'safe-route-steep', type: 'line', source: SAFE_SOURCE, filter: ['all', ['==', ['get', 'steep'], true], OPEN],
    layout: { 'line-cap': 'butt', 'line-join': 'round' },
    paint: { 'line-color': ROUTE_BLUE, 'line-width': width(2.5, 5.5), 'line-dasharray': [1.4, 1.2], 'line-opacity': byBest(1, 0.65) },
  });
  m.addLayer({
    id: 'safe-route-blocked', type: 'line', source: SAFE_SOURCE, filter: ['==', ['get', 'blocked'], true],
    layout: { 'line-cap': 'butt', 'line-join': 'round' },
    paint: { 'line-color': ROUTE_BLOCKED, 'line-width': width(2.5, 5.5), 'line-dasharray': [2, 1.2], 'line-opacity': 0.9 },
  });
  // Wide and invisible: a finger-sized target for tapping a route.
  m.addLayer({
    id: 'safe-route-hit', type: 'line', source: SAFE_SOURCE,
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#000000', 'line-width': 24, 'line-opacity': 0 },
  });
}

/** Is the page in dark mode right now (the theme switch, or the system setting when it says "system")? */
function useDarkTheme(): boolean {
  const theme = usePrefs((s) => s.theme);
  const [systemDark, setSystemDark] = useState(
    () => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches,
  );
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const on = () => setSystemDark(mq.matches);
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);
  return theme === 'dark' || (theme === 'system' && systemDark);
}

/**
 * Dark mode darkens the base map only: the OSM raster is inverted and muted with raster paint
 * properties (brightness-min above brightness-max inverts it), so the route glow, the blocked
 * crimson and the hillshade above it keep their own colours. A CSS filter on the canvas would mute them all.
 */
function applyBaseTheme(m: MlMap, dark: boolean) {
  if (!m.getLayer('osm')) return;
  m.setPaintProperty('osm', 'raster-brightness-min', dark ? 0.82 : 0);
  m.setPaintProperty('osm', 'raster-brightness-max', dark ? 0.08 : 1);
  m.setPaintProperty('osm', 'raster-hue-rotate', dark ? 200 : 0);
  m.setPaintProperty('osm', 'raster-saturation', dark ? -0.6 : 0);
  m.setPaintProperty('osm', 'raster-contrast', dark ? -0.1 : 0);
  if (m.getLayer('hillshade')) {
    m.setPaintProperty('hillshade', 'hillshade-shadow-color', dark ? '#000000' : '#1b2340');
    m.setPaintProperty('hillshade', 'hillshade-highlight-color', dark ? 'rgba(255,255,255,0.12)' : '#ffffff');
  }
  m.setSky(
    dark
      ? { 'sky-color': '#0b1d33', 'horizon-color': '#1c2e45', 'fog-color': '#1c2e45', 'sky-horizon-blend': 0.6, 'horizon-fog-blend': 0.6, 'fog-ground-blend': 0.4 }
      : OSM_STYLE.sky,
  );
}
/** Road-block crosses show from this zoom in (street level), where the routes themselves can be read. */
const BLOCK_MIN_ZOOM = 12.5;
/** Below this width (or on compact maps) text labels collide, so markers get numbers and a key. */
const NARROW_PX = 560;

/** Mapzen Terrain Tiles, hosted by the AWS Open Data programme (public, no key). */
const DEM_TILES = ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'];
const DEM_ATTRIBUTION =
  'Elevation: <a href="https://registry.opendata.aws/terrain-tiles/">Terrain Tiles on AWS</a> (<a href="https://github.com/tilezen/joerd/blob/master/docs/attribution.md">sources</a>)';
const TERRAIN_EXAGGERATION = 1.5;
const PITCH_3D = 60;

const OSM_STYLE = {
  version: 8 as const,
  sources: {
    osm: {
      type: 'raster' as const,
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
    // Two DEM sources: MapLibre recommends separate ones for terrain and hillshade.
    dem: { type: 'raster-dem' as const, tiles: DEM_TILES, encoding: 'terrarium' as const, tileSize: 256, maxzoom: 14, attribution: DEM_ATTRIBUTION },
    shade: { type: 'raster-dem' as const, tiles: DEM_TILES, encoding: 'terrarium' as const, tileSize: 256, maxzoom: 14 },
  },
  layers: [
    { id: 'osm', type: 'raster' as const, source: 'osm' },
    {
      id: 'hillshade',
      type: 'hillshade' as const,
      source: 'shade',
      paint: { 'hillshade-exaggeration': 0.35, 'hillshade-shadow-color': '#1b2340' },
    },
  ],
  sky: {
    'sky-color': '#9cc3e6',
    'horizon-color': '#e8eef6',
    'fog-color': '#e8eef6',
    'sky-horizon-blend': 0.6,
    'horizon-fog-blend': 0.6,
    'fog-ground-blend': 0.4,
  },
};

/** One safe place on the map: a tent pin with its route rank; name, height and status on hover or focus. */
function SafeMarker({ place, villageId, onSelect }: { place: SafePlace; villageId: string; onSelect?: (id: string, villageId: string) => void }) {
  const { t, lang } = useT();
  const name = lang === 'hi' ? place.name_hi || place.name : place.name || place.name_hi;
  const status = t(`safe.status.${place.ledger.status}`);
  const m = fmtNumber(place.headroom_m, lang);
  return (
    <button
      type="button"
      className={`sp st-${place.ledger.status.toLowerCase()}`}
      aria-label={t('map.safe.marker', { name, m, status })}
      onClick={() => onSelect?.(place.id, villageId)}
    >
      <span className="sp-pin" aria-hidden="true">
        <Tent />
        <span className="sp-rank">{place.rank}</span>
      </span>
      <span className="sp-label" aria-hidden="true" lang={lang}>
        <span className="sp-name">{name}</span>
        <span className="sp-meta">
          ↑ {m} m · <span className="sp-status">{status}</span>
        </span>
      </span>
    </button>
  );
}

/** 3D by default on wide screens only; phones and compact maps start flat. */
function default3d(compact?: boolean): boolean {
  return !compact && typeof window !== 'undefined' && window.innerWidth >= 768;
}

/** MapLibre + OSM raster. Markers are real buttons rendered through portals. */
export function VillageMap({
  villages,
  highlight = NO_IDS,
  points = NO_POINTS,
  onSelect,
  className = '',
  focus,
  compact,
  caption,
  safe = NO_SAFE,
  fitSafe = false,
  safeToggle,
  onSafeSelect,
  onRouteSelect,
}: Props) {
  const { t, lang } = useT();
  const dark = useDarkTheme();
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<MlMap | null>(null);
  const markers = useRef<Map<string, Marker>>(new Map());
  const safeMarkers = useRef<Map<string, Marker>>(new Map());
  const blockMarkers = useRef<Map<string, Marker>>(new Map());
  // Read inside map event handlers, which are registered once.
  const routeSelect = useRef(onRouteSelect);
  useEffect(() => {
    routeSelect.current = onRouteSelect;
  }, [onRouteSelect]);
  const routeVillage = useRef<Map<string, string>>(new Map());
  const pointMarkers = useRef<Marker[]>([]);
  const lib = useRef<typeof import('maplibre-gl') | null>(null);
  const [els, setEls] = useState<Record<string, HTMLElement>>({});
  const [safeEls, setSafeEls] = useState<Record<string, HTMLElement>>({});
  const safePlaces = useMemo(
    () => safe.flatMap((v) => v.places.map((p) => ({ key: `${v.village_id}:${p.id}`, place: p, villageId: v.village_id }))),
    [safe],
  );
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const fitted = useRef('');
  const [tight, setTight] = useState(false);
  const [is3d, setIs3d] = useState(() => default3d(compact));
  // Read by the fit-to-villages camera move, which must not undo the tilt.
  const is3dRef = useRef(is3d);
  useEffect(() => {
    is3dRef.current = is3d;
  }, [is3d]);
  // Compact maps (Ask Pukaar) are too small for text labels at this zoom, too.
  const narrow = tight || Boolean(compact);

  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => setTight(el.clientWidth > 0 && el.clientWidth < NARROW_PX));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Numbered by risk then name, so the key below the map reads top-down.
  const numbered = useMemo(
    () => [...villages].sort((a, b) => levelRank(b.level) - levelRank(a.level) || a.name.localeCompare(b.name)),
    [villages],
  );
  const numOf = useMemo(() => new Map(numbered.map((v, i) => [v.id, i + 1])), [numbered]);

  useEffect(() => {
    let cancelled = false;
    const markerMap = markers.current;
    (async () => {
      try {
        const [ml] = await Promise.all([import('maplibre-gl'), import('maplibre-gl/dist/maplibre-gl.css')]);
        if (cancelled || !box.current) return;
        lib.current = ml;
        const m = new ml.Map({
          container: box.current,
          style: OSM_STYLE,
          center: [77.15, 31.6],
          zoom: 8,
          attributionControl: { compact: true },
          cooperativeGestures: compact ?? false,
          maxPitch: 75,
        });
        m.addControl(new ml.NavigationControl({ showCompass: true, visualizePitch: true }), 'top-right');
        m.on('load', () => !cancelled && setReady(true));
        m.on('error', () => {
          /* tile errors are non-fatal; markers still show */
        });
        map.current = m;
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    const safeMap = safeMarkers.current;
    const blockMap = blockMarkers.current;
    return () => {
      cancelled = true;
      markerMap.forEach((mk) => mk.remove());
      markerMap.clear();
      safeMap.forEach((mk) => mk.remove());
      safeMap.clear();
      blockMap.forEach((mk) => mk.remove());
      blockMap.clear();
      map.current?.remove();
      map.current = null;
    };
  }, [compact]);

  // Terrain and camera pitch follow the 2D/3D switch.
  // freezeElevation on every camera move: without it MapLibre (5.x) leaves the camera's ground height
  // frozen at whatever it was when the move began, which is 0 m before the terrain tiles arrive, so at
  // street zoom in the hills the camera ends up inside the mountain. With it, the height is recomputed
  // when the move ends and then follows the terrain tiles as they load.
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    m.setTerrain(is3d ? { source: 'dem', exaggeration: TERRAIN_EXAGGERATION } : null);
    m.easeTo({ pitch: is3d ? PITCH_3D : 0, bearing: is3d ? -15 : 0, duration: prefersReducedMotion() ? 0 : 900, freezeElevation: true });
  }, [is3d, ready]);

  // Dark mode on the base raster only (see applyBaseTheme).
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    applyBaseTheme(m, dark);
  }, [dark, ready]);

  // Sync village markers.
  useEffect(() => {
    const m = map.current;
    const ml = lib.current;
    if (!m || !ml || !ready) return;
    const next: Record<string, HTMLElement> = {};
    const seen = new Set<string>();
    for (const v of villages) {
      seen.add(v.id);
      let mk = markers.current.get(v.id);
      if (!mk) {
        const el = document.createElement('div');
        el.className = 'mk-host';
        mk = new ml.Marker({ element: el, anchor: 'center' }).setLngLat([v.lon, v.lat]).addTo(m);
        el.removeAttribute('aria-label');
        el.removeAttribute('role');
        el.removeAttribute('tabindex');
        markers.current.set(v.id, mk);
      } else mk.setLngLat([v.lon, v.lat]);
      next[v.id] = mk.getElement();
    }
    for (const [id, mk] of markers.current) {
      if (!seen.has(id)) {
        mk.remove();
        markers.current.delete(id);
      }
    }
    // Only set state when the set of marker elements really changed.
    setEls((prev) => {
      const a = Object.keys(prev);
      const same = a.length === Object.keys(next).length && a.every((k) => prev[k] === next[k]);
      return same ? prev : next;
    });

    const ids = focus?.length ? focus : villages.map((v) => v.id);
    const safePts = fitSafe ? viewPoints(safe) : [];
    const key = ids.join(',') + (safePts.length ? `|safe:${safePts.length}` : '');
    if (key && fitted.current !== key) {
      const pts = villages.filter((v) => ids.includes(v.id)).map((v) => [v.lon, v.lat] as [number, number]);
      for (const p of points) pts.push([p.lon, p.lat]);
      pts.push(...safePts);
      if (pts.length) {
        const b = new ml.LngLatBounds(pts[0], pts[0]);
        pts.forEach((p) => b.extend(p));
        const narrow = (box.current?.clientWidth ?? 800) < 600;
        const padding = narrow ? { top: 40, bottom: 80, left: 30, right: 70 } : compact ? { top: 50, bottom: 60, left: 40, right: 110 } : { top: 70, bottom: 90, left: 70, right: 150 };
        const tilt = is3dRef.current;
        // A village's own walking routes need street-level zoom; the overview stays at valley level.
        const maxZoom = safePts.length ? 15 : 11;
        m.fitBounds(b, { padding, maxZoom, pitch: tilt ? PITCH_3D : 0, bearing: tilt ? -15 : 0, duration: fitted.current && !prefersReducedMotion() ? 600 : 0, freezeElevation: true });
        fitted.current = key;
      }
    }
  }, [villages, ready, focus, points, compact, safe, fitSafe]);

  // Safe places: route lines on the canvas (they drape over the 3D terrain) and place markers as real buttons.
  useEffect(() => {
    const m = map.current;
    const ml = lib.current;
    if (!m || !ml || !ready) return;
    type RouteData = Parameters<import('maplibre-gl').GeoJSONSource['setData']>[0];
    const data = routeCollection(safe) as unknown as RouteData;
    const src = m.getSource(SAFE_SOURCE) as import('maplibre-gl').GeoJSONSource | undefined;
    routeVillage.current = new Map(safe.flatMap((v) => v.places.map((p) => [p.id, v.village_id] as [string, string])));
    if (src) src.setData(data);
    else if (safe.length) {
      m.addSource(SAFE_SOURCE, { type: 'geojson', data });
      addRouteLayers(m);
      m.on('click', 'safe-route-hit', (e) => {
        const pid = e.features?.[0]?.properties?.place_id;
        if (!routeSelect.current || typeof pid !== 'string') return;
        routeSelect.current({ placeId: pid, villageId: routeVillage.current.get(pid) ?? null, lon: e.lngLat.lng, lat: e.lngLat.lat });
      });
      m.on('mouseenter', 'safe-route-hit', () => {
        if (routeSelect.current) m.getCanvas().style.cursor = 'pointer';
      });
      m.on('mouseleave', 'safe-route-hit', () => {
        m.getCanvas().style.cursor = '';
      });
    }
    for (const id of SAFE_LAYERS) if (m.getLayer(id)) m.setLayoutProperty(id, 'visibility', safe.length ? 'visible' : 'none');

    // Road blocks: a crimson cross at each blocked point (decoration; the cards and list say it in words).
    const blockSeen = new Set<string>();
    for (const v of safe) {
      for (const b of v.roadblocks ?? []) {
        const key = `${v.village_id}:${b.id}`;
        blockSeen.add(key);
        let mk = blockMarkers.current.get(key);
        if (!mk) {
          const el = document.createElement('div');
          el.className = 'rb-host';
          el.setAttribute('aria-hidden', 'true');
          el.innerHTML = '<span class="rb-x"></span>';
          mk = new ml.Marker({ element: el, anchor: 'center' }).setLngLat([b.lon, b.lat]).addTo(m);
          el.removeAttribute('role');
          el.removeAttribute('tabindex');
          el.removeAttribute('aria-label');
          blockMarkers.current.set(key, mk);
        } else mk.setLngLat([b.lon, b.lat]);
        mk.getElement().title = b.label ? `${b.label}: ${b.note}` : b.note;
      }
    }
    for (const [key, mk] of blockMarkers.current) {
      if (!blockSeen.has(key)) {
        mk.remove();
        blockMarkers.current.delete(key);
      }
    }

    const next: Record<string, HTMLElement> = {};
    const seen = new Set<string>();
    for (const { key, place } of safePlaces) {
      seen.add(key);
      let mk = safeMarkers.current.get(key);
      if (!mk) {
        const el = document.createElement('div');
        el.className = 'sp-host';
        mk = new ml.Marker({ element: el, anchor: 'bottom', opacityWhenCovered: '0.6' }).setLngLat([place.lon, place.lat]).addTo(m);
        el.removeAttribute('aria-label');
        el.removeAttribute('role');
        el.removeAttribute('tabindex');
        safeMarkers.current.set(key, mk);
      } else mk.setLngLat([place.lon, place.lat]);
      next[key] = mk.getElement();
    }
    for (const [key, mk] of safeMarkers.current) {
      if (!seen.has(key)) {
        mk.remove();
        safeMarkers.current.delete(key);
      }
    }
    setSafeEls((prev) => {
      const a = Object.keys(prev);
      const same = a.length === Object.keys(next).length && a.every((k) => prev[k] === next[k]);
      return same ? prev : next;
    });
  }, [safe, safePlaces, ready]);

  // A safe-place pin that would sit on its village's marker at this zoom is spread on a small arc
  // above it, with a leader line to its true spot; zoom in and it returns to that spot.
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !safePlaces.length) return;
    const byVillage = new Map(villages.map((v) => [v.id, v]));
    let raf = 0;
    const layout = () => {
      raf = 0;
      const groups = new Map<string, { mk: Marker; p: [number, number] }[]>();
      for (const { key, place, villageId } of safePlaces) {
        const mk = safeMarkers.current.get(key);
        if (!mk) continue;
        const pt = m.project([place.lon, place.lat]);
        const list = groups.get(villageId) ?? [];
        list.push({ mk, p: [pt.x, pt.y] });
        groups.set(villageId, list);
      }
      const vpts = new Map(villages.map((v) => {
        const pt = m.project([v.lon, v.lat]);
        return [v.id, [pt.x, pt.y] as [number, number]];
      }));
      // Keep fanned pins below the safe-places legend that floats over the top of the map.
      const legend = box.current?.parentElement?.querySelector<HTMLElement>('.safe-legend');
      const topPx = legend ? legend.offsetTop + legend.offsetHeight : 0;
      for (const [vid, items] of groups) {
        const vp = byVillage.has(vid) ? vpts.get(vid) : undefined;
        const others = [...vpts].filter(([id]) => id !== vid).map(([, p]) => p);
        const offs = vp ? fanOffsets(vp, items.map((i) => i.p), others, topPx) : items.map((): [number, number] => [0, 0]);
        items.forEach(({ mk }, i) => {
          const [dx, dy] = offs[i];
          const prev = mk.getOffset();
          if (prev.x === dx && prev.y === dy) return;
          mk.setOffset([dx, dy]);
          const el = mk.getElement();
          el.classList.toggle('is-fanned', dx !== 0 || dy !== 0);
          el.style.setProperty('--leader-len', `${Math.hypot(dx, dy).toFixed(1)}px`);
          el.style.setProperty('--leader-angle', `${Math.atan2(-dy, -dx).toFixed(3)}rad`);
        });
      }
    };
    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(layout);
    };
    layout();
    m.on('move', schedule);
    return () => {
      m.off('move', schedule);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [ready, safePlaces, villages, safeEls]);

  // Road-block crosses only make sense where the routes are visible: hide them at valley zoom,
  // where one would sit on the village marker itself.
  useEffect(() => {
    const m = map.current;
    const el = box.current;
    if (!m || !el || !ready) return;
    const sync = () => el.classList.toggle('is-far', m.getZoom() < BLOCK_MIN_ZOOM);
    sync();
    m.on('zoomend', sync);
    return () => {
      m.off('zoomend', sync);
    };
  }, [ready]);

  // Extra labelled points (from the analyst agent).
  useEffect(() => {
    const m = map.current;
    const ml = lib.current;
    if (!m || !ml || !ready) return;
    pointMarkers.current.forEach((mk) => mk.remove());
    pointMarkers.current = points.map((p) => {
      const el = document.createElement('div');
      el.className = 'mk-point';
      el.textContent = p.label;
      return new ml.Marker({ element: el, anchor: 'bottom' }).setLngLat([p.lon, p.lat]).addTo(m);
    });
  }, [points, ready]);

  return (
    <>
    <div className={`map-wrap ${className}${narrow ? ' is-narrow' : ''}`}>
      <div ref={box} className="map" role="region" aria-label={caption ? `${t('map.label')} (${caption})` : t('map.label')} />
      {caption && <p className="map-caption">{caption}</p>}
      {ready && (
        <button
          type="button"
          className="map-3d"
          aria-pressed={is3d}
          onClick={() => setIs3d((v) => !v)}
          title={t(is3d ? 'map.view2d' : 'map.view3d')}
        >
          {is3d ? '2D' : '3D'}
          <span className="sr-only"> {t(is3d ? 'map.view2d' : 'map.view3d')}</span>
        </button>
      )}
      {ready && safeToggle && (
        <button
          type="button"
          className="map-safe"
          aria-pressed={safeToggle.on}
          onClick={() => safeToggle.onChange(!safeToggle.on)}
          title={t('map.safe.show')}
        >
          <Tent aria-hidden="true" />
          <span className="map-safe-word">{t('map.safe.toggle')}</span>
          <span className="sr-only"> {t('map.safe.show')}</span>
        </button>
      )}
      {ready && safe.length > 0 && (
        <div className="safe-legend" role="group" aria-label={t('map.safe.legend.label')}>
          <span className="sl-item">
            <span className="sl-pin" aria-hidden="true">
              <Tent />
            </span>
            {t('map.safe.legend.place')}
          </span>
          <span className="sl-item">
            <span className="sl-line" aria-hidden="true" />
            {t('map.safe.legend.route')}
          </span>
          <span className="sl-item">
            <span className="sl-line is-steep" aria-hidden="true" />
            {t('map.safe.legend.steep')}
          </span>
          {safe.some((v) => (v.roadblocks ?? []).length > 0) && (
            <span className="sl-item">
              <span className="sl-line is-blocked" aria-hidden="true" />
              {t('map.safe.legend.blocked')}
            </span>
          )}
          <span className="sl-attrib">© OpenStreetMap contributors (ODbL)</span>
        </div>
      )}
      {safePlaces.map(({ key, place, villageId }) => {
        const el = safeEls[key];
        if (!el) return null;
        return createPortal(<SafeMarker place={place} villageId={villageId} onSelect={onSafeSelect} />, el, key);
      })}
      {!ready && !failed && <div className="map-skel skel" aria-hidden="true" />}
      {failed && (
        <div className="map-fail" role="status">
          {t('map.unavailable')}
        </div>
      )}
      {villages.map((v) => {
        const el = els[v.id];
        if (!el) return null;
        const Icon = LEVEL_ICON[v.level];
        const lvWord = `${dict[`level.${v.level}`].hi} / ${dict[`level.${v.level}`].en}`;
        const name = lang === 'hi' ? v.name_hi : v.name;
        const hl = highlight.includes(v.id);
        return createPortal(
          <button
            type="button"
            className={`mk lv-${v.level}${hl ? ' is-hl' : ''}${v.coords_verified ? '' : ' is-approx'}`}
            aria-label={`${t('map.marker', { name, level: lvWord })}${v.coords_verified ? '' : ` (${t('common.approx')})`}`}
            onClick={() => onSelect?.(v.id)}
          >
            {(v.level === 'critical' || v.level === 'warning') && <span className="mk-pulse" aria-hidden="true" />}
            <span className="mk-dot" aria-hidden="true">
              <Icon />
            </span>
            {narrow && (
              <span className="mk-num" aria-hidden="true">
                {numOf.get(v.id)}
              </span>
            )}
            <span className="mk-label" aria-hidden="true" lang={lang}>
              {name}
              {!v.coords_verified && <span className="mk-approx">≈</span>}
            </span>
          </button>,
          el,
          v.id,
        );
      })}
    </div>
    {narrow && numbered.length > 0 && (
      <ol className="map-key" aria-label={t('map.key')}>
        {numbered.map((v) => {
          const Icon = LEVEL_ICON[v.level];
          const name = lang === 'hi' ? v.name_hi : v.name;
          const inner = (
            <>
              <span className={`mk-num lv-${v.level}`} aria-hidden="true">
                {numOf.get(v.id)}
              </span>
              <span lang={lang}>{name}</span>
              <span className={`mk-key-lv lv-${v.level}`} title={t(`level.${v.level}`)}>
                <Icon aria-hidden="true" />
                <span className="sr-only">{t(`level.${v.level}`)}</span>
              </span>
            </>
          );
          return (
            <li key={v.id}>
              {onSelect ? (
                <button type="button" className="map-key-item" onClick={() => onSelect(v.id)}>
                  {inner}
                </button>
              ) : (
                <span className="map-key-item">{inner}</span>
              )}
            </li>
          );
        })}
      </ol>
    )}
    </>
  );
}
