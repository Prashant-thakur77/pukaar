import type { ReactNode } from 'react';
import { useNow } from '../hooks/useMedia';
import { levelWord, useT } from '../i18n';
import { istClock } from '../lib/answerText';
import { fmtNumber } from '../lib/format';
import { riverHeadline, riverNum as num, RIVER_KEYS as KEYS, type RiverLines as Lines, type RLPoint } from '../lib/riverLine';
import { RiverLine, ThresholdLadder, type LadderRow, type RLLine } from './RiverLine';

/*
 * "नदी अभी", the river now: the headline (the flow, which way it is going, what the forecast says about the next
 * line), S1 under it and the ladder under that. The village page and the officer's decision panel use it.
 */

interface Props {
  observed: RLPoint[];
  forecast?: RLPoint[];
  thresholds: Lines | null;
  unit: string;
  /** The heading's id, and its words ("नदी अभी"). */
  title: string;
  headingId: string;
  heading?: 'h2' | 'h3' | 'h4';
  height?: number;
  /** Where the numbers come from, under the ladder. */
  source?: ReactNode;
  ladder?: boolean;
  /** A replay's readings are years old by design: never call them stale. */
  replay?: boolean;
}

const STALE_MIN = 60;

export function RiverNow({ observed, forecast = [], thresholds: th, unit, title, headingId, heading = 'h2', height = 220, source, ladder = true, replay = false }: Props) {
  const { lang } = useT();
  const now = useNow(60_000);
  const hi = lang === 'hi';
  const H = heading;
  const last = [...observed].reverse().find((p) => p.v != null) ?? null;
  const age = last ? Math.round((now - last.t) / 60000) : null;
  const stale = !replay && age != null && age > STALE_MIN ? (hi ? `आख़िरी रीडिंग ${fmtNumber(Math.round(age / 60), lang)} घंटे पुरानी` : `Last reading ${Math.round(age / 60)} h old`) : null;
  const head = riverHeadline(observed, forecast, th, unit, lang);
  const lines: RLLine[] = th ? KEYS.map((k) => ({ level: k, value: th[k], word: `${levelWord(k, lang)} ${num(th[k], lang)}` })) : [];
  const years = th?.return_period_years ?? null;
  const rows: LadderRow[] = [
    ...(th
      ? KEYS.map((k) => ({
          value: th[k],
          level: k,
          word: levelWord(k, lang),
          note: years?.[k] ? (hi ? `${fmtNumber(years[k], lang)} साल में एक बार आने वाला बहाव` : `a flow seen once in ${years[k]} years`) : undefined,
        }))
      : []),
    ...(last?.v != null ? [{ value: last.v, word: hi ? 'अभी' : 'Now', note: istClock(new Date(last.t).toISOString()) ?? undefined, now: true }] : []),
  ];
  const label = hi
    ? `नदी का बहाव ${head.value}, ${head.way}${head.ahead ? `, ${head.ahead}` : ''}`
    : `River flow ${head.value}, ${head.way}${head.ahead ? `, ${head.ahead}` : ''}`;
  return (
    <div className="rn">
      <H id={headingId} className="rn-h">
        {title}
      </H>
      <p className="rn-head">
        <b className="rn-v">{head.value}</b>
        <span className="rn-way">{head.way}</span>
        {head.ahead && <span className="rn-ahead">{head.ahead}</span>}
      </p>
      <RiverLine
        observed={observed}
        forecast={forecast}
        lines={lines}
        height={height}
        label={label}
        stale={stale}
        nowLabel={last ? `${hi ? 'अभी' : 'Now'} ${istClock(new Date(last.t).toISOString()) ?? ''}` : null}
      />
      {ladder && rows.length > 1 && <ThresholdLadder rows={rows} unit={unit} label={hi ? 'रेखाएँ, सबसे ऊँची पहले' : 'The lines, highest first'} />}
      {source && <p className="rn-src">{source}</p>}
    </div>
  );
}
