import { useEffect, useId, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, CircleCheck, CircleDashed, CircleDot, RotateCcw } from 'lucide-react';
import { loadPilotReadiness } from '../api';
import { Skeleton } from '../components/States';
import { TenMetrics } from '../components/TenMetrics';
import { useT } from '../i18n';
import { fmtDate, fmtNumber } from '../lib/format';
import {
  DEFAULT_COST_INPUTS,
  DISTRICT_CASES,
  FIXED_TELECOM,
  SCALES,
  UNIT_COSTS,
  averted,
  avertedWithoutLives,
  benefitCostRatio,
  breakEven,
  estimatePilotCost,
  fmtRupees,
  fmtRupeesAbout,
  fmtRupeesShort,
  longCallRisk,
  scaleCost,
  type CaseKey,
  type CostInputs,
  type CostLineKey,
  type ScaleKey,
  type ScaleLineKey,
} from '../lib/pilotCost';
import { countByStatus, parseReadiness, type Readiness, type ReadinessStatus } from '../lib/pilotReadiness';
import type { Lang } from '../store';
import '../styles/story.css';
import '../styles/explain.css';

// The hero's three figures, from the same estimates as the sections below (lib/pilotCost.ts), never typed by hand.
const GLANCE_ALL_IN = fmtRupeesAbout(scaleCost(SCALES.district).perVillage);
const GLANCE_MESSAGING = fmtRupees(estimatePilotCost(DEFAULT_COST_INPUTS).perSeason);

type Txt = { hi: string; en: string };
type Source = { label: string; hi?: string; href: string };
const srcLabel = (s: Source, lang: Lang) => (lang === 'hi' && s.hi) || s.label;

/** The day the list prices below were read from each provider's page. */
const CHECKED = '2026-10-22';
const GITHUB = 'https://github.com/Prashant-thakur77/pukaar';

const SRC = {
  plivo: { label: 'Plivo, India voice pricing', hi: 'Plivo, भारत में कॉल की दरें', href: 'https://www.plivo.com/voice/pricing/in/' },
  awsVoice: { label: 'AWS End User Messaging pricing', hi: 'AWS End User Messaging की दरें', href: 'https://aws.amazon.com/end-user-messaging/pricing/' },
  msg91: { label: 'MSG91 SMS pricing (excl. 18% GST)', hi: 'MSG91, SMS की दरें (18% GST के बिना)', href: 'https://www.msg91.com/in/pricing' },
  telegram: { label: 'Telegram Bot API FAQ', hi: 'Telegram Bot API: आम सवाल', href: 'https://core.telegram.org/bots/faq' },
  polly: { label: 'Amazon Polly pricing', hi: 'Amazon Polly की दरें', href: 'https://aws.amazon.com/polly/pricing/' },
  dlt1: { label: 'Message Central, India SMS rules', hi: 'Message Central, भारत में SMS के नियम', href: 'https://www.messagecentral.com/sms-guideline/india' },
  dlt2: { label: 'Infobip, DLT registration', hi: 'Infobip, DLT पंजीकरण', href: 'https://www.infobip.com/docs/essentials/asia-registration/dlt-registration' },
  census: { label: 'Mandi district, Census 2011 (villageinfo.org)', hi: 'ज़िला मंडी, जनगणना 2011 (villageinfo.org)', href: 'https://villageinfo.org/district/mandi' },
  vsl: { label: 'Indian value of a statistical life (ISEC WP 407)', hi: 'एक सांख्यिकीय जीवन का भारतीय मूल्य (ISEC WP 407)', href: 'https://econpapers.repec.org/RePEc:sch:wpaper:407' },
  hallegatte: { label: 'Hallegatte 2012, World Bank WPS 6058', hi: 'Hallegatte 2012, विश्व बैंक WPS 6058', href: 'http://documents1.worldbank.org/curated/en/190261468181486694/txt/WPS6058.txt' },
  karnali: {
    label: 'Rai et al. 2020, Karnali flood EWS', hi: 'Rai और साथी 2020, कर्णाली की बाढ़ चेतावनी',
    href: 'https://www.dpnet.org.np/public/uploads/files/CBA%20of%20EWS%20in%20Karnali%20Feb%202020%202021-09-12%2010-18-25.pdf',
  },
  sdmf: { label: 'MHA SDMF guidelines, 2022', hi: 'गृह मंत्रालय, SDMF के नियम, 2022', href: 'https://srcodisha.nic.in/dmrule/SDMF%20Guidelines.pdf' },
} satisfies Record<string, Source>;

