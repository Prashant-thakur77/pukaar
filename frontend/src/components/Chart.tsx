import { useId, useMemo, useState } from 'react';
import type { ChartSpec } from '../types';

/*
 * Draws a ChartSpec returned by the analyst agent as plain SVG. The spec is
 * data only; nothing from the model is ever executed. Series colours follow a
 * fixed order (validated for CVD with the dataviz palette check) and never
 * reuse the four risk-level colours.
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

export function Chart({ spec }: { spec: ChartSpec }) {
  const id = useId();
  const [hover, setHover] = useState<number | null>(null);
  const series = spec.series.slice(0, 4); // more would fold into "other"; agent sends few
  const xs = useMemo(() => {
    const seen: string[] = [];
    for (const s of series) for (const p of s.points) if (!seen.includes(String(p.x))) seen.push(String(p.x));
    return seen;
  }, [series]);
  const values = series.flatMap((s) => s.points.map((p) => p.y)).filter((v) => Number.isFinite(v));
  const minV = Math.min(0, ...values);
  const maxV = niceMax(Math.max(0, ...values));
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
                  return (
                    <path
                      key={`${s.name}-${x}`}
                      className={`bar s${si + 1}${hover === i ? ' is-hover' : ''}`}
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
          {xs.map((x, i) => (
            <rect key={x} className="hit" x={M.l + band * i} y={M.t} width={band} height={ih} onMouseEnter={() => setHover(i)} />
          ))}
        </svg>
        {hover !== null && (
          <div className="chart-tip" style={{ left: `${(xc(hover) / W) * 100}%` }} role="presentation">
            <strong>{xs[hover]}</strong>
            {series.map((s, i) => (
              <span key={s.name}>
                <i className={`swatch s${i + 1}`} aria-hidden="true" /> {series.length > 1 ? `${s.name}: ` : ''}
                <b>{valueAt(s, xs[hover]) ?? '—'}</b>
              </span>
            ))}
          </div>
        )}
      </div>
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
              </tr>
            </thead>
            <tbody>
              {xs.map((x) => (
                <tr key={x}>
                  <th scope="row">{x}</th>
                  {series.map((s) => (
                    <td key={s.name}>{valueAt(s, x) ?? '—'}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
