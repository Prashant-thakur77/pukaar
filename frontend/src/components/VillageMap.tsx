import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Map as MlMap, Marker } from 'maplibre-gl';
import { dict, useT } from '../i18n';
import { LEVEL_ICON, levelRank } from '../lib/levels';
import { prefersReducedMotion } from '../hooks/useMotion';
import type { Level } from '../types';

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
}

// Stable defaults: a fresh `[]` on every render would retrigger the marker
// effect (which sets state) and loop forever.
const NO_IDS: string[] = [];
const NO_POINTS: { lat: number; lon: number; label: string }[] = [];
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

/** 3D by default on wide screens only; phones and compact maps start flat. */
function default3d(compact?: boolean): boolean {
  return !compact && typeof window !== 'undefined' && window.innerWidth >= 768;
}

/** MapLibre + OSM raster. Markers are real buttons rendered through portals. */
export function VillageMap({ villages, highlight = NO_IDS, points = NO_POINTS, onSelect, className = '', focus, compact, caption }: Props) {
  const { t, lang } = useT();
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<MlMap | null>(null);
  const markers = useRef<Map<string, Marker>>(new Map());
  const pointMarkers = useRef<Marker[]>([]);
  const lib = useRef<typeof import('maplibre-gl') | null>(null);
  const [els, setEls] = useState<Record<string, HTMLElement>>({});
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
    return () => {
      cancelled = true;
      markerMap.forEach((mk) => mk.remove());
      markerMap.clear();
      map.current?.remove();
      map.current = null;
    };
  }, [compact]);

  // Terrain and camera pitch follow the 2D/3D switch.
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    m.setTerrain(is3d ? { source: 'dem', exaggeration: TERRAIN_EXAGGERATION } : null);
    m.easeTo({ pitch: is3d ? PITCH_3D : 0, bearing: is3d ? -15 : 0, duration: prefersReducedMotion() ? 0 : 900 });
  }, [is3d, ready]);

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
    const key = ids.join(',');
    if (key && fitted.current !== key) {
      const pts = villages.filter((v) => ids.includes(v.id)).map((v) => [v.lon, v.lat] as [number, number]);
      for (const p of points) pts.push([p.lon, p.lat]);
      if (pts.length) {
        const b = new ml.LngLatBounds(pts[0], pts[0]);
        pts.forEach((p) => b.extend(p));
        const narrow = (box.current?.clientWidth ?? 800) < 600;
        const padding = narrow ? { top: 40, bottom: 80, left: 30, right: 70 } : compact ? { top: 50, bottom: 60, left: 40, right: 110 } : { top: 70, bottom: 90, left: 70, right: 150 };
        const tilt = is3dRef.current;
        m.fitBounds(b, { padding, maxZoom: 11, pitch: tilt ? PITCH_3D : 0, bearing: tilt ? -15 : 0, duration: fitted.current && !prefersReducedMotion() ? 600 : 0 });
        fitted.current = key;
      }
    }
  }, [villages, ready, focus, points, compact]);

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
