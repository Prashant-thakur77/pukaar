import type { CSSProperties, ElementType, ReactNode } from 'react';
import { useInView } from '../hooks/useMotion';

interface Props {
  as?: ElementType;
  children: ReactNode;
  className?: string;
  delay?: number;
  variant?: 'rise' | 'slide';
  style?: CSSProperties;
  id?: string;
}

/** Fades/rises children in once when scrolled into view. CSS handles reduced motion. */
export function Reveal({ as: Tag = 'div', children, className = '', delay = 0, variant = 'rise', style, id }: Props) {
  const { ref, inView } = useInView<HTMLElement>(0.15);
  return (
    <Tag
      ref={ref}
      id={id}
      className={`reveal reveal-${variant}${inView ? ' is-in' : ''} ${className}`}
      style={{ ...style, '--d': `${delay}ms` } as CSSProperties}
    >
      {children}
    </Tag>
  );
}
