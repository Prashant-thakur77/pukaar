import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft,
  BellRing,
  CalendarClock,
  ChevronRight,
  CircleCheck,
  CircleX,
  Clock,
  CloudRain,
  FileText,
  Hourglass,
  Keyboard,
  Landmark,
  Lock,
  Pencil,
  RadioTower,
  Scale,
  ShieldAlert,
  Siren as SirenIcon,
  Users,
  Waves,
  X,
  type LucideIcon,
} from 'lucide-react';
import { api, API_BASE, ApiError } from '../../api';
import { HoldToConfirm, type HoldHandle } from '../../components/HoldToConfirm';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { AlertStatusChip, DeliveryChips, ReplayChip } from '../../components/Chips';
import { LevelIcon } from '../../components/Level';
import { ListenButton } from '../../components/ListenButton';
import { SirenPanel } from '../../components/SirenPanel';
import { Snackbar, type SnackbarMsg } from '../../components/Snackbar';
import { DeniedNote, ErrorState, Skeleton } from '../../components/States';
import { useMedia, useNow } from '../../hooks/useMedia';
import { usePoll } from '../../hooks/usePoll';
import { dict, useT } from '../../i18n';
import { istClock, isStale } from '../../lib/answerText';
import { auditLinkForAlert } from '../../lib/audit';
import { capXmlUrl } from '../../lib/cap';
import { hasAfterAction } from '../../lib/afterAction';
import { evidenceLines, shortReason, type EvidenceLine } from '../../lib/evidence';
import { fmtNumber } from '../../lib/format';
import { dailyPoints, toPoints } from '../../lib/riverLine';
import { RiverNow } from '../../components/RiverNow';
import { isSnoozed, isTyping, pruneSnoozes, readSnoozes, sortQueue, step, waitedMinutes, writeSnoozes, type Snoozes } from '../../lib/inbox';
import { sirenApi } from '../../lib/sirens';
import type { Lang } from '../../store';
import type { Alert, Village } from '../../types';
import { AfterActionLinks, Deliveries, OutcomePicker } from './AlertRecord';
import { useConsole } from './consoleContext';
import { PushNudge } from './PushNudge';

/*
 * The inbox (spec 4.9, C25/C26): what waits for a decision on the left, most severe and oldest first; the
 * decision on the right, with its evidence, the exact message and who it reaches (people and sirens); then one
 * deliberate action, hold to approve. Keyboard: J/K move, A approves (hold, or tap and Enter), R declines,
 * E edits, S sets it aside for 10 minutes, ? lists the keys. On a phone the list and the decision are two
 * screens, the decision with its actions stuck to the bottom.
 */

const WIDE = '(min-width: 1024px)';

const EV_ICON: Record<EvidenceLine['kind'], LucideIcon> = {
  river: Waves,
  rain: CloudRain,
  gauge: RadioTower,
  reports: FileText,
  agree: Users,
  impact: ShieldAlert,
  disagree: Scale,
  hold: Hourglass,
  none: CircleX,
  outlook: CalendarClock,
  official: Landmark,
};

const levelHi = (l: Alert['level']) => dict[`level.${l}`].hi;
const levelEn = (l: Alert['level']) => dict[`level.${l}`].en;
const villageName = (a: Pick<Alert, 'village_name' | 'village_name_hi'>, lang: Lang) => (lang === 'hi' ? a.village_name_hi : a.village_name);

/** "03:10 IST" today; "11 Oct, 22:11 IST" on another day (India time either way). */
function when(iso: string, lang: Lang): string {
  const clock = istClock(iso) ?? '';
  const day = (d: Date) => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(d);
  if (day(new Date(iso)) === day(new Date())) return clock;
  const date = new Intl.DateTimeFormat(lang === 'hi' ? 'hi-IN' : 'en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short' }).format(new Date(iso));
  return `${date}, ${clock}`;
}

