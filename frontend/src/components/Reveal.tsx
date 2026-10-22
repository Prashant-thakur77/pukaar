import type { CSSProperties, ElementType, ReactNode } from 'react';

interface Props {
  as?: ElementType;
  children: ReactNode;
  className?: string;
  /** Kept for the callers; nothing waits any more. */
  delay?: number;
  variant?: 'rise' | 'slide';
  style?: CSSProperties;
  id?: string;
}

/**
 * Content is visible from the first paint: nothing is hidden until it scrolls into view (a blank section in
 * a screenshot, a print or a slow phone reads as a broken page). A plain wrapper, left in place as the seam
 * for the story pages' scroll moments, which add motion only from JavaScript and only under
 * prefers-reduced-motion: no-preference.
 */
export function Reveal({ as: Tag = 'div', children, className = '', style, id }: Props) {
  return (
    <Tag id={id} className={className || undefined} style={style}>
      {children}
    </Tag>
  );
}
