import { useInView } from '../hooks/useMotion';
import { dict, useT } from '../i18n';
import type { Level } from '../types';

interface Props {
  value: number | null;
  bands: { watch: number; warning: number; critical: number };
  unit: string;
  label: string;
}

/** Units in Hindi; the m³/s symbol reads the same in both. */
const UNIT_HI: Record<string, string> = { mm: 'मिमी', cm: 'सेमी', m: 'मी' };

/** Value against Watch / Warning / Critical bands, in the page's language. Fills on scroll-in; ticks fade after. */
export function Gauge({ value, bands, unit: unitEn, label }: Props) {
  const { lang } = useT();
  const unit = lang === 'hi' ? UNIT_HI[unitEn] ?? unitEn : unitEn;
  const w = (l: 'watch' | 'warning' | 'critical') => dict[`level.${l}`][lang];
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
    <div ref={ref} className={`gauge${inView ? ' is-in' : ''}`} role="img" aria-label={`${label}: ${value ?? '—'} ${unit}. ${w('watch')} ${bands.watch}, ${w('warning')} ${bands.warning}, ${w('critical')} ${bands.critical} ${unit}.`}>
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
            <i>{w(l)}</i>
          </span>
        ))}
      </div>
    </div>
  );
}
