import { useEffect, useState } from 'react';
import { ArrowUpRight, CircleCheck, CircleDashed, CloudRain, FlaskConical, Target } from 'lucide-react';
import { loadBacktest } from '../api';
import { LevelBadge } from '../components/Level';
import { DogStory } from '../components/DogStory';
import { SatelliteCompare } from '../components/SatelliteCompare';
import { EmptyState, Skeleton } from '../components/States';
import { useT, type Key } from '../i18n';
import { fmtDate, fmtNumber, fmtTime } from '../lib/format';
import { levelRank } from '../lib/levels';
import { villageNameIn } from '../lib/villageNames';
import scores from '../data/scores.json';
import { LEVELS, type Backtest, type BacktestScenario, type BacktestVillage, type Level } from '../types';
import { Measured } from '../components/Measured';
import { StoryScroller } from '../components/StoryScroller';
import { reached as reachedCount } from '../lib/story';
import '../styles/story.css';
import '../styles/explain.css';

const MEASURED: Key[] = ['impact.m1', 'impact.m2', 'impact.m3'];
const NOT_MEASURED: Key[] = ['impact.n1', 'impact.n2', 'impact.n3'];

function reached(v: BacktestVillage): Level {
  if (v.first_critical) return 'critical';
  if (v.first_warning) return 'warning';
  if (v.first_watch) return 'watch';
  return 'normal';
}

