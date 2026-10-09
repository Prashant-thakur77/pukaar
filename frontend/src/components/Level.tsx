import { useEffect, useRef, useState } from 'react';
import { dict } from '../i18n';
import { LEVEL_ICON } from '../lib/levels';
import type { Level } from '../types';

interface Props {
  level: Level;
  size?: 'sm' | 'md' | 'lg';
  /** Show both Hindi and English words (default). */
  both?: boolean;
  lang?: 'hi' | 'en';
}

/** Level is always icon + word + colour, never colour alone. Flashes when it changes. */
export function LevelBadge({ level, size = 'md', both = true, lang = 'en' }: Props) {
  const Icon = LEVEL_ICON[level];
  const key = `level.${level}` as const;
  const hi = dict[key].hi;
  const en = dict[key].en;
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
    <span className={`level-badge lv-${level} lb-${size}${flash ? ' is-flash' : ''}`} data-level={level}>
      <Icon className="lb-icon" aria-hidden="true" key={level} />
      {both ? (
        <span className="lb-words">
          <span lang="hi">{hi}</span>
          <span className="lb-sep" aria-hidden="true">·</span>
          <span lang="en">{en}</span>
        </span>
      ) : (
        <span className="lb-words" lang={lang}>
          {lang === 'hi' ? hi : en}
        </span>
      )}
    </span>
  );
}

export function LevelIcon({ level, className }: { level: Level; className?: string }) {
  const Icon = LEVEL_ICON[level];
  return <Icon className={className} aria-hidden="true" />;
}

export function LevelLegend() {
  const levels: Level[] = ['normal', 'watch', 'warning', 'critical'];
  return (
    <ul className="legend" aria-label="Levels / स्तर">
      {levels.map((l) => (
        <li key={l}>
          <LevelBadge level={l} size="sm" />
        </li>
      ))}
    </ul>
  );
}
