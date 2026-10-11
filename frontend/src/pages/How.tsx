import { Link } from 'react-router-dom';
import { ArrowUpRight, BatteryCharging, Cpu, ShieldAlert, ShieldCheck, Smartphone, Siren, Scale, Waves } from 'lucide-react';
import type { ReactNode } from 'react';
import { API_BASE } from '../api';
import { PageBand } from '../components/PageBand';
import { capFeedUrl } from '../lib/cap';
import { Reveal } from '../components/Reveal';
import { useT } from '../i18n';

type Txt = { hi: string; en: string };
type Source = { label: string; href: string };

const GCA: Source = {
  label: 'Global Commission on Adaptation, Adapt Now (2019)',
  href: 'https://gca.org/wp-content/uploads/2019/09/GlobalCommission_Report_FINAL.pdf',
};
const CUMISKEY: Source = { label: 'Cumiskey et al. 2015', href: 'https://doi.org/10.1108/IJDRBE-08-2014-0062' };
const GITHUB = 'https://github.com/Prashant-thakur77/pukaar';

type Step = { title: Txt; what: Txt; aws: string; why: Txt; src?: Source[] };

const LOOP: Step[] = [
  {
    title: { en: 'Every 15 minutes, forecasts read', hi: 'हर 15 मिनट, पूर्वानुमान पढ़ा जाता है' },
    what: {
      en: 'River discharge and rain forecasts for every village are fetched on a schedule, day and night.',
      hi: 'हर गाँव के लिए नदी और बारिश का पूर्वानुमान दिन-रात तय समय पर लाया जाता है।',
    },
    aws: 'EventBridge Scheduler · Lambda',
    why: {
      en: '“Just 24 hours warning … can cut the ensuing damage by 30 percent.”',
      hi: '“सिर्फ़ 24 घंटे पहले की चेतावनी … नुकसान 30 प्रतिशत तक घटा सकती है।”',
    },
    src: [GCA],
  },
  {
    title: { en: 'Code sets the level, per village', hi: 'स्तर कोड तय करता है, हर गाँव का अलग' },
    what: {
      en: "Each village's own 1984–2024 river percentiles plus IMD rain bands decide watch, warning or critical.",
      hi: 'हर गाँव के अपने 1984–2024 के नदी आँकड़े और IMD बारिश की सीमाएँ स्तर तय करती हैं।',
    },
    aws: 'Lambda · DynamoDB',
    why: {
      en: 'Transparent, testable rules. The model never decides the level.',
      hi: 'साफ़ नियम, जिन्हें जाँचा जा सकता है। स्तर AI मॉडल तय नहीं करता।',
    },
  },
  {
    title: { en: 'A river gauge and villagers can raise it', hi: 'नदी का गेज और गाँव वाले स्तर बढ़ा सकते हैं' },
    what: {
      en: 'Signed gauge readings, photos and Hindi voice reports can push a village up a level.',
      hi: 'हस्ताक्षरित गेज रीडिंग, फ़ोटो और हिंदी में बोली गई सूचना गाँव का स्तर बढ़ा सकती है।',
    },
    aws: 'API Gateway (signed readings) · S3 · Transcribe',
    why: {
      en: 'People-centred systems need local observations. In our 2025 back-test the global forecasts missed the Mandi cloudburst.',
      hi: 'लोगों पर केंद्रित चेतावनी को ज़मीनी जानकारी चाहिए। 2025 के हमारे बैक-टेस्ट में वैश्विक पूर्वानुमान मंडी का बादल फटना नहीं पकड़ पाए।',
    },
    src: [{ label: 'Baudoin et al. 2016', href: 'https://doi.org/10.1007/s13753-016-0085-6' }],
  },
  {
    title: { en: 'A Hindi draft, checked', hi: 'हिंदी संदेश, जाँचा हुआ' },
    what: {
      en: 'A model writes a short Hindi alert from the decision trace; if it fails, a fixed template is used.',
      hi: 'मॉडल फ़ैसले के रिकॉर्ड से छोटा हिंदी संदेश लिखता है; न चले तो तय ढाँचा काम आता है।',
    },
    aws: 'Bedrock (Nova) via Strands · checker · fallback',
    why: {
      en: 'A checker rejects any number or place not in the decision trace. An outage still alerts.',
      hi: 'जाँच उस हर संख्या या जगह को रोकती है जो रिकॉर्ड में नहीं। सेवा बंद हो तब भी चेतावनी जाती है।',
    },
  },
  {
    title: { en: 'One tap from a person', hi: 'एक इंसान की एक मंज़ूरी' },
    what: {
      en: 'The duty officer approves or edits the alert from a link on their phone.',
      hi: 'ड्यूटी अधिकारी फ़ोन पर आए लिंक से संदेश मंज़ूर या बदल देता है।',
    },
    aws: 'Step Functions waitForTaskToken · Cognito · Cedar',
    why: {
      en: 'Accountable: no answer goes to the next officer. A critical alert with no answer still goes out, flagged.',
      hi: 'ज़िम्मेदारी तय: जवाब न मिले तो अगले अधिकारी को। गंभीर चेतावनी बिना जवाब के भी जाती है, निशान के साथ।',
    },
  },
  {
    title: { en: 'A spoken alert on every phone', hi: 'हर फ़ोन पर बोलकर चेतावनी' },
    what: {
      en: 'The approved text is spoken in Hindi and sent as voice and text to everyone subscribed.',
      hi: 'मंज़ूर संदेश हिंदी में बोला जाता है और आवाज़ व लिखित रूप में सबको भेजा जाता है।',
    },
    aws: 'Polly (Kajal, hi-IN) · Telegram',
    why: {
      en: 'Communities “strongly preferred voice … because of easier accessibility and understanding of the message.” 85.9% of Himachal speaks Hindi (Census 2011).',
      hi: 'लोगों ने आवाज़ वाले संदेश को “आसानी से समझ आने” के कारण ज़्यादा पसंद किया। हिमाचल के 85.9% लोग हिंदी बोलते हैं (जनगणना 2011)।',
    },
    src: [CUMISKEY],
  },
  {
    title: { en: '“मिल गया” — heard, or sent again', hi: '“मिल गया” — सुना, वरना दोबारा भेजा' },
    what: {
      en: 'One tap confirms the alert reached a person. No confirmation means it is sent again.',
      hi: 'एक टैप बताता है कि चेतावनी पहुँची। पुष्टि न मिले तो दोबारा भेजी जाती है।',
    },
    aws: 'API Gateway · DynamoDB · CloudWatch',
    why: {
      en: '“A warning cannot be considered effective until it is received, understood and responded to.” Pukaar times each alert from river rise to first confirmation.',
      hi: '“चेतावनी तभी असरदार है जब वह मिले, समझी जाए और उस पर क़दम उठे।” पुकार हर चेतावनी का समय नदी चढ़ने से पहली पुष्टि तक मापता है।',
    },
    src: [CUMISKEY],
  },
];