export default function Inbox() {
  const { t } = useT();
  const c = useConsole();
  const { alertId } = useParams();
  const [params, setParams] = useSearchParams();
  const view: 'pending' | 'sent' = params.get('v') === 'sent' ? 'sent' : 'pending';
  const navigate = useNavigate();
  const wide = useMedia(WIDE);
  const now = useNow(30_000);
  const [snoozes, setSnoozes] = useState<Snoozes>(readSnoozes);
  const [showKeys, setShowKeys] = useState(false);
  const [snack, setSnack] = useState<SnackbarMsg | null>(null);
  const closeSnack = useCallback(() => setSnack(null), []);
  // What this officer just decided here: its confirmation stays on screen until they move on.
  const [decided, setDecided] = useState<Record<string, { kind: 'approved' | 'declined'; at: string }>>({});

  const pendingAll = useMemo(() => sortQueue((c.pending.data ?? []).filter((a) => a.status === 'pending')), [c.pending.data]);
  const active = pendingAll.filter((a) => !isSnoozed(a, snoozes, now));
  const later = pendingAll.filter((a) => isSnoozed(a, snoozes, now));
  const sent = useMemo(
    () => [...(c.alerts.data ?? [])].filter((a) => a.status !== 'pending').sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [c.alerts.data],
  );
  const list = view === 'pending' ? active : sent;

  // Forget snoozes that are over, or whose alert was decided.
  useEffect(() => {
    if (!c.pending.data) return;
    // Only the phone's copy: what is on screen already ignores them (isSnoozed).
    const kept = pruneSnoozes(snoozes, new Set(pendingAll.map((a) => a.id)), now);
    if (Object.keys(kept).length !== Object.keys(snoozes).length) writeSnoozes(kept);
  }, [c.pending.data, pendingAll, snoozes, now]);

  const findAlert = (id: string | undefined) => (id ? pendingAll.find((a) => a.id === id) ?? sent.find((a) => a.id === id) ?? null : null);
  // On a desk the first alert opens by itself; on a phone the list comes first.
  const selectedId = alertId ?? (wide ? list[0]?.id : undefined);
  const selected = findAlert(selectedId);
  const go = useCallback(
    (id: string | null, replace = false) => navigate(id ? `/console/inbox/${id}${view === 'sent' ? '?v=sent' : ''}` : `/console/inbox${view === 'sent' ? '?v=sent' : ''}`, { replace }),
    [navigate, view],
  );

  const snooze = useCallback(
    async (a: Alert) => {
      try {
        const r = await api.snoozeAlert(a.id, 10);
        const next = { ...readSnoozes(), [a.id]: { until: new Date(r.snoozed_until).getTime(), level: a.level, updated: a.updated_at } };
        writeSnoozes(next);
        setSnoozes(next);
        setSnack({ id: Date.now(), text: t('decide.snoozed') });
        const ids = active.map((x) => x.id).filter((x) => x !== a.id);
        go(step(ids, null, 1), true);
      } catch (e) {
        const err = e instanceof ApiError ? e : new ApiError(0, null);
        setSnack({ id: Date.now(), text: err.messageEn });
      }
    },
    [active, go, t],
  );
  const wake = (id: string) => {
    const next = { ...snoozes };
    delete next[id];
    writeSnoozes(next);
    setSnoozes(next);
    go(id);
  };

  // J/K through the list; ? for the keys. A, R, E and S belong to the decision panel (it listens itself).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
      if (e.key === '?') {
        e.preventDefault();
        setShowKeys(true);
        return;
      }
      const k = e.key.toLowerCase();
      if (k !== 'j' && k !== 'k') return;
      e.preventDefault();
      const ids = list.map((a) => a.id);
      const next = step(ids, selected?.id ?? null, k === 'j' ? 1 : -1);
      if (next) go(next, true);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [list, selected, go]);

  const listPane = (
    <section className="ib-list" aria-labelledby="ib-h">
      <div className="ib-list-head">
        <h1 id="ib-h" className="ib-h">
          {t('cs.nav.inbox')}
        </h1>
        <div className="seg" role="group" aria-label={t('inbox.title')}>
          <button type="button" className={`seg-btn${view === 'pending' ? ' is-on' : ''}`} aria-pressed={view === 'pending'} onClick={() => setParams({})}>
            {t('inbox.title')} <span className="seg-n">{active.length}</span>
          </button>
          <button type="button" className={`seg-btn${view === 'sent' ? ' is-on' : ''}`} aria-pressed={view === 'sent'} onClick={() => setParams({ v: 'sent' })}>
            {t('inbox.sent')}
          </button>
        </div>
      </div>
      {view === 'pending' && <PushNudge />}
      {c.pending.loading && !c.pending.data ? (
        <Skeleton lines={4} />
      ) : c.pending.error && !c.pending.data ? (
        <ErrorState error={c.pending.error} onRetry={c.pending.refresh} compact />
      ) : list.length === 0 ? (
        <div className="ib-empty">
          <CircleCheck aria-hidden="true" />
          <p className="ib-empty-title">{view === 'pending' ? t('inbox.empty.title') : t('inbox.sent.empty')}</p>
          {view === 'pending' && <p className="ib-empty-body">{t('inbox.empty.body')}</p>}
        </div>
      ) : (
        <>
          {view === 'pending' && <p className="ib-sort">{t('inbox.sort')}</p>}
          <ul className="ib-rows">
            {list.map((a) => (
              <li key={a.id}>
                <QueueRow alert={a} selected={a.id === selected?.id} now={now} village={c.villages.data?.find((v) => v.id === a.village_id) ?? null} />
              </li>
            ))}
          </ul>
        </>
      )}
      {view === 'pending' && later.length > 0 && (
        <details className="ib-later">
          <summary>
            <Clock aria-hidden="true" /> {t('inbox.later')} ({later.length})
          </summary>
          <ul className="ib-rows">
            {later.map((a) => (
              <li key={a.id} className="ib-later-row">
                <QueueRow alert={a} selected={a.id === selected?.id} now={now} village={null} />
                <span className="ib-later-left">{t('decide.snooze.left', { n: Math.max(1, Math.ceil(((snoozes[a.id]?.until ?? now) - now) / 60000)) })}</span>
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => wake(a.id)}>
                  {t('decide.wake')}
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
      <button type="button" className="ib-keys-btn" onClick={() => setShowKeys(true)}>
        <Keyboard aria-hidden="true" /> {t('keys.open')} <kbd>?</kbd>
      </button>
    </section>
  );

  const index = selected ? list.findIndex((a) => a.id === selected.id) : -1;
  const decision = selected ? (
    decided[selected.id] ? (
      <Decided key={selected.id} alert={selected} kind={decided[selected.id].kind} at={decided[selected.id].at} onBack={wide ? null : () => go(null)} />
    ) : selected.status === 'pending' ? (
      <DecisionPanel
        key={selected.id}
        alert={selected}
        position={index >= 0 ? { i: index + 1, n: list.length } : null}
        onSnooze={() => void snooze(selected)}
        onBack={wide ? null : () => go(null)}
        onDecided={(kind) => {
          setDecided((d) => ({ ...d, [selected.id]: { kind, at: new Date().toISOString() } }));
          // Keep this alert on screen (its confirmation and delivery count); J moves on.
          go(selected.id, true);
        }}
      />
    ) : (
      <SentPanel key={selected.id} alert={selected} onBack={wide ? null : () => go(null)} />
    )
  ) : alertId ? (
    <GonePanel onBack={() => go(null)} />
  ) : (
    <div className="ib-pick">
      <p>{t('inbox.pick')}</p>
    </div>
  );

  return (
    <div className={`ib${selected && !wide ? ' is-deciding' : ''}`}>
      {(wide || !alertId) && listPane}
      {(wide || alertId) && <div className="ib-decision">{decision}</div>}
      <ShortcutsSheet open={showKeys} onClose={() => setShowKeys(false)} />
      <Snackbar msg={snack} onClose={closeSnack} closeLabel={t('common.close')} />
    </div>
  );
}

/* ---------- the queue ---------- */

function QueueRow({ alert: a, selected, now, village }: { alert: Alert; selected: boolean; now: number; village: Village | null }) {
  const { t, lang } = useT();
  const waited = waitedMinutes(a.created_at, now);
  const pending = a.status === 'pending';
  const why = shortReason(a.decision_trace?.rules_fired, lang);
  return (
    <Link to={`/console/inbox/${a.id}${pending ? '' : '?v=sent'}`} className={`ib-row lv-${a.level}${selected ? ' is-selected' : ''}`} aria-current={selected ? 'true' : undefined}>
      <span className="ib-row-top">
        <span className="ib-level">
          <LevelIcon level={a.level} className="ib-level-icon" />
          <span lang="hi">{levelHi(a.level)}</span>
        </span>
        <span className="ib-village">{villageName(a, lang)}</span>
        {pending && a.level === 'critical' && <span className="ib-urgent">{t('inbox.urgent')}</span>}
        {a.replay && <ReplayChip />}
      </span>
      {why && <span className="ib-why">{why}</span>}
      <span className="ib-row-meta">
        {pending ? <span>{t('inbox.waiting', { n: waited })}</span> : <AlertStatusChip status={a.status} />}
        <span>{t('inbox.people', { n: fmtNumber(a.recipients_count, lang) })}</span>
        {village?.population ? <span className="ib-pop">~{fmtNumber(village.population, lang)}</span> : null}
      </span>
      <ChevronRight aria-hidden="true" className="ib-go" />
    </Link>
  );
}

/* ---------- the decision ---------- */

function DecisionPanel({
  alert,
  position,
  onSnooze,
  onBack,
  onDecided,
}: {
  alert: Alert;
  position: { i: number; n: number } | null;
  onSnooze: () => void;
  onBack: (() => void) | null;
  onDecided: (kind: 'approved' | 'declined') => void;
}) {
  const { t, lang } = useT();
  const c = useConsole();
  const now = useNow(15_000);
  const holdRef = useRef<HoldHandle>(null);
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState('');
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const village = c.villages.data?.find((v) => v.id === alert.village_id) ?? null;
  const canDecide = c.officer;
  const waited = waitedMinutes(alert.created_at, now);

  const run = async (fn: () => Promise<Alert>, kind: 'approved' | 'declined') => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      onDecided(kind);
      c.refreshAlerts();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
      throw e;
    } finally {
      setBusy(false);
    }
  };
  const approve = () => run(() => api.approve(alert.id), 'approved');
  const decline = () => run(() => api.decline(alert.id, reason.trim() || undefined), 'declined').then(() => setDeclining(false), () => setDeclining(false));

  // A, R, E, S on the alert in front of the officer.
  useEffect(() => {
    if (!canDecide) return;
    const down = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target) || editing || declining) return;
      const k = e.key.toLowerCase();
      if (k === 'a' && !e.repeat) {
        e.preventDefault();
        holdRef.current?.begin();
      } else if (k === 'r') {
        e.preventDefault();
        setDeclining(true);
      } else if (k === 'e') {
        e.preventDefault();
        setEditing(true);
      } else if (k === 's') {
        e.preventDefault();
        onSnooze();
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === 'a') holdRef.current?.end();
    };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
    };
  }, [canDecide, editing, declining, onSnooze]);

  const name = villageName(alert, lang);
  return (
    <article className={`dp lv-${alert.level}`} aria-labelledby="dp-h">
      {onBack && (
        <button type="button" className="dp-back go-link" onClick={onBack}>
          <ArrowLeft aria-hidden="true" /> {t('inbox.back')}
        </button>
      )}
      <header className="dp-head">
        <div className="dp-title-row">
          <h2 id="dp-h" className="dp-title">
            <LevelIcon level={alert.level} className="dp-level-icon" />
            <span lang="hi" className="dp-level">
              {levelHi(alert.level)}
            </span>
            {lang === 'en' && <span className="dp-level-en">{levelEn(alert.level)}</span>}
            <span className="dp-sep" aria-hidden="true">
              ·
            </span>
            <span className="dp-village">{name}</span>
          </h2>
          {position && (
            <p className="dp-pos">
              {t('decide.of', position)} <kbd>J</kbd> <kbd>K</kbd>
            </p>
          )}
        </div>
        <p className="dp-sub">
          <span>{t('decide.reach', { n: fmtNumber(alert.recipients_count, lang) })}</span>
          <span>{t('decide.waiting', { n: waited })}</span>
          <span>{t('decide.made', { t: when(alert.created_at, lang) })}</span>
          {alert.replay && <ReplayChip />}
        </p>
      </header>

      <div className="dp-body">
      {err &&
        (err.isDenied ? (
          <DeniedNote error={err} />
        ) : err.isLate ? (
          <p className="dp-note is-warn" role="alert">
            {(lang === 'hi' && err.messageHi) || err.messageEn}
          </p>
        ) : err.isRetry ? (
          <p className="dp-note is-warn" role="alert">
            {t('approve.retry')}
          </p>
        ) : (
          <ErrorState error={err} compact />
        ))}

      <Section title={t('decide.why')}>
        <Evidence alert={alert} village={village} />
      </Section>

      <Section title={t('decide.send')}>
        {editing ? (
          <EditMessage
            alert={alert}
            onDone={(updated) => {
              setEditing(false);
              if (updated) c.refreshAlerts();
            }}
          />
        ) : (
          <>
            <blockquote className="dp-msg" lang="hi">
              {alert.text_hi}
            </blockquote>
            <div className="dp-msg-tools">
              <ListenButton alertId={alert.id} hasAudio={alert.has_audio} />
              <DraftCheckLine alert={alert} />
            </div>
            <details className="dp-en">
              <summary>{t('decide.english')}</summary>
              <p lang="en">{alert.text_en}</p>
            </details>
          </>
        )}
      </Section>

      <Section title={t('decide.towhom')}>
        <Audience alert={alert} village={village} />
      </Section>

      <AnswerWindow alert={alert} now={now} />
      {canDecide && c.health.data?.mode === 'local' && <DevLink alertId={alert.id} />}
      </div>

      <div className="dp-actions">
        {canDecide ? (
          <>
            <HoldToConfirm
              ref={holdRef}
              keyHint="A"
              className="dp-hold"
              disabled={busy || editing}
              onConfirm={approve}
              text={{
                idle: t('decide.hold.idle'),
                holding: t('decide.hold.holding'),
                almost: t('decide.hold.almost'),
                sending: t('decide.hold.sending'),
                done: t('decide.hold.done'),
                hint: t('decide.hold.hint'),
                confirmQ: t('decide.confirm.q'),
                confirmYes: t('decide.confirm.yes'),
                confirmNo: t('common.cancel'),
              }}
            />
            <div className="dp-second">
              <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setEditing((x) => !x)} aria-pressed={editing}>
                <Pencil aria-hidden="true" /> {t('decide.edit')} <kbd>E</kbd>
              </button>
              <button type="button" className="btn btn-ghost" disabled={busy} onClick={onSnooze}>
                <Clock aria-hidden="true" /> {t('decide.snooze')} <kbd>S</kbd>
              </button>
              <button type="button" className="btn btn-decline" disabled={busy} onClick={() => setDeclining(true)}>
                <X aria-hidden="true" /> {t('decide.decline')} <kbd>R</kbd>
              </button>
            </div>
          </>
        ) : (
          <PradhanLock alert={alert} onDone={c.refreshAlerts} />
        )}
      </div>

      <ConfirmDialog
        open={declining}
        title={t('decide.decline.title', { v: name })}
        confirmLabel={t('decide.decline')}
        cancelLabel={t('common.cancel')}
        tone="danger"
        busy={busy}
        onCancel={() => setDeclining(false)}
        onConfirm={() => void decline()}
      >
        <p>{t('decide.decline.body')}</p>
        <label className="field">
          <span className="field-label">{t('console.decline.reason')}</span>
          <input className="input-lg" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} />
        </label>
      </ConfirmDialog>
    </article>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="dp-sec">
      <h3 className="dp-sec-h">{title}</h3>
      {children}
    </section>
  );
}

