import { Link, useNavigate } from 'react-router-dom';
import { MapPin } from 'lucide-react';
import { api } from '../api';
import { AckFunnel } from '../components/AckFunnel';
import { AlertStatusChip, DeliveryChips, ReplayChip } from '../components/Chips';
import { CountUp } from '../components/CountUp';
import { LevelBadge, LevelIcon, LevelLegend } from '../components/Level';
import { Reveal } from '../components/Reveal';
import { EmptyState, ErrorState, Skeleton, SkeletonCards } from '../components/States';
import { VillageMap } from '../components/VillageMap';
import { usePoll } from '../hooks/usePoll';
import { useT } from '../i18n';
import { fmtAgo } from '../lib/format';
import { levelRank } from '../lib/levels';
import type { Counters } from '../types';

const COUNTERS: (keyof Counters)[] = ['villages_watched', 'alerts_sent', 'phones_acknowledged', 'reports_received'];

export default function Live() {
  const { t, lang } = useT();
  const nav = useNavigate();
  const { data, error, loading, refresh, updatedAt } = usePoll(() => api.overview(), []);
  const villages = data ? [...data.villages].sort((a, b) => levelRank(b.level) - levelRank(a.level) || a.name.localeCompare(b.name)) : [];

  return (
    <div className="live wrap-wide">
      <header className="page-head">
        <div>
          <p className="eyebrow">
            <span className="live-dot" aria-hidden="true" /> {t('live.eyebrow')}
          </p>
          <h1 className="display-3">{t('live.title')}</h1>
          <p className="muted">{t('live.lead')}</p>
        </div>
        {updatedAt && (
          <p className="small muted updated" aria-live="off">
            {t('common.updated', { t: fmtAgo(new Date(updatedAt).toISOString(), lang) })}
          </p>
        )}
      </header>

      {error && !data ? (
        <ErrorState error={error} onRetry={refresh} />
      ) : (
        <div className="live-grid">
          <div className="live-map card card-flush">
            {data ? (
              <VillageMap villages={data.villages} onSelect={(id) => nav(`/village/${id}`)} />
            ) : (
              <div className="map-wrap">
                <div className="map-skel skel" aria-hidden="true" />
              </div>
            )}
            <div className="map-legend-float">
              <LevelLegend />
            </div>
          </div>

          <aside className="live-side">
            <ul className="mini-counters">
              {COUNTERS.map((k) => (
                <li key={k} className="mini-counter">
                  {loading && !data ? <Skeleton height={34} /> : <CountUp value={data ? data.counters[k] : null} lang={lang} className="mc-num" />}
                  <span className="mc-label">{t(`counter.${k}`)}</span>
                </li>
              ))}
            </ul>

            <section aria-labelledby="alerts-h" className="side-sec">
              <h2 id="alerts-h" className="h-sec">
                {t('live.alerts')}
              </h2>
              {loading && !data ? (
                <SkeletonCards n={2} />
              ) : data && data.recent_alerts.length === 0 ? (
                <EmptyState title={t('live.alerts.empty')} />
              ) : (
                <ul className="alert-list">
                  {data?.recent_alerts.map((a, i) => (
                    <Reveal as="li" key={a.id} delay={i * 60} className={`alert-row lv-${a.level}`}>
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
                    </Reveal>
                  ))}
                </ul>
              )}
            </section>
          </aside>

          {data && (
            <div className="live-funnel">
              <AckFunnel alerts={data.recent_alerts} />
            </div>
          )}

          <section aria-labelledby="vil-h" className="live-villages">
            <h2 id="vil-h" className="h-sec">
              {t('live.villages')}
            </h2>
            {loading && !data ? (
              <SkeletonCards n={4} />
            ) : (
              <ul className="village-tiles">
                {villages.map((v, i) => (
                  <Reveal as="li" key={v.id} delay={i * 50}>
                    <Link to={`/village/${v.id}`} className={`village-tile lv-${v.level}`}>
                      <span className="vt-icon" aria-hidden="true">
                        <LevelIcon level={v.level} />
                      </span>
                      <span className="vt-names">
                        <span lang="hi" className="vt-hi">
                          {v.name_hi}
                        </span>
                        <span className="vt-en">{v.name}</span>
                      </span>
                      <LevelBadge level={v.level} size="sm" />
                      {!v.coords_verified && (
                        <span className="vt-approx">
                          <MapPin aria-hidden="true" /> {t('common.approx')}
                        </span>
                      )}
                    </Link>
                  </Reveal>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
