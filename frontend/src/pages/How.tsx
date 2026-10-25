import { useEffect, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ArrowRight, ArrowUpRight, BatteryMedium, CircleCheck, Info, Signal, TriangleAlert } from 'lucide-react';
import { api, API_BASE } from '../api';
import { Stack, ToolTable, Traces } from '../components/AgentDetails';
import { RiverLine } from '../components/RiverLine';
import { SirenList } from '../components/SirenList';
import { ErrorState, Skeleton } from '../components/States';
import StoryChart from '../components/StoryChart';
import { TourButton } from '../components/Tour';
import { ValleyMap } from '../components/ValleyMap';
import { usePoll } from '../hooks/usePoll';
import { levelWord, useT } from '../i18n';
import { capFeedUrl } from '../lib/cap';
import { fmtAgo, fmtNumber } from '../lib/format';
import { STORY_FIRST } from '../lib/story';
import type { Lang } from '../store';
import type { AgentCard, AgentRegistry, RainObsView, SensorBoard, SensorVillage } from '../types';
import '../styles/explain.css';

/*
 * /how, one explainer in four chapters (spec 4.7): चक्र (the loop) · एजेंट · सेंसर · भरोसा (trust). It absorbs the
 * old /agents and /sensors pages (they redirect to #agents and #sensors). Plain Hindi first; AWS, Cedar and model
 * names live only inside "इंजीनियरों के लिए" (for engineers) disclosures.
 */

type Txt = { hi: string; en: string };
type Source = { label: string; hi?: string; href: string };
const srcLabel = (s: Source, lang: 'hi' | 'en') => (lang === 'hi' && s.hi) || s.label;
const GITHUB = 'https://github.com/Prashant-thakur77/pukaar';
const KARNALI: Source = {
  label: 'Rai et al. 2020, Karnali flood EWS, Nepal', hi: 'Rai और साथी 2020, कर्णाली की बाढ़ चेतावनी, नेपाल',
  href: 'https://www.dpnet.org.np/public/uploads/files/CBA%20of%20EWS%20in%20Karnali%20Feb%202020%202021-09-12%2010-18-25.pdf',
};
const BIHAR: Source = { label: 'Jagnani & Pande 2024', href: 'https://bpb-us-w2.wpmucdn.com/campuspress.yale.edu/dist/7/2986/files/2024/04/Google_Floods-bcdf49042e23059a.pdf' };
const PDNA_2023: Source = {
  label: 'NDMA PDNA 2023, via The Tribune', hi: 'NDMA PDNA 2023, The Tribune के ज़रिए',
  href: 'https://www.tribuneindia.com/news/himachal/himachal-pradesh-floods-climate-change-illegal-construction-greenery-loss-increasing-disaster-risk-in-himalayas-says-ndma-report-586698',
};
const CUMISKEY: Source = { label: 'Cumiskey et al. 2015', hi: 'Cumiskey और साथी 2015', href: 'https://doi.org/10.1108/IJDRBE-08-2014-0062' };
const BAUDOIN: Source = { label: 'Baudoin et al. 2016', hi: 'Baudoin और साथी 2016', href: 'https://doi.org/10.1007/s13753-016-0085-6' };

/** The engineers' line: AWS and library names stay as they are; any plain words around them are translated. */
type Step = { title: Txt; what: Txt; aws: string | Txt; why?: Txt; src?: Source };
const txt = (x: string | Txt, lang: 'hi' | 'en') => (typeof x === 'string' ? x : x[lang]);

