import { useCallback, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { ArrowRight, ArrowUpRight, Mic, Radar, UserCheck, Volume2 } from 'lucide-react';
import { api } from '../api';
import { Call112 } from '../components/Shell';
import { CountUp } from '../components/CountUp';
import { LevelBadge } from '../components/Level';
import { QRCode } from '../components/QRCode';
import { Reveal } from '../components/Reveal';
import { Valley } from '../components/Valley';
import { usePoll } from '../hooks/usePoll';
import { prefersReducedMotion } from '../hooks/useMotion';
import { useT, type Key } from '../i18n';
import { levelRank } from '../lib/levels';
import { readSession, writeSession } from '../lib/session';
import type { Counters } from '../types';

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

function Intro({ onDone }: { onDone: () => void }) {
  const { t } = useT();
  useEffect(() => {
    // At most 1.1 s; any key, click or tap skips it at once.
    const tm = setTimeout(onDone, 1100);
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
        <span className="intro-rings" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span className="intro-word" lang="hi">
          पुकार
        </span>
        <span className="intro-rule" aria-hidden="true" />
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
        <div className="hero-inner">
          <p className="eyebrow eyebrow-night hero-eyebrow">{t('landing.eyebrow')}</p>
          <h1 id="hero-title" className="hero-mark">
            <span className="hero-rings" aria-hidden="true">
              <i />
              <i />
              <i />
              <i className="idle" />
            </span>
            <span lang="hi" className="hero-word">
              पुकार
            </span>
            <span className="sr-only">Pukaar</span>
          </h1>
          <p className="hero-latin" aria-hidden="true">
            PUKAAR · THE CALL
          </p>
          <p className="hero-promise" lang="hi">
            नदी से पहले, गाँव तक पहुँचने वाली पुकार।
          </p>
          <p className="hero-promise-en" lang="en">
            The call that reaches the village before the river does.
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
        </div>
      </section>

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
