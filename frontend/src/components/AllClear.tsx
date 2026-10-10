import { Link } from 'react-router-dom';
import { ArrowRight, CircleCheck } from 'lucide-react';
import { api } from '../api';
import { usePoll } from '../hooks/usePoll';
import { useT } from '../i18n';
import { fmtAgo, fmtNumber } from '../lib/format';
import type { Village } from '../types';

const SWEEP_MINUTES = 15; // the SweepSchedule in infra/template.yaml
const RAIN_WATCH_MM = 64.5; // IMD "heavy rain" band; services/risk_rules.py RAIN_BANDS

/** Newest live (not replay) reading across all villages: when the last sweep ran. */
function lastSweepAt(villages: Village[]): string | null {
  let best: string | null = null;
  for (const v of villages) {
    const r = v.latest_reading;
    if (r && !r.replay && (!best || r.at > best)) best = r.at;
  }
  return best;
}

function Headroom({ label, value, pct }: { label: string; value: string; pct: number | null }) {
  return (
    <div className="clr-meter">
      <span className="clr-mlabel">{label}</span>
      <span className="clr-bar" aria-hidden="true">
        <i style={{ width: `${pct === null ? 0 : Math.min(100, Math.max(2, pct))}%` }} />
      </span>
      <span className="clr-mval">{value}</span>
    </div>
  );
}

/**
 * Quiet season: every village is Normal. Shows when the last sweep ran, when
 * the next is due, and how far each village is from its Watch line, all from
 * the latest stored reading (GET /villages). Nothing here is estimated.
 */
export function AllClear() {
  const { t, lang } = useT();
  const { data, updatedAt } = usePoll(() => api.villages(), [], 60000);
  if (!data || !updatedAt) return null;
  const last = lastSweepAt(data);
  const nextMin = last ? Math.ceil((new Date(last).getTime() + SWEEP_MINUTES * 60000 - updatedAt) / 60000) : null;

  return (
    <section className="all-clear card" aria-labelledby="clear-h">
      <h2 id="clear-h" className="h-sec">
        <CircleCheck aria-hidden="true" className="clr-icon" /> {t('live.clear.title')}
      </h2>
      <p className="clr-lead">
        {t('live.clear.lead')}{' '}
        {last && (
          <>
            {t('live.clear.sweep', { ago: fmtAgo(last, lang, updatedAt) })}
            {' · '}
            {nextMin !== null && nextMin > 0 ? t('live.clear.next', { n: nextMin }) : t('live.clear.next.due')}
          </>
        )}
      </p>
      <p className="clr-sub small muted">{t('live.clear.headroom')}</p>
      <ul className="clr-list">
        {data.map((v) => {
          const r = v.latest_reading && !v.latest_reading.replay ? v.latest_reading : null;
          const q = r?.discharge_peak ?? null;
          const w = v.thresholds?.watch ?? null;
          const riverPct = q !== null && w ? Math.round((q / w) * 100) : null;
          const rain = r?.rain_24h_mm ?? null;
          return (
            <li key={v.id} className="clr-row">
              <Link to={`/village/${v.id}`} className="clr-name">
                <span lang="hi">{v.name_hi}</span> <span className="muted">· {v.name}</span>
              </Link>
              {r ? (
                <>
                  <Headroom
                    label={t('live.clear.river')}
                    pct={riverPct}
                    value={
                      riverPct === null
                        ? '—'
                        : t('live.clear.river.val', { pct: riverPct, q: fmtNumber(q, lang, 2), w: fmtNumber(w, lang, 2) })
                    }
                  />
                  <Headroom
                    label={t('live.clear.rain')}
                    pct={rain === null ? null : (rain / RAIN_WATCH_MM) * 100}
                    value={rain === null ? '—' : `${fmtNumber(rain, lang, 1)} / ${fmtNumber(RAIN_WATCH_MM, lang, 1)} mm`}
                  />
                </>
              ) : (
                <p className="small muted">{t('live.clear.noreading')}</p>
              )}
            </li>
          );
        })}
      </ul>
      <div className="clr-links">
        <Link to="/#story" className="btn btn-ghost">
          {t('live.clear.story')} <ArrowRight aria-hidden="true" />
        </Link>
        <Link to="/impact" className="btn btn-ghost">
          {t('live.clear.impact')} <ArrowRight aria-hidden="true" />
        </Link>
      </div>
    </section>
  );
}
