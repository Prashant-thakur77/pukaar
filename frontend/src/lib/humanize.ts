import { enumLabels } from '../i18n';
import type { Lang } from '../store';
import type { ReportType, Severity } from '../types';

export interface FlagText {
  text: string;
  /** For `duplicate_of:<id>`: the report it duplicates. */
  reportId?: string;
  tone: 'good' | 'warn' | 'muted';
}

const FLAGS: Record<string, { hi: string; en: string; tone: FlagText['tone'] }> = {
  possible_duplicate: { hi: 'पास की किसी सूचना जैसी लगती है', en: 'Possible duplicate of a nearby report', tone: 'warn' },
  no_gps: { hi: 'जगह नहीं मिली', en: 'No location', tone: 'muted' },
  transcription_unavailable: { hi: 'आवाज़ लिखी नहीं गई (रखी गई है)', en: 'Voice not transcribed (kept)', tone: 'muted' },
  corroborated: { hi: 'दूसरी सूचना से पुष्टि', en: 'Confirmed by a second report', tone: 'good' },
  verified_by_photo: { hi: 'फ़ोटो मेल खाती है', en: 'Photo matches', tone: 'good' },
  offline_created: { hi: 'ऑफ़लाइन बनाई, बाद में भेजी', en: 'Made offline, sent later', tone: 'muted' },
};

/** Report flags written by services/reports.py as plain words. Unknown flags pass through. */
export function humanizeFlag(flag: string, lang: Lang): FlagText {
  const dup = flag.match(/^duplicate_of:(.+)$/);
  if (dup) return { text: lang === 'hi' ? 'सूचना देखें' : 'see report', reportId: dup[1], tone: 'muted' };
  const f = FLAGS[flag];
  if (f) return { text: f[lang], tone: f.tone };
  return { text: flag.replace(/_/g, ' '), tone: 'muted' };
}

/**
 * The rule-based parser writes summaries like "road cut (high) reported".
 * Turn those into the current language; free-text summaries are kept.
 */
export function humanizeSummary(summary: string, lang: Lang, type?: ReportType, severity?: Severity): string {
  const s = (summary ?? '').trim();
  const m = s.match(/^([a-z ]+) \((low|medium|high|critical)\) reported$/);
  if (m) {
    const t = (m[1].replace(/ /g, '_') as ReportType) in enumLabels.reportType ? (m[1].replace(/ /g, '_') as ReportType) : type;
    const sev = m[2] as Severity;
    const tl = t ? enumLabels.reportType[t][lang] : m[1];
    const sl = enumLabels.severity[sev][lang];
    return lang === 'hi' ? `${tl} की सूचना · ख़तरा: ${sl}` : `${tl} reported · severity ${sl.toLowerCase()}`;
  }
  if (s === 'photo or voice report without text') return lang === 'hi' ? 'फ़ोटो या आवाज़ वाली सूचना, लिखा हुआ कुछ नहीं' : 'Photo or voice report, no text';
  if (!s && type) return `${enumLabels.reportType[type][lang]}${severity ? ` · ${enumLabels.severity[severity][lang]}` : ''}`;
  return s;
}
