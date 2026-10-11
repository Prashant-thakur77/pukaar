import { useState } from 'react';
import { CalendarClock, CheckCircle2, Circle, Sprout } from 'lucide-react';
import { api, ApiError } from '../api';
import { useT } from '../i18n';
import { fmtDate, fmtNumber, fmtTime } from '../lib/format';
import { canTickChecklist, isGetReady, pct, withItem } from '../lib/readiness';
import { useAuth } from '../store';
import type { Checklist, Readiness, SoilView } from '../types';
import { Reveal } from './Reveal';

/** Ring showing done / total. */
export function ProgressRing({ done, total, label }: { done: number; total: number; label: string }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const frac = total > 0 ? done / total : 0;
  return (
    <svg className="ring" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label={label}>
      <circle className="ring-track" cx="32" cy="32" r={r} />
      {frac > 0 && <circle className="ring-fill" cx="32" cy="32" r={r} strokeDasharray={`${c * frac} ${c}`} transform="rotate(-90 32 32)" />}
      <text x="32" y="37" textAnchor="middle" className="ring-text">
        {done}/{total}
      </text>
    </svg>
  );
}

/** The soft "get ready" banner from the 7-day river outlook. Never an alert. */
function ReadinessBanner({ readiness }: { readiness: Readiness | null | undefined }) {
  const { t, lang } = useT();
  const ready = isGetReady(readiness);
  const ratio = readiness?.peak_vs_watch_ratio;
  return (
    <div className={`ready-banner${ready ? ' is-ready' : ''}`} role={ready ? 'status' : undefined}>
      <CalendarClock aria-hidden="true" />
      <div>
        <p className="ready-state">
          <strong>{ready ? t('ready.get') : readiness?.available === false || !readiness ? t('ready.unavailable') : t('ready.none')}</strong>
          {readiness?.replay && <span className="chip chip-muted">{t('ready.replay')}</span>}
        </p>
        {ready && readiness ? (
          <p>
            {t('ready.get.lead', {
              d: fmtNumber(readiness.horizon_days ?? 0, lang),
              day: fmtDate(readiness.peak_day, lang),
              r: fmtNumber(ratio ?? 0, lang, 2),
            })}
          </p>
        ) : (
          ratio != null && <p className="small muted">{t('ready.none.lead', { r: fmtNumber(ratio, lang, 2) })}</p>
        )}
        <p className="small muted">{t('ready.soft')}</p>
        {readiness?.source && <p className="small muted">{readiness.source}</p>}
      </div>
    </div>
  );
}

function ChecklistPanel({ villageId, initial }: { villageId: string; initial: Checklist }) {
  const { t, lang, other } = useT();
  const user = useAuth((s) => s.user);
  const signedIn = Boolean(useAuth((s) => s.token));
  const editable = signedIn && canTickChecklist(user, villageId);
  const [list, setList] = useState<Checklist>(initial);
  const [seen, setSeen] = useState<Checklist>(initial);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Polling brings fresh server state; take it unless a save is in flight.
  if (initial !== seen && !busy) {
    setSeen(initial);
    setList(initial);
  }

  async function toggle(item: string, done: boolean) {
    setBusy(item);
    setError(null);
    setList((c) => withItem(c, item, done));
    try {
      setList(await api.setChecklist(villageId, item, done));
    } catch (err) {
      setList((c) => withItem(c, item, !done));
      const e = err as ApiError;
      setError(lang === 'hi' && e?.messageHi ? e.messageHi : e?.isDenied ? e.messageEn : t('ready.save.error'));
    } finally {
      setBusy(null);
    }
  }

  const label = t('ready.progress', { d: fmtNumber(list.done, lang), n: fmtNumber(list.total, lang) });
  return (
    <div className="checklist">
      <div className="checklist-head">
        <ProgressRing done={list.done} total={list.total} label={label} />
        <div>
          <h3>{t('ready.checklist')}</h3>
          <p className="small muted">{label}</p>
        </div>
      </div>
      <ul className="check-items" aria-label={t('ready.checklist')}>
        {list.items.map((i) => {
          const main = lang === 'hi' ? i.label_hi : i.label_en;
          const sub = other === 'hi' ? i.label_hi : i.label_en;
          return (
            <li key={i.item} className={i.done ? 'is-done' : undefined}>
              {editable ? (
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={i.done}
                    disabled={busy === i.item}
                    onChange={(e) => void toggle(i.item, e.target.checked)}
                  />
                  <span className="check-text">
                    <span lang={lang}>{main}</span>
                    <span className="small muted" lang={other}>{sub}</span>
                  </span>
                </label>
              ) : (
                <div className="check-row">
                  {i.done ? <CheckCircle2 aria-hidden="true" className="check-icon ok-icon" /> : <Circle aria-hidden="true" className="check-icon" />}
                  <span className="check-text">
                    <span lang={lang}>{main}</span>
                    <span className="small muted" lang={other}>{sub}</span>
                  </span>
                  <span className="sr-only">{i.done ? '✓' : '—'}</span>
                </div>
              )}
              {i.done && i.done_by && (
                <span className="check-by small muted">{t('ready.done.by', { u: i.done_by, t: fmtTime(i.done_at, lang) })}</span>
              )}
            </li>
          );
        })}
      </ul>
      {error && (
        <p className="small bad-text" role="alert">
          {error}
        </p>
      )}
      {!editable && <p className="small muted">{t('ready.readonly')}</p>}
    </div>
  );
}

