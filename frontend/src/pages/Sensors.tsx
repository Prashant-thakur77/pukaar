import { useId, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  ArrowUpRight,
  BatteryCharging,
  BatteryLow,
  BatteryMedium,
  Bell,
  CircleCheck,
  Cloud,
  Cpu,
  FileCode2,
  Filter,
  Info,
  Radio,
  RadioTower,
  Scale,
  Signal,
  Sun,
  TriangleAlert,
  Waves,
  Zap,
  type LucideIcon,
} from 'lucide-react';
import { api } from '../api';
import { CountUp } from '../components/CountUp';
import { Gauge } from '../components/Gauge';
import { LevelBadge } from '../components/Level';
import { PageBand, StatStrip } from '../components/PageBand';
import { Reveal } from '../components/Reveal';
import { Sparkline } from '../components/Sparkline';
import { ErrorState, SkeletonCards } from '../components/States';
import { usePoll } from '../hooks/usePoll';
import { useReducedMotion } from '../hooks/useMotion';
import { useT } from '../i18n';
import { fmtAgo, fmtNumber } from '../lib/format';
import type { SensorVillage, WatchFinding } from '../types';
import { ValleyLine } from '../components/Art';

type Txt = { hi: string; en: string };
const HW = 'https://github.com/Prashant-thakur77/pukaar/tree/main/docs/hardware';
const FIRMWARE = 'https://github.com/Prashant-thakur77/pukaar/tree/main/docs/hardware/esp32-gauge';

type Node = { icon: LucideIcon; title: Txt; sub: string };
const PATH: Node[] = [
  { icon: Waves, title: { en: 'River gauge', hi: 'नदी गेज' }, sub: 'ESP32 + JSN-SR04T' },
  { icon: Cloud, title: { en: 'AWS IoT Core', hi: 'AWS IoT Core' }, sub: 'MQTT · X.509' },
  { icon: Filter, title: { en: 'Topic rule', hi: 'टॉपिक नियम' }, sub: 'pukaar/gauge/+/+/reading' },
  { icon: Zap, title: { en: 'Ingest Lambda', hi: 'इनजेस्ट Lambda' }, sub: '1/min · ≤5 min old' },
  { icon: Scale, title: { en: 'Risk rules', hi: 'जोखिम नियम' }, sub: '3 marks per village' },
  { icon: Bell, title: { en: 'Alert', hi: 'चेतावनी' }, sub: 'officer approves' },
];

