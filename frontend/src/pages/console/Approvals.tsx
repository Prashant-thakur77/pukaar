import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Bot, Check, CircleCheck, CircleX, Users, X } from 'lucide-react';
import { api, ApiError } from '../../api';
import { ReplayChip } from '../../components/Chips';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { LevelBadge } from '../../components/Level';
import { ListenButton } from '../../components/ListenButton';
import { DeniedNote, EmptyState, ErrorState, SkeletonCards } from '../../components/States';
import type { PollState } from '../../hooks/usePoll';
import { useT } from '../../i18n';
import { fmtAgo } from '../../lib/format';
import type { Alert } from '../../types';

function PendingCard({ alert, onDone }: { alert: Alert; onDone: () => void }) {
  const { t, lang } = useT();
  const [confirm, setConfirm] = useState<'approve' | 'decline' | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const fallback = alert.reasoning_model === 'rule-fallback';

  async function act() {
    if (!confirm) return;
    setBusy(true);
    setErr(null);
    try {
      if (confirm === 'approve') await api.approve(alert.id);
      else await api.decline(alert.id, reason.trim() || undefined);
      setConfirm(null);
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
      setConfirm(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className={`pending-card lv-${alert.level}`}>
      <header className="pc-head">
        <div className="pc-level">
          <LevelBadge level={alert.previous_level} size="sm" />
          <ArrowRight aria-hidden="true" className="pc-arrow" />
          <LevelBadge level={alert.level} size="md" />
        </div>
        <span className="small muted">{fmtAgo(alert.created_at, lang)}</span>
      </header>
      <h3 className="pc-village">
        <Link to={`/village/${alert.village_id}`}>
          <span lang="hi">{alert.village_name_hi}</span> · {alert.village_name}
        </Link>
        {alert.replay && <ReplayChip />}
      </h3>
      <div className="pc-drafts">
        <div>
          <p className="field-label">{t('console.draft.hi')}</p>
          <blockquote lang="hi" className="draft-hi">
            {alert.text_hi}
          </blockquote>
        </div>
        <div>
          <p className="field-label">{t('console.draft.en')}</p>
          <p className="draft-en">{alert.text_en}</p>
        </div>
      </div>
      {alert.reason_en && (
        <p className="pc-reason">
          <strong>{t('console.reason')}:</strong> {alert.reason_en}
        </p>
      )}
      <div className="chip-row">
        <span className={`chip ${fallback ? 'chip-warn' : ''}`}>
          <Bot aria-hidden="true" /> {t('console.model')}: {fallback ? t('console.model.fallback') : alert.reasoning_model}
        </span>
        <span className={`chip ${alert.draft_check?.passed ? 'chip-good' : 'chip-bad'}`} title={alert.draft_check?.reason}>
          {alert.draft_check?.passed ? <CircleCheck aria-hidden="true" /> : <CircleX aria-hidden="true" />}
          {alert.draft_check?.passed ? t('console.check.pass') : t('console.check.fail')}
        </span>
        <span className="chip">
          <Users aria-hidden="true" /> {t('console.dryrun', { n: alert.recipients_count })}
        </span>
      </div>
      {alert.draft_check && !alert.draft_check.passed && alert.draft_check.reason && <p className="small bad-text">{alert.draft_check.reason}</p>}
      {err && (err.isDenied ? <DeniedNote error={err} /> : err.isRetry ? (
        <p className="warn-text" role="alert">
          {t('approve.retry')}
        </p>
      ) : err.isLate ? (
        <p className="warn-text" role="alert">
          {err.messageEn} {err.messageHi && <span lang="hi">· {err.messageHi}</span>}
        </p>
      ) : <ErrorState error={err} compact />)}
      <div className="pc-actions">
        <ListenButton alertId={alert.id} hasAudio={alert.has_audio} />
        <span className="spacer" />
        <button type="button" className="btn btn-decline btn-press" onClick={() => setConfirm('decline')} disabled={busy}>
          <X aria-hidden="true" /> {t('approve.decline')}
        </button>
        <button type="button" className="btn btn-approve btn-press" onClick={() => setConfirm('approve')} disabled={busy}>
          <Check aria-hidden="true" /> {t('approve.approve')}
        </button>
      </div>
      <ConfirmDialog
        open={confirm !== null}
        title={`${confirm === 'approve' ? t('approve.approve') : t('approve.decline')}: ${alert.village_name}`}
        confirmLabel={confirm === 'approve' ? t('approve.approve') : t('approve.decline')}
        cancelLabel={t('common.cancel')}
        tone={confirm === 'decline' ? 'danger' : 'accent'}
        busy={busy}
        onCancel={() => setConfirm(null)}
        onConfirm={() => void act()}
      >
        <p>{confirm === 'approve' ? t('approve.confirm.approve', { n: alert.recipients_count }) : t('approve.confirm.decline')}</p>
        {confirm === 'decline' && (
          <label className="field">
            <span className="field-label">{t('console.decline.reason')}</span>
            <input className="input-lg" value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
        )}
      </ConfirmDialog>
    </article>
  );
}

export function Approvals({ poll, onChange }: { poll: PollState<Alert[]>; onChange: () => void }) {
  const { t } = useT();
  const { data, error, loading, refresh } = poll;
  if (loading && !data) return <SkeletonCards n={2} />;
  if (error && !data) return <ErrorState error={error} onRetry={refresh} compact />;
  if (!data?.length) return <EmptyState title={t('console.pending.empty')} icon={<CircleCheck />} />;
  return (
    <div className="pending-list">
      {data.map((a) => (
        <PendingCard key={a.id} alert={a} onDone={onChange} />
      ))}
    </div>
  );
}
