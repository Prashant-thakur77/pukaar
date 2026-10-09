import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  Bot,
  Check,
  ChevronDown,
  CircleCheck,
  CircleX,
  CloudRain,
  ExternalLink,
  FileText,
  Hourglass,
  LoaderCircle,
  Scale,
  ShieldAlert,
  Users,
  Waves,
  X,
  type LucideIcon,
} from 'lucide-react';
import { api, ApiError } from '../../api';
import { ReplayChip } from '../../components/Chips';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { LevelBadge } from '../../components/Level';
import { ListenButton } from '../../components/ListenButton';
import { Snackbar, type SnackbarMsg } from '../../components/Snackbar';
import { DeniedNote, EmptyState, ErrorState, SkeletonCards } from '../../components/States';
import type { PollState } from '../../hooks/usePoll';
import { useT } from '../../i18n';
import { evidenceLines, type EvidenceLine } from '../../lib/evidence';
import { fmtAgo } from '../../lib/format';
import { levelRank } from '../../lib/levels';
import type { Alert } from '../../types';

/** Cards shown before "Show N more". */
const VISIBLE = 2;

const EV_ICON: Record<EvidenceLine['kind'], LucideIcon> = {
  river: Waves,
  rain: CloudRain,
  reports: FileText,
  agree: Users,
  impact: ShieldAlert,
  disagree: Scale,
  hold: Hourglass,
  none: CircleX,
};

type DraftKind = 'passed' | 'template' | 'escalated' | 'rejected';

/** Red only when a real model draft was rejected; the fixed templates are amber. */
function draftKind(a: Pick<Alert, 'draft_check' | 'reasoning_model'>): DraftKind {
  const reason = a.draft_check?.reason?.toLowerCase() ?? '';
  if (a.draft_check?.passed) return 'passed';
  if (reason.includes('rejected')) return 'rejected';
  if (reason.includes('escalated')) return 'escalated';
  return 'template';
}

function DraftChip({ alert }: { alert: Alert }) {
  const { t } = useT();
  const kind = draftKind(alert);
  if (kind === 'passed')
    return (
      <span className="chip chip-good" title={alert.draft_check?.reason}>
        <CircleCheck aria-hidden="true" /> {t('console.check.pass')}
      </span>
    );
  if (kind === 'rejected')
    return (
      <span className="chip chip-bad" title={alert.draft_check?.reason}>
        <CircleX aria-hidden="true" /> {t('console.check.rejected')}
      </span>
    );
  return (
    <span className="chip chip-warn" title={alert.draft_check?.reason}>
      <ShieldAlert aria-hidden="true" /> {kind === 'escalated' ? t('console.check.escalated') : t('console.check.template')}
    </span>
  );
}

