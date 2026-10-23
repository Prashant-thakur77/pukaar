import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { fmtNumber } from '../lib/format';
import { labelTops, xTicks, yDomain, yTicks, type RLPoint } from '../lib/riverLine';
import { useT } from '../i18n';
import type { Level } from '../types';
import './riverline.css';

/*
 * S1, the living river line (C8), with its accessible twin, the threshold ladder (C9). One inline SVG, no chart
 * library: the observed line, a dotted forecast, each level's line labelled on the line at the right, "now" as a
 * hairline with its time, the numbers on the right. Words are HTML over the drawing, so they stay 16 px at
 * every width. Motion: the observed line draws in once when it first scrolls into view (never under reduced
 * motion); a new reading glides the dot; a line the river has just crossed pulses its label once.
 */

export interface RLLine {
  level: Exclude<Level, 'normal'>;
  value: number;
  /** The word on the line, e.g. "चेतावनी 2.21". */
  word: string;
}

interface Props {
  observed: RLPoint[];
  forecast?: RLPoint[];
  lines: RLLine[];
  /** The figure's spoken summary (the drawing itself is hidden from screen readers; the ladder is the table). */
  label: string;
  height?: number;
  /** "अभी 03:10 IST" over the hairline. */
  nowLabel?: string | null;
  /** A time to put the "now" marker at instead of the last reading (the story moves it). */
  cursor?: number | null;
  /** The x range; by default the observed and forecast points. */
  domain?: [number, number];
  /** Old data: the line goes grey after the last reading and this label says how old. */
  stale?: string | null;
  /** The sensor is off: the line is dashed and this label says so. */
  offline?: string | null;
  /** Dim what lies after the marker (the story: what had not happened yet). */
  veil?: boolean;
  className?: string;
  children?: ReactNode;
}

const PAD_TOP = 30;
const PAD_BOTTOM = 6;
const LABEL_H = 24;

const path = (pts: { x: number; y: number }[]) => pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join('');