function Scenario({ sc }: { sc: BacktestScenario }) {
  const { t, lang } = useT();
  const crit = sc.villages.filter((v) => v.first_critical).length;
  const when = (iso: string | null | undefined) => (iso ? fmtTime(iso, lang) : <span className="muted">{t('impact.bt.never')}</span>);
  const hours = (h: number | null | undefined, lowerBound?: boolean) =>
    // Non-breaking spaces: "≥ 96 h" never splits across lines.
    h == null ? '—' : `${lowerBound ? '≥\u00a0' : ''}${fmtNumber(h, lang)}\u00a0${lang === 'hi' ? 'घंटे' : 'h'}`;
  return (
    <div className="scenario card">
      <header className="sc-head">
        <div>
          <h3 className="sc-title">
            <span>{lang === 'hi' ? sc.title_hi ?? sc.title : sc.title}</span>
          </h3>
          <p className="small muted">
            {fmtDate(sc.start, lang)} → {fmtDate(sc.end, lang)}
          </p>
        </div>
        <p className="sc-summary">
          <b>
            {fmtNumber(crit, lang)}/{fmtNumber(sc.villages.length, lang)}
          </b>
          <span>{t('impact.bt.summary', { c: crit, n: sc.villages.length })}</span>
        </p>
      </header>
      <ul className="sc-bars" aria-hidden="true">
        {sc.villages.map((v) => (
          <li key={v.village_id} className={`lv-${reached(v)}`}>
            <span className="scb-name">{villageNameIn(v.village_id, v.village, lang)}</span>
            <span className="scb-track">
              {LEVELS.map((l) => (
                <i key={l} className={levelRank(l) <= levelRank(reached(v)) && l !== 'normal' ? `on lv-${l}` : ''} />
              ))}
            </span>
          </li>
        ))}
      </ul>
      <ScenarioCards sc={sc} />
      <div className="table-wrap bt-table" tabIndex={0} role="region" aria-label={lang === 'hi' ? sc.title_hi ?? sc.title : sc.title}>
        <table className="data-table stack-sm">
          <thead>
            <tr>
              <th scope="col">{t('impact.bt.village')}</th>
              <th scope="col">{t('impact.bt.reached')}</th>
              <th scope="col">{t('impact.bt.ready')}</th>
              <th scope="col">{t('impact.bt.lead')}</th>
              <th scope="col">{t('impact.bt.first', { l: t('level.warning') })}</th>
              <th scope="col">{t('impact.bt.first', { l: t('level.critical') })}</th>
              <th scope="col">{t('impact.bt.peak')}</th>
              <th scope="col">{t('impact.bt.rain')}</th>
            </tr>
          </thead>
          <tbody>
            {sc.villages.map((v) => (
              <tr key={v.village_id}>
                <th scope="row">{villageNameIn(v.village_id, v.village, lang)}</th>
                <td data-label={t('impact.bt.reached')}>
                  <LevelBadge level={reached(v)} size="sm" plain={reached(v) !== 'critical'} />
                </td>
                <td data-label={t('impact.bt.ready')}>
                  <span>
                    {when(v.first_get_ready)}
                    {v.lead_hours_get_ready_to_peak_day != null && <span className="small muted"> · {hours(v.lead_hours_get_ready_to_peak_day, v.get_ready_from_first_hour)}</span>}
                  </span>
                </td>
                <td data-label={t('impact.bt.lead')}>
                  <span>
                    {when(v.first_watch)}
                    {v.lead_hours_watch_to_peak_day != null && <span className="small muted"> · {hours(v.lead_hours_watch_to_peak_day, v.watch_from_first_hour)}</span>}
                  </span>
                </td>
                <td className="nowrap" data-label={t('impact.bt.first', { l: t('level.warning') })}>{when(v.first_warning)}</td>
                <td className="nowrap" data-label={t('impact.bt.first', { l: t('level.critical') })}>{when(v.first_critical)}</td>
                <td className="nowrap" data-label={t('impact.bt.peak')}>
                  <span>
                    {fmtNumber(v.peak_discharge, lang, 2)} m³/s
                    {v.thresholds && <span className="small muted"> / {fmtNumber(v.thresholds.critical, lang, 2)}</span>}
                    {v.peak_discharge_day && <span className="small muted"> · {fmtDate(v.peak_discharge_day, lang)}</span>}
                  </span>
                </td>
                <td className="nowrap" data-label={t('impact.bt.rain')}>{fmtNumber(v.max_rain_24h_mm, lang, 1)} {lang === 'hi' ? 'मिमी' : 'mm'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sc.sources && (
        <details className="xp-dis sc-sources">
          <summary>{t('impact.bt.sources')}</summary>
          <ul className="xp-sources">
            {Object.entries(sc.sources).map(([k, v]) => {
              const href = v.split(' ')[0];
              return (
                <li key={k}>
                  <a href={href} target="_blank" rel="noreferrer" className="xp-src">
                    {SRC_WORD[k]?.[lang] ?? k}: {href.replace(/^https?:\/\//, '').split('/')[0]} <ArrowUpRight aria-hidden="true" className="xp-ext" />
                  </a>
                  {/* What was read, in the API's own parameter words: English pages only. */}
                  {lang === 'en' && <span className="xp-td-sub">{v.slice(href.length).trim().replace(/^\(|\)$/g, '')}</span>}
                </li>
              );
            })}
          </ul>
        </details>
      )}
    </div>
  );
}


/** The mobile form of the back-test (spec 4.8): a card per village with what matters, the rest in a disclosure. */
function ScenarioCards({ sc }: { sc: BacktestScenario }) {
  const { t, lang } = useT();
  const hi = lang === 'hi';
  const when = (iso: string | null | undefined) => (iso ? fmtTime(iso, lang) : t('impact.bt.never'));
  return (
    <ul className="bt-cards">
      {sc.villages.map((v) => (
        <li key={v.village_id} className={`lv-${reached(v)}`}>
          <p className="bt-card-name">
            <span>{villageNameIn(v.village_id, v.village, lang)}</span>
            <LevelBadge level={reached(v)} size="sm" plain={reached(v) !== 'critical'} />
          </p>
          <dl className="bt-card-facts">
            <div>
              <dt>{hi ? 'पहली ‘सतर्क’' : 'First Watch'}</dt>
              <dd>{when(v.first_watch)}</dd>
            </div>
            <div>
              <dt>{hi ? 'कितने घंटे पहले' : 'Hours early'}</dt>
              <dd>{v.lead_hours_watch_to_peak_day != null ? `${v.watch_from_first_hour ? '≥ ' : ''}${fmtNumber(v.lead_hours_watch_to_peak_day, lang)} ${hi ? 'घंटे' : 'h'}` : '—'}</dd>
            </div>
          </dl>
          <details className="xp-dis">
            <summary>{hi ? 'बाक़ी आँकड़े' : 'The rest'}</summary>
            <dl className="bt-card-facts">
              <div>
                <dt>{t('impact.bt.ready')}</dt>
                <dd>{when(v.first_get_ready)}</dd>
              </div>
              <div>
                <dt>{t('impact.bt.first', { l: t('level.warning') })}</dt>
                <dd>{when(v.first_warning)}</dd>
              </div>
              <div>
                <dt>{t('impact.bt.first', { l: t('level.critical') })}</dt>
                <dd>{when(v.first_critical)}</dd>
              </div>
              <div>
                <dt>{t('impact.bt.peak')}</dt>
                <dd>
                  {fmtNumber(v.peak_discharge, lang, 2)} m³/s{v.peak_discharge_day ? ` · ${fmtDate(v.peak_discharge_day, lang)}` : ''}
                </dd>
              </div>
              <div>
                <dt>{t('impact.bt.rain')}</dt>
                <dd>{fmtNumber(v.max_rain_24h_mm, lang, 1)} {hi ? 'मिमी' : 'mm'}</dd>
              </div>
            </dl>
          </details>
        </li>
      ))}
    </ul>
  );
}

const SRC_WORD: Record<string, { hi: string; en: string }> = {
  rain: { hi: 'बारिश', en: 'Rain' },
  river: { hi: 'नदी', en: 'River' },
  rain_models: { hi: 'बौछार के मॉडल', en: 'Burst models' },
};

const CONFIG_KEY: Record<string, Key> = { rain: 'impact.sc.rain', river: 'impact.sc.river', both: 'impact.sc.both', both_soil: 'impact.sc.both_soil' };

function Scores() {
  const { t, lang } = useT();
  return (
    <section className="band band-paper scores-band" aria-labelledby="sc-h">
      <div className="wrap" data-tour="scores">
        <h2 id="sc-h" className="h-sec">
          <Target aria-hidden="true" /> {t('impact.sc.title')}
        </h2>
        <p className="muted sc-lead">{t('impact.sc.lead')}</p>
        <div className="scenarios">
          {scores.scenarios.map((sc) => (
            <div key={sc.name} className="scenario card score-card">
              <header className="sc-head">
                <h3 className="sc-title">
                  <span>{lang === 'hi' ? sc.title_hi ?? sc.title : sc.title}</span>
                </h3>
                <p className="small muted">{t('impact.sc.scored', { n: sc.configs[0]?.scored ?? 0 })}</p>
              </header>
              <ul className="score-grid">
                {sc.configs.map((c) => (
                  <li key={c.key} className={c.key === 'both' ? 'is-pukaar' : undefined}>
                    <p className="score-name">{t(CONFIG_KEY[c.key] ?? 'impact.sc.both')}</p>
                    <dl className="score-counts">
                      <div className="sc-hit"><dt>{t('impact.sc.hits')}</dt><dd>{fmtNumber(c.hits, lang)}</dd></div>
                      <div className="sc-miss"><dt>{t('impact.sc.misses')}</dt><dd>{fmtNumber(c.misses, lang)}</dd></div>
                      <div className="sc-fa"><dt>{t('impact.sc.fa')}</dt><dd>{c.scored - c.hits - c.misses > 0 ? fmtNumber(c.false_alarms, lang) : '—'}</dd></div>
                    </dl>
                    <p className="small muted">
                      {c.median_lead_hours == null
                        ? '—'
                        : t(c.lead_is_lower_bound ? 'impact.sc.lead_min' : 'impact.sc.lead_h', { h: fmtNumber(c.median_lead_hours, lang) })}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <p className="caveat">{t('impact.sc.caveat')}</p>
        </div>
      </div>
    </section>
  );
}

const STORY_FIVE = scores.scenarios.find((x) => x.name === 'himachal_2023_07')!.soil_effect;

const SOURCES: { label: { hi: string; en: string }; href: string }[] = [
  { label: { en: 'Open-Meteo, archived weather forecasts', hi: 'Open-Meteo, पुराने मौसम पूर्वानुमान' }, href: 'https://historical-forecast-api.open-meteo.com/v1/forecast' },
  { label: { en: 'Open-Meteo flood API (GloFAS v4)', hi: 'Open-Meteo का बाढ़ API (GloFAS v4)' }, href: 'https://flood-api.open-meteo.com/v1/flood' },
  { label: { en: 'Newslaundry, 8 Aug 2023: Pandoh', hi: 'Newslaundry, 8 अगस्त 2023: पंडोह' }, href: 'https://www.newslaundry.com/2023/08/08/our-lives-are-set-back-25-years-in-himachal-a-village-loses-everything-to-floods-2' },
  { label: { en: 'The ground truth, with every source (data/ground_truth.json)', hi: 'असल में क्या हुआ, हर स्रोत के साथ (data/ground_truth.json)' }, href: 'https://github.com/Prashant-thakur77/pukaar/blob/main/data/ground_truth.json' },
  { label: { en: 'The back-test script and its output (data/backtest.json)', hi: 'बैक-टेस्ट की स्क्रिप्ट और उसका नतीजा (data/backtest.json)' }, href: 'https://github.com/Prashant-thakur77/pukaar/blob/main/data/backtest.json' },
];

export default function Proof() {
  const { t, lang } = useT();
  const hi = lang === 'hi';
  const [bt, setBt] = useState<Backtest | null | undefined>(undefined);
  useEffect(() => {
    void loadBacktest().then(setBt);
  }, []);
  const crit = reachedCount(STORY_FIVE, 'critical');
  const critName = STORY_FIVE.find((v) => v.both.first_critical)?.village;

  return (
    <div className="xp impact proof">
      <header className="xp-hero wrap">
        <div className="xp-hero-text">
          <h1 className="xp-h1">{t('impact.title')}</h1>
          <p className="xp-lead">{t('impact.lead')}</p>
        </div>
        <DogStory variant="quote" />
      </header>

      <section className="wrap xp-chapter" aria-labelledby="story-h" data-tour="story">
        <h2 id="story-h" className="xp-h2">
          {hi ? 'वह रात जब नदी चढ़ी' : 'The night the river rose'}
        </h2>
        <p className="xp-lead">
          {hi
            ? '7 से 11 जुलाई 2023, मंडी। उस समय के असली पूर्वानुमान पर आज के पुकार के नियम चलाए गए, घंटे दर घंटे। यह बैक-टेस्ट है: तब कोई चेतावनी नहीं भेजी गई थी।'
            : '7 to 11 July 2023, Mandi. Today’s Pukaar rules, run hour by hour on the forecasts of the time. This is a back-test: no alert was sent then.'}
        </p>
        <StoryScroller />
        <div className="xp-numblock">
          <b>
            {fmtNumber(crit, lang)}/{fmtNumber(STORY_FIVE.length, lang)}
          </b>
          <p className="xp-p">
            {hi
              ? `पाँच में से ${fmtNumber(crit, lang)} गाँव ‘गंभीर’ तक पहुँचा${critName ? ` (${villageNameIn(critName.toLowerCase(), critName, lang)})` : ''}; बाक़ी ‘सतर्क’ या ‘चेतावनी’ पर रहे, या शांत।`
              : `${crit} of the five villages reached Critical${critName ? ` (${critName})` : ''}; the rest stayed at Watch or Warning, or calm.`}
          </p>
        </div>
      </section>

      <section className="band band-paper" aria-labelledby="bt-h">
        <div className="wrap">
          <h2 id="bt-h" className="h-sec">
            <FlaskConical aria-hidden="true" /> {t('impact.backtest')}
          </h2>
          {bt === undefined ? (
            <Skeleton lines={5} />
          ) : bt === null || bt.scenarios.length === 0 ? (
            <EmptyState title={t('impact.backtest.none')} body={t('impact.backtest.none.body')} icon={<FlaskConical />} />
          ) : (
            <div className="scenarios">
              {bt.scenarios.map((sc) => (
                <Scenario key={sc.name} sc={sc} />
              ))}
              <p className="small">{t('impact.bt.ready.note')}</p>
              <p className="caveat">{t('impact.bt.caveat')}</p>
            </div>
          )}
        </div>
      </section>

      <SatelliteCompare />

      <Scores />

      <section className="band band-paper" aria-labelledby="measured-h">
        <div className="wrap">
          <h2 id="measured-h" className="xp-h2">
            {hi ? 'अब तक असल में क्या मापा' : 'Measured so far, for real'}
          </h2>
          <p className="xp-p">
            {hi
              ? 'सिर्फ़ असली रिकॉर्ड: भेजे गए अभ्यास, असली चेतावनियाँ, “मिल गया”। जो मापा नहीं गया, वह यही कहता है।'
              : 'Real records only: drills sent, live alerts, “Got it”. Where nothing is measured, it says so.'}
          </p>
          <Measured />
        </div>
      </section>

      <section className="band band-paper-2" aria-labelledby="limits-h">
        <div className="wrap">
          <h2 id="limits-h" className="xp-h2">
            {hi ? 'ईमानदार सीमाएँ' : 'Honest limits'}
          </h2>
          <div className="measure-grid">
            <div className="measure card">
              <h3 className="h-sec">
                <CircleCheck aria-hidden="true" className="ok-icon" /> {t('impact.measured')}
              </h3>
              <ul className="tick-list">
                {MEASURED.map((k) => (
                  <li key={k}>{t(k)}</li>
                ))}
              </ul>
            </div>
            <div className="measure card">
              <h3 className="h-sec">
                <CircleDashed aria-hidden="true" className="muted-icon" /> {t('impact.notmeasured')}
              </h3>
              <ul className="tick-list is-open">
                {NOT_MEASURED.map((k) => (
                  <li key={k}>{t(k)}</li>
                ))}
              </ul>
            </div>
          </div>
          <div className="candid card">
            <CloudRain aria-hidden="true" className="candid-icon" />
            <div>
              <h3 className="h-sec">{t('impact.cloudburst.title')}</h3>
              <p>{t('impact.cloudburst.body')}</p>
            </div>
          </div>
        </div>
      </section>

      <section className="wrap xp-chapter" aria-labelledby="src-h">
        <h2 id="src-h" className="xp-h2">
          {hi ? 'स्रोत' : 'Sources'}
        </h2>
        <ul className="xp-sources">
          {SOURCES.map((x) => (
            <li key={x.href}>
              <a href={x.href} target="_blank" rel="noreferrer" className="xp-src">
                {x.label[lang]} <ArrowUpRight aria-hidden="true" className="xp-ext" />
              </a>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
