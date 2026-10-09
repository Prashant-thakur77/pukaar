import { useCallback, useState } from 'react';
import { History, LoaderCircle, Play, RotateCcw } from 'lucide-react';
import { api, ApiError } from '../../api';
import { Snackbar, type SnackbarMsg } from '../../components/Snackbar';
import { DeniedNote, ErrorState, Skeleton } from '../../components/States';
import type { PollState } from '../../hooks/usePoll';
import { useT } from '../../i18n';
import { announceReplayChange } from '../../lib/events';
import { fmtTime } from '../../lib/format';
import type { ReplayStatus } from '../../types';

const SCENARIO_NAMES: Record<string, { hi: string; en: string }> = {
  himachal_2023_07: { hi: 'हिमाचल, 7-11 जुलाई 2023', en: 'Himachal, 7-11 July 2023' },
  mandi_2025: { hi: 'मंडी, जून-जुलाई 2025', en: 'Mandi, June-July 2025' },
};

/** Seconds of wall time per hour of archived data. The server caps it so a run fits one worker call. */
export const REPLAY_SPEED = 4;

export function Replay({ poll, onChanged, canControl = true }: { poll: PollState<ReplayStatus>; onChanged?: () => void; canControl?: boolean }) {
  const { t, lang } = useT();
  const [snack, setSnack] = useState<SnackbarMsg | null>(null);
  const closeSnack = useCallback(() => setSnack(null), []);
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
      if (kind === 'start') await api.replayStart(scenario ? { scenario, speed_seconds_per_hour: REPLAY_SPEED } : {});
      else await api.replayReset();
      if (kind === 'reset') setSnack({ id: Date.now(), text: t('console.replay.reset.done') });
      await poll.refresh();
      // Alerts, villages and the banner change with the replay: refetch now, not on the next poll.
      onChanged?.();
      announceReplayChange();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
    } finally {
      setBusy(null);
    }
  }

  if (poll.loading && !s) return <Skeleton lines={2} />;
  if (poll.error && !s) return <ErrorState error={poll.error} onRetry={poll.refresh} compact />;
  const pct = s && s.hours_total ? (s.hours_done / s.hours_total) * 100 : 0;
  const finished = Boolean(s && !s.active && s.hours_total > 0 && s.hours_done >= s.hours_total);
  return (
    <div className="replay-box">
      {!s?.active && !finished && <p className="small muted">{t('console.replay.lead')}</p>}
      {s && (
        <div className={`replay-status${s.active || finished ? ' is-active' : ''}`}>
          <History aria-hidden="true" />
          <div>
            <strong>
              {s.active
                ? (lang === 'hi' ? s.title_hi : s.title) || s.scenario || t('common.replay')
                : finished
                  ? t('shell.replay.done')
                  : t('console.replay.idle')}
            </strong>
            <span className="small muted">{[s.active ? null : (lang === 'hi' ? s.title_hi : s.title) || s.source, s.clock ? fmtTime(s.clock, lang) : null].filter(Boolean).join(' · ')}</span>
            <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={s.hours_total} aria-valuenow={s.hours_done} aria-label={t('console.replay.progress', { d: s.hours_done, t: s.hours_total })}>
              <i style={{ transform: `scaleX(${pct / 100})` }} />
            </div>
            <span className="small">{t('console.replay.progress', { d: s.hours_done, t: s.hours_total })}</span>
          </div>
        </div>
      )}
      {s && !canStart && <p className="small warn-text">{t('console.replay.unavailable')}</p>}
      {canControl && (
      <div className="replay-controls">
      {scenarios.length > 1 && !s?.active && (
        <label className="field replay-pick">
          <span className="sr-only">{t('console.replay.scenario')}</span>
          <span className="select-wrap">
            <select value={scenario} onChange={(e) => setPicked(e.target.value)}>
              {scenarios.map((sc) => (
                <option key={sc} value={sc}>
                  {SCENARIO_NAMES[sc]?.[lang] ?? sc}
                </option>
              ))}
            </select>
          </span>
        </label>
      )}
        <button type="button" className="btn btn-accent btn-press" onClick={() => void run('start')} disabled={busy !== null || !canStart || s?.active}>
          {busy === 'start' ? <LoaderCircle className="spin" aria-hidden="true" /> : <Play aria-hidden="true" />} {t('console.replay.start')}
        </button>
        <button type="button" className="btn btn-ghost btn-press" onClick={() => void run('reset')} disabled={busy !== null}>
          {busy === 'reset' ? <LoaderCircle className="spin" aria-hidden="true" /> : <RotateCcw aria-hidden="true" />}{' '}
          {busy === 'reset' ? t('console.replay.resetting') : t('console.replay.reset')}
        </button>
      </div>
      )}
      {canControl && canStart && <p className="small muted replay-speed">{t('console.replay.speed')}</p>}
      {err && (err.isDenied ? <DeniedNote error={err} /> : <ErrorState error={err} compact />)}
      <Snackbar msg={snack} onClose={closeSnack} closeLabel={t('common.close')} />
    </div>
  );
}