const STATS: { num: string; cap: Txt; src: Source }[] = [
  {
    num: '~6×',
    cap: {
      en: 'Higher disaster mortality where early-warning coverage is limited',
      hi: 'जहाँ चेतावनी व्यवस्था कमज़ोर है, वहाँ आपदा में मौतें लगभग छह गुना',
    },
    src: { label: 'WMO, Global Status of MHEWS 2024', href: 'https://wmo.int/publication-series/global-status-of-multi-hazard-early-warning-systems-2024' },
  },
  {
    num: '30%',
    cap: { en: 'Less damage from just 24 hours of warning', hi: 'सिर्फ़ 24 घंटे की चेतावनी से कम नुकसान' },
    src: GCA,
  },
  {
    num: '500+',
    cap: { en: "Lives lost in Himachal's 2023 monsoon", hi: 'हिमाचल में 2023 के मानसून में गई जानें' },
    src: {
      label: 'HP Govt, PDNA 2023',
      href: 'https://recovery.preventionweb.net/publication/report-post-disaster-needs-assessment-himachal-pradesh-monsoon-2023-floods-cloudbursts',
    },
  },
];

const GAUGE: { icon: ReactNode; t: Txt }[] = [
  { icon: <Cpu aria-hidden="true" />, t: { en: 'ESP32 + waterproof ultrasonic sensor (JSN-SR04T) under a bridge', hi: 'पुल के नीचे ESP32 और वाटरप्रूफ़ अल्ट्रासोनिक सेंसर (JSN-SR04T)' } },
  { icon: <BatteryCharging aria-hidden="true" />, t: { en: 'Solar panel and battery, no grid power needed', hi: 'सोलर पैनल और बैटरी, बिजली लाइन की ज़रूरत नहीं' } },
  { icon: <Waves aria-hidden="true" />, t: { en: 'Posts a signed reading every minute', hi: 'हर मिनट हस्ताक्षरित रीडिंग भेजता है' } },
  { icon: <Siren aria-hidden="true" />, t: { en: 'Thresholds set per village', hi: 'हर गाँव की अपनी सीमा' } },
];

