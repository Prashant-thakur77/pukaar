import { useEffect, useRef, useState } from 'react';
import { dict, useT } from '../i18n';
import { LEVEL_ICON } from '../lib/levels';
import { usePrefs, type Lang } from '../store';
import type { Level } from '../types';

interface Props {
  level: Level;
  size?: 'sm' | 'md' | 'lg';
  /** The word's language; the site's language when left out. */
  lang?: Lang;
  /** A ledger word: icon and word in the level's ink, no box. One pill per item at most. */
  plain?: boolean;
}

/** Level is always icon + word + colour, never colour alone. One word, in the page's language. Flashes when it changes. */
export function LevelBadge({ level, size = 'md', lang, plain = false }: Props) {
  const siteLang = usePrefs((s) => s.lang);
  const Icon = LEVEL_ICON[level];
  const word = dict[`level.${level}`][lang ?? siteLang];
  const prev = useRef(level);
  const [flash, setFlash] = useState(false);
  useEffect(() => {
    if (prev.current !== level) {
      prev.current = level;
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 700);
      return () => clearTimeout(t);
    }
  }, [level]);
  return (
    <span className={`level-badge lv-${level} lb-${size}${plain ? ' lb-plain' : ''}${flash ? ' is-flash' : ''}`} data-level={level}>
      <Icon className="lb-icon" aria-hidden="true" key={level} />
      <span className="lb-words" lang={lang ?? siteLang}>
        {word}
      </span>
    </span>
  );
}

export function LevelIcon({ level, className }: { level: Level; className?: string }) {
  const Icon = LEVEL_ICON[level];
  return <Icon className={className} aria-hidden="true" />;
}

export function LevelLegend() {
  const { lang } = useT();
  const levels: Level[] = ['normal', 'watch', 'warning', 'critical'];
  return (
    <ul className="legend" aria-label={lang === 'hi' ? 'स्तर' : 'Levels'}>
      {levels.map((l) => (
        <li key={l}>
          <LevelBadge level={l} size="sm" />
        </li>
      ))}
    </ul>
  );
}