function Ext({ href, children, className = 'xp-src' }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className={className}>
      {children}
      <ArrowUpRight aria-hidden="true" className="how-ext" />
    </a>
  );
}

function SectionHead({ id, title, lead }: { id: string; n?: string; eyebrow?: string; title: string; lead?: ReactNode }) {
  return (
    <header className="pl-head">
      <h2 id={id} className="xp-h2">
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
  {
    key: 'minutesPerCall',
    label: { en: 'Minutes billed per answered call', hi: 'हर उठाई गई कॉल के बिल वाले मिनट' },
    unit: { en: 'min', hi: 'मिनट' },
    step: '1',
    src: [SRC.plivo],
  },
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
  telegram: { en: 'Telegram, with “Got it”', hi: 'Telegram, “मिल गया” के साथ' },
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
              {srcLabel(s, lang)}
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
  const long = useMemo(() => longCallRisk(fromDraft(draft)), [draft]);
  const checked =`${en ? 'checked' : 'जाँचा'} ${fmtDate(CHECKED, lang)}`;
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
      <div className="wrap">
        <SectionHead
          id="pl-cost-h"
          n="01"
          eyebrow={en ? 'What it costs' : 'ख़र्च'}
          title={en ? 'Messaging cost per village per season' : 'एक गाँव, एक मानसून: संदेशों का ख़र्च'}
          lead={
            en
              ? 'As designed, each alert event is a voice call to every registered number, a second call to those who did not confirm, one Hindi SMS and Telegram (today only Telegram is live). The default village is an average Mandi village: 71 households (Census 2011). Change any number; the totals follow.'
              : 'योजना के अनुसार हर चेतावनी में हर नंबर पर एक वॉइस कॉल, पुष्टि न करने वालों को दूसरी कॉल, एक हिंदी SMS और Telegram (आज सिर्फ़ Telegram चालू है)। शुरुआती गाँव मंडी का औसत गाँव है: 71 घर (जनगणना 2011)। कोई भी संख्या बदलें, जोड़ साथ बदलेगा।'
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
          <div className="pl-result">
            <p className="pl-result-k">{en ? 'Messaging only: one village, one season' : 'सिर्फ़ संदेश: एक गाँव, एक मानसून'}</p>
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
            <p className="pl-result-note">{en ? 'Estimate, messaging only. Not the cost of running the system:' : 'अनुमान, सिर्फ़ संदेश। पूरी व्यवस्था चलाने का ख़र्च नहीं:'}</p>
            <p className="pl-allin">
              <span className="pl-allin-k">{en ? 'All-in, district scale' : 'सब मिलाकर, ज़िले के पैमाने पर'}</span>
              <span className="pl-allin-v">
                {en ? `about ${ALL_IN_PER_VILLAGE} per village per year` : `लगभग ${ALL_IN_PER_VILLAGE} प्रति गाँव प्रति वर्ष`}
              </span>
              <span className="pl-allin-sub">
                {en
                  ? 'People, drills, sirens in one village in five, the platform fee, cloud and messaging, for 300 villages. '
                  : '300 गाँवों के लिए लोग, अभ्यास, हर पाँच में से एक गाँव में सायरन, प्लेटफ़ॉर्म फ़ीस, क्लाउड और संदेश। '}
                <a href="#pays" className="pl-inline">
                  {en ? 'The breakdown' : 'ब्योरा'}
                </a>
              </span>
            </p>
          </div>
          <details className="xp-dis pl-inputs">
            <summary>{en ? 'Enter your own numbers' : 'अपनी संख्याएँ डालें'}</summary>
          <form className="pl-form" onSubmit={(e) => e.preventDefault()} aria-label={en ? 'Cost inputs' : 'ख़र्च की संख्याएँ'}>
              {group(en ? 'The village' : 'गाँव', VILLAGE_FIELDS)}
              {group(en ? 'Prices' : 'क़ीमतें', PRICE_FIELDS)}
              <p className="pl-free">
                {en
                  ? 'Telegram: free (Bot API). Polly, the Hindi voice: synthesised once per alert, under ₹1 an event, so not added. '
                  : 'Telegram: मुफ़्त (Bot API)। Polly, हिंदी आवाज़: हर चेतावनी पर एक बार बनती है, ₹1 से कम, इसलिए जोड़ी नहीं। '}
                <Ext href={SRC.telegram.href}>{srcLabel(SRC.telegram, lang)}</Ext>
                <Ext href={SRC.polly.href}>{srcLabel(SRC.polly, lang)}</Ext>
              </p>
              {group(en ? 'Scale' : 'पैमाना', SCALE_FIELDS)}
              <button type="button" className="btn btn-ghost pl-reset" onClick={() => setDraft(toDraft(DEFAULT_COST_INPUTS))}>
                <RotateCcw aria-hidden="true" /> {en ? 'Back to the defaults' : 'शुरुआती संख्याएँ'}
              </button>
            </form>
          </details>
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
                        {srcLabel(s, lang)}
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
            <span className="pl-row-k">{en ? 'Calls past 60 seconds' : '60 सेकंड से लंबी कॉल'}</span>
            <span>
              {en
                ? `If the Hindi alert and the “press 1” prompt run past a minute, each answered call bills 2 minutes on a 1-minute pulse: +${fmtRupees(long.extra)} a season here (+${fmtNumber(long.share * 100, lang, 0)}%). The alert’s length has to be measured before the price is quoted. `
                : `अगर हिंदी चेतावनी और “1 दबाएँ” एक मिनट से लंबे हों, तो 1 मिनट की पल्स पर हर उठाई गई कॉल के 2 मिनट लगते हैं: यहाँ एक मानसून में +${fmtRupees(long.extra)} (+${fmtNumber(long.share * 100, lang, 0)}%)। क़ीमत बताने से पहले चेतावनी की लंबाई मापनी होगी। `}
              <Ext href={SRC.plivo.href}>{srcLabel(SRC.plivo, lang)}</Ext>
            </span>
          </li>
          <li>
            <span className="pl-row-k">{en ? 'Number rental' : 'नंबर का किराया'}</span>
            <span>
              {en
                ? `${fmtRupees(FIXED_TELECOM.numberRentalPerMonth)} a month for the calling number (${fmtRupees(FIXED_TELECOM.numberRentalPerMonth * 12)} a year), once per deployment, not per village. `
                : `कॉल करने वाले नंबर का ${fmtRupees(FIXED_TELECOM.numberRentalPerMonth)} महीना (${fmtRupees(FIXED_TELECOM.numberRentalPerMonth * 12)} साल), हर तैनाती पर एक बार, हर गाँव पर नहीं। `}
              <Ext href={SRC.plivo.href}>{srcLabel(SRC.plivo, lang)}</Ext>
            </span>
          </li>
          <li>
            <span className="pl-row-k">{en ? 'DLT registration' : 'DLT पंजीकरण'}</span>
            <span>
              {en
                ? `${fmtRupees(FIXED_TELECOM.dltOneOff)} once per sending entity, plus ${fmtRupees(FIXED_TELECOM.dltPerHeaderYear)} a year per header. The sending entity must be the DDMA, not Pukaar. `
                : `भेजने वाली संस्था के लिए एक बार ${fmtRupees(FIXED_TELECOM.dltOneOff)}, हर हेडर ${fmtRupees(FIXED_TELECOM.dltPerHeaderYear)} सालाना। भेजने वाली संस्था DDMA होनी चाहिए, पुकार नहीं। `}
              <Ext href={SRC.dlt1.href}>{srcLabel(SRC.dlt1, lang)}</Ext>
              <Ext href={SRC.dlt2.href}>{srcLabel(SRC.dlt2, lang)}</Ext>
              <span className="pl-checked">{checked}</span>
            </span>
          </li>
          <li>
            <span className="pl-row-k">{en ? 'Cloud (AWS, serverless)' : 'क्लाउड (AWS, सर्वरलेस)'}</span>
            <span>
              <span className="pl-nm">{en ? 'Not measured yet.' : 'अभी मापा नहीं।'}</span>{' '}
              {en
                ? 'Estimated from AWS ap-south-1 list prices at under ₹1,000 a village a year; to be replaced by one month of the live stack’s bill.'
                : 'AWS ap-south-1 की सूची-क़ीमतों से अनुमान: हर गाँव ₹1,000 सालाना से कम; लाइव स्टैक के एक महीने के बिल से बदला जाएगा।'}
            </span>
          </li>
          <li>
            <span className="pl-row-k">{en ? 'Sirens, gauges, rain nodes' : 'सायरन, गेज, बारिश मापक'}</span>
            <span>
              {en
                ? `About ${fmtRupeesShort(UNIT_COSTS.alarmCapex, lang)} per village once and ${fmtRupees(UNIT_COSTS.alarmOpex)} a year, from a bill of materials that is untested on hardware (docs/hardware/ALARM.md).`
                : `हर गाँव लगभग ${fmtRupeesShort(UNIT_COSTS.alarmCapex, lang)} एक बार और ${fmtRupees(UNIT_COSTS.alarmOpex)} सालाना, ऐसी सामग्री-सूची से जो हार्डवेयर पर परखी नहीं गई (docs/hardware/ALARM.md)।`}
            </span>
          </li>
          <li>
            <span className="pl-row-k">{en ? 'People' : 'लोग'}</span>
            <span>
              {en
                ? 'Field coordinators, technicians, enrolment and drills: the largest costs. In the all-in figure below.'
                : 'फ़ील्ड समन्वयक, तकनीशियन, नाम जोड़ना और अभ्यास: सबसे बड़े ख़र्च। नीचे के कुल में शामिल।'}
            </span>
          </li>
        </ul>
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

/* ------------------------------------------------------------------ the ten metrics ------------------------------------------------------------------ */

function MetricsSection() {
  const { lang } = useT();
  const en = lang === 'en';
  return (
    <section className="how-band pl-ten" aria-labelledby="pl-ten-h" id="metrics">
      <div className="wrap">
        <SectionHead
          id="pl-ten-h"
          title={en ? 'The ten numbers a pilot publishes' : 'पायलट के दस आँकड़े'}
          lead={
            en
              ? 'After every alert: who confirmed and how fast, the assisted households, the time from first signal to first call, whether the siren sounded, and more. No deployed warning system we reviewed publishes these. Real values below.'
              : 'हर चेतावनी के बाद: किसने कितनी जल्दी पुष्टि की, मदद वाले घर, पहले संकेत से पहली कॉल तक का समय, सायरन बजा या नहीं, और भी। जिन चालू चेतावनी प्रणालियों को हमने देखा, उनमें से कोई इन्हें प्रकाशित नहीं करती। नीचे असली आँकड़े।'
          }
        />
        <TenMetrics />
      </div>
    </section>
  );
}

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
      <div className="wrap">
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
        <RealSection />
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ 4. real vs next ------------------------------------------------------------------ */

const LIVE: Txt[] = [
  { en: 'The 15-minute sweep and the risk rules, per village', hi: 'हर 15 मिनट की जाँच और हर गाँव के जोखिम नियम' },
  { en: 'One-tap approval, escalating to the next officer', hi: 'एक टैप मंज़ूरी, जवाब न मिले तो अगले अधिकारी को' },
  { en: 'The spoken Hindi alert (Polly)', hi: 'बोलकर हिंदी चेतावनी (Polly)' },
  { en: 'Telegram with “Got it” and a re-send to anyone who has not', hi: 'Telegram पर “मिल गया”, और जिसने नहीं दबाया उसे दोबारा' },
  { en: 'A CAP 1.2 feed, the format SACHET reads', hi: 'CAP 1.2 फ़ीड, जिस मानक को SACHET पढ़ता है' },
  { en: 'The “Are you safe?” roll-call', hi: '“क्या आप सुरक्षित हैं?” हाज़िरी' },
  { en: 'Safe places, walking routes and road blocks', hi: 'सुरक्षित जगहें, पैदल रास्ते और बंद सड़कें' },
  { en: 'An audit trail of every allow and deny', hi: 'हर हाँ और ना का ऑडिट रिकॉर्ड' },
  { en: 'The back-test on archived floods', hi: 'पुरानी बाढ़ों पर बैक-टेस्ट' },
];

const NEXT: Txt[] = [
  { en: 'Voice calls and SMS to keypad phones (voice is built and off; SMS is not built)', hi: 'कीपैड फ़ोन पर वॉइस कॉल और SMS (वॉइस बनी है पर बंद है; SMS नहीं बना)' },
  { en: 'Sirens and rain nodes on hardware (firmware only today)', hi: 'हार्डवेयर पर सायरन और बारिश मापक (आज सिर्फ़ फ़र्मवेयर)' },
  { en: 'An installed river gauge (simulated today)', hi: 'लगा हुआ नदी गेज (आज सिम्युलेटेड)' },
  { en: 'A voice in the local language (Mandeali, Kangri)', hi: 'स्थानीय बोली में आवाज़ (मंडियाली, कांगड़ी)' },
  { en: 'A pilot with a district authority (DDMA)', hi: 'ज़िला प्राधिकरण (DDMA) के साथ पायलट' },
  { en: 'The model drafting the Hindi alert (pending model access; a fixed template runs until then)', hi: 'मॉडल से हिंदी संदेश (मॉडल की अनुमति बाक़ी; तब तक तय ढाँचा चलता है)' },
];

function RealSection() {
  const { lang } = useT();
  const en = lang === 'en';
  return (
    <section className="pl-real" aria-labelledby="pl-real-h">
      <div>
        <SectionHead
          id="pl-real-h"
          n="04"
          eyebrow={en ? 'Honest scope' : 'सच्चा दायरा'}
          title={en ? 'Real today, and next' : 'आज चालू, और आगे'}
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
                के “क्या बना, क्या बाक़ी” वाले हिस्से में है।
              </>
            )
          }
        />
        <p className="pl-facts">
          {en
            ? 'Measured so far (23 Oct 2026): 0 real alerts; 1 drill (Gohar, 11 Oct 2026) delivered to 3 phones, with 0 confirmations; the river gauges are simulators; sirens and rain nodes exist as firmware only; voice calls are off until a DDMA registers as the DLT principal entity.'
            : 'अब तक मापा गया (23 अक्टूबर 2026): 0 असली चेतावनियाँ; 1 अभ्यास (गोहर, 11 अक्टूबर 2026) 3 फ़ोन तक पहुँचा, 0 पुष्टि; नदी गेज सिम्युलेटर हैं; सायरन और बारिश मापक सिर्फ़ फ़र्मवेयर के रूप में हैं; वॉइस कॉल तब तक बंद हैं जब तक कोई DDMA DLT प्रिंसिपल एंटिटी के रूप में पंजीकृत न हो।'}
        </p>
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
      { en: 'Drill: share reached and share who pressed “Got it”', hi: 'अभ्यास: कितनों तक पहुँचा, कितनों ने “मिल गया” दबाया' },
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
      { en: 'Lead time: level rise to the first “Got it”', hi: 'स्तर बढ़ने से पहले “मिल गया” तक का समय' },
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
      <div className="wrap">
        <SectionHead
          id="pl-plan-h"
          n="05"
          eyebrow={en ? '90 days' : '90 दिन'}
          title={en ? 'A 90-day pilot' : '90 दिन का पायलट'}
          lead={en ? 'Three phases, each with the numbers it must produce.' : 'तीन चरण, हर एक के साथ वे आँकड़े जो उसे देने हैं।'}
        />
        <ol className="pl-phases">
          {PLAN.map((p) => (
            <li key={p.when.en} className="pl-phase">
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
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ 6. all-in, and what it may save ------------------------------------------------------------------ */

const SCALE_COSTS = { pilot: scaleCost(SCALES.pilot), district: scaleCost(SCALES.district), state: scaleCost(SCALES.state) };
const ALL_IN_PER_VILLAGE = fmtRupeesAbout(SCALE_COSTS.district.perVillage);
const DISTRICT_COST = SCALE_COSTS.district.total;
const BREAK_EVEN = breakEven(DISTRICT_COST);
const BCR: Record<CaseKey, number> = {
  low: benefitCostRatio(DISTRICT_CASES.low, DISTRICT_COST),
  central: benefitCostRatio(DISTRICT_CASES.central, DISTRICT_COST),
  high: benefitCostRatio(DISTRICT_CASES.high, DISTRICT_COST),
};
const BUSINESS_MODEL = `${GITHUB}/blob/main/docs/BUSINESS_MODEL.md`;

const SCALE_HEAD: Record<ScaleKey, Txt> = {
  pilot: { en: 'Pilot: 5 villages', hi: 'पायलट: 5 गाँव' },
  district: { en: 'District: 300 villages', hi: 'ज़िला: 300 गाँव' },
  state: { en: 'State: 1,000 villages', hi: 'राज्य: 1,000 गाँव' },
};

const SCALE_LINE: Record<ScaleLineKey, Txt> = {
  messaging: { en: 'Messaging (₹22.69 a number a season)', hi: 'संदेश (हर नंबर ₹22.69 एक मानसून)' },
  telecom: { en: 'Number rental and DLT header', hi: 'नंबर का किराया और DLT हेडर' },
  cloud: { en: 'Cloud (AWS ap-south-1)', hi: 'क्लाउड (AWS ap-south-1)' },
  platform: { en: 'Platform and support (₹12,000 a village)', hi: 'प्लेटफ़ॉर्म और सहायता (हर गाँव ₹12,000)' },
  drills: { en: 'Drills and training (₹3,000 a village)', hi: 'अभ्यास और प्रशिक्षण (हर गाँव ₹3,000)' },
  coordinators: { en: 'Field coordinators', hi: 'फ़ील्ड समन्वयक' },
  technicians: { en: 'Technicians', hi: 'तकनीशियन' },
  alarm: { en: 'Alarm layer, annualised and upkeep', hi: 'अलार्म परत, सालाना हिस्सा और रखरखाव' },
};

const CASE_WORD: Record<CaseKey, Txt> = {
  low: { en: 'Low', hi: 'कम' },
  central: { en: 'Central', hi: 'बीच का' },
  high: { en: 'High', hi: 'ज़्यादा' },
};

function PaysSection() {
  const { lang } = useT();
  const en = lang === 'en';
  const keys: ScaleKey[] = ['pilot', 'district', 'state'];
  const ratio = (x: number) => fmtNumber(x, lang, x < 10 ? 1 : 0);
  const months = fmtNumber(Math.round(BREAK_EVEN.monthsPerLife), lang);
  const withoutLives = avertedWithoutLives(DISTRICT_CASES.central) / DISTRICT_COST;
  return (
    <section className="how-band how-gold pl-pays" aria-labelledby="pl-pays-h" id="pays">
      <div className="wrap">
        <SectionHead
          id="pl-pays-h"
          n="06"
          eyebrow={en ? 'The case' : 'तर्क'}
          title={en ? 'All-in cost, and what it may save' : 'पूरा ख़र्च, और क्या बच सकता है'}
          lead={
            en
              ? 'Messaging is the small part. People, drills, the alarm hardware and the team that keeps it running are most of the bill. Every figure is an estimate with its formula in the business model.'
              : 'संदेश छोटा हिस्सा हैं। लोग, अभ्यास, अलार्म का हार्डवेयर और उसे चलाने वाली टीम बिल का बड़ा हिस्सा हैं। हर आँकड़ा अनुमान है, उसका सूत्र बिज़नेस मॉडल में है।'
          }
        />
        <div className="pl-pays-grid">
          <figure className="pl-quote">
            <span className="how-stat-num" aria-hidden="true">
              {en ? `1 / ${months} mo` : `1 / ${months} माह`}
            </span>
            <blockquote>
              <p>
                {en
                  ? `A 300-village district breaks even if Pukaar helps save one life about every ${months} months.`
                  : `300 गाँवों का ज़िला तब बराबर होता है जब पुकार लगभग हर ${months} महीने में एक जान बचाने में मदद करे।`}
              </p>
            </blockquote>
            <figcaption>
              {en
                ? `${fmtRupeesShort(DISTRICT_COST, lang)} a year ÷ ₹1.5 crore, the lowest Indian value of a statistical life found. `
                : `${fmtRupeesShort(DISTRICT_COST, lang)} सालाना ÷ ₹1.5 करोड़, एक सांख्यिकीय जीवन का सबसे कम भारतीय मूल्य। `}
              <Ext href={SRC.vsl.href}>{srcLabel(SRC.vsl, lang)}</Ext>
            </figcaption>
          </figure>
          <div className="pl-pays-side">
            <p className="pl-pays-line">
              <span className="pl-pays-k">{en ? 'Benefit-cost, one district a year' : 'लाभ-लागत, एक ज़िला, एक साल'}</span>
              {(['low', 'central', 'high'] as const).map((k, i) => (
                <span key={k}>
                  {i > 0 && ' · '}
                  {CASE_WORD[k][lang]} <b>{ratio(BCR[k])}</b> ({fmtRupeesShort(averted(DISTRICT_CASES[k]), lang)})
                </span>
              ))}
              <span className="pl-pays-note">
                {en
                  ? `The low case is below 1. Without lives the central case is about ${ratio(withoutLives)}: the case rests on lives, and the lives averted (0.5, 2 and 5 a year) are assumptions, not findings. No cost-benefit study of flash-flood warning in the Indian Himalaya exists.`
                  : `कम वाला अनुमान 1 से नीचे है। जानों के बिना बीच का अनुमान लगभग ${ratio(withoutLives)} है: पूरा तर्क जानों पर टिका है, और बचाई गई जानें (साल में 0.5, 2 और 5) मान्यताएँ हैं, नतीजे नहीं। भारतीय हिमालय में अचानक बाढ़ की चेतावनी का कोई लागत-लाभ अध्ययन नहीं है।`}
              </span>
            </p>
            <p className="pl-pays-line">
              <span className="pl-pays-k">{en ? 'Who pays' : 'कौन देगा'}</span>
              {en
                ? 'A company’s CSR for the pilot (disaster management, Schedule VII item xii), then the DDMA or the State Disaster Mitigation Fund through GeM, dam operators for the villages below their spillways, and HP-READY at state scale. '
                : 'पायलट के लिए किसी कंपनी का CSR (आपदा प्रबंधन, अनुसूची VII मद xii), फिर GeM के ज़रिए DDMA या राज्य आपदा न्यूनीकरण कोष, बाँध चलाने वाली कंपनियाँ अपने स्पिलवे के नीचे के गाँवों के लिए, और राज्य के पैमाने पर HP-READY। '}
              <Ext href={SRC.sdmf.href}>{srcLabel(SRC.sdmf, lang)}</Ext>
            </p>
            <p className="pl-pays-line">
              <span className="pl-pays-k">{en ? 'For context only' : 'सिर्फ़ संदर्भ के लिए'}</span>
              {en
                ? 'Published ratios come from hours or days of warning: 4–36 for weather services and warning in developing countries, and 24–73 for a river-flood warning in Nepal with 2.75 hours of lead. A flash flood gives minutes, so Pukaar does not borrow them. '
                : 'छपे हुए अनुपात घंटों या दिनों की चेतावनी से आते हैं: विकासशील देशों में मौसम सेवा और चेतावनी के लिए 4–36, और नेपाल में 2.75 घंटे पहले वाली नदी-बाढ़ चेतावनी के लिए 24–73। अचानक बाढ़ में मिनट मिलते हैं, इसलिए पुकार इन्हें उधार नहीं लेता। '}
              <Ext href={SRC.hallegatte.href}>{srcLabel(SRC.hallegatte, lang)}</Ext>
              <Ext href={SRC.karnali.href}>{srcLabel(SRC.karnali, lang)}</Ext>
            </p>
          </div>
        </div>

        <div className="table-wrap pl-table" tabIndex={0} role="region" aria-label={en ? 'All-in cost at three scales' : 'तीन पैमानों पर पूरा ख़र्च'}>
          <table className="data-table stack-sm">
            <caption className="sr-only">{en ? 'All-in cost a year at three scales, estimate' : 'तीन पैमानों पर सालाना पूरा ख़र्च, अनुमान'}</caption>
            <thead>
              <tr>
                <th scope="col">{en ? '₹ a year (estimate)' : '₹ सालाना (अनुमान)'}</th>
                {keys.map((k) => (
                  <th key={k} scope="col">
                    {SCALE_HEAD[k][lang]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {SCALE_COSTS.district.lines.map((l, i) => (
                <tr key={l.key}>
                  <th scope="row">{SCALE_LINE[l.key][lang]}</th>
                  {keys.map((k) => (
                    <td key={k} data-label={SCALE_HEAD[k][lang]} className="num">
                      {fmtRupeesShort(SCALE_COSTS[k].lines[i].amount, lang)}
                    </td>
                  ))}
                </tr>
              ))}
              <tr className="pl-total">
                <th scope="row">{en ? 'Total a year' : 'सालाना कुल'}</th>
                {keys.map((k) => (
                  <td key={k} data-label={SCALE_HEAD[k][lang]} className="num">
                    {fmtRupeesShort(SCALE_COSTS[k].total, lang)}
                  </td>
                ))}
              </tr>
              <tr>
                <th scope="row">{en ? 'Per village a year' : 'हर गाँव, सालाना'}</th>
                {keys.map((k) => (
                  <td key={k} data-label={SCALE_HEAD[k][lang]} className="num">
                    {fmtRupeesShort(Math.round(SCALE_COSTS[k].perVillage / 100) * 100, lang)}
                  </td>
                ))}
              </tr>
              <tr>
                <th scope="row">{en ? 'One-time alarm hardware (inside the total, annualised)' : 'एक बार का अलार्म हार्डवेयर (कुल में, सालाना हिस्से के रूप में)'}</th>
                {keys.map((k) => (
                  <td key={k} data-label={SCALE_HEAD[k][lang]} className="num">
                    {fmtRupeesShort(SCALE_COSTS[k].capex, lang)}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
        <p className="pl-caveat">
          {en
            ? 'Alarm hardware in every pilot village and in one village in five beyond, annualised over 7 years at 8%. People costs have no salary survey behind them. The pilot exists to learn, not to pay for itself. '
            : 'हर पायलट गाँव में और उसके बाद हर पाँच में से एक गाँव में अलार्म हार्डवेयर, 7 साल और 8% पर सालाना हिस्सा। लोगों के ख़र्च के पीछे कोई वेतन सर्वे नहीं है। पायलट सीखने के लिए है, अपना ख़र्च निकालने के लिए नहीं। '}
          <Ext href={BUSINESS_MODEL} className="pl-inline">
            {en ? 'The business model, with every source and formula' : 'बिज़नेस मॉडल, हर स्रोत और सूत्र के साथ'}
          </Ext>
        </p>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ page ------------------------------------------------------------------ */

const TOC: { id: string; t: Txt }[] = [
  { id: 'cost', t: { en: 'Messaging', hi: 'संदेश' } },
  { id: 'pays', t: { en: 'All-in and the case', hi: 'पूरा ख़र्च और तर्क' } },
  { id: 'ready', t: { en: 'Readiness', hi: 'तैयारी' } },
  { id: 'metrics', t: { en: 'Ten metrics', hi: 'दस माप' } },
  { id: 'plan', t: { en: '90 days', hi: '90 दिन' } },
];

export default function Pilot() {
  const { lang } = useT();
  const en = lang === 'en';
  const [draft, setDraft] = useState<Draft>(() => toDraft(DEFAULT_COST_INPUTS));
  return (
    <div className="xp how pilot">
      <header className="xp-hero wrap">
        <div className="xp-hero-text">
          <h1 className="xp-h1">{en ? 'A pilot: what it costs, how ready, 90 days' : 'पायलट: ख़र्च, तैयारी और 90 दिन'}</h1>
          <p className="xp-lead">
            {en
              ? 'For a district: what messages cost a village each monsoon, what the whole system costs and may save, what has to be true before a real village is warned, and a 90-day plan. Estimates are labelled.'
              : 'ज़िले के लिए: एक गाँव पर हर मानसून संदेशों का ख़र्च, पूरी व्यवस्था का ख़र्च और उससे क्या बच सकता है, किसी असली गाँव को चेतावनी देने से पहले क्या तैयार होना चाहिए, और 90 दिन की योजना। अनुमान पर अनुमान लिखा है।'}
          </p>
          <nav className="pl-toc" aria-label={en ? 'On this page' : 'इस पेज पर'}>
            <ol>
              {TOC.map((x, i) => (
                <li key={x.id}>
                  <Link to={{ hash: x.id }}>
                    <span className="pl-toc-n" aria-hidden="true">{i + 1}</span> {x.t[lang]}
                  </Link>
                </li>
              ))}
            </ol>
          </nav>
        </div>
        <aside className="xp-hero-art" aria-labelledby="pl-glance-h">
          <h2 id="pl-glance-h" className="xp-art-k">
            {en ? 'The pilot at a glance' : 'पायलट एक नज़र में'}
          </h2>
          <dl className="xp-art-rows">
            <div>
              <dt>{en ? 'All in, per village, per year' : 'सब मिलाकर, प्रति गाँव, प्रति वर्ष'}</dt>
              <dd>{GLANCE_ALL_IN}</dd>
            </div>
            <div>
              <dt>{en ? 'Messages alone, per village, per monsoon' : 'सिर्फ़ संदेश, प्रति गाँव, प्रति मानसून'}</dt>
              <dd>{GLANCE_MESSAGING}</dd>
            </div>
            <div>
              <dt>{en ? 'The plan, start to finish' : 'योजना, शुरू से आख़िर तक'}</dt>
              <dd>{en ? '90 days' : '90 दिन'}</dd>
            </div>
          </dl>
        </aside>
      </header>
      <CostSection draft={draft} setDraft={setDraft} />
      <PaysSection />
      <ReadinessSection />
      <MetricsSection />
      <PlanSection />
      <p className="wrap xp-next">
        <Link to="/proof" className="go-link">
          {en ? 'What has been measured, and the back-test' : 'अब तक क्या मापा, और बैक-टेस्ट'} →
        </Link>
      </p>
    </div>
  );
}
