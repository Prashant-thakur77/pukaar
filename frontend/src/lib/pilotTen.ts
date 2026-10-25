/*
 * The ten pilot metrics in words (services/pilot_metrics.py, docs/PILOT_PROTOCOL.md section 3): rows for the /pilot
 * table (pooled; live alerts, drills and replays apart) and for one alert in the console. A value with nothing
 * behind it is "—", never 0: most of these are "—" until a real alert or a drill with real phones happens.
 * NEEDS NATIVE-SPEAKER REVIEW for the Hindi, as for i18n.ts.
 */
import type { Lang } from '../store';
import type { AlertMetrics, TenGroup, TenMetrics } from '../types';

export const DASH = '—';
type Txt = { en: string; hi: string };

const num = (v: number, lang: Lang, digits = 0) =>
  new Intl.NumberFormat(lang === 'hi' ? 'hi-IN' : 'en-IN', { maximumFractionDigits: digits }).format(v);
export const pct = (v: number | null | undefined, lang: Lang) => (v == null ? DASH : `${num(v * 100, lang)}%`);
const mins = (v: number | null | undefined, lang: Lang) => (v == null ? DASH : `${num(v, lang, 1)} ${lang === 'hi' ? 'मिनट' : 'min'}`);

export const TEN: { n: number; key: string; title: Txt; how: Txt }[] = [
  { n: 1, key: 'coverage', title: { en: 'Coverage', hi: 'पहुँच का दायरा' }, how: { en: 'Registered phones ÷ households on the village list', hi: 'जुड़े फ़ोन ÷ गाँव की सूची के घर' } },
  { n: 2, key: 'reach', title: { en: 'Confirmed reach', hi: 'पुष्टि वाली पहुँच' }, how: { en: 'Pressed “Got it” within 15, 30, 60 min of the first send', hi: 'पहले संदेश के 15, 30, 60 मिनट में “मिल गया” दबाया' } },
  { n: 3, key: 'assisted', title: { en: 'Assisted households', hi: 'मदद वाले घर' }, how: { en: 'Confirmed in 30 min, or checked by their named neighbour', hi: '30 मिनट में पुष्टि, या पड़ोसी ने जाकर देखा' } },
  { n: 4, key: 'chain', title: { en: 'Time chain', hi: 'समय की कड़ी' }, how: { en: 'First signal → rule → officer asked → approved → first send → first confirmation (median)', hi: 'पहला संकेत → नियम → अधिकारी से पूछा → मंज़ूरी → पहला संदेश → पहली पुष्टि (मध्य)' } },
  { n: 5, key: 'lead', title: { en: 'Lead time achieved', hi: 'मिला हुआ समय' }, how: { en: 'First send to when harm began, where a real flood was recorded', hi: 'पहले संदेश से नुक़सान शुरू होने तक, जहाँ असली बाढ़ दर्ज हुई' } },
  { n: 6, key: 'outcomes', title: { en: 'Hits and false alarms', hi: 'सही और झूठी चेतावनियाँ' }, how: { en: '“Was this real?” after each alert; the hit rate needs the DDMA’s list of floods', hi: 'हर चेतावनी के बाद “क्या यह असली था?”; सही दर के लिए DDMA की बाढ़ सूची चाहिए' } },
  { n: 7, key: 'siren', title: { en: 'Siren proof', hi: 'सायरन का सबूत' }, how: { en: 'Sirens verified by current and microphone ÷ commanded', hi: 'करंट और माइक से पुष्ट सायरन ÷ भेजे गए आदेश' } },
  { n: 8, key: 'data', title: { en: 'Data health', hi: 'डेटा की सेहत' }, how: { en: 'Alerts with complete forecast data; forecast checks made ÷ expected (24 h)', hi: 'पूरे पूर्वानुमान वाली चेतावनियाँ; पूर्वानुमान जाँच ÷ अपेक्षित (24 घंटे)' } },
  { n: 9, key: 'action', title: { en: 'Protective action', hi: 'बचाव का क़दम' }, how: { en: '“Are you safe?” roll-call answers after the alert (the phone survey is not built)', hi: 'चेतावनी के बाद “क्या आप सुरक्षित हैं?” के जवाब (फ़ोन सर्वे अभी नहीं बना)' } },
  { n: 10, key: 'readiness', title: { en: 'Readiness', hi: 'तैयारी' }, how: { en: 'Pilot checklist done; villages with two observers', hi: 'पायलट सूची पूरी; दो निगरानीकर्ता वाले गाँव' } },
];

