import { useState, type FormEvent } from 'react';
import { Navigate, useSearchParams } from 'react-router-dom';
import { Filter, ShieldCheck, ShieldX } from 'lucide-react';
import { filterAudit, isRoutineRead, normaliseResource } from '../lib/audit';
import { api } from '../api';
import { EmptyState, ErrorState, Skeleton } from '../components/States';
import { usePoll } from '../hooks/usePoll';
import { useT } from '../i18n';
import { fmtTime } from '../lib/format';
import { useAuth } from '../store';

export default function Audit() {
  const token = useAuth((s) => s.token);
  if (!token) return <Navigate to="/login" replace state={{ from: '/audit' }} />;
  return <AuditInner />;
}

function AuditInner() {
  const { t, lang } = useT();
  const [params, setParams] = useSearchParams();
  const resource = params.get('resource') ?? '';
  const [q, setQ] = useState(resource);
  const [showReads, setShowReads] = useState(false);
  const { data, error, loading, refresh } = usePoll(() => api.audit({ resource: resource || undefined }), [resource], 30000);
  const view = filterAudit(data ?? [], showReads);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const r = normaliseResource(q);
    setQ(r);
    setParams(r ? { resource: r } : {});
  };

  return (
    <div className="wrap audit">
      <p className="eyebrow">{t('console.title')}</p>
      <h1 className="display-3">{t('audit.title')}</h1>
      <p className="muted">{t('audit.lead')}</p>
      <form className="input-row audit-filter" onSubmit={submit}>
        <label className="sr-only" htmlFor="aud-r">
          {t('audit.filter')}
        </label>
        <input id="aud-r" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('audit.filter')} />
        <button type="submit" className="btn btn-ink">
          <Filter aria-hidden="true" /> {t('audit.filter')}
        </button>
      </form>
      {data && (
        <div className="audit-bar">
          <span className={`chip ${view.denies ? 'chip-bad chip-strong' : 'chip-muted'}`} role="status">
            <ShieldX aria-hidden="true" /> {t('audit.denies', { n: view.denies })}
          </span>
          <label className="switch">
            <input type="checkbox" checked={showReads} onChange={(e) => setShowReads(e.target.checked)} />
            <span>{t('audit.reads', { n: showReads ? data.filter(isRoutineRead).length : view.hiddenReads })}</span>
          </label>
          {resource && (
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => { setQ(''); setParams({}); }}>
              {t('audit.clear')}
            </button>
          )}
        </div>
      )}
      {loading && !data ? (
        <Skeleton lines={6} />
      ) : error && !data ? (
        <ErrorState error={error} onRetry={refresh} />
      ) : !view.rows.length ? (
        <EmptyState title={t('state.empty')} />
      ) : (
        <div className="table-wrap card card-flush" tabIndex={0} role="region" aria-label={t('audit.title')}>
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Actor</th>
                <th scope="col">Action</th>
                <th scope="col">Resource</th>
                <th scope="col">Decision</th>
                <th scope="col">Reason</th>
              </tr>
            </thead>
            <tbody>
              {view.rows.map((a) => (
                <tr key={a.id} className={a.decision === 'deny' ? 'row-deny' : ''}>
                  <td className="nowrap">{fmtTime(a.at, lang)}</td>
                  <td>
                    {a.actor} <span className="muted small">({a.role})</span>
                  </td>
                  <td>
                    <code>{a.action}</code>
                  </td>
                  <td>
                    <code>{a.resource}</code>
                  </td>
                  <td>
                    {a.decision === 'allow' ? (
                      <span className="chip chip-good">
                        <ShieldCheck aria-hidden="true" /> {t('audit.allow')}
                      </span>
                    ) : (
                      <span className="chip chip-bad chip-strong">
                        <ShieldX aria-hidden="true" /> {t('audit.deny')}
                      </span>
                    )}
                  </td>
                  <td>{a.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
