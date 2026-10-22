import { useEffect, useId, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, CircleCheck, CircleDashed, CircleDot, RotateCcw } from 'lucide-react';
import { api, loadPilotReadiness } from '../api';
import { PageBand } from '../components/PageBand';
import { Reveal } from '../components/Reveal';
import { ErrorState, Skeleton } from '../components/States';
import { usePoll } from '../hooks/usePoll';
import { useT } from '../i18n';
import { fmtDate, fmtNumber, fmtTime } from '../lib/format';
import { DEFAULT_COST_INPUTS, estimatePilotCost, fmtRupees, fmtRupeesShort, type CostInputs, type CostLineKey } from '../lib/pilotCost';
import { countByStatus, parseReadiness, type Readiness, type ReadinessStatus } from '../lib/pilotReadiness';
import type { Lang } from '../store';
import type { PilotGroup, PilotMetrics } from '../types';

type Txt = { hi: string; en: string };
type Source = { label: string; href: string };

/** The day the list prices below were read from each provider's page. */
const CHECKED = '2026-10-22';
const GITHUB = 'https://github.com/Prashant-thakur77/pukaar';

const SRC = {
  plivo: { label: 'Plivo, India voice pricing', href: 'https://www.plivo.com/voice/pricing/in/' },
  awsVoice: { label: 'AWS End User Messaging pricing', href: 'https://aws.amazon.com/end-user-messaging/pricing/' },
  msg91: { label: 'MSG91 SMS pricing (excl. 18% GST)', href: 'https://www.msg91.com/in/pricing' },
  telegram: { label: 'Telegram Bot API FAQ', href: 'https://core.telegram.org/bots/faq' },
  polly: { label: 'Amazon Polly pricing', href: 'https://aws.amazon.com/polly/pricing/' },
  dlt1: { label: 'Message Central, India SMS rules', href: 'https://www.messagecentral.com/sms-guideline/india' },
  dlt2: { label: 'Infobip, DLT registration', href: 'https://www.infobip.com/docs/essentials/asia-registration/dlt-registration' },
  gca: {
    label: 'Global Commission on Adaptation, Adapt Now (2019), p.14',
    href: 'https://gca.org/wp-content/uploads/2019/09/GlobalCommission_Report_FINAL.pdf',
  },
} satisfies Record<string, Source>;

function Ext({ href, children, className = 'how-cite' }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className={className}>
      {children}
      <ArrowUpRight aria-hidden="true" className="how-ext" />
    </a>
  );
}

function SectionHead({ id, n, eyebrow, title, lead }: { id: string; n: string; eyebrow: string; title: string; lead?: ReactNode }) {
  return (
    <header className="pl-head">
      <p className="how-eyebrow">
        <span className="pl-n" aria-hidden="true">{n}</span> {eyebrow}
      </p>
      <h2 id={id} className="how-h">
        {title}
      </h2>
      {lead && <p className="pl-lead">{lead}</p>}
    </header>
  );
}

/* ------------------------------------------------------------------ 1. cost ------------------------------------------------------------------ */

type FieldKey = keyof CostInputs;
type Field = { key: FieldKey; label: Txt; unit: Txt; step: string; percent?: boolean; src?: Source[] };

const VILLAGE_FIELDS: Field[] = [
  { key: 'households', label: { en: 'Households in the village', hi: 'गाँव में घर' }, unit: { en: 'homes', hi: 'घर' }, step: '1' },
  { key: 'numbersPerHousehold', label: { en: 'Phone numbers per household', hi: 'हर घर में फ़ोन नंबर' }, unit: { en: 'per home', hi: 'प्रति घर' }, step: '0.1' },
  { key: 'eventsPerSeason', label: { en: 'Alert events per season', hi: 'एक मानसून में चेतावनियाँ' }, unit: { en: 'events', hi: 'बार' }, step: '1' },
  { key: 'recallShare', label: { en: 'Called again (did not confirm)', hi: 'दोबारा कॉल (पुष्टि नहीं की)' }, unit: { en: '%', hi: '%' }, step: '1', percent: true },
];

const PRICE_FIELDS: Field[] = [
  { key: 'voicePerMin', label: { en: 'Voice call, per minute', hi: 'वॉइस कॉल, प्रति मिनट' }, unit: { en: '₹/min', hi: '₹/मिनट' }, step: '0.01', src: [SRC.plivo, SRC.awsVoice] },
  { key: 'smsPerSegment', label: { en: 'SMS, per segment', hi: 'SMS, प्रति हिस्सा' }, unit: { en: '₹', hi: '₹' }, step: '0.01', src: [SRC.msg91] },
  { key: 'smsSegments', label: { en: 'Segments per Hindi SMS', hi: 'एक हिंदी SMS के हिस्से' }, unit: { en: '× 70 chars', hi: '× 70 अक्षर' }, step: '1' },
  { key: 'gstRate', label: { en: 'GST on telecom', hi: 'दूरसंचार पर GST' }, unit: { en: '%', hi: '%' }, step: '1', percent: true, src: [SRC.msg91] },
];

const SCALE_FIELDS: Field[] = [
  { key: 'villages', label: { en: 'Villages, for the total', hi: 'कुल के लिए गाँव' }, unit: { en: 'villages', hi: 'गाँव' }, step: '1' },
];