const LOOP: Step[] = [
  {
    title: { hi: 'हर 15 मिनट, पूर्वानुमान की जाँच', en: 'Every 15 minutes, the forecasts are read' },
    what: { hi: 'दिन हो या रात, हर गाँव की नदी और बारिश का ताज़ा पूर्वानुमान आता है।', en: 'Day and night, each village’s river and rain forecasts are fetched.' },
    aws: 'EventBridge Scheduler · Lambda',
    why: {
      hi: 'नेपाल की कर्णाली नदी पर एक घंटा ज़्यादा चेतावनी से घरों की बचत 1.83 गुना हुई। अचानक बाढ़ में मिनट मिलते हैं, इसलिए हर जाँच मायने रखती है।',
      en: 'On Nepal’s Karnali river, one more hour of warning raised what households saved 1.83 times. A flash flood gives minutes, so every check counts.',
    },
    src: KARNALI,
  },
  {
    title: { hi: 'स्तर नियम तय करते हैं, AI नहीं', en: 'Rules set the level, not AI' },
    what: {
      hi: 'नदी के 2, 5 और 20 साल वाले बाढ़-स्तर और IMD की बारिश की सीमाएँ तय करती हैं: सामान्य, सतर्क, चेतावनी या गंभीर।',
      en: 'The river’s 2-, 5- and 20-year flood levels and IMD’s rain bands decide: Normal, Watch, Warning or Critical.',
    },
    aws: 'Lambda · DynamoDB',
  },
  {
    title: { hi: 'गेज और गाँव वाले स्तर बढ़ा सकते हैं', en: 'The gauge and the villagers can raise it' },
    what: { hi: 'नदी गेज की रीडिंग, फ़ोटो और हिंदी में बोली गई सूचना गाँव का स्तर एक क़दम ऊपर कर सकती है।', en: 'A gauge reading, a photo or a spoken Hindi report can raise a village one level.' },
    aws: 'IoT Core · API Gateway · S3 · Transcribe',
    why: { hi: 'लोगों पर केंद्रित चेतावनी को ज़मीनी जानकारी चाहिए। 2025 के बैक-टेस्ट में वैश्विक पूर्वानुमान मंडी का बादल फटना नहीं पकड़ पाए।', en: 'People-centred warning needs local eyes. In our 2025 back-test the global forecasts missed the Mandi cloudburst.' },
    src: BAUDOIN,
  },
  {
    title: { hi: 'हिंदी में संदेश, जाँचा हुआ', en: 'A Hindi message, checked' },
    what: { hi: 'संदेश में कोई संख्या या जगह रिकॉर्ड से बाहर हो तो वह रुकता है, और तय हिंदी ढाँचा काम आता है।', en: 'If the message has any number or place not in the record it is stopped, and a fixed Hindi template is used.' },
    aws: { en: 'Bedrock (Nova) via Strands · checker · fallback', hi: 'Bedrock (Nova), Strands के ज़रिए · जाँच · तय ढाँचा' },
  },
  {
    title: { hi: 'एक इंसान की मंज़ूरी', en: 'One person approves' },
    what: { hi: 'ड्यूटी अधिकारी फ़ोन पर आए लिंक पर एक सेकंड दबाकर मंज़ूर करता है; जवाब न आए तो अगले अधिकारी से पूछा जाता है।', en: 'The officer on duty holds one second on a link to approve; no answer, and the next officer is asked.' },
    aws: 'Step Functions waitForTaskToken · Cognito · Cedar',
  },
  {
    title: { hi: 'जुड़े फ़ोन पर बोलकर चेतावनी', en: 'A spoken alert on registered phones' },
    what: {
      hi: 'मंज़ूर संदेश हिंदी में बोला जाता है और Telegram पर हर जुड़े फ़ोन तक आवाज़ और लिखे रूप में जाता है। कीपैड फ़ोन के लिए वॉइस कॉल बनी है, पर टेलीकॉम पंजीकरण तक बंद है।',
      en: 'The approved message is spoken in Hindi and goes to every subscribed phone on Telegram, as voice and text. Voice calls for keypad phones are built, and off until telecom registration.',
    },
    aws: 'Polly (Kajal, hi-IN) · Telegram',
    why: { hi: 'लोगों ने आवाज़ वाले संदेश को “आसानी से समझ आने” के कारण ज़्यादा पसंद किया।', en: 'Communities “strongly preferred voice … because of easier accessibility and understanding of the message.”' },
    src: CUMISKEY,
  },
  {
    title: { hi: '“मिल गया”, वरना दोबारा', en: '“Got it”, or sent again' },
    what: { hi: 'एक टैप बताता है कि चेतावनी पहुँची; पुष्टि न आए तो दोबारा भेजी जाती है।', en: 'One tap says the alert arrived; no confirmation, and it is sent again.' },
    aws: 'API Gateway · DynamoDB · CloudWatch',
    why: { hi: '“चेतावनी तभी असरदार है जब वह मिले, समझी जाए और उस पर क़दम उठे।”', en: '“A warning cannot be considered effective until it is received, understood and responded to.”' },
    src: CUMISKEY,
  },
  {
    title: { hi: '“मैं सुरक्षित हूँ”: बाद की हाज़िरी', en: '“I am safe”: the roll-call after' },
    what: { hi: 'असली चेतावनी के बाद हर जुड़े फ़ोन से पूछा जाता है “क्या आप सुरक्षित हैं?” अधिकारी पहले उन्हें देखता है जिन्हें मदद चाहिए।', en: 'After a real alert every registered phone is asked “Are you safe?”. The officer sees who needs help first.' },
    aws: 'Telegram · Lambda · DynamoDB (TTL) · Cedar',
  },
];

