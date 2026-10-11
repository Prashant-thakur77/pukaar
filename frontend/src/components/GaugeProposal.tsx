import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Check, Info, LoaderCircle, RefreshCw, Sigma } from 'lucide-react';
import { api, ApiError } from '../api';
import { usePoll } from '../hooks/usePoll';
import { levelWord, useT } from '../i18n';
import { fmtDate, fmtNumber } from '../lib/format';
import { exceedanceX, niceStep } from '../lib/gaugeLearn';
import type { GaugeProposal } from '../types';

const LEVELS = ['watch', 'warning', 'critical'] as const;

/** Percentile curve of the gauge's own record on an exceedance axis, with current and proposed lines. */
function PercentileChart({ p }: { p: GaugeProposal }) {
  const { t, lang } = useT();
  // One SVG unit = one CSS pixel, so labels stay readable from a phone to a desktop.
  const box = useRef<HTMLElement>(null);
  const [W, setW] = useState(640);
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(300, Math.min(760, Math.round(e.contentRect.width)))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const curve = p.curve ?? [];
  if (curve.length < 2 || !p.proposed) return null;
  const narrow = W < 480;
  const H = narrow ? 220 : 260;
  const L = 40;
  const R = narrow ? 92 : 112;
  const T = 14;
  const B = 34;
  const cur = p.current;
  const ys = [...curve.map((c) => c.cm), ...LEVELS.map((l) => p.proposed![`${l}_cm`]), ...(cur ? LEVELS.map((l) => cur[`${l}_cm`]) : [])];
  const step = niceStep(Math.max(...ys) - Math.min(0, ...ys));
  const yMin = Math.floor(Math.min(...ys, 0) / step) * step;
  const yMax = Math.ceil((Math.max(...ys) * 1.04) / step) * step;
  const xMax = exceedanceX(100);
  const x = (pct: number) => L + (exceedanceX(pct) / xMax) * (W - L - R);
  const y = (cm: number) => T + (1 - (cm - yMin) / (yMax - yMin || 1)) * (H - T - B);
  const d = curve.map((c, i) => `${i ? 'L' : 'M'}${x(c.p).toFixed(1)},${y(c.cm).toFixed(1)}`).join(' ');
  const yTicks: number[] = [];
  for (let v = yMin; v <= yMax + 1e-6; v += step) yTicks.push(v);
  const xTicks = narrow ? [0, 90, 99, 100] : [0, 50, 90, 99, 100];
  // Keep direct labels apart when two proposed lines sit close together.
  const labelY: Record<string, number> = {};
  let last = Infinity;
  for (const l of LEVELS) {
    const yy = Math.min(y(p.proposed[`${l}_cm`]), last - 14);
    labelY[l] = yy;
    last = yy;
  }
  return (
    <figure className="gp-chart" ref={box}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t('learn.chart.aria', { n: curve.length })}>
        {yTicks.map((v) => (
          <g key={v} className="gp-grid">
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} />
            <text x={L - 8} y={y(v) + 4} textAnchor="end">
              {fmtNumber(v, lang, 0)}
            </text>
          </g>
        ))}
        {xTicks.map((v) => (
          <text key={v} className="gp-axis" x={x(v)} y={H - 12} textAnchor="middle">
            p{v}
          </text>
        ))}
        <text className="gp-axis" x={L} y={T - 2}>
          cm
        </text>
        {cur &&
          LEVELS.map((l) => (
            <g key={`c-${l}`} className={`gp-line is-current lv-${l}`}>
              <line x1={L} x2={W - R} y1={y(cur[`${l}_cm`])} y2={y(cur[`${l}_cm`])} />
            </g>
          ))}
        {LEVELS.map((l) => (
          <g key={`p-${l}`} className={`gp-line lv-${l}`}>
            <line x1={L} x2={W - R} y1={y(p.proposed![`${l}_cm`])} y2={y(p.proposed![`${l}_cm`])} />
            <text x={W - R + 8} y={labelY[l] + 4}>
              {levelWord(l, lang)} {fmtNumber(p.proposed![`${l}_cm`], lang, 0)}
            </text>
          </g>
        ))}
        <path d={d} className="gp-curve" />
        {curve.map((c) => (
          <g key={c.p} className="gp-pt">
            <circle cx={x(c.p)} cy={y(c.cm)} r={10} className="gp-hit">
              <title>{`p${c.p}: ${fmtNumber(c.cm, lang, 1)} cm`}</title>
            </circle>
            {[p.percentiles.watch, p.percentiles.warning, p.percentiles.critical].includes(c.p) && <circle cx={x(c.p)} cy={y(c.cm)} r={4.5} className="gp-dot" />}
          </g>
        ))}
      </svg>
      <figcaption className="small muted">{t('learn.chart.caption')}</figcaption>
    </figure>
  );
}

