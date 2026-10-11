import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { ArrowRight, ArrowUpRight, Mic, Radar, UserCheck, Volume2 } from 'lucide-react';
import { api } from '../api';
import { Call112, PukaarMark } from '../components/Shell';
import { CountUp } from '../components/CountUp';
import { LevelBadge } from '../components/Level';
import { QRCode } from '../components/QRCode';
import { Reveal } from '../components/Reveal';
import { Spine } from '../components/Spine';
import { StoryNight } from '../components/StoryNight';
import { Valley } from '../components/Valley';
import { usePoll } from '../hooks/usePoll';
import { prefersReducedMotion } from '../hooks/useMotion';
import { useT, type Key } from '../i18n';
import { levelRank } from '../lib/levels';
import { readSession, writeSession } from '../lib/session';
import type { Counters } from '../types';

const HeroScene = lazy(() => import('../components/HeroScene'));

/** 3D only where it will run smoothly; everyone else keeps the SVG valley. */
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

const COUNTERS: (keyof Counters)[] = ['villages_watched', 'alerts_sent', 'phones_acknowledged', 'reports_received'];

/**
 * Sourced fact: the article's headline and text give "at least 10 dead, 34
 * missing" as official figures after the night of 30 June - 1 July 2025
 * (checked by web search on 2026-10-09; later reports raised the toll).
 */
const FACT = {
  hi: '30 जून से 1 जुलाई 2025 की रात मंडी ज़िले में कई जगह बादल फटे। शुरुआती सरकारी आँकड़ों के अनुसार कम से कम 10 लोगों की मौत हुई और 34 लापता थे।',
  en: 'On the night of 30 June to 1 July 2025, cloudbursts struck Mandi district. Early official figures: at least 10 people dead and 34 missing.',
  source: 'Down To Earth',
  url: 'https://www.downtoearth.org.in/natural-disasters/cloudbursts-devastate-himachals-mandi-at-least-10-dead-34-missing-after-1900-excess-rain-on-july-1',
};

/** The five villages along the drawn river, as fractions of the 600x220 stage. */
const INTRO_VILLAGES: [number, number][] = [
  [92, 132],
  [196, 96],
  [300, 128],
  [404, 92],
  [508, 120],
];

