import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { CircleCheck, CircleX, Clock, Link2Off, Users, X } from 'lucide-react';
import { api, ApiError } from '../api';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { HoldToConfirm } from '../components/HoldToConfirm';
import '../styles/console-shell.css';
import { ListenButton } from '../components/ListenButton';
import { ReplayChip } from '../components/Chips';
import { DeniedNote, ErrorState, Skeleton } from '../components/States';
import { usePoll } from '../hooks/usePoll';
import { dict, useT, type Key } from '../i18n';
import { QuotedAlert } from '../components/QuotedAlert';
import { RiverNow } from '../components/RiverNow';
import { useNow } from '../hooks/useMedia';
import { evidenceLines } from '../lib/evidence';
import { fmtNumber } from '../lib/format';
import { waitedMinutes } from '../lib/inbox';
import { LEVEL_ICON } from '../lib/levels';
import { toPoints } from '../lib/riverLine';
import { expiryMs, fmtDuration } from '../lib/format';
import type { Alert } from '../types';
import '../styles/console.css';

/** One line in the page's language (the switch in the bare header changes it). */
function Bi({ k, vars }: { k: Key; vars?: Record<string, string | number> }) {
  const { t } = useT();
  return <>{t(k, vars)}</>;
}

function useCountdown(iso: string | number | undefined) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const at = expiryMs(iso);
  return at == null ? null : at - now;
}

function LatePage({ error, timedOut }: { error?: ApiError | null; timedOut?: boolean }) {
  const { t, lang } = useT();
  const body = lang === 'hi' ? error?.messageHi || t('approve.late.body') : error?.messageEn && error.status === 409 ? error.messageEn : t('approve.late.body');
  return (
    <section className="approve-end is-late" role="alert">
      <span className="result-icon" aria-hidden="true">
        <Clock />
      </span>
      <h1 className="result-title">
        <Bi k={timedOut ? 'approve.timeout.title' : 'approve.late.title'} />
      </h1>
      <p className="result-body">{body}</p>
      <p>
        <Link to="/console/inbox" className="go-link">
          {lang === 'hi' ? 'कंसोल में देखें' : 'See it in the console'}
        </Link>
      </p>
    </section>
  );
}

/** 400 {code:"invalid"}: a broken or forged link. Different from "late" (409). */
function InvalidPage() {
  return (
    <section className="approve-end is-invalid" role="alert">
      <span className="result-icon" aria-hidden="true">
        <Link2Off />
      </span>
      <h1 className="result-title">
        <Bi k="approve.invalid" />
      </h1>
      <p className="result-body">
        <Bi k="approve.invalid.body" />
      </p>
    </section>
  );
}

const isInvalid = (e: ApiError | null | undefined) => Boolean(e && (e.code === 'invalid' || e.status === 400 || e.status === 404 || e.status === 401));