/** Why this level: the rules' evidence in words, the river forecast against its lines, the last reading. */
function Evidence({ alert, village }: { alert: Alert; village: Village | null }) {
  const { t, lang } = useT();
  const lines = evidenceLines(alert.decision_trace, lang);
  const rules = alert.decision_trace?.rules_fired ?? [];
  const reading = village?.latest_reading ?? null;
  return (
    <>
      {village && <MiniRiver village={village} />}
      {lines.length > 0 && <EvidenceList lines={lines.slice(0, 2)} />}
      {reading?.at && (
        <p className="dp-meta">
          <span>
            {t('decide.reading', { t: istClock(reading.at) ?? '' })} ·{' '}
            {isStale(reading.at) ? <span className="warn-text">{t('decide.old')}</span> : <span className="ok-text">✓ {t('decide.fresh')}</span>}
          </span>
        </p>
      )}
      {(lines.length > 2 || rules.length > 0) && (
        <details className="dp-more">
          <summary>{t('decide.more', { n: Math.max(0, lines.length - 2) + (rules.length ? 1 : 0) })}</summary>
          {lines.length > 2 && <EvidenceList lines={lines.slice(2)} />}
          {rules.length > 0 && (
            <p className="dp-meta">
              <span>
                {t('decide.rules')}: <code>{rules.join(' · ')}</code>
              </span>
            </p>
          )}
        </details>
      )}
    </>
  );
}