/*
 * Entry sequence (after EcoLafaek's: a gold line draws the land, life moves along it, the mark lands, then the page):
 *   0-1100 ms   a gold line draws the Beas through the valley (stroke-dashoffset)
 *   1000-1700   the five villages light up along it, each sending out a call ring
 *   1650-2300   the mark pops, then पुकार / PUKAAR and the tagline rise in, loader dashes run
 *   2600-3000   the stage dissolves into the hero
 * Skippable at any moment (button, click, any key); shown once per session; never under reduced motion.
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
          <span className="intro-word" lang="hi">
            पुकार
          </span>
          <span className="intro-en">Pukaar</span>
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

export default function Landing() {
  const { t, lang } = useT();
  const [use3d] = useState(canRun3d);
  const [scene3d, setScene3d] = useState(false);
  const sceneReady = useCallback(() => setScene3d(true), []);
  const [intro, setIntro] = useState(() => !readSession('pukaar.intro') && !prefersReducedMotion());
  const { data, error } = usePoll(() => api.overview(), [], 30000);
  const reportUrl = `${typeof window !== 'undefined' ? window.location.origin : ''}/report`;

  // Stable so the intro's timer is not restarted when data arrives.
  const finishIntro = useCallback(() => {
    writeSession('pukaar.intro', '1');
    setIntro(false);
  }, []);

  const raised = data ? data.villages.filter((v) => levelRank(v.level) >= levelRank('warning')) : [];
  const top = data ? [...data.villages].sort((a, b) => levelRank(b.level) - levelRank(a.level))[0] : null;

  const steps: { n: string; icon: typeof Radar; title: Key; body: Key }[] = [
    { n: '01', icon: Radar, title: 'landing.step1.title', body: 'landing.step1.body' },
    { n: '02', icon: UserCheck, title: 'landing.step2.title', body: 'landing.step2.body' },
    { n: '03', icon: Volume2, title: 'landing.step3.title', body: 'landing.step3.body' },
  ];

  return (
    <div className="landing">
      {intro && <Intro onDone={finishIntro} />}

      <section className={`hero${intro ? ' is-waiting' : ''}`} aria-labelledby="hero-title">
        <Valley />
        {use3d && (
          <Suspense fallback={null}>
            <HeroScene onReady={sceneReady} />
          </Suspense>
        )}
        <div className="hero-inner">
          <div className="hero-copy">
            <p className="eyebrow eyebrow-night hero-eyebrow">{t('landing.eyebrow')}</p>
            <h1 id="hero-title" className="hero-h1">
              <span className="hh-line">{lang === 'hi' ? 'नदी से पहले,' : 'The call that'}</span>
              <span className="hh-line">{lang === 'hi' ? 'गाँव तक पहुँचने' : 'reaches the village'}</span>
              <span className="hh-line hh-gold">{lang === 'hi' ? 'वाली पुकार।' : 'before the river.'}</span>
            </h1>
            <p className="hero-sub" lang={lang === 'hi' ? 'en' : 'hi'}>
              {lang === 'hi' ? 'The call that reaches the village before the river does.' : 'नदी से पहले, गाँव तक पहुँचने वाली पुकार।'}
            </p>
            <p className="hero-lead">
              {lang === 'hi'
                ? 'हर 15 मिनट पूर्वानुमान पढ़ता है, कोड ख़तरे का स्तर तय करता है, अधिकारी एक टैप में मंज़ूर करता है, और हर फ़ोन पर हिंदी में बोली गई चेतावनी पहुँचती है।'
                : 'Every 15 minutes it reads the forecasts, code sets each village’s risk level, an officer approves with one tap, and every phone hears a spoken Hindi alert.'}
            </p>
          <div className="hero-ctas">
            <Link to="/report" className="btn btn-xl btn-accent btn-press">
              <Mic aria-hidden="true" />
              <span className="btn-stack">
                <span lang="hi">सूचना दें</span>
                <span className="btn-sub">Report</span>
              </span>
            </Link>
            <Link to="/live" className="btn btn-xl btn-night btn-press">
              <span className="btn-stack">
                <span lang="hi">लाइव डैशबोर्ड</span>
                <span className="btn-sub">Live dashboard</span>
              </span>
              <ArrowUpRight aria-hidden="true" />
            </Link>
          </div>
          <div className="hero-live">
            {data && top ? (
              <Link to="/live" className="hero-live-chip">
                <span className="live-dot" aria-hidden="true" />
                {raised.length > 0 ? (
                  <>
                    <LevelBadge level={raised[0].level} size="sm" />
                    <span>
                      {lang === 'hi'
                        ? `${raised.length} गाँव चेतावनी या उससे ऊपर`
                        : `${raised.length} village${raised.length === 1 ? '' : 's'} at Warning or above`}
                    </span>
                  </>
                ) : (
                  <>
                    <LevelBadge level={top.level} size="sm" />
                    <span>{lang === 'hi' ? `${data.villages.length} गाँवों पर नज़र` : `Watching ${data.villages.length} villages`}</span>
                  </>
                )}
              </Link>
            ) : null}
            <Call112 />
          </div>
          </div>
          <div className="hero-float" aria-hidden="true">
            <div className="hf-card hf-gold">
              <span className="hf-num">72<small>h</small></span>
              <span className="hf-cap">{lang === 'hi' ? 'नदी के सबसे ऊँचे दिन से पहले · गोहर 2023' : "ahead of the river's peak day · Gohar 2023"}</span>
            </div>
            <div className="hf-card hf-ticket">
              <span className="hf-eyebrow">
                <i className="live-dot" /> {lang === 'hi' ? 'टेलीग्राम पर आवाज़ के साथ' : 'On Telegram, with voice'}
              </span>
              <span className="hf-hi" lang="hi">
                पुकार: गोहर के लिए गंभीर ख़तरा। तुरंत नदी-नालों और ढलानों से दूर ऊँची, सुरक्षित जगह पर जाएँ।
              </span>
              <span className="hf-row">
                <span className="hf-play">▶ 0:13</span>
                <span className="hf-ack">✓ मिल गया</span>
              </span>
            </div>
            <div className="hf-card hf-cream">
              <span className="hf-num">{data ? data.villages.length : 5}</span>
              <span className="hf-cap">{lang === 'hi' ? 'गाँव · हर 15 मिनट जाँच' : 'villages · checked every 15 min'}</span>
            </div>
          </div>
        </div>
        {scene3d && (
          <p className="hero-terrain-note" lang={lang}>
            {t('landing.terrain')}
          </p>
        )}
        <div className="hero-fade" aria-hidden="true" />
      </section>

      <section className="band band-marigold" aria-labelledby="ctr-title">
        <div className="wrap">
          <p id="ctr-title" className="eyebrow eyebrow-ink">
            {t('landing.counters.eyebrow')}
          </p>
          <ul className="counters">
            {COUNTERS.map((k, i) => (
              <Reveal as="li" key={k} delay={i * 80} className="counter">
                <CountUp value={data ? data.counters[k] : null} lang={lang} className="counter-num" />
                <span className="counter-label">{t(`counter.${k}`)}</span>
              </Reveal>
            ))}
          </ul>
          {error && !data && <p className="counter-error">{t('landing.counters.error')}</p>}
          {data && !data.replay.active && data.villages.length > 0 && raised.length === 0 && top?.level === 'normal' && (
            <p className="counter-clear">
              {t('landing.clear', { n: data.villages.length })}{' '}
              <Link to="/live">
                {t('landing.clear.link')} <ArrowRight aria-hidden="true" />
              </Link>
            </p>
          )}
        </div>
      </section>

      <StoryNight />

      <section className="band band-paper how" aria-labelledby="how-title">
        <div className="wrap">
          <div className="how-head">
            <Reveal variant="slide">
              <p className="eyebrow">{t('landing.how.eyebrow')}</p>
              <h2 id="how-title" className="display-2">
                {t('landing.how.title')}
              </h2>
            </Reveal>
            <Reveal delay={120}>
              <p className="lead">{t('landing.how.lead')}</p>
            </Reveal>
          </div>
          <ol className="steps">
            {steps.map((s, i) => (
              <Reveal as="li" key={s.n} delay={i * 110} className="step">
                <span className="step-num" aria-hidden="true">
                  {s.n}
                </span>
                <span className={`step-icon step-icon-${i + 1}`} aria-hidden="true">
                  <s.icon />
                  <i />
                </span>
                <h3 className="step-title">{t(s.title)}</h3>
                <p>{t(s.body)}</p>
              </Reveal>
            ))}
          </ol>
        </div>
      </section>

      <Spine />

      <section className="band band-night fact" aria-labelledby="fact-title">
        <div className="wrap fact-grid">
          <Reveal variant="slide">
            <p className="eyebrow eyebrow-night">{t('landing.fact.eyebrow')}</p>
            <h2 id="fact-title" className="display-2 on-night">
              <span lang="hi">३० जून २०२५</span>
              <span className="fact-en">30 June 2025 · Mandi</span>
            </h2>
          </Reveal>
          <Reveal delay={100} className="fact-body">
            <p className="fact-text" lang="hi">
              {FACT.hi}
            </p>
            <p className="fact-text-en">{FACT.en}</p>
            <p className="fact-src">
              Source:{' '}
              <a href={FACT.url} target="_blank" rel="noreferrer">
                {FACT.source} <ArrowUpRight aria-hidden="true" />
              </a>
            </p>
          </Reveal>
        </div>
      </section>

      <section className="thesis band" aria-label={t('thesis.label')}>
        <div className="wrap">
          <p className="thesis-lines" lang={lang}>
            {lang === 'hi' ? (
              <>
                <span>कोड तय करता है।</span>
                <span>इंसान मंज़ूरी देता है।</span>
                <span className="hl-line">गाँव सुनता है।</span>
              </>
            ) : (
              <>
                <span>Code decides.</span>
                <span>A person approves.</span>
                <span className="hl-line">The village hears.</span>
              </>
            )}
          </p>
        </div>
      </section>

      <section className="band band-paper cta" aria-labelledby="cta-title">
        <div className="wrap cta-grid">
          <Reveal variant="slide">
            <h2 id="cta-title" className="display-2">
              {t('landing.cta.title')}
            </h2>
            <p className="lead">{t('landing.cta.body')}</p>
            <div className="cta-row">
              <Link to="/report" className="btn btn-lg btn-ink btn-press">
                <Mic aria-hidden="true" /> {t('landing.cta.report')}
              </Link>
              <Link to="/impact" className="btn btn-lg btn-ghost btn-press">
                {t('nav.impact')} <ArrowRight aria-hidden="true" />
              </Link>
            </div>
          </Reveal>
          <Reveal delay={120} className="qr-card">
            <QRCode value={reportUrl} label={t('landing.qr.aria')} />
            <div>
              <p className="qr-title">{t('landing.qr.title')}</p>
              <p className="qr-body">{t('landing.qr.body')}</p>
              <p className="qr-url">{reportUrl.replace(/^https?:\/\//, '')}</p>
            </div>
          </Reveal>
        </div>
      </section>
    </div>
  );
}
