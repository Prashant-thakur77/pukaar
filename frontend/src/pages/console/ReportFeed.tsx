import { useCallback, useState } from 'react';
import { CircleCheck, Copy, Flag, Hammer, MapPin, ShieldCheck } from 'lucide-react';
import { api, ApiError } from '../../api';
import { ReplayChip, ReportStateChip } from '../../components/Chips';
import { Snackbar, type SnackbarMsg } from '../../components/Snackbar';
import { DeniedNote, EmptyState, ErrorState, SkeletonCards } from '../../components/States';
import type { PollState } from '../../hooks/usePoll';
import { enumLabels, useT } from '../../i18n';
import { fmtAgo } from '../../lib/format';
import { humanizeFlag, humanizeSummary } from '../../lib/humanize';
import type { Report, ReportState, Village } from '../../types';

const ACTIONS: { state: ReportState; icon: typeof ShieldCheck }[] = [
  { state: 'verified', icon: ShieldCheck },
  { state: 'actioned', icon: Hammer },
  { state: 'resolved', icon: CircleCheck },
  { state: 'duplicate', icon: Copy },
  { state: 'false', icon: Flag },
];

const SEV_LEVEL = { low: 'normal', medium: 'watch', high: 'warning', critical: 'critical' } as const;

export function ReportFeed({ poll, villages }: { poll: PollState<Report[]>; villages: Village[] }) {
  const { t, lang, pick } = useT();
  const { data, error, loading, refresh } = poll;
  const [snack, setSnack] = useState<SnackbarMsg | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [overrides, setOverrides] = useState<Record<string, Report>>({});
  const close = useCallback(() => setSnack(null), []);

  async function move(r: Report, state: ReportState, undo = false) {
    setErr(null);
    try {
      const updated = await api.setReportState(r.id, state);
      setOverrides((o) => ({ ...o, [r.id]: updated }));
      if (!undo) {
        const prev = updated.previous_state ?? r.state;
        setSnack({
          id: Date.now(),
          text: t('console.report.moved', { s: pick(enumLabels.reportState[state]) }),
          actionLabel: t('common.undo'),
          onAction: () => void move(updated, prev, true),
        });
      }
      await refresh();
      setOverrides((o) => {
        const { [r.id]: _drop, ...rest } = o;
        void _drop;
        return rest;
      });
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
    }
  }

  if (loading && !data) return <SkeletonCards n={3} />;
  if (error && !data) return <ErrorState error={error} onRetry={refresh} compact />;
  const list = (data ?? []).map((r) => overrides[r.id] ?? r);
  const vname = (id: string) => {
    const v = villages.find((x) => x.id === id);
    return v ? (lang === 'hi' ? v.name_hi : v.name) : id;
  };

  return (
    <>
      {err && (err.isDenied ? <DeniedNote error={err} /> : <ErrorState error={err} compact />)}
      {list.length === 0 ? (
        <EmptyState title={t('console.reports.empty')} />
      ) : (
        <ul className="report-feed">
          {[...list]
            .sort((a, b) => b.created_at.localeCompare(a.created_at))
            .map((r) => (
              <li key={r.id} id={`report-${r.id}`} className={`report-card lv-${SEV_LEVEL[r.severity] ?? 'normal'}`}>
                <div className="rc-top">
                  <span className="rc-type">{pick(enumLabels.reportType[r.report_type])}</span>
                  <span className="chip">{pick(enumLabels.severity[r.severity])}</span>
                  <ReportStateChip state={r.state} />
                  {r.replay && <ReplayChip />}
                  <span className="small muted rc-time">{fmtAgo(r.created_at, lang)}</span>
                </div>
                <p className="rc-village">
                  {vname(r.village_id)}
                  {r.lat != null && r.lon != null && (
                    <span className="small muted">
                      {' '}
                      <MapPin aria-hidden="true" className="inline-icon" /> {r.lat.toFixed(4)}, {r.lon.toFixed(4)}
                    </span>
                  )}
                </p>
                <p className="rc-summary">{humanizeSummary(r.summary_en, lang, r.report_type, r.severity) || r.text}</p>
                {r.transcript && (
                  <p className="rc-transcript" lang="hi">
                    “{r.transcript}”
                  </p>
                )}
                <div className="rc-media">
                  {r.photo_url && <img src={r.photo_url} alt={`Photo: ${r.summary_en || r.report_type}`} loading="lazy" />}
                  {r.audio_url && <audio src={r.audio_url} controls preload="none" aria-label="रिपोर्ट की आवाज़ सुनें (Play report audio)" />}
                </div>
                {r.flags.length > 0 && (
                  <p className="rc-flags">
                    {r.flags.map((f) => {
                      const h = humanizeFlag(f, lang);
                      return h.reportId ? (
                        <a key={f} className="flag-link small" href={`#report-${h.reportId}`}>
                          {h.text}
                        </a>
                      ) : (
                        <span key={f} className={`chip chip-sm chip-${h.tone}`} title={f}>
                          {h.text}
                        </span>
                      );
                    })}
                  </p>
                )}
                {r.parser_source && <p className="small muted">{t('console.parser', { p: r.parser_source })}</p>}
                <div className="rc-actions" role="group" aria-label="Set report state">
                  {ACTIONS.map((a) => (
                    <button
                      key={a.state}
                      type="button"
                      className={`btn btn-sm btn-state${r.state === a.state ? ' is-current' : ''}`}
                      onClick={() => void move(r, a.state)}
                      disabled={r.state === a.state}
                      aria-pressed={r.state === a.state}
                    >
                      <a.icon aria-hidden="true" /> {pick(enumLabels.reportState[a.state])}
                    </button>
                  ))}
                </div>
              </li>
            ))}
        </ul>
      )}
      <Snackbar msg={snack} onClose={close} closeLabel={t('common.close')} />
    </>
  );
}