function EvidenceList({ lines }: { lines: EvidenceLine[] }) {
  return (
    <ul className="dp-ev">
      {lines.map((l, i) => {
        const Icon = EV_ICON[l.kind];
        return (
          <li key={i} className={l.level ? `lv-${l.level}` : ''}>
            <Icon aria-hidden="true" />
            <span>{l.text}</span>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The river in the decision (S1, compact): the last day's flow from the village's /now answer, the forecast days
 * after it, and the watch, warning and danger lines labelled on the lines. The ladder is left out: the evidence
 * lines under it say the same in words.
 */
function MiniRiver({ village }: { village: Village }) {
  const { lang } = useT();
  const { data } = usePoll(() => api.villageNow(village.id), [village.id], 120_000);
  const r = village.latest_reading;
  const th = village.thresholds;
  const observed = data?.river?.points?.length ? toPoints(data.river.points) : r?.discharge != null ? [{ t: Date.parse(r.at), v: r.discharge }] : [];
  const forecast = dailyPoints(r?.discharge_forecast, observed[observed.length - 1]?.t ?? -Infinity);
  if (!th || observed.length + forecast.length < 2) return null;
  return (
    <RiverNow
      observed={observed}
      forecast={forecast}
      thresholds={th}
      unit="m³/s"
      title={lang === 'hi' ? 'नदी अभी' : 'The river now'}
      headingId={`dp-river-${village.id}`}
      heading="h4"
      height={150}
      ladder={false}
      replay={Boolean(village.replay)}
    />
  );
}

function DraftCheckLine({ alert }: { alert: Alert }) {
  const { t } = useT();
  const passed = alert.draft_check?.passed;
  const edited = /edited by/.test(alert.draft_check?.reason ?? '');
  const Icon = passed ? CircleCheck : ShieldAlert;
  const word = edited ? t('decide.edit.saved') : passed ? t('console.check.pass') : t('console.check.template');
  return (
    <span className={`dp-check ${passed ? 'ok-text' : 'warn-text'}`} title={alert.draft_check?.reason}>
      <Icon aria-hidden="true" /> {t('decide.check')}: {word}
    </span>
  );
}

/** Who hears it: the registered people (relays first), the village, and its sirens. */
function Audience({ alert, village }: { alert: Alert; village: Village | null }) {
  const { t, lang } = useT();
  const devs = usePoll(() => sirenApi.villageDevices(alert.village_id), [alert.village_id], 60000);
  const sirens = (devs.data?.devices ?? []).filter((d) => d.kind === 'siren');
  const sounds = alert.level === 'warning' || alert.level === 'critical';
  const lvl = lang === 'hi' ? levelHi(alert.level) : levelEn(alert.level);
  return (
    <dl className="dp-aud">
      <div>
        <dt>
          <Users aria-hidden="true" />
        </dt>
        <dd>
          {alert.recipients_count > 0 ? t('decide.people', { n: fmtNumber(alert.recipients_count, lang) }) : t('decide.people.none')}
          {village?.population ? <span className="dp-aud-sub">{t('decide.population', { n: fmtNumber(village.population, lang) })}</span> : null}
        </dd>
      </div>
      <div>
        <dt>
          <SirenIcon aria-hidden="true" />
        </dt>
        <dd>
          {devs.loading && !devs.data ? (
            '…'
          ) : !sirens.length ? (
            t('decide.sirens.none')
          ) : !sounds ? (
            t('decide.sirens.quiet', { lvl })
          ) : (
            <>
              {sirens.length === 1 ? t('decide.sirens.one') : t('decide.sirens', { n: sirens.length })}
              <span className="dp-aud-sub">
                {sirens.map((s) => s.device_id).join(', ')}
                {alert.level === 'critical' && <> · {t('decide.sirens.critical')}</>}
              </span>
            </>
          )}
        </dd>
      </div>
    </dl>
  );
}

/** How long this officer has to answer before the next one is asked (the roster's approval window). */
function AnswerWindow({ alert, now }: { alert: Alert; now: number }) {
  const { t } = useT();
  const c = useConsole();
  const r = c.roster.data;
  const secs = alert.level === 'critical' ? r?.approval_timeout_critical_seconds ?? r?.approval_timeout_seconds : r?.approval_timeout_seconds;
  if (!secs) return null;
  const since = new Date(alert.updated_at || alert.created_at).getTime();
  const used = Math.max(0, now - since);
  const pct = Math.min(100, (used / (secs * 1000)) * 100);
  const left = Math.max(0, Math.ceil((secs * 1000 - used) / 60000));
  return (
    <div className="dp-window">
      <p className="dp-window-label">
        <Hourglass aria-hidden="true" /> {t('decide.window')}: {left > 0 ? t('decide.window.left', { n: left }) : t('decide.window.over')}
      </p>
      <span className="dp-window-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} aria-label={t('decide.window')}>
        <i style={{ width: `${pct}%` }} />
      </span>
    </div>
  );
}

function EditMessage({ alert, onDone }: { alert: Alert; onDone: (updated: boolean) => void }) {
  const { t, lang } = useT();
  const [hi, setHi] = useState(alert.text_hi);
  const [en, setEn] = useState(alert.text_en);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.editAlert(alert.id, hi, en);
      onDone(true);
    } catch (e) {
      const ae = e instanceof ApiError ? e : new ApiError(0, null);
      setErr((lang === 'hi' && ae.messageHi) || ae.messageEn);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      className="dp-edit"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          onDone(false);
        }
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
          e.preventDefault();
          void save();
        }
      }}
    >
      <p className="dp-edit-rules">{t('decide.edit.rules')}</p>
      <label className="field">
        <span className="field-label">{t('decide.edit.hi')}</span>
        <textarea lang="hi" rows={5} value={hi} onChange={(e) => setHi(e.target.value)} autoFocus maxLength={600} />
      </label>
      <label className="field">
        <span className="field-label">{t('decide.edit.en')}</span>
        <textarea lang="en" rows={3} value={en} onChange={(e) => setEn(e.target.value)} maxLength={600} />
      </label>
      {err && (
        <p className="dp-note is-bad" role="alert">
          {err}
        </p>
      )}
      <div className="dp-edit-actions">
        <button type="submit" className="btn btn-accent" disabled={busy}>
          {t('decide.edit.save')} <kbd>Ctrl Enter</kbd>
        </button>
        <button type="button" className="btn btn-ghost" onClick={() => onDone(false)}>
          {t('common.cancel')} <kbd>Esc</kbd>
        </button>
      </div>
    </form>
  );
}

/** A pradhan sees the decision but cannot make it; "try anyway" asks the server, which says why (DEMO step 7). */
function PradhanLock({ alert, onDone }: { alert: Alert; onDone: () => void }) {
  const { t } = useT();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const tryAnyway = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.approve(alert.id);
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="dp-locked">
      <button type="button" className="hold-btn is-locked" disabled aria-describedby={`try-${alert.id}`}>
        <span className="hold-label">
          <Lock aria-hidden="true" /> {t('console.approve.officers')}
        </span>
      </button>
      <button type="button" id={`try-${alert.id}`} className="link-btn" onClick={() => void tryAnyway()} disabled={busy}>
        {t('console.approve.try')}
      </button>
      {err && (err.isDenied ? <DeniedNote error={err} /> : <ErrorState error={err} compact />)}
    </div>
  );
}

