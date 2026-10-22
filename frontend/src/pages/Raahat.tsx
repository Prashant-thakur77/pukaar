import { useEffect, useState } from 'react';
import { CircleAlert, CircleCheck, Landmark, LoaderCircle } from 'lucide-react';
import { api, ApiError } from '../api';
import { PageBand, StatStrip } from '../components/PageBand';
import { EmptyState, ErrorState, Skeleton } from '../components/States';
import { useT } from '../i18n';
import { explorerAddress, formatTinr, readPoolOnChain, rpcTransport } from '../lib/chain';
import { fmtNumber } from '../lib/format';
import type { RaahatPool } from '../types';
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
            <PoolCard info={info} />
          )}
        </div>
      </section>
    </div>
  );
}
