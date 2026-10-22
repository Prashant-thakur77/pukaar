import { fmtNumber } from '../lib/format';
import type { Lang } from '../store';

/**
 * A number, shown at its value. Live numbers never count up: a change is announced, not animated
 * (the redesign's motion rules). The name stays so story pages can bring a count back later.
 */
export function CountUp({ value, lang, className }: { value: number | null | undefined; lang: Lang; className?: string }) {
  return <span className={className ? `countup ${className}` : 'countup'}>{fmtNumber(value ?? null, lang)}</span>;
}
