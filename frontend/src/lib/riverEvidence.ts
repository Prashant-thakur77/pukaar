/*
 * Plain words for the river evidence (risk_rules.river_assessment, readiness.outlook,
 * official_data): the ensemble's odds, the return-period lines, the get-ready outlook and the
 * official sources. Used by the village page and by the console's "Why this level".
 * Every number shown is one the API sent; nothing is estimated here.
 */
import { levelWord } from '../i18n';
import type { Lang } from '../store';
import type { EnsembleDay, Level, OfficialItem, Readiness, Thresholds } from '../types';
import { isLevel } from './levels';

type RiverLevel = 'watch' | 'warning' | 'critical';
const RIVER_LEVELS: RiverLevel[] = ['watch', 'warning', 'critical'];
const DEFAULT_YEARS: Record<RiverLevel, number> = { watch: 2, warning: 5, critical: 20 };

const num = (v: number, lang: Lang, digits = 2) =>
  new Intl.NumberFormat(lang === 'hi' ? 'hi-IN' : 'en-IN', { maximumFractionDigits: digits }).format(v);

/** Digits for a discharge: small khads need decimals, the Beas does not. */
export function cms(v: number, lang: Lang): string {
  return num(v, lang, v >= 100 ? 0 : v >= 10 ? 1 : 2);
}

/** The ensemble part of a river view or a trace's river evidence item. */
export interface EnsembleLike {
  mode?: string;
  ensemble_status?: string | null;
  members?: number | null;
  p_min?: number;
  lead_days?: EnsembleDay[];
  replay?: boolean;
}

export interface EnsembleLine {
  level: RiverLevel;
  agree: number;
  members: number;
  lead: number;
  p: number;
  /** At or over the cut-off that raises a level (P ≥ p_min). */
  raises: boolean;
  text: string;
}

function years(th: Thresholds | null | undefined, lvl: RiverLevel): number | null {
  if (th?.method && th.method !== 'return_period') return null;
  return th?.return_period_years?.[lvl] ?? DEFAULT_YEARS[lvl];
}

function markName(th: Thresholds | null | undefined, lvl: RiverLevel, lang: Lang): string {
  const y = years(th, lvl);
  if (lang === 'hi') return y ? `${num(y, lang)} साल वाले बाढ़-स्तर` : `“${levelWord(lvl, lang)}” सीमा`;
  return y ? `its ${y}-year flood level` : `its ${levelWord(lvl, lang).toLowerCase()} line`;
}

/**
 * One line per river level that any forecast run reaches, highest P first per level, e.g.
 * "3 of 10 forecast runs say the river passes its 2-year flood level within 2 days".
 * Empty when there is no ensemble (see ensembleNote).
 */
export function ensembleLines(r: EnsembleLike | null | undefined, th: Thresholds | null | undefined, lang: Lang): EnsembleLine[] {
  if (!r || r.mode !== 'ensemble' || !r.lead_days?.length) return [];
  const pMin = r.p_min ?? 0.3;
  const out: EnsembleLine[] = [];
  for (const lvl of RIVER_LEVELS) {
    // The lead day with the highest share; the earlier one on a tie.
    const best = [...r.lead_days].sort((a, b) => b.p[lvl] - a.p[lvl] || a.lead - b.lead)[0];
    if (!best || best.p[lvl] <= 0) continue;
    const agree = Math.round(best.p[lvl] * best.members);
    const days = best.lead;
    const text =
      lang === 'hi'
        ? `${num(best.members, lang)} में से ${num(agree, lang)} पूर्वानुमान-रन कहते हैं कि नदी ${num(days, lang)} दिन के भीतर अपने ${markName(th, lvl, lang)} से ऊपर जाएगी`
        : `${agree} of ${best.members} forecast runs say the river passes ${markName(th, lvl, lang)} within ${days} day${days === 1 ? '' : 's'}`;
    out.push({ level: lvl, agree, members: best.members, lead: days, p: best.p[lvl], raises: best.p[lvl] >= pMin, text });
  }
  return out;
}

/** The sentence when no run reaches even Watch, or when there is no ensemble to read. */
export function ensembleNote(r: EnsembleLike | null | undefined, th: Thresholds | null | undefined, lang: Lang): string | null {
  const hi = lang === 'hi';
  if (!r || r.mode === 'none') return hi ? 'नदी का कोई पूर्वानुमान अभी नहीं मिला' : 'No river forecast yet';
  if (r.mode === 'ensemble') {
    if (ensembleLines(r, th, lang).length) return null;
    const n = r.members ?? r.lead_days?.[0]?.members ?? 0;
    const d = Math.max(...(r.lead_days ?? []).map((x) => x.lead), 3);
    return hi
      ? `${num(n, lang)} में से कोई भी पूर्वानुमान-रन नदी को अगले ${num(d, lang)} दिन में ${markName(th, 'watch', lang)} तक नहीं ले जाता`
      : `None of the ${n} forecast runs take the river past ${markName(th, 'watch', lang)} in the next ${d} days`;
  }
  const why = r.replay
    ? hi ? 'रीप्ले में एन्सेम्बल नहीं होता' : 'replays carry no ensemble'
    : r.ensemble_status === 'off'
      ? hi ? 'एन्सेम्बल बंद है' : 'the ensemble is switched off'
      : hi ? 'एन्सेम्बल अभी उपलब्ध नहीं' : 'the ensemble is unavailable';
  return hi ? `नदी: एकल पूर्वानुमान, पूर्वानुमान-रन नहीं (${why})` : `River: a single forecast, not the forecast runs (${why})`;
}

