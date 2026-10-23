import { useEffect, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { List, Map as MapIcon } from 'lucide-react';
import { api } from '../api';
import { AckFunnel } from '../components/AckFunnel';
import { Freshness, VillageRows, type RowVillage } from '../components/Answer';
import { AlertStatusChip, DeliveryChips, ReplayChip } from '../components/Chips';
import { LevelBadge, LevelLegend } from '../components/Level';
import { LazyVillageMap } from '../components/LazyVillageMap';
import { LivePill } from '../components/LivePill';
import { EmptyState, ErrorState } from '../components/States';
import { useMedia } from '../hooks/useMedia';
import { usePoll } from '../hooks/usePoll';
import { useT } from '../i18n';
import { levelIsKnown } from '../lib/dataStatus';
import { fmtAgo, fmtNumber } from '../lib/format';
import { levelRank } from '../lib/levels';
import { PUBLIC_CHANNELS } from '../lib/live';
import type { SafePlacesView, Village } from '../types';
import '../styles/Live.css';

/*
 * /live (spec 4.6): the same five villages as home, as a list first, with the map on demand. A phone gets a
 * list/map switch (the list by default; MapLibre loads only when the map is asked for). A desk gets the list on the
 * left and the map on the right, loaded when the browser is idle on a good connection; hovering a row lights its
 * marker. Then the latest alerts and how many phones said "मिल गया".
 */

const RAIN_WATCH_MM = 64.5; // IMD "heavy rain", services/risk_rules.py RAIN_BANDS

/** "नदी: सतर्क रेखा का 47% · बारिश 0.4/64.5 मिमी", from the latest stored reading. Nothing estimated. */
function headroom(v: Village | undefined, lang: 'hi' | 'en'): ReactNode {
  const r = v?.latest_reading;
  if (!r) return null;
  const hi = lang === 'hi';
  const q = r.discharge_peak ?? r.discharge;
  const w = v?.thresholds?.watch;
  const parts: string[] = [];
  if (q != null && w) parts.push(hi ? `नदी: सतर्क रेखा का ${fmtNumber((q / w) * 100, lang)}%` : `River: ${fmtNumber((q / w) * 100, lang)}% of the Watch line`);
  if (r.rain_24h_mm != null) parts.push(hi ? `बारिश ${fmtNumber(r.rain_24h_mm, lang, 1)}/${fmtNumber(RAIN_WATCH_MM, lang, 1)} मिमी` : `rain ${fmtNumber(r.rain_24h_mm, lang, 1)}/${RAIN_WATCH_MM} mm`);
  return parts.join(' · ') || null;
}

/** The "safe places" map layer: fetched for every village the first time it is switched on. */
function useSafeLayer(ids: string[]) {
  const [on, setOn] = useState(false);
  const [views, setViews] = useState<SafePlacesView[]>([]);
  const key = ids.join(',');
  useEffect(() => {
    if (!on || !key) return;
    let alive = true;
    Promise.allSettled(key.split(',').map((id) => api.safePlaces(id))).then((rs) => {
      if (alive) setViews(rs.flatMap((r) => (r.status === 'fulfilled' ? [r.value] : [])));
    });
    return () => {
      alive = false;
    };
  }, [on, key]);
  return { on, setOn, views: on ? views : NO_VIEWS };
}
const NO_VIEWS: SafePlacesView[] = [];

/** On a desk with a good connection, the map loads by itself once the browser is idle. */
function useIdleMap(wide: boolean): boolean {
  const [idle, setIdle] = useState(false);
  useEffect(() => {
    if (!wide) return;
    const conn = (navigator as Navigator & { connection?: { effectiveType?: string; saveData?: boolean } }).connection;
    if (conn?.saveData || /(^|-)2g|3g/.test(conn?.effectiveType ?? '')) return;
    const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number; cancelIdleCallback?: (id: number) => void };
    if (w.requestIdleCallback) {
      const id = w.requestIdleCallback(() => setIdle(true), { timeout: 4000 });
      return () => w.cancelIdleCallback?.(id);
    }
    const t = window.setTimeout(() => setIdle(true), 1500);
    return () => clearTimeout(t);
  }, [wide]);
  return idle;
}

