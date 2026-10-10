import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import story from '../data/story-gohar-2023.json';
import { useReducedMotion } from '../hooks/useMotion';
import { useT } from '../i18n';
import type { Level } from '../types';

/*
 * "The night the river rose": Gohar, Mandi, July 2023, replayed through the
 * real risk rules (built by backend/src/Pukaar/scripts/story.py, so it always
 * matches data/backtest.json). A sticky chart draws itself as the reader
 * scrolls through five steps. Every number comes from the data file.
 */

type Bi = { hi: string; en: string };
interface Point {
  at: string;
  rain_24h_mm: number | null;
  discharge_peak: number | null;
  level: string;
}

const POINTS = story.points as Point[];
const IST: Intl.DateTimeFormatOptions = { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' };
const idxOf = (iso: string | null) => Math.max(0, POINTS.findIndex((p) => p.at === iso));

const W = 640;
const H = 340;
const PAD = { l: 44, r: 16, t: 34, b: 72 };
const Y_MAX = 140; // mm; the IMD critical band (204.5) sits above, marked with an arrow.
const LEVEL_WORD: Record<Level, Bi> = {
  normal: { hi: 'सामान्य', en: 'Normal' },
  watch: { hi: 'सतर्क', en: 'Watch' },
  warning: { hi: 'चेतावनी', en: 'Warning' },
  critical: { hi: 'गंभीर', en: 'Critical' },
};

const x = (i: number) => PAD.l + (i / (POINTS.length - 1)) * (W - PAD.l - PAD.r);
const y = (mm: number) => PAD.t + (1 - Math.min(mm, Y_MAX) / Y_MAX) * (H - PAD.t - PAD.b);

interface Step {
  upto: number;
  eyebrow?: Bi;
  title: (when: (i: number) => string) => { hi: React.ReactNode; en: React.ReactNode };
  body: (when: (i: number) => string) => Bi;
}

const W_IDX = idxOf(story.first.watch);
const WR_IDX = idxOf(story.first.warning);
const C_IDX = idxOf(story.first.critical);
const LEAD = story.lead_hours_watch_to_peak_day;

const STEPS: Step[] = [
  {
    upto: W_IDX - 1,
    eyebrow: { hi: 'गोहर · मंडी · जुलाई 2023 · पुराने आँकड़ों पर दोबारा चलाया', en: 'Gohar · Mandi · July 2023 · re-run on archived data' },
    title: () => ({
      hi: <>जो चाहिए था, वह <mark className="hl">पूर्वानुमान में पहले से था।</mark></>,
      en: <>Everything needed was <mark className="hl">already in the forecast.</mark></>,
    }),
    body: () => ({
      hi: 'यह अगले 24 घंटे की बारिश का पूर्वानुमान है, घंटे-दर-घंटे, जैसा पुकार की हर 15 मिनट की जाँच पढ़ती। धारीदार रेखाएँ IMD की भारी बारिश की सीमाएँ हैं।',
      en: "This is the rain forecast for the next 24 hours, hour by hour, as Pukaar's 15-minute sweep would have read it. The dashed lines are IMD's heavy-rain bands.",
    }),
  },
  {
    upto: W_IDX,
    title: (when) => ({
      hi: <>{when(W_IDX)}: नदी का पूर्वानुमान <mark className="hl">अपने 90वें प्रतिशतक</mark> से ऊपर।</>,
      en: <>{when(W_IDX)}: the river forecast passes <mark className="hl">its 90th percentile.</mark></>,
    }),
    body: () => ({
      hi: `गोहर की नदी के 1984 से अब तक के रिकॉर्ड से सीमा तय होती है। स्तर: सतर्क। पुकार हिंदी में संदेश का मसौदा बनाता है और ज़िला अधिकारी से पूछता है।`,
      en: "Gohar's own river record since 1984 sets the marks. Level: Watch. Pukaar drafts a Hindi alert and asks the district officer.",
    }),
  },
  {
    upto: WR_IDX,
    title: (when) => ({
      hi: <>{when(WR_IDX)}: <mark className="hl">दो स्रोत एक बात कहते हैं।</mark></>,
      en: <>{when(WR_IDX)}: <mark className="hl">two sources agree.</mark></>,
    }),
    body: () => ({
      hi: 'बारिश 64.5 mm पार करती है, और नदी पहले से सतर्क पर है। इसलिए स्तर एक ऊपर: चेतावनी। स्तर कोड तय करता है, मॉडल नहीं। अधिकारी फ़ोन पर मसौदा सुनता है और मंज़ूर करता है।',
      en: 'Rain passes 64.5 mm while the river is already at Watch, so the level goes up one: Warning. Code sets the level, never the model. The officer listens to the draft on a phone and approves it.',
    }),
  },
  {
    upto: C_IDX,
    title: (when) => ({
      hi: <>{when(C_IDX)}: <mark className="hl">गंभीर।</mark></>,
      en: <>{when(C_IDX)}: <mark className="hl">Critical.</mark></>,
    }),
    body: () => ({
      hi: 'बारिश का पूर्वानुमान 115.6 mm पार करता है। गोहर के हर जुड़े फ़ोन पर हिंदी में बोली गई चेतावनी जाती है। एक बटन, "मिल गया", बताता है कि सुन ली गई। जवाब नहीं आया तो दोबारा भेजी जाती है।',
      en: 'The rain forecast passes 115.6 mm. Every registered phone in Gohar gets a spoken Hindi alert. One tap, "मिल गया", confirms it was heard. No answer? It is sent again.',
    }),
  },
  {
    upto: POINTS.length - 1,
    title: () => ({
      hi: <><mark className="hl big">{LEAD} घंटे</mark> पहले, नदी के सबसे ऊँचे दिन से।</>,
      en: <><mark className="hl big">{LEAD} hours</mark> ahead of the river's peak day.</>,
    }),
    body: () => ({
      hi: 'पहली "सतर्क" से नदी के सबसे ऊँचे बहाव वाले दिन तक। यह पुराने आँकड़ों पर जाँच है, जहाँ "पूर्वानुमान" बाद में बना पुनर्विश्लेषण है; असली पूर्वानुमान कम निश्चित होता है, इसलिए इसे ऊपरी सीमा मानें।',
      en: "From the first Watch to the day of peak river flow. This is a back-test on archived data, where the forecast is a later reanalysis; a real forecast is less certain, so read it as an upper bound.",
    }),
  },
];

const BAND_LABEL: Record<'watch' | 'warning' | 'critical', Bi> = {
  watch: LEVEL_WORD.watch,
  warning: LEVEL_WORD.warning,
  critical: LEVEL_WORD.critical,
};

export function StoryNight() {
  const { t, lang } = useT();
  const reduced = useReducedMotion();
  const [active, setActive] = useState(reduced ? STEPS.length - 1 : 0);
  const refs = useRef<(HTMLLIElement | null)[]>([]);
  const L = (b: Bi) => b[lang];
  const when = (i: number) => new Date(POINTS[i].at).toLocaleString(lang === 'hi' ? 'hi-IN' : 'en-IN', IST);

  useEffect(() => {
    if (reduced || typeof IntersectionObserver === 'undefined') return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setActive(Number((e.target as HTMLElement).dataset.step));
      },
      { rootMargin: '-45% 0px -45% 0px' },
    );
    refs.current.forEach((el) => el && io.observe(el));
    return () => io.disconnect();
  }, [reduced]);

  const shown = reduced ? POINTS.length - 1 : STEPS[active].upto;
  const path = useMemo(
    () => POINTS.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.rain_24h_mm ?? 0).toFixed(1)}`).join(' '),
    [],
  );
  const cur = POINTS[shown];
  const curLevel = cur.level as Level;
  const clipW = x(shown) - PAD.l + 2;

  return (
    <section id="story" className="story band" aria-labelledby="story-h">
      <div className="wrap story-grid">
        <div className="story-chart">
          <figure className="story-fig">
            <div className="story-readout" aria-hidden="true">
              <span className="sr-when">{when(shown)} IST</span>
              <span className="sr-val">{(cur.rain_24h_mm ?? 0).toFixed(1)} mm</span>
              <span className={`sr-lv lv-${curLevel}`}>{L(LEVEL_WORD[curLevel])}</span>
            </div>
            <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="story-fig-t">
              <title id="story-fig-t">{t('story.figTitle')}</title>
              {(['watch', 'warning'] as const).map((k) => (
                <g key={k} className={`band-line band-${k}`}>
                  <line x1={PAD.l} x2={W - PAD.r} y1={y(story.imd_bands_mm[k])} y2={y(story.imd_bands_mm[k])} />
                  <text x={W - PAD.r} y={y(story.imd_bands_mm[k]) - 6} textAnchor="end">
                    {story.imd_bands_mm[k]} mm · {L(BAND_LABEL[k])}
                  </text>
                </g>
              ))}
              <text className="band-off" x={W - PAD.r} y={PAD.t - 10} textAnchor="end">
                ↑ {story.imd_bands_mm.critical} mm · {L(BAND_LABEL.critical)}
              </text>
              <text className="axis-t" x={PAD.l} y={PAD.t - 10}>
                {t('story.axis')}
              </text>
              <text className="axis-y" x={PAD.l - 8} y={y(0)} textAnchor="end">0</text>
              <text className="axis-y" x={PAD.l - 8} y={y(100) + 4} textAnchor="end">100</text>
              <clipPath id="story-clip">
                <rect x={PAD.l - 2} y={0} width={clipW} height={H} className="story-clip-rect" />
              </clipPath>
              <path d={path} className="rain-ghost" />
              <path d={path} className="rain-line" clipPath="url(#story-clip)" />
              <circle cx={x(shown)} cy={y(cur.rain_24h_mm ?? 0)} r={6} className="rain-dot" />
              {/* Level ribbon: the final level each hour, with words at each change. */}
              <g className="ribbon" clipPath="url(#story-clip)">
                {POINTS.map((p, i) => (
                  <rect key={p.at} x={x(i)} y={H - PAD.b + 14} width={(W - PAD.l - PAD.r) / (POINTS.length - 1) + 0.5} height={14} className={`rb lv-${p.level}`} />
                ))}
              </g>
              {[W_IDX, WR_IDX, C_IDX].map((i, n) =>
                i <= shown ? (
                  <g key={i} className="flag">
                    <line x1={x(i)} x2={x(i)} y1={PAD.t} y2={H - PAD.b + 28 + (n % 2) * 16} />
                    <text x={x(i) + 4} y={H - PAD.b + 44 + (n % 2) * 16}>
                      {L(LEVEL_WORD[POINTS[i].level as Level])}
                    </text>
                  </g>
                ) : null,
              )}
            </svg>
            <figcaption className="small muted">{t('story.caption')}</figcaption>
          </figure>
        </div>

        <div className="story-steps">
          <h2 id="story-h" className="sr-only">
            {t('story.heading')}
          </h2>
          <ol>
            {STEPS.map((s, i) => (
              <li
                key={i}
                ref={(el) => {
                  refs.current[i] = el;
                }}
                data-step={i}
                className={`story-step${i === active || reduced ? ' is-on' : ''}`}
              >
                {s.eyebrow && <p className="eyebrow">{L(s.eyebrow)}</p>}
                <p className="story-title" lang={lang}>
                  {s.title(when)[lang]}
                </p>
                <p className="story-body" lang={lang}>
                  {L(s.body(when))}
                </p>
                {i === STEPS.length - 1 && (
                  <Link to="/impact" className="btn btn-ghost story-more">
                    {t('story.more')} <ArrowRight aria-hidden="true" />
                  </Link>
                )}
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
