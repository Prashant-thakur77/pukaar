import { lazy, Suspense, useEffect, useRef, useState, type ComponentProps } from 'react';
import { Map as MapIcon } from 'lucide-react';
import { useT } from '../i18n';
import type { VillageMap as VillageMapComponent } from './VillageMap';

/** The map chunk failed to load (offline, or a stale build): say so in place of the map. */
function MapUnavailable() {
  const { t } = useT();
  return (
    <div className="map-wrap map-gate">
      <p className="map-gate-note small muted">{t('map.gate.failed')}</p>
    </div>
  );
}

const VillageMap = lazy(() =>
  import('./VillageMap').then(
    (m) => ({ default: m.VillageMap }),
    () => ({ default: MapUnavailable as typeof VillageMapComponent }),
  ),
);

type Props = ComponentProps<typeof VillageMapComponent> & {
  /** Load at once instead of waiting for the map to scroll into view. */
  eager?: boolean;
};

/**
 * The map (MapLibre, its tiles and the terrain) costs a phone on 2G several hundred kB, so it loads only
 * when its box scrolls into view or the reader taps "Show map". Everything the map shows is also in the
 * text around it (levels, safe places, routes), so nothing is lost while it waits.
 */
export function LazyVillageMap({ eager = false, ...props }: Props) {
  const { t } = useT();
  const [on, setOn] = useState(eager);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = box.current;
    if (on || !el || typeof IntersectionObserver === 'undefined') return;
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setOn(true), { threshold: 0.2 });
    io.observe(el);
    return () => io.disconnect();
  }, [on]);

  const skeleton = (
    <div className="map-wrap">
      <div className="map-skel skel" aria-hidden="true" />
    </div>
  );
  if (on)
    return (
      <Suspense fallback={skeleton}>
        <VillageMap {...props} />
      </Suspense>
    );
  return (
    <div ref={box} className="map-wrap map-gate">
      <div className="map-gate-body">
        <MapIcon aria-hidden="true" />
        <p className="map-gate-note small">{t('map.gate.note')}</p>
        <button type="button" className="btn btn-ghost" onClick={() => setOn(true)}>
          {t('map.gate.show')}
        </button>
      </div>
    </div>
  );
}