const WHY_NUMBERS: { num: string; cap: Txt; src: Source }[] = [
  { num: '~6×', cap: { hi: 'जहाँ चेतावनी कमज़ोर है, वहाँ आपदा में मौतें लगभग छह गुना', en: 'higher disaster deaths where early warning is weak' }, src: { label: 'WMO 2024', href: 'https://wmo.int/publication-series/global-status-of-multi-hazard-early-warning-systems-2024' } },
  {
    num: '46.5%',
    cap: { hi: 'ज़्यादा संभावना कि चेतावनी पानी से पहले पहुँचे, जब हर पंचायत में प्रशिक्षित स्वयंसेवक हों (बिहार)', en: 'more likely to get a warning before the water, with trained volunteers in each panchayat (Bihar)' },
    src: BIHAR,
  },
  { num: '~500', cap: { hi: 'जानें गईं, हिमाचल के 2023 के मानसून में', en: 'lives lost in Himachal’s 2023 monsoon' }, src: PDNA_2023 },
];

const PATH: { hi: string; en: string; id: string | Txt }[] = [
  { hi: 'नदी गेज', en: 'River gauge', id: 'ESP32 + JSN-SR04T' },
  { hi: 'सुरक्षित कनेक्शन', en: 'Secure link', id: 'AWS IoT Core · MQTT · X.509' },
  { hi: 'छँटाई', en: 'Filter', id: { en: 'Topic rule pukaar/gauge/+/+/reading', hi: 'टॉपिक नियम pukaar/gauge/+/+/reading' } },
  { hi: 'जाँच और दर्ज', en: 'Check and store', id: { en: 'Ingest Lambda · ≤5 min old', hi: 'Ingest Lambda · 5 मिनट से ज़्यादा पुराना नहीं' } },
  { hi: 'नियम', en: 'Rules', id: { en: 'risk_rules · 3 marks per village', hi: 'risk_rules · हर गाँव पर 3 निशान' } },
  { hi: 'चेतावनी', en: 'Alert', id: { en: 'officer approves', hi: 'अधिकारी मंज़ूर करता है' } },
];

function Ext({ href, children, className = '' }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className={className}>
      {children}
      <ArrowUpRight aria-hidden="true" className="xp-ext" />
    </a>
  );
}

/** C20: a <details> with a 48 px summary, for everything engineers want and villagers do not. */
function Disclosure({ summary, children, className = '' }: { summary: ReactNode; children: ReactNode; className?: string }) {
  return (
    <details className={`xp-dis ${className}`}>
      <summary>{summary}</summary>
      <div className="xp-dis-body">{children}</div>
    </details>
  );
}

const forEngineers = (lang: Lang) => (lang === 'hi' ? 'इंजीनियरों के लिए' : 'For engineers');

/* ---------- 1. the loop ---------- */

function Loop() {
  const { lang } = useT();
  const hi = lang === 'hi';
  return (
    <section id="loop" className="xp-chapter" aria-labelledby="loop-h">
      <p className="xp-chap-n">{hi ? 'अध्याय 1' : 'Chapter 1'}</p>
      <h2 id="loop-h" className="xp-h2">
        {hi ? 'चक्र: पूर्वानुमान से “मिल गया” तक' : 'The loop: from a forecast to “Got it”'}
      </h2>
      <ol className="xp-steps" data-tour="how-loop">
        {LOOP.map((s, i) => (
          <li key={txt(s.aws, 'en')}>
            <span className="xp-step-n" aria-hidden="true">
              {i + 1}
            </span>
            <h3 className="xp-h3">{s.title[lang]}</h3>
            <p className="xp-p">{s.what[lang]}</p>
            {i === 0 && (
              <figure className="xp-fig">
                <StoryChart cursor={Date.parse(STORY_FIRST.warning!)} height={170} />
                <figcaption>
                  {hi
                    ? 'जुलाई 2023, गोहर: हर घंटे की जाँच में अगले 24 घंटे की बारिश का अनुमान ‘सतर्क’ और फिर ‘चेतावनी’ की सीमा पार गया (बैक-टेस्ट)।'
                    : 'July 2023, Gohar: hour by hour, the 24-hour rain forecast crossed the Watch line, then the Warning line (back-test).'}{' '}
                  <Link to="/proof">{hi ? 'पूरी कहानी' : 'The whole story'}</Link>
                </figcaption>
              </figure>
            )}
            {s.why && s.src && (
              <blockquote className="xp-quote">
                <p>{s.why[lang]}</p>
                <footer>
                  <Ext href={s.src.href}>{srcLabel(s.src, lang)}</Ext>
                </footer>
              </blockquote>
            )}
            <Disclosure summary={forEngineers(lang)}>
              <p className="xp-chips" translate="no">
                {txt(s.aws, lang)}
              </p>
            </Disclosure>
          </li>
        ))}
      </ol>
      <h3 className="xp-h3 xp-gap">{hi ? 'पहले चेतावनी क्यों' : 'Why warn early'}</h3>
      <ul className="xp-nums">
        {WHY_NUMBERS.map((n) => (
          <li key={n.num}>
            <span className="xp-num">{n.num}</span>
            <span className="xp-p">{n.cap[lang]}</span>
            <Ext href={n.src.href} className="xp-src">
              {srcLabel(n.src, lang)}
            </Ext>
          </li>
        ))}
      </ul>
    </section>
  );
}

