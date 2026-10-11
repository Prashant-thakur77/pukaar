import { useEffect, useState } from 'react';
import { CircleCheck, CircleDashed, CloudRain, FlaskConical, Target } from 'lucide-react';
import { loadBacktest } from '../api';
import { LevelBadge } from '../components/Level';
import { Reveal } from '../components/Reveal';
import { Headline } from '../components/PageBand';
import { EmptyState, Skeleton } from '../components/States';
import { useT, type Key } from '../i18n';
import { fmtDate, fmtNumber, fmtTime } from '../lib/format';
import { levelRank } from '../lib/levels';
import scores from '../data/scores.json';
import { LEVELS, type Backtest, type BacktestScenario, type BacktestVillage, type Level } from '../types';

const MEASURED: Key[] = ['impact.m1', 'impact.m2', 'impact.m3'];
const NOT_MEASURED: Key[] = ['impact.n1', 'impact.n2', 'impact.n3'];

function reached(v: BacktestVillage): Level {
  if (v.first_critical) return 'critical';
  if (v.first_warning) return 'warning';
  if (v.first_watch) return 'watch';
  return 'normal';
}

function Scenario({ sc, i }: { sc: BacktestScenario; i: number }) {
  const { t, lang } = useT();
  const crit = sc.villages.filter((v) => v.first_critical).length;
  const when = (iso: string | null) => (iso ? fmtTime(iso, lang) : <span className="muted">{t('impact.bt.never')}</span>);
  return (
    <Reveal className="scenario card" delay={i * 100}>
      <header className="sc-head">
        <div>
          <h3 className="sc-title">
            <span lang="hi">{sc.title_hi ?? sc.title}</span>
            <span className="sc-title-en">{sc.title}</span>
          </h3>
          <p className="small muted">
            {fmtDate(sc.start, lang)} → {fmtDate(sc.end, lang)}
          </p>
        </div>
        <p className="sc-summary">{t('impact.bt.summary', { c: crit, n: sc.villages.length })}</p>
      </header>
      <ul className="sc-bars" aria-hidden="true">
        {sc.villages.map((v) => (
          <li key={v.village_id} className={`lv-${reached(v)}`}>
            <span className="scb-name">{v.village}</span>
            <span className="scb-track">
              {LEVELS.map((l) => (
                <i key={l} className={levelRank(l) <= levelRank(reached(v)) && l !== 'normal' ? `on lv-${l}` : ''} />
              ))}
            </span>
          </li>
        ))}
      </ul>
      <div className="table-wrap" tabIndex={0} role="region" aria-label={sc.title}>
        <table className="data-table stack-sm">
          <thead>
            <tr>
              <th scope="col">{t('impact.bt.village')}</th>
              <th scope="col">{t('impact.bt.reached')}</th>
              <th scope="col">{t('impact.bt.first', { l: t('level.watch') })}</th>
              <th scope="col">{t('impact.bt.first', { l: t('level.warning') })}</th>
              <th scope="col">{t('impact.bt.first', { l: t('level.critical') })}</th>
              <th scope="col">{t('impact.bt.peak')}</th>
              <th scope="col">{t('impact.bt.rain')}</th>
              <th scope="col">{t('impact.bt.lead')}</th>
            </tr>
          </thead>
          <tbody>
            {sc.villages.map((v) => (
              <tr key={v.village_id}>
                <th scope="row">{v.village}</th>
                <td data-label={t('impact.bt.reached')}>
                  <LevelBadge level={reached(v)} size="sm" />
                </td>
                <td className="nowrap" data-label={t('impact.bt.first', { l: t('level.watch') })}>{when(v.first_watch)}</td>
                <td className="nowrap" data-label={t('impact.bt.first', { l: t('level.warning') })}>{when(v.first_warning)}</td>
                <td className="nowrap" data-label={t('impact.bt.first', { l: t('level.critical') })}>{when(v.first_critical)}</td>
                <td className="nowrap" data-label={t('impact.bt.peak')}>
                  {fmtNumber(v.peak_discharge, lang, 2)} m³/s
                  {v.thresholds && <span className="small muted"> / {fmtNumber(v.thresholds.critical, lang, 2)}</span>}
                  {v.peak_discharge_day && <span className="small muted"> · {fmtDate(v.peak_discharge_day, lang)}</span>}
                </td>
                <td className="nowrap" data-label={t('impact.bt.rain')}>{fmtNumber(v.max_rain_24h_mm, lang, 1)} mm</td>
                <td className="nowrap" data-label={t('impact.bt.lead')}>{v.lead_hours_watch_to_peak_day == null ? '—' : `${fmtNumber(v.lead_hours_watch_to_peak_day, lang)} h`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sc.sources && (
        <p className="small muted sc-sources">
          {t('impact.bt.sources')}:{' '}
          {Object.entries(sc.sources).map(([k, v]) => (
            <span key={k}>
              {k}: <code>{v}</code>{' '}
            </span>
          ))}
        </p>
      )}
    </Reveal>
  );
}

const CONFIG_KEY: Record<string, Key> = { rain: 'impact.sc.rain', river: 'impact.sc.river', both: 'impact.sc.both' };

function Scores() {
  const { t, lang } = useT();
  return (
    <section className="band band-paper scores-band" aria-labelledby="sc-h">
      <div className="wrap">
        <h2 id="sc-h" className="h-sec">
          <Target aria-hidden="true" /> {t('impact.sc.title')}
        </h2>
        <p className="muted sc-lead">{t('impact.sc.lead')}</p>
        <div className="scenarios">
          {scores.scenarios.map((sc, i) => (
            <Reveal key={sc.name} className="scenario card score-card" delay={i * 100}>
              <header className="sc-head">
                <h3 className="sc-title">
                  <span lang="hi">{sc.title_hi ?? sc.title}</span>
                  <span className="sc-title-en">{sc.title}</span>
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
            </Reveal>
          ))}
          <p className="caveat">{t('impact.sc.caveat')}</p>
        </div>
      </div>
    </section>
  );
}

export default function Impact() {
  const { t } = useT();
  const [bt, setBt] = useState<Backtest | null | undefined>(undefined);
  useEffect(() => {
    void loadBacktest().then(setBt);
  }, []);
  
  return (
    <div className="impact">
      <section className="band band-night impact-hero">
        <div className="wrap">
          <Reveal variant="slide">
            <p className="eyebrow eyebrow-night">{t('impact.eyebrow')}</p>
            <h1 className="display-2 on-night pg-title">
              <Headline text={t('impact.title')} />
            </h1>
            <p className="lead on-night-2">{t('impact.lead')}</p>
          </Reveal>
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
              {bt.scenarios.map((sc, i) => (
                <Scenario key={sc.name} sc={sc} i={i} />
              ))}
              <p className="caveat">{t('impact.bt.caveat')}</p>
              {bt.rules && <p className="small muted">Rules: <code>{bt.rules}</code></p>}
            </div>
          )}
        </div>
      </section>

      <Scores />

      <section className="band band-paper-2">
        <div className="wrap measure-grid">
          <Reveal className="measure card">
            <h2 className="h-sec">
              <CircleCheck aria-hidden="true" className="ok-icon" /> {t('impact.measured')}
            </h2>
            <ul className="tick-list">
              {MEASURED.map((k) => (
                <li key={k}>{t(k)}</li>
              ))}
            </ul>
          </Reveal>
          <Reveal className="measure card" delay={100}>
            <h2 className="h-sec">
              <CircleDashed aria-hidden="true" className="muted-icon" /> {t('impact.notmeasured')}
            </h2>
            <ul className="tick-list is-open">
              {NOT_MEASURED.map((k) => (
                <li key={k}>{t(k)}</li>
              ))}
            </ul>
          </Reveal>
        </div>
      </section>

      <section className="band band-paper">
        <div className="wrap">
          <Reveal className="candid card">
            <CloudRain aria-hidden="true" className="candid-icon" />
            <div>
              <h2 className="h-sec">{t('impact.cloudburst.title')}</h2>
              <p>{t('impact.cloudburst.body')}</p>
            </div>
          </Reveal>
        </div>
      </section>
    </div>
  );
}