export default function Approve() {
  const { t, lang } = useT();
  const { token = '' } = useParams();
  const { data, error, loading, refresh } = usePoll(() => api.approval(token), [token], 0);
  const [confirm, setConfirm] = useState<'approve' | 'decline' | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Alert | null>(null);
  const [actErr, setActErr] = useState<ApiError | null>(null);
  const left = useCountdown(data?.expires_at);

  async function decide(d: 'approve' | 'decline') {
    setBusy(true);
    setActErr(null);
    try {
      setResult(await api.decideApproval(token, d));
    } catch (e) {
      setActErr(e instanceof ApiError ? e : new ApiError(0, null));
      throw e;
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  }

  let body;
  if (loading && !data) {
    body = (
      <div className="card">
        <Skeleton lines={5} />
      </div>
    );
  } else if (error && !data) {
    body = error.status === 409 || error.status === 410 ? <LatePage error={error} /> : isInvalid(error) ? <InvalidPage /> : <ErrorState error={error} onRetry={refresh} />;
  } else if (result) {
    const ok = result.status !== 'declined';
    body = (
      <section className={`approve-end ${ok ? 'is-ok' : 'is-declined'}`} aria-live="polite">
        <span className="result-icon" aria-hidden="true">
          {ok ? <CircleCheck /> : <CircleX />}
          <i />
        </span>
        <h1 className="result-title">{ok ? <Bi k="approve.done.approved" /> : <Bi k="approve.done.declined" />}</h1>
      </section>
    );
  } else if (actErr && actErr.code === 'invalid') {
    body = <InvalidPage />;
  } else if (actErr?.isLate || (data && !data.valid) || (left !== null && left <= 0)) {
    // Our own countdown ran out (no server answer yet): say so, not "already decided".
    body = <LatePage error={actErr} timedOut={!actErr && Boolean(data?.valid) && left !== null && left <= 0} />;
  } else if (data) {
    const a = data.alert;
    body = (
      <Decision
        a={a}
        left={left}
        busy={busy}
        actErr={actErr}
        onApprove={() => decide('approve')}
        onDecline={() => setConfirm('decline')}
      />
    );
  }

  return (
    <div className="approve ota">
      {body}
      {data && !result && (
        <ConfirmDialog
          open={confirm !== null}
          title={t('approve.decline')}
          confirmLabel={lang === 'hi' ? 'हाँ, अस्वीकार करें' : 'Yes, decline'}
          cancelLabel={t('common.cancel')}
          tone="danger"
          busy={busy}
          sheet
          onCancel={() => setConfirm(null)}
          onConfirm={() => confirm && void decide(confirm).catch(() => {})}
        >
          <p>
            <Bi k="approve.confirm.decline" />
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}

/**
 * The decision, laid out as the console's on a phone (spec 4.9, 4.13): the level and village on the level's own
 * banner, why (the river line and the evidence in words), exactly what will be sent and to whom, then hold to
 * approve stuck to the thumb with Decline under it. In the page's language; the spoken Hindi message is quoted
 * word for word on an English page too, with its English meaning (QuotedAlert).
 */
function Decision({ a, left, busy, actErr, onApprove, onDecline }: {
  a: Alert;
  left: number | null;
  busy: boolean;
  actErr: ApiError | null;
  onApprove: () => Promise<unknown>;
  onDecline: () => void;
}) {
  const { t, lang } = useT();
  const hi = lang === 'hi';
  const now = useNow(30_000);
  const Icon = LEVEL_ICON[a.level];
  const river = usePoll(() => api.villageNow(a.village_id), [a.village_id], 0);
  const ev = evidenceLines(a.decision_trace, lang);
  const fallback = a.reasoning_model === 'rule-fallback';
  const waited = waitedMinutes(a.created_at, now);
  const obs = river.data?.river?.points?.length ? toPoints(river.data.river.points) : [];
  const th = river.data?.river?.thresholds ?? null;
  return (
    <article className={`dp ota-card lv-${a.level}`} aria-labelledby="ota-h">
      <header className="ota-banner">
        <p className="ota-eyebrow">
          <Bi k="approve.eyebrow" />
          <span className={`countdown${left !== null && left < 120000 ? ' is-low' : ''}`}>
            <Clock aria-hidden="true" /> {left !== null ? fmtDuration(left) : '—'}
          </span>
        </p>
        <h1 id="ota-h" className="ota-title">
          <Icon aria-hidden="true" className="ota-icon" />
          <span>
            {dict[`level.${a.level}`][lang]} · {hi ? a.village_name_hi || a.village_name : a.village_name}
          </span>
        </h1>
        <p className="ota-sub">
          <span>
            {hi
              ? `${fmtNumber(a.recipients_count, 'hi')} लोगों तक · ${fmtNumber(waited, 'hi')} मिनट से इंतज़ार`
              : `To ${fmtNumber(a.recipients_count, 'en')} people · waiting ${waited} min`}
          </span>
          {a.replay && <ReplayChip />}
        </p>
      </header>

      <div className="dp-body">
        <section className="dp-sec">
          <h2 className="dp-sec-h">
            <Bi k="decide.why" />
          </h2>
          {th && obs.length > 1 && (
            <RiverNow observed={obs} thresholds={th} unit="m³/s" title={hi ? 'नदी अभी' : 'The river now'} headingId="ota-river" heading="h3" height={140} ladder={false} replay={a.replay} />
          )}
          {ev.length > 0 && (
            <ul className="dp-ev ota-ev">
              {ev.slice(0, 3).map((l, i) => (
                <li key={i} className={l.level ? `lv-${l.level}` : ''}>
                  <span>{l.text}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="dp-sec">
          <h2 className="dp-sec-h">
            <Bi k="decide.send" />
          </h2>
          <QuotedAlert hi={a.text_hi} en={a.text_en} />
          <div className="dp-msg-tools">
            <ListenButton alertId={a.id} hasAudio={a.has_audio} />
            {fallback && (
              <p className="chip chip-warn chip-bi">
                <Bi k="console.check.template" />
              </p>
            )}
          </div>
        </section>

        <section className="dp-sec">
          <h2 className="dp-sec-h">
            <Bi k="decide.towhom" />
          </h2>
          <p className="ota-whom">
            <Users aria-hidden="true" />
            <span>
              {hi
                ? `${fmtNumber(a.recipients_count, 'hi')} जुड़े हुए लोग · कॉल, SMS और Telegram`
                : `${fmtNumber(a.recipients_count, 'en')} registered people · call, SMS and Telegram`}
            </span>
          </p>
        </section>

        {actErr && !actErr.isLate && (actErr.isDenied ? <DeniedNote error={actErr} /> : actErr.isRetry ? (
          <p className="warn-text" role="alert">
            <Bi k="approve.retry" />
          </p>
        ) : <ErrorState error={actErr} compact />)}
      </div>

      <div className="dp-actions">
        <HoldToConfirm
          className="approve-hold"
          disabled={busy}
          onConfirm={onApprove}
          text={{
            idle: t('decide.hold.idle'),
            holding: t('decide.hold.holding'),
            almost: t('decide.hold.almost'),
            sending: t('decide.hold.sending'),
            done: t('decide.hold.done'),
            hint: t('decide.hold.hint'),
            confirmQ: t('decide.confirm.q'),
            confirmYes: t('decide.confirm.yes'),
            confirmNo: t('common.cancel'),
          }}
        />
        <button type="button" className="btn btn-ghost btn-decline ota-decline" onClick={onDecline} disabled={busy}>
          <X aria-hidden="true" />
          <span>{t('approve.decline')}</span>
        </button>
      </div>
    </article>
  );
}
