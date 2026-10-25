import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { KeyRound, LoaderCircle, RotateCcw, Send } from 'lucide-react';
import { api, ApiError } from '../../api';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { HoldToConfirm } from '../../components/HoldToConfirm';
import { ListenButton } from '../../components/ListenButton';
import { QuotedAlert } from '../../components/QuotedAlert';
import { QRCode } from '../../components/QRCode';
import { Snackbar, type SnackbarMsg } from '../../components/Snackbar';
import { DeniedNote, ErrorState, Skeleton } from '../../components/States';
import { useNow } from '../../hooks/useMedia';
import { usePoll } from '../../hooks/usePoll';
import { useT } from '../../i18n';
import type { Lang } from '../../store';
import { fmtNumber, fmtTime } from '../../lib/format';
import { CHANNELS } from '../../lib/live';
import type { DemoAlert } from '../../types';
import { AlertMetricsPanel } from './AlertRecord';
import { Page } from './Sections';
import '../../styles/demo.css';

/*
 * /console/demo: the live jury demo's presenter screen (docs/DEMO_LIVE.md), big enough for a screen share.
 * Jurors scan the QR (t.me/<bot>?start=demo-<code>) and agree to the notice; the presenter starts the one practice
 * alert and approves it with the same hold-to-approve as the inbox; the counts (joined, delivered, confirmed) and the
 * seconds to the first and the median confirmation follow live. Counts and times only: never a name or a chat id.
 * The public demo accounts may watch; Cedar (run_demo) keeps the code and the buttons to the presenter.
 */

const POLL_MS = 2000;

function secs(n: number | null | undefined, lang: Lang): string {
  if (n == null) return '—';
  return `${fmtNumber(n, lang, n < 10 ? 1 : 0)} ${lang === 'hi' ? 'से.' : 's'}`;
}