/** Local stack only: open the one-tap approval link the asked officer would get on Telegram (for demos). */
function DevLink({ alertId }: { alertId: string }) {
  const { t } = useT();
  const [err, setErr] = useState<string | null>(null);
  const open = async () => {
    setErr(null);
    const w = window.open('', '_blank');
    try {
      const res = await api.devApprovalLink(alertId);
      let path = `/a/${res.token}`;
      try {
        const u = new URL(res.url);
        path = `${u.pathname}${u.search}`;
      } catch {
        /* keep the token path */
      }
      if (w) {
        w.opener = null;
        w.location.href = `${window.location.origin}${path}`;
      } else window.location.assign(path);
    } catch (e) {
      w?.close();
      setErr(e instanceof ApiError ? e.messageEn : 'error');
    }
  };
  return (
    <p className="dp-meta">
      <button type="button" className="link-btn" onClick={() => void open()} title={t('console.devlink.note')}>
        {t('console.devlink')} ↗
      </button>
      {err && <span className="bad-text">{err}</span>}
    </p>
  );
}

/** C14: what the officer just did, said once (role=alert), with the live delivery count under it. */
function Decided({ alert, kind, at, onBack }: { alert: Alert; kind: 'approved' | 'declined'; at: string; onBack: (() => void) | null }) {
  const { t, lang } = useT();
  const c = useConsole();
  const fresh = (c.alerts.data ?? []).find((a) => a.id === alert.id) ?? alert;
  return (
    <article className={`dp lv-${alert.level}`}>
      {onBack && (
        <button type="button" className="dp-back go-link" onClick={onBack}>
          <ArrowLeft aria-hidden="true" /> {t('inbox.back')}
        </button>
      )}
      <div className={`dp-done${kind === 'declined' ? ' is-declined' : ''}`} role="alert">
        {kind === 'approved' ? (
          <>
            <p className="dp-done-title">
              <CircleCheck aria-hidden="true" /> {t('decide.sent.title', { t: istClock(at) ?? '' })}
            </p>
            <p className="dp-done-body">
              {villageName(alert, lang)} · {t('decide.sent.body', { n: fmtNumber(alert.recipients_count, lang) })}
            </p>
          </>
        ) : (
          <p className="dp-done-title">
            <CircleX aria-hidden="true" /> {t('decide.declined')} · {villageName(alert, lang)}
          </p>
        )}
      </div>
      {kind === 'approved' && <Record alert={fresh} />}
    </article>
  );
}

