import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { LevelBadge } from '../../components/Level';
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
          <Link to={`/village/${v.id}`} className={`queue-row lv-${v.level}`}>
            <span className="q-rank">{i + 1}</span>
            <span className="q-main">
              <span className="q-name">
                <span lang="hi">{v.name_hi}</span> <span className="muted">· {v.name}</span>
              </span>
              <span className="small muted">
                {t('console.reading', {
                  r: fmtNumber(v.latest_reading?.rain_24h_mm, lang, 1),
                  d: v.latest_reading?.discharge_peak != null ? `${fmtNumber(v.latest_reading.discharge_peak, lang, 0)} m³/s` : '—',
                })}
                {v.level_since && ` · ${fmtAgo(v.level_since, lang)}`}
              </span>
            </span>
            <LevelBadge level={v.level} size="sm" />
            {v.open_alert_id && <span className="q-open" title="Open alert" aria-label="Open alert" />}
            <ChevronRight aria-hidden="true" className="q-go" />
          </Link>
        </li>
      ))}
    </ol>
  );
}
