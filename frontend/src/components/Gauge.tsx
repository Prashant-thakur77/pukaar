import { useInView } from '../hooks/useMotion';
import { dict } from '../i18n';
import type { Level } from '../types';

interface Props {
  value: number | null;
  bands: { watch: number; warning: number; critical: number };
  unit: string;
  label: string;
}

/** Value against Watch / Warning / Critical bands. Fills on scroll-in; ticks fade after. */
export function Gauge({ value, bands, unit, label }: Props) {
  const { ref, inView } = useInView<HTMLDivElement>(0.3);
  const max = Math.max(bands.critical * 1.3, (value ?? 0) * 1.08);
  const pct = (v: number) => `${Math.min(100, (v / max) * 100)}%`;
  const zones: { from: number; to: number; level: Level }[] = [
    { from: 0, to: bands.watch, level: 'normal' },
    { from: bands.watch, to: bands.warning, level: 'watch' },
    { from: bands.warning, to: bands.critical, level: 'warning' },
    { from: bands.critical, to: max, level: 'critical' },
  ];
  return (
    <div ref={ref} className={`gauge${inView ? ' is-in' : ''}`} role="img" aria-label={`${label}: ${value ?? '—'} ${unit}. Watch ${bands.watch}, Warning ${bands.warning}, Critical ${bands.critical} ${unit}.`}>
      <div className="g-track">
        {zones.map((z) => (
          <span key={z.level} className={`g-zone lv-${z.level}`} style={{ left: pct(z.from), width: `calc(${pct(z.to)} - ${pct(z.from)})` }} />
        ))}
        {value != null && <span className="g-fill" style={{ width: pct(value) }} />}
        {value != null && <span className="g-value" style={{ left: pct(value) }} />}
      </div>
      <div className="g-ticks" aria-hidden="true">
        {(['watch', 'warning', 'critical'] as const).map((l, i) => (
          <span key={l} className={`g-tick lv-${l}`} style={{ left: pct(bands[l]), transitionDelay: `${900 + i * 100}ms` }}>
            <b>{bands[l]}</b>
            <i>{dict[`level.${l}`].en}</i>
          </span>
        ))}
      </div>
    </div>
  );
}
