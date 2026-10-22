import { TrendingUp } from 'lucide-react';
import { useT } from '../i18n';
import { fmtAgo, fmtNumber } from '../lib/format';
import { countedLine, healthWords, qualityWord, risingLine } from '../lib/gaugeHealth';
import type { GaugeHealth, GaugeQuality, Level } from '../types';

/**
 * A gauge's state as a ledger: the newest reading's quality, counted against measured, the
 * rising-fast marker, and health (last seen, battery, bad-reading share, reasons).
 */
export function GaugeLedger({
  health,
  quality,
  qualityReasons,
  counted,
  measured,
  rising,
  riseCm,
  withVitals = true,
}: {
  health?: GaugeHealth | null;
  quality?: GaugeQuality | string | null;
  qualityReasons?: string[];
  counted?: Level | null;
  measured?: Level | null;
  rising?: boolean;
  riseCm?: number | null;
  /** Also list last heard and battery (the sensors board shows those in its own facts). */
  withVitals?: boolean;
}) {
  const { t, lang } = useT();
  const hw = healthWords(health, lang);
  const both = countedLine(counted, measured, lang);
  const rise = risingLine(rising, riseCm, lang);
  const q = quality ?? null;
  return (
    <div className="gl">
      {rise && (
        <p className="gl-rise" role="note">
          <TrendingUp aria-hidden="true" /> {rise}
        </p>
      )}
      <dl className="rv-ledger gl-rows">
        {q && (
          <div className={q === 'good' ? undefined : 'is-bad'}>
            <dt>{t('gauge.quality')}</dt>
            <dd>
              {qualityWord(q, lang)}
              {q !== 'good' && qualityReasons && qualityReasons.length > 0 && <span className="gl-code"> · {qualityReasons.join(', ')}</span>}
            </dd>
          </div>
        )}
        {both && (
          <div>
            <dt>{t('gauge.counted')}</dt>
            <dd>{both}</dd>
          </div>
        )}
        {hw && health && (
          <>
            <div className={hw.ok ? undefined : 'is-bad'}>
              <dt>{t('gauge.health')}</dt>
              <dd>{hw.status}</dd>
            </div>
            {withVitals && (
              <>
                <div className={health.reasons.includes('silent') ? 'is-bad' : undefined}>
                  <dt>{t('gauge.lastseen')}</dt>
                  <dd>{health.last_seen ? fmtAgo(health.last_seen, lang) : '—'}</dd>
                </div>
                <div className={health.battery_low ? 'is-bad' : undefined}>
                  <dt>{t('gauge.batt')}</dt>
                  <dd>
                    {health.battery_v == null
                      ? '—'
                      : health.battery_low
                        ? t('gauge.batt.low', { v: fmtNumber(health.battery_v, lang, 2) })
                        : `${fmtNumber(health.battery_v, lang, 2)} V`}
                  </dd>
                </div>
              </>
            )}
            <div className={health.reasons.includes('bad_quality') ? 'is-bad' : undefined}>
              <dt>{t('gauge.bad')}</dt>
              <dd>{hw.badShare}</dd>
            </div>
          </>
        )}
      </dl>
    </div>
  );
}
