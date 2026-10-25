import { type ReactNode, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, CloudOff, Mountain, Phone } from 'lucide-react';
import { dict, useT } from '../i18n';
import { LEVEL_ICON } from '../lib/levels';
import { freshnessText, istClock, levelStep, meterLabel, placeLine } from '../lib/answerText';
import type { SafePlaceNow } from '../lib/villageNow';
import type { ActionLine } from '../lib/actions';
import type { Level } from '../types';
import './answer.css';

/*
 * The answer, the same on every page that shows one village or the five: the level banner (C1), the
 * freshness stamp (C6), "what to do now" (C3), the sticky action bar (C4) and the village rows (C7).
 * Everything here paints in its final state: no entrance motion, no skeleton.
 */

export type BannerLevel = Level | 'nodata';

const STEPS: Level[] = ['normal', 'watch', 'warning', 'critical'];

/** The four-step scale as a meter: "स्तर 3 में से 4: चेतावनी". Colour is never the only signal. */
export function LevelMeter({ level, unknown = false }: { level: Level; unknown?: boolean }) {
  const { lang } = useT();
  const step = levelStep(level);
  return (
    <span className="lv-meter" role="img" aria-label={meterLabel(level, unknown, lang)}>
      {STEPS.map((l, i) => (
        <i key={l} className={!unknown && i < step ? 'is-on' : ''} />
      ))}
    </span>
  );
}

function useMinuteTick(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);
  return now;
}

/** C6, the freshness stamp: the words come from answerText.ts, the same as the boot painter's. */
export function Freshness({ at, offline = false, every = false, next = false }: { at: string | null; offline?: boolean; every?: boolean; next?: boolean }) {
  const { lang } = useT();
  const now = useMinuteTick();
  const f = freshnessText(at, lang, { offline, every, next }, now);
  if (!istClock(at)) return <p className="fresh">{f.line}</p>;
  return (
    <p className={`fresh${f.stale ? ' is-stale' : ''}${f.offline ? ' is-offline' : ''}`}>
      {f.chip && (
        <span className="fresh-chip">
          {f.offline ? (
            <>
              <CloudOff aria-hidden="true" /> {f.chip}
            </>
          ) : (
            f.chip
          )}
        </span>
      )}
      <span>{f.line}</span>
    </p>
  );
}

interface BannerProps {
  level: Level;
  unknown?: boolean;
  means: ActionLine;
  /** The page's h1: the village, or the five. */
  title: ReactNode;
  why?: ReactNode;
  children?: ReactNode;
  id?: string;
  /** h1 on a village page; h2 when several banners share a page. */
  heading?: 'h1' | 'h2';
}

/** C1: the level first, in words and icon, then where, why and when it was checked. */
export function LevelBanner({ level, unknown = false, means, title, why, children, id, heading = 'h1' }: BannerProps) {
  const H = heading;
  const { lang } = useT();
  const shown: BannerLevel = unknown ? 'nodata' : level;
  const Icon = unknown ? CloudOff : LEVEL_ICON[level];
  const hi = lang === 'hi';
  const word = unknown ? (hi ? 'डेटा नहीं मिल रहा' : 'No data') : dict[`level.${level}`][lang];
  return (
    <section className={`lvb lv-${shown}`} aria-labelledby={id} aria-live={level === 'critical' ? 'assertive' : 'polite'} aria-atomic="true">
      <div className="lvb-head">
        <Icon className="lvb-icon" aria-hidden="true" />
        <p className="lvb-word">
          <span>{word}</span>
        </p>
        <LevelMeter level={level} unknown={unknown} />
      </div>
      <p className="lvb-sub">{unknown ? (hi ? '‘सामान्य’ पर भरोसा न करें' : 'Do not rely on “Normal”') : means[lang]}</p>
      <H className="lvb-place" id={id}>
        {title}
      </H>
      {why && <p className="lvb-why">{why}</p>}
      {children}
    </section>
  );
}

