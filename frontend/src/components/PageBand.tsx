import type { ReactNode } from 'react';

/** A big Anton headline whose last word is set in gold. */
export function Headline({ text, className = '' }: { text: string; className?: string }) {
  const words = text.trim().split(/\s+/);
  const last = words.pop() ?? '';
  return (
    <span className={`hl-split ${className}`}>
      {words.length > 0 && <>{words.join(' ')} </>}
      <em className="hl-gold">{last}</em>
    </span>
  );
}

export type Stat = { key: string; value: ReactNode; label: ReactNode; tone?: 'alert' };

/** A row of hero numbers: huge Anton numeral, thin top rule, tiny caption. */
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
 * The page header band: a full-width dark (or cream) block with a gold eyebrow,
 * a huge uppercase title and a one-line lead. Children render under the lead.
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
          <p className="pg-eyebrow">
            {live && <span className="live-dot" aria-hidden="true" />}
            {eyebrow}
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
