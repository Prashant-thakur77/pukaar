import type { Lang } from '../store';
import { levelWord } from '../i18n';
import { isLevel } from './levels';

/**
 * Turns rule ids written by services/risk_rules.py into a readable line.
 * Unknown ids are shown as they are, so nothing is ever hidden.
 */
export function describeRule(rule: string, lang: Lang): string {
  const hi = lang === 'hi';
  const [cond, outcome] = splitLast(rule);
  const lv = outcome && isLevel(outcome) ? levelWord(outcome, lang) : outcome;
  let m = cond.match(/^rain_24h>=([\d.]+)mm$/);
  if (m) return hi ? `24 घंटे की बारिश ≥ ${m[1]} मिमी → ${lv}` : `24 h rain ≥ ${m[1]} mm → ${lv}`;
  m = cond.match(/^discharge>=([\d.]+)$/);
  if (m) return hi ? `नदी का बहाव ≥ ${m[1]} m³/s → ${lv}` : `River discharge ≥ ${m[1]} m³/s → ${lv}`;
  switch (cond) {
    case 'verified_reports':
      return hi ? `पुष्ट गाँव-सूचनाएँ → ${lv}` : `Verified village reports → ${lv}`;
    case 'two_sources_agree':
      return hi ? 'दो अलग स्रोत सहमत → एक स्तर ऊपर' : 'Two independent sources agree → one level up';
    case 'verified_impact_report':
      return hi ? 'पुष्ट नुकसान की सूचना → कम से कम चेतावनी' : 'Verified impact report → at least Warning';
    case 'data_disagrees':
      return hi ? 'डेटा और सूचनाएँ मेल नहीं खाते: अधिकारी देखें' : 'Data and reports disagree: officer to check';
    case 'no_reading':
      return hi ? 'कोई माप नहीं मिला' : 'No reading available';
  }
  return rule;
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