const ALL_FIELDS = [...VILLAGE_FIELDS, ...PRICE_FIELDS, ...SCALE_FIELDS];

type Draft = Record<FieldKey, string>;

function toDraft(i: CostInputs): Draft {
  const out = {} as Draft;
  for (const f of ALL_FIELDS) out[f.key] = String(f.percent ? Math.round(i[f.key] * 1000) / 10 : i[f.key]);
  out.minutesPerCall = String(i.minutesPerCall);
  return out;
}

function fromDraft(d: Draft): CostInputs {
  const out = { ...DEFAULT_COST_INPUTS };
  for (const f of ALL_FIELDS) {
    const v = Number.parseFloat(d[f.key].replace(',', '.'));
    out[f.key] = Number.isFinite(v) ? (f.percent ? v / 100 : v) : 0;
  }
  return out;
}

const LINE_LABEL: Record<CostLineKey, Txt> = {
  voice: { en: 'Voice call to every number', hi: 'हर नंबर पर वॉइस कॉल' },
  recall: { en: 'Re-call to those who did not confirm', hi: 'जिन्होंने पुष्टि नहीं की, उन्हें दोबारा कॉल' },
  sms: { en: 'Hindi SMS copy', hi: 'हिंदी SMS' },
  telegram: { en: 'Telegram, with “मिल गया”', hi: 'Telegram, “मिल गया” के साथ' },
  gst: { en: 'GST', hi: 'GST' },
};

function CostField({ f, value, onChange, lang }: { f: Field; value: string; onChange: (v: string) => void; lang: Lang }) {
  const id = useId();
  const unitId = `${id}-unit`;
  return (
    <div className="pl-field">
      <label htmlFor={id}>{f.label[lang]}</label>
      <span className="pl-input">
        <input
          id={id}
          type="number"
          inputMode="decimal"
          min={0}
          max={f.percent ? 100 : undefined}
          step={f.step}
          value={value}
          aria-describedby={unitId}
          onChange={(e) => onChange(e.target.value)}
        />
        <span id={unitId} className="pl-unit">
          {f.unit[lang]}
        </span>
      </span>
      {f.src && (
        <span className="pl-src">
          {f.src.map((s) => (
            <Ext key={s.href} href={s.href}>
              {s.label}
            </Ext>
          ))}
        </span>
      )}
    </div>
  );
}

