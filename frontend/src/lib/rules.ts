import type { Lang } from '../store';
import { levelWord } from '../i18n';
import { isLevel } from './levels';
import type { Level } from '../types';

/**
 * Turns rule ids written by services/risk_rules.py into a readable line.
 * Unknown ids are shown as they are, so nothing is ever hidden.
 */
export function describeRule(rule: string, lang: Lang): string {
  const hi = lang === 'hi';
  const soil = rule.match(/^soil_saturated:S=([\d.]+):bands x([\d.]+)$/);
  if (soil)
    return hi
      ? `मिट्टी भरी हुई (S = ${soil[1]}) → बारिश की सीमाएँ × ${soil[2]}`
      : `Saturated soil (S = ${soil[1]}) → rain bands × ${soil[2]}`;
  const [cond, outcome] = splitLast(rule);
  const lv = outcome && isLevel(outcome) ? levelWord(outcome, lang) : outcome;
  const burst = parseBurstTag(rule);
  if (burst) return burstText(burst, lang);
  let m = cond.match(/^rain_24h>=([\d.]+)mm$/);
  if (m) return hi ? `24 घंटे की बारिश ≥ ${m[1]} मिमी → ${lv}` : `24 h rain ≥ ${m[1]} mm → ${lv}`;
  m = cond.match(/^gauge>=([\d.]+)cm$/);
  if (m) return hi ? `नदी गेज ≥ ${m[1]} सेमी → ${lv}` : `River gauge ≥ ${m[1]} cm → ${lv}`;
  m = cond.match(/^staff_gauge:(.+)$/);
  if (m)
    return hi
      ? `पैमाने वाला पत्थर: निशान ${m[1]}, अधिकारी ने पुष्टि की → ${lv}`
      : `Staff gauge: mark ${m[1]}, confirmed by an officer → ${lv}`;
  m = cond.match(/^discharge>=([\d.]+)$/);
  if (m) return hi ? `नदी का बहाव ≥ ${m[1]} m³/s → ${lv}` : `River discharge ≥ ${m[1]} m³/s → ${lv}`;
  switch (cond) {
    case 'verified_reports':
      return hi ? `पुष्ट गाँव-सूचनाएँ → ${lv}` : `Verified village reports → ${lv}`;
    case 'staff_gauge_confirmed':
      return hi ? `पुष्ट पैमाना-रीडिंग → ${lv}` : `Officer-confirmed staff gauge readings → ${lv}`;
    case 'two_sources_agree':
      return hi ? 'दो अलग स्रोत सहमत → एक स्तर ऊपर' : 'Two independent sources agree → one level up';
    case 'verified_impact_report':
      return hi ? 'पुष्ट नुकसान की सूचना → कम से कम चेतावनी' : 'Verified impact report → at least Warning';
    case 'data_disagrees':
      return hi ? 'डेटा और सूचनाएँ मेल नहीं खाते: अधिकारी देखें' : 'Data and reports disagree: officer to check';
    case 'auto_verified_capped':
      return hi ? 'अपने-आप पुष्ट सूचना: अधिकतम चेतावनी तक' : 'Auto-verified report: counts up to Warning at most';
    case 'gauge_simulated':
      return hi ? 'गेज का माप सिम्युलेटर से है, असली हार्डवेयर से नहीं' : 'Gauge reading is from the simulator, not real hardware';
    case 'no_reading':
      return hi ? 'कोई माप नहीं मिला' : 'No reading available';
  }
  return rule;
}

/** The heavy-burst rule's tag (risk_rules.intensity_rule_tag): "rain_intensity:3h=48>=45mm+rain_24h:warning". */
export interface BurstTag {
  hours: number;
  mm: number;
  threshold: number;
  /** Why a burst went to Warning: the 24 h rain already reached a band, or the soil is saturated. */
  reason: '24h' | 'soil' | null;
  level: Level | null;
}

export function parseBurstTag(rule: string): BurstTag | null {
  const m = rule.match(/^rain_intensity:(\d+)h=([\d.]+)>=([\d.]+)mm(\+rain_24h|\+soil_saturated)?(?::(\w+))?$/);
  if (!m) return null;
  return {
    hours: Number(m[1]),
    mm: Number(m[2]),
    threshold: Number(m[3]),
    reason: m[4] === '+rain_24h' ? '24h' : m[4] === '+soil_saturated' ? 'soil' : null,
    level: m[5] && isLevel(m[5]) ? m[5] : null,
  };
}

const num = (v: number, lang: Lang) => new Intl.NumberFormat(lang === 'hi' ? 'hi-IN' : 'en-IN', { maximumFractionDigits: 1 }).format(v);

/**
 * One readable line for a forecast heavy burst. `models` is how many forecast models were read and
 * `combine` how they were joined ("max": the highest of them, "mean": their hourly mean).
 */
export function burstText(b: BurstTag, lang: Lang, models?: { n: number; combine?: string | null }): string {
  const hi = lang === 'hi';
  const hrs = hi ? `${num(b.hours, lang)} घंटे` : `${b.hours} hour${b.hours === 1 ? '' : 's'}`;
  const many = models && models.n > 1;
  const src = !many
    ? ''
    : models!.combine === 'mean'
      ? hi ? `, ${num(models!.n, lang)} मॉडलों का औसत` : `, mean of ${models!.n} models`
      : hi ? `, ${num(models!.n, lang)} मॉडलों में सबसे ज़्यादा` : `, highest of ${models!.n} models`;
  const why =
    b.reason === '24h'
      ? hi ? ', और 24 घंटे की बारिश भी सीमा पर' : ', with the 24 h rain already over a band'
      : b.reason === 'soil'
        ? hi ? ', और मिट्टी पानी से भरी' : ', with the soil saturated'
        : '';
  const lv = b.level ? ` → ${levelWord(b.level, lang)}` : '';
  return hi
    ? `भारी बौछार का पूर्वानुमान: ${hrs} में ${num(b.mm, lang)} मिमी तक${src} (सीमा ${num(b.threshold, lang)} मिमी)${why}${lv}`
    : `Heavy burst forecast: up to ${num(b.mm, lang)} mm in ${hrs}${src} (limit ${num(b.threshold, lang)} mm)${why}${lv}`;
}

export function describeContradiction(c: string, lang: Lang): string {
  const hi = lang === 'hi';
  if (c === 'data_low_reports_high') return hi ? 'मौसम डेटा कम, पर गाँव से गंभीर सूचनाएँ' : 'Forecast data is low but village reports are severe';
  if (c === 'data_high_reports_low') return hi ? 'मौसम डेटा ऊँचा, पर सूचनाएँ हल्की' : 'Forecast data is high but reports are mild';
  return c;
}

function splitLast(rule: string): [string, string | null] {
  const i = rule.lastIndexOf(':');
  return i < 0 ? [rule, null] : [rule.slice(0, i), rule.slice(i + 1)];
}
