import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ChevronDown, CircleAlert, CircleCheck, CircleDashed, CircleX, Landmark, LoaderCircle, ScrollText } from 'lucide-react';
import { api, ApiError } from '../api';
import { ChainReceiptLazy } from '../components/ChainReceiptLazy';
import { ReplayChip } from '../components/Chips';
import { PageBand, StatStrip } from '../components/PageBand';
import { EmptyState, ErrorState, Skeleton } from '../components/States';
import { usePoll } from '../hooks/usePoll';
import { useT } from '../i18n';
import { explorerAddress, explorerTx, formatTinr, readPoolOnChain, rpcTransport } from '../lib/chain';
import { fmtDate, fmtNumber, fmtTime } from '../lib/format';
import { inr, ledgerTotals, timelineSteps, type LedgerStep } from '../lib/ledger';
import { CHANNELS } from '../lib/live';
import type { RaahatLedgerItem, RaahatPool, RaahatRule, Village } from '../types';
import '../raahat.css';

type Check = { state: 'checking' } | { state: 'ok'; wei: bigint } | { state: 'failed' };

/** The pool as the browser reads it from the chain itself, so nobody has to trust our API for the number. */
function useBrowserCheck(info: RaahatPool | null | undefined): Check | null {
  const where = info?.configured && info.addresses && info.chain_id && info.public_rpc_url ? info : null;
  const key = where ? `${where.chain_id}:${where.addresses!.pool}:${where.block ?? ''}` : '';
  // The answer is kept with the key it was read for: a new chain, pool or block means "checking" again.
  const [done, setDone] = useState<{ key: string; check: Check } | null>(null);
  useEffect(() => {
    if (!where) return;
    let live = true;
    readPoolOnChain(
      { chainId: where.chain_id!, token: where.addresses!.test_inr, pool: where.addresses!.pool },
      rpcTransport(where.public_rpc_url!),
    ).then(
      (wei) => live && setDone({ key, check: { state: 'ok', wei } }),
      () => live && setDone({ key, check: { state: 'failed' } }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-check when the chain, pool or block changes
  }, [key]);
  if (!where) return null;
  return done?.key === key ? done.check : { state: 'checking' };
}

function AddressLink({ explorer, address, label }: { explorer?: string | null; address: string; label: string }) {
  const { t } = useT();
  const href = explorerAddress(explorer, address);
  return (
    <div className="kv">
      <dt>{label}</dt>
      <dd>
        {href ? (
          <a href={href} target="_blank" rel="noreferrer" className="mono break">
            {address}
          </a>
        ) : (
          <>
            <span className="mono break">{address}</span> <span className="small muted">({t('raahat.explorer.none')})</span>
          </>
        )}
      </dd>
    </div>
  );
}

function PoolCard({ info }: { info: RaahatPool }) {
  const { t, lang } = useT();
  const check = useBrowserCheck(info);
  const serverWei = info.reachable ? info.pool?.balance_wei : undefined;
  const shownWei = serverWei ?? (check?.state === 'ok' ? check.wei.toString() : undefined);
  const symbol = info.token?.symbol ?? 'tINR';
  return (
    <div className="card raahat-pool">
      <h2 className="h-sec">
        <Landmark aria-hidden="true" /> {t('raahat.pool')}
      </h2>
      {!info.reachable && <p className="small">{t('raahat.unreachable')}</p>}
      {shownWei !== undefined && (
        <StatStrip
          stats={[{ key: 'bal', value: `${formatTinr(shownWei, lang)} ${symbol}`, label: t('raahat.pool.balance') }]}
        />
      )}
      {check && (
        <p className="small raahat-check" role="status">
          {check.state === 'checking' && (
            <>
              <LoaderCircle aria-hidden="true" className="spin" /> {t('raahat.verify.checking')}
            </>
          )}
          {check.state === 'ok' && (serverWei === undefined || BigInt(serverWei) === check.wei) && (
            <>
              <CircleCheck aria-hidden="true" className="ok-icon" /> {t('raahat.verify.ok')}
            </>
          )}
          {check.state === 'ok' && serverWei !== undefined && BigInt(serverWei) !== check.wei && (
            <>
              <CircleAlert aria-hidden="true" /> {t('raahat.verify.mismatch', { v: `${formatTinr(check.wei, lang)} ${symbol}` })}
            </>
          )}
          {check.state === 'failed' && (
            <>
              <CircleAlert aria-hidden="true" /> {t('raahat.verify.failed')}
            </>
          )}
        </p>
      )}
      <p className="small muted">{t('raahat.pool.test')}</p>
      {!info.pool_is_contract && <p className="small caveat">{t('raahat.pool.placeholder')}</p>}
      <dl className="kv-list">
        <div className="kv">
          <dt>{t('raahat.network')}</dt>
          <dd>
            {info.network} ({info.chain_id}){info.block != null && <> · {t('raahat.block', { n: fmtNumber(info.block, lang) })}</>}
          </dd>
        </div>
        {info.addresses && (
          <>
            <AddressLink explorer={info.explorer} address={info.addresses.pool} label={t('raahat.address.pool')} />
            <AddressLink explorer={info.explorer} address={info.addresses.test_inr} label={`${t('raahat.token')} (${symbol})`} />
          </>
        )}
      </dl>
    </div>
  );
}

function RuleCard({ rule }: { rule: RaahatRule }) {
  const { t, lang } = useT();
  return (
    <div className="card raahat-rule">
      <h2 className="h-sec">
        <ScrollText aria-hidden="true" /> {t('raahat.rule.title')}
      </h2>
      <p className="raahat-rule-line" lang={lang}>
        {t('raahat.rule.line', { a: inr(rule.amount_anticipatory_wei, lang), c: inr(rule.amount_confirmed_wei, lang), h: rule.cooldown_hours })}
      </p>
      <p className="small">
        {rule.sealed
          ? t('raahat.rule.sealed', { d: fmtDate(new Date(rule.sealed_at * 1000).toISOString(), lang) })
          : t('raahat.rule.unsealed')}
      </p>
      <p className="small caveat">{t('raahat.illustrative')}</p>
    </div>
  );
}

const STEP_ICON = { done: CircleCheck, waiting: CircleDashed, failed: CircleX } as const;

function Step({ step, explorer }: { step: LedgerStep; explorer: string | null }) {
  const { t, lang } = useT();
  const Icon = STEP_ICON[step.state];
  const href = step.tx ? explorerTx(explorer, step.tx) : null;
  let detail = '';
  if (step.state === 'failed') detail = t('raahat.step.failed');
  else if (step.state === 'waiting') detail = t('raahat.step.waiting');
  else if (step.key === 'heard') detail = t('raahat.step.heard.counts', { a: step.acknowledged ?? 0, d: step.delivered ?? 0 });
  else if ((step.key === 'tier1' || step.key === 'tier2') && step.totalWei)
    detail = t('raahat.step.released', { n: step.households ?? 0, v: inr(step.totalWei, lang) });
  return (
    <li className={`lstep is-${step.state}`}>
      <Icon aria-hidden="true" />
      <span className="lstep-name">{t(`raahat.step.${step.key}` as never)}</span>
      <span className="small muted">{detail}</span>
      {step.tx &&
        (href ? (
          <a className="link mono small" href={href} target="_blank" rel="noreferrer">
            {step.tx.slice(0, 10)}… ↗
          </a>
        ) : (
          <span className="mono small">{step.tx.slice(0, 10)}…</span>
        ))}
    </li>
  );
}

function LedgerRow({ item, village, focus }: { item: RaahatLedgerItem; village?: Village; focus: boolean }) {
  const { t, lang } = useT();
  const [open, setOpen] = useState(focus);
  const name = village ? (lang === 'hi' ? village.name_hi : village.name) : item.village_id;
  return (
    <li className={`ledger-row${focus ? ' is-focus' : ''}`} id={`a-${item.alert_id}`}>
      <div className="ac-top">
        <strong>{name}</strong>
        <span className="chip">{t(`raahat.level.${item.level}` as never)}</span>
        {item.exercise && <ReplayChip />}
        <span className="small muted">{fmtTime(item.anchored_at, lang)}</span>
      </div>
      <ol className="ledger-steps">
        {timelineSteps(item).map((s) => (
          <Step key={s.key} step={s} explorer={item.explorer} />
        ))}
      </ol>
      {item.anchor_state === 'sent' && (
        <>
          <button type="button" className="btn btn-sm btn-ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            <ChevronDown aria-hidden="true" className={open ? 'rot' : ''} /> {t('raahat.receipt.toggle')}
          </button>
          {open && <ChainReceiptLazy alertId={item.alert_id} />}
        </>
      )}
    </li>
  );
}

function Ledger() {
  const { t, lang } = useT();
  const [params] = useSearchParams();
  const focus = params.get('alert') ?? '';
  const ledger = usePoll(() => api.raahatLedger(), [], 30000, { live: [CHANNELS.raahat, CHANNELS.alerts, CHANNELS.deliveries] });
  const villages = usePoll(() => api.villages(), [], 300000);
  const byId = new Map((villages.data ?? []).map((v) => [v.id, v]));
  const items = ledger.data?.items ?? [];
  const totals = ledgerTotals(items);
  useEffect(() => {
    if (focus && items.some((i) => i.alert_id === focus)) document.getElementById(`a-${focus}`)?.scrollIntoView({ block: 'center' });
  }, [focus, items.length]); // eslint-disable-line react-hooks/exhaustive-deps -- once the row exists
  return (
    <section className="band band-paper" aria-labelledby="ledger-h">
      <div className="wrap">
        <h2 id="ledger-h" className="h-sec">
          <ScrollText aria-hidden="true" /> {t('raahat.ledger.title')}
        </h2>
        <p className="small muted">{t('raahat.ledger.lead')}</p>
        {ledger.error && !ledger.data ? (
          <ErrorState error={ledger.error} compact />
        ) : !ledger.data ? (
          <Skeleton lines={4} />
        ) : items.length === 0 ? (
          <EmptyState title={t('raahat.ledger.none')} icon={<ScrollText />} />
        ) : (
          <>
            <ul className="ledger-totals small">
              <li>{t('raahat.ledger.total.live', { v: fmtNumber(Number(totals.live.wei / 10n ** 18n), lang), n: totals.live.households })}</li>
              <li>{t('raahat.ledger.total.exercise', { v: fmtNumber(Number(totals.exercise.wei / 10n ** 18n), lang), n: totals.exercise.households })}</li>
            </ul>
            <p className="small caveat">{t('raahat.illustrative')}</p>
            <ul className="ledger-list">
              {items.map((it) => (
                <LedgerRow key={it.alert_id} item={it} village={byId.get(it.village_id)} focus={it.alert_id === focus} />
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}

export default function Raahat() {
  const { t } = useT();
  const [info, setInfo] = useState<RaahatPool | null | undefined>(undefined);
  const [error, setError] = useState<ApiError | null>(null);
  const load = () =>
    api.raahatPool().then(
      (got) => {
        setError(null);
        setInfo(got);
      },
      (e: ApiError) => {
        setError(e);
        setInfo(null);
      },
    );
  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="raahat">
      <PageBand eyebrow={t('raahat.eyebrow')} title={t('raahat.title')} lead={t('raahat.lead')} />
      <section className="band band-paper" aria-label={t('raahat.pool')}>
        <div className="wrap">
          {info === undefined ? (
            <Skeleton lines={4} />
          ) : error ? (
            <ErrorState error={error} onRetry={() => void load()} />
          ) : !info?.configured ? (
            <EmptyState title={t('raahat.none.title')} body={t('raahat.none.body')} icon={<Landmark />} />
          ) : (
            <div className="raahat-top">
              <PoolCard info={info} />
              {info.rule && <RuleCard rule={info.rule} />}
            </div>
          )}
        </div>
      </section>
      {info?.configured && <Ledger />}
    </div>
  );
}
