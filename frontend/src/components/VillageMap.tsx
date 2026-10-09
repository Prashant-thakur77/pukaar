import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Map as MlMap, Marker } from 'maplibre-gl';
import { dict, useT } from '../i18n';
import { LEVEL_ICON } from '../lib/levels';
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
}

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
  },
  layers: [{ id: 'osm', type: 'raster' as const, source: 'osm' }],
};

/** MapLibre + OSM raster. Markers are real buttons rendered through portals. */
export function VillageMap({ villages, highlight = [], points = [], onSelect, className = '', focus, compact }: Props) {
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
          dragRotate: false,
          pitchWithRotate: false,
        });
        m.addControl(new ml.NavigationControl({ showCompass: false }), 'top-right');
        m.touchZoomRotate.disableRotation();
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
    setEls(next);

    const ids = focus?.length ? focus : villages.map((v) => v.id);
    const key = ids.join(',');
    if (key && fitted.current !== key) {
      const pts = villages.filter((v) => ids.includes(v.id)).map((v) => [v.lon, v.lat] as [number, number]);
      for (const p of points) pts.push([p.lon, p.lat]);
      if (pts.length) {
        const b = new ml.LngLatBounds(pts[0], pts[0]);
        pts.forEach((p) => b.extend(p));
        const narrow = (box.current?.clientWidth ?? 800) < 600;
        const padding = narrow ? { top: 40, bottom: 80, left: 30, right: 70 } : compact ? { top: 40, bottom: 40, left: 40, right: 110 } : { top: 70, bottom: 90, left: 70, right: 150 };
        m.fitBounds(b, { padding, maxZoom: 11, duration: fitted.current ? 600 : 0 });
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
    <div className={`map-wrap ${className}`}>
      <div ref={box} className="map" role="region" aria-label={t('map.label')} />
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
  );
}
