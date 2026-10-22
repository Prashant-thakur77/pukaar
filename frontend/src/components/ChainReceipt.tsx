import { useEffect, useState } from 'react';
import { CircleAlert, CircleCheck, Link2, LoaderCircle, ShieldCheck } from 'lucide-react';
import { api, ApiError } from '../api';
import { useT } from '../i18n';
import { alertKey, explorerTx, readAnchor, rpcTransport, txMined, verifyCapHash } from '../lib/chain';
import { fmtNumber, fmtTime } from '../lib/format';
import type { RaahatAnchor } from '../types';
import { ReplayChip } from './Chips';
import '../raahat.css';

type Verify =
  | { state: 'idle' }
  | { state: 'running' }
  | { state: 'done'; ok: boolean; onChain: string; computed: string }
  | { state: 'error'; message: string };

const short = (h: string) => `${h.slice(0, 10)}…${h.slice(-6)}`;

function TxLink({ explorer, hash }: { explorer: string | null; hash: string }) {
  const href = explorerTx(explorer, hash);
  return href ? (
    <a href={href} target="_blank" rel="noreferrer" className="mono" title={hash}>
      {short(hash)} ↗
    </a>
  ) : (
    <span className="mono" title={hash}>
      {short(hash)}
    </span>
  );
}

/** When the anchor transaction was mined, read in the browser from the chain itself. */
function useMined(a: RaahatAnchor | null) {
  const [mined, setMined] = useState<{ tx: string; block: bigint; at: number } | null>(null);
  const tx = a?.state === 'sent' ? a.tx : null;
  const rpc = a?.public_rpc_url ?? null;
  useEffect(() => {
    if (!tx || !rpc) return;
    let live = true;
    txMined(tx, rpcTransport(rpc)).then(
      (m) => live && m && setMined({ tx, ...m }),
      () => undefined, // the receipt card still shows the hash; the time simply stays unknown
    );
    return () => {
      live = false;
    };
  }, [tx, rpc]);
  return mined && mined.tx === tx ? mined : null;
}

/**
 * The chain receipt of one alert (PLAN.md Step 1): transaction, block and time, the exercise flag, the
 * outcome, and "re-verify": the browser reads capHash from the AlertRegistry, fetches the CAP XML from the
 * URL recorded on chain and hashes it itself. Nothing here trusts the API for the answer.
 * An alert that was never anchored (Raahat off, or older than it) gets one line saying so.
 */
export default function ChainReceipt({ alertId }: { alertId: string }) {
  const { t, lang } = useT();
  const [a, setA] = useState<RaahatAnchor | null>(null);
  const [missing, setMissing] = useState(false);
  const [verify, setVerify] = useState<Verify>({ state: 'idle' });
  useEffect(() => {
    let live = true;
    api.raahatAnchor(alertId).then(
      (got) => live && setA(got),
      (e: ApiError) => live && e.status === 404 && setMissing(true),
    );
    return () => {
      live = false;
    };
  }, [alertId]);
  const mined = useMined(a);
  if (missing) return <p className="small muted chain-receipt-none">{t('raahat.receipt.none')}</p>;
  if (!a) return null;

  const reverify = async () => {
    setVerify({ state: 'running' });
    try {
      if (!a.public_rpc_url) throw new Error('no public RPC');
      const rec = await readAnchor(
        { chainId: a.chain_id, registry: a.registry, alertKey: alertKey(a.alert_id) },
        rpcTransport(a.public_rpc_url),
      );
      if (/^0x0+$/.test(rec.capHash)) throw new Error(t('raahat.receipt.pending'));
      const got = await verifyCapHash(rec.capUri, rec.capHash);
      setVerify({ state: 'done', ok: got.ok, onChain: rec.capHash, computed: got.computed });
    } catch (err) {
      setVerify({ state: 'error', message: (err as Error).message?.slice(0, 120) || 'error' });
    }
  };

  return (
    <section className="chain-receipt" aria-label={t('raahat.receipt.title')}>
      <h3 className="h-sub">
        <Link2 aria-hidden="true" /> {t('raahat.receipt.title')} · {a.network}
        {a.exercise && (
          <>
            {' '}
            <ReplayChip /> <span className="small">{t('raahat.receipt.exercise')}</span>
          </>
        )}
      </h3>
      {a.state === 'failed' ? (
        <p className="small">
          <CircleAlert aria-hidden="true" /> {t('raahat.receipt.failed')}
        </p>
      ) : (
        <>
          <p className="small muted">{t('raahat.receipt.lead')}</p>
          <dl className="kv-list">
            <div className="kv">
              <dt>{t('raahat.receipt.tx')}</dt>
              <dd>
                {a.tx ? <TxLink explorer={a.explorer} hash={a.tx} /> : t('raahat.receipt.sending')}
                {a.tx && (
                  <span className="small muted">
                    {' · '}
                    {mined
                      ? t('raahat.receipt.mined', { n: fmtNumber(Number(mined.block), lang), t: fmtTime(new Date(mined.at * 1000).toISOString(), lang) })
                      : t('raahat.receipt.pending')}
                  </span>
                )}
              </dd>
            </div>
            {a.cap_hash && (
              <div className="kv">
                <dt>{t('raahat.receipt.capHash')}</dt>
                <dd className="mono break">{a.cap_hash}</dd>
              </div>
            )}
            {a.outcome_state === 'sent' && a.outcome_tx && (
              <div className="kv">
                <dt>{t('raahat.receipt.outcome', { a: a.acknowledged ?? 0, d: a.delivered ?? 0 })}</dt>
                <dd>
                  <TxLink explorer={a.explorer} hash={a.outcome_tx} />
                </dd>
              </div>
            )}
          </dl>
          <div className="chain-verify">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => void reverify()} disabled={verify.state === 'running'}>
              <ShieldCheck aria-hidden="true" /> {t('raahat.verify.button')}
            </button>
            <p className="small raahat-check" role="status">
              {verify.state === 'running' && (
                <>
                  <LoaderCircle aria-hidden="true" className="spin" /> {t('raahat.verify.running')}
                </>
              )}
              {verify.state === 'done' && (
                <>
                  {verify.ok ? <CircleCheck aria-hidden="true" className="ok-icon" /> : <CircleAlert aria-hidden="true" />}{' '}
                  {t(verify.ok ? 'raahat.verify.match' : 'raahat.verify.nomatch')}
                  <span className="mono break"> {short(verify.computed)}</span>
                </>
              )}
              {verify.state === 'error' && (
                <>
                  <CircleAlert aria-hidden="true" /> {t('raahat.verify.error', { e: verify.message })}
                </>
              )}
            </p>
          </div>
        </>
      )}
    </section>
  );
}