/** A decided alert: delivery, the siren tier, who it reached, the after-action report and the outcome. */
function SentPanel({ alert, onBack }: { alert: Alert; onBack: (() => void) | null }) {
  const { t, lang } = useT();
  return (
    <article className={`dp lv-${alert.level}`} aria-labelledby="sp-h">
      {onBack && (
        <button type="button" className="dp-back go-link" onClick={onBack}>
          <ArrowLeft aria-hidden="true" /> {t('inbox.back')}
        </button>
      )}
      <header className="dp-head">
        <h2 id="sp-h" className="dp-title">
          <LevelIcon level={alert.level} className="dp-level-icon" />
          <span lang="hi" className="dp-level">
            {levelHi(alert.level)}
          </span>
          <span className="dp-sep" aria-hidden="true">
            ·
          </span>
          <span className="dp-village">{villageName(alert, lang)}</span>
        </h2>
        <p className="dp-sub">
          <AlertStatusChip status={alert.status} />
          <span>{t('decide.made', { t: when(alert.created_at, lang) })}</span>
          {alert.decided_by && <span>{alert.decided_by}</span>}
          {alert.replay && <ReplayChip />}
        </p>
      </header>
      <Section title={t('decide.sent.msg')}>
        <blockquote className="dp-msg" lang="hi">
          {alert.text_hi}
        </blockquote>
      </Section>
      <Record alert={alert} />
    </article>
  );
}

