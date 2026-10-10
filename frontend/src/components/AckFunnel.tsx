import { BellRing, CheckCheck, FileText, Send } from 'lucide-react';
import { useT, type Key } from '../i18n';
import type { PublicAlert } from '../types';

interface Step {
  key: Key;
  icon: typeof Send;
  value: number;
}

/**
 * From draft to a villager's "मिल गया": how far the recent alerts got.
 * Counts come straight from the public overview; nothing is estimated.
 */
export function AckFunnel({ alerts }: { alerts: PublicAlert[] }) {
  const { t } = useT();
  const drafted = alerts.length;
  const approved = alerts.filter((a) => a.approved).length;
  const delivered = alerts.reduce((n, a) => n + a.delivered_count, 0);
  const acked = alerts.reduce((n, a) => n + a.acknowledged_count, 0);
  // Replay alerts go to the stub channel only, so no phone could ever confirm them:
  // the rate counts live alerts, and an all-replay list says so instead of "0%".
  const replayed = alerts.filter((a) => a.replay).length;
  const allReplay = drafted > 0 && replayed === drafted;
  const live = alerts.filter((a) => !a.replay);
  const liveDelivered = live.reduce((n, a) => n + a.delivered_count, 0);
  const liveAcked = live.reduce((n, a) => n + a.acknowledged_count, 0);

  const alertSteps: Step[] = [
    { key: 'funnel.drafted', icon: FileText, value: drafted },
    { key: 'funnel.approved', icon: CheckCheck, value: approved },
  ];
  const phoneSteps: Step[] = [
    { key: allReplay ? 'funnel.delivered.replay' : 'funnel.delivered', icon: Send, value: delivered },
    { key: 'funnel.acked', icon: BellRing, value: acked },
  ];
  const ackRate = liveDelivered > 0 ? Math.round((liveAcked / liveDelivered) * 100) : null;

  const row = (s: Step, max: number) => (
    <li key={s.key} className="fn-step">
      <span className="fn-icon" aria-hidden="true">
        <s.icon />
      </span>
      <span className="fn-label">{t(s.key)}</span>
      <span className="fn-bar" aria-hidden="true">
        <i style={{ width: `${max > 0 ? Math.max(4, (s.value / max) * 100) : 0}%` }} />
      </span>
      <span className="fn-num">{s.value}</span>
    </li>
  );

  return (
    <section className="funnel card" aria-labelledby="funnel-h">
      <div className="fn-head">
        <h2 id="funnel-h" className="h-sec">
          {t('funnel.title')}
        </h2>
        <p className="small muted">
          {t('funnel.scope', { n: String(drafted) })}
          {replayed > 0 && ` · ${t('funnel.replay', { n: String(replayed) })}`}
        </p>
      </div>
      <div className="fn-cols">
        <div>
          <p className="fn-group">{t('funnel.alerts')}</p>
          <ol className="fn-list">{alertSteps.map((s) => row(s, drafted))}</ol>
        </div>
        <div>
          <p className="fn-group">{t('funnel.phones')}</p>
          <ol className="fn-list">{phoneSteps.map((s) => row(s, delivered))}</ol>
        </div>
      </div>
      <p className="fn-rate">
        {ackRate !== null
          ? t('funnel.rate', { pct: String(ackRate) })
          : replayed > 0
            ? t('funnel.rate.replay')
            : t('funnel.rate.none')}
      </p>
    </section>
  );
}