function WhyLevel({ alert }: { alert: Alert }) {
  const { t, lang } = useT();
  const [open, setOpen] = useState(false);
  const lines = evidenceLines(alert.decision_trace, lang);
  const rules = alert.decision_trace?.rules_fired ?? [];
  if (!lines.length && !rules.length) return null;
  const id = `why-${alert.id}`;
  return (
    <div className="why">
      <button type="button" className="trace-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
        {t('console.why')}
        <ChevronDown aria-hidden="true" className={open ? 'rot' : ''} />
      </button>
      {open && (
        <div id={id} className="why-body">
          <ul className="why-list">
            {lines.map((l, i) => {
              const Icon = EV_ICON[l.kind];
              return (
                <li key={i} className={l.level ? `lv-${l.level}` : ''}>
                  <Icon aria-hidden="true" />
                  <span>{l.text}</span>
                </li>
              );
            })}
          </ul>
          {rules.length > 0 && (
            <p className="why-raw small muted">
              {t('console.why.rules')}: <code>{rules.join(' · ')}</code>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function DevLinkButton({ alertId }: { alertId: string }) {
  const { t } = useT();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);

  async function open() {
    setBusy(true);
    setErr(null);
    // Open the tab inside the click so pop-up blockers allow it, then point it at the link.
    const w = window.open('', '_blank');
    try {
      const res = await api.devApprovalLink(alertId);
      // The backend builds the URL from its own web_url; keep this tab's origin.
      let path = res.url;
      try {
        const u = new URL(res.url);
        path = `${u.pathname}${u.search}`;
      } catch {
        path = `/a/${res.token}`;
      }
      const url = `${window.location.origin}${path}`;
      if (w) {
        w.opener = null;
        w.location.href = url;
      } else window.location.assign(url);
    } catch (e) {
      w?.close();
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button type="button" className="btn btn-sm btn-ghost btn-press" onClick={() => void open()} disabled={busy} title={t('console.devlink.note')}>
        {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <ExternalLink aria-hidden="true" />} {t('console.devlink')}
      </button>
      {err && (
        <p className="small warn-text" role="alert">
          {err.messageEn}
        </p>
      )}
    </>
  );
}

function PendingCard({ alert, onDone, onGone, localMode }: { alert: Alert; onDone: () => void; onGone: (a: Alert) => void; localMode: boolean }) {
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
      const ae = e instanceof ApiError ? e : new ApiError(0, null);
      setConfirm(null);
      // 404: the alert is gone (e.g. the replay was reset). Drop the card.
      if (ae.status === 404) onGone(alert);
      else setErr(ae);
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
      <blockquote lang="hi" className="draft-hi" aria-label={t('console.draft.hi')}>
        {alert.text_hi}
      </blockquote>
      <p className="draft-en small">{alert.text_en}</p>
      <div className="chip-row">
        {!fallback && (
          <span className="chip">
            <Bot aria-hidden="true" /> {t('console.model')}: {alert.reasoning_model}
          </span>
        )}
        <DraftChip alert={alert} />
        <span className="chip">
          <Users aria-hidden="true" /> {t('console.dryrun', { n: alert.recipients_count })}
        </span>
      </div>
      {draftKind(alert) === 'rejected' && alert.draft_check.reason && <p className="small bad-text">{alert.draft_check.reason}</p>}
      <WhyLevel alert={alert} />
      {err &&
        (err.isDenied ? (
          <DeniedNote error={err} />
        ) : err.isRetry ? (
          <p className="warn-text" role="alert">
            {t('approve.retry')}
          </p>
        ) : err.isLate ? (
          <p className="warn-text" role="alert">
            {err.messageEn} {err.messageHi && <span lang="hi">· {err.messageHi}</span>}
          </p>
        ) : (
          <ErrorState error={err} compact />
        ))}
      <div className="pc-actions">
        <ListenButton alertId={alert.id} hasAudio={alert.has_audio} />
        {localMode && (
          <span className="pc-devlink">
            <DevLinkButton alertId={alert.id} />
          </span>
        )}
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

export function Approvals({ poll, onChange, localMode = false }: { poll: PollState<Alert[]>; onChange: () => void; localMode?: boolean }) {
  const { t, lang } = useT();
  const { data, error, loading, refresh } = poll;
  const [gone, setGone] = useState<string[]>([]);
  const [all, setAll] = useState(false);
  const [snack, setSnack] = useState<SnackbarMsg | null>(null);
  const close = useCallback(() => setSnack(null), []);

  const onGone = (a: Alert) => {
    setGone((g) => [...g, a.id]);
    setSnack({ id: Date.now(), text: t('console.pending.gone', { v: lang === 'hi' ? a.village_name_hi : a.village_name }) });
    onChange();
  };

  if (loading && !data) return <SkeletonCards n={2} />;
  if (error && !data) return <ErrorState error={error} onRetry={refresh} compact />;
  // Most severe first, then oldest first: the alert that matters most is never behind "Show more".
  const list = (data ?? [])
    .filter((a) => a.status === 'pending' && !gone.includes(a.id))
    .sort((a, b) => levelRank(b.level) - levelRank(a.level) || a.created_at.localeCompare(b.created_at));
  const shown = all ? list : list.slice(0, VISIBLE);
  const hidden = list.length - shown.length;
  return (
    <>
      {list.length === 0 ? (
        <EmptyState title={t('console.pending.empty')} icon={<CircleCheck />} />
      ) : (
        <div className="pending-list">
          {shown.map((a) => (
            <PendingCard key={a.id} alert={a} onDone={onChange} onGone={onGone} localMode={localMode} />
          ))}
          {(hidden > 0 || (all && list.length > VISIBLE)) && (
            <button type="button" className="btn btn-ghost pending-more" aria-expanded={all} onClick={() => setAll((x) => !x)}>
              <ChevronDown aria-hidden="true" className={all ? 'rot' : ''} />
              {all ? t('console.pending.fewer') : t('console.pending.more', { n: hidden })}
              {!all && (
                <span className="pm-levels" aria-hidden="true">
                  {list.slice(VISIBLE).map((a) => (
                    <i key={a.id} className={`lv-${a.level}`} />
                  ))}
                </span>
              )}
            </button>
          )}
        </div>
      )}
      <Snackbar msg={snack} onClose={close} closeLabel={t('common.close')} />
    </>
  );
}
