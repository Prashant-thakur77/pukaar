import type { Key } from '../i18n';
import { LANDING_COUNTERS } from '../lib/counters';
import type { Lang } from '../store';
import type { Counters } from '../types';
import { CountUp } from './CountUp';
import { Reveal } from './Reveal';

type T = (key: Key, vars?: Record<string, string | number>) => string;

interface Props {
  /** null while loading (each counter shows a dash). */
  counters: Counters | null;
  lang: Lang;
  t: T;
  /** Shown under "None yet" when no flood alert has gone out, e.g. "All 5 villages are at Normal right now." */
  zeroNote?: string | null;
}

/** The landing counters (lib/counters.ts), with "None yet" in place of a bare 0 for flood alerts sent. */
export function CounterRow({ counters, lang, t, zeroNote }: Props) {
  return (
    <ul className="counters">
      {LANDING_COUNTERS.map((k, i) => {
        // An API older than this page may not send every counter yet: a dash, never a made-up 0.
        const value = counters ? (counters[k] ?? null) : null;
        const none = k === 'alerts_sent' && value === 0;
        return (
          <Reveal as="li" key={k} delay={i * 80} className={none ? 'counter counter-zero' : 'counter'}>
            {none ? (
              <span className="counter-num counter-none">{t('counter.alerts_sent.none')}</span>
            ) : (
              <CountUp value={value} lang={lang} className="counter-num" />
            )}
            <span className="counter-label">{t(`counter.${k}`)}</span>
            {none && zeroNote ? <span className="counter-note">{zeroNote}</span> : null}
          </Reveal>
        );
      })}
    </ul>
  );
}
