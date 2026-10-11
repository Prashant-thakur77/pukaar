/*
 * Before/after split view of the July 2023 Beas flood from Sentinel-2.
 * Images and scenes.json are baked by scripts/build_satellite.py into
 * public/satellite/2023/; nothing is fetched until the section is near.
 */
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { Satellite } from 'lucide-react';
import { useT } from '../i18n';
import { fmtDate, fmtNumber } from '../lib/format';
import { labelLeft, nextPos, posFromPointer, SAT_BASE, scenePair, type SatMeta, type SatScene } from '../lib/satellite';
import { EmptyState, Skeleton } from './States';

type Mode = 'rgb' | 'water';

function useNear<T extends Element>(): [React.RefObject<T | null>, boolean] {
  const ref = useRef<T | null>(null);
  // Without IntersectionObserver (old browsers, tests) load straight away.
  const [near, setNear] = useState(() => typeof IntersectionObserver === 'undefined');
  useEffect(() => {
    const el = ref.current;
    if (!el || near) return;
    const io = new IntersectionObserver((es) => es.some((e) => e.isIntersecting) && setNear(true), { rootMargin: '600px 0px' });
    io.observe(el);
    return () => io.disconnect();
  }, [near]);
  return [ref, near];
}

function Layer({ scene, mode, alt }: { scene: SatScene; mode: Mode; alt: string }) {
  return (
    <>
      <img className="sat-img" src={SAT_BASE + scene.true_colour} alt={alt} loading="lazy" decoding="async" draggable={false} />
      {mode === 'water' && <img className="sat-water" src={SAT_BASE + scene.water} alt="" loading="lazy" decoding="async" draggable={false} />}
    </>
  );
}

