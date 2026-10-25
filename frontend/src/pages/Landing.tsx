import { type ComponentType, type KeyboardEvent, lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { ArrowDown, ArrowRight, ArrowUpRight, Camera, ChevronRight, CircleCheck, Eye, Map as MapIcon, Mic, PenLine, PhoneCall, UserCheck } from 'lucide-react';
import { api } from '../api';
import { Freshness, LevelBanner, VillageRows, type RowVillage } from '../components/Answer';
import { Kicker, Lehar } from '../components/Art';
import { QRCode } from '../components/QRCode';
import { Reveal } from '../components/Reveal';
import { PukaarMark } from '../components/Shell';
import { Valley } from '../components/Valley';
import { TourButton } from '../components/Tour';
import { usePoll } from '../hooks/usePoll';
import { useHandOff } from '../boot/handoff';
import { levelWord, useT } from '../i18n';
import { LEAD, MEANS } from '../lib/actions';
import { levelIsKnown } from '../lib/dataStatus';
import { levelRank } from '../lib/levels';
import { DEFAULT_COST_INPUTS, SCALES, breakEven, estimatePilotCost, fmtRupees, fmtRupeesAbout, scaleCost } from '../lib/pilotCost';
import { PilotNotice } from '../components/PilotNotice';
import { readLS, writeLS } from '../store';
import type { Counters, PublicOverview } from '../types';
import { ValleyMap } from '../components/ValleyMap';
import { prefersReducedMotion, useCountUp, useInView } from '../hooks/useMotion';
import { readSession, writeSession } from '../lib/session';
import { useTour } from '../lib/tour';
// The alert lead from the story data (scripts/story.py), never typed by hand.
import { first as GOHAR_FIRST, lead_hours_watch_to_peak_day as GOHAR_ALERT_LEAD_H } from '../data/story-gohar-2023.json';
import './landing.css';

const CACHE_KEY = 'pukaar.overview';

/** The last overview this phone saw, so the status paints at once on the next visit and with no signal. */
function readCached(): PublicOverview | null {
  const raw = readLS(CACHE_KEY);
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as PublicOverview;
    return Array.isArray(v?.villages) ? v : null;
  } catch {
    return null;
  }
}

// The story's chart (S3), one still frame: its own chunk, fetched only when the band nears the screen.
const StoryChart = lazy(() => import('../components/StoryChart'));

function StoryFrame() {
  const { ref, inView } = useInView<HTMLDivElement>(0);
  return (
    <div ref={ref} className="home-frame">
      {inView && (
        <Suspense fallback={null}>
          <StoryChart cursor={Date.parse(GOHAR_FIRST.watch)} height={180} />
        </Suspense>
      )}
    </div>
  );
}

// Estimates from lib/pilotCost.ts (docs/BUSINESS_MODEL.md): messaging alone for an average Mandi village, and the
// all-in cost per village at district scale, never one passed off as the other.
const MESSAGING_PER_VILLAGE = fmtRupees(estimatePilotCost(DEFAULT_COST_INPUTS).perSeason);
const DISTRICT = scaleCost(SCALES.district);
const ALL_IN_PER_VILLAGE = fmtRupeesAbout(DISTRICT.perVillage);
const BREAK_EVEN_MONTHS = Math.round(breakEven(DISTRICT.total).monthsPerLife);

/**
 * Sourced fact: Down To Earth's headline and text give "at least 10 dead, 34 missing" as the early official figures
 * after the night of 30 June to 1 July 2025 (later reports raised the toll).
 */
const FACT = {
  hi: '30 जून से 1 जुलाई 2025 की रात मंडी ज़िले में कई जगह बादल फटे। शुरुआती सरकारी आँकड़ों के अनुसार कम से कम 10 लोगों की मौत हुई और 34 लापता थे।',
  en: 'On the night of 30 June to 1 July 2025, cloudbursts struck Mandi district. Early official figures: at least 10 people dead and 34 missing.',
  url: 'https://www.downtoearth.org.in/natural-disasters/cloudbursts-devastate-himachals-mandi-at-least-10-dead-34-missing-after-1900-excess-rain-on-july-1',
};

// The 3D valley is optional: if its chunk cannot load (e.g. an old build in the cache), the drawn valley stays.
const HeroScene = lazy<ComponentType<{ onReady: () => void }>>(() =>
  import('../components/HeroScene').catch(() => ({ default: () => null })),
);

/** 3D only where it will run smoothly; everyone else keeps the drawn valley. */
function canRun3d(): boolean {
  if (typeof window === 'undefined' || prefersReducedMotion()) return false;
  const nav = navigator as Navigator & { connection?: { saveData?: boolean }; deviceMemory?: number };
  if (nav.connection?.saveData) return false;
  if (nav.deviceMemory !== undefined && nav.deviceMemory < 4) return false;
  try {
    return !!document.createElement('canvas').getContext('webgl2');
  } catch {
    return false;
  }
}

