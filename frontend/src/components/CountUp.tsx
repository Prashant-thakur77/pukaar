import { useCountUp, useInView } from '../hooks/useMotion';
import { fmtNumber } from '../lib/format';
import type { Lang } from '../store';

export function CountUp({ value, lang, className }: { value: number | null; lang: Lang; className?: string }) {
  const { ref, inView } = useInView<HTMLSpanElement>(0.4);
  const shown = useCountUp(value, inView);
  return (
    <span ref={ref} className={className}>
      <span aria-hidden="true">{shown === null ? '—' : fmtNumber(shown, lang)}</span>
      <span className="sr-only">{value === null ? '—' : fmtNumber(value, lang)}</span>
    </span>
  );
}
