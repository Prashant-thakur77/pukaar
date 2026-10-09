import { levelWord } from '../i18n';
import type { Lang } from '../store';
import { enumLabels } from '../i18n';
import type { DecisionTrace, Level, TraceEvidence } from '../types';
import { isLevel, levelRank } from './levels';

export interface EvidenceLine {
  text: string;
  /** Which signal this line is about (for an icon). */
  kind: 'river' | 'rain' | 'reports' | 'agree' | 'impact' | 'disagree' | 'hold' | 'none';
  level?: Level;
}

const n = (v: number, lang: Lang, digits = 2) =>
  new Intl.NumberFormat(lang === 'hi' ? 'hi-IN' : 'en-IN', { maximumFractionDigits: digits }).format(v);

const NEXT_UP: Record<Level, Level | null> = { normal: 'watch', watch: 'warning', warning: 'critical', critical: null };

function riverLine(r: TraceEvidence, lang: Lang): EvidenceLine | null {
  const peak = r.discharge_peak;
  const th = r.thresholds;
  if (peak == null) return null;
  const hi = lang === 'hi';
  const lv = isLevel(r.river_level) ? r.river_level : 'normal';
  if (!th) return { kind: 'river', level: lv, text: hi ? `नदी का अधिकतम बहाव ${n(peak, lang)} m³/s (सीमा तय नहीं)` : `River peak ${n(peak, lang)} m³/s (no thresholds set)` };
  if (lv !== 'normal') {
    const limit = th[lv];
    return {
      kind: 'river',
      level: lv,
      text: hi
        ? `नदी का अधिकतम बहाव ${n(peak, lang)} m³/s ≥ ${levelWord(lv, lang)} सीमा ${n(limit, lang)} m³/s`
        : `River peak ${n(peak, lang)} m³/s ≥ ${levelWord(lv, lang).toLowerCase()} threshold ${n(limit, lang)} m³/s`,
    };
  }
  return {
    kind: 'river',
    level: 'normal',
    text: hi ? `नदी का अधिकतम बहाव ${n(peak, lang)} m³/s, सतर्क सीमा ${n(th.watch, lang)} से कम` : `River peak ${n(peak, lang)} m³/s, below the watch threshold ${n(th.watch, lang)} m³/s`,
  };
}

function rainLine(r: TraceEvidence, lang: Lang): EvidenceLine | null {
  const mm = r.rain_24h_mm;
  if (mm == null) return null;
  const hi = lang === 'hi';
  const lv = isLevel(r.rain_level) ? r.rain_level : 'normal';
  const bands = r.rain_bands_mm ?? {};
  if (lv !== 'normal' && bands[lv] != null) {
    return {
      kind: 'rain',
      level: lv,
      text: hi
        ? `अगले 24 घंटे में बारिश ${n(mm, lang, 1)} मिमी ≥ ${n(bands[lv]!, lang, 1)} मिमी (IMD ${levelWord(lv, lang)} सीमा)`
        : `Rain next 24 h ${n(mm, lang, 1)} mm ≥ ${n(bands[lv]!, lang, 1)} mm (IMD ${levelWord(lv, lang).toLowerCase()} band)`,
    };
  }
  const next = NEXT_UP[lv];
  const nb = next ? bands[next] : undefined;
  return {
    kind: 'rain',
    level: lv,
    text:
      nb != null
        ? hi
          ? `अगले 24 घंटे में बारिश ${n(mm, lang, 1)} मिमी, ${levelWord(next!, lang)} सीमा ${n(nb, lang, 1)} मिमी से कम`
          : `Rain next 24 h ${n(mm, lang, 1)} mm, below the ${levelWord(next!, lang).toLowerCase()} band ${n(nb, lang, 1)} mm`
        : hi
          ? `अगले 24 घंटे में बारिश ${n(mm, lang, 1)} मिमी`
          : `Rain next 24 h ${n(mm, lang, 1)} mm`,
  };
}

