import { useState, type FormEvent } from 'react';
import { BellRing, CircleCheck, Clock3, HeartHandshake, LifeBuoy, LoaderCircle, ShieldCheck } from 'lucide-react';
import { api, ApiError } from '../../api';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { DeniedNote, EmptyState, ErrorState, Skeleton } from '../../components/States';
import { usePoll } from '../../hooks/usePoll';
import { CHANNELS } from '../../lib/live';
import { useT } from '../../i18n';
import { fmtAgo, fmtTime } from '../../lib/format';
import type { RollCall, RollCallBoard, Village } from '../../types';

/**
 * "Surakshit Hoon" roll-call board: who is safe, who needs help (first), who has not answered.
 * Names and times only; the API never sends phone numbers or chat ids.
 */
export function RollCallPanel({ villages, villageIds }: { villages: Village[]; villageIds: string[] | null }) {
  const { t } = useT();
  const list = usePoll(() => api.rollcalls(), [], 20000, { live: [CHANNELS.rollcall, CHANNELS.officer] });
  const [picked, setPicked] = useState<string | null>(null);
  const all = list.data ?? [];
  const selected = picked ?? all.find((r) => r.open)?.id ?? all[0]?.id ?? null;
  const own = villageIds ? villages.filter((v) => villageIds.includes(v.id)) : villages;

  return (
    <div className="rollcall">
      <p className="small muted rc-lead">{t('rollcall.lead')}</p>
      {list.loading && !list.data ? (
        <Skeleton lines={3} />
      ) : list.error && !list.data ? (
        list.error.isDenied ? <DeniedNote error={list.error} /> : <ErrorState error={list.error} onRetry={list.refresh} compact />
      ) : all.length === 0 ? (
        <EmptyState title={t('rollcall.none')} icon={<ShieldCheck aria-hidden="true" />} />
      ) : (
        <>
          {all.length > 1 && <RollCallPicker items={all} selected={selected} onPick={setPicked} />}
          {selected && <Board id={selected} onChanged={() => void list.refresh()} />}
        </>
      )}
      <OpenForm
        villages={own}
        onOpened={(id) => {
          setPicked(id);
          void list.refresh();
        }}
      />
    </div>
  );
}

function RollCallPicker({ items, selected, onPick }: { items: RollCall[]; selected: string | null; onPick: (id: string) => void }) {
  const { t, lang } = useT();
  return (
    <label className="field rc-pick">
      <span className="field-label">{t('rollcall.pick')}</span>
      <span className="select-wrap">
        <select value={selected ?? ''} onChange={(e) => onPick(e.target.value)}>
          {items.map((r) => (
            <option key={r.id} value={r.id}>
              {lang === 'hi' ? r.village_name_hi : r.village_name} · {fmtTime(r.opened_at, lang)} ·{' '}
              {r.open ? t('rollcall.state.open') : t('rollcall.state.closed')}
              {r.exercise ? ` · ${t('rollcall.exercise')}` : ''}
            </option>
          ))}
        </select>
      </span>
    </label>
  );
}