export function RiverLine({ observed, forecast = [], lines, label, height = 220, nowLabel, cursor = null, domain, stale, offline, veil = false, className = '', children }: Props) {
  const { lang } = useT();
  const box = useRef<HTMLDivElement>(null);
  const [drawn, setDrawn] = useState(false);
  const obs = observed.filter((p) => p.v != null) as { t: number; v: number }[];
  const fc = forecast.filter((p) => p.v != null) as { t: number; v: number }[];
  const last = obs[obs.length - 1] ?? null;

  // A line the newest reading has just crossed (upwards) pulses its label once.
  const prev = useRef<number | null>(null);
  const [pulse, setPulse] = useState<string | null>(null);
  useEffect(() => {
    const was = prev.current;
    prev.current = last?.v ?? null;
    if (was == null || last == null) return;
    const crossed = lines.find((l) => was < l.value && last.v >= l.value);
    if (!crossed) return;
    const show = window.setTimeout(() => setPulse(crossed.level), 0);
    const hide = window.setTimeout(() => setPulse(null), 1300);
    return () => {
      clearTimeout(show);
      clearTimeout(hide);
    };
  }, [last?.v, lines]); // eslint-disable-line react-hooks/exhaustive-deps

  // Draw in once, the first time it is on screen, and only when motion is welcome.
  useEffect(() => {
    const el = box.current;
    if (!el || typeof IntersectionObserver === 'undefined' || !matchMedia('(prefers-reduced-motion: no-preference)').matches) return;
    const io = new IntersectionObserver((es) => {
      if (es.some((e) => e.isIntersecting)) {
        setDrawn(true);
        io.disconnect();
      }
    }, { threshold: 0.4 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  if (obs.length < 2 && fc.length < 2) return null;
  const all = [...obs, ...fc];
  const [t0, t1] = domain ?? [all[0].t, Math.max(...all.map((p) => p.t))];
  const [lo, hi] = yDomain(all.map((p) => p.v), lines.map((l) => l.value));
  const inner = height - PAD_TOP - PAD_BOTTOM;
  const X = (t: number) => ((t - t0) / Math.max(1, t1 - t0)) * 1000;
  const Y = (v: number) => PAD_TOP + (1 - (v - lo) / (hi - lo)) * inner;
  const pct = (t: number) => Math.min(100, Math.max(0, X(t) / 10));
  const obsPts = obs.map((p) => ({ x: X(p.t), y: Y(p.v) }));
  const fcPts = (last && fc.length ? [last, ...fc] : fc).map((p) => ({ x: X(p.t), y: Y(p.v) }));
  const lineYs = lines.map((l) => Y(l.value));
  // The "now" words own the top row of the plot; the line words start under it.
  const tops = labelTops(lineYs, LABEL_H, nowLabel || stale || offline ? LABEL_H + 2 : 0);
  const nowT = cursor ?? last?.t ?? null;
  // The value at the marker: the last reading at or before it.
  const at = nowT == null ? null : [...obs].reverse().find((p) => p.t <= nowT) ?? obs[0] ?? null;
  // Ticks right at an edge would collide with their neighbour's words: the edges are left bare.
  const ticks = xTicks(t0, t1, lang, height <= 200 ? 4 : 5).filter((k) => pct(k.t) >= 5 && pct(k.t) <= 95);
  const digits = hi < 10 ? 2 : hi < 100 ? 1 : 0;
  const nowStyle = { '--x': `${nowT == null ? 0 : pct(nowT)}%`, '--y': `${at ? Y(at.v) : 0}px` } as CSSProperties;

  return (
    <figure className={`rl${drawn ? ' is-drawn' : ''}${offline ? ' is-offline' : ''}${stale ? ' is-stale' : ''} ${className}`}>
      {children}
      <div className="rl-plot" style={{ height }}>
        <div className={`rl-box${veil ? ' has-veil' : ''}`} ref={box} role="img" aria-label={label}>
          <svg viewBox={`0 0 1000 ${height}`} preserveAspectRatio="none" aria-hidden="true" focusable="false">
            {yTicks([lo, hi]).map((v) => (
              <line key={v} className="rl-grid" x1="0" x2="1000" y1={Y(v)} y2={Y(v)} />
            ))}
            {lines.map((l, i) => (
              <line key={l.level} className={`rl-th lv-${l.level}`} x1="0" x2="1000" y1={lineYs[i]} y2={lineYs[i]} />
            ))}
            {fcPts.length > 1 && <path className="rl-fc" d={path(fcPts)} />}
            {stale && last && nowT != null && <path className="rl-gap" d={path([{ x: X(last.t), y: Y(last.v) }, { x: X(Math.max(nowT, last.t)), y: Y(last.v) }])} />}
            <g className="rl-obs-g">{obsPts.length > 1 && <path className="rl-obs" d={path(obsPts)} />}</g>
          </svg>
          {veil && nowT != null && <i className="rl-veil" style={nowStyle} aria-hidden="true" />}
          {lines.map((l, i) => (
            <span key={l.level} className={`rl-word lv-${l.level}${pulse === l.level ? ' is-pulse' : ''}`} style={{ top: tops[i] }} aria-hidden="true">
              {l.word}
            </span>
          ))}
          {nowT != null && (
            <div className={`rl-now${nowT != null && pct(nowT) < 14 ? ' is-start' : nowT != null && pct(nowT) > 86 ? ' is-end' : ''}`} style={nowStyle} aria-hidden="true">
              <i className="rl-hair" />
              {at && <i className="rl-dot" />}
              {(nowLabel || stale || offline) && <span className="rl-now-word">{offline ?? stale ?? nowLabel}</span>}
            </div>
          )}
        </div>
        <div className="rl-y" aria-hidden="true">
          {yTicks([lo, hi]).map((v) => (
            <span key={v} style={{ top: Y(v) }}>
              {fmtNumber(v, lang, digits)}
            </span>
          ))}
        </div>
      </div>
      <div className="rl-x" aria-hidden="true">
        {ticks.map((k) => (
          <span key={k.t} style={{ left: `${pct(k.t)}%` }} className={pct(k.t) < 10 ? 'is-first' : pct(k.t) > 90 ? 'is-last' : undefined}>
            <b>{k.time}</b>
            {k.date && <small>{k.date}</small>}
          </span>
        ))}
      </div>
    </figure>
  );
}

export interface LadderRow {
  value: number;
  level?: Level;
  /** "चेतावनी" or "अभी". */
  word: string;
  /** What it means: "खेत, रास्ते डूबते हैं". */
  note?: string;
  now?: boolean;
}

/** C9: the same lines as a list, highest first, with "now" in its place. The chart's accessible twin. */
export function ThresholdLadder({ rows, unit, label }: { rows: LadderRow[]; unit: string; label: string }) {
  const { lang } = useT();
  const sorted = [...rows].sort((a, b) => b.value - a.value || (a.now ? -1 : 1));
  const digits = Math.max(...rows.map((r) => r.value)) < 10 ? 2 : 1;
  return (
    <ol className="rl-ladder" aria-label={label}>
      {sorted.map((r) => (
        <li key={`${r.word}-${r.value}`} className={`${r.level ? `lv-${r.level}` : ''}${r.now ? ' is-now' : ''}`}>
          <span className="rl-l-v">
            {fmtNumber(r.value, lang, digits)} {unit}
          </span>
          <span className="rl-l-w">{r.word}</span>
          {r.note && <span className="rl-l-n">{r.note}</span>}
        </li>
      ))}
    </ol>
  );
}
