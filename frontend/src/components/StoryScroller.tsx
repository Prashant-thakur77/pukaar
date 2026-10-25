import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import scores from '../data/scores.json';
import { dict, useT } from '../i18n';
import { useReducedMotion } from '../hooks/useMotion';
import { fmtNumber } from '../lib/format';
import { LEVEL_ICON } from '../lib/levels';
import { useMedia } from '../hooks/useMedia';
import { levelsAt, STORY_BANDS, STORY_FACTS, STORY_PEAK_RAIN, STORY_SOURCES, STORY_STEPS, type StoryStep } from '../lib/story';
import type { Lang } from '../store';
import StoryChart from './StoryChart';
import { ValleyMap } from './ValleyMap';
import './story-scroller.css';

/*
 * S3, "the night the river rose" (C29). A sticky chart of Gohar's rain forecast through 7-11 July 2023, with four
 * dated steps beside it (under it on a phone). As each step reaches the middle of the screen the chart's marker
 * moves to its hour and the five villages on the small valley take the level each had reached by then. One
 * IntersectionObserver, no scroll listener; transform and opacity only. With reduced motion, or no observer, it is
 * four still frames in order. Every number is the back-test's own (lib/story.ts).
 */

const SCENARIO = scores.scenarios.find((s) => s.name === 'himachal_2023_07')!;
const FIVE = SCENARIO.soil_effect.map((v) => ({ village_id: v.village_id, both: v.both }));
const NAMES: Record<string, { name: string; name_hi: string }> = {
  thunag: { name: 'Thunag', name_hi: 'थुनाग' },
  janjehli: { name: 'Janjehli', name_hi: 'जंजैहली' },
  gohar: { name: 'Gohar', name_hi: 'गोहर' },
  pandoh: { name: 'Pandoh', name_hi: 'पंडोह' },
  sujanpur: { name: 'Sujanpur', name_hi: 'सुजानपुर' },
};
/** The one village with a reported flood in the window, and how early the rules' Watch came there. */
const PANDOH_LEAD = SCENARIO.villages.find((v) => v.village_id === 'pandoh')?.both.lead_hours ?? null;
const PANDOH_SRC = 'https://www.newslaundry.com/2023/08/08/our-lives-are-set-back-25-years-in-himachal-a-village-loses-everything-to-floods-2';
const url = (s: string) => s.split(' ')[0];

