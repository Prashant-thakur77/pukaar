import { useEffect, useMemo, useRef, useState } from 'react';
import { Camera, Check, Eye, EyeOff, ImagePlus, LoaderCircle, Ruler, RotateCcw, Save, X } from 'lucide-react';
import { api, ApiError } from '../api';
import { levelWord, useT } from '../i18n';
import { forgetStaffGauges, useStaffGauges } from '../hooks/useStaffGauges';
import { compressPhoto } from '../lib/photo';
import { buildMarks, levelForMark, marksTopFirst, nearestMark, type Scheme } from '../lib/staffGauge';
import { fmtTime } from '../lib/format';
import type { Level, NewStaffGauge, PublicStaffReading, Report, StaffGauge, StaffMark, StaffPoint } from '../types';

/* ------------------------------------------------------------------------------------------
 * The scale drawn on the reference photo. Coordinates are 0..1 of the photo, so the overlay
 * sits in a box with the photo's own aspect ratio and stretches with it.
 * ---------------------------------------------------------------------------------------- */

interface ScaleProps {
  photoUrl: string | null;
  alt: string;
  marks: StaffMark[];
  top?: StaffPoint | null;
  bottom?: StaffPoint | null;
  thresholds?: { watch_at: number | null; warning_at: number | null; critical_at: number | null };
  chosen?: number | null;
  /** A second mark (the officer's) shown beside the villager's. */
  confirmed?: number | null;
  onPick?: (m: StaffMark) => void;
  onTap?: (p: StaffPoint) => void;
  className?: string;
}

