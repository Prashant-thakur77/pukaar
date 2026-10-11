import { enumLabels, useT } from '../i18n';
import type { AlertStatus, ReportState } from '../types';

const GOOD_ALERT: AlertStatus[] = ['approved', 'delivering', 'delivered', 'closed'];
const BAD_ALERT: AlertStatus[] = ['declined', 'expired', 'auto_sent_unapproved', 'failsafe'];

export function AlertStatusChip({ status }: { status: AlertStatus }) {
  const { pick } = useT();
  const tone = GOOD_ALERT.includes(status) ? 'good' : BAD_ALERT.includes(status) ? 'bad' : 'pending';
  return <span className={`chip chip-${tone}`}>{pick(enumLabels.alertStatus[status])}</span>;
}

export function ReportStateChip({ state }: { state: ReportState }) {
  const { pick } = useT();
  const tone = ['verified', 'verified_auto', 'reviewed', 'actioned', 'resolved'].includes(state) ? 'good' : state === 'false' || state === 'duplicate' ? 'muted' : 'pending';
  return <span className={`chip chip-${tone}`}>{pick(enumLabels.reportState[state])}</span>;
}

/** Replay data is marked with a small tracked label, not a pill. */
export function ReplayChip() {
  const { t } = useT();
  return (
    <span className="replay-tag" title={t('shell.replay.chip')}>
      {t('common.replay')}
    </span>
  );
}

/** Approval, delivered and acknowledged counts as one plain line, not a row of chips. */
export function DeliveryChips({ approved, delivered, acked, status }: { approved: boolean; delivered: number; acked: number; status?: AlertStatus }) {
  const { t } = useT();
  // "Auto-sent, unapproved" already says it is unapproved, so the line does not repeat it.
  const word = approved ? t('live.chip.approved') : status === 'failsafe' ? t('live.chip.unapproved') : null;
  return (
    <span className="meta-line">
      {word && <span className={approved ? 'ml-good' : 'ml-bad'}>{word}</span>}
      <span>{t('live.chip.delivered', { n: delivered })}</span>
      <span>{t('live.chip.acked', { n: acked })}</span>
    </span>
  );
}
