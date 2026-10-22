import { useCallback, useEffect, useState } from 'react';
import { CircleCheck, HandCoins } from 'lucide-react';
import { api, ApiError } from '../../api';
import { ReplayChip } from '../../components/Chips';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { EmptyState, ErrorState, Skeleton } from '../../components/States';
import { usePoll } from '../../hooks/usePoll';
import { useT } from '../../i18n';
import { explorerTx } from '../../lib/chain-links';
import { CHANNELS } from '../../lib/live';
import { inr } from '../../lib/ledger';
import type { RaahatLedgerItem, RaahatRelief, Village } from '../../types';
import { AttestControls } from './RaahatAttest';
import '../../raahat.css';
import { raahatApi } from '../../lib/raahatApi';
import '../../i18n-raahat';

type Tier = RaahatRelief['tiers'][number];

/** One alert's two tiers: amount, eligibility (reason codes in words) and the one-tap Release. */
function ReliefCard({ item, village, onReleased }: { item: RaahatLedgerItem; village: Village | undefined; onReleased: () => void }) {
  const { t, lang } = useT();
  const [relief, setRelief] = useState<RaahatRelief | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [confirm, setConfirm] = useState<Tier | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const load = useCallback(
    () =>
      raahatApi.raahatRelief(item.alert_id).then(
        (r) => {
          setRelief(r);
          setError(null);
        },
        (e: ApiError) => setError(e),
      ),
    [item.alert_id],
  );
  useEffect(() => {
    void load();
  }, [load, item.releases.length]);

  const name = village ? (lang === 'hi' ? village.name_hi : village.name) : item.village_id;
  const release = async (tier: Tier) => {
    setBusy(true);
    setNote(null);
    try {
      await raahatApi.raahatRelease(item.alert_id, tier.tier);
    } catch (e) {
      const err = e as ApiError;
      const code = (err.detail as { code?: string } | null)?.code;
      setNote(code && code !== 'chain_failed' ? t(`raahat.why.${code}` as never) : t('raahat.relief.failed'));
    } finally {
      setBusy(false);
      setConfirm(null);
      void load();
      onReleased(); // the pool balance and the ledger change with a release: re-read them now
    }
  };

  return (
    <li className="relief-card">
      <div className="ac-top">
        <strong>{name}</strong>
        <span className="chip">{t(`raahat.level.${item.level}` as never)}</span>
        {item.exercise && <ReplayChip />}
      </div>
      {error && <ErrorState error={error} compact />}
      {!relief && !error && <Skeleton lines={2} />}
      {relief?.tiers.map((tier) => (
        <div key={tier.tier} className="relief-tier">
          <p className="small">
            <strong>{t(tier.tier === 1 ? 'raahat.step.tier1' : 'raahat.step.tier2')}</strong>
            {tier.households != null && tier.amount_wei && tier.total_wei && (
              <>
                {' · '}
                {t('raahat.relief.tier', { t: tier.tier, n: tier.households, a: inr(tier.amount_wei, lang), v: inr(tier.total_wei, lang) })}
              </>
            )}
          </p>
          {tier.release?.state === 'sent' ? (
            <p className="small ok-text">
              <CircleCheck aria-hidden="true" className="ok-icon" /> {t('raahat.relief.released')}
              {tier.release.tx && (
                <>
                  {' · '}
                  <a className="link mono" href={explorerTx(item.explorer, tier.release.tx) ?? undefined} target="_blank" rel="noreferrer">
                    {tier.release.tx.slice(0, 10)}…
                  </a>
                </>
              )}
            </p>
          ) : tier.release?.state === 'pending' ? (
            <p className="small">{t('raahat.receipt.pending')}</p>
          ) : tier.eligible ? (
            <button type="button" className="btn btn-accent btn-sm" onClick={() => setConfirm(tier)}>
              <HandCoins aria-hidden="true" /> {t('raahat.relief.release')}
            </button>
          ) : (
            <ul className="chips-row">
              {tier.why.map((w) => (
                <li key={w} className="chip chip-muted">
                  {t(`raahat.why.${w}` as never)}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
      {relief && <AttestControls alertId={item.alert_id} villageId={item.village_id} role="officer" onChange={() => void load()} />}
      {note && (
        <p className="small bad-text" role="alert">
          {note}
        </p>
      )}
      <ConfirmDialog
        open={confirm !== null}
        title={t('raahat.relief.title')}
        confirmLabel={t('raahat.relief.release')}
        cancelLabel={t('common.cancel')}
        busy={busy}
        onCancel={() => setConfirm(null)}
        onConfirm={() => confirm && void release(confirm)}
      >
        {confirm && (
          <>
            <p>
              {t('raahat.relief.confirm', { village: name, n: confirm.households ?? 0, v: inr(confirm.total_wei ?? '0', lang) })}
            </p>
            <p className="small muted">{t('raahat.relief.confirm.body')}</p>
            <p className="small muted">{t('raahat.illustrative')}</p>
          </>
        )}
      </ConfirmDialog>
    </li>
  );
}

/** Officer console: alerts recorded on chain with their relief tiers (PLAN.md Step 2). */
export function Relief({ villages }: { villages: Village[] }) {
  const { t, lang } = useT();
  const ledger = usePoll(() => raahatApi.raahatLedger(), [], 30000, { live: [CHANNELS.raahat, CHANNELS.alerts] });
  const pool = usePoll(() => raahatApi.raahatPool(), [], 60000, { live: [CHANNELS.raahat] });
  // Names: the console's list when it has them, else this panel's own (it can render before the console's arrives).
  const own = usePoll(() => api.villages(), [], 300000);
  const items = (ledger.data?.items ?? []).filter((i) => i.anchor_state === 'sent').slice(0, 8);
  const byId = new Map([...(own.data ?? []), ...villages].map((v) => [v.id, v]));
  const refresh = () => {
    void ledger.refresh();
    void pool.refresh();
  };
  return (
    <div className="relief">
      <p className="small muted">{t('raahat.relief.lead')}</p>
      <p className="small caveat">{t('raahat.illustrative')}</p>
      {pool.data?.pool && <p className="small">{t('raahat.relief.pool', { v: inr(pool.data.pool.balance_wei, lang) })}</p>}
      {ledger.error && !ledger.data ? (
        <ErrorState error={ledger.error} compact />
      ) : !ledger.data ? (
        <Skeleton lines={3} />
      ) : items.length === 0 ? (
        <EmptyState title={t('raahat.relief.none')} icon={<HandCoins />} />
      ) : (
        <ul className="relief-list">
          {items.map((it) => (
            <ReliefCard key={it.alert_id} item={it} village={byId.get(it.village_id)} onReleased={refresh} />
          ))}
        </ul>
      )}
    </div>
  );
}