/* ---------- 2. the agents ---------- */

function Agents({ reg, error, refresh }: { reg: AgentRegistry | null; error: Parameters<typeof ErrorState>[0]['error'] | null; refresh: () => void }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  const agents = reg?.agents ?? [];
  // What every agent is barred from (one Cedar policy covers them all, and code sets the level): said once.
  const counts = new Map<string, { n: number; text: string; cedar: boolean }>();
  for (const a of agents)
    for (const nv of a.never) {
      const c = counts.get(nv.action) ?? { n: 0, text: hi ? nv.hi : nv.en, cedar: nv.source.startsWith('cedar') };
      c.n += 1;
      counts.set(nv.action, c);
    }
  const shared = [...counts.entries()].filter(([action, c]) => c.cedar || c.n === agents.length || action === 'set_level');
  const sharedSet = new Set(shared.map(([a]) => a));
  const own = (a: AgentCard) => a.never.filter((n) => !sharedSet.has(n.action));
  return (
    <section id="agents" className="xp-chapter" aria-labelledby="agents-h">
      <p className="xp-chap-n">{hi ? 'अध्याय 2' : 'Chapter 2'}</p>
      <h2 id="agents-h" className="xp-h2">
        {hi ? 'एजेंट सलाह देते हैं, फ़ैसला कोड और इंसान करते हैं' : 'Agents advise; code and people decide'}
      </h2>
      <p className="xp-lead">
        {hi
          ? 'पुकार में पाँच छोटे एजेंट हैं: संदेश लिखना, सवालों के जवाब, गाँव की सूचना समझना, उसकी सुरक्षा जाँच, और गेज की निगरानी। हर एक सिर्फ़ पढ़ सकता है।'
          : 'Pukaar has five small agents: one drafts the message, one answers officers, one reads village reports, one screens them, one watches the gauges. Each can only read.'}
      </p>
      <div className="xp-never">
        <p className="xp-never-h">{hi ? 'कोई एजेंट कभी नहीं कर सकता' : 'No agent can ever'}</p>
        {reg ? (
          <div className="xp-never-groups">
            {[true, false].map((cedar) => {
              const items = shared.filter(([, c]) => c.cedar === cedar);
              if (!items.length) return null;
              return (
                <div key={String(cedar)}>
                  <p className="xp-never-k">
                    {cedar ? (hi ? 'नीति रोकती है' : 'Barred by policy') : hi ? 'बनावट में ही नहीं' : 'Not in the design'}
                    <span className="xp-tag">{cedar ? 'Cedar' : hi ? 'कोड' : 'code'}</span>
                  </p>
                  <ul>
                    {items.map(([action, c]) => (
                      <li key={action}>{c.text}</li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        ) : error ? (
          <ErrorState error={error} onRetry={refresh} compact />
        ) : (
          <Skeleton lines={4} />
        )}
      </div>
      {agents.length > 0 && (
        <div className="table-wrap" tabIndex={0} role="region" aria-label={hi ? 'पाँच एजेंट' : 'The five agents'}>
          <table className="data-table stack-sm xp-agents">
            <thead>
              <tr>
                <th scope="col">{hi ? 'एजेंट' : 'Agent'}</th>
                <th scope="col">{hi ? 'क्या करता है' : 'What it does'}</th>
                <th scope="col">{hi ? 'और क्या कभी नहीं' : 'And never'}</th>
                <th scope="col">{hi ? 'न चले तो' : 'If it fails'}</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((a) => (
                <tr key={a.id}>
                  <th scope="row">{hi ? a.name_hi : a.name_en}</th>
                  <td data-label={hi ? 'क्या करता है' : 'What it does'}>{hi ? a.role_hi : a.role_en}</td>
                  <td data-label={hi ? 'और क्या कभी नहीं' : 'And never'}>{own(a).length ? own(a).map((n) => (hi ? n.hi : n.en)).join('; ') : '—'}</td>
                  <td data-label={hi ? 'न चले तो' : 'If it fails'}>{hi ? a.fallback_hi : a.fallback_en}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {reg && (
        <p className="xp-status">
          <span className="xp-status-k">{hi ? 'स्थिति' : 'Status'}</span>
          {hi ? reg.model.status.label_hi : reg.model.status.label_en}
          {' · '}
          {hi ? reg.guardrail.status.label_hi : reg.guardrail.status.label_en}
        </p>
      )}
      <Disclosure summary={hi ? 'एक असली चेतावनी, चरण दर चरण' : 'A real alert, round by round'}>
        <p className="xp-p">
          {hi
            ? 'हाल की चेतावनी उसके रिकॉर्ड से: कोड ने क्या पढ़ा, कौन-से नियम लगे, किसने मंज़ूरी दी, किसने सुना। कोई नाम या फ़ोन नंबर नहीं।'
            : 'A recent alert from its record: what code read, which rules fired, who approved, who heard it. No names or phone numbers.'}
        </p>
        <Traces />
      </Disclosure>
      <Disclosure summary={`${forEngineers(lang)}: ${hi ? 'टूल और AWS' : 'tools and AWS'}`}>
        <ToolTable reg={reg} />
        <Stack reg={reg} />
        <p className="xp-p">
          {hi ? 'अधिकारी कंसोल में ' : 'Officers can ask in the console: '}
          <Link to="/console/ask">{hi ? 'पुकार से पूछें' : 'Ask Pukaar'}</Link>
          {hi ? ' (साइन-इन ज़रूरी)।' : ' (sign-in needed).'}
        </p>
      </Disclosure>
    </section>
  );
}

/* ---------- 3. the sensors ---------- */

function GaugeCard({ v }: { v: SensorVillage }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  const l = v.latest;
  const bands = { watch: v.gauge.watch_cm, warning: v.gauge.warning_cm, critical: v.gauge.critical_cm };
  return (
    <li className="xp-gauge">
      <p className="xp-gauge-name">
        <span>{hi ? v.name_hi || v.name : v.name}</span>
        {v.simulated && <span className="xp-tag">{hi ? 'सिम्युलेटेड' : 'Simulated'}</span>}
      </p>
      <p className="xp-gauge-now">
        <b>{l ? `${fmtNumber(l.water_level_cm, lang, 0)} ${hi ? 'सेमी' : 'cm'}` : hi ? 'कोई रीडिंग नहीं' : 'No reading'}</b>
        {l && <span>{fmtAgo(l.at, lang)}</span>}
        {l && !v.fresh && !v.findings.length && <span className="xp-warn">{hi ? 'पुरानी, गिनी नहीं जाती' : 'old, not counted'}</span>}
      </p>
      {v.series.length > 1 && (
        <RiverLine
          observed={v.series.map((p) => ({ t: Date.parse(p.at), v: p.cm }))}
          lines={(['watch', 'warning', 'critical'] as const).map((k) => ({ level: k, value: bands[k], word: `${levelWord(k, lang)} ${bands[k]}` }))}
          height={120}
          offline={v.fresh ? null : hi ? 'सेंसर बंद' : 'Sensor off'}
          label={hi ? `${v.name_hi} का नदी गेज, पिछले 24 घंटे` : `${v.name} river gauge, last 24 hours`}
        />
      )}
      <p className="xp-gauge-facts">
        <span>
          <BatteryMedium aria-hidden="true" /> {l?.battery_v != null ? `${fmtNumber(l.battery_v, lang, 2)} V` : '—'}
        </span>
        <span>
          <Signal aria-hidden="true" /> {l?.rssi != null ? `${l.rssi} dBm` : '—'}
        </span>
        <span>{hi ? `24 घंटे में ${fmtNumber(v.readings_24h, lang)} रीडिंग` : `${v.readings_24h} readings in 24 h`}</span>
      </p>
      {v.findings.length > 0 && (
        <ul className="xp-findings">
          {v.findings.map((f) => (
            <li key={f.kind} className={`is-${f.severity}`}>
              <TriangleAlert aria-hidden="true" /> {hi ? f.message_hi : f.message_en}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

const WINDOWS = ['15min', '1h', '3h'] as const;

function RainGauges({ rain, names }: { rain: Record<string, RainObsView> | undefined; names: Map<string, string> }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  const entries = Object.entries(rain ?? {});
  const win = (w: (typeof WINDOWS)[number]) => (w === '15min' ? (hi ? '15 मिनट' : '15 min') : w === '1h' ? (hi ? '1 घंटा' : '1 h') : hi ? '3 घंटे' : '3 h');
  return (
    <div className="xp-rain">
      <h3 className="xp-h3">{hi ? 'बारिश गेज' : 'Rain gauges'}</h3>
      <p className="xp-p">
        {hi
          ? 'टिपिंग-बकेट गेज असली बारिश नापता है। 15 मिनट, 1 घंटे या 3 घंटे में सीमा पार हो तो स्तर बढ़ सकता है (अकेले अधिकतम चेतावनी तक), कभी घटता नहीं।'
          : 'A tipping-bucket gauge measures the rain that falls. Past a band in 15 minutes, 1 hour or 3 hours it can raise the level (to Warning at most on its own), never lower it.'}
      </p>
      {entries.length === 0 ? (
        <p className="xp-honest">
          <Info aria-hidden="true" />
          {hi ? 'अभी किसी गाँव से बारिश गेज की ताज़ा रीडिंग नहीं है। रीडिंग आने पर 15 मिनट, 1 घंटे और 3 घंटे की बारिश यहाँ दिखेगी।' : 'No village has a fresh rain-gauge reading yet. When one arrives, each window’s rain shows here.'}
        </p>
      ) : (
        <ul className="xp-rain-list">
          {entries.flatMap(([vid, r]) =>
            r.devices.map((d) => (
              <li key={d.device_id}>
                <p className="xp-gauge-name">
                  {names.get(vid) ?? vid}
                  {d.simulated && <span className="xp-tag">{hi ? 'सिम्युलेटेड' : 'Simulated'}</span>}
                  {!d.fresh && <span className="xp-warn">{hi ? 'पुरानी' : 'old'}</span>}
                  {d.stuck && <span className="xp-warn">{hi ? 'बकेट अटकी लगती है' : 'bucket looks stuck'}</span>}
                </p>
                <dl className="xp-rain-win">
                  {WINDOWS.map((w) => (
                    <div key={w}>
                      <dt>{win(w)}</dt>
                      <dd>
                        {d.windows[w] != null ? `${fmtNumber(d.windows[w], lang, 1)} ${hi ? 'मिमी' : 'mm'}` : '—'}
                        {r.bands[`watch_${w}`] != null && (
                          <span className="xp-en">
                            {' '}
                            / {levelWord('watch', lang)} {fmtNumber(r.bands[`watch_${w}`], lang, 1)}
                          </span>
                        )}
                      </dd>
                    </div>
                  ))}
                </dl>
              </li>
            )),
          )}
        </ul>
      )}
    </div>
  );
}

function Sensors({ data, error, refresh }: { data: SensorBoard | null; error: Parameters<typeof ErrorState>[0]['error'] | null; refresh: () => void }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  const names = new Map((data?.villages ?? []).map((v) => [v.id, hi ? v.name_hi : v.name]));
  const none = data && data.installed_gauges === 0;
  return (
    <section id="sensors" className="xp-chapter" aria-labelledby="sensors-h">
      <p className="xp-chap-n">{hi ? 'अध्याय 3' : 'Chapter 3'}</p>
      <h2 id="sensors-h" className="xp-h2">
        {hi ? 'सेंसर: नदी अभी क्या कर रही है' : 'Sensors: what the river is doing now'}
      </h2>
      <p className="xp-lead">
        {hi
          ? 'पूर्वानुमान बताता है कि नदी क्या कर सकती है; गेज बताता है कि अभी क्या कर रही है। पुल के नीचे लगा गेज हर मिनट पानी नापता है, और सीमा से ऊपर की ताज़ा रीडिंग अपने आप स्तर बढ़ा सकती है।'
          : 'A forecast says what the river may do; a gauge says what it is doing. A gauge under the bridge measures the water every minute, and a fresh reading over a line can raise the level on its own.'}
      </p>
      <ol className="xp-path" aria-label={hi ? 'गेज से चेतावनी तक' : 'From the gauge to the alert'}>
        {PATH.map((p) => (
          <li key={p.en}>{p[lang]}</li>
        ))}
      </ol>
      <Disclosure summary={`${forEngineers(lang)}: ${hi ? 'रास्ता और हार्डवेयर' : 'the path and the hardware'}`}>
        <ol className="xp-path-ids" translate="no">
          {PATH.map((p) => (
            <li key={p.en}>
              {p[lang]}: {txt(p.id, lang)}
            </li>
          ))}
        </ol>
        <p className="xp-p">
          {hi
            ? 'ESP32, वाटरप्रूफ़ अल्ट्रासोनिक प्रोब (JSN-SR04T), 6 V सोलर पैनल और 18650 बैटरी। हर गेज का अपना X.509 प्रमाणपत्र, और वह सिर्फ़ अपने टॉपिक पर भेज सकता है। फ़र्मवेयर हार्डवेयर पर अभी जाँचा नहीं गया।'
            : 'ESP32, a waterproof ultrasonic probe (JSN-SR04T), a 6 V solar panel and an 18650 cell. Each gauge has its own X.509 certificate and may publish only to its own topic. The firmware is untested on hardware.'}{' '}
          <Ext href={`${GITHUB}/tree/main/docs/hardware`}>{hi ? 'डिज़ाइन और फ़र्मवेयर' : 'Design and firmware'}</Ext>
        </p>
      </Disclosure>

      <h3 className="xp-h3 xp-gap">{hi ? 'नदी गेज' : 'River gauges'}</h3>
      {data ? (
        <p className="xp-honest">
          <Info aria-hidden="true" />
          {none
            ? hi
              ? `अभी कोई गेज हार्डवेयर नहीं लगा; पाँचों गेज सिम्युलेटर हैं।`
              : 'No gauge hardware is installed yet; all five gauges are simulators.'
            : hi
              ? `${fmtNumber(data.installed_gauges, lang)} गेज लगे हैं, बाक़ी सिम्युलेटर हैं।`
              : `${data.installed_gauges} gauges are installed; the rest are simulators.`}
        </p>
      ) : null}
      {data ? (
        <>
          {data.villages.some((v) => v.latest) && (
            <ul className="xp-gauges">
              {data.villages
                .filter((v) => v.latest)
                .map((v) => (
                  <GaugeCard key={v.id} v={v} />
                ))}
            </ul>
          )}
          {data.villages.some((v) => !v.latest) && (
            <p className="xp-p">
              {hi
                ? `${data.villages.filter((v) => !v.latest).map((v) => v.name_hi).join(', ')}: इन गेज से अब तक कोई रीडिंग नहीं आई।`
                : `${data.villages.filter((v) => !v.latest).map((v) => v.name).join(', ')}: no reading from these gauges yet.`}
            </p>
          )}
        </>
      ) : error ? (
        <ErrorState error={error} onRetry={refresh} compact />
      ) : (
        <Skeleton lines={5} />
      )}
      {data && (
        <p className="xp-watch">
          {data.watch.findings.length === 0 ? <CircleCheck aria-hidden="true" /> : <TriangleAlert aria-hidden="true" />}
          {hi
            ? `निगरानी एजेंट हर गेज की चार जाँच करता है: पुरानी रीडिंग, अटकी रीडिंग, असंभव उछाल, कम बैटरी। ${data.watch.findings.length ? `अभी ${fmtNumber(data.watch.findings.length, lang)} ${data.watch.findings.length === 1 ? 'बात देखनी है' : 'बातें देखनी हैं'}।` : 'अभी सब ठीक।'}`
            : `The watch agent runs four checks on every gauge: old readings, stuck readings, impossible jumps, low battery. ${data.watch.findings.length ? `${data.watch.findings.length} to look at now.` : 'All clear now.'}`}
        </p>
      )}
      <RainGauges rain={data?.rain_obs} names={names} />
      <SirenList devices={data?.devices} names={names} />
    </section>
  );
}

/* ---------- 4. trust ---------- */

function Trust() {
  const { lang } = useT();
  const hi = lang === 'hi';
  const items: { t: Txt; b: Txt; link?: ReactNode }[] = [
    {
      t: { hi: 'एक इंसान की मंज़ूरी', en: 'One person approves' },
      b: { hi: 'कोई चेतावनी अपने आप नहीं जाती। सिर्फ़ ‘गंभीर’ चेतावनी, जब कोई अधिकारी जवाब न दे, निशान के साथ जाती है।', en: 'No alert goes out on its own. Only a Critical alert with no officer answering goes, flagged for review.' },
    },
    {
      t: { hi: 'हर क़दम दर्ज', en: 'Every step on record' },
      b: { hi: 'कौन क्या कर सकता है, नीति तय करती है; हर हाँ और ना ऑडिट में दर्ज होती है, मिटाई नहीं जा सकती।', en: 'A policy decides who may do what; every allow and deny goes into an audit trail that cannot be erased.' },
      link: <Link to="/console/audit">{hi ? 'ऑडिट देखें (साइन-इन)' : 'See the audit (sign-in)'}</Link>,
    },
    {
      t: { hi: 'सरकारी मानक', en: 'The government standard' },
      b: { hi: 'हर भेजी गई चेतावनी CAP 1.2 संदेश के रूप में भी छपती है, उसी मानक में जिस पर NDMA का सचेत (SACHET) सिस्टम बना है।', en: 'Every alert sent is also published as a CAP 1.2 message, the standard NDMA’s SACHET system is built on.' },
      link: <Ext href={capFeedUrl(API_BASE)}>{hi ? 'CAP 1.2 फ़ीड' : 'CAP 1.2 feed'}</Ext>,
    },
    {
      t: { hi: 'गाँव वालों की निजता', en: 'Villagers’ privacy' },
      b: { hi: 'फ़ोन नंबर छिपाए जाते हैं; सूचना का पाठ किसी AI से पहले जाँचा जाता है। डेटा DPDP अधिनियम के हिसाब से, सिर्फ़ चेतावनी के काम के लिए।', en: 'Phone numbers are masked; report text is screened before any AI reads it. Data is kept under the DPDP Act, for warnings only.' },
    },
    {
      t: { hi: 'सस्ते फ़ोन, कमज़ोर नेट', en: 'Cheap phones, weak signal' },
      b: { hi: 'गाँव का जवाब धीमे 3G पर भी पहले आता है, और नेट न हो तो आख़िरी जानकारी उसके समय के साथ दिखती है।', en: 'A village’s answer comes first even on slow 3G, and with no signal the last information shows with its time.' },
    },
  ];
  return (
    <section id="trust" className="xp-chapter" aria-labelledby="trust-h">
      <p className="xp-chap-n">{hi ? 'अध्याय 4' : 'Chapter 4'}</p>
      <h2 id="trust-h" className="xp-h2">
        {hi ? 'भरोसा' : 'Trust'}
      </h2>
      <ul className="xp-trust">
        {items.map((x) => (
          <li key={x.t.en}>
            <h3 className="xp-h3">{x.t[lang]}</h3>
            <p className="xp-p">{x.b[lang]}</p>
            {x.link && <p className="xp-link">{x.link}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

const CHAPTERS: { id: string; t: Txt }[] = [
  { id: 'loop', t: { hi: 'चक्र', en: 'The loop' } },
  { id: 'agents', t: { hi: 'एजेंट', en: 'Agents' } },
  { id: 'sensors', t: { hi: 'सेंसर', en: 'Sensors' } },
  { id: 'trust', t: { hi: 'भरोसा', en: 'Trust' } },
];

export default function How() {
  const { lang } = useT();
  const hi = lang === 'hi';
  const { hash } = useLocation();
  const reg = usePoll(() => api.agents(), [], 60000);
  const sensors = usePoll(() => api.sensors(), [], 30000);
  const overview = usePoll(() => api.overview(), [], 60000);
  // /agents and /sensors land here with #agents and #sensors.
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView({ block: 'start' });
  }, [hash]);
  return (
    <div className="xp how">
      <header className="xp-hero wrap">
        <div className="xp-hero-text">
          <h1 className="xp-h1">{hi ? 'पुकार कैसे काम करता है' : 'How Pukaar works'}</h1>
          <p className="xp-lead">
            {hi
              ? 'हर 15 मिनट पाँच गाँवों की नदी और बारिश की जाँच, नियमों से तय स्तर, एक अधिकारी की मंज़ूरी, और हर जुड़े फ़ोन पर हिंदी में बोली गई चेतावनी।'
              : 'Every 15 minutes the river and rain of five villages are checked; rules set the level; one officer approves; every registered phone gets the alert spoken in Hindi.'}
          </p>
          <TourButton />
        </div>
        <ValleyMap villages={overview.data?.villages ?? []} className="xp-hero-valley" />
      </header>
      <div className="wrap xp-body">
        <nav className="xp-toc" aria-label={hi ? 'अध्याय' : 'Chapters'}>
          <ol>
            {CHAPTERS.map((c, i) => (
              <li key={c.id}>
                <a href={`#${c.id}`}>
                  <span aria-hidden="true">{i + 1}</span> {c.t[lang]}
                </a>
              </li>
            ))}
          </ol>
        </nav>
        <div className="xp-main">
          <Loop />
          <Agents reg={reg.data} error={reg.error} refresh={() => void reg.refresh()} />
          <Sensors data={sensors.data} error={sensors.error} refresh={() => void sensors.refresh()} />
          <Trust />
          <p className="xp-next">
            <Link to="/proof" className="go-link">
              {hi ? 'सबूत: बैक-टेस्ट और जो अभी नहीं मापा' : 'The proof: the back-test, and what is not measured yet'} <ArrowRight aria-hidden="true" />
            </Link>
            <Ext href={GITHUB} className="go-link">
              {hi ? 'GitHub पर कोड' : 'Code on GitHub'}
            </Ext>
          </p>
        </div>
      </div>
    </div>
  );
}