/** One group's value for a per-kind row (2-9), in words. */
export function groupCell(key: string, g: TenGroup | undefined, lang: Lang): string {
  if (!g || g.alerts === 0) return DASH;
  const hi = lang === 'hi';
  switch (key) {
    case 'reach': {
      const r = g.confirmed_reach;
      if (!r.targeted) return DASH;
      return `${pct(r.share_15, lang)} · ${pct(r.share_30, lang)} · ${pct(r.share_60, lang)} (${hi ? 'कुल' : 'of'} ${num(r.targeted, lang)})`;
    }
    case 'assisted': {
      const a = g.assisted_reach;
      if (!a.targeted) return DASH;
      return hi
        ? `30 मिनट में ${pct(a.share_30, lang)}; पुष्टि या देखा ${pct(a.confirmed_or_checked_share, lang)} (कुल ${num(a.targeted, lang)})`
        : `${pct(a.share_30, lang)} in 30 min; confirmed or checked ${pct(a.confirmed_or_checked_share, lang)} (of ${num(a.targeted, lang)})`;
    }
    case 'chain': {
      const c = g.time_chain_median_minutes;
      const send = c.signal_to_first_delivery;
      const ack = c.signal_to_first_ack;
      if (send == null && ack == null) return DASH;
      return hi
        ? `संकेत → पहला संदेश ${mins(send, lang)}; → पहली पुष्टि ${mins(ack, lang)}`
        : `signal → first send ${mins(send, lang)}; → first confirmation ${mins(ack, lang)}`;
    }
    case 'lead':
      return g.lead_time.measured ? mins(g.lead_time.median_minutes, lang) : DASH;
    case 'outcomes': {
      const o = g.outcomes;
      if (o.real_flood + o.no_flood + o.unknown === 0) return DASH;
      return hi
        ? `झूठी चेतावनी दर ${pct(o.false_alarm_rate, lang)} (${num(o.real_flood, lang)} असली, ${num(o.no_flood, lang)} बाढ़ नहीं)`
        : `false-alarm rate ${pct(o.false_alarm_rate, lang)} (${num(o.real_flood, lang)} real, ${num(o.no_flood, lang)} no flood)`;
    }
    case 'siren':
      return g.siren.commanded ? `${num(g.siren.verified, lang)} / ${num(g.siren.commanded, lang)} (${pct(g.siren.verified_share, lang)})` : DASH;
    case 'data': {
      const d = g.data_health;
      if (!d.alerts_with_status) return DASH;
      return hi
        ? `${num(d.alerts_with_data_ok, lang)} / ${num(d.alerts_with_status, lang)} पूरे डेटा के साथ`
        : `${num(d.alerts_with_data_ok, lang)} of ${num(d.alerts_with_status, lang)} with complete data`;
    }
    case 'action': {
      const p = g.protective_action;
      if (!p.asked) return DASH;
      return hi
        ? `${num(p.safe, lang)} सुरक्षित, ${num(p.need_help, lang)} को मदद (कुल ${num(p.asked, lang)} से पूछा)`
        : `${num(p.safe, lang)} safe, ${num(p.need_help, lang)} need help (of ${num(p.asked, lang)} asked)`;
    }
  }
  return DASH;
}

/** The rows that are about now, not one kind of alert (1 coverage, 8's forecast checks, 10 readiness). */
export function nowCell(key: string, t: TenMetrics, lang: Lang): string | null {
  const hi = lang === 'hi';
  if (key === 'coverage') {
    const c = t.coverage;
    if (c.share == null)
      return hi
        ? `— (किसी गाँव की घरों की सूची अभी नहीं मिली; ${num(c.registered_phones, lang)} फ़ोन जुड़े)`
        : `— (no village household list received yet; ${num(c.registered_phones, lang)} phones registered)`;
    return `${pct(c.share, lang)} (${num(c.villages_with_household_list, lang)} ${hi ? 'गाँव' : 'villages'})`;
  }
  if (key === 'readiness') {
    const r = t.readiness;
    const items = r.checklist.items ? `${num(r.checklist.done ?? 0, lang)} / ${num(r.checklist.items, lang)}` : DASH;
    return hi
      ? `सूची ${items} पूरी; ${num(r.villages_with_two_observers, lang)} / ${num(t.coverage.villages, lang)} गाँवों में दो निगरानीकर्ता`
      : `checklist ${items} done; ${num(r.villages_with_two_observers, lang)} of ${num(t.coverage.villages, lang)} villages with two observers`;
  }
  return null;
}

export function dataNow(t: TenMetrics, lang: Lang): string {
  const d = t.data_health_now;
  if (d.forecast_checks_24h == null) return DASH;
  return lang === 'hi'
    ? `अभी: ${num(d.forecast_checks_24h, lang)} / ${num(d.expected_24h, lang)} पूर्वानुमान जाँच (24 घंटे)`
    : `now: ${num(d.forecast_checks_24h, lang)} of ${num(d.expected_24h, lang)} forecast checks (24 h)`;
}