export function ReadinessCard({ villageId, readiness, checklist }: { villageId: string; readiness?: Readiness | null; checklist?: Checklist | null }) {
  return (
    <Reveal className="card ready-card">
      <ReadinessBanner readiness={readiness} />
      {checklist && checklist.items.length > 0 && <ChecklistPanel villageId={villageId} initial={checklist} />}
    </Reveal>
  );
}

/** Evidence card: root-zone soil saturation S on the village's own range, and the modifier state. */
export function SoilCard({ soil }: { soil: SoilView | null | undefined }) {
  const { t, lang } = useT();
  const s = soil?.saturation ?? null;
  return (
    <Reveal className="ev-card ev-wide ev-soil" delay={100}>
      <header className="ev-head">
        <Sprout aria-hidden="true" />
        <h3>{t('soil.title')}</h3>
        {soil?.applied && <span className="chip chip-warn">{t('soil.applied', { f: fmtNumber(soil.factor, lang, 2) })}</span>}
      </header>
      {!soil || s == null ? (
        <p className="muted">{t('soil.none')}</p>
      ) : (
        <>
          <p className="ev-value">
            {fmtNumber(s, lang, 2)} <span>S · {fmtNumber(soil.moisture_root, lang, 3)} m³/m³</span>
          </p>
          <div
            className={`soil-bar${s >= soil.saturated_at ? ' is-wet' : ''}`}
            role="meter"
            aria-valuemin={0}
            aria-valuemax={1}
            aria-valuenow={s}
            aria-label={`${t('soil.sat')}: ${fmtNumber(s, lang, 2)}`}
          >
            <span className="soil-zone" style={{ left: pct(soil.saturated_at), width: `calc(100% - ${pct(soil.saturated_at)})` }} />
            <span className="soil-fill" style={{ width: pct(s) }} />
            <span className="soil-mark" style={{ left: pct(soil.saturated_at) }} title={t('soil.mark')} />
          </div>
          <div className="soil-scale small muted">
            <span>{t('soil.dry', { v: fmtNumber(soil.dry, lang, 2) })}</span>
            <span>{t('soil.wet', { v: fmtNumber(soil.wet, lang, 2) })}</span>
          </div>
          <p className="soil-legend small muted">
            <span className="soil-key" aria-hidden="true" /> {t('soil.mark')}
          </p>
          <p className="small">
            <strong>
              {soil.state === 'applied'
                ? t('soil.applied', { f: fmtNumber(soil.factor, lang, 2) })
                : soil.state === 'off'
                  ? soil.factor_if_on < 1
                    ? t('soil.off', { f: fmtNumber(soil.factor_if_on, lang, 2) })
                    : t('soil.off.below')
                  : t('soil.below')}
            </strong>
          </p>
          <p className="small muted">{t('soil.lead')}</p>
          {!soil.calibrated && <p className="small muted">{t('soil.default')}</p>}
        </>
      )}
      <p className="small muted">{t('soil.never')}</p>
      {soil?.at && <p className="ev-sweep small">{t('village.ev.latest', { t: fmtTime(soil.at, lang) })}</p>}
    </Reveal>
  );
}
