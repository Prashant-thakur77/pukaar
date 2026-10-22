import { levelWord } from '../i18n';
import type { Lang } from '../store';
import { enumLabels } from '../i18n';
import type { DecisionTrace, EnsembleDay, Level, OfficialItem, Readiness, Thresholds, TraceEvidence } from '../types';
import { isLevel, levelRank } from './levels';
import { ensembleLines, ensembleNote, officialRows, outlookLine } from './riverEvidence';
import { burstText, parseBurstTag, type BurstTag } from './rules';

export interface EvidenceLine {
  text: string;
  /** Which signal this line is about (for an icon). */
  kind: 'river' | 'rain' | 'gauge' | 'reports' | 'agree' | 'impact' | 'disagree' | 'hold' | 'none' | 'outlook' | 'official';
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
    const years = th.return_period_years?.[lv];
    return {
      kind: 'river',
      level: lv,
      text: years
        ? hi
          ? `नदी का अधिकतम बहाव ${n(peak, lang)} m³/s ≥ ${n(years, lang)} साल वाला बाढ़-स्तर ${n(limit, lang)} m³/s (${levelWord(lv, lang)})`
          : `River peak ${n(peak, lang)} m³/s ≥ its ${years}-year flood level ${n(limit, lang)} m³/s (${levelWord(lv, lang)})`
        : hi
          ? `नदी का अधिकतम बहाव ${n(peak, lang)} m³/s ≥ ${levelWord(lv, lang)} सीमा ${n(limit, lang)} m³/s`
          : `River peak ${n(peak, lang)} m³/s ≥ ${levelWord(lv, lang).toLowerCase()} threshold ${n(limit, lang)} m³/s`,
    };
  }
  const y = th.return_period_years?.watch;
  return {
    kind: 'river',
    level: 'normal',
    text: y
      ? hi
        ? `नदी का अधिकतम बहाव ${n(peak, lang)} m³/s, ${n(y, lang)} साल वाले बाढ़-स्तर ${n(th.watch, lang)} से कम`
        : `River peak ${n(peak, lang)} m³/s, below its ${y}-year flood level ${n(th.watch, lang)} m³/s`
      : hi
        ? `नदी का अधिकतम बहाव ${n(peak, lang)} m³/s, सतर्क सीमा ${n(th.watch, lang)} से कम`
        : `River peak ${n(peak, lang)} m³/s, below the watch threshold ${n(th.watch, lang)} m³/s`,
  };
}

