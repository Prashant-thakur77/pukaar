import { useLayoutEffect, useState, type CSSProperties, type ElementType, type ReactNode } from 'react';
import { prefersReducedMotion, useInView } from '../hooks/useMotion';

interface Props {
  as?: ElementType;
  children: ReactNode;
  className?: string;
  /** Milliseconds before this one rises, for a row that comes in one after another. */
  delay?: number;
  variant?: 'rise' | 'slide';
  style?: CSSProperties;
  id?: string;
}

/**
 * Rises (or slides) its children in once when they scroll into view. Only what starts below the fold is held back,
 * and only with motion allowed, so a first screen, a print or a phone without IntersectionObserver never shows a
 * blank section; under reduced motion everything is simply there.
 */
export function Reveal({ as: Tag = 'div', children, className = '', delay = 0, variant = 'rise', style, id }: Props) {
  const { ref, inView } = useInView<HTMLElement>(0.15);
  const [armed, setArmed] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || prefersReducedMotion() || typeof IntersectionObserver === 'undefined') return;
    if (el.getBoundingClientRect().top > window.innerHeight) setArmed(true);
  }, [ref]);
  const cls = [className, armed && `reveal reveal-${variant}`, armed && inView && 'is-in'].filter(Boolean).join(' ');
  return (
    <Tag ref={ref} id={id} className={cls || undefined} style={armed ? ({ ...style, '--d': `${delay}ms` } as CSSProperties) : style}>
      {children}
    </Tag>
  );
}
