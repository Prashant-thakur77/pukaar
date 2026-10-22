// Pukaar Raahat on the existing pages (landing, how, village). No chain library here: these read the API's
// ledger and link to /raahat, where the browser checks the chain itself.
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, CircleCheck, CircleDashed, HandCoins } from 'lucide-react';
import { useT } from '../i18n';
import { fmtNumber } from '../lib/format';
import { inr, ledgerTotals } from '../lib/ledger';
import type { RaahatLedger, RaahatPool } from '../types';
import '../raahat.css';
import { raahatApi } from '../lib/raahatApi';
import '../i18n-raahat';

function useRaahat(villageId = '') {
  const [ledger, setLedger] = useState<RaahatLedger | null>(null);
  const [pool, setPool] = useState<RaahatPool | null>(null);
  useEffect(() => {
    let live = true;
    raahatApi.raahatLedger(villageId).then((l) => live && setLedger(l), () => undefined);
    raahatApi.raahatPool().then((p) => live && setPool(p), () => undefined);
    return () => {
      live = false;
    };
  }, [villageId]);
  return { ledger, pool };
}

/** Landing: "relief reached ₹X / N households", live and replay apart, and the one-line reason for a chain. */
export function RaahatCounter() {
  const { t, lang } = useT();
  const { ledger, pool } = useRaahat();
  if (!pool?.configured || !ledger) return null;
  const totals = ledgerTotals(ledger.items);
  return (
    <div className="raahat-counter">
      {totals.live.releases > 0 && (
        <p className="raahat-counter-num">
          <HandCoins aria-hidden="true" /> {t('raahat.landing.live', { v: inr(totals.live.wei, lang), n: fmtNumber(totals.live.households, lang) })}
        </p>
      )}
      {totals.exercise.releases > 0 && (
        <p className={totals.live.releases > 0 ? 'small' : 'raahat-counter-num'}>
          {totals.live.releases === 0 && <HandCoins aria-hidden="true" />}{' '}
          {t('raahat.landing.exercise', { v: inr(totals.exercise.wei, lang), n: fmtNumber(totals.exercise.households, lang) })}
        </p>
      )}
      <p className="small">
        {t('raahat.landing.why')}{' '}
        <Link to="/raahat">
          {t('raahat.landing.link')} <ArrowRight aria-hidden="true" />
        </Link>
      </p>
    </div>
  );
}

const FLOW = ['forecast', 'approve', 'anchor', 'anticipatory', 'confirm', 'receipts'] as const;

/** How: where the money goes, step by step (PLAN.md §2, drawn). */
export function RaahatFlow() {
  const { t } = useT();
  return (
    <section className="how-band how-cream raahat-flow-band" aria-labelledby="how-money-h">
      <div className="wrap-wide">
        <p className="how-eyebrow">{t('raahat.eyebrow')}</p>
        <h2 id="how-money-h" className="how-h">
          {t('raahat.how.title')}
        </h2>
        <p>{t('raahat.how.lead')}</p>
        <ol className="raahat-flow">
          {FLOW.map((k, i) => (
            <li key={k} className={`rf-step rf-${k}`}>
              <span className="rf-num" aria-hidden="true">
                {i + 1}
              </span>
              <strong>{t(`raahat.how.${k}` as never)}</strong>
              <span className="small">{t(`raahat.how.${k}.body` as never)}</span>
            </li>
          ))}
        </ol>
        <p className="small">
          {t('raahat.how.not')} <Link to="/raahat">{t('raahat.landing.link')}</Link>
        </p>
        <p className="small caveat">{t('raahat.illustrative')}</p>
      </div>
    </section>
  );
}

/** Village page: this village's rule, its last release and how many households have a receipt. */
export function RaahatVillage({ villageId }: { villageId: string }) {
  const { t, lang } = useT();
  const { ledger, pool } = useRaahat(villageId);
  if (!pool?.configured) return null;
  const rule = pool.rule;
  const last = ledger?.items.find((i) => i.releases.some((r) => r.state === 'sent'));
  const paid = last ? Math.max(...last.releases.filter((r) => r.state === 'sent').map((r) => r.households ?? 0)) : 0;
  return (
    <section className="card raahat-village" aria-labelledby="rv-h">
      <h2 id="rv-h" className="h-sec">
        <HandCoins aria-hidden="true" /> {t('raahat.village.title')}
      </h2>
      {rule && (
        <p>{t('raahat.rule.line', { a: inr(rule.amount_anticipatory_wei, lang), c: inr(rule.amount_confirmed_wei, lang), h: rule.cooldown_hours })}</p>
      )}
      {last ? (
        <ul className="tick-list">
          {last.releases
            .filter((r) => r.state === 'sent')
            .map((r) => (
              <li key={r.tier}>
                <CircleCheck aria-hidden="true" className="ok-icon" /> {t(r.tier === 1 ? 'raahat.step.tier1' : 'raahat.step.tier2')}:{' '}
                {t('raahat.step.released', { n: r.households ?? 0, v: inr(r.total_wei ?? '0', lang) })}
                {last.exercise ? ` (${t('common.replay')})` : ''}
              </li>
            ))}
          <li>
            <CircleDashed aria-hidden="true" /> {t('raahat.receipts.count', { n: last.receipts ?? 0, t: paid })}
          </li>
        </ul>
      ) : (
        <p className="small muted">{t('raahat.village.none')}</p>
      )}
      <p className="small caveat">{t('raahat.illustrative')}</p>
      <Link to={last ? `/raahat?alert=${last.alert_id}` : '/raahat'} className="link">
        {t('raahat.landing.link')} <ArrowRight aria-hidden="true" />
      </Link>
    </section>
  );
}
