import { type ReactNode, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, CloudOff, Mountain, Phone } from 'lucide-react';
import { dict, levelWord, useT } from '../i18n';
import { LEVEL_ICON } from '../lib/levels';
import { istClock, isStale, levelStep, minutesSince, placeLine, type SafePlaceNow } from '../lib/villageNow';
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
  const label = unknown
    ? lang === 'hi' ? 'स्तर पता नहीं: डेटा नहीं मिल रहा' : 'Level unknown: no data'
    : lang === 'hi' ? `स्तर ${step} में से 4: ${levelWord(level, 'hi')}` : `Level ${step} of 4: ${levelWord(level, 'en')}`;
  return (
    <span className="lv-meter" role="img" aria-label={label}>
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

/**
 * "आख़िरी जाँच 03:10 IST · 4 मिनट पहले". Older than an hour, it says the information is old; from the phone's
 * copy with no signal, it says so and gives the time of that copy.
 */
export function Freshness({ at, offline = false, every = false, next = false }: { at: string | null; offline?: boolean; every?: boolean; next?: boolean }) {
  const { lang } = useT();
  const now = useMinuteTick();
  const clock = istClock(at);
  const mins = minutesSince(at, now);
  const stale = isStale(at, now);
  const hi = lang === 'hi';
  if (!clock) {
    return <p className="fresh">{hi ? 'अभी कोई जाँच नहीं मिली' : 'No check received yet'}</p>;
  }
  const ago =
    mins == null ? '' : mins < 1 ? (hi ? 'अभी' : 'just now') : mins < 60 ? (hi ? `${mins} मिनट पहले` : `${mins} min ago`) : hi ? `${Math.round(mins / 60)} घंटे पहले` : `${Math.round(mins / 60)} h ago`;
  // The sweep runs every 15 minutes: the next one is due 15 minutes after the last.
  const nextIn = next && mins != null && mins < 15 ? 15 - mins : null;
  return (
    <p className={`fresh${stale ? ' is-stale' : ''}${offline ? ' is-offline' : ''}`}>
      {offline && (
        <span className="fresh-chip">
          <CloudOff aria-hidden="true" /> {hi ? 'इंटरनेट नहीं है' : 'No internet'}
        </span>
      )}
      {stale && !offline && <span className="fresh-chip">{hi ? 'पुरानी जानकारी' : 'Old information'}</span>}
      <span>
        {offline ? (hi ? `आख़िरी जानकारी ${clock} की` : `Last information from ${clock}`) : hi ? `आख़िरी जाँच ${clock}` : `Last checked ${clock}`}
        {ago && <> · {ago}</>}
        {every && !stale && !offline && <> · {hi ? 'हर 15 मिनट जाँच' : 'checked every 15 minutes'}</>}
        {nextIn != null && nextIn > 0 && !offline && <> · {hi ? `अगली ${nextIn} मिनट में` : `next in ${nextIn} min`}</>}
      </span>
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
  const word = unknown ? (lang === 'hi' ? 'डेटा नहीं मिल रहा' : 'No data') : dict[`level.${level}`].hi;
  const en = unknown ? 'No data' : dict[`level.${level}`].en;
  return (
    <section className={`lvb lv-${shown}`} aria-labelledby={id} aria-live={level === 'critical' ? 'assertive' : 'polite'} aria-atomic="true">
      <div className="lvb-head">
        <Icon className="lvb-icon" aria-hidden="true" />
        <p className="lvb-word">
          <span lang="hi">{word}</span>
        </p>
        <LevelMeter level={level} unknown={unknown} />
      </div>
      {lang === 'en' ? (
        <p className="lvb-sub" lang="en">
          {unknown ? 'No data · do not rely on “Normal”' : `${en} · ${means.en}`}
        </p>
      ) : (
        <p className="lvb-sub">
          {!unknown && <span lang="en">{en}</span>}
          {!unknown && <span aria-hidden="true"> · </span>}
          <span lang="hi">{unknown ? '‘सामान्य’ पर भरोसा न करें' : means.hi}</span>
        </p>
      )}
      <H className="lvb-place" id={id}>
        {title}
      </H>
      {why && <p className="lvb-why">{why}</p>}
      {children}
    </section>
  );
}

/** C3: at most three numbered lines, Hindi first and the English under it. */
export function ActionList({ lines, level, children }: { lines: ActionLine[]; level: BannerLevel; children?: ReactNode }) {
  const { t } = useT();
  return (
    <section className={`acts lv-${level}`} aria-labelledby="acts-h">
      <h2 id="acts-h" className="acts-h">
        {t('village.do')}
      </h2>
      <ol className="acts-list">
        {lines.slice(0, 3).map((l) => (
          <li key={l.en}>
            <span className="acts-hi" lang="hi">
              {l.hi}
            </span>
            <span className="acts-en" lang="en">
              {l.en}
            </span>
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
            <Phone aria-hidden="true" /> <span lang="hi">112 पर कॉल करें</span>
          </a>
        )}
        <a href={whereHref} className="sab-btn sab-where">
          <Mountain aria-hidden="true" />
          <span className="sab-text">
            <span lang="hi">कहाँ जाएँ</span>
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
export function VillageRows({ villages, label }: { villages: RowVillage[]; label: string }) {
  const sorted = [...villages].sort((a, b) => levelStep(b.level) - levelStep(a.level) || a.name.localeCompare(b.name));
  return (
    <ul className="vrows" aria-label={label}>
      {sorted.map((v) => {
        const shown: BannerLevel = v.unknown ? 'nodata' : v.level;
        const Icon = v.unknown ? CloudOff : LEVEL_ICON[v.level];
        return (
          <li key={v.id}>
            <Link to={`/village/${v.id}`} className={`vrow lv-${shown}`}>
              <span className="vrow-name">
                <span lang="hi">{v.name_hi}</span> <span className="vrow-en" lang="en">{v.name}</span>
              </span>
              <span className="vrow-level">
                <Icon aria-hidden="true" />
                <span lang="hi">{v.unknown ? 'डेटा नहीं' : dict[`level.${v.level}`].hi}</span>
              </span>
              <ChevronRight aria-hidden="true" className="vrow-go" />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