/** C3: at most three numbered lines, in the page's language. */
export function ActionList({ lines, level, children }: { lines: ActionLine[]; level: BannerLevel; children?: ReactNode }) {
  const { t, lang } = useT();
  return (
    <section className={`acts lv-${level}`} aria-labelledby="acts-h">
      <h2 id="acts-h" className="acts-h">
        {t('village.do')}
      </h2>
      <ol className="acts-list">
        {lines.slice(0, 3).map((l) => (
          <li key={l.en}>
            <span className="acts-hi">{l[lang]}</span>
          </li>
        ))}
      </ol>
      {children && <div className="acts-more">{children}</div>}
    </section>
  );
}

/**
 * C4: at Warning and Critical, the next step stays in reach of the thumb. Warning: where to go. Critical: 112
 * and where to go. Nothing at Normal or Watch. A spacer of the same height keeps the last content visible.
 */
export function StickyActionBar({ level, place, whereHref = '#where' }: { level: Level; place: SafePlaceNow | null; whereHref?: string }) {
  const { t, lang } = useT();
  if (level !== 'warning' && level !== 'critical') return null;
  const line = placeLine(place, lang);
  return (
    <>
      <div className="sab-spacer" aria-hidden="true" />
      <nav className={`sab lv-${level}`} aria-label={lang === 'hi' ? 'अभी के लिए' : 'Right now'}>
        {level === 'critical' && (
          <a href="tel:112" className="sab-btn sab-112" aria-label={t('shell.call112.aria')}>
            <Phone aria-hidden="true" /> <span>{lang === 'hi' ? '112 पर कॉल करें' : 'Call 112'}</span>
          </a>
        )}
        <a href={whereHref} className="sab-btn sab-where">
          <Mountain aria-hidden="true" />
          <span className="sab-text">
            <span>{lang === 'hi' ? 'कहाँ जाएँ' : 'Where to go'}</span>
            {line && level === 'warning' && <span className="sab-place"> · {line}</span>}
          </span>
          <ChevronRight aria-hidden="true" className="sab-go" />
        </a>
      </nav>
    </>
  );
}

export interface RowVillage {
  id: string;
  name: string;
  name_hi: string;
  level: Level;
  unknown?: boolean;
}

/** C7: one 56 px row per village; the whole row is the link. Highest level first, then by name. */
export function VillageRows({ villages, label, hot = null, onHot, sub }: { villages: RowVillage[]; label: string; hot?: string | null; onHot?: (id: string | null) => void; sub?: Record<string, ReactNode> }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  const sorted = [...villages].sort((a, b) => levelStep(b.level) - levelStep(a.level) || a.name.localeCompare(b.name));
  return (
    <ul className="vrows" aria-label={label}>
      {sorted.map((v) => {
        const shown: BannerLevel = v.unknown ? 'nodata' : v.level;
        const Icon = v.unknown ? CloudOff : LEVEL_ICON[v.level];
        return (
          <li key={v.id}>
            <Link
              to={`/village/${v.id}`}
              className={`vrow lv-${shown}${hot === v.id ? ' is-hot' : ''}`}
              onPointerEnter={onHot && (() => onHot(v.id))}
              onPointerLeave={onHot && (() => onHot(null))}
              onFocus={onHot && (() => onHot(v.id))}
              onBlur={onHot && (() => onHot(null))}
            >
              <span className="vrow-name">
                <strong lang={lang}>{hi ? v.name_hi || v.name : v.name}</strong>
                {sub?.[v.id] && <span className="vrow-sub">{sub[v.id]}</span>}
              </span>
              <span className="vrow-level">
                <Icon aria-hidden="true" />
                <span>{v.unknown ? dict['data.badge.none'][lang] : dict[`level.${v.level}`][lang]}</span>
              </span>
              <ChevronRight aria-hidden="true" className="vrow-go" />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