/** The five villages along the drawn river, in the 600x220 intro stage. */
const INTRO_VILLAGES: [number, number][] = [
  [92, 132],
  [196, 96],
  [300, 128],
  [404, 92],
  [508, 120],
];

/*
 * Entry sequence (a river-blue line draws the Beas, the villages light up along it, the mark lands, then the page):
 *   0-1100 ms   the line draws the river through the valley
 *   1000-1700   the five villages light up, each sending out a call ring
 *   1650-2300   the mark pops, then the name and the line rise in
 *   2600-3000   the stage dissolves into the hero
 * Skippable at any moment (button, click, any key); once per session; never under reduced motion.
 */
function Intro({ onDone }: { onDone: () => void }) {
  const { t, lang } = useT();
  useEffect(() => {
    const tm = setTimeout(onDone, 3000);
    const key = () => onDone();
    window.addEventListener('keydown', key);
    return () => {
      clearTimeout(tm);
      window.removeEventListener('keydown', key);
    };
  }, [onDone]);
  return createPortal(
    <div className="intro" role="presentation" onClick={onDone}>
      <div className="intro-stage">
        <svg className="intro-river" viewBox="0 0 600 220" aria-hidden="true">
          <path className="ir-ridge" d="M0 70 L70 28 L118 58 L176 14 L236 52 L300 22 L358 60 L420 18 L486 56 L540 30 L600 62" />
          <path className="ir-line" pathLength={1} d="M20 150 C 70 150, 80 118, 140 116 S 230 92, 262 112 S 340 140, 380 112 S 460 86, 500 108 S 560 132, 586 118" />
          {INTRO_VILLAGES.map(([x, y], i) => (
            <g key={i} className="ir-village" style={{ animationDelay: `${1000 + i * 130}ms` }}>
              <circle className="ir-ring" cx={x} cy={y} r={7} style={{ animationDelay: `${1080 + i * 130}ms` }} />
              <circle cx={x} cy={y} r={5} />
            </g>
          ))}
        </svg>
        <div className="intro-brand">
          <span className="intro-mark">
            <PukaarMark size={76} />
          </span>
          <span className="intro-word">{lang === 'hi' ? 'पुकार' : 'Pukaar'}</span>
          <span className="intro-tag">{lang === 'hi' ? 'नदी से पहले, गाँव तक पहुँचने वाली पुकार' : 'The call that reaches the village before the river does'}</span>
          <span className="intro-dashes" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
        </div>
      </div>
      <button type="button" className="intro-skip" onClick={onDone}>
        {t('landing.skip')} <ArrowRight aria-hidden="true" />
      </button>
    </div>,
    document.body,
  );
}

/** A section's head: the wave mark, a serif title and one line under it. */
function SecHead({ id, title, sub }: { id: string; title: string; sub?: string }) {
  return (
    <div className="sec-head">
      <Lehar className="sec-orn" />
      <h2 id={id} className="sec-h">
        {title}
      </h2>
      {sub && <p className="sec-sub">{sub}</p>}
    </div>
  );
}

/** One counter, counted up from zero the first time it scrolls into view. */
function Count({ value, label }: { value: number; label: string }) {
  const { ref, inView } = useInView<HTMLLIElement>(0.3);
  const shown = useCountUp(value, inView);
  return (
    <li ref={ref} className="home-metric">
      <span className="home-metric-label">{label}</span>
      <span className="home-metric-num" aria-hidden="true">
        {(inView ? (shown ?? value) : value).toLocaleString('en-IN')}
      </span>
      <span className="sr-only">{value.toLocaleString('en-IN')}</span>
    </li>
  );
}

const COUNTED: (keyof Counters)[] = ['villages_watched', 'forecast_checks_24h', 'reports_received', 'alerts_sent', 'phones_acknowledged'];

/** The services and data Pukaar runs on, by their own names (each one is in use today). */
const BUILT_ON = ['AWS', 'Amazon Polly', 'Telegram', 'Open-Meteo', 'GloFAS', 'OpenStreetMap', 'MapLibre', 'three.js'];

type ShowTab = 'village' | 'officer' | 'alert' | 'report';
const SHOW_TABS: ShowTab[] = ['village', 'officer', 'alert', 'report'];

/**
 * Inside Pukaar: one framed panel with four tabs, one for each person the system serves (after sarvam.ai's product
 * frame). Each tab says what that person does and shows it as a small illustration, with a link to the real page.
 */