function rainLine(r: TraceEvidence, lang: Lang): EvidenceLine | null {
  const mm = r.rain_24h_mm;
  if (mm == null) return null;
  const hi = lang === 'hi';
  // rain_level is the higher of the 24 h bands and the heavy-burst rule; this line is the 24 h total's.
  const lv = isLevel(r.rain_24h_level) ? r.rain_24h_level : isLevel(r.rain_level) ? r.rain_level : 'normal';
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

type BurstWindow = { hours?: number; mm?: number | null; threshold_mm?: number };

/**
 * The heavy-burst rule (risk_rules.rain_intensity): the forecast's wettest 1, 3 or 6 hours. From the
 * trace's rain_intensity evidence when it is there (it names the models), else from the rule tag.
 */
function burstLine(trace: DecisionTrace, lang: Lang): EvidenceLine | null {
  const ev = (trace.evidence ?? []).find((e) => e.kind === 'rain_intensity');
  const tag = (trace.rules_fired ?? []).map(parseBurstTag).find((b): b is BurstTag => Boolean(b));
  const models = ev?.models && typeof ev.models === 'object' ? { n: Object.keys(ev.models).length, combine: ev.combine as string | undefined } : undefined;
  const lv = isLevel(ev?.level) ? ev.level : (tag?.level ?? null);
  const hits = Array.isArray(ev?.hit) ? (ev.hit as BurstWindow[]) : [];
  if (hits.length) {
    // The shortest window that reached its limit, as the rule tag names it.
    const h = [...hits].sort((a, b) => (a.hours ?? 0) - (b.hours ?? 0))[0];
    if (h.hours != null && h.mm != null && h.threshold_mm != null) {
      const reason = ev?.reason === '24h' || ev?.reason === 'soil' ? ev.reason : null;
      return { kind: 'rain', level: lv ?? undefined, text: burstText({ hours: h.hours, mm: h.mm, threshold: h.threshold_mm, reason, level: lv }, lang, models) };
    }
  }
  if (tag) return { kind: 'rain', level: tag.level ?? undefined, text: burstText(tag, lang, models) };
  // No burst: the window closest to its limit, so the officer sees how far off it is.
  const maxima = ev?.maxima as Record<string, BurstWindow> | undefined;
  const limits = ev?.windows_mm as Record<string, number> | undefined;
  if (!maxima || !limits) return null;
  const near = Object.entries(limits)
    .map(([d, limit]) => ({ hours: Number(d), mm: maxima[d]?.mm, limit }))
    .filter((w): w is { hours: number; mm: number; limit: number } => typeof w.mm === 'number' && w.limit > 0)
    .sort((a, b) => b.mm / b.limit - a.mm / a.limit)[0];
  if (!near) return null;
  const hi = lang === 'hi';
  const hrs = hi ? `${n(near.hours, lang)} घंटे` : `${near.hours} hour${near.hours === 1 ? '' : 's'}`;
  return {
    kind: 'rain',
    level: 'normal',
    text: hi
      ? `भारी बौछार नहीं: ${hrs} में अधिकतम ${n(near.mm, lang, 1)} मिमी, सीमा ${n(near.limit, lang, 1)} मिमी से कम`
      : `No heavy burst: at most ${n(near.mm, lang, 1)} mm in ${hrs}, below the ${n(near.limit, lang, 1)} mm limit`,
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
    const burst = burstLine(trace, lang);
    // Lead with whichever signal is higher (a stable sort keeps river, 24 h rain, burst on a tie).
    const pair = [river, rain, burst].filter((x): x is EvidenceLine => Boolean(x));
    pair.sort((a, b) => levelRank(b.level) - levelRank(a.level));
    out.push(...pair);
  } else {
    if (rules.includes('no_reading')) out.push({ kind: 'none', text: hi ? 'कोई माप नहीं मिला' : 'No river or rain reading available' });
    const burst = burstLine(trace, lang);
    if (burst) out.push(burst);
  }

  // The ensemble's odds: how many forecast runs reach each return-period line.
  const river = ev.find((e) => e.kind === 'river');
  if (river) {
    const th = (reading?.thresholds ?? null) as Thresholds | null;
    const ens = {
      mode: river.mode as string | undefined,
      ensemble_status: river.ensemble_status as string | null | undefined,
      members: river.members as number | null | undefined,
      p_min: river.p_min as number | undefined,
      lead_days: river.lead_days as EnsembleDay[] | undefined,
      replay: Boolean(trace.replay ?? reading?.replay),
    };
    const lines = ensembleLines(ens, th, lang);
    for (const l of lines.slice(-2).reverse()) out.push({ kind: 'river', level: l.raises ? l.level : undefined, text: l.text });
    const note = ensembleNote(ens, th, lang);
    if (note) out.push({ kind: 'river', text: note });
  }

  // The get-ready outlook: evidence only, never a level.
  const outlook = ev.find((e) => e.kind === 'outlook') as Partial<Readiness> | undefined;
  const ol = outlookLine(outlook ?? (trace.readiness as Partial<Readiness> | undefined), lang);
  if (ol) out.push({ kind: 'outlook', text: ol });

  // Official sources, as corroboration; "unavailable" says nothing.
  const official = ev.find((e) => e.kind === 'official');
  const rows = officialRows((official?.items ?? []) as OfficialItem[], lang);
  for (const row of rows.filter((r) => r.status === 'ok')) {
    out.push({ kind: 'official', level: row.level, text: `${row.label}: ${row.text}` });
  }
  // Sources that said nothing go on one line each: unavailable, then switched off.
  const down = rows.filter((r) => r.status === 'unavailable').map((r) => r.label);
  if (down.length) out.push({ kind: 'official', text: hi ? `उपलब्ध नहीं (कुछ नहीं कहते): ${down.join(', ')}` : `Unavailable, so saying nothing: ${down.join(', ')}` });
  const off = rows.filter((r) => r.status === 'off').map((r) => r.label);
  if (off.length) out.push({ kind: 'official', text: hi ? `बंद: ${off.join(', ')}` : `Switched off: ${off.join(', ')}` });

  const gauge = ev.find((e) => e.kind === 'gauge');
  if (gauge && typeof gauge.water_level_cm === 'number') {
    const lv = isLevel(gauge.gauge_level) ? gauge.gauge_level : undefined;
    const sim = gauge.simulated ? (hi ? ' (सिम्युलेटेड)' : ' (simulated)') : '';
    out.push({
      kind: 'gauge',
      level: lv,
      text: hi
        ? `नदी गेज ${Math.round(gauge.water_level_cm)} सेमी${sim}${lv ? ` → ${levelWord(lv, lang)}` : ''}`
        : `River gauge ${Math.round(gauge.water_level_cm)} cm${sim}${lv ? ` → ${levelWord(lv, lang)}` : ''}`,
    });
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
