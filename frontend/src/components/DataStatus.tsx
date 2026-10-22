import { CloudOff, Clock } from 'lucide-react';
import { useT } from '../i18n';
import { dataIssue, levelIsKnown, liveLevelIfDifferent } from '../lib/dataStatus';
import { fmtAgo, fmtTime } from '../lib/format';
import type { DataStatus, Level } from '../types';
import { LevelBadge } from './Level';

type V = { level: Level; live_level?: Level; replay?: boolean; data_status?: DataStatus; data_ok_at?: string | null; data_note?: string };

/** "No data" / "Data late" in place of a Normal that nobody can vouch for. Never green. */
export function DataBadge({ kind, size = 'sm', plain = false }: { kind: 'stale' | 'unavailable'; size?: 'sm' | 'md' | 'lg'; plain?: boolean }) {
  const { t } = useT();
  const Icon = kind === 'unavailable' ? CloudOff : Clock;
  return (
    <span className={`level-badge lv-nodata lb-${size}${plain ? ' lb-plain' : ''}`} data-level="unknown">
      <Icon className="lb-icon" aria-hidden="true" />
      <span className="lb-words">
        <span lang="hi">{kind === 'unavailable' ? 'डेटा नहीं' : 'डेटा देर से'}</span>
        <span className="lb-sep" aria-hidden="true">
          ·
        </span>
        <span lang="en">{kind === 'unavailable' ? t('data.badge.none') : t('data.badge.late')}</span>
      </span>
    </span>
  );
}

/** The village's level as shown to the public: the level, or the data badge when Normal cannot be vouched for. */
export function ShownLevel({ v, size = 'sm', plain = false }: { v: V; size?: 'sm' | 'md' | 'lg'; plain?: boolean }) {
  const issue = dataIssue(v);
  if (issue && !levelIsKnown(v)) return <DataBadge kind={issue.kind} size={size} plain={plain} />;
  return <LevelBadge level={v.level} size={size} plain={plain && v.level !== 'critical'} />;
}

/**
 * Late or missing forecast data, said plainly with the time of the last good data. `compact` is
 * the one-line form for tiles and queue rows.
 */
export function DataStatusNote({ v, compact = false }: { v: V; compact?: boolean }) {
  const { t, lang } = useT();
  const issue = dataIssue(v);
  if (!issue) return null;
  const when = issue.okAt ? (compact ? fmtAgo(issue.okAt, lang) : fmtTime(issue.okAt, lang)) : null;
  const title = issue.kind === 'unavailable' ? t('data.none') : t('data.late');
  if (compact)
    return (
      <span className={`data-line is-${issue.kind}`}>
        {issue.kind === 'unavailable' ? <CloudOff aria-hidden="true" /> : <Clock aria-hidden="true" />}
        {title}
        {when && <span className="data-when">{t('data.lastgood', { t: when })}</span>}
      </span>
    );
  return (
    <div className={`data-note is-${issue.kind}`} role="status">
      {issue.kind === 'unavailable' ? <CloudOff aria-hidden="true" /> : <Clock aria-hidden="true" />}
      <div>
        <p className="data-title">{title}</p>
        <p className="data-body">
          {when ? t('data.lastgood.long', { t: when }) : t('data.lastgood.never')} {t('data.held')}
          {v.level === 'normal' && <> {t('data.notsafe')}</>}
        </p>
      </div>
    </div>
  );
}

/** During a replay a Normal live village shows the replay's level; the live one is said beside it. */
export function LiveLevelNote({ v, compact = false }: { v: V; compact?: boolean }) {
  const { t, lang } = useT();
  const live = liveLevelIfDifferent(v);
  if (!live) return null;
  return (
    <span className={`live-level-note${compact ? ' is-compact' : ''}`}>
      {t('data.livelevel')} <LevelBadge level={live} size="sm" plain both={!compact} lang={lang} />
      {v.replay && <span className="lln-why">{t('data.replayshown')}</span>}
    </span>
  );
}
