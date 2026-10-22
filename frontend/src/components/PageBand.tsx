import type { ReactNode } from 'react';
import { Lehar } from './Art';

/**
 * A headline as a plain statement. No word is set apart: in Hindi the last word is often grammar ("है",
 * "हुई"), and a gradient or italic word clips the matras above the headline bar.
 */
export function Headline({ text, className = '' }: { text: string; className?: string }) {
  return <span className={className || undefined}>{text}</span>;
}

export type Stat = { key: string; value: ReactNode; label: ReactNode; tone?: 'alert' };

/** A row of hero numbers: large serif numeral, thin top rule, short caption. */
export function StatStrip({ stats, className = '' }: { stats: Stat[]; className?: string }) {
  return (
    <ul className={`stat-strip ${className}`}>
      {stats.map((s) => (
        <li key={s.key} className={`stat${s.tone === 'alert' ? ' is-alert' : ''}`}>
          <span className="stat-num">{s.value}</span>
          <span className="stat-label">{s.label}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * The page header band: a soft gradient field (mist by day, the river at night) with an ornamented
 * kicker, a serif title and a one-line lead, and the valley drawn in line at its foot.
 * Children render under the lead.
 */
export function PageBand({
  eyebrow,
  title,
  lead,
  aside,
  children,
  tone = 'night',
  className = '',
  live = false,
}: {
  eyebrow: ReactNode;
  title: string;
  lead?: ReactNode;
  aside?: ReactNode;
  children?: ReactNode;
  tone?: 'night' | 'cream' | 'forest' | 'crimson';
  className?: string;
  live?: boolean;
}) {
  return (
    <header className={`pg-band pg-${tone} ${className}`}>
      <div className="wrap-wide pg-inner">
        <div className="pg-text">
          <p className="pg-eyebrow kicker">
            {live ? <span className="live-dot" aria-hidden="true" /> : <Lehar />}
            <span className="kicker-text">{eyebrow}</span>
          </p>
          <h1 className="pg-title">
            <Headline text={title} />
          </h1>
          {lead && <p className="pg-lead">{lead}</p>}
        </div>
        {aside && <div className="pg-aside">{aside}</div>}
      </div>
      {children && <div className="wrap-wide pg-extra">{children}</div>}
    </header>
  );
}
