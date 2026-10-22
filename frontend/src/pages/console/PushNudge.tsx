import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { BellOff, ChevronRight } from 'lucide-react';
import { api } from '../../api';
import { useT } from '../../i18n';
import { pushEnvironment } from '../../lib/push';

/**
 * "इस फ़ोन पर मंज़ूरी की सूचना चालू नहीं · चालू करें ›" (spec 4.9): an amber line above the inbox until this phone
 * gets approval notifications. Shown only where push can work (a browser that has it, a server with a key).
 */
export function PushNudge() {
  const { t } = useT();
  const [off, setOff] = useState(false);
  useEffect(() => {
    let alive = true;
    (async () => {
      if (pushEnvironment() !== 'supported' || Notification.permission === 'denied') return;
      const reg = await navigator.serviceWorker.getRegistration().catch(() => undefined);
      const sub = reg ? await reg.pushManager.getSubscription().catch(() => null) : null;
      if (sub) return;
      const key = await api.vapidKey().catch(() => null);
      if (alive && key?.key) setOff(true);
    })();
    return () => {
      alive = false;
    };
  }, []);
  if (!off) return null;
  return (
    <p className="cs-nudge">
      <BellOff aria-hidden="true" />
      <span>{t('inbox.push.off')}</span>
      <Link to="/console/settings" className="cs-nudge-go">
        {t('inbox.push.on')} <ChevronRight aria-hidden="true" />
      </Link>
    </p>
  );
}