/** The cut-off in words: "3 in 10 runs or more raise a level". */
export function cutoffNote(pMin: number | undefined, lang: Lang): string {
  const tenths = Math.round((pMin ?? 0.3) * 10);
  return lang === 'hi' ? `10 में से ${num(tenths, lang)} या ज़्यादा रन सहमत हों, तभी स्तर बढ़ता है` : `A level rises only when ${tenths} in 10 runs or more agree`;
}

export interface LineRow {
  key: RiverLevel | 'early';
  label: string;
  what: string;
  value: number;
}

/** The return-period lines and the get-ready line, highest first. */
export function thresholdRows(th: Thresholds | null | undefined, lang: Lang): LineRow[] {
  if (!th) return [];
  const hi = lang === 'hi';
  const rows: LineRow[] = [...RIVER_LEVELS].reverse().map((lvl) => {
    const y = years(th, lvl);
    return {
      key: lvl,
      label: levelWord(lvl, lang),
      what: y ? (hi ? `${num(y, lang)} साल की बाढ़` : `${y}-year flood`) : hi ? 'सीमा' : 'threshold',
      value: th[lvl],
    };
  });
  if (th.early != null) {
    rows.push({ key: 'early', label: hi ? 'तैयार रहें' : 'Get ready', what: hi ? 'नदी 10 में से 1 दिन इतनी ऊँची बहती है (आउटलुक, चेतावनी नहीं)' : 'the river runs this high 1 day in 10 (an outlook, never an alert)', value: th.early });
  }
  return rows;
}

/** "Get ready: the river is forecast to run high" in one line, or null when the outlook is quiet. */
export function outlookLine(r: Partial<Readiness> | null | undefined, lang: Lang): string | null {
  if (!r || r.state !== 'get_ready') return null;
  const hi = lang === 'hi';
  const basis =
    r.basis === 'ensemble_median'
      ? hi ? 'एन्सेम्बल का मध्य' : 'ensemble median'
      : r.basis === 'mixed'
        ? hi ? 'एन्सेम्बल का मध्य और एकल पूर्वानुमान' : 'ensemble median and single forecast'
        : hi ? 'एकल पूर्वानुमान' : 'single forecast';
  const line = r.line === 'watch' ? r.watch : r.early;
  const d = r.horizon_days ?? 0;
  if (hi) {
    return `तैयार रहें: नदी के ऊँचा बहने का पूर्वानुमान। ${num(d, lang)} दिन बाद बहाव ${line != null ? `${cms(line, lang)} m³/s की` : ''} रेखा पार करता है (${basis})। यह चेतावनी नहीं है, स्तर नहीं बदलता।`;
  }
  return `Get ready: the river is forecast to run high. In ${d} day${d === 1 ? '' : 's'} the flow passes ${line != null ? `the ${cms(line, lang)} m³/s line` : 'its line'} (${basis}). Not an alert; it never changes the level.`;
}

const COLOUR: Record<string, { en: string; hi: string }> = {
  none: { en: 'no colour', hi: 'कोई रंग नहीं' },
  green: { en: 'green', hi: 'हरा' },
  yellow: { en: 'yellow', hi: 'पीला' },
  orange: { en: 'orange', hi: 'नारंगी' },
  red: { en: 'red', hi: 'लाल' },
};

const SOURCE_NAME: Record<string, { en: string; hi: string }> = {
  cwc: { en: 'CWC river stations', hi: 'CWC नदी स्टेशन' },
  imd: { en: 'IMD district colour', hi: 'IMD ज़िले का रंग' },
  flood_hub: { en: 'Google Flood Hub', hi: 'Google Flood Hub' },
  bipad: { en: 'BIPAD (Nepal)', hi: 'BIPAD (नेपाल)' },
};

export interface OfficialRow {
  source: string;
  label: string;
  text: string;
  status: OfficialItem['status'];
  level?: Level;
}

/** One plain row per official source. Unavailable reads "unavailable", never "normal". */
export function officialRows(items: OfficialItem[] | null | undefined, lang: Lang): OfficialRow[] {
  const hi = lang === 'hi';
  return (items ?? []).map((it) => {
    const label = (SOURCE_NAME[it.source] ?? { en: it.name, hi: it.name })[lang];
    const lv = isLevel(it.level) && it.level !== 'normal' ? it.level : undefined;
    let text: string;
    if (it.status === 'unavailable') text = hi ? 'उपलब्ध नहीं (कुछ नहीं कहता)' : 'unavailable (says nothing)';
    else if (it.status === 'off') text = hi ? 'बंद' : 'switched off';
    else if (it.source === 'cwc') {
      const n = it.stations_above_warning ?? 0;
      const m = it.matched?.length ?? 0;
      text = hi
        ? `भारत में ${num(n, lang)} स्टेशन चेतावनी स्तर से ऊपर; इस नदी पर ${num(m, lang)}${it.mapped ? '' : ' (इस गाँव के लिए स्टेशन कोड अभी तय नहीं)'}`
        : `${n} station${n === 1 ? '' : 's'} above warning in India; ${m} on this river${it.mapped ? '' : ' (no station codes mapped to this village yet)'}`;
    } else if (it.source === 'imd') {
      const c = COLOUR[it.colour ?? 'none'] ?? { en: String(it.colour), hi: String(it.colour) };
      text = hi ? `आज और कल: ${c.hi} (सभी मौसम ख़तरे, सिर्फ़ बाढ़ नहीं)` : `${c.en} for today and tomorrow (every weather hazard, not floods alone)`;
    } else text = it.detail ?? (hi ? 'ठीक' : 'ok');
    return { source: it.source, label, text, status: it.status, level: lv };
  });
}
