import { useState } from 'react';
import { History, LoaderCircle, Play, RotateCcw } from 'lucide-react';
import { api, ApiError } from '../../api';
import { DeniedNote, ErrorState, Skeleton } from '../../components/States';
import type { PollState } from '../../hooks/usePoll';
import { useT } from '../../i18n';
import { fmtTime } from '../../lib/format';
import type { ReplayStatus } from '../../types';

export function Replay({ poll }: { poll: PollState<ReplayStatus> }) {
  const { t, lang } = useT();
  const [busy, setBusy] = useState<'start' | 'reset' | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [picked, setPicked] = useState('');
  const s = poll.data;
  const scenarios = s && Array.isArray(s.available) ? s.available : [];
  const canStart = Boolean(s && (Array.isArray(s.available) ? s.available.length > 0 : s.available));
  const scenario = picked || scenarios[0] || '';

  async function run(kind: 'start' | 'reset') {
    setBusy(kind);
    setErr(null);
    try {
      if (kind === 'start') await api.replayStart(scenario ? { scenario, speed_seconds_per_hour: 1 } : {});
      else await api.replayReset();
      await poll.refresh();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
    } finally {
      setBusy(null);
    }
  }

  if (poll.loading && !s) return <Skeleton lines={2} />;
  if (poll.error && !s) return <ErrorState error={poll.error} onRetry={poll.refresh} compact />;
  const pct = s && s.hours_total ? (s.hours_done / s.hours_total) * 100 : 0;
  return (
    <div className="replay-box">
      <p className="small muted">{t('console.replay.lead')}</p>
      {s && (
        <div className={`replay-status${s.active ? ' is-active' : ''}`}>
          <History aria-hidden="true" />
          <div>
            <strong>{s.active ? (lang === 'hi' ? s.title_hi : s.title) || s.scenario || t('common.replay') : t('console.replay.idle')}</strong>
            <span className="small muted">
              {s.source && ` · ${s.source}`}
              {s.clock && ` · ${fmtTime(s.clock, lang)}`}
            </span>
            <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={s.hours_total} aria-valuenow={s.hours_done} aria-label={t('console.replay.progress', { d: s.hours_done, t: s.hours_total })}>
              <i style={{ transform: `scaleX(${pct / 100})` }} />
            </div>
            <span className="small">{t('console.replay.progress', { d: s.hours_done, t: s.hours_total })}</span>
          </div>
        </div>
      )}
      {s && !canStart && <p className="small warn-text">{t('console.replay.unavailable')}</p>}
      {scenarios.length > 1 && !s?.active && (
        <label className="field">
          <span className="field-label">{t('console.replay.scenario')}</span>
          <span className="select-wrap">
            <select value={scenario} onChange={(e) => setPicked(e.target.value)}>
              {scenarios.map((sc) => (
                <option key={sc} value={sc}>
                  {sc}
                </option>
              ))}
            </select>
          </span>
        </label>
      )}
      <div className="row">
        <button type="button" className="btn btn-accent btn-press" onClick={() => void run('start')} disabled={busy !== null || !canStart || s?.active}>
          {busy === 'start' ? <LoaderCircle className="spin" aria-hidden="true" /> : <Play aria-hidden="true" />} {t('console.replay.start')}
        </button>
        <button type="button" className="btn btn-ghost btn-press" onClick={() => void run('reset')} disabled={busy !== null}>
          {busy === 'reset' ? <LoaderCircle className="spin" aria-hidden="true" /> : <RotateCcw aria-hidden="true" />} {t('console.replay.reset')}
        </button>
      </div>
      {err && (err.isDenied ? <DeniedNote error={err} /> : <ErrorState error={err} compact />)}
    </div>
  );
}
