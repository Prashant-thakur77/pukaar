import { useCallback, useEffect, useState } from 'react';
import { CircleCheck, ReceiptText } from 'lucide-react';
import { ApiError } from '../../api';
import { ReplayChip } from '../../components/Chips';
import { EmptyState, ErrorState, Skeleton } from '../../components/States';
import { usePoll } from '../../hooks/usePoll';
import { useT } from '../../i18n';
import { CHANNELS } from '../../lib/live';
import type { RaahatHousehold, RaahatLedgerItem } from '../../types';
import { AttestControls } from './RaahatAttest';
import '../../raahat.css';
import { raahatApi } from '../../lib/raahatApi';
import '../../i18n-raahat';

/** One released alert: the pradhan's attestation and the household list with a reference box per household. */
function ReleasedAlert({ item, onChange }: { item: RaahatLedgerItem; onChange: () => void }) {
  const { t } = useT();
  const [rows, setRows] = useState<RaahatHousehold[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [refs, setRefs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = useCallback(() => raahatApi.raahatHouseholds(item.alert_id).then(setRows, setError), [item.alert_id]);
  useEffect(() => {
    void load();
  }, [load]);

  const record = async (household: string) => {
    setBusy(household);
    setMsg(null);
    try {
      await raahatApi.raahatReceipt(item.alert_id, household, refs[household] ?? '');
      onChange();
    } catch (err) {
      const code = ((err as ApiError).detail as { code?: string } | null)?.code;
      setMsg(code ? t(`raahat.why.${code}` as never) : t('raahat.relief.failed'));
    } finally {
      setBusy(null);
      void load();
    }
  };
  const done = rows?.filter((r) => r.receipt?.state === 'sent').length ?? 0;

  return (
    <li className="relief-card">
      <div className="ac-top">
        <strong>{t(`raahat.level.${item.level}` as never)}</strong>
        {item.exercise && <ReplayChip />}
        {rows && <span className="chip">{t('raahat.receipts.count', { n: done, t: rows.length })}</span>}
      </div>
      <AttestControls alertId={item.alert_id} villageId={item.village_id} role="pradhan" onChange={onChange} />
      {error && <ErrorState error={error} compact />}
      {!rows && !error && <Skeleton lines={3} />}
      {rows && (
        <div className="table-wrap" tabIndex={0} role="region" aria-label={`${t('raahat.receipts.count', { n: done, t: rows.length })} · ${item.alert_id}`}>
          <table className="data-table compact stack-sm">
            <tbody>
              {rows.map((r) => (
                <tr key={r.household}>
                  <th scope="row">
                    {r.label} <span className="mono small muted">{r.household.slice(0, 10)}…</span>
                  </th>
                  <td>
                    {r.receipt?.state === 'sent' ? (
                      <span className="ok-text small">
                        <CircleCheck aria-hidden="true" /> {t('raahat.receipts.done')}
                      </span>
                    ) : (
                      <span className="receipt-entry">
                        <input
                          aria-label={`${t('raahat.receipts.ref')}: ${r.label}`}
                          placeholder={t('raahat.receipts.ref')}
                          value={refs[r.household] ?? ''}
                          onChange={(e) => setRefs({ ...refs, [r.household]: e.target.value })}
                          maxLength={64}
                        />
                        <button type="button" className="btn btn-sm" disabled={busy !== null || !(refs[r.household] ?? '').trim()} onClick={() => void record(r.household)}>
                          {t('raahat.receipts.record')}
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {msg && (
        <p className="small bad-text" role="alert">
          {msg}
        </p>
      )}
    </li>
  );
}

/** Pradhan console: relief released for their own villages, the attestation and the receipts (PLAN.md Step 3). */
export function RaahatPradhan({ villageIds }: { villageIds: string[] }) {
  const { t } = useT();
  const ledger = usePoll(() => raahatApi.raahatLedger(), [], 30000, { live: [CHANNELS.raahat] });
  const items = (ledger.data?.items ?? []).filter(
    (i) => villageIds.includes(i.village_id) && i.releases.some((r) => r.state === 'sent'),
  );
  return (
    <div className="relief">
      <p className="small muted">{t('raahat.receipts.lead')}</p>
      {ledger.error && !ledger.data ? (
        <ErrorState error={ledger.error} compact />
      ) : !ledger.data ? (
        <Skeleton lines={3} />
      ) : items.length === 0 ? (
        <EmptyState title={t('raahat.receipts.none')} icon={<ReceiptText />} />
      ) : (
        <ul className="relief-list">
          {items.map((it) => (
            <ReleasedAlert key={it.alert_id} item={it} onChange={() => void ledger.refresh()} />
          ))}
        </ul>
      )}
    </div>
  );
}