function CostSection({ draft, setDraft }: { draft: Draft; setDraft: (d: Draft) => void }) {
  const { lang } = useT();
  const en = lang === 'en';
  const est = useMemo(() => estimatePilotCost(fromDraft(draft)), [draft]);
  const checked = `${en ? 'checked' : 'जाँचा'} ${fmtDate(CHECKED, lang)}`;
  const set = (k: FieldKey) => (v: string) => setDraft({ ...draft, [k]: v });
  const group = (legend: string, fields: Field[]) => (
    <fieldset className="pl-fieldset">
      <legend>{legend}</legend>
      {fields.map((f) => (
        <CostField key={f.key} f={f} value={draft[f.key]} onChange={set(f.key)} lang={lang} />
      ))}
    </fieldset>
  );
  const villages = est.inputs.villages;
  const lineSrc: Record<CostLineKey, Source[]> = { voice: [SRC.plivo], recall: [SRC.plivo], sms: [SRC.msg91], telegram: [SRC.telegram], gst: [SRC.msg91] };
  const unit: Record<CostLineKey, string> = {
    voice: `${fmtNumber(est.numbers, lang, 1)} × ${fmtRupees(est.inputs.voicePerMin)}`,
    recall: `${fmtNumber(est.recalls, lang, 1)} × ${fmtRupees(est.inputs.voicePerMin)}`,
    sms: `${fmtNumber(est.numbers, lang, 1)} × ${fmtNumber(est.inputs.smsSegments, lang)} × ${fmtRupees(est.inputs.smsPerSegment)}`,
    telegram: en ? 'Free Bot API' : 'मुफ़्त Bot API',
    gst: `${fmtNumber(est.inputs.gstRate * 100, lang, 1)}%`,
  };

  return (
    <section className="how-band how-cream pl-cost" aria-labelledby="pl-cost-h" id="cost">
      <div className="wrap-wide">
        <SectionHead
          id="pl-cost-h"
          n="01"
          eyebrow={en ? 'What it costs' : 'ख़र्च'}
          title={en ? 'Cost per village per season' : 'एक गाँव, एक मानसून का ख़र्च'}
          lead={
            en
              ? 'Each alert event is a voice call to every registered number, a second call to those who did not confirm, one Hindi SMS and Telegram. Change any number; the totals follow.'
              : 'हर चेतावनी में हर नंबर पर एक वॉइस कॉल, पुष्टि न करने वालों को दूसरी कॉल, एक हिंदी SMS और Telegram। कोई भी संख्या बदलें, जोड़ साथ बदलेगा।'
          }
        />
        <p className="pl-estimate" role="note">
          <strong>{en ? 'Estimate' : 'अनुमान'}</strong>
          <span>
            {en
              ? 'Replace with provider quotes and the measured AWS bill. List prices, read from each provider’s page; '
              : 'कंपनियों के कोटेशन और AWS के असली बिल से बदलें। हर कंपनी के पेज से ली गई सूची-क़ीमतें; '}
            {checked}.
          </span>
        </p>

        <div className="pl-calc">
          <form className="pl-form" onSubmit={(e) => e.preventDefault()} aria-label={en ? 'Cost inputs' : 'ख़र्च की संख्याएँ'}>
            {group(en ? 'The village' : 'गाँव', VILLAGE_FIELDS)}
            {group(en ? 'Prices' : 'क़ीमतें', PRICE_FIELDS)}
            <p className="pl-free">
              {en
                ? 'Telegram: free (Bot API). Polly, the Hindi voice: synthesised once per alert, under ₹1 an event, so not added. '
                : 'Telegram: मुफ़्त (Bot API)। Polly, हिंदी आवाज़: हर चेतावनी पर एक बार बनती है, ₹1 से कम, इसलिए जोड़ी नहीं। '}
              <Ext href={SRC.telegram.href}>{SRC.telegram.label}</Ext>
              <Ext href={SRC.polly.href}>{SRC.polly.label}</Ext>
            </p>
            {group(en ? 'Scale' : 'पैमाना', SCALE_FIELDS)}
            <button type="button" className="btn btn-ghost pl-reset" onClick={() => setDraft(toDraft(DEFAULT_COST_INPUTS))}>
              <RotateCcw aria-hidden="true" /> {en ? 'Back to the defaults' : 'शुरुआती संख्याएँ'}
            </button>
          </form>

          <div className="pl-result">
            <p className="pl-result-k">{en ? 'One village, one season' : 'एक गाँव, एक मानसून'}</p>
            <output className="pl-big" aria-live="polite">
              {fmtRupees(est.perSeason)}
            </output>
            <p className="pl-result-sub">
              {en
                ? `${fmtNumber(est.inputs.eventsPerSeason, lang)} events × ${fmtNumber(est.numbers, lang, 1)} numbers`
                : `${fmtNumber(est.inputs.eventsPerSeason, lang)} चेतावनियाँ × ${fmtNumber(est.numbers, lang, 1)} नंबर`}
            </p>
            <dl className="pl-figs">
              <div>
                <dt>{en ? 'Per alert event' : 'हर चेतावनी'}</dt>
                <dd>{fmtRupees(est.perEvent)}</dd>
              </div>
              <div>
                <dt>{en ? 'Per household, per season' : 'हर घर, एक मानसून'}</dt>
                <dd>{fmtRupees(est.perHousehold)}</dd>
              </div>
              <div>
                <dt>{en ? 'Per registered number' : 'हर पंजीकृत नंबर'}</dt>
                <dd>{fmtRupees(est.perNumber)}</dd>
              </div>
              <div>
                <dt>
                  {en ? `${fmtNumber(villages, lang)} villages, per season` : `${fmtNumber(villages, lang)} गाँव, एक मानसून`}
                </dt>
                <dd>{fmtRupeesShort(est.forVillages, lang)}</dd>
              </div>
            </dl>
            <p className="pl-result-note">{en ? 'Estimate, messaging only. Cloud and hardware below.' : 'अनुमान, सिर्फ़ संदेश। क्लाउड और हार्डवेयर नीचे।'}</p>
          </div>
        </div>

        <div className="table-wrap pl-table" tabIndex={0} role="region" aria-label={en ? 'Cost lines' : 'ख़र्च का ब्योरा'}>
          <table className="data-table stack-sm">
            <thead>
              <tr>
                <th scope="col">{en ? 'Item' : 'मद'}</th>
                <th scope="col">{en ? 'Each event' : 'हर बार'}</th>
                <th scope="col">{en ? 'Per event' : 'प्रति चेतावनी'}</th>
                <th scope="col">{en ? 'Per season' : 'प्रति मानसून'}</th>
                <th scope="col">{en ? 'Source' : 'स्रोत'}</th>
              </tr>
            </thead>
            <tbody>
              {est.lines.map((l) => (
                <tr key={l.key}>
                  <th scope="row">{LINE_LABEL[l.key][lang]}</th>
                  <td data-label={en ? 'Each event' : 'हर बार'}>{unit[l.key]}</td>
                  <td data-label={en ? 'Per event' : 'प्रति चेतावनी'} className="num">{fmtRupees(l.perEvent)}</td>
                  <td data-label={en ? 'Per season' : 'प्रति मानसून'} className="num">{fmtRupees(l.perSeason)}</td>
                  <td data-label={en ? 'Source' : 'स्रोत'}>
                    {lineSrc[l.key].map((s) => (
                      <Ext key={s.href} href={s.href}>
                        {s.label}
                      </Ext>
                    ))}
                    <span className="pl-checked">{checked}</span>
                  </td>
                </tr>
              ))}
              <tr className="pl-total">
                <th scope="row">{en ? 'Messaging total' : 'संदेशों का कुल'}</th>
                <td data-label={en ? 'Each event' : 'हर बार'}>{en ? 'Estimate' : 'अनुमान'}</td>
                <td data-label={en ? 'Per event' : 'प्रति चेतावनी'} className="num">{fmtRupees(est.perEvent)}</td>
                <td data-label={en ? 'Per season' : 'प्रति मानसून'} className="num">{fmtRupees(est.perSeason)}</td>
                <td data-label={en ? 'Source' : 'स्रोत'}>—</td>
              </tr>
            </tbody>
          </table>
        </div>

        <h3 className="pl-h3">{en ? 'Not in the sum' : 'जोड़ में शामिल नहीं'}</h3>
        <ul className="pl-rows">
          <li>
            <span className="pl-row-k">{en ? 'DLT registration' : 'DLT पंजीकरण'}</span>
            <span>
              {en
                ? '₹5,900 once per sending entity, plus ₹590 a year per header. Negligible at district scale. '
                : 'भेजने वाली संस्था के लिए एक बार ₹5,900, हर हेडर ₹590 सालाना। ज़िले के पैमाने पर नगण्य। '}
              <Ext href={SRC.dlt1.href}>{SRC.dlt1.label}</Ext>
              <Ext href={SRC.dlt2.href}>{SRC.dlt2.label}</Ext>
              <span className="pl-checked">{checked}</span>
            </span>
          </li>
          <li>
            <span className="pl-row-k">{en ? 'Cloud (AWS, serverless)' : 'क्लाउड (AWS, सर्वरलेस)'}</span>
            <span>
              <span className="pl-nm">{en ? 'Not measured yet.' : 'अभी मापा नहीं।'}</span>{' '}
              {en ? 'To be read from AWS Cost Explorer for one month of the live stack.' : 'लाइव स्टैक के एक महीने के लिए AWS Cost Explorer से पढ़ा जाएगा।'}
            </span>
          </li>
          <li>
            <span className="pl-row-k">{en ? 'River gauge' : 'नदी का गेज'}</span>
            <span>
              <span className="pl-nm">{en ? 'No sourced price yet.' : 'अभी कोई स्रोत वाली क़ीमत नहीं।'}</span>{' '}
              {en ? 'One-time hardware plus a SIM; two vendor quotes needed.' : 'एक बार का हार्डवेयर और एक SIM; दो कंपनियों के कोटेशन चाहिए।'}
            </span>
          </li>
        </ul>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ 2. measured ------------------------------------------------------------------ */

function NotYet() {
  const { lang } = useT();
  return <span className="pl-nm">{lang === 'en' ? 'not measured yet' : 'अभी मापा नहीं'}</span>;
}

function Measure({ value, label, note }: { value: ReactNode; label: string; note?: string }) {
  return (
    <li className="pl-stat">
      <span className="pl-stat-num">{value}</span>
      <span className="pl-stat-label">{label}</span>
      {note && <span className="pl-stat-note">{note}</span>}
    </li>
  );
}

function minutes(m: number | null, lang: Lang): ReactNode {
  if (m == null) return <NotYet />;
  return (
    <>
      {fmtNumber(m, lang, 1)}
      <small> {lang === 'en' ? 'min' : 'मिनट'}</small>
    </>
  );
}

function share(g: PilotGroup, lang: Lang): ReactNode {
  if (g.ack_share == null) return <NotYet />;
  return `${fmtNumber(g.ack_share * 100, lang, 0)}%`;
}

const hours = (h: number, lang: Lang) => `${fmtNumber(h, lang)} ${lang === 'en' ? 'h' : 'घंटे'}`;

function MeasuredBody({ m }: { m: PilotMetrics }) {
  const { lang } = useT();
  const en = lang === 'en';
  const d = m.drills;
  const l = m.live;
  return (
    <>
      <h3 className="pl-h3">{en ? 'Drills: labelled tests to real phones' : 'अभ्यास: असली फ़ोन पर, साफ़ लिखा परीक्षण'}</h3>
      <ul className="pl-stats">
        <Measure value={fmtNumber(d.alerts, lang)} label={en ? 'Drill alerts sent' : 'भेजे गए अभ्यास संदेश'} />
        <Measure
          value={fmtNumber(d.reached, lang)}
          label={en ? 'Phones reached' : 'फ़ोन तक पहुँचे'}
          note={en ? 'Summed over drills; demo recipients without a phone not counted' : 'सब अभ्यासों का जोड़; बिना फ़ोन वाले डेमो नाम नहीं गिने'}
        />
        <Measure value={share(d, lang)} label={en ? 'Pressed “मिल गया”' : '“मिल गया” दबाया'} />
        <Measure
          value={minutes(d.median_minutes_first_ack, lang)}
          label={en ? 'Median, send to first “मिल गया”' : 'मध्य समय, भेजने से पहले “मिल गया” तक'}
        />
      </ul>
      <h3 className="pl-h3">{en ? 'Live flood alerts' : 'असली बाढ़ चेतावनियाँ'}</h3>
      <ul className="pl-stats">
        <Measure value={fmtNumber(l.alerts, lang)} label={en ? 'Live alerts sent' : 'भेजी गई असली चेतावनियाँ'} note={en ? 'Never replays, never drills' : 'रीप्ले और अभ्यास नहीं'} />
        <Measure value={fmtNumber(l.reached, lang)} label={en ? 'Phones reached' : 'फ़ोन तक पहुँचे'} />
        <Measure value={share(l, lang)} label={en ? 'Pressed “मिल गया”' : '“मिल गया” दबाया'} />
        <Measure
          value={minutes(l.median_minutes_first_ack, lang)}
          label={en ? 'Median, send to first “मिल गया”' : 'मध्य समय, भेजने से पहले “मिल गया” तक'}
        />
      </ul>

      <h3 className="pl-h3">{en ? 'Back-test: hours of warning before the river’s peak day' : 'बैक-टेस्ट: नदी के सबसे ऊँचे दिन से पहले कितने घंटे की चेतावनी'}</h3>
      {m.backtest && m.backtest.scenarios.length > 0 ? (
        <ul className="pl-rows pl-bt">
          {m.backtest.scenarios.map((s) => (
            <li key={s.name}>
              <span className="pl-row-k">{(en ? s.title : s.title_hi) || s.title}</span>
              <span className="pl-bt-main">
                <span className="pl-bt-num">{s.median_lead_hours == null ? <NotYet /> : hours(s.median_lead_hours, lang)}</span>
                <span className="pl-bt-cap">
                  {en
                    ? `median lead · ${s.villages_alerted} of ${s.villages_scored} villages reached Watch${s.max_lead_hours != null ? ` · up to ${fmtNumber(s.max_lead_hours, lang)} h` : ''}`
                    : `मध्य समय · ${s.villages_scored} में से ${s.villages_alerted} गाँव “सतर्क” तक${s.max_lead_hours != null ? ` · अधिकतम ${fmtNumber(s.max_lead_hours, lang)} घंटे` : ''}`}
                </span>
                <span className="meta-line">
                  {s.villages.map((v) => (
                    <span key={v.village_id}>
                      {v.village} {v.lead_hours == null ? (en ? 'no alert' : 'चेतावनी नहीं') : `${v.lead_is_lower_bound ? '≥ ' : ''}${hours(v.lead_hours, lang)}`}
                      {v.get_ready_lead_hours != null &&
                        (en
                          ? ` (get ready ${v.get_ready_is_lower_bound ? '≥ ' : ''}${hours(v.get_ready_lead_hours, lang)})`
                          : ` (तैयार रहें ${v.get_ready_is_lower_bound ? '≥ ' : ''}${hours(v.get_ready_lead_hours, lang)})`)}
                    </span>
                  ))}
                </span>
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p>
          <NotYet />
        </p>
      )}
      <p className="pl-caveat">
        {en
          ? 'Back-test lead times are on archived forecasts, from the first Watch (the alert) to the river’s peak day; they are not a live season. In brackets, the get-ready outlook, which the officer and pradhan see but which never alerts; ≥ means it was on from the first archived hour. In 2025 the global forecasts missed the Mandi cloudburst. '
          : 'बैक-टेस्ट पुराने पूर्वानुमानों पर है, पहले “सतर्क” (चेतावनी) से नदी के सबसे ऊँचे दिन तक; यह असली मानसून नहीं। कोष्ठक में “तैयार रहें” आउटलुक है, जो अधिकारी और प्रधान को दिखता है पर कभी चेतावनी नहीं बनता; ≥ का मतलब पहले रिकॉर्ड घंटे से चालू। 2025 में वैश्विक पूर्वानुमान मंडी का बादल-फटना नहीं पकड़ पाए। '}
        <Link to="/impact">{en ? 'The full back-test' : 'पूरा बैक-टेस्ट'} →</Link>
      </p>
      <p className="pl-asof">
        {en ? 'From the API, GET /public/pilot-metrics, at ' : 'API से, GET /public/pilot-metrics, समय '}
        <span translate="no">{fmtTime(m.as_of, lang)}</span>
      </p>
    </>
  );
}

function MeasuredSection() {
  const { lang } = useT();
  const en = lang === 'en';
  const { data, error, loading, refresh } = usePoll(() => api.pilotMetrics(), [], 0);
  return (
    <section className="how-band how-loop pl-measured" aria-labelledby="pl-m-h" id="measured">
      <div className="wrap-wide">
        <SectionHead
          id="pl-m-h"
          n="02"
          eyebrow={en ? 'Measured' : 'मापा गया'}
          title={en ? 'Measured so far' : 'अब तक क्या मापा'}
          lead={
            en
              ? 'Real records only, counted by the API from stored alerts and deliveries. Where nothing has been measured, the page says so.'
              : 'सिर्फ़ असली रिकॉर्ड, API दर्ज चेतावनियों और डिलीवरी से गिनता है। जो मापा नहीं गया, पेज वही कहता है।'
          }
        />
        {data ? (
          <MeasuredBody m={data} />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refresh()} />
        ) : loading ? (
          <Skeleton lines={6} />
        ) : null}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ 3. readiness ------------------------------------------------------------------ */

const STATUS: Record<ReadinessStatus, { word: Txt; Icon: typeof CircleCheck }> = {
  done: { word: { en: 'Done', hi: 'हो गया' }, Icon: CircleCheck },
  in_progress: { word: { en: 'In progress', hi: 'चल रहा है' }, Icon: CircleDot },
  not_started: { word: { en: 'Not started', hi: 'शुरू नहीं' }, Icon: CircleDashed },
};

function ReadinessSection() {
  const { lang } = useT();
  const en = lang === 'en';
  const [doc, setDoc] = useState<Readiness | null | undefined>(undefined);
  useEffect(() => {
    void loadPilotReadiness().then((raw) => setDoc(parseReadiness(raw)));
  }, []);
  const counts = doc ? countByStatus(doc.items) : null;
  return (
    <section className="how-band how-cream pl-ready" aria-labelledby="pl-r-h" id="ready">
      <div className="wrap-wide">
        <SectionHead
          id="pl-r-h"
          n="03"
          eyebrow={en ? 'Road to deployment' : 'तैनाती का रास्ता'}
          title={en ? 'Pilot readiness' : 'पायलट की तैयारी'}
          lead={
            en
              ? 'What has to be true before Pukaar warns a real village, who owns each step, and where it stands today.'
              : 'किसी असली गाँव को चेतावनी देने से पहले क्या होना ज़रूरी है, हर क़दम किसके ज़िम्मे है, और आज वह कहाँ है।'
          }
        />
        {doc === undefined ? (
          <Skeleton lines={6} />
        ) : doc === null ? (
          <p className="pl-nm">{en ? 'The checklist is not available.' : 'सूची उपलब्ध नहीं है।'}</p>
        ) : (
          <>
            <p className="meta-line pl-ready-sum">
              {(['done', 'in_progress', 'not_started'] as const).map((s) => (
                <span key={s}>
                  <b>{fmtNumber(counts![s], lang)}</b> {STATUS[s].word[lang].toLowerCase()}
                </span>
              ))}
              {doc.updated && (
                <span>
                  {en ? 'updated' : 'अपडेट'} {fmtDate(doc.updated, lang)}
                </span>
              )}
            </p>
            <ol className="pl-check">
              {doc.items.map((it) => {
                const st = STATUS[it.status];
                return (
                  <li key={it.id} className={`pl-item is-${it.status}`}>
                    <span className="pl-status">
                      <st.Icon aria-hidden="true" /> {st.word[lang]}
                    </span>
                    <div className="pl-item-body">
                      <h3 className="pl-item-title">{it.title[lang]}</h3>
                      <p className="pl-why">{it.why[lang]}</p>
                      {it.note && <p className="pl-note">{it.note[lang]}</p>}
                    </div>
                    <p className="pl-owner">
                      <span className="pl-owner-k">{en ? 'Owner' : 'ज़िम्मेदार'}</span> {it.owner[lang]}
                    </p>
                  </li>
                );
              })}
            </ol>
            <p className="pl-asof">
              {en ? 'Statuses are kept in ' : 'स्थिति यहाँ रखी जाती है: '}
              <Ext href={`${GITHUB}/blob/main/data/pilot_readiness.json`}>data/pilot_readiness.json</Ext>
            </p>
          </>
        )}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ 4. real vs next ------------------------------------------------------------------ */

const LIVE: Txt[] = [
  { en: 'The 15-minute sweep and the risk rules, per village', hi: 'हर 15 मिनट की जाँच और हर गाँव के जोखिम नियम' },
  { en: 'One-tap approval, escalating to the next officer', hi: 'एक टैप मंज़ूरी, जवाब न मिले तो अगले अधिकारी को' },
  { en: 'The spoken Hindi alert (Polly)', hi: 'बोलकर हिंदी चेतावनी (Polly)' },
  { en: 'Telegram with “मिल गया” and a re-send to anyone who has not', hi: 'Telegram पर “मिल गया”, और जिसने नहीं दबाया उसे दोबारा' },
  { en: 'A CAP 1.2 feed, the format SACHET reads', hi: 'CAP 1.2 फ़ीड, जिस मानक को SACHET पढ़ता है' },
  { en: 'The “Are you safe?” roll-call', hi: '“क्या आप सुरक्षित हैं?” हाज़िरी' },
  { en: 'Safe places, walking routes and road blocks', hi: 'सुरक्षित जगहें, पैदल रास्ते और बंद सड़कें' },
  { en: 'An audit trail of every allow and deny', hi: 'हर हाँ और ना का ऑडिट रिकॉर्ड' },
  { en: 'The back-test on archived floods', hi: 'पुरानी बाढ़ों पर बैक-टेस्ट' },
];

const NEXT: Txt[] = [
  { en: 'Voice calls and SMS to keypad phones', hi: 'कीपैड फ़ोन पर वॉइस कॉल और SMS' },
  { en: 'An installed river gauge (simulated today)', hi: 'लगा हुआ नदी गेज (आज सिम्युलेटेड)' },
  { en: 'A voice in the local language (Mandeali, Kangri)', hi: 'स्थानीय बोली में आवाज़ (मंडियाली, कांगड़ी)' },
  { en: 'A pilot with a district authority (DDMA)', hi: 'ज़िला प्राधिकरण (DDMA) के साथ पायलट' },
  { en: 'The model drafting the Hindi alert (pending model access; a fixed template runs until then)', hi: 'मॉडल से हिंदी संदेश (मॉडल की अनुमति बाक़ी; तब तक तय ढाँचा चलता है)' },
];

function RealSection() {
  const { lang } = useT();
  const en = lang === 'en';
  return (
    <section className="how-band how-loop pl-real" aria-labelledby="pl-real-h" id="real">
      <div className="wrap-wide">
        <SectionHead
          id="pl-real-h"
          n="04"
          eyebrow={en ? 'Honest scope' : 'सच्चा दायरा'}
          title={en ? 'Real today, and next' : 'आज असली, और आगे'}
          lead={
            en ? (
              <>
                The same split as “Built versus planned” in the{' '}
                <Ext href={`${GITHUB}#built-versus-planned`} className="pl-inline">
                  README
                </Ext>
                .
              </>
            ) : (
              <>
                वही बँटवारा जो{' '}
                <Ext href={`${GITHUB}#built-versus-planned`} className="pl-inline">
                  README
                </Ext>{' '}
                के “Built versus planned” में है।
              </>
            )
          }
        />
        <div className="pl-two">
          <div className="pl-col is-live">
            <h3 className="pl-col-h">
              <CircleCheck aria-hidden="true" /> {en ? 'Live on the deployed stack' : 'तैनात स्टैक पर चालू'}
            </h3>
            <ul>
              {LIVE.map((x) => (
                <li key={x.en}>{x[lang]}</li>
              ))}
            </ul>
          </div>
          <div className="pl-col is-next">
            <h3 className="pl-col-h">
              <CircleDashed aria-hidden="true" /> {en ? 'Next' : 'आगे'}
            </h3>
            <ul>
              {NEXT.map((x) => (
                <li key={x.en}>{x[lang]}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ 5. plan ------------------------------------------------------------------ */

const PLAN: { when: Txt; title: Txt; what: Txt; metrics: Txt[] }[] = [
  {
    when: { en: 'Week 0', hi: 'हफ़्ता 0' },
    title: { en: 'Sign-off', hi: 'मंज़ूरी' },
    what: {
      en: 'DDMA sign-off for the pilot villages and the auto-send rule; DLT registration of the sender, header and Hindi templates.',
      hi: 'पायलट गाँवों और अपने-आप भेजने के नियम पर DDMA की मंज़ूरी; भेजने वाले, हेडर और हिंदी ढाँचों का DLT पंजीकरण।',
    },
    metrics: [
      { en: 'DDMA letter on file', hi: 'DDMA का पत्र' },
      { en: 'DLT entity, header and templates approved', hi: 'DLT संस्था, हेडर और ढाँचे मंज़ूर' },
    ],
  },
  {
    when: { en: 'Weeks 1–4', hi: 'हफ़्ते 1–4' },
    title: { en: 'Onboard and drill', hi: 'जोड़ना और अभ्यास' },
    what: {
      en: 'Pradhan consent and a Hindi data notice; households enrolled; safe places walked; a labelled drill in each village.',
      hi: 'प्रधान की सहमति और हिंदी में डेटा सूचना; घर जोड़े गए; सुरक्षित जगहें पैदल जाँचीं; हर गाँव में साफ़ लिखा अभ्यास।',
    },
    metrics: [
      { en: 'Households enrolled, of all households', hi: 'कुल घरों में से जुड़े घर' },
      { en: 'Drill: share reached and share who pressed “मिल गया”', hi: 'अभ्यास: कितनों तक पहुँचा, कितनों ने “मिल गया” दबाया' },
      { en: 'Median minutes to confirm', hi: 'पुष्टि तक का मध्य समय (मिनट)' },
      { en: 'Could name their safe place (3 questions by phone)', hi: 'अपनी सुरक्षित जगह बता सके (फ़ोन पर 3 सवाल)' },
    ],
  },
  {
    when: { en: 'Weeks 5–12', hi: 'हफ़्ते 5–12' },
    title: { en: 'Live or drill season', hi: 'असली या अभ्यास का मौसम' },
    what: {
      en: 'Live alerts in the monsoon, or monthly drills outside it; an after-action report for each; the AWS bill and provider invoices read.',
      hi: 'मानसून में असली चेतावनी, बाक़ी समय हर महीने अभ्यास; हर एक की बाद की रिपोर्ट; AWS बिल और कंपनियों के बिल पढ़े गए।',
    },
    metrics: [
      { en: 'Lead time: level rise to the first “मिल गया”', hi: 'स्तर बढ़ने से पहले “मिल गया” तक का समय' },
      { en: 'Approval time and auto-sends', hi: 'मंज़ूरी का समय और अपने-आप भेजी गई चेतावनियाँ' },
      { en: 'False alarms and misses, against what happened', hi: 'जो हुआ उससे मिलाकर ग़लत चेतावनियाँ और छूटी घटनाएँ' },
      { en: 'Measured cost per village', hi: 'हर गाँव का मापा गया ख़र्च' },
    ],
  },
];

function PlanSection() {
  const { lang } = useT();
  const en = lang === 'en';
  return (
    <section className="how-band how-cream pl-plan" aria-labelledby="pl-plan-h" id="plan">
      <div className="wrap-wide">
        <SectionHead
          id="pl-plan-h"
          n="05"
          eyebrow={en ? '90 days' : '90 दिन'}
          title={en ? 'A 90-day pilot' : '90 दिन का पायलट'}
          lead={en ? 'Three phases, each with the numbers it must produce.' : 'तीन चरण, हर एक के साथ वे आँकड़े जो उसे देने हैं।'}
        />
        <ol className="pl-phases">
          {PLAN.map((p, i) => (
            <Reveal as="li" key={p.when.en} className="pl-phase" delay={i * 80}>
              <span className="pl-when">{p.when[lang]}</span>
              <div>
                <h3 className="pl-phase-title">{p.title[lang]}</h3>
                <p>{p.what[lang]}</p>
                <p className="pl-metrics-k">{en ? 'Measured' : 'मापेंगे'}</p>
                <ul className="pl-metrics">
                  {p.metrics.map((m) => (
                    <li key={m.en}>{m[lang]}</li>
                  ))}
                </ul>
              </div>
            </Reveal>
          ))}
        </ol>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ 6. why it pays ------------------------------------------------------------------ */

function PaysSection({ perSeason, villages }: { perSeason: number; villages: number }) {
  const { lang } = useT();
  const en = lang === 'en';
  return (
    <section className="how-band how-gold pl-pays" aria-labelledby="pl-pays-h" id="pays">
      <div className="wrap-wide">
        <SectionHead id="pl-pays-h" n="06" eyebrow={en ? 'The case' : 'तर्क'} title={en ? 'Why it pays' : 'यह क्यों फ़ायदेमंद है'} />
        <div className="pl-pays-grid">
          <figure className="pl-quote">
            <span className="how-stat-num" aria-hidden="true">10×</span>
            <blockquote>
              <p>
                {en
                  ? '“Early warning systems save lives and assets worth at least ten times their cost.”'
                  : '“चेतावनी व्यवस्थाएँ अपनी लागत से कम से कम दस गुना मूल्य की जानें और संपत्ति बचाती हैं।”'}
              </p>
            </blockquote>
            <figcaption>
              <Ext href={SRC.gca.href}>{SRC.gca.label}</Ext>
            </figcaption>
          </figure>
          <div className="pl-pays-side">
            <p className="pl-pays-line">
              <span className="pl-pays-k">{en ? 'At the inputs above' : 'ऊपर की संख्याओं पर'}</span>
              {en
                ? `${fmtNumber(villages, lang)} villages ≈ ${fmtRupeesShort(perSeason * villages, lang)} a season in messaging (estimate).`
                : `${fmtNumber(villages, lang)} गाँव ≈ एक मानसून में ${fmtRupeesShort(perSeason * villages, lang)} संदेशों पर (अनुमान)।`}
            </p>
            <p className="pl-pays-line">
              <span className="pl-pays-k">{en ? 'Who pays' : 'कौन देगा'}</span>
              {en
                ? 'A district or state disaster authority (DDMA, SDMA) from its mitigation funds, a company’s CSR budget, or a dam operator for the villages below its spillway.'
                : 'ज़िला या राज्य आपदा प्राधिकरण (DDMA, SDMA) अपने न्यूनीकरण कोष से, किसी कंपनी का CSR बजट, या बाँध चलाने वाली कंपनी अपने स्पिलवे के नीचे के गाँवों के लिए।'}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ page ------------------------------------------------------------------ */

const TOC: { id: string; t: Txt }[] = [
  { id: 'cost', t: { en: 'Cost', hi: 'ख़र्च' } },
  { id: 'measured', t: { en: 'Measured', hi: 'मापा गया' } },
  { id: 'ready', t: { en: 'Readiness', hi: 'तैयारी' } },
  { id: 'real', t: { en: 'Real and next', hi: 'असली और आगे' } },
  { id: 'plan', t: { en: '90-day plan', hi: '90 दिन' } },
  { id: 'pays', t: { en: 'Why it pays', hi: 'क्यों फ़ायदेमंद' } },
];

export default function Pilot() {
  const { lang } = useT();
  const en = lang === 'en';
  const [draft, setDraft] = useState<Draft>(() => toDraft(DEFAULT_COST_INPUTS));
  const est = useMemo(() => estimatePilotCost(fromDraft(draft)), [draft]);
  return (
    <div className="how pilot">
      <PageBand
        eyebrow={en ? 'For a district, a jury or a funder' : 'ज़िले, निर्णायकों या फ़ंड देने वालों के लिए'}
        title={en ? 'A pilot: cost, proof and readiness' : 'पायलट: ख़र्च, सबूत और तैयारी'}
        lead={
          en
            ? 'What a pilot costs, what has been measured, how ready deployment is, and what is real today versus next. Estimates are labelled; measured numbers come from the API.'
            : 'पायलट का ख़र्च, अब तक क्या मापा, तैनाती कितनी तैयार है, और आज क्या असली है, क्या आगे। अनुमान पर अनुमान लिखा है; मापे गए आँकड़े API से आते हैं।'
        }
      >
        <nav className="pl-toc" aria-label={en ? 'On this page' : 'इस पेज पर'}>
          <ol>
            {TOC.map((x, i) => (
              <li key={x.id}>
                <Link to={{ hash: x.id }}>
                  <span className="pl-toc-n" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span> {x.t[lang]}
                </Link>
              </li>
            ))}
          </ol>
        </nav>
      </PageBand>
      <CostSection draft={draft} setDraft={setDraft} />
      <MeasuredSection />
      <ReadinessSection />
      <RealSection />
      <PlanSection />
      <PaysSection perSeason={est.perSeason} villages={est.inputs.villages} />
    </div>
  );
}
