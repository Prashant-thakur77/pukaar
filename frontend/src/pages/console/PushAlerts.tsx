import { useEffect, useState } from 'react';
import { BellOff, BellRing, LoaderCircle, Send, Smartphone } from 'lucide-react';
import { api, ApiError } from '../../api';
import { ErrorState } from '../../components/States';
import { dict, useT } from '../../i18n';
import { pushEnvironment, sameKey, subscriptionId, urlBase64ToUint8Array } from '../../lib/push';

type State = 'checking' | 'unsupported' | 'ios-install' | 'no-worker' | 'server-off' | 'blocked' | 'off' | 'on';

const MESSAGE: Record<Exclude<State, 'checking'>, keyof typeof dict> = {
  unsupported: 'console.push.unsupported',
  'ios-install': 'console.push.ios',
  'no-worker': 'console.push.no_worker',
  'server-off': 'console.push.server_off',
  blocked: 'console.push.blocked',
  off: 'console.push.off',
  on: 'console.push.on',
};

async function registration(): Promise<ServiceWorkerRegistration | null> {
  try {
    return (await navigator.serviceWorker.getRegistration()) ?? null;
  } catch {
    return null;
  }
}

interface Detected {
  state: State;
  key: string | null;
  phones: number | null;
}

/** Where this browser stands. A subscription already on this phone is sent to the server again,
 * which restarts its 180-day expiry and restores it if the server dropped it. */
async function detect(): Promise<Detected> {
  const env = pushEnvironment();
  if (env !== 'supported') return { state: env, key: null, phones: null };
  const reg = await registration();
  if (!reg) return { state: 'no-worker', key: null, phones: null };
  let key: string | null = null;
  try {
    key = (await api.vapidKey()).key;
  } catch {
    key = null;
  }
  if (!key) return { state: 'server-off', key: null, phones: null };
  if (Notification.permission === 'denied') return { state: 'blocked', key, phones: null };
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return { state: 'off', key, phones: null };
  if (!sameKey(sub.options.applicationServerKey, key)) {
    await sub.unsubscribe().catch(() => false); // the server key was rotated: this one can never work
    return { state: 'off', key, phones: null };
  }
  try {
    await api.addPushSubscription(sub.toJSON());
    const phones = (await api.pushSubscriptions()).length;
    return { state: 'on', key, phones };
  } catch {
    return { state: 'on', key, phones: null };
  }
}

/** Web Push approval alerts on this phone, next to the Telegram link. */
export function PushAlerts() {
  const { t } = useT();
  const [state, setState] = useState<State>('checking');
  const [key, setKey] = useState<string | null>(null);
  const [phones, setPhones] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [note, setNote] = useState<string | null>(null);

  function apply(d: Detected) {
    setState(d.state);
    setKey(d.key);
    setPhones(d.phones);
  }

  useEffect(() => {
    let alive = true;
    void detect().then((d) => {
      if (alive) apply(d);
    });
    return () => {
      alive = false;
    };
  }, []);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setErr(null);
    setNote(null);
    try {
      await fn();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
    } finally {
      setBusy(false);
    }
  }

  const turnOn = () =>
    run(async () => {
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        setState(permission === 'denied' ? 'blocked' : 'off');
        return;
      }
      const reg = await registration();
      if (!reg || !key) {
        setState(reg ? 'server-off' : 'no-worker');
        return;
      }
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key) });
      try {
        await api.addPushSubscription(sub.toJSON());
      } catch (e) {
        await sub.unsubscribe().catch(() => false); // the server did not keep it: do not leave a dead one here
        throw e;
      }
      apply(await detect());
    });

  const turnOff = () =>
    run(async () => {
      const reg = await registration();
      const sub = reg ? await reg.pushManager.getSubscription() : null;
      if (sub) {
        try {
          await api.removePushSubscription(await subscriptionId(sub.endpoint));
        } catch (e) {
          if (!(e instanceof ApiError && e.status === 404)) throw e;
        }
        await sub.unsubscribe().catch(() => false);
      }
      setState('off');
      setPhones(null);
    });

  const test = () =>
    run(async () => {
      const r = await api.pushTest();
      setNote(t('console.push.test_sent', { n: r.sent }));
    });

  const icon =
    state === 'on' ? <BellRing aria-hidden="true" /> : state === 'checking' ? <LoaderCircle className="spin" aria-hidden="true" /> : state === 'ios-install' ? <Smartphone aria-hidden="true" /> : <BellOff aria-hidden="true" />;

  return (
    <div className="push-alerts stack">
      <p className="small muted">{t('console.push.lead')}</p>
      <p className={`push-state is-${state}`} role="status" aria-live="polite">
        {icon} <span>{state === 'checking' ? '…' : t(MESSAGE[state])}</span>
      </p>
      {state === 'on' && phones != null && <p className="small muted">{t('console.push.phones', { n: phones })}</p>}
      {(state === 'off' || state === 'on') && (
        <div className="push-actions">
          {state === 'off' ? (
            <button type="button" className="btn btn-ghost btn-press" onClick={() => void turnOn()} disabled={busy}>
              {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <BellRing aria-hidden="true" />} {t('console.push.turn_on')}
            </button>
          ) : (
            <>
              <button type="button" className="btn btn-ghost btn-press" onClick={() => void test()} disabled={busy}>
                {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <Send aria-hidden="true" />} {t('console.push.test')}
              </button>
              <button type="button" className="btn btn-ghost btn-press" onClick={() => void turnOff()} disabled={busy}>
                <BellOff aria-hidden="true" /> {t('console.push.turn_off')}
              </button>
            </>
          )}
        </div>
      )}
      {note && (
        <p className="small muted" role="status">
          {note}
        </p>
      )}
      {err && <ErrorState error={err} compact />}
    </div>
  );
}
