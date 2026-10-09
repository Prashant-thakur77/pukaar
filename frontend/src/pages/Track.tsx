import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { CircleCheck, CircleDot, Search } from 'lucide-react';
import { api } from '../api';
import { ErrorState, Skeleton } from '../components/States';
import { usePoll } from '../hooks/usePoll';
import { enumLabels, useT } from '../i18n';
import { fmtTime } from '../lib/format';

export default function Track() {
  const { code = '' } = useParams();
  const { t, lang, pick } = useT();
  const nav = useNavigate();
  const [q, setQ] = useState('');
  const { data, error, loading, refresh } = usePoll(() => api.track(code), [code], code ? 30000 : 0);

  const lookup = (e: FormEvent) => {
    e.preventDefault();
    if (q.trim()) nav(`/t/${q.trim().toUpperCase()}`);
  };

  return (
    <div className="track wrap-narrow">
      <p className="eyebrow">{t('track.title')}</p>
      <h1 className="track-code-h">{code}</h1>

      {loading && !data ? (
        <div className="card">
          <Skeleton lines={4} />
        </div>
      ) : error && !data ? (
        error.status === 404 ? (
          <p className="warn-text" role="alert">
            {t('track.notfound')}
          </p>
        ) : (
          <ErrorState error={error} onRetry={refresh} />
        )
      ) : data ? (
        <section className="card track-card">
          <p className="track-village">
            <span lang="hi">{data.village_name_hi}</span> <span className="muted">· {data.village_name}</span>
          </p>
          <p className="muted">
            {pick(enumLabels.reportType[data.report_type])} · {fmtTime(data.created_at, lang)}
          </p>
          <ol className="timeline">
            {data.steps.map((s, i) => (
              <li key={s.key} className={`tl-step${s.done ? ' is-done' : ''}`} style={{ ['--d' as string]: `${i * 140}ms` }}>
                <span className="tl-dot" aria-hidden="true">
                  {s.done ? <CircleCheck /> : <CircleDot />}
                </span>
                <div>
                  <p className="tl-title">{t(`track.step.${s.key}`)}</p>
                  <p className="small muted">{s.done ? fmtTime(s.at, lang) : t('track.pending')}</p>
                </div>
              </li>
            ))}
          </ol>
          <p className="small muted">
            {pick(enumLabels.reportState[data.state])}
          </p>
        </section>
      ) : null}

      <form className="track-lookup" onSubmit={lookup}>
        <label className="field">
          <span className="field-label">{t('track.lookup')}</span>
          <span className="input-row">
            <input value={q} onChange={(e) => setQ(e.target.value)} autoCapitalize="characters" className="input-lg" />
            <button type="submit" className="btn btn-lg btn-ink">
              <Search aria-hidden="true" /> {t('track.go')}
            </button>
          </span>
        </label>
      </form>
      <p>
        <Link to="/report" className="link">
          {t('report.another')} →
        </Link>
      </p>
    </div>
  );
}
