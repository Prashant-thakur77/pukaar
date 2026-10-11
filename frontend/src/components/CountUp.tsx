import { useCountUp, useInView } from '../hooks/useMotion';
import { fmtNumber } from '../lib/format';
import type { Lang } from '../store';

/**
 * A number that counts up once it scrolls into view.
 *
 * The page holds the final value exactly once, as text in the screen-reader span, so copying the
 * number and reading it aloud both give the real value. The animated frames are drawn by CSS from
 * `data-n` (`.countup-frame::before`): generated content is never copied, and the span is
 * aria-hidden, so the running digits are not announced either.
 */
export function CountUp({ value, lang, className }: { value: number | null | undefined; lang: Lang; className?: string }) {
  const target = value ?? null;
  const { ref, inView } = useInView<HTMLSpanElement>(0.4);
  const shown = useCountUp(target, inView);
  return (
    <span ref={ref} className={className ? `countup ${className}` : 'countup'}>
      <span className="countup-frame" aria-hidden="true" data-n={fmtNumber(shown, lang)} />
      <span className="sr-only">{fmtNumber(target, lang)}</span>
    </span>
  );
}