export function StaffScale({ photoUrl, alt, marks, top, bottom, thresholds, chosen, confirmed, onPick, onTap, className }: ScaleProps) {
  const [ratio, setRatio] = useState(4 / 3);
  const box = useRef<HTMLDivElement>(null);
  const sorted = useMemo(() => [...marks].sort((a, b) => a.value - b.value), [marks]);
  const lo = sorted[0];
  const hi = sorted[sorted.length - 1];
  const a = bottom ?? (lo ? { x: lo.x, y: lo.y } : null);
  const b = top ?? (hi ? { x: hi.x, y: hi.y } : null);
  const every = sorted.length > 13 ? 2 : 1;
  const interactive = Boolean(onPick || onTap);

  function tap(e: React.PointerEvent<HTMLDivElement>) {
    if (!interactive || !box.current) return;
    const r = box.current.getBoundingClientRect();
    const p = { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) };
    if (onTap) onTap(p);
    else if (onPick) {
      const m = nearestMark(marks, p.y);
      if (m) onPick(m);
    }
  }

  return (
    <div
      ref={box}
      className={`sg-scale${interactive ? ' is-tappable' : ''}${className ? ` ${className}` : ''}`}
      style={{ aspectRatio: String(ratio) }}
      onPointerUp={tap}
    >
      {photoUrl ? (
        <img
          src={photoUrl}
          alt={alt}
          draggable={false}
          onLoad={(e) => {
            const i = e.currentTarget;
            if (i.naturalWidth && i.naturalHeight) setRatio(i.naturalWidth / i.naturalHeight);
          }}
        />
      ) : (
        <div className="sg-noimg" aria-hidden="true" />
      )}
      <svg className="sg-overlay" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        {a && b && <line className="sg-rod" x1={a.x * 100} y1={a.y * 100} x2={b.x * 100} y2={b.y * 100} vectorEffect="non-scaling-stroke" />}
        {sorted.map((m) => {
          const lv = thresholds ? levelForMark(thresholds, m.value) : 'normal';
          const pick = m.value === chosen || m.value === confirmed;
          return (
            <line
              key={m.value}
              className={`sg-tick lv-${lv}${pick ? ' is-picked' : ''}`}
              x1={m.x * 100 - (pick ? 9 : 3.5)}
              x2={m.x * 100 + (pick ? 9 : 3.5)}
              y1={m.y * 100}
              y2={m.y * 100}
              vectorEffect="non-scaling-stroke"
            />
          );
        })}
        {/* the two taps, shown while drawing the scale */}
        {onTap !== undefined || (top && !bottom) ? (
          <>
            {top && <circle className="sg-tap" cx={top.x * 100} cy={top.y * 100} r={1.6} vectorEffect="non-scaling-stroke" />}
            {bottom && <circle className="sg-tap" cx={bottom.x * 100} cy={bottom.y * 100} r={1.6} vectorEffect="non-scaling-stroke" />}
          </>
        ) : null}
      </svg>
      {sorted.map((m, i) => {
        const isChosen = m.value === chosen;
        const isConfirmed = m.value === confirmed;
        if (!isChosen && !isConfirmed && i % every !== 0 && i !== sorted.length - 1) return null;
        const left = m.x > 0.7;
        // On a small photo only the lowest mark, the threshold marks and the chosen ones keep a label.
        const key = i === 0 || [thresholds?.watch_at, thresholds?.warning_at, thresholds?.critical_at].includes(m.value);
        return (
          <span
            key={m.value}
            className={`sg-label${isChosen ? ' is-chosen' : ''}${isConfirmed ? ' is-confirmed' : ''}${left ? ' to-left' : ''}${key || isChosen || isConfirmed ? '' : ' is-minor'}`}
            style={{ left: `${m.x * 100}%`, top: `${m.y * 100}%` }}
          >
            {m.label}
          </span>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------------------------------
 * Big-touch-target picker: one button per mark, highest first.
 * ---------------------------------------------------------------------------------------- */

export function MarkPicker({ gauge, value, onChange, compact = false, label }: { gauge: StaffGauge; value: number | null; onChange: (v: number) => void; compact?: boolean; label: string }) {
  const { lang } = useT();
  return (
    <div className={`sg-picker${compact ? ' is-compact' : ''}`} role="radiogroup" aria-label={label}>
      {marksTopFirst(gauge.marks).map((m) => {
        const lv: Level = levelForMark(gauge, m.value);
        const on = value === m.value;
        return (
          <button key={m.value} type="button" role="radio" aria-checked={on} className={`sg-pick lv-${lv}${on ? ' is-on' : ''}`} onClick={() => onChange(m.value)}>
            <span className="sg-pick-mark">{m.label}</span>
            {lv !== 'normal' && <span className="sg-pick-lv">{levelWord(lv, lang)}</span>}
            {on && <Check aria-hidden="true" className="sg-pick-check" />}
          </button>
        );
      })}
    </div>
  );
}

function VisionNote({ gauge }: { gauge: StaffGauge }) {
  const { lang } = useT();
  return <p className="sg-vision small muted">{lang === 'hi' ? gauge.vision_note_hi : gauge.vision_note_en}</p>;
}

/* ------------------------------------------------------------------------------------------
 * Villager: "Compare with the marked rock" on the report page.
 * ---------------------------------------------------------------------------------------- */

export function StaffCompare({
  gauges,
  photoUrl,
  onTakePhoto,
  value,
  gaugeId,
  onChange,
}: {
  gauges: StaffGauge[];
  photoUrl: string | null;
  onTakePhoto: () => void;
  value: number | null;
  gaugeId: string | null;
  onChange: (gaugeId: string | null, value: number | null) => void;
}) {
  const { t, lang } = useT();
  const gauge = gauges.find((g) => g.id === gaugeId) ?? gauges[0];
  const name = lang === 'hi' && gauge.name_hi ? gauge.name_hi : gauge.name;
  return (
    <section className="sg-compare" aria-labelledby="sg-compare-h">
      <div className="sg-compare-head">
        <h2 id="sg-compare-h" className="h-sub">
          <Ruler aria-hidden="true" /> {t('staff.compare.title')}
        </h2>
        <button type="button" className="icon-btn" onClick={() => onChange(null, null)} aria-label={t('staff.compare.close')}>
          <X aria-hidden="true" />
        </button>
      </div>
      {gauges.length > 1 && (
        <div className="chip-row" role="group" aria-label={t('staff.compare.which')}>
          {gauges.map((g) => (
            <button key={g.id} type="button" className={`chip chip-btn${g.id === gauge.id ? ' is-on' : ''}`} aria-pressed={g.id === gauge.id} onClick={() => onChange(g.id, null)}>
              {lang === 'hi' && g.name_hi ? g.name_hi : g.name}
            </button>
          ))}
        </div>
      )}
      <p className="small">
        <strong>{name}</strong>
        {gauge.where && <span className="muted"> · {gauge.where}</span>}
      </p>
      <div className="sg-pair">
        <figure>
          <StaffScale photoUrl={gauge.photo_url} alt={t('staff.ref.alt', { n: name })} marks={gauge.marks} top={gauge.scale_top} bottom={gauge.scale_bottom} thresholds={gauge} chosen={value} onPick={(m) => onChange(gauge.id, m.value)} />
          <figcaption className="small muted">{t('staff.ref.caption')}</figcaption>
        </figure>
        <figure>
          {photoUrl ? (
            <div className="sg-scale sg-new">
              <img src={photoUrl} alt={t('report.photo.ready')} />
            </div>
          ) : (
            <button type="button" className="sg-take btn-press" onClick={onTakePhoto}>
              <Camera aria-hidden="true" />
              <span>{t('staff.take')}</span>
            </button>
          )}
          <figcaption className="small muted">{t('staff.new.caption')}</figcaption>
        </figure>
      </div>
      <p className="sg-ask" id="sg-ask">
        {t('staff.ask')}
      </p>
      <MarkPicker gauge={gauge} value={gauge.id === gaugeId ? value : null} onChange={(v) => onChange(gauge.id, v)} label={t('staff.ask')} />
      {value != null && !photoUrl && <p className="small warn-text">{t('staff.need.photo')}</p>}
      <VisionNote gauge={gauge} />
    </section>
  );
}

/* ------------------------------------------------------------------------------------------
 * Officer: reference vs new photo, the villager's mark, confirm / adjust / unreadable.
 * ---------------------------------------------------------------------------------------- */

export function StaffReview({ report, canEdit, onUpdated }: { report: Report; canEdit: boolean; onUpdated: (r: Report) => void }) {
  const { t, lang } = useT();
  const sr = report.staff_reading!;
  const { gauges: all } = useStaffGauges(report.village_id);
  const gauge = all?.find((g) => g.id === sr.gauge_id) ?? null;
  const confirmedValue = sr.status === 'confirmed' ? (sr.confirmed_value ?? null) : null;
  const [pick, setPick] = useState<number | null>(confirmedValue ?? sr.value);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function send(body: { value?: number | null; unreadable?: boolean }) {
    setBusy(true);
    setErr(null);
    try {
      onUpdated(await api.confirmStaffReading(report.id, body));
    } catch (e) {
      const ae = e instanceof ApiError ? e : new ApiError(0, null);
      setErr((lang === 'hi' && ae.messageHi) || ae.messageEn);
    } finally {
      setBusy(false);
    }
  }

  const pickLabel = gauge?.marks.find((m) => m.value === pick)?.label ?? '';
  const status =
    sr.status === 'confirmed'
      ? t('staff.status.confirmed', { m: sr.confirmed_mark ?? '', u: sr.confirmed_by ?? '', t: fmtTime(sr.confirmed_at ?? null, lang) })
      : sr.status === 'unreadable'
        ? t('staff.status.unreadable', { u: sr.confirmed_by ?? '' })
        : t('staff.status.unconfirmed');
  return (
    <div className={`sg-review is-${sr.status}`}>
      <p className="sg-review-head">
        <Ruler aria-hidden="true" /> <strong>{t('staff.review.title', { n: sr.gauge_name || gauge?.name || '' })}</strong>
        <span className="chip chip-sm">{t('staff.review.villager', { m: sr.mark })}</span>
        <span className={`chip chip-sm ${sr.status === 'confirmed' ? 'chip-good' : sr.status === 'unreadable' ? 'chip-muted' : 'chip-pending'}`}>{status}</span>
        {sr.status === 'confirmed' && sr.confirmed_level && sr.confirmed_level !== 'normal' && (
          <span className={`chip chip-sm lv-chip lv-${sr.confirmed_level}`}>{levelWord(sr.confirmed_level, lang)}</span>
        )}
      </p>
      {gauge ? (
        <div className="sg-pair">
          <figure>
            <StaffScale
              photoUrl={gauge.photo_url}
              alt={t('staff.ref.alt', { n: gauge.name })}
              marks={gauge.marks}
              top={gauge.scale_top}
              bottom={gauge.scale_bottom}
              thresholds={gauge}
              chosen={canEdit ? pick : sr.value}
              confirmed={confirmedValue}
              onPick={canEdit ? (m) => setPick(m.value) : undefined}
            />
            <figcaption className="small muted">{t('staff.ref.caption.officer')}</figcaption>
          </figure>
          <figure>
            {report.photo_url ? (
              <div className="sg-scale sg-new">
                <img src={report.photo_url} alt={t('staff.new.alt')} loading="lazy" />
              </div>
            ) : (
              <p className="small muted">{t('staff.no.photo')}</p>
            )}
            <figcaption className="small muted">{t('staff.new.caption.officer', { t: fmtTime(report.created_at, lang) })}</figcaption>
          </figure>
        </div>
      ) : (
        <p className="small muted">{all == null ? t('state.loading') : t('staff.gauge.missing')}</p>
      )}
      {canEdit && gauge && (
        <>
          <MarkPicker gauge={gauge} value={pick} onChange={setPick} compact label={t('staff.review.pick')} />
          <div className="sg-review-actions">
            <button type="button" className="btn btn-sm btn-accent" disabled={busy || pick == null || pick === confirmedValue} onClick={() => void send({ value: pick })}>
              {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <Check aria-hidden="true" />}
              {pick === confirmedValue
                ? t('staff.review.done', { m: pickLabel })
                : pick === sr.value
                  ? t('staff.review.confirm', { m: pickLabel })
                  : t('staff.review.adjust', { m: pickLabel })}
            </button>
            <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={() => void send({ unreadable: true })}>
              <EyeOff aria-hidden="true" /> {t('staff.review.unreadable')}
            </button>
          </div>
          <p className="small muted">{t('staff.review.rule')}</p>
        </>
      )}
      {err && (
        <p className="small bad-text" role="alert">
          {err}
        </p>
      )}
      {gauge && <VisionNote gauge={gauge} />}
    </div>
  );
}

/* ------------------------------------------------------------------------------------------
 * Set-up: reference photo, two taps, marks, optional threshold marks. Officers and the
 * village's own pradhan (Cedar decides on the server).
 * ---------------------------------------------------------------------------------------- */

type Step = 'top' | 'bottom' | 'done';

export function StaffGaugeSetup({ villageId, onCreated, onCancel }: { villageId: string; onCreated: (g: StaffGauge) => void; onCancel: () => void }) {
  const { t, lang } = useT();
  const [photo, setPhoto] = useState<Blob | null>(null);
  const [busyPhoto, setBusyPhoto] = useState(false);
  const [name, setName] = useState('');
  const [nameHi, setNameHi] = useState('');
  const [where, setWhere] = useState('');
  const [top, setTop] = useState<StaffPoint | null>(null);
  const [bottom, setBottom] = useState<StaffPoint | null>(null);
  const [kind, setKind] = useState<'class' | 'cm'>('class');
  const [lo, setLo] = useState(-5);
  const [hi, setHi] = useState(5);
  const [span, setSpan] = useState(200);
  const [step, setStep] = useState(50);
  const [base, setBase] = useState(0);
  const [th, setTh] = useState<{ watch_at: number | null; warning_at: number | null; critical_at: number | null }>({ watch_at: null, warning_at: null, critical_at: null });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const url = useMemo(() => (photo ? URL.createObjectURL(photo) : null), [photo]);
  useEffect(() => () => void (url && URL.revokeObjectURL(url)), [url]);

  const tapStep: Step = !top ? 'top' : !bottom ? 'bottom' : 'done';
  const scheme: Scheme = kind === 'class' ? { kind: 'class', lo, hi } : { kind: 'cm', spanCm: span, stepCm: step, baseCm: base };
  const marks = top && bottom ? buildMarks(top, bottom, scheme) : [];
  const tooMany = marks.length > 41;
  const canSave = Boolean(photo && name.trim() && top && bottom && marks.length >= 2 && !tooMany && !saving);

  async function onFile(f: File | undefined) {
    if (!f) return;
    setBusyPhoto(true);
    try {
      setPhoto(await compressPhoto(f, 1600, 0.8));
    } catch {
      setPhoto(f);
    } finally {
      setBusyPhoto(false);
      setTop(null);
      setBottom(null);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  function onTap(p: StaffPoint) {
    if (tapStep === 'top') setTop(p);
    else if (tapStep === 'bottom') {
      if (top && p.y <= top.y) {
        setErr(t('staff.setup.below'));
        return;
      }
      setErr(null);
      setBottom(p);
    }
  }

  async function save() {
    if (!photo || !top || !bottom) return;
    setSaving(true);
    setErr(null);
    const meta: NewStaffGauge = { name: name.trim(), name_hi: nameHi.trim(), where: where.trim(), scale_top: top, scale_bottom: bottom, unit: kind, marks, ...th };
    try {
      const g = await api.createStaffGauge(villageId, meta, photo);
      forgetStaffGauges(villageId);
      onCreated(g);
    } catch (e) {
      const ae = e instanceof ApiError ? e : new ApiError(0, null);
      setErr((lang === 'hi' && ae.messageHi) || ae.messageEn);
    } finally {
      setSaving(false);
    }
  }

  const values = marks.map((m) => m.value);
  const thPick = (k: keyof typeof th) => (
    <label className="field sg-th">
      <span className="field-label">{levelWord(k.replace('_at', '') as Level, lang)}</span>
      <span className="select-wrap">
        <select value={th[k] ?? ''} onChange={(e) => setTh((o) => ({ ...o, [k]: e.target.value === '' ? null : Number(e.target.value) }))}>
          <option value="">{t('staff.setup.th.none')}</option>
          {[...values].reverse().map((v) => (
            <option key={v} value={v}>
              {marks.find((m) => m.value === v)?.label}
            </option>
          ))}
        </select>
      </span>
    </label>
  );

  return (
    <section className="sg-setup card" aria-labelledby="sg-setup-h">
      <div className="sg-compare-head">
        <h3 id="sg-setup-h" className="h-sub">
          <Ruler aria-hidden="true" /> {t('staff.setup.title')}
        </h3>
        <button type="button" className="icon-btn" onClick={onCancel} aria-label={t('common.close')}>
          <X aria-hidden="true" />
        </button>
      </div>
      <ol className="sg-steps small">
        <li>{t('staff.setup.s1')}</li>
        <li>{t('staff.setup.s2')}</li>
        <li>{t('staff.setup.s3')}</li>
      </ol>
      <div className="sg-setup-grid">
        <div>
          {url ? (
            <>
              <StaffScale photoUrl={url} alt={t('staff.setup.photo')} marks={marks} top={top} bottom={bottom} thresholds={th} onTap={tapStep === 'done' ? undefined : onTap} />
              <p className="sg-tapnote" role="status">
                {tapStep === 'top' ? t('staff.setup.tap.top') : tapStep === 'bottom' ? t('staff.setup.tap.bottom') : t('staff.setup.tap.done', { n: marks.length })}
              </p>
              <div className="chip-row">
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => (setTop(null), setBottom(null))} disabled={!top}>
                  <RotateCcw aria-hidden="true" /> {t('staff.setup.redraw')}
                </button>
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => fileRef.current?.click()}>
                  <ImagePlus aria-hidden="true" /> {t('staff.setup.other')}
                </button>
              </div>
            </>
          ) : (
            <button type="button" className="sg-take btn-press" onClick={() => fileRef.current?.click()} disabled={busyPhoto}>
              {busyPhoto ? <LoaderCircle className="spin" aria-hidden="true" /> : <Camera aria-hidden="true" />}
              <span>{t('staff.setup.photo')}</span>
            </button>
          )}
          <input ref={fileRef} type="file" accept="image/*" capture="environment" className="sr-only" tabIndex={-1} aria-hidden="true" onChange={(e) => void onFile(e.target.files?.[0])} />
        </div>
        <div className="sg-form">
          <label className="field">
            <span className="field-label">{t('staff.setup.name')}</span>
            <input value={name} onChange={(e) => setName(e.target.value.slice(0, 80))} placeholder="Big rock below the bridge" />
          </label>
          <label className="field">
            <span className="field-label">{t('staff.setup.name.hi')}</span>
            <input lang="hi" value={nameHi} onChange={(e) => setNameHi(e.target.value.slice(0, 80))} placeholder="पुल के नीचे बड़ा पत्थर" />
          </label>
          <label className="field">
            <span className="field-label">{t('staff.setup.where')}</span>
            <input value={where} onChange={(e) => setWhere(e.target.value.slice(0, 200))} placeholder={t('staff.setup.where.ph')} />
          </label>
          <fieldset className="sg-kind">
            <legend className="field-label">{t('staff.setup.scale')}</legend>
            <label>
              <input type="radio" name="sg-kind" checked={kind === 'class'} onChange={() => setKind('class')} /> {t('staff.setup.classes')}
            </label>
            <label>
              <input type="radio" name="sg-kind" checked={kind === 'cm'} onChange={() => setKind('cm')} /> {t('staff.setup.cm')}
            </label>
          </fieldset>
          {kind === 'class' ? (
            <div className="sg-nums">
              <label className="field">
                <span className="field-label">{t('staff.setup.lo')}</span>
                <input type="number" value={lo} onChange={(e) => setLo(Math.round(Number(e.target.value)))} />
              </label>
              <label className="field">
                <span className="field-label">{t('staff.setup.hi')}</span>
                <input type="number" value={hi} onChange={(e) => setHi(Math.round(Number(e.target.value)))} />
              </label>
            </div>
          ) : (
            <div className="sg-nums">
              <label className="field">
                <span className="field-label">{t('staff.setup.span')}</span>
                <input type="number" min={1} value={span} onChange={(e) => setSpan(Number(e.target.value))} />
              </label>
              <label className="field">
                <span className="field-label">{t('staff.setup.step')}</span>
                <input type="number" min={1} value={step} onChange={(e) => setStep(Number(e.target.value))} />
              </label>
              <label className="field">
                <span className="field-label">{t('staff.setup.base')}</span>
                <input type="number" value={base} onChange={(e) => setBase(Number(e.target.value))} />
              </label>
            </div>
          )}
          {tooMany && <p className="small warn-text">{t('staff.setup.toomany')}</p>}
          {marks.length >= 2 && (
            <fieldset className="sg-ths">
              <legend className="field-label">{t('staff.setup.th')}</legend>
              <p className="small muted">{t('staff.setup.th.lead')}</p>
              <div className="sg-nums">
                {thPick('watch_at')}
                {thPick('warning_at')}
                {thPick('critical_at')}
              </div>
            </fieldset>
          )}
          {err && (
            <p className="small bad-text" role="alert">
              {err}
            </p>
          )}
          <button type="button" className="btn btn-accent" disabled={!canSave} onClick={() => void save()}>
            {saving ? <LoaderCircle className="spin" aria-hidden="true" /> : <Save aria-hidden="true" />} {t('staff.setup.save')}
          </button>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------------------------------
 * Village page: the reference points, their recent readings, and set-up for staff.
 * ---------------------------------------------------------------------------------------- */

export function StaffGaugeList({ view, canManage, villageId, onChanged }: { view: { gauges: StaffGauge[]; readings: PublicStaffReading[] } | null | undefined; canManage: boolean; villageId: string; onChanged: () => void }) {
  const { t, lang } = useT();
  const [setup, setSetup] = useState(false);
  const [shown, setShown] = useState<string | null>(null);
  const gauges = view?.gauges ?? [];
  const readings = view?.readings ?? [];
  return (
    <div className="sg-list">
      {gauges.length === 0 && !setup && <p className="muted">{canManage ? t('staff.none.staff') : t('staff.none')}</p>}
      <ul className="sg-cards">
        {gauges.map((g) => {
          const mine = readings.filter((r) => r.gauge_id === g.id);
          const open = shown === g.id || gauges.length === 1;
          return (
            <li key={g.id} className="card sg-card">
              <div className="sg-card-head">
                <h3>{lang === 'hi' && g.name_hi ? g.name_hi : g.name}</h3>
                <span className="small muted">
                  {g.marks.length} {t('staff.marks')} · {g.marks[0]?.label} … {g.marks[g.marks.length - 1]?.label}
                </span>
                {gauges.length > 1 && (
                  <button type="button" className="btn btn-sm btn-ghost" aria-expanded={open} onClick={() => setShown(open ? null : g.id)}>
                    <Eye aria-hidden="true" /> {open ? t('common.less') : t('common.more')}
                  </button>
                )}
              </div>
              {g.where && <p className="small muted">{g.where}</p>}
              {open && <StaffScale photoUrl={g.photo_url} alt={t('staff.ref.alt', { n: g.name })} marks={g.marks} top={g.scale_top} bottom={g.scale_bottom} thresholds={g} />}
              <p className="small">
                {(['watch', 'warning', 'critical'] as const)
                  .filter((l) => g[`${l}_at`] != null)
                  .map((l) => `${levelWord(l, lang)} ≥ ${g.marks.find((m) => m.value === g[`${l}_at`])?.label}`)
                  .join(' · ') || t('staff.th.none')}
              </p>
              {mine.length > 0 && (
                <ul className="sg-readings">
                  {mine.slice(0, 4).map((r) => (
                    <li key={r.report_id}>
                      <span className="sg-reading-mark">{r.mark}</span>
                      <span className="small">
                        {fmtTime(r.at, lang)} ·{' '}
                        {r.status === 'confirmed' ? t('staff.reading.confirmed') : r.status === 'unreadable' ? t('staff.reading.unreadable') : t('staff.reading.unconfirmed')}
                      </span>
                      {r.level && r.level !== 'normal' && <span className={`chip chip-sm lv-chip lv-${r.level}`}>{levelWord(r.level, lang)}</span>}
                    </li>
                  ))}
                </ul>
              )}
              <VisionNote gauge={g} />
              {canManage && (
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  onClick={() => {
                    if (!window.confirm(t('staff.retire.confirm'))) return;
                    void api
                      .updateStaffGauge(villageId, g.id, { active: false })
                      .then(() => {
                        forgetStaffGauges(villageId);
                        onChanged();
                      })
                      .catch(() => undefined);
                  }}
                >
                  <X aria-hidden="true" /> {t('staff.retire')}
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {canManage &&
        (setup ? (
          <StaffGaugeSetup
            villageId={villageId}
            onCancel={() => setSetup(false)}
            onCreated={() => {
              setSetup(false);
              onChanged();
            }}
          />
        ) : (
          <button type="button" className="btn btn-ghost" onClick={() => setSetup(true)}>
            <Ruler aria-hidden="true" /> {t('staff.setup.open')}
          </button>
        ))}
    </div>
  );
}
