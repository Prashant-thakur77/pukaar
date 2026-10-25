import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { DataStatusNote, LiveLevelNote, ShownLevel } from '../../components/DataStatus';
import { levelIsKnown } from '../../lib/dataStatus';
import { ErrorState, SkeletonCards } from '../../components/States';
import type { PollState } from '../../hooks/usePoll';
import { useT } from '../../i18n';
import { fmtAgo, fmtNumber } from '../../lib/format';
import { levelRank } from '../../lib/levels';
import type { Village } from '../../types';

export function VillageQueue({ poll }: { poll: PollState<Village[]> }) {
  const { t, lang } = useT();
  const { data, error, loading, refresh } = poll;
  if (loading && !data) return <SkeletonCards n={4} />;
  if (error && !data) return <ErrorState error={error} onRetry={refresh} compact />;
  const ranked = [...(data ?? [])].sort(
    (a, b) =>
      levelRank(b.level) - levelRank(a.level) ||
      (b.latest_reading?.rain_24h_mm ?? 0) - (a.latest_reading?.rain_24h_mm ?? 0) ||
      a.name.localeCompare(b.name),
  );
  return (
    <ol className="queue">
      {ranked.map((v, i) => (
        <li key={v.id}>
          <Link to={`/village/${v.id}`} className={`queue-row lv-${levelIsKnown(v) ? v.level : 'nodata'}`}>
            <span className="q-rank">{i + 1}</span>
            <span className="q-main">
              <span className="q-name">
                {lang === 'hi' ? v.name_hi || v.name : v.name}
              </span>
              <span className="q-badges">
                <ShownLevel v={v} plain />
                {v.open_alert_id && <span className="q-open" role="img" title={t('queue.open.alert')} aria-label={t('queue.open.alert')} />}
                {v.readiness?.state === 'get_ready' && (
                  <span className="q-ready" title={t('ready.soft')}>
                    {t('ready.get')}
                  </span>
                )}
              </span>
              <DataStatusNote v={v} compact />
              <LiveLevelNote v={v} compact />
              <span className="small muted">
                {t('console.reading', {
                  r: fmtNumber(v.latest_reading?.rain_24h_mm, lang, 1),
                  d: v.latest_reading?.discharge_peak != null ? `${fmtNumber(v.latest_reading.discharge_peak, lang, 0)} m³/s` : '—',
                })}
                {v.level_since && ` · ${fmtAgo(v.level_since, lang)}`}
              </span>
            </span>
            <ChevronRight aria-hidden="true" className="q-go" />
          </Link>
        </li>
      ))}
    </ol>
  );
}