function Board({ id, onChanged }: { id: string; onChanged: () => void }) {
  const { t, lang } = useT();
  const { data, error, loading, refresh } = usePoll<RollCallBoard>(() => api.rollcall(id), [id], 15000, {
    live: [CHANNELS.rollcall, CHANNELS.officer],
    match: (e) => e.data.rollcall_id === id,
  });
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);

  if (loading && !data) return <Skeleton lines={4} />;
  if (error && !data) return error.isDenied ? <DeniedNote error={error} /> : <ErrorState error={error} onRetry={refresh} compact />;
  if (!data) return null;
  const rc = data.rollcall;
  const total = Math.max(rc.asked, 1);

  async function remind() {
    setBusy(true);
    setNote(null);
    try {
      const out = await api.remindRollcall(id);
      setNote({ ok: true, text: t('rollcall.remind.done', { n: out.reminded }) });
      void refresh();
      onChanged();
    } catch (er) {
      const e = er instanceof ApiError ? er : new ApiError(0, null);
      setNote({ ok: false, text: lang === 'hi' && e.messageHi ? e.messageHi : e.messageEn });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={`rc-board${rc.need_help > 0 ? ' has-help' : ''}`} aria-label={t('rollcall.title')}>
      <header className="rc-head">
        <h3 className="rc-village">
          <span lang="hi">{rc.village_name_hi}</span> <span className="muted">· {rc.village_name}</span>
        </h3>
        <span className={`chip ${rc.open ? 'chip-good' : 'chip-muted'}`}>{rc.open ? t('rollcall.state.open') : t('rollcall.state.closed')}</span>
        {rc.exercise && <span className="chip chip-warn">{t('rollcall.exercise')}</span>}
      </header>
      <p className="small muted">
        {rc.opened_by === 'system' ? t('rollcall.by.system') : t('rollcall.by.officer', { u: rc.opened_by_user ?? '' })} · {fmtAgo(rc.opened_at, lang)}
        {' · '}
        {rc.open ? t('rollcall.closes', { t: fmtTime(rc.closes_at, lang) }) : t('rollcall.closed.at', { t: fmtTime(rc.closes_at, lang) })}
      </p>

      <ul className="rc-counts" aria-label={t('rollcall.title')}>
        <li className="rc-count is-help">
          <span className="rc-num">{rc.need_help}</span>
          <span className="rc-label">
            <LifeBuoy aria-hidden="true" /> {t('rollcall.help')}
          </span>
        </li>
        <li className="rc-count is-safe">
          <span className="rc-num">{rc.safe}</span>
          <span className="rc-label">
            <CircleCheck aria-hidden="true" /> {t('rollcall.safe')}
          </span>
        </li>
        <li className="rc-count is-wait">
          <span className="rc-num">{rc.not_answered}</span>
          <span className="rc-label">
            <Clock3 aria-hidden="true" /> {t('rollcall.waiting')}
          </span>
        </li>
      </ul>
      <div className="rc-bar" aria-hidden="true">
        <span className="rc-bar-help" style={{ width: `${(rc.need_help / total) * 100}%` }} />
        <span className="rc-bar-safe" style={{ width: `${(rc.safe / total) * 100}%` }} />
      </div>

      <h4 className="h-sub rc-h-help">
        <LifeBuoy aria-hidden="true" /> {t('rollcall.help')} ({data.need_help.length})
      </h4>
      {data.need_help.length === 0 ? (
        <p className="small muted">{t('rollcall.none.help')}</p>
      ) : (
        <ul className="rc-list rc-list-help">
          {data.need_help.map((p, i) => (
            <li key={`${p.name}-${p.at}-${i}`}>
              <strong>{p.name}</strong>
              <span className="small">{fmtTime(p.at, lang)}</span>
              {p.simulated && <span className="chip chip-muted">{t('rollcall.simulated')}</span>}
              {p.note && <p className="rc-note">“{p.note}”</p>}
            </li>
          ))}
        </ul>
      )}

      <h4 className="h-sub">
        <Clock3 aria-hidden="true" /> {t('rollcall.waiting')} ({data.not_answered.length})
      </h4>
      {data.not_answered.length === 0 ? (
        <p className="small muted">{t('rollcall.everyone')}</p>
      ) : (
        <ul className="rc-list rc-list-wait">
          {data.not_answered.map((p, i) => (
            <li key={`${p.name}-${i}`}>
              <span>{p.name}</span>
              {p.demo && <span className="chip chip-muted">{t('rollcall.demo')}</span>}
              {p.failed && <span className="chip chip-bad">{t('rollcall.failed')}</span>}
            </li>
          ))}
        </ul>
      )}
      {rc.open && data.not_answered.length > 0 && (
        <div className="rc-remind">
          <button type="button" className="btn btn-ink btn-press" onClick={() => void remind()} disabled={busy}>
            {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <BellRing aria-hidden="true" />} {t('rollcall.remind')}
          </button>
          <span className="small muted">
            {t('rollcall.remind.rule')}
            {rc.last_reminded_at && ` · ${t('rollcall.remind.last', { t: fmtAgo(rc.last_reminded_at, lang) })}`}
          </span>
        </div>
      )}
      {note && (
        <p className={note.ok ? 'ok-text' : 'warn-text'} role="status">
          {note.text}
        </p>
      )}

      <h4 className="h-sub">
        <CircleCheck aria-hidden="true" /> {t('rollcall.safe')} ({data.safe.length})
      </h4>
      {data.safe.length > 0 && (
        <ul className="rc-list rc-list-safe">
          {data.safe.map((p, i) => (
            <li key={`${p.name}-${p.at}-${i}`}>
              <span>{p.name}</span>
              <span className="small muted">{fmtTime(p.at, lang)}</span>
              {p.simulated && <span className="chip chip-muted">{t('rollcall.simulated')}</span>}
            </li>
          ))}
        </ul>
      )}
      <p className="small muted rc-privacy">{t('rollcall.privacy')}</p>
    </section>
  );
}

function OpenForm({ villages, onOpened }: { villages: Village[]; onOpened: (id: string) => void }) {
  const { t, lang } = useT();
  const [villageId, setVillageId] = useState('');
  const [exercise, setExercise] = useState(true);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const v = villages.find((x) => x.id === villageId);

  async function open() {
    setBusy(true);
    setErr(null);
    try {
      const board = await api.openRollcall(villageId, exercise);
      setConfirm(false);
      onOpened(board.rollcall.id);
    } catch (er) {
      const e = er instanceof ApiError ? er : new ApiError(0, null);
      const existing = (e.detail as { rollcall_id?: string } | null)?.rollcall_id;
      setConfirm(false);
      if (e.isLate && existing) onOpened(existing);
      else setErr(e);
    } finally {
      setBusy(false);
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (villageId) setConfirm(true);
  };

  return (
    <form className="stack rc-open" onSubmit={submit}>
      <h3 className="h-sub">
        <HeartHandshake aria-hidden="true" /> {t('rollcall.open')}
      </h3>
      <label className="field">
        <span className="field-label">{t('rollcall.village')}</span>
        <span className="select-wrap">
          <select value={villageId} onChange={(e) => setVillageId(e.target.value)} required>
            <option value="">—</option>
            {villages.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name} · {x.name_hi}
              </option>
            ))}
          </select>
        </span>
      </label>
      <label className="check">
        <input type="checkbox" checked={exercise} onChange={(e) => setExercise(e.target.checked)} /> {t('rollcall.open.exercise')}
      </label>
      <button type="submit" className="btn btn-ghost btn-press" disabled={busy || !villageId}>
        <ShieldCheck aria-hidden="true" /> {t('rollcall.open')}
      </button>
      {err && (err.isDenied ? <DeniedNote error={err} /> : <ErrorState error={err} compact />)}
      <ConfirmDialog
        open={confirm}
        title={t('rollcall.open')}
        confirmLabel={t('common.confirm')}
        cancelLabel={t('common.cancel')}
        busy={busy}
        onConfirm={() => void open()}
        onCancel={() => setConfirm(false)}
      >
        <p>{t('rollcall.open.confirm', { v: v ? (lang === 'hi' ? v.name_hi : v.name) : villageId })}</p>
        {exercise && <p className="small muted">{t('rollcall.exercise')}</p>}
      </ConfirmDialog>
    </form>
  );
}
