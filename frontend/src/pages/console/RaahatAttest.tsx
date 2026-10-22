import { useCallback, useEffect, useState } from 'react';
import { CircleCheck, CircleDashed, Satellite } from 'lucide-react';
import { api, ApiError } from '../../api';
import { Skeleton } from '../../components/States';
import { useT } from '../../i18n';
import type { RaahatAttestations, RaahatAttester, Report } from '../../types';
import { raahatApi } from '../../lib/raahatApi';
import '../../i18n-raahat';

const VERIFIED = new Set(['verified_auto', 'verified', 'reviewed', 'actioned', 'resolved']);
const ATTESTERS: RaahatAttester[] = ['pradhan', 'officer', 'satellite'];

function reason(err: unknown, t: (k: never, v?: Record<string, string>) => string): string {
  const code = ((err as ApiError).detail as { code?: string } | null)?.code;
  return code ? t(`raahat.why.${code}` as never) : (err as Error).message || 'error';
}

/** The three attester chips for one alert, and the actions this person may take (Cedar decides on the server). */
export function AttestControls({ alertId, villageId, role, onChange }: { alertId: string; villageId: string; role: 'officer' | 'pradhan'; onChange?: () => void }) {
  const { t } = useT();
  const [st, setSt] = useState<RaahatAttestations | null>(null);
  const [severity, setSeverity] = useState(2);
  const [note, setNote] = useState('');
  const [reportId, setReportId] = useState('');
  const [photos, setPhotos] = useState<Report[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const load = useCallback(() => raahatApi.raahatAttestations(alertId).then(setSt, () => undefined), [alertId]);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (role !== 'pradhan') return;
    api.reports({ village_id: villageId }).then(
      (rs) => setPhotos(rs.filter((r) => r.photo_url && VERIFIED.has(r.state))),
      () => setPhotos([]),
    );
  }, [role, villageId]);

  const send = async (body: Parameters<typeof raahatApi.raahatAttest>[1]) => {
    setBusy(true);
    setMsg(null);
    try {
      await raahatApi.raahatAttest(alertId, body);
      onChange?.();
    } catch (err) {
      setMsg(t('raahat.attest.failed', { e: reason(err, t as never) }));
    } finally {
      setBusy(false);
      void load();
    }
  };

  const mine: RaahatAttester = role === 'officer' ? 'officer' : 'pradhan';
  return (
    <div className="attest">
      <p className="small">
        <strong>{t('raahat.attest.title')}</strong>
      </p>
      {!st && <Skeleton lines={1} />}
      {st && <ul className="chips-row" aria-label={t('raahat.attest.title')}>
        {ATTESTERS.map((who) => {
          const a = st?.attestations[who];
          return (
            <li key={who} className={`chip${a && a.severity >= 2 ? ' chip-ok' : ' chip-muted'}`}>
              {a ? <CircleCheck aria-hidden="true" /> : <CircleDashed aria-hidden="true" />} {t(`raahat.attest.${who}` as never)}
              {' · '}
              {a ? t('raahat.attest.severity', { s: a.severity }) : t('raahat.attest.none')}
            </li>
          );
        })}
      </ul>}
      {st?.confirmed && <p className="small ok-text">{t('raahat.attest.confirmed')}</p>}
      {st && !st.attestations[mine] && (
        <div className="attest-form">
          <label className="field small">
            <span>{t('raahat.attest.severity', { s: '' }).replace(/\s*\/3$/, '')}</span>
            <select value={severity} onChange={(e) => setSeverity(Number(e.target.value))}>
              {[0, 1, 2, 3].map((s) => (
                <option key={s} value={s}>
                  {t(`raahat.sev.${s}` as never)}
                </option>
              ))}
            </select>
          </label>
          {role === 'officer' ? (
            <>
              <label className="field small">
                <span>{t('raahat.attest.note')}</span>
                <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
              </label>
              <button type="button" className="btn btn-sm" disabled={busy || !note.trim()} onClick={() => void send({ who: 'officer', severity, note })}>
                {t('raahat.attest.as_officer')}
              </button>
            </>
          ) : photos && photos.length > 0 ? (
            <>
              <label className="field small">
                <span>{t('raahat.attest.photo')}</span>
                <select value={reportId} onChange={(e) => setReportId(e.target.value)}>
                  <option value="">—</option>
                  {photos.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.id} · {r.created_at.slice(0, 16).replace('T', ' ')}
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" className="btn btn-sm" disabled={busy || !reportId} onClick={() => void send({ who: 'pradhan', severity, report_id: reportId })}>
                {t('raahat.attest.send')}
              </button>
            </>
          ) : (
            <p className="small muted">{t('raahat.attest.photo_none')}</p>
          )}
        </div>
      )}
      {role === 'officer' && st && !st.attestations.satellite && (
        st.satellite_covers ? (
          <button type="button" className="btn btn-sm" disabled={busy} onClick={() => void send({ who: 'satellite' })}>
            <Satellite aria-hidden="true" /> {t('raahat.attest.satellite_run')}
          </button>
        ) : (
          <p className="small muted">{t('raahat.attest.satellite_none')}</p>
        )
      )}
      {msg && (
        <p className="small bad-text" role="alert">
          {msg}
        </p>
      )}
    </div>
  );
}
