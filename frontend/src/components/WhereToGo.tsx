import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUpRight, Ban, Footprints, Mountain, Route, Signpost, Tent, TrendingUp } from 'lucide-react';
import { api, ApiError } from '../api';
import { usePoll } from '../hooks/usePoll';
import { useT } from '../i18n';
import { fmtAgo, fmtDate, fmtNumber } from '../lib/format';
import { canEditShelters, fmtDistance, fmtGrade, namedInAlerts, routeMidpoint, SHELTER_STATES, snapToRoute } from '../lib/safePlaces';
import { useAuth } from '../store';
import type { MapVillage } from './VillageMap';
import { VillageMap } from './VillageMap';
import { ErrorState, Skeleton } from './States';
import type { RoadBlock, SafePlace, SafePlacesView, ShelterState } from '../types';

/** A tap on a route this far (or further) from every baked route is not taken as a block point. */
const SNAP_MAX_M = 60;

function StatusPill({ status }: { status: SafePlace['ledger']['status'] }) {
  const { t } = useT();
  return <span className={`sp-pill st-${status.toLowerCase()}`}>{t(`safe.status.${status}`)}</span>;
}

function errText(e: unknown, lang: 'hi' | 'en'): string {
  const ae = e instanceof ApiError ? e : new ApiError(0, null);
  return lang === 'hi' && ae.messageHi ? ae.messageHi : ae.messageEn;
}

function placeName(p: SafePlace, lang: 'hi' | 'en'): string {
  return lang === 'hi' ? p.name_hi || p.name : p.name || p.name_hi;
}

