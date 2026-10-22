import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { CircleCheck, CircleX, Clock, Link2Off, X } from 'lucide-react';
import { api, ApiError } from '../api';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { HoldToConfirm } from '../components/HoldToConfirm';
import '../styles/console-shell.css';
import { LevelBadge } from '../components/Level';
import { ListenButton } from '../components/ListenButton';
import { ReplayChip } from '../components/Chips';
import { DeniedNote, ErrorState, Skeleton } from '../components/States';
import { usePoll } from '../hooks/usePoll';
import { both, useBothLangs, type Key } from '../i18n';
import { expiryMs, fmtDuration } from '../lib/format';
import type { Alert } from '../types';
import '../styles/console.css';

/** Both languages on every line: an officer may read either. */
function Bi({ k, vars }: { k: Key; vars?: Record<string, string | number> }) {
  const f = (s: string) => s.replace(/\{(\w+)\}/g, (_, n: string) => String(vars?.[n] ?? ''));
  return (
    <>
      <span lang="hi">{f(both(k).hi)}</span>
      <span className="bi-en">{f(both(k).en)}</span>
    </>
  );
}

function useCountdown(iso: string | number | undefined) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const at = expiryMs(iso);
  return at == null ? null : at - now;
}

function LatePage({ error, timedOut }: { error?: ApiError | null; timedOut?: boolean }) {
  return (
    <section className="approve-end is-late" role="alert">
      <span className="result-icon" aria-hidden="true">
        <Clock />
      </span>
      <h1 className="result-title">
        <Bi k={timedOut ? 'approve.timeout.title' : 'approve.late.title'} />
      </h1>
      <p className="result-body">
        {error?.messageHi ? <span lang="hi">{error.messageHi}</span> : <span lang="hi">{both('approve.late.body').hi}</span>}
        <span className="bi-en">{error?.messageEn && error.status === 409 ? error.messageEn : both('approve.late.body').en}</span>
      </p>
    </section>
  );
}

/** 400 {code:"invalid"}: a broken or forged link. Different from "late" (409). */
function InvalidPage() {
  return (
    <section className="approve-end is-invalid" role="alert">
      <span className="result-icon" aria-hidden="true">
        <Link2Off />
      </span>
      <h1 className="result-title">
        <Bi k="approve.invalid" />
      </h1>
      <p className="result-body">
        <span lang="hi">{both('approve.invalid.body').hi}</span>
        <span className="bi-en">{both('approve.invalid.body').en}</span>
      </p>
    </section>
  );
}

const isInvalid = (e: ApiError | null | undefined) => Boolean(e && (e.code === 'invalid' || e.status === 400 || e.status === 404 || e.status === 401));

export default function Approve() {
  // Every line is in both languages: wait for both tables (i18n.ts).
  useBothLangs();
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
      throw e;
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
    body = error.status === 409 || error.status === 410 ? <LatePage error={error} /> : isInvalid(error) ? <InvalidPage /> : <ErrorState error={error} onRetry={refresh} />;
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
  } else if (actErr && actErr.code === 'invalid') {
    body = <InvalidPage />;
  } else if (actErr?.isLate || (data && !data.valid) || (left !== null && left <= 0)) {
    // Our own countdown ran out (no server answer yet): say so, not "already decided".
    body = <LatePage error={actErr} timedOut={!actErr && Boolean(data?.valid) && left !== null && left <= 0} />;
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
        {fallback && (
          <p className="chip chip-warn chip-bi">
            <Bi k="console.check.template" />
          </p>
        )}
        {actErr && !actErr.isLate && (actErr.isDenied ? <DeniedNote error={actErr} /> : actErr.isRetry ? (
          <p className="warn-text" role="alert">
            <Bi k="approve.retry" />
          </p>
        ) : <ErrorState error={actErr} compact />)}
        <p className="onetap-label">
          <Bi k="approve.onetap" />
        </p>
        <div className="approve-actions">
          {/* S4: hold one second to approve (or tap, then confirm); the console's own control. */}
          <HoldToConfirm
            className="approve-hold"
            disabled={busy}
            onConfirm={() => decide('approve')}
            text={{
              idle: `${both('decide.hold.idle').hi} · ${both('decide.hold.idle').en}`,
              holding: both('decide.hold.holding').hi,
              almost: both('decide.hold.almost').hi,
              sending: `${both('decide.hold.sending').hi} · ${both('decide.hold.sending').en}`,
              done: `${both('decide.hold.done').hi} · ${both('decide.hold.done').en}`,
              hint: `${both('decide.hold.hint').hi}. ${both('decide.hold.hint').en}`,
              confirmQ: `${both('decide.confirm.q').hi} · ${both('decide.confirm.q').en}`,
              confirmYes: 'हाँ, मंज़ूर · Yes, approve',
              confirmNo: 'रद्द · Cancel',
            }}
          />
          <button type="button" className="btn btn-xl btn-decline btn-press" onClick={() => setConfirm('decline')} disabled={busy}>
            <X aria-hidden="true" />
            <span lang="hi">{both('approve.decline').hi}</span>
            <span className="btn-sub">{both('approve.decline').en}</span>
          </button>
        </div>
        <ConfirmDialog
          open={confirm !== null}
          title={confirm === 'approve' ? `${both('approve.approve').hi} · ${both('approve.approve').en}` : `${both('approve.decline').hi} · ${both('approve.decline').en}`}
          confirmLabel={confirm === 'approve' ? 'हाँ, मंज़ूर · Yes, approve' : 'हाँ, अस्वीकार · Yes, decline'}
          cancelLabel="रद्द · Cancel"
          tone={confirm === 'decline' ? 'danger' : 'accent'}
          busy={busy}
          sheet
          onCancel={() => setConfirm(null)}
          onConfirm={() => confirm && void decide(confirm).catch(() => {})}
        >
          <p>{confirm === 'approve' ? <Bi k="approve.confirm.approve" vars={{ n: a.recipients_count }} /> : <Bi k="approve.confirm.decline" />}</p>
        </ConfirmDialog>
      </article>
    );
  }

  return <div className="approve wrap-narrow">{body}</div>;
}