function left(iso: string | null, now: number): string {
  if (!iso) return '';
  const s = Math.max(0, Math.round((new Date(iso).getTime() - now) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export default function LiveDemo() {
  const { lang } = useT();
  const en = lang === 'en';
  const poll = usePoll(() => api.demo(), [], POLL_MS, { live: [CHANNELS.officer], liveIntervalMs: POLL_MS });
  const now = useNow(1000);
  const [busy, setBusy] = useState<'open' | 'alert' | 'reset' | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [snack, setSnack] = useState<SnackbarMsg | null>(null);
  const closeSnack = useCallback(() => setSnack(null), []);
  const d = poll.data;

  const run = async (kind: 'open' | 'alert' | 'reset') => {
    setBusy(kind);
    setErr(null);
    try {
      const fn = kind === 'open' ? api.demoOpen : kind === 'alert' ? api.demoAlert : api.demoReset;
      const out = await fn();
      if (kind === 'reset') {
        const e = out.erased;
        setSnack({ id: Date.now(), text: en ? `Demo reset: ${e?.people ?? 0} people and ${e?.alerts ?? 0} alerts erased.` : `डेमो रीसेट: ${e?.people ?? 0} लोग और ${e?.alerts ?? 0} संदेश मिटाए गए।` });
      }
      await poll.refresh();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
    } finally {
      setBusy(null);
      setConfirmReset(false);
    }
  };

  const title = en ? 'Live demo' : 'लाइव डेमो';
  const lead = en
    ? 'Jurors join from their own phones; you approve one practice alert as the duty officer; their phones get the spoken Hindi alert with the “Got it” button. Practice only: the demo village is not a real place and is counted nowhere else.'
    : 'निर्णायक अपने फ़ोन से जुड़ते हैं; आप ड्यूटी अधिकारी की तरह एक अभ्यास संदेश मंज़ूर करते हैं; उनके फ़ोन पर बोला हुआ हिंदी संदेश “मिल गया” बटन के साथ आता है। केवल अभ्यास: डेमो गाँव असली जगह नहीं है और कहीं और गिना नहीं जाता।';

  if (poll.loading && !d) {
    return (
      <Page title={title} lead={lead} wide>
        <Skeleton lines={6} />
      </Page>
    );
  }
  if (poll.error && !d) {
    return (
      <Page title={title} lead={lead} wide>
        {poll.error.isDenied ? <DeniedNote error={poll.error} /> : <ErrorState error={poll.error} onRetry={poll.refresh} />}
      </Page>
    );
  }
  if (!d) return null;
  const a = d.alert;
  const open = Boolean(a && ['drafting', 'pending', 'approved', 'delivering'].includes(a.status));
  const waitAlert = d.next_alert_at ? left(d.next_alert_at, now) : '';
  const nextAlertLeft = d.next_alert_at && new Date(d.next_alert_at).getTime() > now;

  return (
    <Page title={title} lead={lead} wide>
      <p className="dm-banner" role="note">
        <strong>{en ? 'Practice' : 'अभ्यास'}</strong> {en ? '— not a real warning. Names and chat ids are erased within' : '— असली चेतावनी नहीं। नाम और चैट आईडी'} {d.keep_hours}{' '}
        {en ? 'hours; this screen shows counts only.' : 'घंटे में मिटा दिए जाते हैं; यह स्क्रीन केवल गिनती दिखाती है।'}
      </p>
      {!d.enabled && <p className="dm-note is-warn">{en ? 'The live demo is off on this stack (PUKAAR_LIVE_DEMO).' : 'इस स्टैक पर लाइव डेमो बंद है।'}</p>}
      {err && (err.isDenied ? <DeniedNote error={err} /> : <p className="dm-note is-warn" role="alert">{err.messageIn(lang)}</p>)}

      <div className="dm-grid">
        <section className="dm-card dm-join" aria-labelledby="dm-join-h">
          <h2 id="dm-join-h" className="dm-h">{en ? '1. Join from your phone' : '1. अपने फ़ोन से जुड़ें'}</h2>
          {d.code && d.join_url ? (
            <>
              <div className="dm-qr">
                <QRCode value={d.join_url} size={240} label={en ? `QR code: open Telegram and send /start demo-${d.code}` : `QR कोड: टेलीग्राम खोलें और /start demo-${d.code} भेजें`} />
              </div>
              <p className="dm-code-line">
                <span className="dm-code-k">{en ? 'Code' : 'कोड'}</span>
                <span className="dm-code" translate="no">{d.code}</span>
              </p>
              <p className="dm-how">
                {en ? 'Scan, or in Telegram open' : 'स्कैन करें, या टेलीग्राम में'} <span translate="no">@{d.bot}</span> {en ? 'and send' : 'खोलकर भेजें'}{' '}
                <code translate="no">/start demo-{d.code}</code>
              </p>
              <p className="dm-meta">
                {en ? 'Code expires in' : 'कोड की मियाद'} <span className="dm-num-inline">{left(d.code_expires_at, now)}</span> · {en ? `at most ${d.max_people} people` : `अधिकतम ${d.max_people} लोग`}
              </p>
            </>
          ) : d.can_run ? (
            <p className="dm-meta">{d.open ? (en ? 'The code has expired: make a new one.' : 'कोड की मियाद ख़त्म: नया बनाएँ।') : en ? 'Open the demo to make a join code.' : 'जुड़ने का कोड बनाने के लिए डेमो खोलें।'}</p>
          ) : (
            <p className="dm-meta">{en ? 'The join code is on the presenter’s screen.' : 'जुड़ने का कोड प्रस्तुतकर्ता की स्क्रीन पर है।'}</p>
          )}
          {d.can_run && (
            <div className="dm-actions">
              <button type="button" className="btn btn-ghost btn-press" disabled={busy !== null || !d.enabled} onClick={() => void run('open')}>
                {busy === 'open' ? <LoaderCircle className="spin" aria-hidden="true" /> : <KeyRound aria-hidden="true" />}{' '}
                {d.open ? (en ? 'New code' : 'नया कोड') : en ? 'Open the demo' : 'डेमो खोलें'}
              </button>
            </div>
          )}
        </section>

        <section className="dm-card dm-live" aria-labelledby="dm-live-h">
          <h2 id="dm-live-h" className="dm-h">{en ? '2. Live' : '2. लाइव'}</h2>
          <dl className="dm-counts" aria-live="polite">
            <Count k={en ? 'Joined' : 'जुड़े'} v={`${fmtNumber(d.joined, lang)}`} sub={`/ ${d.max_people}`} />
            <Count k={en ? 'Delivered' : 'पहुँचा'} v={a ? fmtNumber(a.delivered, lang) : '—'} sub={a ? `/ ${fmtNumber(a.targeted, lang)}` : ''} />
            <Count k={en ? 'Confirmed “Got it”' : '“मिल गया” दबाया'} v={a ? fmtNumber(a.confirmed, lang) : '—'} />
            <Count k={en ? 'First confirmation' : 'पहली पुष्टि'} v={secs(a?.seconds.first_sent_to_first_ack, lang)} sub={en ? 'after it was sent' : 'भेजने के बाद'} />
            <Count k={en ? 'Median confirmation' : 'मध्य पुष्टि'} v={secs(a?.seconds.first_sent_to_median_ack, lang)} sub={en ? 'after it was sent' : 'भेजने के बाद'} />
          </dl>
          {a && <Timeline a={a} lang={lang} />}
          {d.can_run && (
            <div className="dm-actions">
              <button type="button" className="btn btn-accent btn-press" disabled={busy !== null || !d.open || open || Boolean(nextAlertLeft)} onClick={() => void run('alert')}>
                {busy === 'alert' ? <LoaderCircle className="spin" aria-hidden="true" /> : <Send aria-hidden="true" />} {en ? 'Start the demo alert' : 'डेमो संदेश शुरू करें'}
              </button>
              {nextAlertLeft && !open && <span className="dm-meta">{en ? `Next one in ${waitAlert} (one per 2 minutes)` : `अगला ${waitAlert} बाद (हर 2 मिनट में एक)`}</span>}
              <button type="button" className="btn btn-ghost btn-press" disabled={busy !== null} onClick={() => setConfirmReset(true)}>
                {busy === 'reset' ? <LoaderCircle className="spin" aria-hidden="true" /> : <RotateCcw aria-hidden="true" />} {en ? 'Reset demo' : 'डेमो रीसेट करें'}
              </button>
            </div>
          )}
        </section>
      </div>

      {a && <Decision a={a} canRun={d.can_run} onDone={poll.refresh} />}

      {a && a.approved && (
        <section className="dm-card" aria-labelledby="dm-ddma-h">
          <h2 id="dm-ddma-h" className="dm-h">{en ? '3. What a DDMA sees for this alert' : '3. DDMA को इस संदेश के लिए क्या दिखता है'}</h2>
          <p className="dm-meta">
            {en ? 'The ten pilot metrics, from the same records. ' : 'पायलट के दस माप, उन्हीं रिकॉर्ड से। '}
            <Link to={`/console/inbox/${encodeURIComponent(a.id)}`}>{en ? 'Open the alert’s record in the console' : 'कंसोल में संदेश का रिकॉर्ड खोलें'}</Link>
          </p>
          <AlertMetricsPanel alertId={a.id} />
        </section>
      )}

      <ConfirmDialog
        open={confirmReset}
        title={en ? 'Reset the demo?' : 'डेमो रीसेट करें?'}
        confirmLabel={en ? 'Erase and reset' : 'मिटाएँ और रीसेट करें'}
        cancelLabel={en ? 'Cancel' : 'रद्द करें'}
        tone="danger"
        busy={busy === 'reset'}
        onCancel={() => setConfirmReset(false)}
        onConfirm={() => void run('reset')}
      >
        <p>{en ? 'Every demo person and demo alert is erased now, and the join code stops working.' : 'डेमो के सभी लोग और संदेश अभी मिटा दिए जाएँगे, और जुड़ने का कोड काम करना बंद कर देगा।'}</p>
      </ConfirmDialog>
      <Snackbar msg={snack} onClose={closeSnack} closeLabel={en ? 'Close' : 'बंद करें'} />
    </Page>
  );
}

function Count({ k, v, sub }: { k: string; v: string; sub?: string }) {
  return (
    <div className="dm-count">
      <dt>{k}</dt>
      <dd>
        <span className="dm-num">{v}</span>
        {sub ? <span className="dm-sub"> {sub}</span> : null}
      </dd>
    </div>
  );
}

function Timeline({ a, lang }: { a: DemoAlert; lang: Lang }) {
  const en = lang === 'en';
  const steps: { k: string; at: string | null; gap: number | null }[] = [
    { k: en ? 'Approved' : 'मंज़ूर', at: a.times.approved, gap: null },
    { k: en ? 'Sent' : 'भेजा', at: a.times.first_sent, gap: a.seconds.approved_to_first_sent },
    { k: en ? 'First “Got it”' : 'पहला “मिल गया”', at: a.times.first_ack, gap: a.seconds.first_sent_to_first_ack },
  ];
  return (
    <ol className="dm-steps" aria-label={en ? 'Timeline' : 'समय-रेखा'}>
      {steps.map((s) => (
        <li key={s.k} className={s.at ? 'is-done' : ''}>
          <span className="dm-step-k">{s.k}</span>
          <span className="dm-step-v">
            {s.at ? fmtTime(s.at, lang) : '—'}
            {s.gap != null && <span className="dm-step-gap"> (+{secs(s.gap, lang)})</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** The real officer step: the same approve route and hold-to-approve as the inbox, for the demo alert only. */
function Decision({ a, canRun, onDone }: { a: DemoAlert; canRun: boolean; onDone: () => Promise<void> }) {
  const { t, lang } = useT();
  const en = lang === 'en';
  const [err, setErr] = useState<ApiError | null>(null);
  const pending = a.status === 'pending';
  const status = en
    ? { drafting: 'Preparing the message and its audio…', pending: 'Waiting for the officer’s approval', approved: 'Approved: sending', delivering: 'Sending', delivered: 'Sent', declined: 'Declined: nothing sent', expired: 'Expired: nothing sent' }
    : { drafting: 'संदेश और आवाज़ तैयार हो रही है…', pending: 'अधिकारी की मंज़ूरी का इंतज़ार', approved: 'मंज़ूर: भेजा जा रहा है', delivering: 'भेजा जा रहा है', delivered: 'भेज दिया', declined: 'अस्वीकार: कुछ नहीं भेजा', expired: 'समय ख़त्म: कुछ नहीं भेजा' };
  const approve = async () => {
    setErr(null);
    try {
      await api.approve(a.id);
      await onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
      throw e;
    }
  };
  return (
    <section className="dm-card dm-decide lv-warning" aria-labelledby="dm-msg-h">
      <h2 id="dm-msg-h" className="dm-h">
        {en ? 'The practice alert' : 'अभ्यास संदेश'} · <span className="dm-status">{(status as Record<string, string>)[a.status] ?? a.status}</span>
      </h2>
      <QuotedAlert hi={a.text_hi} en={a.text_en} />
      <div className="dm-actions">
        <ListenButton alertId={a.id} hasAudio={a.has_audio} />
        <Link to={`/console/inbox/${encodeURIComponent(a.id)}`}>{en ? 'Open it in the inbox' : 'इनबॉक्स में खोलें'}</Link>
      </div>
      {pending && canRun && (
        <HoldToConfirm
          className="dm-hold"
          onConfirm={approve}
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
      )}
      {err && (err.isDenied ? <DeniedNote error={err} /> : <p className="dm-note is-warn" role="alert">{err.messageIn(lang)}</p>)}
    </section>
  );
}

