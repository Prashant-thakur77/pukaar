import { useId, useState, type FormEvent, type ReactNode } from 'react';
import { Navigate, useSearchParams } from 'react-router-dom';
import { ChevronLeft, ChevronRight, LoaderCircle, UserCheck } from 'lucide-react';
import { api, ApiError } from '../../api';
import { Page } from './Sections';
import { DutyHandover } from './DutyHandover';
import { useConsole } from './consoleContext';
import { useMedia } from '../../hooks/useMedia';
import { DeniedNote, ErrorState, Skeleton } from '../../components/States';
import { usePoll } from '../../hooks/usePoll';
import { useT } from '../../i18n';
import { fmtNumber } from '../../lib/format';
import { DISTRICT_HI } from '../../lib/answerText';
import { addDays, approvalTimes, chainRole, dayLabel, emptyShifts, isCurrent, istClock, nobodyOnDuty, shiftWindow, todayIST, validUsername } from '../../lib/roster';
import { gapWord } from '../../lib/pilotTen';
import { useAuth } from '../../store';
import type { EscalationTitle, OnDuty, RosterDay, RosterShift, RosterView, ShiftId } from '../../types';
import '../../styles/console.css';

const SHIFTS: ShiftId[] = ['day', 'night'];

/** /roster: who approves alerts now, and the week's duty chart. Officers only (Cedar "officer-roster"). */
export default function RosterPage() {
  const token = useAuth((s) => s.token);
  if (!token) return <Navigate to="/login" replace state={{ from: '/console/roster' }} />;
  return <Roster />;
}

function Roster() {
  const { t } = useT();
  const [params, setParams] = useSearchParams();
  const c = useConsole();
  // The header's district, unless the link names one.
  const district = params.get('district') ?? c.district ?? '';
  const start = params.get('start') ?? todayIST();
  const poll = usePoll(() => api.roster({ district: district || undefined, start }), [district, start], 60000);
  const view = poll.data;
  const go = (next: { district?: string; start?: string }) => {
    const p: Record<string, string> = {};
    const d = next.district ?? district;
    const s = next.start ?? start;
    if (d) p.district = d;
    if (s !== todayIST()) p.start = s;
    setParams(p);
  };

  return (
    <Page title={t('roster.title')} lead={t('roster.lead')} wide>
      <div className="roster">
        {poll.loading && !view ? (
          <Skeleton lines={6} />
        ) : poll.error && !view ? (
          poll.error.isDenied ? <DeniedNote error={poll.error} /> : <ErrorState error={poll.error} onRetry={poll.refresh} />
        ) : view ? (
          <>
            <OnDutyNow view={view} onChanged={poll.refresh} />
            <DutyHandover district={view.district} />
            <Policy view={view} />
            <Week view={view} start={start} onGo={go} onChanged={poll.refresh} />
            <VillageReadiness district={district} />
          </>
        ) : null}
      </div>
    </Page>
  );
}

/**
 * Each village's people on the ground (GET /care/villages, services/assisted.py): at least two observers or relays
 * (Babai 2014 had one gauge, one reader, one phone), half of them women encouraged, every assisted household with a
 * neighbour named to check on them, and the household list that coverage is counted against. Gaps first.
 */