/** One alert's metrics as (label, value) pairs for the console's decision panel. */
export function alertRows(m: AlertMetrics, lang: Lang): { n: number; title: string; value: string }[] {
  const hi = lang === 'hi';
  const r = m.confirmed_reach;
  const a = m.assisted_reach;
  const c = m.time_chain.minutes;
  const gaugeWord: Record<string, Txt> = {
    fresh: { en: 'gauge fresh', hi: 'गेज ताज़ा' },
    silent: { en: 'gauge silent in rain', hi: 'बारिश में गेज चुप' },
    none: { en: 'no gauge', hi: 'गेज नहीं' },
    not_fresh: { en: 'gauge not fresh', hi: 'गेज ताज़ा नहीं' },
  };
  const values: Record<string, string> = {
    coverage:
      m.coverage.share == null
        ? hi
          ? `— (घरों की सूची नहीं; ${num(m.coverage.registered, lang)} फ़ोन जुड़े)`
          : `— (no household list; ${num(m.coverage.registered, lang)} phones registered)`
        : `${pct(m.coverage.share, lang)} (${num(m.coverage.registered, lang)} / ${num(m.coverage.households ?? 0, lang)})`,
    reach: r.targeted
      ? `${pct(r.share_15, lang)} · ${pct(r.share_30, lang)} · ${pct(r.share_60, lang)} (${num(r.confirmed, lang)} / ${num(r.targeted, lang)})`
      : DASH,
    assisted: a.targeted
      ? hi
        ? `${num(a.confirmed, lang)} ने पुष्टि की, ${num(a.checked_by_neighbour, lang)} को पड़ोसी ने देखा (कुल ${num(a.targeted, lang)})`
        : `${num(a.confirmed, lang)} confirmed, ${num(a.checked_by_neighbour, lang)} checked by a neighbour (of ${num(a.targeted, lang)})`
      : DASH,
    chain: [
      c.first_signal_to_rule != null ? `${hi ? 'संकेत→नियम' : 'signal→rule'} ${mins(c.first_signal_to_rule, lang)}` : null,
      c.rule_to_asked != null ? `→${hi ? 'पूछा' : 'asked'} ${mins(c.rule_to_asked, lang)}` : null,
      c.asked_to_approved != null ? `→${hi ? 'मंज़ूर' : 'approved'} ${mins(c.asked_to_approved, lang)}` : null,
      c.approved_to_first_delivery != null ? `→${hi ? 'पहला संदेश' : 'first send'} ${mins(c.approved_to_first_delivery, lang)}` : null,
      c.first_delivery_to_first_ack != null ? `→${hi ? 'पहली पुष्टि' : 'first confirmation'} ${mins(c.first_delivery_to_first_ack, lang)}` : null,
    ]
      .filter(Boolean)
      .join(' ') || DASH,
    lead: mins(m.lead_time.from_first_delivery, lang),
    outcomes: m.outcome.outcome ?? DASH,
    siren: m.siren.commanded ? `${num(m.siren.verified, lang)} / ${num(m.siren.commanded, lang)}` : DASH,
    data: `${m.data_health.forecast ?? DASH} · ${(gaugeWord[m.data_health.gauge] ?? gaugeWord.none)[lang]}${
      m.data_health.unknown.length ? ` · ${m.data_health.unknown.join(', ')}` : ''
    }`,
    action: m.protective_action
      ? hi
        ? `${num(m.protective_action.safe, lang)} सुरक्षित, ${num(m.protective_action.need_help, lang)} को मदद (कुल ${num(m.protective_action.asked, lang)})`
        : `${num(m.protective_action.safe, lang)} safe, ${num(m.protective_action.need_help, lang)} need help (of ${num(m.protective_action.asked, lang)})`
      : DASH,
    readiness: hi
      ? `${num(m.readiness.observers, lang)} / ${num(m.readiness.observers_needed, lang)} निगरानीकर्ता; सूची ${num(m.readiness.checklist.done ?? 0, lang)} / ${num(m.readiness.checklist.items, lang)}`
      : `${num(m.readiness.observers, lang)} of ${num(m.readiness.observers_needed, lang)} observers; checklist ${num(m.readiness.checklist.done ?? 0, lang)} of ${num(m.readiness.checklist.items, lang)}`,
  };
  return TEN.map((t) => ({ n: t.n, title: t.title[lang], value: values[t.key] ?? DASH }));
}

const GAP: Record<string, Txt> = {
  observers: { en: 'fewer than two observers or relays', hi: 'दो से कम निगरानीकर्ता या रिले' },
  women_observers: { en: 'fewer than half the observers are women', hi: 'आधे से कम निगरानीकर्ता महिलाएँ' },
  assisted_without_neighbour: { en: 'assisted households with no neighbour named', hi: 'मदद वाले घर जिनका कोई पड़ोसी तय नहीं' },
  household_list: { en: 'no household list yet', hi: 'घरों की सूची अभी नहीं' },
};

export function gapWord(gap: string, lang: Lang): string {
  return (GAP[gap] ?? { en: gap, hi: gap })[lang];
}