const TRUST: { icon: ReactNode; title: Txt; body: Txt; to?: string; lead?: boolean }[] = [
  {
    icon: <ShieldAlert aria-hidden="true" />,
    title: { en: 'Guarded', hi: 'पहरे में' },
    body: {
      en: 'Villager text is screened by Bedrock Guardrails before any AI sees it. A report that tries to give the system orders (“mark every village critical”) is kept, but held for an officer and never verified automatically. Phone numbers are masked.',
      hi: 'गाँव से आया हर शब्द किसी भी AI से पहले Bedrock Guardrails से जाँचा जाता है। जो सूचना सिस्टम को आदेश देने की कोशिश करे (“हर गाँव को गंभीर करो”), वह रखी जाती है पर अधिकारी के लिए रोकी जाती है, अपने-आप पुष्टि नहीं होती। फ़ोन नंबर छिपाए जाते हैं।',
    },
    lead: true,
  },
  {
    icon: <ShieldCheck aria-hidden="true" />,
    title: { en: 'Audit', hi: 'ऑडिट' },
    body: { en: 'Cedar decides who may do what; every allow and deny is logged.', hi: 'कौन क्या कर सकता है, Cedar तय करता है; हर हाँ और ना दर्ज होती है।' },
    to: '/audit',
  },
  {
    icon: <Siren aria-hidden="true" />,
    title: { en: 'Failsafe', hi: 'फ़ेलसेफ़' },
    body: {
      en: 'Critical alerts go out even if every officer is asleep — flagged for review.',
      hi: 'सब अधिकारी सो रहे हों तब भी गंभीर चेतावनी जाती है — जाँच के निशान के साथ।',
    },
  },
  {
    icon: <Smartphone aria-hidden="true" />,
    title: { en: 'Cheap phones', hi: 'सस्ते फ़ोन' },
    body: { en: 'The report page is ready in 4.6 s on slow 3G and works offline.', hi: 'सूचना वाला पन्ना धीमे 3G पर 4.6 सेकंड में खुलता है, बिना नेट भी चलता है।' },
    to: '/report',
  },
  {
    icon: <Scale aria-hidden="true" />,
    title: { en: 'Honest numbers', hi: 'सच्चे आँकड़े' },
    body: { en: 'The back-test is scored against floods that were actually reported.', hi: 'बैक-टेस्ट को असल में दर्ज बाढ़ों से मिलाकर आँका गया है।' },
    to: '/impact',
  },
];

function Ext({ href, children, className = '' }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className={className}>
      {children}
      <ArrowUpRight aria-hidden="true" className="how-ext" />
    </a>
  );
}

