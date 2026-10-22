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
 * scrolls through the steps. Every number comes from the data file; a step
 * the data does not reach (Critical, for Gohar since risk-rules-v2) is left out.
 */

type Bi = { hi: string; en: string };
interface Point {
  at: string;
  rain_24h_mm: number | null;
  discharge_peak: number | null;
  level: string;
  river_level?: string;
  get_ready?: boolean;
}

const POINTS = story.points as Point[];
const IST: Intl.DateTimeFormatOptions = { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' };
const DAY: Intl.DateTimeFormatOptions = { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'long' };
const idxOf = (iso: string | null | undefined) => (iso ? POINTS.findIndex((p) => p.at === iso) : -1);

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
  title: (when: (i: number) => string, day: (iso: string) => string) => { hi: React.ReactNode; en: React.ReactNode };
  body: (when: (i: number) => string, day: (iso: string) => string) => Bi;
}

const first = story.first as { get_ready: string | null; watch: string | null; warning: string | null; critical: string | null };
const GR_IDX = Math.max(0, idxOf(first.get_ready));
const W_IDX = idxOf(first.watch);
const WR_IDX = idxOf(first.warning);
const C_IDX = idxOf(first.critical);
const LEAD = story.lead_hours_watch_to_peak_day;
const READY_LEAD = story.lead_hours_get_ready_to_peak_day as number | null;
const READY_MIN = Boolean(story.get_ready_from_first_hour);
const TRIGGER = story.get_ready_trigger as { first_day_over: string; line_cms: number } | null;
const EARLY = TRIGGER?.line_cms ?? (story.discharge_thresholds as { early?: number } | null)?.early ?? null;
// The stream stayed under its 2-year flood level the whole time: the alert came from rain alone.
const RIVER_QUIET = POINTS.every((p) => (p.river_level ?? 'normal') === 'normal');
const BANDS = story.imd_bands_mm;

