/*
 * UI strings in Hindi and English. The strings themselves are in i18n/strings.ts (written side by side); the
 * build splits them into one table per language, and a phone downloads only the one it shows: main.tsx loads
 * it before the first render, the other one follows when the phone is idle (a language switch never waits).
 *
 * NEEDS NATIVE-SPEAKER REVIEW: every Hindi string here and in i18n/strings.ts was written without a native
 * speaker. Have a Hindi speaker from Mandi district check the wording (plain, spoken register; no
 * Sanskritised words) before release.
 */
import { use } from 'react';
import { scopeFor, usePrefs, type Lang } from './store';
import type { strings } from './i18n/strings';
import type { AlertStatus, DirectiveType, Level, ReportState, ReportType, Severity } from './types';

type Entry = { hi: string; en: string };

/**
 * The level words and the data badges: kept in the main bundle so they never wait for a language table (the
 * pre-JS painter and the first frame use them). Everything else is in i18n/strings.ts.
 */
export const dict = {
  'level.normal': { hi: 'सामान्य', en: 'Normal' },
  'level.watch': { hi: 'सतर्क', en: 'Watch' },
  'level.warning': { hi: 'चेतावनी', en: 'Warning' },
  'level.critical': { hi: 'गंभीर', en: 'Critical' },
  'data.badge.none': { hi: 'डेटा नहीं', en: 'No data' },
  'data.badge.late': { hi: 'डेटा देर से', en: 'Data late' },
} satisfies Record<string, Entry>;

export type Key = keyof typeof strings | keyof typeof dict;
type CoreKey = keyof typeof dict;

const LEVEL_KEYS: Record<Level, CoreKey> = {
  normal: 'level.normal',
  watch: 'level.watch',
  warning: 'level.warning',
  critical: 'level.critical',
};

export const levelWord = (level: Level, lang: Lang): string => dict[LEVEL_KEYS[level]][lang];

export const enumLabels = {
  reportType: {
    water_rising: { hi: 'पानी बढ़ रहा है', en: 'Water rising' },
    road_cut: { hi: 'सड़क टूटी', en: 'Road cut' },
    bridge_unsafe: { hi: 'पुल असुरक्षित', en: 'Bridge unsafe' },
    landslide: { hi: 'भूस्खलन', en: 'Landslide' },
    homes_affected: { hi: 'घर प्रभावित', en: 'Homes affected' },
    people_trapped: { hi: 'लोग फँसे हैं', en: 'People trapped' },
    other: { hi: 'अन्य', en: 'Other' },
  } satisfies Record<ReportType, Entry>,
  severity: {
    low: { hi: 'कम', en: 'Low' },
    medium: { hi: 'मध्यम', en: 'Medium' },
    high: { hi: 'ज़्यादा', en: 'High' },
    critical: { hi: 'गंभीर', en: 'Critical' },
  } satisfies Record<Severity, Entry>,
  reportState: {
    received: { hi: 'मिली', en: 'Received' },
    transcribing: { hi: 'लिखी जा रही', en: 'Transcribing' },
    unverified: { hi: 'जाँच बाकी', en: 'Unverified' },
    verified_auto: { hi: 'अपने-आप पुष्ट', en: 'Auto-verified' },
    verified: { hi: 'पुष्ट', en: 'Verified' },
    reviewed: { hi: 'देखी गई', en: 'Reviewed' },
    actioned: { hi: 'कार्रवाई हुई', en: 'Actioned' },
    resolved: { hi: 'सुलझ गई', en: 'Resolved' },
    duplicate: { hi: 'दोहराई गई', en: 'Duplicate' },
    false: { hi: 'गलत', en: 'False' },
  } satisfies Record<ReportState, Entry>,
  alertStatus: {
    drafting: { hi: 'मसौदा बन रहा', en: 'Drafting' },
    pending: { hi: 'मंज़ूरी बाकी', en: 'Pending' },
    approved: { hi: 'मंज़ूर', en: 'Approved' },
    declined: { hi: 'अस्वीकार', en: 'Declined' },
    expired: { hi: 'समय समाप्त', en: 'Expired' },
    delivering: { hi: 'भेजी जा रही', en: 'Delivering' },
    delivered: { hi: 'पहुँच गई', en: 'Delivered' },
    auto_sent_unapproved: { hi: 'बिना मंज़ूरी भेजी', en: 'Auto-sent, unapproved' },
    failsafe: { hi: 'सुरक्षा टेम्पलेट', en: 'Failsafe sent' },
    closed: { hi: 'बंद', en: 'Closed' },
  } satisfies Record<AlertStatus, Entry>,
  directiveType: {
    evacuate: { hi: 'गाँव खाली करें', en: 'Evacuate' },
    shelter_in_place: { hi: 'जहाँ हैं वहीं सुरक्षित रहें', en: 'Shelter in place' },
    advisory: { hi: 'सलाह', en: 'Advisory' },
    all_clear: { hi: 'ख़तरा टला', en: 'All clear' },
  } satisfies Record<DirectiveType, Entry>,
};

export function format(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (_, k: string) => (k in vars ? String(vars[k]) : `{${k}}`));
}

/* ---------- one table per language, loaded on demand ---------- */

type Table = Record<string, string>;
const tables: Partial<Record<Lang, Table>> = {};
const loading: Partial<Record<Lang, Promise<void>>> = {};
const LOADERS: Record<Lang, () => Promise<{ default: Table }>> = {
  hi: () => import('virtual:pk-strings/hi'),
  en: () => import('virtual:pk-strings/en'),
};

/** Downloads a language's table once; the same promise for every caller until it has arrived. */
export function loadLang(lang: Lang): Promise<void> {
  if (tables[lang]) return Promise.resolve();
  loading[lang] ??= LOADERS[lang]().then(
    (m) => {
      tables[lang] = m.default;
    },
    (err: unknown) => {
      delete loading[lang];
      throw err;
    },
  );
  return loading[lang];
}

export const langReady = (lang: Lang): boolean => Boolean(tables[lang]);

export function translate(lang: Lang, key: Key, vars?: Record<string, string | number>): string {
  const core = (dict as Record<string, Entry | undefined>)[key];
  const s = core ? core[lang] : (tables[lang]?.[key] ?? tables[lang === 'hi' ? 'en' : 'hi']?.[key] ?? '');
  return format(s, vars);
}

/** Which area a page belongs to; it only picks the first-visit language (store.ts). */
export { scopeFor };

/**
 * The one language of the whole site (store.ts): every page shows only it, and a switch on any page applies to
 * every page.
 */
export function useT() {
  const lang = usePrefs((s) => s.lang);
  const setLang = usePrefs((s) => s.setLang);
  // A language whose table has not arrived yet waits for it, inside Suspense.
  if (!tables[lang]) use(loadLang(lang));
  const t = (key: Key, vars?: Record<string, string | number>) => translate(lang, key, vars);
  const pick = (e: Entry) => e[lang];
  // A switch fetches the table first, so the page never blanks while it arrives.
  const switchTo = (l: Lang) => void loadLang(l).then(() => setLang(l), () => setLang(l));
  return { t, lang, pick, setLang: switchTo, other: (lang === 'hi' ? 'en' : 'hi') as Lang };
}