export function GaugeProposalPanel({ villageId, canAccept, onAccepted }: { villageId: string; canAccept: boolean; onAccepted: () => void }) {
  const { t, lang } = useT();
  // Readings arrive every minute; recompute on demand rather than on a timer.
  const { data: p, error, loading, refresh } = usePoll(() => api.gaugeProposal(villageId), [villageId], 0);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const load = () => void refresh();
  const err = saveErr ?? (error ? (lang === 'hi' && error.messageHi) || error.messageEn : null);

  async function accept() {
    if (!p?.proposed) return;
    if (!window.confirm(t('learn.accept.confirm'))) return;
    setSaving(true);
    setSaveErr(null);
    try {
      await api.setGaugeThresholds(villageId, { ...p.proposed, from_proposal: true });
      setDone(t('learn.accepted'));
      onAccepted();
      load();
    } catch (e) {
      const ae = e instanceof ApiError ? e : new ApiError(0, null);
      setSaveErr((lang === 'hi' && ae.messageHi) || ae.messageEn);
      if (ae.status === 409) load();
    } finally {
      setSaving(false);
    }
  }

  const note = p ? (lang === 'hi' ? p.note_hi : p.note_en) : null;
  const same =
    p?.proposed && p.current && LEVELS.every((l) => p.proposed![`${l}_cm`] === p.current![`${l}_cm`]);
  return (
    <section className="gp-panel" aria-labelledby="gp-h">
      <header className="gp-head">
        <Sigma aria-hidden="true" />
        <h4 id="gp-h">{p && p.status === 'ready' ? t('learn.title', { n: fmtNumber(p.basis.days, lang, 1) }) : t('learn.title.short')}</h4>
        <button type="button" className="icon-btn" onClick={load} aria-label={t('learn.reload')} disabled={loading}>
          {loading ? <LoaderCircle className="spin" aria-hidden="true" /> : <RefreshCw aria-hidden="true" />}
        </button>
      </header>
      {err && (
        <p className="small bad-text" role="alert">
          {err}
        </p>
      )}
      {done && (
        <p className="small ok-text" role="status">
          <Check aria-hidden="true" className="inline-icon" /> {done}
        </p>
      )}
      {p && (
        <>
          <p className="small muted">
            {t('learn.basis', {
              r: fmtNumber(p.basis.readings, lang),
              d: fmtNumber(p.basis.days, lang, 1),
              from: fmtDate(p.basis.from, lang),
              to: fmtDate(p.basis.to, lang),
            })}
            {p.basis.excluded ? ` · ${t('learn.excluded', { n: fmtNumber(p.basis.excluded, lang) })}` : ''}
            {p.basis.simulated && <span className="chip chip-sm chip-warn"> {t('gauge.sim')}</span>}
          </p>
          {p.status === 'ready' && p.proposed ? (
            <>
              <PercentileChart p={p} />
              <div className="table-wrap" tabIndex={0} role="region" aria-label={t('learn.table')}>
                <table className="data-table compact stack-sm gp-table">
                  <thead>
                    <tr>
                      <th scope="col">{t('learn.col.level')}</th>
                      <th scope="col">{t('learn.col.now')}</th>
                      <th scope="col">{t('learn.col.proposed')}</th>
                      <th scope="col">{t('learn.col.raw')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {LEVELS.map((l) => {
                      const adj = p.adjustments?.find((a) => a.level === l);
                      return (
                        <tr key={l}>
                          <th scope="row">
                            <span className={`gp-swatch lv-${l}`} aria-hidden="true" /> {levelWord(l, lang)}
                          </th>
                          <td data-label={t('learn.col.now')}>{p.current ? `${fmtNumber(p.current[`${l}_cm`], lang, 0)} cm` : '—'}</td>
                          <td data-label={t('learn.col.proposed')}>
                            <strong>{fmtNumber(p.proposed![`${l}_cm`], lang, 0)} cm</strong>
                            {adj && <span className="small muted"> · {t('learn.floor', { r: adj.rule })}</span>}
                          </td>
                          <td className="small" data-label={t('learn.col.raw')}>
                            p{p.percentiles[l]} = {fmtNumber(p.raw![l], lang, 1)} cm
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="small muted">
                {t('learn.rule', { b: fmtNumber(p.baseline_cm ?? 0, lang, 1), m: p.baseline_rule ?? '', s: fmtNumber(p.min_separation_cm ?? 0, lang, 0) })}
              </p>
            </>
          ) : null}
          {note && (
            <p className="gp-note small" role="note">
              <Info aria-hidden="true" /> {note}
            </p>
          )}
          {p.current && (
            <p className="small muted">
              {p.current.set_by ? t('learn.current.source', { s: p.current.source, u: p.current.set_by }) : t('learn.current.seeded', { s: p.current.source })}
            </p>
          )}
          <h5 className="gp-faults-h">{t('learn.faults')}</h5>
          {p.faults.length === 0 ? (
            <p className="small muted">{t('learn.faults.none')}</p>
          ) : (
            <ul className="gp-faults">
              {p.faults.map((f) => (
                <li key={f.kind} className={`gp-fault is-${f.severity}`}>
                  {f.severity === 'warn' ? <AlertTriangle aria-hidden="true" /> : <Info aria-hidden="true" />}
                  <span>{lang === 'hi' ? f.message_hi : f.message_en}</span>
                </li>
              ))}
            </ul>
          )}
          {p.status === 'ready' && p.proposed && (
            <div className="gp-actions">
              {canAccept ? (
                <button type="button" className="btn btn-sm btn-accent" disabled={saving || Boolean(same)} onClick={() => void accept()}>
                  {saving ? <LoaderCircle className="spin" aria-hidden="true" /> : <Check aria-hidden="true" />} {same ? t('learn.same') : t('learn.accept')}
                </button>
              ) : (
                <p className="small muted">{t('learn.officer.only')}</p>
              )}
              <p className="small muted">{t('learn.never.auto')}</p>
            </div>
          )}
        </>
      )}
    </section>
  );
}