export function SatelliteCompare() {
  const { t, lang, pick } = useT();
  const [ref, near] = useNear<HTMLDivElement>();
  const [meta, setMeta] = useState<SatMeta | null | undefined>(undefined);
  const [pos, setPos] = useState(50);
  const [mode, setMode] = useState<Mode>('rgb');
  const [afterIx, setAfterIx] = useState(0);
  const frame = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  useEffect(() => {
    if (!near) return;
    let live = true;
    fetch(SAT_BASE + 'scenes.json')
      .then((r) => (r.ok ? (r.json() as Promise<SatMeta>) : null))
      .catch(() => null)
      .then((m) => live && setMeta(m));
    return () => {
      live = false;
    };
  }, [near]);

  const pair = scenePair(meta);
  const before = pair?.before;
  const after = pair?.afters[Math.min(afterIx, pair.afters.length - 1)];

  const moveTo = (clientX: number) => {
    const box = frame.current?.getBoundingClientRect();
    if (box) setPos(posFromPointer(clientX, box.left, box.width));
  };
  const onDown = (e: PointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    moveTo(e.clientX);
  };
  const onMove = (e: PointerEvent<HTMLDivElement>) => dragging.current && moveTo(e.clientX);
  const onUp = () => {
    dragging.current = false;
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const p = nextPos(pos, e.key, e.shiftKey);
    if (p == null) return;
    e.preventDefault();
    setPos(p);
  };

  const date = (s: SatScene) => fmtDate(s.date + 'T12:00:00Z', lang);

  return (
    <section className="band band-paper sat-band" aria-labelledby="sat-h">
      <div className="wrap" ref={ref}>
        <h2 id="sat-h" className="h-sec">
          <Satellite aria-hidden="true" /> {t('sat.title')}
        </h2>
        <p className="muted sat-lead">{t('sat.lead')}</p>

        {meta === undefined ? (
          <Skeleton height={360} className="sat-skel" />
        ) : !before || !after ? (
          <EmptyState title={t('sat.none')} body={meta?.reason ?? t('sat.none.body')} icon={<Satellite />} />
        ) : (
          <figure className="sat-figure">
            <div className="sat-controls">
              <div className="sat-seg" role="group" aria-label={t('sat.mode')}>
                {(['rgb', 'water'] as Mode[]).map((m) => (
                  <button key={m} type="button" className={`sat-opt${mode === m ? ' is-on' : ''}`} aria-pressed={mode === m} onClick={() => setMode(m)}>
                    {t(m === 'rgb' ? 'sat.mode.rgb' : 'sat.mode.water')}
                  </button>
                ))}
              </div>
              {pair.afters.length > 1 && (
                <div className="sat-seg" role="group" aria-label={t('sat.afterpick')}>
                  {pair.afters.map((a, i) => (
                    <button key={a.scene_id} type="button" className={`sat-opt${a === after ? ' is-on' : ''}`} aria-pressed={a === after} onClick={() => setAfterIx(i)}>
                      {date(a)}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div
              ref={frame}
              className={`sat-frame mode-${mode}`}
              style={{ aspectRatio: `${meta!.size[0]} / ${meta!.size[1]}`, ['--pos' as string]: `${pos}%` }}
              onPointerDown={onDown}
              onPointerMove={onMove}
              onPointerUp={onUp}
              onPointerCancel={onUp}
            >
              <div className="sat-layer">
                <Layer scene={before} mode={mode} alt={t('sat.alt', { d: date(before) })} />
              </div>
              <div className="sat-layer sat-after">
                <Layer scene={after} mode={mode} alt={t('sat.alt', { d: date(after) })} />
              </div>
              <span className="sat-tag sat-tag-l">
                {t('sat.before')} · {date(before)}
              </span>
              <span className="sat-tag sat-tag-r">
                {t('sat.after')} · {date(after)}
              </span>
              <ul className="sat-markers" aria-label={t('sat.places')}>
                {meta!.markers.map((m) => (
                  <li key={m.id} className={`sat-mk mk-${m.kind}${labelLeft(m, meta!.markers) ? ' mk-flip' : ''}`} style={{ left: `${m.x * 100}%`, top: `${m.y * 100}%` }}>
                    <i aria-hidden="true" />
                    <span>{pick({ hi: m.name_hi, en: m.name })}</span>
                  </li>
                ))}
              </ul>
              <div
                className="sat-handle"
                role="slider"
                tabIndex={0}
                aria-label={t('sat.slider')}
                aria-orientation="horizontal"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={pos}
                aria-valuetext={t('sat.valuetext', { p: Math.round(pos), b: date(before), a: date(after) })}
                onKeyDown={onKey}
              >
                <span className="sat-knob" aria-hidden="true">
                  ‹ ›
                </span>
              </div>
            </div>

            {mode === 'water' && (
              <p className="sat-legend small">
                <span>
                  <span className="sw sw-water" aria-hidden="true" /> {t('sat.legend.water')}
                </span>
                <span>
                  <span className="sw sw-cloud" aria-hidden="true" /> {t('sat.legend.cloud')}
                </span>
              </p>
            )}

            <figcaption className="sat-cap">
              <dl className="sat-scenes">
                {[before, after].map((s) => (
                  <div key={s.scene_id}>
                    <dt>{t(s.role === 'before' ? 'sat.before' : 'sat.after')}</dt>
                    <dd>
                      <strong>{date(s)}</strong>
                      {s.days_after_peak != null && <> · {t('sat.days', { n: s.days_after_peak })}</>}
                      <br />
                      <span className="small muted">
                        {t('sat.cloud', { c: fmtNumber(s.crop_cloud_pct, lang, 1), t: fmtNumber(s.tile_cloud_pct, lang, 1) })}
                      </span>
                      <br />
                      <a className="small sat-id" href={s.stac} target="_blank" rel="noreferrer">
                        <code>{s.scene_id}</code>
                      </a>
                    </dd>
                  </div>
                ))}
              </dl>
              <p className="caveat">
                {t('sat.caption', { d: date(after), n: after.days_after_peak ?? 0 })}
                {after.crop_cloud_pct > 0 && <> {t('sat.streak')}</>}
              </p>
              {after.water_area && (
                <p className="small muted">
                  {t('sat.area', {
                    b: fmtNumber(after.water_area.before_km2, lang, 1),
                    a: fmtNumber(after.water_area.after_km2, lang, 1),
                    c: fmtNumber(after.water_area.compared_km2, lang),
                  })}
                </p>
              )}
              <p className="small muted sat-attr">
                <a href={meta!.licence_url} target="_blank" rel="noreferrer">
                  {meta!.licence}
                </a>
                . {t('sat.source')}
              </p>
            </figcaption>
          </figure>
        )}
      </div>
    </section>
  );
}
