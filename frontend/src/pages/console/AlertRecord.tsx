import { useState } from 'react';
import { Download, FileText } from 'lucide-react';
import { api, ApiError } from '../../api';
import { TimeToEar } from '../../components/TimeToEar';
import { Skeleton } from '../../components/States';
import { usePoll } from '../../hooks/usePoll';
import { useT } from '../../i18n';
import { afterActionFilename } from '../../lib/afterAction';
import { fmtTime } from '../../lib/format';
import { CHANNELS } from '../../lib/live';
import { relayLabel } from '../../lib/roster';
import { alertRows } from '../../lib/pilotTen';
import type { Alert, AlertOutcome } from '../../types';

/* A sent alert's record in the console: its after-action report, "was this real?" and who it reached. */

/**
 * The alert's after-action report (GET /alerts/{id}/after-action). The route needs the sign-in
 * token, which a plain link cannot carry, so the page is fetched and shown from a blob URL. The
 * report is static HTML with a CSP that runs no script.
 */
export function AfterActionLinks({ alert: a }: { alert: Alert }) {
  const { t, lang } = useT();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async (mode: 'open' | 'download') => {
    setErr(null);
    setBusy(true);
    // Open the tab inside the click so pop-up blockers allow it; fill it when the report arrives.
    const win = mode === 'open' ? window.open('', '_blank') : null;
    try {
      const blob = await api.afterAction(a.id);
      const url = URL.createObjectURL(new Blob([blob], { type: 'text/html;charset=utf-8' }));
      if (win) {
        win.opener = null;
        win.location.href = url;
      } else {
        const link = document.createElement('a');
        link.href = url;
        link.download = afterActionFilename(a);
        document.body.appendChild(link);
        link.click();
        link.remove();
      }
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      win?.close();
      setErr(e instanceof ApiError ? (lang === 'hi' && e.messageHi) || e.messageEn : t('console.aar.error'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <p className="small aar-links">
      <button type="button" className="link-btn" disabled={busy} title={t('console.aar.title')} onClick={() => void run('open')}>
        <FileText aria-hidden="true" /> {t('console.aar.open')}
      </button>
      {' · '}
      <button type="button" className="link-btn" disabled={busy} onClick={() => void run('download')}>
        <Download aria-hidden="true" /> {t('console.aar.download')}
      </button>
      {err && (
        <span className="bad-text" role="alert">
          {' '}
          {err}
        </span>
      )}
    </p>
  );
}

const OUTCOMES: AlertOutcome[] = ['real_flood', 'no_flood', 'unknown'];

/** "Was this real?" for a closed live alert (POST /alerts/{id}/outcome); it can be corrected later. */
export function OutcomePicker({ alert: a }: { alert: Alert }) {
  const { t, lang } = useT();
  const [value, setValue] = useState<AlertOutcome | null>(a.outcome ?? null);
  // When harm began (optional, local time): the lead time achieved, pilot metric 5.
  const [onset, setOnset] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async (o: AlertOutcome) => {
    setErr(null);
    setBusy(true);
    try {
      const iso = onset && o === 'real_flood' ? new Date(onset).toISOString() : undefined;
      const updated = await api.setAlertOutcome(a.id, o, iso);
      setValue(updated.outcome ?? o);
    } catch (e) {
      setErr(e instanceof ApiError ? (lang === 'hi' && e.messageHi) || e.messageEn : t('console.aar.error'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <fieldset className="aar-outcome">
      <legend className="small">{t('console.outcome.q')}</legend>
      <span role="group" aria-label={t('console.outcome.q')}>
        {OUTCOMES.map((o) => (
          <button
            key={o}
            type="button"
            className={`btn btn-sm btn-state${value === o ? ' is-current' : ''}`}
            aria-pressed={value === o}
            disabled={busy}
            onClick={() => void save(o)}
          >
            {t(`console.outcome.${o}`)}
          </button>
        ))}
      </span>
      <span className="small muted" role="status">
        {' '}
        {value ? t('console.outcome.saved', { o: t(`console.outcome.${value}`) }) : t('console.outcome.hint')}
      </span>
      <label className="small aar-onset">
        {lang === 'hi' ? 'असली बाढ़ हो तो, नुक़सान कब शुरू हुआ (वैकल्पिक)' : 'If a real flood: when harm began (optional)'}{' '}
        <input type="datetime-local" value={onset} disabled={busy} onChange={(e) => setOnset(e.target.value)} />
      </label>
      {err && (
        <span className="bad-text small" role="alert">
          {' '}
          {err}
        </span>
      )}
    </fieldset>
  );
}

export function Deliveries({ alertId }: { alertId: string }) {
  const { t, lang } = useT();
  const { data, error, loading } = usePoll(() => api.alert(alertId), [alertId], 15000, {
    live: [CHANNELS.alerts, CHANNELS.deliveries],
    match: (e) => e.data.alert_id === alertId,
  });
  if (loading && !data) return <Skeleton lines={2} />;
  if (error && !data) return <p className="small bad-text">{error.messageEn}</p>;
  const ds = data?.deliveries ?? [];
  if (!ds.length) return <p className="small muted">{t('console.deliveries.none')}</p>;
  return (
    <>
    {data && <TimeToEar alert={data.alert} deliveries={ds} />}
    <ul className="dl-list">
      {ds.map((d) => (
        <li key={`${d.recipient_id}-${d.channel}`} className={d.relay_role ? 'dl-relay' : undefined}>
          <strong>{d.name}</strong>
          <span className={`chip ${d.channel === 'stub' ? 'chip-muted' : ''}`}>
            {d.channel === 'stub' ? t('console.channel.stub') : d.channel === 'voice' ? t('console.channel.voice') : t('console.channel.telegram')}
          </span>
          {d.relay_role && <span className="dl-relay-word">{t('console.delivery.relay', { r: relayLabel(d.relay_role, lang) })}</span>}
          <span className="small">
            {d.sent_at ? t('console.delivery.sent', { t: fmtTime(d.sent_at, lang) }) : t('console.delivery.notsent')}
            {' · '}
            {d.acknowledged_at ? (
              <span className="ok-text">
                ✓{' '}
                {d.relay_role
                  ? t('console.delivery.relaydone', { t: fmtTime(d.acknowledged_at, lang) })
                  : t('console.delivery.acked', { t: fmtTime(d.acknowledged_at, lang) })}
              </span>
            ) : (
              <span className="muted">{t('console.delivery.noack')}</span>
            )}
            {d.all_clear_status && (
              <span className={d.all_clear_status === 'failed' ? 'bad-text' : 'muted'}>
                {' · '}
                {t(d.all_clear_status === 'failed' ? 'console.delivery.allclear.failed' : 'console.delivery.allclear')}
              </span>
            )}
            {d.error && <span className="bad-text"> · {d.error}</span>}
          </span>
        </li>
      ))}
    </ul>
    </>
  );
}

/** The ten pilot metrics for this alert (GET /alerts/{id}/metrics): counts and times, "—" where not measured. */
export function AlertMetricsPanel({ alertId }: { alertId: string }) {
  const { lang } = useT();
  const { data, error, loading } = usePoll(() => api.alertMetrics(alertId), [alertId], 60000);
  if (loading && !data) return <Skeleton lines={3} />;
  if (error && !data) return <p className="small bad-text">{error.messageEn}</p>;
  if (!data) return null;
  const kind =
    data.kind === 'live'
      ? null
      : data.kind === 'drill'
        ? lang === 'hi' ? 'अभ्यास' : 'Drill'
        : data.kind === 'demo'
          ? lang === 'hi' ? 'लाइव डेमो' : 'Live demo'
          : lang === 'hi' ? 'रीप्ले' : 'Replay';
  return (
    <>
      {kind && (
        <p className="small muted">
          {lang === 'hi' ? `${kind}: असली चेतावनियों से अलग गिना जाता है।` : `${kind}: counted apart from real alerts.`}
        </p>
      )}
      <dl className="dp-metrics">
        {alertRows(data, lang).map((r) => (
          <div key={r.n}>
            <dt>
              {r.n}. {r.title}
            </dt>
            <dd>{r.value}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}