function Record({ alert: a }: { alert: Alert }) {
  const { t } = useT();
  const c = useConsole();
  const sent = ['delivering', 'delivered', 'closed', 'auto_sent_unapproved', 'failsafe'].includes(a.status) || a.delivered_count > 0;
  const cap = capXmlUrl(a, API_BASE);
  const total = Math.max(a.recipients_count, a.delivered_count, 1);
  return (
    <>
      <Section title={t('decide.record')}>
        <div className="dp-funnel" aria-label={t('decide.funnel')}>
          <DeliveryChips approved={a.approved} delivered={a.delivered_count} acked={a.acknowledged_count} status={a.status} />
          <span className="dp-funnel-bar" aria-hidden="true">
            <i className="is-delivered" style={{ width: `${(a.delivered_count / total) * 100}%` }} />
            <i className="is-acked" style={{ width: `${(a.acknowledged_count / total) * 100}%` }} />
          </span>
        </div>
        <SirenPanel alert={a} />
        <p className="dp-links">
          {c.officer && (
            <Link className="link" to={auditLinkForAlert(a.id)}>
              {t('console.audit')}
            </Link>
          )}
          {cap && (
            <a className="link" href={cap} target="_blank" rel="noreferrer" title={t('console.cap.title')}>
              CAP XML ↗
            </a>
          )}
        </p>
        {hasAfterAction(a) && <AfterActionLinks alert={a} />}
        {hasAfterAction(a) && c.officer && !a.replay && !a.decision_trace?.drill && <OutcomePicker alert={a} />}
      </Section>
      {sent && (
        <Section title={t('console.deliveries', { n: a.recipients_count || a.delivered_count })}>
          <Deliveries alertId={a.id} />
        </Section>
      )}
      {(a.sirens_total ?? 0) > 0 && (
        <p className="dp-meta">
          <BellRing aria-hidden="true" /> {a.siren_pattern ?? ''}
        </p>
      )}
    </>
  );
}