function Showcase({ hi }: { hi: boolean }) {
  const [tab, setTab] = useState<ShowTab>('village');
  const label: Record<ShowTab, string> = hi
    ? { village: 'गाँव वाले', officer: 'अधिकारी', alert: 'चेतावनी', report: 'सूचना' }
    : { village: 'Villagers', officer: 'Officer', alert: 'The alert', report: 'Reports' };
  const Icon = { village: MapIcon, officer: UserCheck, alert: PhoneCall, report: Mic }[tab];
  const body: Record<ShowTab, { h: string; p: string; to: string; go: string }> = hi
    ? {
        village: { h: 'हर गाँव वाले को एक जवाब', p: 'पेज खोलें, अपना गाँव चुनें: उसका स्तर और अभी क्या करें, बड़े अक्षरों में। कोई साइन-इन नहीं, धीमे नेटवर्क पर भी।', to: '/village/gohar', go: 'एक गाँव खोलें' },
        officer: { h: 'एक अधिकारी मंज़ूरी देता है', p: 'चेतावनी ड्यूटी वाले अधिकारी के पास रुकती है: सबूत, सटीक शब्द, और मंज़ूरी के लिए एक सेकंड दबाए रखें। जवाब न मिले तो अगले अधिकारी से पूछा जाता है।', to: '/login', go: 'अधिकारी साइन-इन' },
        alert: { h: 'हिंदी में एक आवाज़', p: 'टेलीग्राम पर बोली गई चेतावनी: क्या हुआ और अभी क्या करें, और “मिल गया” बटन, ताकि पता चले किसे मिली।', to: '/how', go: 'पूरा तरीका' },
        report: { h: 'गाँव भी बताता है', p: 'बोलकर, फ़ोटो खींचकर या लिखकर: पानी बढ़ता दिखे तो सूचना अधिकारियों की स्क्रीन पर पहुँचती है।', to: '/report', go: 'सूचना दें' },
      }
    : {
        village: { h: 'Every villager gets one answer', p: 'Open the page, pick your village: its level and what to do now, in large type. No sign-in, and it works on a slow network.', to: '/village/gohar', go: 'Open a village' },
        officer: { h: 'One officer approves', p: 'The alert waits for the officer on duty: the evidence, the exact words, and a one-second hold to approve. No answer, and the next officer is asked.', to: '/login', go: 'Officer sign-in' },
        alert: { h: 'A voice, in Hindi', p: 'A spoken alert on Telegram: what is happening and what to do now, with a “Got it” button so we know who heard it.', to: '/how', go: 'The full method' },
        report: { h: 'The village reports back', p: 'Speak, take a photo or write: when the water rises, the report reaches the officers’ screen.', to: '/report', go: 'Report' },
      };
  const b = body[tab];
  const onKey = (e: KeyboardEvent) => {
    const i = SHOW_TABS.indexOf(tab);
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    const next = SHOW_TABS[(i + step + SHOW_TABS.length) % SHOW_TABS.length];
    setTab(next);
    document.getElementById(`show-t-${next}`)?.focus();
  };
  return (
    <section className="home-sec" aria-labelledby="show-h">
      <div className="wrap">
        <SecHead id="show-h" title={hi ? 'पुकार के अंदर' : 'Inside Pukaar'} sub={hi ? 'चार लोग, एक व्यवस्था।' : 'Four people, one system.'} />
        <Reveal className="show">
          <div className="show-tabs" role="tablist" aria-label={hi ? 'पुकार के अंदर' : 'Inside Pukaar'} onKeyDown={onKey}>
            {SHOW_TABS.map((k) => {
              const TabIcon = { village: MapIcon, officer: UserCheck, alert: PhoneCall, report: Mic }[k];
              return (
                <button key={k} type="button" role="tab" id={`show-t-${k}`} aria-controls="show-panel" aria-selected={tab === k} tabIndex={tab === k ? 0 : -1} className="show-tab" onClick={() => setTab(k)}>
                  <TabIcon aria-hidden="true" /> {label[k]}
                </button>
              );
            })}
          </div>
          <div className="show-panel" id="show-panel" role="tabpanel" aria-labelledby={`show-t-${tab}`}>
            <div className="show-copy">
              <span className="show-icon" aria-hidden="true">
                <Icon />
              </span>
              <h3>{b.h}</h3>
              <p>{b.p}</p>
              <Link to={b.to} className="home-pill">
                {b.go} <ArrowRight aria-hidden="true" />
              </Link>
            </div>
            <div className="show-art" aria-hidden="true">
              <ShowArt tab={tab} hi={hi} />
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/** The tab's small illustration: drawn with the page's own pieces, not a screenshot. */
function ShowArt({ tab, hi }: { tab: ShowTab; hi: boolean }) {
  if (tab === 'village')
    return (
      <div className="sa-card">
        <p className="sa-k">{hi ? 'गोहर · ज़िला मंडी' : 'Gohar · Mandi district'}</p>
        <p className="sa-level lv-warning">{hi ? 'चेतावनी' : 'Warning'}</p>
        <p className="sa-line">{hi ? 'तैयार रहें' : 'Get ready'}</p>
        <ol className="sa-acts">
          <li>{hi ? 'ऊँची जगह और वहाँ तक का रास्ता अभी देख लें।' : 'Look at the high place and the route to it now.'}</li>
          <li>{hi ? 'बुज़ुर्ग, बच्चे और पशु पहले।' : 'The elderly, children and animals first.'}</li>
        </ol>
      </div>
    );
  if (tab === 'officer')
    return (
      <div className="sa-card">
        <p className="sa-level lv-critical">{hi ? 'गंभीर · थुनाग' : 'Critical · Thunag'}</p>
        <p className="sa-line">{hi ? 'नदी ख़तरे की रेखा से ऊपर' : 'River above the critical line'}</p>
        <p className="sa-quote">{hi ? '“थुनाग के लोग ध्यान दें: अभी ऊँची जगह पर जाएँ।”' : '“People of Thunag: move to high ground now.”'}</p>
        <span className="sa-hold">{hi ? 'मंज़ूरी के लिए दबाए रखें' : 'Hold to approve and send'}</span>
      </div>
    );
  if (tab === 'alert')
    return (
      <div className="sa-card sa-chat">
        <p className="sa-k">{hi ? 'टेलीग्राम · पुकार' : 'Telegram · Pukaar'}</p>
        <div className="sa-bubble">
          <span className="sa-play">▶ 0:13</span>
          <p>{hi ? 'पुकार: गोहर के लिए गंभीर ख़तरा। तुरंत ऊँची, सुरक्षित जगह पर जाएँ।' : 'Pukaar: serious danger for Gohar. Move to high, safe ground now.'}</p>
        </div>
        <span className="sa-ack">✓ {hi ? 'मिल गया' : 'Got it'}</span>
      </div>
    );
  return (
    <div className="sa-card sa-report">
      <p className="sa-k">{hi ? 'क्या हो रहा है? बताएँ।' : 'What is happening? Tell us.'}</p>
      <div className="sa-ways">
        <span className="is-on">
          <Mic /> {hi ? 'बोलें' : 'Speak'}
        </span>
        <span>
          <Camera /> {hi ? 'फ़ोटो' : 'Photo'}
        </span>
        <span>
          <PenLine /> {hi ? 'लिखें' : 'Write'}
        </span>
      </div>
    </div>
  );
}

/**
 * The home page: the call that reaches the village before the river (the hero, with a live line on the five
 * villages), then the status and the village list, then what Pukaar is, in a few short bands. One language at a
 * time: every word on the page follows the language switch.
 */
export default function Landing() {
  const { t, lang } = useT();
  const hi = lang === 'hi';
  const [cached] = useState(readCached);
  // The valley and the rows light each other (S2).
  const [hot, setHot] = useState<string | null>(null);
  const { data: fresh, error } = usePoll(() => api.overview(), [], 30000);
  useEffect(() => {
    if (fresh) writeLS(CACHE_KEY, JSON.stringify(fresh));
  }, [fresh]);
  const data = fresh ?? cached;
  // The boot painter drew this page already: hand over once there is something to show.
  useHandOff(Boolean(data) || Boolean(error));
  const offline = !fresh && Boolean(cached) && Boolean(error?.isNetwork);
  const reportUrl = `${typeof window !== 'undefined' ? window.location.origin : ''}/report`;
  const [use3d] = useState(canRun3d);
  const [scene3d, setScene3d] = useState(false);
  const sceneReady = useCallback(() => setScene3d(true), []);
  const [introWanted, setIntro] = useState(() => !readSession('pukaar.intro') && !prefersReducedMotion());
  // A tour opened with ?tour=1 starts on this hero: the intro would cover it.
  const touring = useTour((s) => s.active);
  const intro = introWanted && !touring;
  // The headline rises in only behind the intro; otherwise it is already on screen from the boot painter.
  const [entering] = useState(intro);
  // Stable, so the intro's timer is not restarted when data arrives.
  const finishIntro = useCallback(() => {
    writeSession('pukaar.intro', '1');
    setIntro(false);
  }, []);

  const villages = data?.villages ?? [];
  const name = (v: { name: string; name_hi: string }) => (hi ? v.name_hi : v.name);
  const rows: RowVillage[] = villages.map((v) => ({ id: v.id, name: v.name, name_hi: v.name_hi, level: v.level, unknown: !levelIsKnown(v) }));
  const raised = [...villages].filter((v) => levelRank(v.level) >= levelRank('watch')).sort((a, b) => levelRank(b.level) - levelRank(a.level));
  const unknown = villages.filter((v) => !levelIsKnown(v));
  const checkedAt = villages.reduce<string | null>((m, v) => (v.data_ok_at && (!m || v.data_ok_at > m) ? v.data_ok_at : m), null);
  const n = villages.length;
  const status = t('nav.status');

  // The hero's live line: the answer in one sentence, a tap away from the list.
  const live = !data
    ? { cls: 'lv-nodata', text: hi ? 'गाँवों की जाँच हो रही है…' : 'Checking the villages…' }
    : raised.length > 0
      ? {
          cls: `lv-${raised[0].level}`,
          text: hi
            ? `${name(raised[0])}: ${levelWord(raised[0].level, lang)}${raised.length > 1 ? ` और ${raised.length - 1} गाँव` : ''}`
            : `${name(raised[0])}: ${levelWord(raised[0].level, lang)}${raised.length > 1 ? ` and ${raised.length - 1} more` : ''}`,
        }
      : unknown.length > 0
        ? { cls: 'lv-nodata', text: hi ? `${unknown.length} गाँव का डेटा नहीं मिल रहा` : `No data for ${unknown.length} ${unknown.length === 1 ? 'village' : 'villages'}` }
        : { cls: 'lv-normal', text: hi ? `सभी ${n} गाँव सामान्य` : `All ${n} villages at Normal` };

  return (
    <div className="home">
      {intro && <Intro onDone={finishIntro} />}

      <section className={`home-hero${entering ? ' is-entering' : ''}${intro ? ' is-waiting' : ''}`} aria-labelledby="hero-h">
        <Valley />
        {use3d && (
          <Suspense fallback={null}>
            <HeroScene onReady={sceneReady} />
          </Suspense>
        )}
        <div className="wrap-wide home-hero-in">
          <div className="home-hero-copy" data-tour="hero">
            <Kicker className="home-kicker">{hi ? 'हिमाचल प्रदेश · मंडी और हमीरपुर' : 'Himachal Pradesh · Mandi and Hamirpur'}</Kicker>
            <h1 id="hero-h" className="home-hero-h1">
              <span className="hh-line">{hi ? 'नदी से पहले,' : 'The call that'}</span> <span className="hh-line">{hi ? 'गाँव तक पहुँचने' : 'reaches the village'}</span>{' '}
              <span className="hh-line home-hero-blue">{hi ? 'वाली पुकार।' : 'before the river.'}</span>
            </h1>
            <p className="home-hero-lead">
              {hi
                ? 'पुकार हर 15 मिनट बारिश और नदी का पूर्वानुमान पढ़ता है। ख़तरा दिखे तो एक अधिकारी एक टैप में चेतावनी मंज़ूर करता है, और गाँव के लिए जुड़े हर फ़ोन पर वह हिंदी में बोलकर पहुँचती है।'
                : 'Every 15 minutes Pukaar reads the rain and river forecasts. When danger shows, an officer approves the alert with one tap, and every phone registered for the village hears it spoken in Hindi.'}
            </p>
            <div className="home-hero-ctas">
              <Link to="/report" className="home-report">
                <Mic aria-hidden="true" />
                <span>{hi ? 'पानी बढ़ रहा है? सूचना दें' : 'Water rising? Report it'}</span>
              </Link>
              <Link to="/live" className="home-ghost">
                <span>{hi ? 'लाइव नक्शा' : 'Live map'}</span>
                <ArrowUpRight aria-hidden="true" />
              </Link>
            </div>
            <div className="home-hero-row">
              <a href="#villages" className={`home-live ${live.cls}`}>
                <span className="home-live-dot" aria-hidden="true" />
                <span>{live.text}</span>
                <ArrowDown aria-hidden="true" />
              </a>
              <TourButton className="home-tour" />
            </div>
          </div>

          <div className="home-float" aria-hidden="true">
            <div className="hf-card hf-lead">
              <span className="hf-num">
                {GOHAR_ALERT_LEAD_H}
                <small>{hi ? ' घंटे' : 'h'}</small>
              </span>
              <span className="hf-cap">{hi ? 'नदी के सबसे ऊँचे दिन से पहले · गोहर, जुलाई 2023 का बैक-टेस्ट' : 'ahead of the river’s highest day · Gohar, July 2023 back-test'}</span>
            </div>
            <div className="hf-card hf-ticket">
              <span className="hf-eyebrow">
                <i className="home-live-dot" /> {hi ? 'टेलीग्राम पर, आवाज़ के साथ' : 'On Telegram, with voice'}
              </span>
              <span className="hf-text">
                {hi
                  ? 'पुकार: गोहर के लिए गंभीर ख़तरा। तुरंत नदी-नालों और ढलानों से दूर ऊँची, सुरक्षित जगह पर जाएँ।'
                  : 'Pukaar: serious danger for Gohar. Move away from streams and slopes to high, safe ground now.'}
              </span>
              <span className="hf-row">
                <span className="hf-play">▶ 0:13</span>
                <span className="hf-ack">✓ {hi ? 'मिल गया' : 'Got it'}</span>
              </span>
            </div>
            <div className="hf-card hf-count">
              <span className="hf-num">{n || 5}</span>
              <span className="hf-cap">{hi ? 'गाँव · हर 15 मिनट जाँच' : 'villages · checked every 15 min'}</span>
            </div>
          </div>
        </div>
        {scene3d && <p className="hero-terrain-note">{t('landing.terrain')}</p>}
      </section>

      <section className="home-status wrap" id="villages" aria-labelledby="home-h">
        <div className="home-now">
          <p className="home-region">{status}</p>
          {!data ? (
            <>
              <h2 id="home-h" className="home-h1">
                {status}
              </h2>
              <p className="home-wait">{hi ? 'हर गाँव का हाल आ रहा है…' : 'Getting each village’s level…'}</p>
            </>
          ) : raised.length === 0 ? (
            <>
              <h2 id="home-h" className="home-h1">
                {unknown.length > 0 ? (
                  hi ? (
                    <>{unknown.length} गाँव का डेटा नहीं मिल रहा</>
                  ) : (
                    <>No data for {unknown.length} {unknown.length === 1 ? 'village' : 'villages'}</>
                  )
                ) : hi ? (
                  <>
                    आज सब {n} गाँव{' '}
                    <span className="home-ok">
                      <CircleCheck aria-hidden="true" />
                      सामान्य
                    </span>{' '}
                    हैं।
                  </>
                ) : (
                  <>
                    All {n} villages are at{' '}
                    <span className="home-ok">
                      <CircleCheck aria-hidden="true" />
                      Normal
                    </span>
                    .
                  </>
                )}
              </h2>
              {unknown.length > 0 && <p className="home-lead">{hi ? '‘सामान्य’ पर भरोसा न करें; नदी पर ख़ुद नज़र रखें।' : 'Do not rely on “Normal”; watch the river yourself.'}</p>}
              <Freshness at={checkedAt} offline={offline} next />
            </>
          ) : (
            <>
              <h2 id="home-h" className="sr-only">
                {status}
              </h2>
              <div className="home-banners">
                {raised.map((v) => (
                  <LevelBanner
                    key={v.id}
                    heading="h2"
                    level={v.level}
                    means={MEANS[v.level]}
                    title={
                      <Link to={`/village/${v.id}`} className="home-banner-link">
                        <span>{name(v)}</span>
                        <span className="home-banner-go">
                          {hi ? 'क्या करें' : 'What to do'} <ChevronRight aria-hidden="true" />
                        </span>
                      </Link>
                    }
                    why={<span>{LEAD[v.level][lang]}</span>}
                  />
                ))}
              </div>
              {raised.length < n && (
                <p className="home-lead">
                  {hi ? `बाक़ी ${n - raised.length} गाँव सामान्य हैं।` : `The other ${n - raised.length} villages are at Normal.`}
                </p>
              )}
              <Freshness at={checkedAt} offline={offline} next />
            </>
          )}
        </div>

        <div className="home-pick">
          <h3 className="home-h2">{hi ? 'अपना गाँव चुनें' : 'Choose your village'}</h3>
          {rows.length > 0 ? (
            <VillageRows villages={rows} label={hi ? 'पाँच गाँव' : 'The villages'} hot={hot} onHot={setHot} />
          ) : (
            /* The list's own height, held while it loads, so nothing below it jumps when it arrives. */
            <p className="vrows vrows-wait">{hi ? 'गाँवों की सूची आ रही है…' : 'Loading the villages…'}</p>
          )}
          <div className="home-acts">
            <Link to="/live" className="go-link">
              <MapIcon aria-hidden="true" /> {t('nav.map')} <ChevronRight aria-hidden="true" />
            </Link>
          </div>
          <PilotNotice />
        </div>

        {/* The valley (the seam for the live S2 map): beside the status on a desk, under it on a phone. */}
        <div className="home-lede">
          <ValleyMap villages={villages} hot={hot} onHot={setHot} />
        </div>
      </section>

      <section className="home-built" aria-label={hi ? 'किन चीज़ों पर बना है' : 'What it is built on'}>
        <div className="wrap">
          <p className="home-built-k">{hi ? 'इन पर बना' : 'Built on'}</p>
        </div>
        <div className="home-marquee">
          <ul className="home-marquee-row">
            {[...BUILT_ON, ...BUILT_ON].map((x, i) => (
              <li key={i} aria-hidden={i >= BUILT_ON.length || undefined}>
                {x}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <Showcase hi={hi} />

      {data?.counters && (
        <section className="home-sec" aria-labelledby="ctr-h">
          <Reveal className="wrap">
            <SecHead id="ctr-h" title={hi ? 'अब तक, सीधे सर्वर से' : 'So far, straight from the server'} sub={hi ? 'हर संख्या जमा रिकॉर्ड से गिनी गई है, अनुमान नहीं।' : 'Every number is counted from stored records, not estimated.'} />
            <ul className="home-metrics">
              {COUNTED.map((k) => (
                <Count key={k} value={data.counters[k] as number} label={k === 'alerts_sent' && !data.counters.alerts_sent ? `${t('counter.alerts_sent')} · ${t('counter.alerts_sent.none')}` : t(`counter.${k}`)} />
              ))}
            </ul>
          </Reveal>
        </section>
      )}

      <section className="home-sec" aria-labelledby="how-h">
        <div className="wrap">
          <SecHead id="how-h" title={hi ? 'नज़र। मंज़ूरी। पुकार।' : 'Watch. Approve. Call.'} sub={hi ? 'मशीन नज़र रखती है, इंसान फ़ैसला करता है, और गाँव के हर जुड़े फ़ोन तक आवाज़ जाती है।' : 'Code watches the sky and the river. A person decides. A voice reaches every phone registered in the village.'} />
          <ol className="home-tiles">
            <Reveal as="li" delay={0} className="home-tile">
              <span className="home-art home-art-1" aria-hidden="true">
                <Eye />
              </span>
              <span className="home-tile-n" aria-hidden="true">
                01
              </span>
              <h3>{hi ? 'नज़र' : 'Watch'}</h3>
              <p>{hi ? 'हर 15 मिनट, हर गाँव की बारिश और नदी जाँची जाती है। स्तर तय नियम बताते हैं, कोई अंदाज़ा नहीं।' : 'Every 15 minutes each village’s rain and river are checked. Fixed rules set the level, not a guess.'}</p>
            </Reveal>
            <Reveal as="li" delay={110} className="home-tile">
              <span className="home-art home-art-2" aria-hidden="true">
                <UserCheck />
              </span>
              <span className="home-tile-n" aria-hidden="true">
                02
              </span>
              <h3>{hi ? 'मंज़ूरी' : 'Approve'}</h3>
              <p>{hi ? 'ड्यूटी पर एक अधिकारी चेतावनी पढ़कर एक टैप में मंज़ूर करता है। जवाब न मिले तो अगले अधिकारी से पूछा जाता है।' : 'The officer on duty reads the alert and approves it with one tap. No answer, and the next officer is asked.'}</p>
            </Reveal>
            <Reveal as="li" delay={220} className="home-tile">
              <span className="home-art home-art-3" aria-hidden="true">
                <PhoneCall />
              </span>
              <span className="home-tile-n" aria-hidden="true">
                03
              </span>
              <h3>{hi ? 'पुकार' : 'Call'}</h3>
              <p>
                {hi
                  ? 'टेलीग्राम पर हिंदी में बोली गई चेतावनी और “मिल गया” बटन: क्या हुआ, और अभी क्या करें। कीपैड फ़ोन के लिए वॉइस कॉल बनी है, टेलीकॉम पंजीकरण तक बंद।'
                  : 'A spoken Hindi alert on Telegram with a “Got it” button: what is happening, and what to do now. Voice calls for keypad phones are built, and off until telecom registration.'}
              </p>
            </Reveal>
          </ol>
          <p className="home-center">
            <Link to="/how" className="home-pill">
              {hi ? 'पूरा तरीका देखें' : 'See the full method'} <ArrowRight aria-hidden="true" />
            </Link>
          </p>
        </div>
      </section>

      <section className="home-sec" aria-labelledby="fact-h">
        <Reveal className="wrap home-fact">
          <div className="home-card home-fact-copy">
            <h2 id="fact-h" className="home-card-h">
              {hi ? 'यह क्यों ज़रूरी है' : 'Why this matters'}
            </h2>
            <p className="home-para">{hi ? FACT.hi : FACT.en}</p>
            <p className="home-fact-src">
              {hi ? 'स्रोत:' : 'Source:'}{' '}
              <a href={FACT.url} target="_blank" rel="noreferrer">
                Down To Earth <ArrowUpRight aria-hidden="true" />
              </a>
            </p>
          </div>
          <div className="home-fact-art" aria-hidden="true">
            <span className="home-fact-script">नदी नाला बादल बारिश पानी पुकार गाँव पहाड़ सतर्क चेतावनी गंभीर ऊँची जगह रास्ता मिल गया ब्यास मंडी गोहर थुनाग जंजैहली पंडोह सुजानपुर पुल ढलान बाढ़ आवाज़ फ़ोन सूचना मंज़ूरी नज़र घाटी धारा किनारा सुरक्षित</span>
            <span className="home-fact-date">{hi ? '30 जून 2025' : '30 June 2025'}</span>
            <span className="home-fact-place">{hi ? 'मंडी, हिमाचल प्रदेश' : 'Mandi, Himachal Pradesh'}</span>
          </div>
        </Reveal>
      </section>

      <section className="home-sec" aria-labelledby="proof-h">
        <div className="wrap">
          <SecHead
            id="proof-h"
            title={hi ? `${GOHAR_ALERT_LEAD_H} घंटे पहले चेतावनी मिल सकती थी` : `The warning could have come ${GOHAR_ALERT_LEAD_H} hours earlier`}
            sub={hi ? 'जुलाई 2023 की बाढ़ के असली पूर्वानुमान पर पुकार के नियम।' : 'Pukaar’s rules, run on the real forecasts of the July 2023 flood.'}
          />
          <Reveal className="home-card home-proof">
            <div>
              <p className="home-num" aria-hidden="true">
                {GOHAR_ALERT_LEAD_H}
                <span>{hi ? 'घंटे' : 'h'}</span>
              </p>
              <p className="home-para">
                {hi
                  ? 'गोहर में नदी के सबसे ऊँचे दिन से इतने घंटे पहले ‘सतर्क’ आ जाता। यह बैक-टेस्ट है, असली चेतावनी नहीं, और सिर्फ़ 4 गाँव-घटनाएँ जाँची जा सकीं।'
                  : 'In Gohar, Watch would have come this many hours before the river’s highest day. This is a back-test, not a real alert, and only 4 village-events could be verified.'}
              </p>
              <Link to="/proof" className="home-pill">
                {hi ? 'सबूत देखें' : 'See the proof'} <ArrowRight aria-hidden="true" />
              </Link>
            </div>
            <StoryFrame />
          </Reveal>
        </div>
      </section>

      <section className="home-sec home-thesis" aria-label={hi ? 'पुकार का नियम' : 'How Pukaar decides'}>
        <Reveal className="wrap">
          <Lehar className="sec-orn" />
          <p className="home-thesis-lines">
            <span>{hi ? 'कोड तय करता है।' : 'Code decides.'}</span>
            <span>{hi ? 'इंसान मंज़ूरी देता है।' : 'A person approves.'}</span>
            <span className="home-thesis-blue">{hi ? 'गाँव सुनता है।' : 'The village hears.'}</span>
          </p>
        </Reveal>
      </section>

      <section className="home-sec" aria-labelledby="district-h">
        <div className="wrap">
          <SecHead id="district-h" title={hi ? 'एक ज़िले के लिए ख़र्च' : 'What it costs a district'} sub={hi ? '300 गाँवों के ज़िले का अनुमान: लोग, अभ्यास, सायरन, प्लेटफ़ॉर्म, क्लाउड और संदेश।' : 'A 300-village district, estimated: people, drills, sirens, the platform, cloud and messages.'} />
          <Reveal className="home-card home-cost">
            <dl className="home-rows">
              <div>
                <dt>{hi ? 'प्रति गाँव, प्रति वर्ष, सब मिलाकर' : 'Per village, per year, all in'}</dt>
                <dd>{ALL_IN_PER_VILLAGE}</dd>
              </div>
              <div>
                <dt>{hi ? 'सिर्फ़ संदेश, एक गाँव, एक मानसून' : 'Messaging alone, one village, one monsoon'}</dt>
                <dd>{MESSAGING_PER_VILLAGE}</dd>
              </div>
              <div>
                <dt>{hi ? 'ख़र्च बराबर, अगर इतने महीनों में एक जान बचे' : 'Breaks even if it helps save one life every'}</dt>
                <dd>{hi ? `${BREAK_EVEN_MONTHS} महीने` : `${BREAK_EVEN_MONTHS} months`}</dd>
              </div>
            </dl>
            <Link to="/pilot" className="home-pill">
              {hi ? 'पायलट की योजना' : 'The pilot plan'} <ArrowRight aria-hidden="true" />
            </Link>
          </Reveal>
        </div>
      </section>

      <section className="home-sec" aria-labelledby="cta-h">
        <div className="wrap">
          <Reveal className="home-cta">
            <div className="home-cta-copy">
              <h2 id="cta-h" className="home-cta-h">
                {hi ? 'पानी बढ़ता दिखे? हमें बताएँ।' : 'See the water rising? Tell us.'}
              </h2>
              <p>{hi ? 'बोलकर, लिखकर या फ़ोटो के साथ बताएँ। आपकी सूचना अधिकारियों की स्क्रीन पर पहुँचती है।' : 'Speak, type or add a photo. Your report goes to the officers’ screen.'}</p>
              <Link to="/report" className="home-report home-report-light">
                <Mic aria-hidden="true" />
                <span>{hi ? 'सूचना दें' : 'Report'}</span>
              </Link>
            </div>
            <div className="home-qr">
              <QRCode value={reportUrl} label={hi ? 'सूचना वाले पेज का QR कोड' : 'QR code for the report page'} size={140} />
              <div>
                <p className="home-qr-title">{hi ? 'अपने फ़ोन से सूचना दें' : 'Report from your phone'}</p>
                <p className="home-qr-body">{hi ? 'सूचना वाला पेज खोलने के लिए स्कैन करें।' : 'Scan to open the report page.'}</p>
                <p className="home-qr-url">{reportUrl.replace(/^https?:\/\//, '')}</p>
              </div>
            </div>
          </Reveal>
        </div>
      </section>
    </div>
  );
}