function VillageReadiness({ district }: { district: string }) {
  const { lang } = useT();
  const en = lang === 'en';
  const poll = usePoll(() => api.villageCare(), [], 300000);
  const rows = (poll.data?.villages ?? []).filter((v) => !district || v.district === district);
  const sorted = [...rows].sort((a, b) => b.gaps.length - a.gaps.length || a.name.localeCompare(b.name));
  return (
    <section className="rs-now" aria-labelledby="rs-ready-h">
      <h2 id="rs-ready-h" className="rs-h">
        {en ? 'Village readiness: observers and assisted households' : 'गाँव की तैयारी: निगरानीकर्ता और मदद वाले घर'}
      </h2>
      <p className="rs-meta">
        {en
          ? 'Two observers or relays per village (pradhan, gauge reader, task force), half of them women where possible; each assisted household with a neighbour named to check on them. Gender is optional and only counts coverage.'
          : 'हर गाँव में दो निगरानीकर्ता या रिले (प्रधान, गेज रीडर, टास्क फ़ोर्स), जहाँ हो सके आधी महिलाएँ; हर मदद वाले घर के लिए एक पड़ोसी तय। लिंग वैकल्पिक है और केवल दायरा गिनने के लिए।'}
      </p>
      {poll.loading && !poll.data ? (
        <Skeleton lines={3} />
      ) : poll.error && !poll.data ? (
        poll.error.isDenied ? <DeniedNote error={poll.error} /> : <ErrorState error={poll.error} onRetry={poll.refresh} />
      ) : (
        <ul className="rs-now-list">
          {sorted.map((v) => (
            <li key={v.village_id} className={`rs-now-row${v.gaps.length ? ' is-empty' : ''}`}>
              <p className="rs-district">
                <span className="rs-district-name">{en ? v.name : v.name_hi}</span>
                <span className="rs-shift">
                  {en
                    ? `${fmtNumber(v.observers, lang)} of ${fmtNumber(v.observers_needed, lang)} observers · ${fmtNumber(v.women_observers, lang)} women · ${fmtNumber(v.assisted, lang)} assisted · ${fmtNumber(v.registered_phones, lang)} phones${v.households ? ` of ${fmtNumber(v.households, lang)} households` : ''}`
                    : `${fmtNumber(v.observers, lang)} / ${fmtNumber(v.observers_needed, lang)} निगरानीकर्ता · ${fmtNumber(v.women_observers, lang)} महिलाएँ · ${fmtNumber(v.assisted, lang)} मदद वाले घर · ${fmtNumber(v.registered_phones, lang)} फ़ोन${v.households ? `, ${fmtNumber(v.households, lang)} घरों में से` : ''}`}
                </span>
              </p>
              {v.gaps.length > 0 ? (
                <p className="rs-gap" role="note">
                  {v.gaps.map((g) => gapWord(g, lang)).join(' · ')}
                  {v.assisted_without_neighbour.length > 0 && ` (${v.assisted_without_neighbour.join(', ')})`}
                </p>
              ) : (
                <p className="rs-meta">{en ? 'No gaps' : 'कोई कमी नहीं'}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** First on a phone: who answers an alert this minute, district by district. */
function OnDutyNow({ view, onChanged }: { view: RosterView; onChanged: () => void }) {
  const { t } = useT();
  return (
    <section className="rs-now" aria-labelledby="rs-now-h">
      <h2 id="rs-now-h" className="rs-h">
        {t('roster.now')}
      </h2>
      <ul className="rs-now-list">
        {view.now.map((d) => (
          <DutyRow key={d.district} duty={d} onChanged={onChanged} />
        ))}
      </ul>
    </section>
  );
}

function DutyRow({ duty: d, onChanged }: { duty: OnDuty; onChanged: () => void }) {
  const { t, lang } = useT();
  const me = useAuth((s) => s.user?.username);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [done, setDone] = useState(false);
  const empty = nobodyOnDuty(d);
  const isMe = !empty && d.primary === me;

  const takeOver = async () => {
    setBusy(true);
    setErr(null);
    setDone(false);
    try {
      await api.takeOver(d.district);
      setDone(true);
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className={`rs-now-row${empty ? ' is-empty' : ''}`}>
      <p className="rs-district">
        <span className="rs-district-name">{lang === 'hi' ? DISTRICT_HI[d.district] ?? d.district : d.district}</span>
        <span className="rs-shift">
          {t(d.shift === 'day' ? 'roster.shift.day' : 'roster.shift.night')} · {shiftWindow(d.starts_at, d.ends_at)}
        </span>
      </p>
      {empty ? (
        <p className="rs-gap" role="note">
          {d.chain.length ? t('roster.nobody', { list: d.chain.join(', ') }) : t('roster.nobody.none')}
        </p>
      ) : (
        <ol className="rs-chain">
          {d.chain.map((who, i) => (
            <li key={who} className={i === 0 ? 'is-first' : ''}>
              <span className="rs-role">{chainRole(d.roles[i] ?? '', lang)}</span>
              <span className="rs-name">{who}</span>
            </li>
          ))}
        </ol>
      )}
      {d.taken_over_from && d.taken_over_at && (
        <p className="rs-meta">{t('roster.takenover', { who: d.taken_over_from, t: istClock(d.taken_over_at) })}</p>
      )}
      {!isMe && (
        <p className="rs-actions">
          <button type="button" className="btn btn-ink btn-press" disabled={busy} onClick={() => void takeOver()}>
            {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <UserCheck aria-hidden="true" />} {t('roster.takeover')}
          </button>
        </p>
      )}
      {done && (
        <p className="ok-text small" role="status">
          {t('roster.takeover.done')}
        </p>
      )}
      {err && (err.isDenied ? <DeniedNote error={err} /> : <ErrorState error={err} compact />)}
    </li>
  );
}

/** The two rules the control room needs to know at night, as plain sentences. */
function Policy({ view }: { view: RosterView }) {
  const { t, lang } = useT();
  const at = approvalTimes(view);
  const m = (x: number) => fmtNumber(x, lang, 1);
  return (
    <ul className="rs-policy">
      <li>
        {t('roster.autosend')}{' '}
        <strong>{t(view.critical_auto_send ? 'roster.autosend.on' : 'roster.autosend.off')}</strong>
        <span className="rs-ddma"> · {t('roster.ddma')}</span>
      </li>
      <li>
        {t('roster.nudge', {
          n: m(at.nudgeMin),
          nc: at.criticalNudgeMin !== at.nudgeMin ? t('roster.nudge.crit', { m: m(at.criticalNudgeMin) }) : '',
          c: m(at.criticalWindowMin),
          w: m(at.windowMin),
        })}
      </li>
      <li>{t('roster.relays')}</li>
    </ul>
  );
}

type Editing = { date: string; shift: ShiftId; entry: RosterShift | null };

function Week({ view, start, onGo, onChanged }: { view: RosterView; start: string; onGo: (n: { district?: string; start?: string }) => void; onChanged: () => void }) {
  const { t, lang } = useT();
  const [editing, setEditing] = useState<Editing | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const selectId = useId();
  const phone = useMedia('(max-width: 639px)');
  const today = todayIST();
  const gaps = emptyShifts(view.days);
  const shiftName = (s: ShiftId) => t(s === 'day' ? 'roster.shift.day' : 'roster.shift.night');
  const hours = (s: ShiftId) => {
    const sh = view.shifts.find((x) => x.id === s);
    return sh ? `${sh.start}–${sh.end}` : '';
  };
  const form = editing && (
    <ShiftForm
      key={`${editing.date}-${editing.shift}`}
      district={view.district}
      editing={editing}
      title={`${shiftName(editing.shift)} · ${dayLabel(editing.date, lang)} · ${lang === 'hi' ? DISTRICT_HI[view.district] ?? view.district : view.district}`}
      officers={view.officers}
      onDone={(msg) => { setEditing(null); setSaved(msg); onChanged(); }}
      onCancel={() => setEditing(null)}
    />
  );

  return (
    <section className="rs-week" aria-labelledby="rs-week-h">
      <div className="rs-week-head">
        <h2 id="rs-week-h" className="rs-h">
          {t('roster.week')}
        </h2>
        <p className={`rs-count${gaps ? ' is-gap' : ''}`} role="status">
          {gaps ? t('roster.gaps', { n: gaps }) : t('roster.full')}
        </p>
      </div>
      <div className="rs-tools">
        {view.districts.length > 1 && (
          <label className="rs-district-pick" htmlFor={selectId}>
            <span className="field-label">{t('roster.district')}</span>
            <span className="select-wrap">
              <select id={selectId} value={view.district} onChange={(e) => { setEditing(null); onGo({ district: e.target.value }); }}>
                {view.districts.map((d) => (
                  <option key={d} value={d}>
                    {lang === 'hi' ? DISTRICT_HI[d] ?? d : d}
                  </option>
                ))}
              </select>
            </span>
          </label>
        )}
        <nav className="rs-nav" aria-label={t('roster.week')}>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setEditing(null); onGo({ start: addDays(start, -7) }); }}>
            <ChevronLeft aria-hidden="true" /> {t('roster.prev')}
          </button>
          {start !== todayIST() && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setEditing(null); onGo({ start: todayIST() }); }}>
              {t('roster.thisweek')}
            </button>
          )}
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setEditing(null); onGo({ start: addDays(start, 7) }); }}>
            {t('roster.next')} <ChevronRight aria-hidden="true" />
          </button>
        </nav>
      </div>

      {phone ? (
        <ul className="rs-days">
          {view.days.map((d) => (
            <DayFold
              key={d.date}
              day={d}
              open={d.date === today || d.date === addDays(today, 1)}
              shiftName={shiftName}
              hours={hours}
              editing={editing}
              onEdit={(s) => { setSaved(null); setEditing({ date: d.date, shift: s, entry: d.shifts[s].entry }); }}
            >
              {editing?.date === d.date ? form : null}
            </DayFold>
          ))}
        </ul>
      ) : (
      <div className="table-wrap rs-table-wrap" tabIndex={0} role="region" aria-label={`${t('roster.week')} · ${view.district}`}>
        <table className="data-table stack-sm rs-table">
          <thead>
            <tr>
              <th scope="col">{t('roster.date')}</th>
              {SHIFTS.map((s) => (
                <th key={s} scope="col">
                  {shiftName(s)} <span className="rs-th-time">{hours(s)}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.days.map((d) => (
              <tr key={d.date}>
                <th scope="row" className="rs-day">
                  {dayLabel(d.date, lang)}
                </th>
                {SHIFTS.map((s) => (
                  <ShiftCell
                    key={s}
                    day={d}
                    shift={s}
                    label={`${shiftName(s)} ${hours(s)}`}
                    open={editing?.date === d.date && editing.shift === s}
                    onEdit={() => { setSaved(null); setEditing({ date: d.date, shift: s, entry: d.shifts[s].entry }); }}
                  />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}
      {saved && (
        <p className="ok-text" role="status">
          {saved}
        </p>
      )}
      {!phone && form}
    </section>
  );
}

/**
 * A phone (spec 4.10): one fold per day. Today and tomorrow open; the rest closed, their summary saying who is on
 * each shift ("दिन: officer1 / officer2 · रात: officer3"), and an empty shift in red: "खाली · भरें".
 */
function DayFold({ day, open, shiftName, hours, editing, onEdit, children }: {
  children?: ReactNode;
  day: RosterDay;
  open: boolean;
  shiftName: (s: ShiftId) => string;
  hours: (s: ShiftId) => string;
  editing: Editing | null;
  onEdit: (s: ShiftId) => void;
}) {
  const { t, lang } = useT();
  const hi = lang === 'hi';
  const short = (s: ShiftId) => (s === 'day' ? (hi ? 'दिन' : 'Day') : hi ? 'रात' : 'Night');
  const empty = SHIFTS.filter((s) => !day.shifts[s].entry);
  return (
    <li className={`rs-day-fold${empty.length ? ' has-gap' : ''}`}>
      <details open={open}>
        <summary>
          <span className="rs-fold-day">{dayLabel(day.date, lang)}</span>
          <span className="rs-fold-who">
            {SHIFTS.map((s) => {
              const e = day.shifts[s].entry;
              return (
                <span key={s} className={e ? undefined : 'is-gap'}>
                  {short(s)}: {e ? [e.primary, e.backup].filter(Boolean).join(' / ') : hi ? 'खाली · भरें ›' : 'empty · fill ›'}
                </span>
              );
            })}
          </span>
        </summary>
        <div className="rs-fold-body">
          {SHIFTS.map((s) => {
            const e = day.shifts[s].entry;
            const now = isCurrent(day, s);
            const label = `${shiftName(s)} ${hours(s)}`;
            return (
              <div key={s} className={`rs-fold-shift${e ? '' : ' is-empty'}${now ? ' is-now' : ''}`}>
                <p className="rs-fold-h">
                  {label}
                  {now && <span className="rs-now-word"> · {t('roster.current')}</span>}
                </p>
                {e ? (
                  <dl className="rs-people">
                    <div>
                      <dt>{t('roster.primary')}</dt>
                      <dd className="rs-primary">{e.primary}</dd>
                    </div>
                    {e.backup && (
                      <div>
                        <dt>{t('roster.backup')}</dt>
                        <dd>{e.backup}</dd>
                      </div>
                    )}
                    {e.escalation && (
                      <div>
                        <dt>{e.escalation_title}</dt>
                        <dd>{e.escalation}</dd>
                      </div>
                    )}
                  </dl>
                ) : (
                  <p className="rs-none">{hi ? 'खाली: कोई तैनात नहीं' : 'Empty: nobody rostered'}</p>
                )}
                <button
                  type="button"
                  className="btn btn-ghost rs-fold-edit"
                  aria-expanded={editing?.date === day.date && editing.shift === s}
                  onClick={() => onEdit(s)}
                  aria-label={t('roster.edit.aria', { d: dayLabel(day.date, lang), s: label })}
                >
                  {e ? t('roster.edit') : hi ? 'भरें' : 'Fill'}
                </button>
              </div>
            );
          })}
          {children}
        </div>
      </details>
    </li>
  );
}

function ShiftCell({ day, shift, label, open, onEdit }: { day: RosterDay; shift: ShiftId; label: string; open: boolean; onEdit: () => void }) {
  const { t, lang } = useT();
  const e = day.shifts[shift].entry;
  const now = isCurrent(day, shift);
  return (
    <td data-label={label} className={`rs-cell${e ? '' : ' is-empty'}${now ? ' is-now' : ''}`}>
      <div className="rs-cell-inner">
        {e ? (
          <dl className="rs-people">
            <div>
              <dt>{t('roster.primary')}</dt>
              <dd className="rs-primary">{e.primary}</dd>
            </div>
            {e.backup && (
              <div>
                <dt>{t('roster.backup')}</dt>
                <dd>{e.backup}</dd>
              </div>
            )}
            {e.escalation && (
              <div>
                <dt>{e.escalation_title}</dt>
                <dd>{e.escalation}</dd>
              </div>
            )}
          </dl>
        ) : (
          <p className="rs-none">{t('roster.empty')}</p>
        )}
        <p className="rs-cell-foot">
          {now && <span className="rs-now-word">{t('roster.current')}</span>}
          <button type="button" className="link-btn" aria-expanded={open} onClick={onEdit} aria-label={t('roster.edit.aria', { d: dayLabel(day.date, lang), s: label })}>
            {t('roster.edit')}
          </button>
        </p>
      </div>
    </td>
  );
}

function ShiftForm({ district, editing, title, officers, onDone, onCancel }: {
  district: string;
  editing: Editing;
  title: string;
  officers: string[];
  onDone: (msg: string) => void;
  onCancel: () => void;
}) {
  const { t } = useT();
  const id = useId();
  const e = editing.entry;
  const [primary, setPrimary] = useState(e?.primary ?? '');
  const [backup, setBackup] = useState(e?.backup ?? '');
  const [escalation, setEscalation] = useState(e?.escalation ?? '');
  const [post, setPost] = useState<EscalationTitle>(e?.escalation_title ?? 'ADM');
  const [note, setNote] = useState(e?.note ?? '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const bad = [primary, backup, escalation].some((v) => v.trim() && !validUsername(v));

  const run = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      onDone(msg);
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex : new ApiError(0, null));
    } finally {
      setBusy(false);
    }
  };
  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    if (!primary.trim() || bad) return;
    void run(
      () =>
        api.setRosterShift(district, editing.date, editing.shift, {
          primary: primary.trim(),
          backup: backup.trim() || null,
          escalation: escalation.trim() || null,
          escalation_title: post,
          note: note.trim(),
        }),
      t('roster.saved'),
    );
  };

  return (
    <form className="rs-form" onSubmit={submit} aria-labelledby={`${id}-h`}>
      <h3 id={`${id}-h`} className="rs-form-h">
        {title}
      </h3>
      <datalist id={`${id}-officers`}>
        {officers.map((o) => (
          <option key={o} value={o} />
        ))}
      </datalist>
      <div className="rs-fields">
        <label className="field">
          <span className="field-label">{t('roster.primary')}</span>
          <input value={primary} onChange={(x) => setPrimary(x.target.value)} list={`${id}-officers`} required autoComplete="off" spellCheck={false} aria-describedby={`${id}-hint`} />
        </label>
        <label className="field">
          <span className="field-label">{t('roster.backup')}</span>
          <input value={backup} onChange={(x) => setBackup(x.target.value)} list={`${id}-officers`} autoComplete="off" spellCheck={false} aria-describedby={`${id}-hint`} />
        </label>
        <label className="field">
          <span className="field-label">{t('roster.escalation')}</span>
          <input value={escalation} onChange={(x) => setEscalation(x.target.value)} list={`${id}-officers`} autoComplete="off" spellCheck={false} aria-describedby={`${id}-hint`} />
        </label>
        <label className="field">
          <span className="field-label">{t('roster.escalation.post')}</span>
          <span className="select-wrap">
            <select value={post} onChange={(x) => setPost(x.target.value as EscalationTitle)}>
              <option value="ADM">ADM</option>
              <option value="DM">DM</option>
            </select>
          </span>
        </label>
        <label className="field rs-note">
          <span className="field-label">{t('roster.note')}</span>
          <input value={note} onChange={(x) => setNote(x.target.value)} maxLength={200} />
        </label>
      </div>
      <p id={`${id}-hint`} className={`small ${bad ? 'bad-text' : 'muted'}`}>
        {bad ? t('roster.username.bad') : t('roster.username')}
      </p>
      <p className="rs-form-actions">
        <button type="submit" className="btn btn-ink btn-press" disabled={busy || !primary.trim() || bad}>
          {busy && <LoaderCircle className="spin" aria-hidden="true" />} {t('roster.save')}
        </button>
        {e && (
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => void run(() => api.clearRosterShift(district, editing.date, editing.shift), t('roster.cleared'))}>
            {t('roster.clear')}
          </button>
        )}
        <button type="button" className="btn btn-ghost" disabled={busy} onClick={onCancel}>
          {t('roster.cancel')}
        </button>
      </p>
      {err && (err.isDenied ? <DeniedNote error={err} /> : <ErrorState error={err} compact />)}
    </form>
  );
}