function stamp(t: number, lang: Lang) {
  return new Intl.DateTimeFormat(lang === 'hi' ? 'hi-IN' : 'en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(t);
}

function StepText({ s, lang }: { s: StoryStep; lang: Lang }) {
  const hi = lang === 'hi';
  const n = (v: number, d = 0) => fmtNumber(v, lang, d);
  const f = STORY_FACTS;
  const lv = (l: 'watch' | 'warning') => dict[`level.${l}`][lang];
  const body: Record<StoryStep['id'], { title: string; text: string; src: { label: string; href: string }[] }> = {
    ready: {
      title: hi ? '‘तैयार रहें’' : 'Get ready',
      text: hi
        ? `नदी के पूर्वानुमान में ${n(f.readyDaysAhead)} दिन आगे ‘तैयार रहें’ रेखा (${n(f.readyLine, 2)} m³/s) पार होती दिखी। गोहर की धारा के सबसे ऊँचे दिन से ${n(f.readyLead)} घंटे पहले। यह चेतावनी नहीं, तैयारी का इशारा है।`
        : `The river forecast showed the get-ready line (${n(f.readyLine, 2)} m³/s) crossed ${f.readyDaysAhead} days ahead: ${f.readyLead} hours before Gohar’s stream peaked. A nudge to prepare, not an alert.`,
      src: [{ label: hi ? 'GloFAS नदी पूर्वानुमान (Open-Meteo)' : 'GloFAS river forecast (Open-Meteo)', href: url(STORY_SOURCES.river) }],
    },
    watch: {
      title: lv('watch'),
      text: hi
        ? `अगले 24 घंटे की बारिश का अनुमान ${n(STORY_BANDS.watch, 1)} मिमी पार कर गया, IMD की ‘भारी बारिश’ सीमा। नदी के सबसे ऊँचे दिन से ${n(f.watchLead)} घंटे पहले।`
        : `The 24-hour rain forecast crossed ${n(STORY_BANDS.watch, 1)} mm, IMD’s “heavy rain” band: ${f.watchLead} hours before the river’s highest day.`,
      src: [{ label: hi ? 'पुराने मौसम पूर्वानुमान (Open-Meteo)' : 'Archived weather forecasts (Open-Meteo)', href: url(STORY_SOURCES.rain) }],
    },
    warning: {
      title: lv('warning'),
      text: hi
        ? `अनुमान ${n(STORY_BANDS.warning, 1)} मिमी (‘बहुत भारी’) के पार गया, सबसे ऊँचा ${n(STORY_PEAK_RAIN, 1)} मिमी। उसी दिन पास के पंडोह में ब्यास की बाढ़ पुल और घर बहा ले गई।${PANDOH_LEAD != null ? ` वहाँ पुकार का ‘सतर्क’ ${n(PANDOH_LEAD)} घंटे पहले आ जाता।` : ''}`
        : `The forecast went past ${n(STORY_BANDS.warning, 1)} mm (“very heavy”), up to ${n(STORY_PEAK_RAIN, 1)} mm. That day the Beas flood crossed nearby Pandoh, taking a bridge and homes.${PANDOH_LEAD != null ? ` There, Pukaar’s Watch would have come ${PANDOH_LEAD} hours earlier.` : ''}`,
      src: [
        { label: hi ? 'पुराने मौसम पूर्वानुमान (Open-Meteo)' : 'Archived weather forecasts (Open-Meteo)', href: url(STORY_SOURCES.rain) },
        { label: hi ? 'Newslaundry, 8 अगस्त 2023' : 'Newslaundry, 8 Aug 2023', href: PANDOH_SRC },
      ],
    },
    peak: {
      title: hi ? 'नदी सबसे ऊँची' : 'The river at its highest',
      text: hi
        ? `गोहर की धारा का बहाव ${n(f.peakFlow, 2)} m³/s तक गया, ‘सतर्क’ रेखा (${n(f.watchLine, 2)}) से नीचे। ख़तरा बारिश से आया, नदी से नहीं; इसीलिए पुकार दोनों को देखता है। गोहर ‘गंभीर’ तक नहीं पहुँचा।`
        : `Gohar’s stream peaked at ${n(f.peakFlow, 2)} m³/s, under the Watch line (${n(f.watchLine, 2)}). The danger came from the rain, not the river: that is why Pukaar watches both. Gohar never reached Critical.`,
      src: [{ label: hi ? 'GloFAS नदी पूर्वानुमान (Open-Meteo)' : 'GloFAS river forecast (Open-Meteo)', href: url(STORY_SOURCES.river) }],
    },
  };
  const b = body[s.id];
  const day = s.id === 'peak' ? new Intl.DateTimeFormat(hi ? 'hi-IN' : 'en-IN', { day: 'numeric', month: 'short' }).format(s.t) : `${stamp(s.t, lang)} IST`;
  return (
    <>
      <p className="s3-when">{day}</p>
      <h3 className={`s3-title lv-${s.level}`}>{b.title}</h3>
      <p className="s3-text">{b.text}</p>
      <p className="s3-src">
        {b.src.map((x) => (
          <a key={x.href} href={x.href} target="_blank" rel="noreferrer">
            {x.label} <ArrowUpRight aria-hidden="true" />
          </a>
        ))}
      </p>
    </>
  );
}

/** The five villages at time t: the small valley on a desk, a line of chips on a phone. */
function Five({ t }: { t: number }) {
  const { lang } = useT();
  const levels = levelsAt(FIVE, t);
  const villages = FIVE.map((v) => ({ id: v.village_id, ...NAMES[v.village_id], level: levels[v.village_id], data_status: 'ok' as const, data_ok_at: null }));
  return (
    <>
      <ValleyMap villages={villages} still className="s3-valley" />
      <ul className="s3-chips" aria-label={lang === 'hi' ? 'पाँच गाँव, उस समय तक का सबसे ऊँचा स्तर' : 'The five villages, the highest level by then'}>
        {villages.map((v) => {
          const Icon = LEVEL_ICON[v.level];
          return (
            <li key={v.id} className={`lv-${v.level}`}>
              <Icon aria-hidden="true" />
              <span>{lang === 'hi' ? v.name_hi : v.name}</span>
              <span className="sr-only">{dict[`level.${v.level}`][lang]}</span>
            </li>
          );
        })}
      </ul>
    </>
  );
}

export function StoryScroller() {
  const { lang } = useT();
  const reduced = useReducedMotion();
  const [active, setActive] = useState(0);
  const steps = useRef<(HTMLLIElement | null)[]>([]);
  const io = typeof IntersectionObserver !== 'undefined';
  const phone = useMedia('(max-width: 1023px)');

  useEffect(() => {
    if (reduced || !io) return;
    const obs = new IntersectionObserver(
      (es) => {
        for (const e of es) if (e.isIntersecting) setActive(Number((e.target as HTMLElement).dataset.i));
      },
      { rootMargin: '-45% 0px -45% 0px' },
    );
    steps.current.forEach((el) => el && obs.observe(el));
    return () => obs.disconnect();
  }, [reduced, io]);

  if (reduced || !io)
    return (
      <ol className="s3-still">
        {STORY_STEPS.map((s) => (
          <li key={s.id}>
            <StoryChart cursor={s.t} height={180} />
            <StepText s={s} lang={lang} />
          </li>
        ))}
      </ol>
    );

  const now = STORY_STEPS[active];
  return (
    <div className="s3">
      <div className="s3-stick">
        <StoryChart cursor={now.t} height={phone ? 170 : 300} />
        <Five t={now.t} />
      </div>
      <ol className="s3-steps">
        {STORY_STEPS.map((s, i) => (
          <li key={s.id} ref={(el) => { steps.current[i] = el; }} data-i={i} className={i === active ? 'is-on' : undefined}>
            <StepText s={s} lang={lang} />
          </li>
        ))}
      </ol>
    </div>
  );
}
