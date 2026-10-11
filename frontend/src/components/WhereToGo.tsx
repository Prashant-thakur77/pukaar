import { useMemo, useState } from 'react';
import { ArrowUpRight, Footprints, Mountain, Signpost, Tent, TrendingUp } from 'lucide-react';
import { api, ApiError } from '../api';
import { usePoll } from '../hooks/usePoll';
import { useT } from '../i18n';
import { fmtAgo, fmtNumber } from '../lib/format';
import { canEditShelters, fmtDistance, fmtGrade, namedInAlerts, SHELTER_STATES } from '../lib/safePlaces';
import { useAuth } from '../store';
import type { MapVillage } from './VillageMap';
import { VillageMap } from './VillageMap';
import { ErrorState, Skeleton } from './States';
import type { SafePlace, SafePlacesView, ShelterState } from '../types';

function StatusPill({ status }: { status: SafePlace['ledger']['status'] }) {
  const { t } = useT();
  return <span className={`sp-pill st-${status.toLowerCase()}`}>{t(`safe.status.${status}`)}</span>;
}

function PlaceCard({ place, villageId, editable, named, onSaved }: {
  place: SafePlace;
  villageId: string;
  editable: boolean;
  named: boolean;
  onSaved: (v: SafePlacesView) => void;
}) {
  const { t, lang } = useT();
  const [busy, setBusy] = useState<ShelterState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const name = lang === 'hi' ? place.name_hi || place.name : place.name || place.name_hi;
  const other = lang === 'hi' ? place.name : place.name_hi;
  const l = place.ledger;

  async function set(status: ShelterState) {
    setBusy(status);
    setErr(null);
    try {
      onSaved(await api.setShelter(villageId, place.id, { status }));
    } catch (e) {
      const ae = e instanceof ApiError ? e : new ApiError(0, null);
      setErr(lang === 'hi' && ae.messageHi ? ae.messageHi : ae.messageEn);
    } finally {
      setBusy(null);
    }
  }

  return (
    <li id={`place-${place.id}`} className={`wtg-card st-${l.status.toLowerCase()}${named ? ' is-named' : ''}`}>
      <div className="wtg-top">
        <span className="wtg-rank" aria-hidden="true">
          {place.rank}
        </span>
        <div className="wtg-names">
          <h3 lang={lang}>{name}</h3>
          {other && other !== name && <p className="small muted">{other}</p>}
          <p className="wtg-kind small">
            <Tent aria-hidden="true" /> {lang === 'hi' ? place.kind_hi : place.kind_en}
          </p>
        </div>
        <StatusPill status={l.status} />
      </div>
      <ul className="wtg-facts">
        <li>
          <Mountain aria-hidden="true" /> {t('safe.headroom', { m: fmtNumber(place.headroom_m, lang) })}
        </li>
        <li>
          <Footprints aria-hidden="true" /> {t('safe.walk', { d: fmtDistance(place.route_length_m, lang), min: fmtNumber(place.walk_min, lang) })}
        </li>
        <li>
          <TrendingUp aria-hidden="true" /> {t('safe.climb', { m: fmtNumber(place.climb_m, lang) })} · {t('safe.grade', { g: fmtGrade(place.max_grade, lang) })}
          {place.steep_m > 0 && <> · {t('safe.steep', { d: fmtDistance(place.steep_m, lang) })}</>}
        </li>
        {place.off_network_m >= 100 && (
          <li>
            <Signpost aria-hidden="true" /> {t('safe.offnet', { d: fmtDistance(place.off_network_m, lang) })}
          </li>
        )}
      </ul>
      {named && <p className="wtg-named small">{t('safe.named')}</p>}
      {(l.capacity != null || l.updated_by) && (
        <p className="small muted">
          {l.capacity != null && <>{t('safe.capacity', { n: fmtNumber(l.capacity, lang) })} · </>}
          {l.updated_by && t('safe.updated', { who: l.updated_by, t: fmtAgo(l.updated_at, lang) })}
          {l.note && <> · {l.note}</>}
        </p>
      )}
      {editable && (
        <div className="wtg-set" role="group" aria-label={t('safe.set.label', { name })}>
          {SHELTER_STATES.map((s) => (
            <button
              key={s}
              type="button"
              className={`btn btn-sm wtg-st st-${s.toLowerCase()}`}
              aria-pressed={l.status === s}
              disabled={busy !== null}
              onClick={() => void set(s)}
            >
              {busy === s ? '…' : t(`safe.status.${s}`)}
            </button>
          ))}
        </div>
      )}
      {err && (
        <p className="small bad-text" role="alert">
          {err}
        </p>
      )}
      <a className="small link" href={place.osm_url} target="_blank" rel="noreferrer">
        {t('safe.osm')} <ArrowUpRight aria-hidden="true" />
      </a>
    </li>
  );
}

/** "Where to go": the map with the walking routes, and one card per safe place. */
export function WhereToGo({ village }: { village: MapVillage }) {
  const { t, lang } = useT();
  const user = useAuth((s) => s.user);
  const { data, error, loading, refresh } = usePoll(() => api.safePlaces(village.id), [village.id], 60000);
  const [saved, setSaved] = useState<SafePlacesView | null>(null);
  // The POST answers with the whole view; show it at once, then let polling take over again.
  const view = saved ?? data;
  const editable = canEditShelters(user, village.id);
  const { id, name, name_hi, lat, lon, level, coords_verified } = village;
  // Stable props for the map, so a poll that changes nothing does not redraw the routes.
  const mapVillages = useMemo(() => [{ id, name, name_hi, lat, lon, level, coords_verified }], [id, name, name_hi, lat, lon, level, coords_verified]);
  const mapFocus = useMemo(() => [id], [id]);
  const mapSafe = useMemo(() => (view ? [view] : []), [view]);

  if (loading && !view) return <Skeleton lines={4} />;
  if (error && !view) return <ErrorState error={error} onRetry={refresh} compact />;
  if (!view) return null;
  const named = namedInAlerts(view.places);

  return (
    <div className="wtg">
      {view.places.length > 0 && (
        <div className="wtg-map card card-flush">
          <VillageMap
            villages={mapVillages}
            focus={mapFocus}
            safe={mapSafe}
            fitSafe
            onSafeSelect={(pid) => document.getElementById(`place-${pid}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
          />
        </div>
      )}
      {view.places.length === 0 ? (
        <p className="wtg-empty card">{t('safe.none')}</p>
      ) : (
        <>
          {!named && <p className="small muted wtg-none-named">{t('safe.named.none')}</p>}
          <ol className="wtg-list">
            {view.places.map((p) => (
              <PlaceCard
                key={p.id}
                place={p}
                villageId={village.id}
                editable={editable}
                named={named?.id === p.id}
                onSaved={(v) => {
                  setSaved(v);
                  void refresh().then(() => setSaved(null));
                }}
              />
            ))}
          </ol>
          {view.places.length < 2 && <p className="small muted">{t('safe.thin')}</p>}
        </>
      )}
      <div className="wtg-foot small muted">
        <p lang={lang}>{lang === 'hi' ? view.limits_hi : view.limits_en}</p>
        <p>{t('safe.method')}</p>
        <p>
          <a className="link" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
            {t('safe.attrib')}
          </a>
        </p>
      </div>
    </div>
  );
}
