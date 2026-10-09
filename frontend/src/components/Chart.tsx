import { useId, useMemo, useState } from 'react';
import { LEVEL_ICON } from '../lib/levels';
import { LEVELS, type ChartSpec, type Level } from '../types';

/*
 * Draws a ChartSpec returned by the analyst agent as plain SVG. The spec is
 * data only; nothing from the model is ever executed. Series colours follow a
 * fixed order (validated for CVD with the dataviz palette check) and never
 * reuse the four risk-level colours, except one case: a single-series bar
 * chart of villages is coloured by each village's level, with icon + word in
 * the legend so the colour is never the only cue.
 */

const W = 640;
const H = 280;
const M = { t: 16, r: 16, b: 46, l: 52 };

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
  return step * p;
}

function fmt(v: number): string {
  if (Math.abs(v) >= 1000) return `${Math.round(v / 100) / 10}k`;
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

/** "% of warning threshold" charts get a 100 % reference line. */
const isWarningShare = (spec: Pick<ChartSpec, 'y_label'>) => /%\s*of\s*warning/i.test(spec.y_label ?? '');

interface ChartProps {
  spec: ChartSpec;
  /** Level of the village a bar stands for; single-series bar charts are then coloured by level. */
  levelOf?: (x: string) => Level | undefined;
  /** Words for the level legend, e.g. "Critical". */
  levelWord?: (l: Level) => string;
  /** Label of the 100 % reference line. */
  thresholdLabel?: string;
  /** One line under the chart. */
  note?: string;
}

export function Chart({ spec, levelOf, levelWord, thresholdLabel = 'warning threshold', note }: ChartProps) {
  const id = useId();
  const [hover, setHover] = useState<number | null>(null);
  const series = spec.series.slice(0, 4); // more would fold into "other"; agent sends few
  const xs = useMemo(() => {
    const seen: string[] = [];
    for (const s of series) for (const p of s.points) if (!seen.includes(String(p.x))) seen.push(String(p.x));
    return seen;
  }, [series]);
  const values = series.flatMap((s) => s.points.map((p) => p.y)).filter((v) => Number.isFinite(v));
  const refLine = isWarningShare(spec) ? 100 : null;
  const minV = Math.min(0, ...values);
  const maxV = niceMax(Math.max(0, refLine != null ? refLine * 1.1 : 0, ...values));
  const byLevel = spec.type === 'bar' && series.length === 1 && Boolean(levelOf) && xs.length > 0 && xs.every((x) => levelOf?.(x));
  const lvOf = (x: string): Level | undefined => (byLevel ? levelOf?.(x) : undefined);
  const shownLevels = byLevel ? LEVELS.filter((l) => xs.some((x) => levelOf?.(x) === l)) : [];
  const iw = W - M.l - M.r;
  const ih = H - M.t - M.b;
  const y = (v: number) => M.t + ih - ((v - minV) / (maxV - minV || 1)) * ih;
  const band = iw / Math.max(1, xs.length);
  const xc = (i: number) => M.l + band * i + band / 2;
  const ticks = Array.from({ length: 5 }, (_, i) => minV + ((maxV - minV) * i) / 4);
  const labelEvery = Math.ceil(xs.length / 8);
  const valueAt = (s: (typeof series)[number], x: string) => s.points.find((p) => String(p.x) === x)?.y;

  if (!xs.length) return null;

  return (
    <figure className="chart" aria-labelledby={`${id}-t`}>
      <figcaption id={`${id}-t`} className="chart-title">
        {spec.title}
      </figcaption>
      {byLevel && (
        <ul className="chart-legend" aria-label={`${spec.series[0]?.name ?? ''}: colour = level`}>
          {shownLevels.map((l) => {
            const Icon = LEVEL_ICON[l];
            return (
              <li key={l} className={`lv-${l}`}>
                <span className={`swatch lv-${l}`} aria-hidden="true" />
                <Icon aria-hidden="true" className="legend-icon" />
                {levelWord ? levelWord(l) : l}
              </li>
            );
          })}
          {refLine != null && (
            <li>
              <span className="swatch is-ref" aria-hidden="true" />
              {thresholdLabel} (100%)
            </li>
          )}
        </ul>
      )}
      {!byLevel && refLine != null && (
        <ul className="chart-legend">
          <li>
            <span className="swatch is-ref" aria-hidden="true" />
            {thresholdLabel} (100%)
          </li>
        </ul>
      )}
      {series.length > 1 && (
        <ul className="chart-legend">
          {series.map((s, i) => (
            <li key={s.name}>
              <span className={`swatch s${i + 1} ${spec.type === 'line' ? 'is-line' : ''}`} aria-hidden="true" />
              {s.name}
            </li>
          ))}
        </ul>
      )}
      <div className="chart-plot">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${spec.title}. ${spec.y_label} by ${spec.x_label}. Data table below.`} onMouseLeave={() => setHover(null)}>
          {ticks.map((tv) => (
            <g key={tv}>
              <line className="grid" x1={M.l} x2={W - M.r} y1={y(tv)} y2={y(tv)} />
              <text className="tick" x={M.l - 8} y={y(tv)} dy="0.32em" textAnchor="end">
                {fmt(tv)}
              </text>
            </g>
          ))}
          {xs.map((x, i) =>
            i % labelEvery === 0 ? (
              <text key={x} className="tick" x={xc(i)} y={H - M.b + 18} textAnchor="middle">
                {x.length > 12 ? `${x.slice(0, 11)}…` : x}
              </text>
            ) : null,
          )}
          <text className="axis-label" x={M.l + iw / 2} y={H - 6} textAnchor="middle">
            {spec.x_label}
          </text>
          <text className="axis-label" transform={`translate(14 ${M.t + ih / 2}) rotate(-90)`} textAnchor="middle">
            {spec.y_label}
          </text>
          {hover !== null && spec.type === 'line' && <line className="crosshair" x1={xc(hover)} x2={xc(hover)} y1={M.t} y2={M.t + ih} />}
          {spec.type === 'bar'
            ? series.map((s, si) => {
                const gw = Math.min(band * 0.72, 22 * series.length + 2 * (series.length - 1));
                const bw = (gw - 2 * (series.length - 1)) / series.length;
                return xs.map((x, i) => {
                  const v = valueAt(s, x);
                  if (v == null) return null;
                  const x0 = xc(i) - gw / 2 + si * (bw + 2);
                  const top = y(Math.max(0, v));
                  const h = Math.max(1, Math.abs(y(v) - y(0)));
                  const r = Math.min(4, bw / 2, h);
                  const lv = lvOf(x);
                  return (
                    <path
                      key={`${s.name}-${x}`}
                      className={`bar ${lv ? `lv-${lv}` : `s${si + 1}`}${hover === i ? ' is-hover' : ''}`}
                      d={`M${x0},${top + h} V${top + r} Q${x0},${top} ${x0 + r},${top} H${x0 + bw - r} Q${x0 + bw},${top} ${x0 + bw},${top + r} V${top + h} Z`}
                    />
                  );
                });
              })
            : series.map((s, si) => {
                const pts = xs.map((x, i) => [xc(i), valueAt(s, x)] as const).filter((p): p is readonly [number, number] => p[1] != null);
                return (
                  <g key={s.name}>
                    <path className={`line s${si + 1}`} d={pts.map((p, i) => `${i ? 'L' : 'M'}${p[0]},${y(p[1])}`).join(' ')} />
                    {pts.length <= 24 &&
                      pts.map((p) => <circle key={p[0]} className={`dot s${si + 1}`} cx={p[0]} cy={y(p[1])} r={hover !== null && xc(hover) === p[0] ? 5 : 3.5} />)}
                  </g>
                );
              })}
          {refLine != null && (
            <g className="ref">
              <line x1={M.l} x2={W - M.r} y1={y(refLine)} y2={y(refLine)} />
              <text x={W - M.r} y={y(refLine) - 6} textAnchor="end">
                {thresholdLabel}
              </text>
            </g>
          )}
          {xs.map((x, i) => (
            <rect key={x} className="hit" x={M.l + band * i} y={M.t} width={band} height={ih} onMouseEnter={() => setHover(i)} />
          ))}
        </svg>
        {hover !== null && (
          <div className="chart-tip" style={{ left: `${(xc(hover) / W) * 100}%` }} role="presentation">
            <strong>{xs[hover]}</strong>
            {series.map((s, i) => (
              <span key={s.name}>
                <i className={`swatch ${lvOf(xs[hover]) ? `lv-${lvOf(xs[hover])}` : `s${i + 1}`}`} aria-hidden="true" /> {series.length > 1 ? `${s.name}: ` : ''}
                <b>{valueAt(s, xs[hover]) ?? '—'}</b>
                {lvOf(xs[hover]) && levelWord ? ` · ${levelWord(lvOf(xs[hover])!)}` : ''}
              </span>
            ))}
          </div>
        )}
      </div>
      {note && <p className="chart-note small muted">{note}</p>}
      <details className="chart-table">
        <summary>
          {spec.y_label} · {xs.length} {xs.length === 1 ? 'row' : 'rows'} (table)
        </summary>
        <div className="table-wrap" tabIndex={0} role="region" aria-label={`${spec.title} data`}>
          <table>
            <thead>
              <tr>
                <th scope="col">{spec.x_label}</th>
                {series.map((s) => (
                  <th key={s.name} scope="col">
                    {s.name}
                  </th>
                ))}
                {byLevel && <th scope="col">Level</th>}
              </tr>
            </thead>
            <tbody>
              {xs.map((x) => (
                <tr key={x}>
                  <th scope="row">{x}</th>
                  {series.map((s) => (
                    <td key={s.name}>{valueAt(s, x) ?? '—'}</td>
                  ))}
                  {byLevel && <td>{levelWord ? levelWord(lvOf(x)!) : lvOf(x)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