/** The device path, drawn twice: across for wide screens, down for phones. A pulse travels it unless motion is reduced. */
function DevicePath() {
  const { lang } = useT();
  const reduced = useReducedMotion();
  const uid = useId().replace(/:/g, '');
  const across = { w: 1200, h: 210, step: 200, x0: 100, y: 78 };
  const down = { w: 360, h: 640, step: 108, x: 46, y0: 52 };
  const acrossPath = `M${across.x0} ${across.y} H${across.x0 + across.step * (PATH.length - 1)}`;
  const downPath = `M${down.x} ${down.y0} V${down.y0 + down.step * (PATH.length - 1)}`;
  const label =
    lang === 'en'
      ? 'Device path: river gauge, AWS IoT Core over MQTT with an X.509 certificate, a topic rule, the ingest Lambda, the risk rules, then an alert.'
      : 'डिवाइस का रास्ता: नदी गेज, MQTT और X.509 प्रमाणपत्र से AWS IoT Core, टॉपिक नियम, इनजेस्ट Lambda, जोखिम नियम, फिर चेतावनी।';
  const pulse = (path: string, delay: string) =>
    reduced ? null : (
      <circle r="7" className="sn-pulse">
        <animateMotion dur="4.8s" begin={delay} repeatCount="indefinite" path={path} keyPoints="0;1" keyTimes="0;1" calcMode="linear" />
      </circle>
    );
  return (
    <div className="sn-path" role="img" aria-label={label}>
      <svg className="sn-path-across" viewBox={`0 0 ${across.w} ${across.h}`} aria-hidden="true">
        <defs>
          <linearGradient id={`${uid}-g`} x1="0" x2="1" y1="0" y2="0">
            <stop offset="0" stopColor="#8ad0ff" />
            <stop offset="0.5" stopColor="#4fb3ff" />
            <stop offset="1" stopColor="#2f7df6" />
          </linearGradient>
        </defs>
        <path d={acrossPath} className="sn-wire" stroke={`url(#${uid}-g)`} />
        <path d={acrossPath} className="sn-wire-flow" />
        {pulse(acrossPath, '0s')}
        {pulse(acrossPath, '2.4s')}
        {PATH.map((n, i) => {
          const cx = across.x0 + i * across.step;
          return (
            <g key={n.sub} className="sn-node" style={{ animationDelay: `${i * 0.8}s` }}>
              <circle cx={cx} cy={across.y} r="38" className="sn-node-ring" />
              <circle cx={cx} cy={across.y} r="31" className="sn-node-disc" />
              <n.icon x={cx - 14} y={across.y - 14} width={28} height={28} className="sn-node-icon" />
              <text x={cx} y={across.y + 68} className="sn-node-title" textAnchor="middle">
                {n.title[lang]}
              </text>
              <text x={cx} y={across.y + 92} className="sn-node-sub" textAnchor="middle">
                {n.sub}
              </text>
            </g>
          );
        })}
      </svg>
      <svg className="sn-path-down" viewBox={`0 0 ${down.w} ${down.h}`} aria-hidden="true">
        <defs>
          <linearGradient id={`${uid}-v`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#8ad0ff" />
            <stop offset="1" stopColor="#2f7df6" />
          </linearGradient>
        </defs>
        <path d={downPath} className="sn-wire" stroke={`url(#${uid}-v)`} />
        <path d={downPath} className="sn-wire-flow" />
        {pulse(downPath, '0s')}
        {pulse(downPath, '2.4s')}
        {PATH.map((n, i) => {
          const cy = down.y0 + i * down.step;
          return (
            <g key={n.sub} className="sn-node" style={{ animationDelay: `${i * 0.8}s` }}>
              <circle cx={down.x} cy={cy} r="32" className="sn-node-ring" />
              <circle cx={down.x} cy={cy} r="26" className="sn-node-disc" />
              <n.icon x={down.x - 12} y={cy - 12} width={24} height={24} className="sn-node-icon" />
              <text x={down.x + 52} y={cy - 2} className="sn-node-title">
                {n.title[lang]}
              </text>
              <text x={down.x + 52} y={cy + 22} className="sn-node-sub">
                {n.sub}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

const TRANSPORT: Record<string, Txt> = {
  mqtt: { en: 'MQTT', hi: 'MQTT' },
  https: { en: 'HTTPS', hi: 'HTTPS' },
  http: { en: 'HTTPS', hi: 'HTTPS' },
  unrecorded: { en: 'Not recorded', hi: 'दर्ज नहीं' },
};

function FindingRow({ f, name }: { f: WatchFinding; name?: string }) {
  const { lang } = useT();
  const Icon = f.kind === 'battery' ? BatteryLow : f.severity === 'warn' ? TriangleAlert : Info;
  return (
    <li className={`sn-finding is-${f.severity}`}>
      <Icon aria-hidden="true" />
      <span>
        {name && <b>{name} · </b>}
        {lang === 'en' ? f.message_en : f.message_hi}
      </span>
    </li>
  );
}

function GaugeTile({ v, i }: { v: SensorVillage; i: number }) {
  const { lang } = useT();
  const en = lang === 'en';
  const bands = { watch: v.gauge.watch_cm, warning: v.gauge.warning_cm, critical: v.gauge.critical_cm };
  const latest = v.latest;
  const transport = latest?.transport ?? null;
  const Batt = latest?.battery_v != null && latest.battery_v < 3.5 ? BatteryLow : BatteryMedium;
  return (
    <Reveal as="li" className={`sn-card${v.fresh ? ' is-fresh' : ' is-stale'}`} delay={(i % 3) * 80}>
      <header className="sn-card-head">
        <div>
          <h3 className="sn-card-name">{en ? v.name : v.name_hi}</h3>
          <p className="sn-card-alt" lang={en ? 'hi' : 'en'}>
            {en ? v.name_hi : v.name}
          </p>
        </div>
        <div className="sn-chips">
          {v.simulated && <span className="sn-chip is-sim">{en ? 'Simulated' : 'सिम्युलेटेड'}</span>}
          {transport && <span className="sn-chip">{(TRANSPORT[transport] ?? { en: transport, hi: transport })[lang]}</span>}
        </div>
      </header>

      <div className="sn-stage">
        {latest ? (
          <p className={`sn-stage-num${v.fresh ? '' : ' is-stale'}`}>
            {fmtNumber(latest.water_level_cm, lang, 0)}
            <span>cm</span>
          </p>
        ) : (
          <p className="sn-stage-num is-empty" aria-label={en ? 'No reading' : 'कोई रीडिंग नहीं'}>
            — —
          </p>
        )}
        {v.fresh && v.gauge_level ? (
          <LevelBadge level={v.gauge_level} size="sm" both={false} lang={lang} />
        ) : (
          <span className="sn-chip is-stale">{latest ? (en ? 'Stale: not counted' : 'पुरानी: गिनी नहीं जाती') : en ? 'No reading yet' : 'अभी कोई रीडिंग नहीं'}</span>
        )}
      </div>
      <Gauge value={v.fresh && latest ? latest.water_level_cm : null} bands={bands} unit="cm" label={en ? `${v.name} river stage` : `${v.name_hi} नदी का स्तर`} />

      <dl className="sn-facts">
        <div>
          <dt>{en ? 'Last reading' : 'आख़िरी रीडिंग'}</dt>
          <dd>
            <i className={`sn-dot${v.fresh ? ' is-fresh' : ''}`} aria-hidden="true" />
            {latest ? fmtAgo(latest.at, lang) : '—'}
          </dd>
        </div>
        <div>
          <dt>{en ? 'Battery' : 'बैटरी'}</dt>
          <dd>
            <Batt aria-hidden="true" /> {latest?.battery_v != null ? `${fmtNumber(latest.battery_v, lang, 2)} V` : '—'}
          </dd>
        </div>
        <div>
          <dt>{en ? 'Signal' : 'सिग्नल'}</dt>
          <dd>
            <Signal aria-hidden="true" /> {latest?.rssi != null ? `${latest.rssi} dBm` : '—'}
          </dd>
        </div>
        <div>
          <dt>{en ? 'Readings, 24 h' : 'रीडिंग, 24 घंटे'}</dt>
          <dd>{fmtNumber(v.readings_24h, lang)}</dd>
        </div>
      </dl>

      {v.series.length > 1 && (
        <div className="trend-card c-gauge sn-spark">
          <Sparkline
            values={v.series.map((p) => p.cm)}
            label={en ? `${v.name}, last 24 hours` : `${v.name_hi}, पिछले 24 घंटे`}
            unit=" cm"
            height={64}
            marks={(['watch', 'warning', 'critical'] as const).map((l) => ({ value: bands[l], className: `lv-${l}`, label: l }))}
          />
        </div>
      )}

      <div className="sn-watch-mini">
        <p className="sn-k">
          <RadioTower aria-hidden="true" /> {en ? 'Watch agent' : 'निगरानी एजेंट'}
        </p>
        {v.findings.length === 0 ? (
          <p className="sn-ok">
            <CircleCheck aria-hidden="true" /> {en ? 'All four checks pass' : 'चारों जाँच ठीक'}
          </p>
        ) : (
          <ul className="sn-findings">
            {v.findings.map((f) => (
              <FindingRow key={f.kind} f={f} />
            ))}
          </ul>
        )}
      </div>
      <p className="sn-device" translate="no">
        {v.gauge.device_id}
        {!v.gauge.installed && <span>{en ? ' · no hardware installed yet' : ' · अभी हार्डवेयर नहीं लगा'}</span>}
      </p>
    </Reveal>
  );
}

const HARDWARE: { icon: LucideIcon; t: Txt }[] = [
  { icon: Cpu, t: { en: 'ESP32-WROOM-32: Wi-Fi, deep sleep at about 10 µA', hi: 'ESP32-WROOM-32: Wi-Fi, गहरी नींद में लगभग 10 µA' } },
  { icon: Waves, t: { en: 'JSN-SR04T waterproof ultrasonic probe, face down under the bridge deck (25–450 cm)', hi: 'JSN-SR04T वाटरप्रूफ़ अल्ट्रासोनिक प्रोब, पुल के नीचे मुँह नीचे (25–450 सेमी)' } },
  { icon: Sun, t: { en: '6 V solar panel, 18650 cell and TP4056 charger: no grid power', hi: '6 V सोलर पैनल, 18650 सेल और TP4056 चार्जर: बिजली लाइन नहीं चाहिए' } },
  { icon: BatteryCharging, t: { en: 'Battery voltage reported with every reading', hi: 'हर रीडिंग के साथ बैटरी वोल्टेज' } },
  { icon: Radio, t: { en: 'MQTT over TLS to AWS IoT Core, or a signed HTTPS POST; 2G fallback stub', hi: 'TLS पर MQTT से AWS IoT Core, या हस्ताक्षरित HTTPS; 2G विकल्प अधूरा' } },
];

function Ext({ href, children, className = '' }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className={className}>
      {children}
      <ArrowUpRight aria-hidden="true" className="how-ext" />
    </a>
  );
}

export default function Sensors() {
  const { lang } = useT();
  const en = lang === 'en';
  const p = (x: Txt) => x[lang];
  const { data, error, loading, refresh } = usePoll(() => api.sensors(), [], 30000);
  const names = new Map((data?.villages ?? []).map((v) => [v.id, en ? v.name : v.name_hi]));
  const warn = (data?.watch.findings ?? []).filter((f) => f.severity === 'warn');
  const transports = Object.entries(data?.by_transport ?? {});

  return (
    <div className="how sensors-page">
      <PageBand
        eyebrow={en ? 'Sensors · from the river to the rules' : 'सेंसर · नदी से नियमों तक'}
        title={en ? 'The river, measured' : 'नदी, नापी हुई'}
        lead={
          en
            ? 'A forecast says what the river may do. A gauge says what it is doing. Each village gauge reads the river every minute, and a fresh reading at or above a mark can raise the level on its own.'
            : 'पूर्वानुमान बताता है कि नदी क्या कर सकती है। गेज बताता है कि नदी अभी क्या कर रही है। हर गाँव का गेज हर मिनट नदी नापता है, और निशान से ऊपर की ताज़ा रीडिंग अपने आप स्तर बढ़ा सकती है।'
        }
        live
      >
        <StatStrip
          stats={[
            {
              key: 'readings',
              value: <CountUp value={data ? data.readings_24h : null} lang={lang} />,
              label: en ? 'Readings in the last 24 h' : 'पिछले 24 घंटे की रीडिंग',
              tone: 'alert',
            },
            {
              key: 'fresh',
              value: data ? `${data.fresh_gauges}/${data.gauges}` : '—',
              label: en ? `Gauges fresh (≤${data?.fresh_minutes ?? 30} min)` : `ताज़ा गेज (≤${data?.fresh_minutes ?? 30} मिनट)`,
            },
            {
              key: 'installed',
              value: data ? `${data.installed_gauges}/${data.gauges}` : '—',
              label: en ? 'Hardware installed' : 'हार्डवेयर लगा',
            },
            {
              key: 'findings',
              value: <CountUp value={data ? warn.length : null} lang={lang} />,
              label: en ? 'Watch-agent findings' : 'निगरानी एजेंट की चेतावनी',
            },
          ]}
        />
      </PageBand>

      <section className="how-band sn-path-band" aria-labelledby="sn-path-h">
        <div className="wrap-wide">
          <p className="how-eyebrow">{en ? 'The device path' : 'डिवाइस का रास्ता'}</p>
          <h2 id="sn-path-h" className="how-h">
            {en ? 'Gauge to ' : 'गेज से '}
            <em className="hl-gold">{en ? 'alert' : 'चेतावनी तक'}</em>
          </h2>
          <DevicePath />
          <div className="sn-path-notes">
            <p>
              {en
                ? 'Each gauge has its own X.509 certificate and may publish only to its own topic. A signed HTTPS POST (an HMAC key per device) reaches the same ingest code through API Gateway.'
                : 'हर गेज का अपना X.509 प्रमाणपत्र है और वह सिर्फ़ अपने टॉपिक पर भेज सकता है। हस्ताक्षरित HTTPS (हर डिवाइस की अपनी HMAC कुंजी) API Gateway से उसी कोड तक पहुँचता है।'}
            </p>
            {transports.length > 0 && (
              <ul className="sn-transports" aria-label={en ? 'Readings by transport, last 24 h' : 'रास्ते के हिसाब से रीडिंग, 24 घंटे'}>
                {transports.map(([k, n]) => (
                  <li key={k}>
                    <b>{fmtNumber(n, lang)}</b> {(TRANSPORT[k] ?? { en: k, hi: k })[lang]}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <p className="sn-sat-credit">
            {en
              ? 'Behind: the Beas near Pandoh and Mandi from Sentinel-2, 3 June 2023. Contains modified Copernicus Sentinel data 2023.'
              : 'पीछे: पंडोह और मंडी के पास ब्यास, Sentinel-2 से, 3 जून 2023। Contains modified Copernicus Sentinel data 2023.'}
          </p>
        </div>
      </section>

      <section className="how-band how-loop" aria-labelledby="sn-gauges-h">
        <div className="wrap-wide">
          <p className="how-eyebrow">{en ? 'Every village gauge, live' : 'हर गाँव का गेज, लाइव'}</p>
          <h2 id="sn-gauges-h" className="how-h">
            {en ? 'The gauges' : 'गेज'}
          </h2>
          <p className="sn-honest">
            <Info aria-hidden="true" />
            {en
              ? 'No gauge hardware is installed yet. Live gauges are a labelled simulator until it is, and thresholds are illustrative.'
              : 'अभी कोई गेज हार्डवेयर नहीं लगा है। तब तक लाइव गेज साफ़ लिखे सिम्युलेटर हैं, और सीमाएँ उदाहरण हैं।'}
          </p>
          {loading && !data ? (
            <SkeletonCards n={3} />
          ) : error && !data ? (
            <ErrorState error={error} onRetry={() => void refresh()} />
          ) : (
            <ul className="sn-cards">
              {(data?.villages ?? []).map((v, i) => (
                <GaugeTile key={v.id} v={v} i={i} />
              ))}
            </ul>
          )}
        </div>
      </section>

      <section className="how-band sn-watch" aria-labelledby="sn-watch-h">
        <div className="wrap-wide sn-watch-grid">
          <div>
            <p className="how-eyebrow">{en ? 'Deterministic, no model' : 'सादा कोड, कोई मॉडल नहीं'}</p>
            <h2 id="sn-watch-h" className="how-h">
              {en ? 'The Watch agent' : 'निगरानी एजेंट'}
            </h2>
            <p className="how-lead">
              {en
                ? 'Gauges fail quietly: a dead battery, a probe iced over, an echo off floating debris. The Watch agent checks every gauge’s own readings and says so. It never changes a level; the rules already ignore a stale gauge.'
                : 'गेज चुपचाप ख़राब होते हैं: बैटरी ख़त्म, प्रोब जमा, तैरते मलबे से गूँज। निगरानी एजेंट हर गेज की अपनी रीडिंग जाँचकर बताता है। वह कभी स्तर नहीं बदलता; पुराना गेज नियम पहले से नहीं गिनते।'}
            </p>
            <ul className="sn-checks">
              {(data?.watch.checks ?? []).map((c) => (
                <li key={c.kind}>
                  <CircleCheck aria-hidden="true" />
                  <span>{en ? c.en : c.hi}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="sn-watch-board">
            <p className="sn-k">
              <RadioTower aria-hidden="true" /> {en ? 'Latest findings' : 'ताज़ा नतीजे'}
            </p>
            {data && data.watch.findings.length === 0 ? (
              <p className="sn-ok">
                <CircleCheck aria-hidden="true" /> {en ? 'Every gauge passes every check.' : 'हर गेज हर जाँच में ठीक।'}
              </p>
            ) : (
              <ul className="sn-findings">
                {(data?.watch.findings ?? []).map((f) => (
                  <FindingRow key={`${f.village_id}-${f.kind}`} f={f} name={names.get(f.village_id)} />
                ))}
              </ul>
            )}
            <Link to="/agents" className="ag-link">
              {en ? 'All five agents' : 'पाँचों एजेंट'} <ArrowRight aria-hidden="true" />
            </Link>
          </div>
        </div>
      </section>

      <section className="how-band how-forest" aria-labelledby="sn-hw-h">
        <div className="wrap-wide how-hw">
          <div>
            <p className="how-eyebrow">{en ? 'Hardware' : 'हार्डवेयर'}</p>
            <h2 id="sn-hw-h" className="how-h">
              {en ? 'A box under the bridge' : 'पुल के नीचे एक डिब्बा'}
            </h2>
            <p className="how-lead">
              {en
                ? 'The probe measures the distance down to the water; stage is the probe’s height above a fixed mark minus that distance. Solar keeps it running through the monsoon.'
                : 'प्रोब पानी तक की दूरी नापता है; नदी का स्तर = तय निशान से प्रोब की ऊँचाई घटा वह दूरी। सोलर से यह पूरे मानसून चलता है।'}
            </p>
            <div className="how-cta-row">
              <Ext href={HW} className="btn how-btn-light">
                {en ? 'Design, wiring and parts' : 'डिज़ाइन, वायरिंग और पुर्ज़े'}
              </Ext>
              <Ext href={FIRMWARE} className="btn how-btn-light">
                <FileCode2 aria-hidden="true" /> {en ? 'Firmware' : 'फ़र्मवेयर'}
              </Ext>
            </div>
            <p className="how-honest">
              {en
                ? 'The sketch is untested on hardware. Live gauges are simulated, and labelled so, until hardware is installed.'
                : 'स्केच अभी हार्डवेयर पर जाँचा नहीं गया। हार्डवेयर लगने तक लाइव गेज सिम्युलेटेड हैं और ऐसा लिखा रहता है।'}
            </p>
          </div>
          <ul className="how-hw-list">
            {HARDWARE.map((g, i) => (
              <Reveal as="li" key={g.t.en} delay={i * 80}>
                <g.icon aria-hidden="true" />
                <span>{p(g.t)}</span>
              </Reveal>
            ))}
          </ul>
        </div>
      </section>

      <section className="how-band how-cta" aria-labelledby="sn-cta-h">
        <div className="wrap-wide">
          <h2 id="sn-cta-h" className="how-h">
            {en ? 'Who reads the ' : 'रीडिंग कौन '}
            <em className="hl-gold">{en ? 'readings' : 'पढ़ता है'}</em>
          </h2>
          <div className="how-cta-row">
            <Link to="/agents" className="btn btn-accent">
              {en ? 'Meet the agents' : 'एजेंट देखें'} <ArrowRight aria-hidden="true" />
            </Link>
            <Link to="/live" className="btn how-btn-light">
              {en ? 'Live map' : 'लाइव नक्शा'}
            </Link>
            <Link to="/how" className="btn how-btn-light">
              {en ? 'The whole loop' : 'पूरा चक्र'}
            </Link>
          </div>
        </div>
        <ValleyLine className="cta-valley" />
      </section>
    </div>
  );
}