const ALL_STEPS: (Step | null)[] = [
  {
    upto: Math.max(GR_IDX, W_IDX - 1),
    eyebrow: { hi: 'गोहर · मंडी · जुलाई 2023 · पुराने आँकड़ों पर दोबारा चलाया', en: 'Gohar · Mandi · July 2023 · re-run on archived data' },
    title: (when) => ({
      hi: <>{when(GR_IDX)}: <mark className="hl">तैयार रहें।</mark> यह चेतावनी नहीं।</>,
      en: <>{when(GR_IDX)}: <mark className="hl">get ready.</mark> Not an alert.</>,
    }),
    body: (_, day) => ({
      hi: `आने वाले हफ़्ते का नदी पूर्वानुमान ${TRIGGER ? `${day(TRIGGER.first_day_over)} को ` : ''}गोहर की तैयारी वाली रेखा${EARLY != null ? ` (${EARLY} m³/s, ऐसा बहाव 10 में से 1 दिन)` : ''} पार करता है। प्रधान की तैयारी सूची सामने आती है। कुछ नहीं भेजा जाता, स्तर सामान्य रहता है।`,
      en: `The river forecast for the week ahead passes Gohar's get-ready line${EARLY != null ? ` (${EARLY} m³/s, a flow the stream reaches 1 day in 10)` : ''}${TRIGGER ? ` on ${day(TRIGGER.first_day_over)}` : ''}. The pradhan's early-action checklist comes up. Nothing is sent, and the level stays Normal.`,
    }),
  },
  W_IDX >= 0
    ? {
        upto: W_IDX,
        title: (when) => ({
          hi: <>{when(W_IDX)}: बारिश {BANDS.watch} mm पार। <mark className="hl">सतर्क।</mark></>,
          en: <>{when(W_IDX)}: rain passes {BANDS.watch} mm. <mark className="hl">Watch.</mark></>,
        }),
        body: () => ({
          hi: `अगले 24 घंटे की बारिश IMD की भारी बारिश की सीमा पार करती है। स्तर कोड तय करता है, मॉडल नहीं। पुकार हिंदी में संदेश का मसौदा बनाकर ज़िला अधिकारी से पूछता है।${RIVER_QUIET ? ' नदी पूरे हफ़्ते अपने 2 साल वाले बाढ़-स्तर से नीचे रहती है।' : ''}`,
          en: `The rain forecast for the next 24 hours passes IMD's heavy-rain band. Code sets the level, never a model. Pukaar drafts a Hindi alert and asks the district officer.${RIVER_QUIET ? ' The stream stays under its 2-year flood level all week.' : ''}`,
        }),
      }
    : null,
  WR_IDX >= 0
    ? {
        upto: WR_IDX,
        title: (when) => ({
          hi: <>{when(WR_IDX)}: {BANDS.warning} mm। <mark className="hl">चेतावनी।</mark></>,
          en: <>{when(WR_IDX)}: {BANDS.warning} mm. <mark className="hl">Warning.</mark></>,
        }),
        body: () => ({
          hi: 'बहुत भारी बारिश का पूर्वानुमान। अधिकारी फ़ोन पर मसौदा सुनकर मंज़ूर करता है। गोहर के हर जुड़े फ़ोन पर हिंदी में बोली गई चेतावनी जाती है; एक बटन, "मिल गया", बताता है कि सुन ली गई।',
          en: 'Very heavy rain on the forecast. The officer listens to the draft on a phone and approves it. Every registered phone in Gohar gets a spoken Hindi alert; one tap, "मिल गया", confirms it was heard.',
        }),
      }
    : null,
  C_IDX >= 0
    ? {
        upto: C_IDX,
        title: (when) => ({
          hi: <>{when(C_IDX)}: <mark className="hl">गंभीर।</mark></>,
          en: <>{when(C_IDX)}: <mark className="hl">Critical.</mark></>,
        }),
        body: () => ({
          hi: 'जवाब नहीं आया तो चेतावनी दोबारा भेजी जाती है, और गंभीर स्तर पर कोई अधिकारी न मिले तो तय साँचे से अपने-आप जाती है।',
          en: 'No answer? It is sent again, and at Critical with no officer answering it goes out from the fixed template.',
        }),
      }
    : null,
  {
    upto: POINTS.length - 1,
    title: () => ({
      hi: <><mark className="hl big">{LEAD} घंटे</mark> पहले चेतावनी, नदी के सबसे ऊँचे दिन से।</>,
      en: <><mark className="hl big">{LEAD} hours</mark> of alert before the river's highest day.</>,
    }),
    body: (_, day) => ({
      hi: `तैयारी का आउटलुक इससे भी पहले था${READY_LEAD != null ? `: ${READY_MIN ? 'कम से कम ' : ''}${READY_LEAD} घंटे${READY_MIN ? ', पहले ही घंटे से' : ''}` : ''}। दोनों रीप्ले में नदी के सबसे ऊँचे दिन (${day(String(story.peak_discharge_day))}) तक गिने गए। यह पुराने आँकड़ों पर जाँच है, जहाँ "पूर्वानुमान" बाद में बना पुनर्विश्लेषण है; असली पूर्वानुमान कम निश्चित होता है, इसलिए दोनों को ऊपरी सीमा मानें। उस हफ़्ते गोहर में असल में क्या हुआ, यह अभी पक्का नहीं।`,
      en: `The get-ready outlook came first${READY_LEAD != null ? `: ${READY_MIN ? 'at least ' : ''}${READY_LEAD} hours ahead${READY_MIN ? ', on from the first archived hour' : ''}` : ''}. Both run to the river's highest day in the replay (${day(String(story.peak_discharge_day))}). This is a back-test on archived data, where the forecast is a later reanalysis; real forecasts are less certain, so read both as upper bounds. What happened in Gohar itself that week is not yet verified.`,
    }),
  },
];
const STEPS = ALL_STEPS.filter((st): st is Step => st !== null);

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
  const day = (iso: string) => new Date(iso).toLocaleDateString(lang === 'hi' ? 'hi-IN' : 'en-IN', DAY);

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
              {cur.get_ready && <span className="sr-ready">{t('story.ready')}</span>}
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
              {/* Get-ready strip: the outlook each hour (never an alert), above the level ribbon. */}
              <g className="ready-strip" clipPath="url(#story-clip)">
                {POINTS.map((p, i) =>
                  p.get_ready ? <rect key={p.at} x={x(i)} y={H - PAD.b + 4} width={(W - PAD.l - PAD.r) / (POINTS.length - 1) + 0.5} height={6} className="rb-ready" /> : null,
                )}
              </g>
              {/* Level ribbon: the final level each hour, with words at each change. */}
              <g className="ribbon" clipPath="url(#story-clip)">
                {POINTS.map((p, i) => (
                  <rect key={p.at} x={x(i)} y={H - PAD.b + 14} width={(W - PAD.l - PAD.r) / (POINTS.length - 1) + 0.5} height={14} className={`rb lv-${p.level}`} />
                ))}
              </g>
              {[W_IDX, WR_IDX, C_IDX].filter((i) => i >= 0).map((i, n) =>
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
                  {s.title(when, day)[lang]}
                </p>
                <p className="story-body" lang={lang}>
                  {L(s.body(when, day))}
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