/** The link named an alert that is no longer in the lists (decided long ago, or a replay was reset). */
function GonePanel({ onBack }: { onBack: () => void }) {
  const { t } = useT();
  return (
    <div className="ib-pick">
      <p>{t('approve.late.body')}</p>
      <button type="button" className="btn btn-ghost" onClick={onBack}>
        <ArrowLeft aria-hidden="true" /> {t('inbox.back')}
      </button>
    </div>
  );
}

/* ---------- the keys ---------- */

function ShortcutsSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useT();
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal?.();
    if (!open && d.open) d.close();
  }, [open]);
  const rows: [string, string][] = [
    ['J', t('keys.j')],
    ['K', t('keys.k')],
    ['A', t('keys.a')],
    ['R', t('keys.r')],
    ['E', t('keys.e')],
    ['S', t('keys.s')],
    ['?', t('keys.help')],
    ['Esc', t('keys.esc')],
  ];
  return (
    <dialog
      ref={ref}
      className="dialog keys-sheet"
      aria-labelledby="keys-h"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      <h2 id="keys-h" className="dialog-title">
        <Keyboard aria-hidden="true" /> {t('keys.title')}
      </h2>
      <dl className="keys-list">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>
              <kbd>{k}</kbd>
            </dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      <div className="dialog-actions">
        <button type="button" className="btn btn-accent" onClick={onClose} autoFocus>
          {t('common.close')}
        </button>
      </div>
    </dialog>
  );
}