export default function Live() {
  const { t, lang } = useT();
  const hi = lang === 'hi';
  const nav = useNavigate();
  // Live push refetches on any level, alert, count or roll-call change; polling every 15 s is the fallback.
  const { data, error, refresh, live } = usePoll(() => api.overview(), [], 15000, { live: PUBLIC_CHANNELS });
  const detail = usePoll(() => api.villages(), [], 60000);
  const wide = useMedia('(min-width: 1024px)');
  const idle = useIdleMap(wide);
  const [view, setView] = useState<'list' | 'map'>('list');
  const [hot, setHot] = useState<string | null>(null);
  const safeLayer = useSafeLayer(data ? data.villages.map((v) => v.id) : []);

  const villages = data ? [...data.villages].sort((a, b) => levelRank(b.level) - levelRank(a.level) || a.name.localeCompare(b.name)) : [];
  const rows: RowVillage[] = villages.map((v) => ({ id: v.id, name: v.name, name_hi: v.name_hi, level: v.level, unknown: !levelIsKnown(v) }));
  const byId = new Map((detail.data ?? []).map((v) => [v.id, v]));
  // Every row keeps its second line's room from the start, so nothing jumps when the readings arrive.
  const sub = Object.fromEntries(villages.map((v) => [v.id, headroom(byId.get(v.id), lang) ?? '\u00a0']));
  const raised = villages.filter((v) => levelIsKnown(v) && v.level !== 'normal');
  const unknown = villages.filter((v) => !levelIsKnown(v));
  const checkedAt = villages.reduce<string | null>((m, v) => (v.data_ok_at && (!m || v.data_ok_at > m) ? v.data_ok_at : m), null);
  const c = data?.counters;
  const n = villages.length;
  const [asked, setAsked] = useState(false);
  const showMap = wide || view === 'map';
  const mapNow = (wide && (idle || asked)) || view === 'map';

  return (
    <div className="lv2">
      <header className="wrap lv2-head">
        <p className="home-region">{hi ? 'हिमाचल · मंडी और हमीरपुर' : 'Himachal · Mandi and Hamirpur'}</p>
        <h1 className="lv2-h1">
          {!data
            ? t('live.title')
            : raised.length
              ? hi
                ? `${fmtNumber(raised.length, lang)} गाँव सामान्य से ऊपर`
                : `${raised.length} ${raised.length === 1 ? 'village is' : 'villages are'} above Normal`
              : unknown.length
                ? hi
                  ? `${fmtNumber(unknown.length, lang)} गाँव का डेटा नहीं मिल रहा`
                  : `No data for ${unknown.length} ${unknown.length === 1 ? 'village' : 'villages'}`
                : hi
                  ? `आज सब ${fmtNumber(n, lang)} गाँव सामान्य हैं।`
                  : `All ${n} villages are at Normal.`}
        </h1>
        <div className="lv2-meta">
          <Freshness at={checkedAt} next />
          <LivePill live={live} />
        </div>
        {!c && <p className="lv2-sum" aria-hidden="true">{'\u00a0'}</p>}
        {c && (
          <p className="lv2-sum">
            {hi
              ? `${fmtNumber(c.villages_watched, lang)} गाँवों पर नज़र · ${c.alerts_sent ? `${fmtNumber(c.alerts_sent, lang)} असली चेतावनी भेजी गई` : 'अब तक कोई असली बाढ़ चेतावनी नहीं भेजी गई'}${c.drills_delivered ? ` (${fmtNumber(c.drills_delivered, lang)} अभ्यास)` : ''}`
              : `Watching ${c.villages_watched} villages · ${c.alerts_sent ? `${c.alerts_sent} real ${c.alerts_sent === 1 ? 'alert' : 'alerts'} sent` : 'no real flood alert sent yet'}${c.drills_delivered ? ` (${c.drills_delivered} ${c.drills_delivered === 1 ? 'drill' : 'drills'})` : ''}`}
          </p>
        )}
      </header>

      {error && !data ? (
        <div className="wrap">
          <ErrorState error={error} onRetry={refresh} />
        </div>
      ) : (
        <div className="wrap lv2-grid">
          <div className="lv2-seg" role="group" aria-label={hi ? 'सूची या नक्शा' : 'List or map'}>
            <button type="button" aria-pressed={view === 'list'} onClick={() => setView('list')}>
              <List aria-hidden="true" /> {hi ? 'सूची' : 'List'}
            </button>
            <button type="button" aria-pressed={view === 'map'} onClick={() => setView('map')}>
              <MapIcon aria-hidden="true" /> {hi ? 'नक्शा' : 'Map'}
            </button>
          </div>
          <section className={`lv2-list${!wide && view === 'map' ? ' is-off' : ''}`} aria-labelledby="lv2-list-h" data-tour="live-list">
            <h2 id="lv2-list-h" className="sr-only">
              {t('live.villages')}
            </h2>
            {rows.length ? (
              <VillageRows villages={rows} label={hi ? 'पाँच गाँव' : 'The villages'} hot={hot} onHot={setHot} sub={sub} />
            ) : (
              <p className="vrows vrows-wait">{hi ? 'गाँवों की सूची आ रही है…' : 'Loading the villages…'}</p>
            )}
          </section>
          {showMap && (
            <section className="lv2-map" aria-label={hi ? 'नक्शा' : 'Map'} data-tour="live-map">
              {data && !mapNow && (
                <div className="map-wrap map-gate">
                  <div className="map-gate-body">
                    <MapIcon aria-hidden="true" />
                    <p className="map-gate-note small">{t('map.gate.note')}</p>
                    <button type="button" className="btn btn-ghost" onClick={() => setAsked(true)}>
                      {t('map.gate.show')}
                    </button>
                  </div>
                </div>
              )}
              {data && mapNow && (
                <LazyVillageMap
                  eager
                  villages={data.villages}
                  highlight={hot ? [hot] : undefined}
                  onSelect={(id) => nav(`/village/${id}`)}
                  safe={safeLayer.views}
                  safeToggle={{ on: safeLayer.on, onChange: safeLayer.setOn }}
                  onSafeSelect={(_, villageId) => nav(`/village/${villageId}`)}
                />
              )}
              <div className="map-legend-float">
                <LevelLegend />
              </div>
            </section>
          )}
        </div>
      )}

      {data && (
        <div className="wrap lv2-below">
          <section aria-labelledby="alerts-h" className="lv2-alerts">
            <h2 id="alerts-h" className="lv2-h2">
              {t('live.alerts')}
            </h2>
            {data.recent_alerts.length === 0 ? (
              <EmptyState title={t('live.alerts.empty')} body={hi ? 'हर 15 मिनट नदी और बारिश की जाँच होती है; चेतावनी आई तो यहाँ दिखेगी।' : 'River and rain are checked every 15 minutes; an alert shows here when one goes out.'} />
            ) : (
              <ul className="alert-list">
                {data.recent_alerts.slice(0, 3).map((a) => (
                  <li key={a.id} className={`alert-row lv-${a.level}`}>
                    <div className="ar-top">
                      <LevelBadge level={a.level} size="sm" />
                      <AlertStatusChip status={a.status} />
                      {a.replay && <ReplayChip />}
                    </div>
                    <p className="ar-name">
                      <span lang="hi">{a.village_name_hi}</span> <span className="muted">· {a.village_name}</span>
                    </p>
                    <DeliveryChips approved={a.approved} delivered={a.delivered_count} acked={a.acknowledged_count} status={a.status} />
                    <p className="small muted">{fmtAgo(a.created_at, lang)}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <div className="lv2-funnel" data-tour="funnel">
            <AckFunnel alerts={data.recent_alerts} />
          </div>
        </div>
      )}
    </div>
  );
}
