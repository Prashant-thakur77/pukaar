import { enumLabels } from '../i18n';
import type { Lang } from '../store';
import type { Report, ReportScreen, ReportType, Severity } from '../types';

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
  // Report-abuse protection (backend services/report_guard.py): a possible duplicate or flood of reports.
  same_source: { hi: 'इसी फ़ोन या नेटवर्क से हाल की एक और सूचना', en: 'Same phone or network as a recent report', tone: 'warn' },
  source_flood: { hi: 'एक ही जगह से बहुत सारी सूचनाएँ', en: 'Many reports from one source', tone: 'warn' },
  report_surge: { hi: 'इस गाँव से अचानक बहुत सूचनाएँ', en: 'Sudden flood of reports from this village', tone: 'warn' },
  source_unknown: { hi: 'भेजने वाला पता नहीं, अपने-आप पुष्टि नहीं', en: 'Sender unknown, cannot auto-verify', tone: 'muted' },
  photo_agrees: { hi: 'फ़ोटो सूचना से मेल खाती है, अधिकारी पुष्टि करें', en: 'Photo agrees, officer to confirm', tone: 'good' },
  transcript_skipped_held: { hi: 'रोकी गई: आवाज़ ख़ुद सुनें', en: 'Held: listen to the voice note', tone: 'muted' },
  'gps_implausible:published_centre': { hi: 'जगह गाँव का छपा हुआ बिंदु है, नापी हुई नहीं', en: 'Location is the published village point, not a fix', tone: 'warn' },
  'gps_implausible:null_island': { hi: 'जगह 0,0 है', en: 'Location is 0,0', tone: 'warn' },
};

/** Why a nearby agreeing report did not confirm this one (backend report_guard.not_independent). */
const REJECTED: Record<string, { hi: string; en: string }> = {
  same_ip: { hi: 'उसी इंटरनेट पते से', en: 'same internet address' },
  same_network: { hi: 'उसी नेटवर्क से', en: 'same network' },
  same_device: { hi: 'उसी फ़ोन से', en: 'same phone' },
  same_session: { hi: 'उसी सत्र से', en: 'same session' },
  source_unknown: { hi: 'भेजने वाला पता नहीं', en: 'sender unknown' },
  device_unknown: { hi: 'फ़ोन पता नहीं', en: 'phone unknown' },
  session_unknown: { hi: 'सत्र पता नहीं', en: 'session unknown' },
  published_centre: { hi: 'उसकी जगह गाँव का छपा बिंदु', en: 'its location is the published village point' },
  null_island: { hi: 'उसकी जगह 0,0', en: 'its location is 0,0' },
  outside_village: { hi: 'वह गाँव से बाहर', en: 'it is outside the village' },
};

/** Report flags written by services/reports.py as plain words. Unknown flags pass through. */
export function humanizeFlag(flag: string, lang: Lang): FlagText {
  const dup = flag.match(/^(?:duplicate_of|same_source_as):(.+)$/);
  if (dup) return { text: lang === 'hi' ? 'सूचना देखें' : 'see report', reportId: dup[1], tone: 'muted' };
  const rej = flag.match(/^corroboration_rejected:(.+)$/);
  if (rej) {
    const why = REJECTED[rej[1]];
    const head = lang === 'hi' ? 'दूसरी सूचना से पुष्टि नहीं' : 'Not confirmed by the nearby report';
    return { text: why ? `${head}: ${why[lang]}` : head, tone: 'warn' };
  }
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
  // A free-text English summary is never shown on a Hindi page: the report's type and severity say it instead.
  const english = s && lang === 'hi' && !/[ऀ-ॿ]/.test(s);
  if ((!s || english) && type) return `${enumLabels.reportType[type][lang]}${severity ? ` · ${enumLabels.severity[severity][lang]}` : ''}`;
  return s;
}

type Bi = { hi: string; en: string };
const INSTRUCTION: Bi = { en: 'possible instruction to the system', hi: 'सिस्टम को आदेश देने की कोशिश हो सकती है' };
const ABUSE: Bi = { en: 'abusive or harmful language', hi: 'अपमानजनक या हानिकारक भाषा' };
const SCREEN_REASONS: Record<string, Bi> = {
  prompt_attack: { en: 'tries to override the system’s rules', hi: 'सिस्टम के नियम बदलवाने की कोशिश' },
  instruction_to_system: { en: 'gives orders about levels or alerts', hi: 'स्तर या चेतावनी के बारे में आदेश' },
  hate: { en: 'hateful language', hi: 'नफ़रत भरी भाषा' },
  insults: { en: 'insulting language', hi: 'अपमानजनक भाषा' },
  violence: { en: 'violent language', hi: 'हिंसक भाषा' },
  misconduct: { en: 'talk of wrongdoing', hi: 'ग़लत काम की बात' },
  word_filter: { en: 'blocked words', hi: 'रोके गए शब्द' },
  'pii:phone': { en: 'phone number hidden', hi: 'फ़ोन नंबर छिपाया गया' },
  'pii:email': { en: 'e-mail hidden', hi: 'ई-मेल छिपाया गया' },
};

