import { BellRing, CheckCheck, Timer, TriangleAlert, Volume2 } from 'lucide-react';
import { useT, type Key } from '../i18n';
import { fmtTime } from '../lib/format';
import type { Alert, Delivery } from '../types';

/** "1 min 05 s" style gap between two ISO times, or null if either is missing. */
function gap(from: string | null | undefined, to: string | null | undefined): number | null {
  if (!from || !to) return null;
  const ms = new Date(to).getTime() - new Date(from).getTime();
  return Number.isFinite(ms) && ms >= 0 ? ms : null;
}

function fmtGap(ms: number, lang: 'hi' | 'en'): string {
  const s = Math.round(ms / 1000);
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (lang === 'hi') return m ? `${m} मि ${String(r).padStart(2, '0')} से` : `${r} से`;
  return m ? `${m} min ${String(r).padStart(2, '0')} s` : `${r} s`;
}

const earliest = (xs: (string | null)[]) => xs.filter((x): x is string => !!x).sort()[0] ?? null;

/**
 * Time to ear: from the level rising to the first spoken alert on a phone and
 * the first "मिल गया". Every mark is a timestamp the stack recorded.
 */
export function TimeToEar({ alert, deliveries }: { alert: Alert; deliveries: Delivery[] }) {
  const { t, lang } = useT();
  const firstSent = earliest(deliveries.map((d) => d.sent_at));
  const firstAck = earliest(deliveries.map((d) => d.acknowledged_at));
  const marks: { key: Key; icon: typeof Timer; at: string | null }[] = [
    { key: 'tte.rose', icon: TriangleAlert, at: alert.created_at },
    { key: 'tte.decided', icon: CheckCheck, at: alert.decided_at },
    { key: 'tte.voice', icon: Volume2, at: firstSent },
    { key: 'tte.ack', icon: BellRing, at: firstAck },
  ];
  const total = gap(alert.created_at, firstAck);
  return (
    <section className="tte" aria-label={t('tte.title')}>
      <p className="tte-head">
        <Timer aria-hidden="true" /> {t('tte.title')}
        <strong className={`tte-total${total == null ? ' is-pending' : ''}`}>{total == null ? t('tte.notyet') : fmtGap(total, lang)}</strong>
      </p>
      <ol className="tte-marks">
        {marks.map((m, i) => {
          const g = i > 0 ? gap(marks[i - 1].at, m.at) : null;
          return (
            <li key={m.key} className={m.at ? 'is-done' : ''}>
              <span className="tte-icon" aria-hidden="true">
                <m.icon />
              </span>
              <span className="tte-label">{t(m.key)}</span>
              <span className="tte-at">{fmtTime(m.at, lang)}</span>
              {g != null && <span className="tte-gap">+{fmtGap(g, lang)}</span>}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
