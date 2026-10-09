import { useId } from 'react';

interface Props {
  values: (number | null)[];
  label: string;
  unit?: string;
  marks?: { value: number; className: string; label: string }[];
  height?: number;
}

/** Small area line with optional threshold marks; draws in on mount. */
export function Sparkline({ values, label, unit = '', marks = [], height = 96 }: Props) {
  const id = useId();
  const W = 320;
  const H = height;
  const pts = values.map((v, i) => [i, v] as const).filter((p): p is readonly [number, number] => p[1] != null && Number.isFinite(p[1]));
  if (pts.length < 2) return <p className="muted small">—</p>;
  const all = [...pts.map((p) => p[1]), ...marks.map((m) => m.value)];
  const max = Math.max(...all) * 1.08 || 1;
  const min = Math.min(0, ...all);
  const x = (i: number) => 4 + (i / (values.length - 1)) * (W - 8);
  const y = (v: number) => 6 + (1 - (v - min) / (max - min || 1)) * (H - 12);
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');
  const last = pts[pts.length - 1];
  const area = `${d} L${x(last[0])},${H} L${x(pts[0][0])},${H} Z`;
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`${label}: latest ${last[1]}${unit}, peak ${Math.max(...pts.map((p) => p[1]))}${unit}`}>
      <defs>
        <linearGradient id={`${id}-g`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="currentColor" stopOpacity="0.28" />
          <stop offset="1" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      {marks.map((m) => (
        <g key={m.label}>
          <line className={`spark-mark ${m.className}`} x1={0} x2={W} y1={y(m.value)} y2={y(m.value)} vectorEffect="non-scaling-stroke" />
        </g>
      ))}
      <path d={area} fill={`url(#${id}-g)`} className="spark-area" />
      <path d={d} className="spark-line" pathLength={1} vectorEffect="non-scaling-stroke" />
      <circle cx={x(last[0])} cy={y(last[1])} r={3.5} className="spark-dot" />
    </svg>
  );
}