/** One guardrail reason code (backend llm/guardrail.py) in plain words. */
export function screenReason(code: string, lang: Lang): string {
  const r = SCREEN_REASONS[code];
  if (r) return r[lang];
  if (code.startsWith('topic:')) return code.slice(6);
  return code.replace(/[_:]/g, ' ');
}

export interface HeldText {
  /** The chip: "Held for review: <why>". */
  chip: string;
  /** Every reason in plain words, and which check made the call. */
  detail: string;
}

const INSTRUCTION_CODES = new Set(['prompt_attack', 'instruction_to_system']);
const ABUSE_CODES = new Set(['hate', 'insults', 'violence', 'misconduct', 'word_filter']);

/** Held because it came in over a rate limit (backend report_guard.py): kept for an officer, never dropped. */
const RATE_HOLDS: Record<string, { hi: string; en: string }> = {
  source_rate_limit: { hi: 'एक ही जगह से बहुत सारी सूचनाएँ', en: 'too many reports from one source' },
  village_surge: { hi: 'इस गाँव से अचानक बहुत सूचनाएँ', en: 'sudden flood of reports from this village' },
};

/** For a held report (the guardrail stopped it, or it came in over a rate limit): the chip and its
 * detail line. Null when it was not held. */
export function heldLabel(screen: ReportScreen | null | undefined, lang: Lang, holdReason?: string | null): HeldText | null {
  if (holdReason && (!screen || screen.allowed)) {
    const why = RATE_HOLDS[holdReason];
    const hi = lang === 'hi';
    const head = hi ? 'जाँच के लिए रोकी गई' : 'Held for review';
    return {
      chip: why ? `${head}: ${why[lang]}` : head,
      detail: hi
        ? 'संभावित दोहराव या सूचनाओं की बाढ़। सूचना रखी गई है; अधिकारी पढ़कर तय करें, अपने-आप पुष्टि नहीं होगी।'
        : 'Possible duplicate or flood of reports. Kept, not discarded; an officer decides, it is never auto-verified.',
    };
  }
  if (!screen || screen.allowed) return null;
  const rs = screen.reasons ?? [];
  const why = rs.some((r) => INSTRUCTION_CODES.has(r) || r.startsWith('topic:'))
    ? INSTRUCTION
    : rs.some((r) => ABUSE_CODES.has(r))
      ? ABUSE
      : null;
  const head = lang === 'hi' ? 'जाँच के लिए रोकी गई' : 'Held for review';
  const hi = lang === 'hi';
  const by = screen.engine === 'bedrock-guardrail'
    ? hi ? 'Bedrock Guardrails ने रोकी' : 'Screened by Bedrock Guardrails'
    : hi ? 'स्थानीय जाँच ने रोकी' : 'Screened by the local check';
  const reasons = rs.map((r) => screenReason(r, lang)).join(', ');
  const tail = hi ? 'अधिकारी पढ़कर तय करें; अपने-आप पुष्टि नहीं होगी।' : 'An officer decides; it is never auto-verified.';
  return { chip: why ? `${head}: ${why[lang]}` : head, detail: `${by}${reasons ? ` · ${reasons}` : ''}. ${tail}` };
}

/** Flags the backend (services/report_guard.py) puts on a possible duplicate or flood of reports. */
const FLOOD_FLAGS = new Set(['same_source', 'source_flood', 'report_surge']);

/** Reports in the last hour that look like a duplicate or a flood: same phone or network, or over a rate limit. */
export function floodCount(reports: Pick<Report, 'created_at' | 'flags' | 'hold_reason'>[], now: number = Date.now()): number {
  return reports.filter(
    (r) => now - Date.parse(r.created_at) <= 3600_000 && (Boolean(r.hold_reason) || r.flags.some((f) => FLOOD_FLAGS.has(f))),
  ).length;
}

/** Masking notes for a report that passed ("phone number hidden"); empty when nothing was masked. */
export function maskedNotes(screen: ReportScreen | null | undefined, lang: Lang): string[] {
  if (!screen || !screen.allowed) return [];
  return (screen.reasons ?? []).filter((r) => r.startsWith('pii:')).map((r) => screenReason(r, lang));
}