function PlaceCard({ place, villageId, editable, named, onSaved, onMarkBlocked }: {
  place: SafePlace;
  villageId: string;
  editable: boolean;
  named: boolean;
  onSaved: (v: SafePlacesView) => void;
  onMarkBlocked: (placeId: string) => void;
}) {
  const { t, lang } = useT();
  const [busy, setBusy] = useState<ShelterState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const name = placeName(place, lang);
  const other = lang === 'hi' ? place.name : place.name_hi;
  const l = place.ledger;
  const blocks = place.route_blocks ?? [];

  async function set(status: ShelterState) {
    setBusy(status);
    setErr(null);
    try {
      onSaved(await api.setShelter(villageId, place.id, { status }));
    } catch (e) {
      setErr(errText(e, lang));
    } finally {
      setBusy(null);
    }
  }

  return (
    <li
      id={`place-${place.id}`}
      className={`wtg-card st-${l.status.toLowerCase()}${named ? ' is-named' : ''}${place.route_blocked ? ' is-blocked' : ''}`}
    >
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
      {place.best_open_route && (
        <p className="wtg-best small">
          <Route aria-hidden="true" /> {t('safe.best')}
        </p>
      )}
      {place.route_blocked && (
        <div className="wtg-blocked small" role="note">
          {blocks.map((b) => (
            <p key={b.id}>
              <Ban aria-hidden="true" /> {t('safe.blocked.route', { note: b.label ? `${b.label}: ${b.note}` : b.note })}
            </p>
          ))}
          <p className="wtg-blocked-none">{t('safe.blocked.none')}</p>
        </div>
      )}
      <ul className={`wtg-facts${place.route_blocked ? ' is-struck' : ''}`}>
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
      {editable && !place.route_blocked && (
        <button type="button" className="btn btn-sm btn-ghost wtg-mark" onClick={() => onMarkBlocked(place.id)}>
          <Ban aria-hidden="true" /> {t('safe.block.mark')}
        </button>
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

type Pending = { placeId: string; lon: number; lat: number; how: 'tap' | 'mid' };

/** The "Mark blocked" form: a point on a baked route (tapped, or halfway along), a road name and a note. */
function BlockForm({ pending, view, villageId, onSaved, onCancel }: {
  pending: Pending;
  view: SafePlacesView;
  villageId: string;
  onSaved: (v: SafePlacesView) => void;
  onCancel: () => void;
}) {
  const { t, lang } = useT();
  const [label, setLabel] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const place = view.places.find((p) => p.id === pending.placeId);
  const name = place ? placeName(place, lang) : '';

  useEffect(() => {
    heading.current?.focus();
  }, [pending]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!note.trim()) {
      setErr(t('safe.block.note'));
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      onSaved(await api.addRoadblock(villageId, { lat: pending.lat, lon: pending.lon, note: note.trim(), label: label.trim() }));
    } catch (e2) {
      setErr(errText(e2, lang));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="wtg-block-form card" onSubmit={(e) => void submit(e)} aria-labelledby="wtg-block-title">
      <h3 id="wtg-block-title" ref={heading} tabIndex={-1}>
        <Ban aria-hidden="true" /> {t('safe.block.title')}
      </h3>
      <p className="small muted">{t(pending.how === 'tap' ? 'safe.block.at.tap' : 'safe.block.at.mid', { name })}</p>
      <label className="field">
        <span className="field-label">{t('safe.block.label')}</span>
        <input type="text" value={label} maxLength={80} onChange={(e) => setLabel(e.target.value)} autoComplete="off" />
      </label>
      <label className="field">
        <span className="field-label">{t('safe.block.note')}</span>
        <input
          type="text"
          value={note}
          maxLength={200}
          required
          placeholder={t('safe.block.note.ph')}
          onChange={(e) => setNote(e.target.value)}
          autoComplete="off"
        />
      </label>
      <p className="small muted">{t('safe.block.limit')}</p>
      {err && (
        <p className="small bad-text" role="alert">
          {err}
        </p>
      )}
      <div className="wtg-block-actions">
        <button type="submit" className="btn btn-danger" disabled={busy}>
          {busy ? '…' : t('safe.block.save')}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
          {t('safe.block.cancel')}
        </button>
      </div>
    </form>
  );
}

function BlockRow({ block, view, villageId, editable, onSaved }: {
  block: RoadBlock;
  view: SafePlacesView;
  villageId: string;
  editable: boolean;
  onSaved: (v: SafePlacesView) => void;
}) {
  const { t, lang } = useT();
  const [busy, setBusy] = useState<'renew' | 'clear' | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const names = block.place_ids
    .map((id) => view.places.find((p) => p.id === id))
    .filter((p): p is SafePlace => Boolean(p))
    .map((p) => placeName(p, lang));

  async function act(kind: 'renew' | 'clear') {
    setBusy(kind);
    setErr(null);
    try {
      onSaved(kind === 'renew' ? await api.renewRoadblock(villageId, block.id) : await api.clearRoadblock(villageId, block.id));
    } catch (e) {
      setErr(errText(e, lang));
    } finally {
      setBusy(null);
    }
  }

  return (
    <li className="wtg-rb">
      <p className="wtg-rb-what">
        <Ban aria-hidden="true" /> {block.label ? <strong>{block.label}: </strong> : null}
        {block.note}
      </p>
      <p className="small muted">
        {names.length ? t('safe.block.crosses', { names: names.join(', ') }) : t('safe.block.crosses.none')}
      </p>
      <p className="small muted">
        {t('safe.block.by', { who: block.created_by, t: fmtAgo(block.created_at, lang) })}
        {block.renewed_by && <> · {t('safe.block.renewed', { who: block.renewed_by, t: fmtAgo(block.renewed_at, lang) })}</>}
        {' · '}
        {t('safe.block.expires', { t: fmtDate(block.expires_at, lang) })}
      </p>
      {editable && (
        <div className="wtg-block-actions">
          <button type="button" className="btn btn-sm" disabled={busy !== null} onClick={() => void act('renew')}>
            {busy === 'renew' ? '…' : t('safe.block.renew')}
          </button>
          <button type="button" className="btn btn-sm btn-ghost" disabled={busy !== null} onClick={() => void act('clear')}>
            {busy === 'clear' ? '…' : t('safe.block.clear')}
          </button>
        </div>
      )}
      {err && (
        <p className="small bad-text" role="alert">
          {err}
        </p>
      )}
    </li>
  );
}

/** "Where to go": the map with the walking routes, and one card per safe place. */
export function WhereToGo({ village }: { village: MapVillage }) {
  const { t, lang } = useT();
  const user = useAuth((s) => s.user);
  const { data, error, loading, refresh } = usePoll(() => api.safePlaces(village.id), [village.id], 60000);
  const [saved, setSaved] = useState<SafePlacesView | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
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
  const blocks = view.roadblocks ?? [];
  const allBlocked = view.places.length > 0 && view.places.every((p) => p.route_blocked);
  const scrollTo = (pid: string) => document.getElementById(`place-${pid}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  const onSaved = (v: SafePlacesView) => {
    setSaved(v);
    void refresh().then(() => setSaved(null));
  };

  return (
    <div className="wtg">
      {view.places.length > 0 && (
        <div className="wtg-map card card-flush">
          <VillageMap
            villages={mapVillages}
            focus={mapFocus}
            safe={mapSafe}
            fitSafe
            onSafeSelect={(pid) => scrollTo(pid)}
            onRouteSelect={({ placeId, lon: tlon, lat: tlat }) => {
              if (!editable) {
                scrollTo(placeId);
                return;
              }
              const snap = snapToRoute(view, tlon, tlat);
              if (!snap || snap.distance_m > SNAP_MAX_M) return;
              setPending({ placeId, lon: snap.lon, lat: snap.lat, how: 'tap' });
            }}
          />
        </div>
      )}
      {editable && view.places.length > 0 && !pending && <p className="small muted wtg-tap-hint">{t('safe.block.tap')}</p>}
      {pending && (
        <BlockForm
          pending={pending}
          view={view}
          villageId={village.id}
          onCancel={() => setPending(null)}
          onSaved={(v) => {
            setPending(null);
            onSaved(v);
          }}
        />
      )}
      {view.places.length === 0 ? (
        <p className="wtg-empty card">{t('safe.none')}</p>
      ) : (
        <>
          {allBlocked && (
            <p className="wtg-all-blocked card small" role="note">
              <Ban aria-hidden="true" /> {t('safe.blocked.all')}
            </p>
          )}
          {!named && !allBlocked && <p className="small muted wtg-none-named">{t('safe.named.none')}</p>}
          <ol className="wtg-list">
            {view.places.map((p) => (
              <PlaceCard
                key={p.id}
                place={p}
                villageId={village.id}
                editable={editable}
                named={named?.id === p.id}
                onSaved={onSaved}
                onMarkBlocked={(pid) => {
                  const mid = routeMidpoint(view, pid);
                  if (mid) setPending({ placeId: pid, lon: mid.lon, lat: mid.lat, how: 'mid' });
                }}
              />
            ))}
          </ol>
          {view.places.length < 2 && <p className="small muted">{t('safe.thin')}</p>}
        </>
      )}
      {blocks.length > 0 && (
        <section className="wtg-rbs" aria-labelledby="wtg-rbs-title">
          <h3 id="wtg-rbs-title">{t('safe.block.list')}</h3>
          <ul>
            {blocks.map((b) => (
              <BlockRow key={b.id} block={b} view={view} villageId={village.id} editable={editable} onSaved={onSaved} />
            ))}
          </ul>
        </section>
      )}
      <div className="wtg-foot small muted">
        <p lang={lang}>{lang === 'hi' ? view.limits_hi : view.limits_en}</p>
        <p lang={lang}>{(lang === 'hi' ? view.route_limit_hi : view.route_limit_en) || t('safe.block.limit')}</p>
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