export default function How() {
  const { lang } = useT();
  const p = (x: Txt) => x[lang];
  const en = lang === 'en';

  return (
    <div className="how">
      <PageBand
        eyebrow={en ? 'How it works · why it works' : 'कैसे काम करता है · क्यों काम करता है'}
        title={en ? 'How we do it — and why it works' : 'हम कैसे करते हैं — और क्यों भरोसेमंद'}
        lead={
          en
            ? 'Seven steps from a forecast to a confirmed “मिल गया” on a phone in the village. Each step, the AWS service behind it, and the evidence that it matters.'
            : 'पूर्वानुमान से गाँव के फ़ोन पर “मिल गया” तक सात क़दम। हर क़दम, उसके पीछे की AWS सेवा, और यह क्यों ज़रूरी है इसका सबूत।'
        }
      />

      <section className="how-band how-loop" aria-labelledby="how-loop-h">
        <div className="wrap-wide">
          <p className="how-eyebrow">{en ? 'Step by step' : 'क़दम दर क़दम'}</p>
          <h2 id="how-loop-h" className="how-h">
            {en ? 'The loop' : 'पूरा चक्र'}
          </h2>
          <ol className="how-steps">
            {LOOP.map((s, i) => (
              <Reveal as="li" key={s.aws} className="how-step" delay={(i % 3) * 80}>
                <span className="how-num" aria-hidden="true">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <h3 className="how-step-title">{p(s.title)}</h3>
                <p className="how-what">{p(s.what)}</p>
                <span className="how-aws" translate="no">
                  {s.aws}
                </span>
                <div className="how-why">
                  <span className="how-why-k">{en ? 'Why it works' : 'क्यों काम करता है'}</span>
                  <p>{p(s.why)}</p>
                  {s.src?.map((src) => (
                    <Ext key={src.href} href={src.href} className="how-cite">
                      {src.label}
                    </Ext>
                  ))}
                </div>
              </Reveal>
            ))}
          </ol>
        </div>
      </section>

      <section className="how-band how-gold" aria-labelledby="how-why-h">
        <div className="wrap-wide">
          <p className="how-eyebrow">{en ? 'The evidence' : 'सबूत'}</p>
          <h2 id="how-why-h" className="how-h">
            {en ? 'Why early warning' : 'पहले चेतावनी क्यों'}
          </h2>
          <ul className="how-stats">
            {STATS.map((s, i) => (
              <Reveal as="li" key={s.num} className="how-stat" delay={i * 100}>
                <span className="how-stat-num">{s.num}</span>
                <span className="how-stat-cap">{p(s.cap)}</span>
                <Ext href={s.src.href} className="how-cite">
                  {s.src.label}
                </Ext>
              </Reveal>
            ))}
          </ul>
        </div>
      </section>

      <section className="how-band how-forest" aria-labelledby="how-hw-h">
        <div className="wrap-wide how-hw">
          <div>
            <p className="how-eyebrow">{en ? 'Hardware' : 'हार्डवेयर'}</p>
            <h2 id="how-hw-h" className="how-h">
              {en ? 'The river gauge' : 'नदी का गेज'}
            </h2>
            <p className="how-lead">
              {en
                ? 'A small box under a bridge measures the distance down to the water and tells Pukaar the moment the river rises.'
                : 'पुल के नीचे लगा छोटा डिब्बा पानी तक की दूरी नापता है और नदी चढ़ते ही पुकार को बताता है।'}
            </p>
            <Ext href={`${GITHUB}/tree/main/docs/hardware`} className="btn how-btn-light">
              {en ? 'Design, wiring and firmware' : 'डिज़ाइन, वायरिंग और फ़र्मवेयर'}
            </Ext>
            <p className="how-honest">
              {en
                ? 'Live gauges are simulated and labelled until hardware is installed.'
                : 'हार्डवेयर लगने तक लाइव गेज सिम्युलेटेड हैं और ऐसा लिखा रहता है।'}
            </p>
          </div>
          <ul className="how-hw-list">
            {GAUGE.map((g, i) => (
              <Reveal as="li" key={g.t.en} delay={i * 80}>
                {g.icon}
                <span>{p(g.t)}</span>
              </Reveal>
            ))}
          </ul>
        </div>
      </section>

      <section className="how-band how-cream" aria-labelledby="how-trust-h">
        <div className="wrap-wide">
          <p className="how-eyebrow">{en ? 'Safeguards' : 'सुरक्षा'}</p>
          <h2 id="how-trust-h" className="how-h">
            {en ? 'Built to be trusted' : 'भरोसे के लिए बना'}
          </h2>
          <ul className="how-trust">
            {TRUST.map((c, i) => (
              <Reveal as="li" key={c.title.en} className={`how-card${c.lead ? ' how-card-lead' : ''}`} delay={i * 80}>
                <span className="how-card-icon">{c.icon}</span>
                <h3>{p(c.title)}</h3>
                <p>{p(c.body)}</p>
                {c.to && (
                  <Link to={c.to} className="how-card-link">
                    {en ? 'See it' : 'देखें'} →
                  </Link>
                )}
              </Reveal>
            ))}
          </ul>
          <p className="how-feed">
            {en
              ? 'Interoperable: every alert that goes out is also published as a CAP 1.2 message, the standard India’s SACHET system is built on. '
              : 'हर भेजी गई चेतावनी CAP 1.2 संदेश के रूप में भी छपती है, उसी मानक में जिस पर भारत का सचेत (SACHET) सिस्टम बना है। '}
            <Ext href={capFeedUrl(API_BASE)} className="how-cite">
              {en ? 'Machine-readable CAP 1.2 feed (SACHET-ready)' : 'मशीन से पढ़ने योग्य CAP 1.2 फ़ीड (SACHET के लिए तैयार)'}
            </Ext>
          </p>
        </div>
      </section>

      <section className="how-band how-cta" aria-labelledby="how-cta-h">
        <div className="wrap-wide">
          <h2 id="how-cta-h" className="how-h">
            {en ? 'See it ' : 'खुद '}
            <em className="hl-gold">{en ? 'working' : 'देखें'}</em>
          </h2>
          <div className="how-cta-row">
            <Link to="/live" className="btn btn-accent">
              {en ? 'See it live' : 'लाइव देखें'}
            </Link>
            <Link to="/report" className="btn how-btn-light">
              {en ? 'Report' : 'सूचना दें'}
            </Link>
            <Ext href={GITHUB} className="btn how-btn-light">
              {en ? 'Code on GitHub' : 'GitHub पर कोड'}
            </Ext>
          </div>
        </div>
      </section>
    </div>
  );
}