/** One readable line per piece of evidence in a decision trace (risk_rules.py). */
export function evidenceLines(trace: DecisionTrace | null | undefined, lang: Lang): EvidenceLine[] {
  if (!trace) return [];
  const hi = lang === 'hi';
  const out: EvidenceLine[] = [];
  const rules = trace.rules_fired ?? [];
  const ev = trace.evidence ?? [];
  const reading = ev.find((e) => e.kind === 'reading');
  if (reading) {
    const river = riverLine(reading, lang);
    const rain = rainLine(reading, lang);
    // Lead with whichever signal is higher.
    const pair = [river, rain].filter((x): x is EvidenceLine => Boolean(x));
    pair.sort((a, b) => levelRank(b.level) - levelRank(a.level));
    out.push(...pair);
  } else if (rules.includes('no_reading')) {
    out.push({ kind: 'none', text: hi ? 'कोई माप नहीं मिला' : 'No river or rain reading available' });
  }

  const reports = ev.filter((e) => e.kind === 'report');
  const verified = reports.filter((r) => r.verified);
  const vr = rules.find((r) => r.startsWith('verified_reports:'));
  if (verified.length) {
    const lv = vr ? vr.split(':')[1] : undefined;
    const kinds = verified
      .map((r) => `${r.type ? enumLabels.reportType[r.type as keyof typeof enumLabels.reportType]?.[lang] ?? r.type : '—'}${r.severity ? ` (${enumLabels.severity[r.severity][lang]})` : ''}`)
      .join(', ');
    out.push({
      kind: 'reports',
      level: isLevel(lv) ? lv : undefined,
      text: hi
        ? `${verified.length} पुष्ट गाँव-सूचना: ${kinds}${isLevel(lv) ? ` → ${levelWord(lv, lang)}` : ''}`
        : `${verified.length} verified village report${verified.length > 1 ? 's' : ''}: ${kinds}${isLevel(lv) ? ` → ${levelWord(lv, lang)}` : ''}`,
    });
  }
  const unverified = reports.length - verified.length;
  if (unverified > 0) {
    out.push({ kind: 'reports', text: hi ? `${unverified} सूचना अभी जाँच बाकी (स्तर नहीं बढ़ाती)` : `${unverified} unverified report${unverified > 1 ? 's' : ''} (cannot raise the level)` });
  }
  if (rules.some((r) => r.startsWith('two_sources_agree'))) out.push({ kind: 'agree', text: hi ? 'दो अलग स्रोत सहमत: एक स्तर ऊपर' : 'Two sources agree: +1 level' });
  if (rules.some((r) => r.startsWith('verified_impact_report'))) out.push({ kind: 'impact', text: hi ? 'पुष्ट नुकसान की सूचना: कम से कम चेतावनी' : 'Verified damage report: at least Warning' });
  if (rules.some((r) => r.startsWith('auto_verified_capped')))
    out.push({ kind: 'reports', text: hi ? 'अपने-आप पुष्ट सूचना अधिकतम चेतावनी तक ही ले जाती है' : 'Auto-verified reports can raise the level to Warning at most' });
  for (const c of trace.contradictions ?? []) {
    out.push({
      kind: 'disagree',
      text:
        c === 'data_low_reports_high'
          ? hi ? 'मौसम डेटा कम, पर गाँव से गंभीर सूचनाएँ: अधिकारी देखें' : 'Forecast data is low but village reports are severe: officer to check'
          : c === 'data_high_reports_low'
            ? hi ? 'मौसम डेटा ऊँचा, पर सूचनाएँ हल्की' : 'Forecast data is high but reports are mild'
            : c,
    });
  }
  const hold = holdLine(trace, lang);
  if (hold) out.push(hold);
  return out;
}

/** Hysteresis: the level rises at once but drops one step only after N calm sweeps. */
export function holdLine(
  trace: Pick<DecisionTrace, 'level' | 'raw_level' | 'hysteresis'> | null | undefined,
  lang: Lang,
  override?: { level: Level; raw: Level; calm: number; needed?: number },
): EvidenceLine | null {
  const h = (trace?.hysteresis ?? {}) as { calm_sweeps?: number; needed_to_drop?: number };
  const level = override?.level ?? (isLevel(trace?.level) ? trace!.level : undefined);
  const raw = override?.raw ?? (isLevel(trace?.raw_level) ? (trace!.raw_level as Level) : undefined);
  if (!level || !raw || levelRank(raw) >= levelRank(level)) return null;
  const needed = override?.needed ?? h.needed_to_drop ?? 3;
  const calm = override?.calm ?? h.calm_sweeps ?? 0;
  return {
    kind: 'hold',
    level,
    text:
      lang === 'hi'
        ? `${levelWord(level, lang)} पर रुका: स्तर एक कदम तभी घटता है जब लगातार ${needed} जाँच शांत रहें (अब तक ${calm} / ${needed})`
        : `Holding at ${levelWord(level, lang)}: levels drop one step only after ${needed} calm sweeps (${calm} of ${needed} so far)`,
  };
}
