/*
 * Gauge health and reading quality in plain words (services/gauge.py: health, quality, the
 * 2-of-3 rule and the rate-of-rise marker). Shared by the village page and the sensors board.
 */
import { levelWord } from '../i18n';
import type { Lang } from '../store';
import type { GaugeHealth, GaugeQuality, Level } from '../types';
import { isLevel, levelRank } from './levels';

const num = (v: number, lang: Lang, digits = 0) =>
  new Intl.NumberFormat(lang === 'hi' ? 'hi-IN' : 'en-IN', { maximumFractionDigits: digits }).format(v);

const QUALITY: Record<GaugeQuality, { en: string; hi: string }> = {
  good: { en: 'good', hi: 'ठीक' },
  suspect: { en: 'suspect, not counted', hi: 'संदिग्ध, गिनी नहीं जाती' },
  spike: { en: 'spike, not counted', hi: 'अचानक उछाल, गिनी नहीं जाती' },
  out_of_range: { en: 'out of range, not counted', hi: 'सीमा से बाहर, गिनी नहीं जाती' },
};

/** "good", or what is wrong with the newest reading and that it does not count. */
export function qualityWord(q: GaugeQuality | string | null | undefined, lang: Lang): string {
  return (QUALITY[(q ?? 'good') as GaugeQuality] ?? { en: String(q), hi: String(q) })[lang];
}

const REASON: Record<string, { en: string; hi: string }> = {
  silent: { en: 'silent', hi: 'चुप' },
  low_battery: { en: 'low battery', hi: 'बैटरी कम' },
  bad_quality: { en: 'half its readings bad', hi: 'आधी रीडिंग ख़राब' },
};

export interface HealthWords {
  ok: boolean;
  /** "Healthy" or "Unhealthy: silent, low battery". */
  status: string;
  /** "3 of 120 (2.5%)", or "—" with no readings. */
  badShare: string;
}

export function healthWords(h: GaugeHealth | null | undefined, lang: Lang): HealthWords | null {
  if (!h) return null;
  const hi = lang === 'hi';
  const reasons = h.reasons.map((r) => (REASON[r] ?? { en: r, hi: r })[lang]).join(', ');
  const status = h.unhealthy ? (hi ? `ठीक नहीं: ${reasons}` : `Unhealthy: ${reasons}`) : hi ? 'ठीक' : 'Healthy';
  const badShare =
    h.readings_24h > 0 && h.bad_share_24h != null
      ? hi
        ? `${num(h.readings_24h, lang)} में से ${num(h.bad_24h, lang)} (${num(h.bad_share_24h * 100, lang, 1)}%)`
        : `${num(h.bad_24h, lang)} of ${num(h.readings_24h, lang)} (${num(h.bad_share_24h * 100, lang, 1)}%)`
      : '—';
  return { ok: !h.unhealthy, status, badShare };
}

/**
 * Counted versus measured: the newest reading's band on its own against the level the rules count
 * (2 of the last 3 good readings, one step up when rising fast). Null when they agree.
 */
export function countedLine(counted: Level | null | undefined, measured: Level | null | undefined, lang: Lang): string | null {
  if (!isLevel(measured) || !isLevel(counted) || measured === counted) return null;
  const hi = lang === 'hi';
  // Higher than the reading itself: the rate-of-rise step. Lower: the 2-of-3 rule has not agreed yet.
  const up = levelRank(counted) > levelRank(measured);
  if (hi) {
    return `नया माप अकेले “${levelWord(measured, lang)}” पर; नियम “${levelWord(counted, lang)}” गिनते हैं (${up ? 'पानी तेज़ी से बढ़ रहा है, इसलिए एक स्तर ऊपर' : 'पिछली 3 अच्छी रीडिंग में से 2 का सहमत होना ज़रूरी'})`;
  }
  return `The newest reading alone is at ${levelWord(measured, lang)}; the rules count ${levelWord(counted, lang)} (${up ? 'rising fast, so one level up' : '2 of the last 3 good readings must agree'})`;
}

export function risingLine(rising: boolean | undefined, riseCm: number | null | undefined, lang: Lang): string | null {
  if (!rising) return null;
  const hi = lang === 'hi';
  const by = riseCm != null ? (hi ? ` (+${num(riseCm, lang, 1)} सेमी)` : ` (+${num(riseCm, lang, 1)} cm)`) : '';
  return hi ? `तेज़ी से बढ़ रहा${by}: एक स्तर ऊपर गिना गया` : `Rising fast${by}: counted one level up`;
}
