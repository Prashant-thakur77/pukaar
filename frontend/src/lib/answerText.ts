/*
 * The words of the answer, with no imports: the React page (components/Answer.tsx) and the boot painter
 * that paints the answer before React has arrived (boot/boot.ts, inlined into index.html) both build
 * their text here, so the two say exactly the same thing and the hand-over is invisible.
 */

export type AnswerLevel = 'normal' | 'watch' | 'warning' | 'critical';
export type AnswerLang = 'hi' | 'en';

/** The level words. The same as i18n's level.* (i18n.test.ts holds them together). */
export const LEVEL_WORDS: Record<AnswerLevel, { hi: string; en: string }> = {
  normal: { hi: 'सामान्य', en: 'Normal' },
  watch: { hi: 'सतर्क', en: 'Watch' },
  warning: { hi: 'चेतावनी', en: 'Warning' },
  critical: { hi: 'गंभीर', en: 'Critical' },
};

/** Position on the four-step scale, 1 to 4. */
export function levelStep(level: AnswerLevel): number {
  return { normal: 1, watch: 2, warning: 3, critical: 4 }[level];
}

/** The meter's accessible name: "स्तर 3 में से 4: चेतावनी". */
export function meterLabel(level: AnswerLevel, unknown: boolean, lang: AnswerLang): string {
  if (unknown) return lang === 'hi' ? 'स्तर पता नहीं: डेटा नहीं मिल रहा' : 'Level unknown: no data';
  const step = levelStep(level);
  return lang === 'hi' ? `स्तर ${step} में से 4: ${LEVEL_WORDS[level].hi}` : `Level ${step} of 4: ${LEVEL_WORDS[level].en}`;
}

/** "03:10 IST": the clock time in India, whatever the phone's own time zone. */
export function istClock(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const hm = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false }).format(d);
  return `${hm} IST`;
}

/** Minutes since a time, or null. */
export function minutesSince(iso: string | null | undefined, now = Date.now()): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? null : Math.max(0, Math.round((now - t) / 60000));
}

/** Older than an hour: the page says so instead of letting an old Normal look current. */
export const STALE_MINUTES = 60;

export function isStale(iso: string | null | undefined, now = Date.now()): boolean {
  const m = minutesSince(iso, now);
  return m != null && m > STALE_MINUTES;
}

export interface FreshnessText {
  /** "इंटरनेट नहीं है" or "पुरानी जानकारी", shown as a chip before the line; null when fresh. */
  chip: string | null;
  /** The line itself: "आख़िरी जाँच 03:10 IST · 4 मिनट पहले · हर 15 मिनट जाँच". */
  line: string;
  stale: boolean;
  offline: boolean;
}

/**
 * C6: "आख़िरी जाँच 03:10 IST · 4 मिनट पहले". Older than an hour, it says the information is old; from the phone's
 * copy with no signal, it says so and gives the time of that copy.
 */
export function freshnessText(
  at: string | null | undefined,
  lang: AnswerLang,
  opts: { offline?: boolean; every?: boolean; next?: boolean } = {},
  now = Date.now(),
): FreshnessText {
  const hi = lang === 'hi';
  const offline = Boolean(opts.offline);
  const clock = istClock(at);
  if (!clock) return { chip: null, line: hi ? 'अभी कोई जाँच नहीं मिली' : 'No check received yet', stale: false, offline: false };
  const mins = minutesSince(at, now);
  const stale = isStale(at, now);
  const ago =
    mins == null ? '' : mins < 1 ? (hi ? 'अभी' : 'just now') : mins < 60 ? (hi ? `${mins} मिनट पहले` : `${mins} min ago`) : hi ? `${Math.round(mins / 60)} घंटे पहले` : `${Math.round(mins / 60)} h ago`;
  // The sweep runs every 15 minutes: the next one is due 15 minutes after the last.
  const nextIn = opts.next && mins != null && mins < 15 ? 15 - mins : null;
  const parts = [offline ? (hi ? `आख़िरी जानकारी ${clock} की` : `Last information from ${clock}`) : hi ? `आख़िरी जाँच ${clock}` : `Last checked ${clock}`];
  if (ago) parts.push(ago);
  if (opts.every && !stale && !offline) parts.push(hi ? 'हर 15 मिनट जाँच' : 'checked every 15 minutes');
  if (nextIn != null && nextIn > 0 && !offline) parts.push(hi ? `अगली ${nextIn} मिनट में` : `next in ${nextIn} min`);
  const chip = offline ? (hi ? 'इंटरनेट नहीं है' : 'No internet') : stale ? (hi ? 'पुरानी जानकारी' : 'Old information') : null;
  return { chip, line: parts.join(' · '), stale, offline };
}

export const DISTRICT_HI: Record<string, string> = { Mandi: 'मंडी', Hamirpur: 'हमीरपुर', Kullu: 'कुल्लू', Kangra: 'काँगड़ा' };

/** "ज़िला मंडी" / "Mandi district". */
export function districtLine(district: string, lang: AnswerLang): string {
  return lang === 'hi' ? `ज़िला ${DISTRICT_HI[district] ?? district}` : `${district} district`;
}

/** The shelter ledger's word for a place: open, ready, full, closed, or not yet checked. */
export function shelterWord(status: string, lang: AnswerLang): string {
  const w: Record<string, [string, string]> = {
    OPEN: ['खुला', 'Open'],
    STANDBY: ['तैयार', 'Ready'],
    FULL: ['भरा हुआ', 'Full'],
    CLOSED: ['बंद', 'Closed'],
  };
  const [hi, en] = w[status] ?? ['जाँच बाक़ी', 'Not yet checked'];
  return lang === 'hi' ? hi : en;
}

export interface PlaceText {
  kind_en: string | null;
  kind_hi: string | null;
  walk_min: number | null;
}

/** "अस्पताल, 25 मिनट" from the nearest open place. */
export function placeLine(p: PlaceText | null, lang: AnswerLang): string | null {
  if (!p) return null;
  const kind = lang === 'hi' ? p.kind_hi || p.kind_en : p.kind_en || p.kind_hi;
  const mins = p.walk_min != null ? (lang === 'hi' ? `${p.walk_min} मिनट` : `${p.walk_min} min`) : null;
  return [kind, mins].filter(Boolean).join(', ') || null;
}

/** "17 मी ऊँचा · 1.2 किमी · ~25 मिनट पैदल": the facts of the place beside the answer on a desk. */
export function placeFacts(p: { headroom_m: number | null; route_length_m: number | null; walk_min: number | null }, lang: AnswerLang): string {
  const hi = lang === 'hi';
  // The same as lib/format's fmtNumber(km, lang, 1).
  const km = p.route_length_m != null ? new Intl.NumberFormat(hi ? 'hi-IN' : 'en-IN', { maximumFractionDigits: 1 }).format(p.route_length_m / 1000) : null;
  return [
    p.headroom_m != null ? (hi ? `${Math.round(p.headroom_m)} मी ऊँचा` : `${Math.round(p.headroom_m)} m higher`) : null,
    km != null ? `${km} ${hi ? 'किमी' : 'km'}` : null,
    p.walk_min != null ? (hi ? `~${p.walk_min} मिनट पैदल` : `~${p.walk_min} min on foot`) : null,
  ]
    .filter(Boolean)
    .join(' · ');
}
