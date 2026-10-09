import { CircleCheck, History, PhoneCall, Send, ShieldAlert, ShieldCheck } from 'lucide-react';
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

export function ReplayChip() {
  const { t } = useT();
  return (
    <span className="chip chip-replay" title={t('shell.replay.chip')}>
      <History aria-hidden="true" /> {t('common.replay')}
    </span>
  );
}

/** Approved / delivered / acknowledged trio used on public and console lists. */
export function DeliveryChips({ approved, delivered, acked, status }: { approved: boolean; delivered: number; acked: number; status?: AlertStatus }) {
  const { t } = useT();
  return (
    <span className="chip-row">
      {approved ? (
        <span className="chip chip-good">
          <ShieldCheck aria-hidden="true" /> {t('live.chip.approved')}
        </span>
      ) : status === 'auto_sent_unapproved' || status === 'failsafe' ? (
        <span className="chip chip-bad">
          <ShieldAlert aria-hidden="true" /> {t('live.chip.unapproved')}
        </span>
      ) : null}
      <span className="chip">
        <Send aria-hidden="true" /> {t('live.chip.delivered', { n: delivered })}
      </span>
      <span className="chip">
        {acked > 0 ? <CircleCheck aria-hidden="true" /> : <PhoneCall aria-hidden="true" />} {t('live.chip.acked', { n: acked })}
      </span>
    </span>
  );
}
