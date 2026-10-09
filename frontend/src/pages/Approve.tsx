import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Check, CircleCheck, CircleX, Clock, X } from 'lucide-react';
import { api, ApiError } from '../api';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { LevelBadge } from '../components/Level';
import { ListenButton } from '../components/ListenButton';
import { ReplayChip } from '../components/Chips';
import { DeniedNote, ErrorState, Skeleton } from '../components/States';
import { usePoll } from '../hooks/usePoll';
import { dict } from '../i18n';
import { fmtDuration } from '../lib/format';
import type { Alert } from '../types';

/** Both languages on every line: an officer may read either. */
function Bi({ k, vars }: { k: keyof typeof dict; vars?: Record<string, string | number> }) {
  const f = (s: string) => s.replace(/\{(\w+)\}/g, (_, n: string) => String(vars?.[n] ?? ''));
  return (
    <>
      <span lang="hi">{f(dict[k].hi)}</span>
      <span className="bi-en">{f(dict[k].en)}</span>
    </>
  );
}

function useCountdown(iso: string | undefined) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return iso ? new Date(iso).getTime() - now : null;
}

function LatePage({ error }: { error?: ApiError | null }) {
  return (
    <section className="approve-end is-late" role="alert">
      <span className="result-icon" aria-hidden="true">
        <Clock />
      </span>
      <h1 className="result-title">
        <Bi k="approve.late.title" />
      </h1>
      <p className="result-body">
        {error?.messageHi ? <span lang="hi">{error.messageHi}</span> : <span lang="hi">{dict['approve.late.body'].hi}</span>}
        <span className="bi-en">{error?.messageEn && error.status === 409 ? error.messageEn : dict['approve.late.body'].en}</span>
      </p>
    </section>
  );
}

export default function Approve() {
  const { token = '' } = useParams();
  const { data, error, loading, refresh } = usePoll(() => api.approval(token), [token], 0);
  const [confirm, setConfirm] = useState<'approve' | 'decline' | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Alert | null>(null);
  const [actErr, setActErr] = useState<ApiError | null>(null);
  const left = useCountdown(data?.expires_at);

  async function decide(d: 'approve' | 'decline') {
    setBusy(true);
    setActErr(null);
    try {
      setResult(await api.decideApproval(token, d));
    } catch (e) {
      setActErr(e instanceof ApiError ? e : new ApiError(0, null));
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  }

  let body;
  if (loading && !data) {
    body = (
      <div className="card">
        <Skeleton lines={5} />
      </div>
    );
  } else if (error && !data) {
    body = error.status === 409 || error.status === 410 ? <LatePage error={error} /> : error.status === 404 || error.status === 400 || error.status === 401 ? (
      <section className="approve-end is-late" role="alert">
        <span className="result-icon" aria-hidden="true">
          <CircleX />
        </span>
        <h1 className="result-title">
          <Bi k="approve.invalid" />
        </h1>
      </section>
    ) : (
      <ErrorState error={error} onRetry={refresh} />
    );
  } else if (result) {
    const ok = result.status !== 'declined';
    body = (
      <section className={`approve-end ${ok ? 'is-ok' : 'is-declined'}`} aria-live="polite">
        <span className="result-icon" aria-hidden="true">
          {ok ? <CircleCheck /> : <CircleX />}
          <i />
        </span>
        <h1 className="result-title">{ok ? <Bi k="approve.done.approved" /> : <Bi k="approve.done.declined" />}</h1>
      </section>
    );
  } else if (actErr?.isLate || (data && !data.valid) || (left !== null && left <= 0)) {
    body = <LatePage error={actErr} />;
  } else if (data) {
    const a = data.alert;
    const fallback = a.reasoning_model === 'rule-fallback';
    body = (
      <article className={`approve-card lv-${a.level}`}>
        <header className="approve-top">
          <p className="eyebrow">
            <Bi k="approve.eyebrow" />
          </p>
          <span className={`countdown${left !== null && left < 120000 ? ' is-low' : ''}`}>
            <Clock aria-hidden="true" /> {left !== null ? fmtDuration(left) : '—'}
          </span>
        </header>
        <div className="approve-level">
          <LevelBadge level={a.level} size="lg" />
          {a.replay && <ReplayChip />}
        </div>
        <h1 className="approve-village">
          <span lang="hi">{a.village_name_hi}</span>
          <span className="bi-en">{a.village_name}</span>
        </h1>
        <ListenButton alertId={a.id} big hasAudio={a.has_audio} />
        <blockquote className="draft-hi" lang="hi">
          {a.text_hi}
        </blockquote>
        <p className="draft-en">{a.text_en}</p>
        <p className="small muted">
          <Bi k="approve.recipients" vars={{ n: a.recipients_count }} />
        </p>
        {fallback && <p className="chip chip-warn">rule fallback · नियम टेम्पलेट</p>}
        {actErr && !actErr.isLate && (actErr.isDenied ? <DeniedNote error={actErr} /> : actErr.isRetry ? (
          <p className="warn-text" role="alert">
            <Bi k="approve.retry" />
          </p>
        ) : <ErrorState error={actErr} compact />)}
        <div className="approve-actions">
          <button type="button" className="btn btn-xl btn-approve btn-press" onClick={() => setConfirm('approve')} disabled={busy}>
            <Check aria-hidden="true" />
            <span lang="hi">{dict['approve.approve'].hi}</span>
            <span className="btn-sub">{dict['approve.approve'].en}</span>
          </button>
          <button type="button" className="btn btn-xl btn-decline btn-press" onClick={() => setConfirm('decline')} disabled={busy}>
            <X aria-hidden="true" />
            <span lang="hi">{dict['approve.decline'].hi}</span>
            <span className="btn-sub">{dict['approve.decline'].en}</span>
          </button>
        </div>
        <ConfirmDialog
          open={confirm !== null}
          title={confirm === 'approve' ? `${dict['approve.approve'].hi} · ${dict['approve.approve'].en}` : `${dict['approve.decline'].hi} · ${dict['approve.decline'].en}`}
          confirmLabel={confirm === 'approve' ? 'हाँ, मंज़ूर · Yes, approve' : 'हाँ, अस्वीकार · Yes, decline'}
          cancelLabel="रद्द · Cancel"
          tone={confirm === 'decline' ? 'danger' : 'accent'}
          busy={busy}
          onCancel={() => setConfirm(null)}
          onConfirm={() => confirm && void decide(confirm)}
        >
          <p>{confirm === 'approve' ? <Bi k="approve.confirm.approve" vars={{ n: a.recipients_count }} /> : <Bi k="approve.confirm.decline" />}</p>
        </ConfirmDialog>
      </article>
    );
  }

  return <div className="approve wrap-narrow">{body}</div>;
}
