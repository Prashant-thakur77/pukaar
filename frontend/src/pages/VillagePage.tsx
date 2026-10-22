import { useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { ArrowLeft, ChevronRight, Mountain, Ruler, Tent, BatteryMedium, ChevronDown, ClipboardCheck, CloudRain, FileText, Gauge as GaugeIcon, HeartHandshake, History, ListChecks, Megaphone, RadioTower, Scale, TrendingUp, Waves } from 'lucide-react';
import { api } from '../api';
import { AlertStatusChip, DeliveryChips, ReplayChip, ReportStateChip } from '../components/Chips';
import { Gauge } from '../components/Gauge';
import { GaugeProposalPanel } from '../components/GaugeProposal';
import { StaffGaugeList } from '../components/StaffGauge';
import { canManageStaffGauge, staffEvidenceLine } from '../lib/staffGauge';
import { LevelBadge } from '../components/Level';
import { ListenButton } from '../components/ListenButton';
import { ReadinessCard, SoilCard } from '../components/Readiness';
import { RiverOdds } from '../components/RiverEvidence';
import { GaugeLedger } from '../components/GaugeHealth';
import { Reveal } from '../components/Reveal';
import { Sparkline } from '../components/Sparkline';
import { TimeToEar } from '../components/TimeToEar';
import { WhereToGo } from '../components/WhereToGo';
import { ActionList, Freshness, LevelBanner, StickyActionBar } from '../components/Answer';
import { Call112 } from '../components/Shell';
import { useVillageNow } from '../hooks/useVillageNow';
import './village.css';
import { districtLine, shelterWord } from '../lib/villageNow';
import { DataStatusNote, LiveLevelNote } from '../components/DataStatus';
import { DeniedNote, EmptyState, ErrorState, Skeleton, SkeletonCards } from '../components/States';
import { SirenLastTested } from '../components/SirenLastTested';
import { usePoll } from '../hooks/usePoll';
import { CHANNELS, PUBLIC_CHANNELS } from '../lib/live';
import { enumLabels, useT } from '../i18n';
import { fmtAgo, fmtDate, fmtNumber, fmtTime } from '../lib/format';
import { isLevel } from '../lib/levels';
import { describeContradiction, describeRule } from '../lib/rules';
import { auditLinkForAlert } from '../lib/audit';
import { holdLine } from '../lib/evidence';
import { humanizeSummary } from '../lib/humanize';
import { useAuth } from '../store';
import type { Alert, DecisionTrace, GaugeView, Level, PublicRollCall, RiverView, SoilView, TraceEvidence, Village } from '../types';

function AlertDetails({ alert }: { alert: Alert }) {
  const { t, lang } = useT();
  const { data, error, loading } = usePoll(() => api.alert(alert.id), [alert.id], 15000, {
    live: [CHANNELS.alerts, CHANNELS.deliveries],
    match: (e) => e.data.alert_id === alert.id,
  });
  if (loading && !data) return <Skeleton lines={3} />;
  if (error && !data) return error.isDenied ? <DeniedNote error={error} /> : <ErrorState error={error} compact />;
  if (!data) return null;
  return (
    <div className="alert-details">
      {data.deliveries.length > 0 && <TimeToEar alert={data.alert} deliveries={data.deliveries} />}
      <h4 className="h-sub">{t('village.deliveries')}</h4>
      {data.deliveries.length === 0 ? (
        <p className="small muted">{t('state.empty')}</p>
      ) : (
        <div className="table-wrap" tabIndex={0} role="region" aria-label={t('village.deliveries')}>
          <table className="data-table compact stack-sm">
            <thead>
              <tr>
                <th scope="col">{t('village.dl.name')}</th>
                <th scope="col">{t('village.dl.channel')}</th>
                <th scope="col">{t('village.dl.status')}</th>
                <th scope="col">{t('village.dl.sent')}</th>
                <th scope="col">{t('village.dl.ack')}</th>
              </tr>
            </thead>
            <tbody>
              {data.deliveries.map((d) => (
                <tr key={d.recipient_id}>
                  <th scope="row">{d.name}</th>
                  <td data-label={t('village.dl.channel')}>{d.channel === 'stub' ? t('console.channel.stub') : t('console.channel.telegram')}</td>
                  <td data-label={t('village.dl.status')}>
                    {d.status}
                    {d.error && <span className="small bad-text"> · {d.error}</span>}
                  </td>
                  <td data-label={t('village.dl.sent')}>{fmtTime(d.sent_at, lang)}</td>
                  <td data-label={t('village.dl.ack')}>{d.acknowledged_at ? <span className="ok-text">✓ {fmtTime(d.acknowledged_at, lang)}</span> : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h4 className="h-sub">{t('village.timeline')}</h4>
      <ol className="mini-timeline">
        {data.timeline.map((e, i) => (
          <li key={i}>
            <span className="mt-time">{fmtTime(e.at, lang)}</span>
            <strong>{e.step}</strong> <span className="muted">{e.detail}</span>
          </li>
        ))}
      </ol>
      <Link className="link" to={auditLinkForAlert(alert.id)}>
        {t('village.audit')} →
      </Link>
    </div>
  );
}

function AlertCard({ alert, signedIn }: { alert: Alert; signedIn: boolean }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  return (
    <li className={`alert-card lv-${alert.level}`}>
      <div className="ac-top">
        <LevelBadge level={alert.level} size="sm" />
        <AlertStatusChip status={alert.status} />
        {alert.reasoning_model === 'rule-fallback' && <span className="chip chip-warn">{t('console.model.fallback')}</span>}
        {alert.replay && <ReplayChip />}
      </div>
      <p className="ac-text" lang="hi">
        {alert.text_hi}
      </p>
      <p className="small muted">{alert.text_en}</p>
      <div className="ac-row">
        <DeliveryChips approved={alert.approved} delivered={alert.delivered_count} acked={alert.acknowledged_count} status={alert.status} />
        <ListenButton alertId={alert.id} hasAudio={alert.has_audio} />
      </div>
      {signedIn && (
        <>
          <button type="button" className="btn btn-sm btn-ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            <ChevronDown aria-hidden="true" className={open ? 'rot' : ''} /> {open ? t('common.less') : t('common.more')}
          </button>
          {open && <AlertDetails alert={alert} />}
        </>
      )}
    </li>
  );
}

/** Public reports carry no words, GPS or media: only whether a place, a photo or a voice note came with them. */
function ReportCarried({ r }: { r: { has_location?: boolean; has_photo?: boolean; has_audio?: boolean } }) {
  const { t } = useT();
  const parts = [r.has_location && t('village.rp.location'), r.has_photo && t('village.rp.photo'), r.has_audio && t('village.rp.voice')].filter(Boolean);
  if (!parts.length) return null;
  return <p className="small muted rp-carried">{t('village.rp.with', { x: parts.join(' · ') })}</p>;
}

/** An open "Surakshit Hoon" roll-call: counts only, never names. */
function RollCallCount({ rc }: { rc: PublicRollCall }) {
  const { t } = useT();
  return (
    <section aria-labelledby="rcv-h" className={`rc-public${rc.need_help > 0 ? ' has-help' : ''}`}>
      <h2 id="rcv-h" className="h-sec">
        <HeartHandshake aria-hidden="true" /> {t('rollcall.title')}
        {rc.exercise && <span className="chip chip-warn">{t('rollcall.exercise')}</span>}
      </h2>
      <p className="rc-public-line" role="status">
        {t(rc.need_help === 1 ? 'rollcall.public.one' : 'rollcall.public.many', { s: rc.safe, h: rc.need_help })}
      </p>
      <p className="small muted">
        {t('rollcall.public.waiting', { n: rc.not_answered })} · {t('rollcall.public.lead')}
      </p>
    </section>
  );
}

/** IMD 24 h rain bands (mm) used by services/risk_rules.py. */
const IMD_BANDS = { watch: 64.5, warning: 115.6, critical: 204.5 };

/** IMD bands times the soil factor, rounded up to 0.1 mm like risk_rules.scaled_bands. */
function scaleBands(f: number) {
  const k = Math.max(0.7, Math.min(1, f));
  const up = (mm: number) => Math.ceil(Math.round(mm * k * 10 * 1e6) / 1e6) / 10;
  return { watch: up(IMD_BANDS.watch), warning: up(IMD_BANDS.warning), critical: up(IMD_BANDS.critical) };
}

/** River gauge: the measured stage, a third source beside the rain and river forecasts. */
function GaugeCard({ gauge, villageId, onChanged }: { gauge: GaugeView | null | undefined; villageId: string; onChanged: () => void }) {
  const { t, lang } = useT();
  const user = useAuth((s) => s.user);
  const signedIn = Boolean(useAuth((s) => s.token));
  // Officers anywhere, the village's own pradhan (read only); Cedar decides on the server.
  const seesProposal = signedIn && Boolean(gauge?.config) && canManageStaffGauge(user, villageId);
  const latest = gauge?.latest ?? null;
  const cfg = gauge?.config;
  const bands = cfg ? { watch: cfg.watch_cm, warning: cfg.warning_cm, critical: cfg.critical_cm } : null;
  const empty = !gauge || !latest;
  return (
    <Reveal className="ev-card ev-wide ev-gauge" delay={110}>
      <header className="ev-head">
        <RadioTower aria-hidden="true" />
        <h3>{t('gauge.title')}</h3>
        {gauge?.fresh && gauge.level && isLevel(gauge.level) && <LevelBadge level={gauge.level} size="sm" />}
        {latest?.simulated && <span className="chip chip-warn">{t('gauge.sim')}</span>}
      </header>
      {empty ? (
        <div className="ev-gauge-empty">
          <p className="muted">{cfg?.installed ? t('gauge.stale') : t('gauge.none')}</p>
          <p className="small muted">{cfg?.installed ? t('gauge.stale.lead') : t('gauge.none.lead')}</p>
        </div>
      ) : (
        <div className="ev-gauge-body">
          <div>
            <p className={`ev-value${gauge.fresh ? '' : ' is-stale'}`}>
              {fmtNumber(latest.water_level_cm, lang, 0)} <span>cm</span>
            </p>
            <p className="small muted">{t('gauge.stage')}</p>
            {bands && <Gauge value={gauge.fresh ? latest.water_level_cm : null} bands={bands} unit="cm" label={t('gauge.title')} />}
            {!gauge.fresh && (
              <p className="small">
                <strong>{t('gauge.stale')}</strong> · <span className="muted">{t('gauge.stale.lead')}</span>
              </p>
            )}
            <p className="ev-sweep small">
              {t('gauge.reading', { t: fmtAgo(latest.at, lang) })}
              {latest.battery_v != null && (
                <span className="ev-gauge-batt">
                  {' '}· <BatteryMedium aria-hidden="true" /> {t('gauge.battery', { v: fmtNumber(latest.battery_v, lang, 2) })}
                </span>
              )}
            </p>
          </div>
          <div className="trend-card c-gauge">
            <p className="small">{t('gauge.trend')}</p>
            <Sparkline
              values={gauge.series.map((p) => p.cm)}
              label={t('gauge.title')}
              unit=" cm"
              height={80}
              marks={bands ? (['watch', 'warning', 'critical'] as const).map((l) => ({ value: bands[l], className: `lv-${l}`, label: l })) : []}
            />
          </div>
        </div>
      )}
      {gauge && (latest || gauge.health) && (
        <GaugeLedger
          health={gauge.health}
          quality={latest?.quality}
          qualityReasons={latest?.quality_reasons}
          counted={gauge.fresh ? gauge.level : null}
          measured={gauge.fresh ? gauge.measured_level : null}
          rising={gauge.rising_fast}
          riseCm={latest?.rise_cm}
        />
      )}
      {latest?.simulated && <p className="small muted">{t('gauge.sim.note')}</p>}
      {cfg && !cfg.installed && !empty && <p className="small muted">{t('gauge.illustrative')}</p>}
      {cfg?.thresholds_set_by && (
        <p className="small muted">{t('learn.current.source', { s: cfg.thresholds_source ?? '', u: cfg.thresholds_set_by })}</p>
      )}
      {seesProposal && <GaugeProposalPanel villageId={villageId} canAccept={user?.role === 'officer'} onAccepted={onChanged} />}
    </Reveal>
  );
}

function Evidence({ village, trace, traceReplay, gauge, soil, river, onChanged }: { village: Village; trace: DecisionTrace | null; traceReplay: boolean; gauge?: GaugeView | null; soil?: SoilView | null; river?: RiverView | null; onChanged: () => void }) {
  const { t, lang, pick } = useT();
  const traceReading = trace?.evidence?.find((e) => e.kind === 'reading') ?? null;
  const reports = (trace?.evidence ?? []).filter((e): e is TraceEvidence => e.kind === 'report');
  const staffEv = (trace?.evidence ?? []).filter((e) => e.kind === 'staff_gauge');
  const lr = village.latest_reading;
  // Rain and river cards show the newest sweep; the rules card shows the sweep that raised the alert.
  const useLatest = Boolean(lr && (!traceReading?.at || lr.at >= String(traceReading.at)));
  const rain = useLatest ? lr!.rain_24h_mm : (traceReading?.rain_24h_mm ?? null);
  const rainLevel = (useLatest ? lr!.rain_level : traceReading?.rain_level) as Level | undefined;
  // The newest sweep's bands: lowered only when the soil modifier is on and applied.
  const bandsRaw = useLatest && soil?.applied ? scaleBands(soil.factor) : useLatest ? IMD_BANDS : traceReading?.rain_bands_mm;
  const rainBands =
    bandsRaw && bandsRaw.watch != null && bandsRaw.warning != null && bandsRaw.critical != null ? (bandsRaw as { watch: number; warning: number; critical: number }) : IMD_BANDS;
  const peak = useLatest ? lr!.discharge_peak : (traceReading?.discharge_peak ?? null);
  const riverLevel = (useLatest ? lr!.river_level : traceReading?.river_level) as Level | undefined;
  const th = (useLatest ? village.thresholds : traceReading?.thresholds) ?? village.thresholds ?? traceReading?.thresholds ?? null;
  const sweepAt = useLatest ? lr!.at : traceReading?.at ? String(traceReading.at) : null;
  const sweepLabel = sweepAt ? t(useLatest ? 'village.ev.latest' : 'village.ev.alert', { t: fmtTime(sweepAt, lang) }) : null;
  const alertSweepAt = traceReading?.at ? String(traceReading.at) : typeof trace?.generated_at === 'string' ? trace.generated_at : null;
  // The rules card explains the alert's sweep. Hide it when that sweep was a replay, or when a
  // newer reading has come in and the village has since moved off the alert's level.
  const traceStale = Boolean(lr && alertSweepAt && lr.at > alertSweepAt && trace?.level !== village.level);
  const showRules = !traceReplay && !trace?.replay && !traceStale;

  return (
    <div className="evidence-grid">
      <Reveal className="ev-card">
        <header className="ev-head">
          <CloudRain aria-hidden="true" />
          <h3>{t('village.rain')}</h3>
          {rainLevel && isLevel(rainLevel) && <LevelBadge level={rainLevel} size="sm" />}
        </header>
        {rain == null ? (
          <p className="muted">{t('village.no.reading')}</p>
        ) : (
          <>
            <p className="ev-value">
              {fmtNumber(rain, lang, 1)} <span>mm</span>
            </p>
            <Gauge value={rain} bands={rainBands} unit="mm" label={t('village.rain')} />
            <p className="small muted">{t('village.rain.bands')}</p>
          </>
        )}
        {sweepLabel && <p className="ev-sweep small">{sweepLabel}</p>}
      </Reveal>
      <Reveal className="ev-card" delay={80}>
        <header className="ev-head">
          <Waves aria-hidden="true" />
          <h3>{t('village.river')}</h3>
          {riverLevel && isLevel(riverLevel) && <LevelBadge level={riverLevel} size="sm" />}
        </header>
        {peak == null ? (
          <p className="muted">{t('village.no.reading')}</p>
        ) : (
          <p className="ev-value">
            {fmtNumber(peak, lang, 1)} <span>m³/s</span>
          </p>
        )}
        {th ? (
          <>
            <Gauge value={peak} bands={th} unit="m³/s" label={t('village.river')} />
            {th.source && <p className="small muted">{th.source}</p>}
          </>
        ) : (
          <p className="small muted">{t('village.no.thresholds')}</p>
        )}
        {sweepLabel && <p className="ev-sweep small">{sweepLabel}</p>}
      </Reveal>
      {(river || lr?.official?.length) && <RiverOdds river={river} official={lr?.official} />}
      <GaugeCard gauge={gauge} villageId={village.id} onChanged={onChanged} />
      <SoilCard soil={soil} />
      {showRules && trace?.rules_fired && trace.rules_fired.length > 0 && (
        <Reveal className="ev-card ev-wide" delay={140}>
          <header className="ev-head">
            <ListChecks aria-hidden="true" />
            <h3>{t('village.rules')}</h3>
            {trace.rules_version && <code className="small muted">{String(trace.rules_version)}</code>}
          </header>
          {alertSweepAt && <p className="ev-sweep small">{t('village.ev.alert', { t: fmtTime(alertSweepAt, lang) })}</p>}
          <ul className="rule-list">
            {trace.rules_fired.map((r) => (
              <li key={r}>
                <span>{describeRule(r, lang)}</span>
                <code>{r}</code>
              </li>
            ))}
          </ul>
          {trace.contradictions && trace.contradictions.length > 0 && (
            <div className="contra">
              <Scale aria-hidden="true" />
              <div>
                <strong>{t('village.contradictions')}</strong>
                {trace.contradictions.map((c) => (
                  <p key={c} className="small">
                    {describeContradiction(c, lang)}
                  </p>
                ))}
              </div>
            </div>
          )}
        </Reveal>
      )}
      {showRules && staffEv.length > 0 && (
        <Reveal className="ev-card ev-wide" delay={160}>
          <header className="ev-head">
            <Ruler aria-hidden="true" />
            <h3>{t('staff.title')}</h3>
          </header>
          <ul className="ev-reports">
            {staffEv.map((e) => (
              <li key={String(e.report_id)}>
                <span>{staffEvidenceLine(e, fmtTime(typeof e.at === 'string' ? e.at : null, lang), lang)}</span>
                {isLevel(String(e.level)) && e.level !== 'normal' && <LevelBadge level={e.level as Level} size="sm" />}
              </li>
            ))}
          </ul>
        </Reveal>
      )}
      {reports.length > 0 && (
        <Reveal className="ev-card ev-wide" delay={180}>
          <header className="ev-head">
            <FileText aria-hidden="true" />
            <h3>{t('village.reports.evidence')}</h3>
          </header>
          <ul className="ev-reports">
            {reports.map((r) => (
              <li key={String(r.report_id)}>
                <span>{r.type ? pick(enumLabels.reportType[r.type]) : '—'}</span>
                <span className="muted">{r.severity ? pick(enumLabels.severity[r.severity]) : ''}</span>
                {r.state && <ReportStateChip state={r.state} />}
                <span className="small muted">weight {r.weight ?? '—'}</span>
              </li>
            ))}
          </ul>
        </Reveal>
      )}
    </div>
  );
}

export default function VillagePage() {
  const { id = '' } = useParams();
  const { t, lang, pick } = useT();
  const signedIn = Boolean(useAuth((s) => s.token));
  const user = useAuth((s) => s.user);
  const { data, error, refresh } = usePoll(() => api.village(id), [id], 15000, {
    live: PUBLIC_CHANNELS,
    match: (e) => e.data.village_id === id,
  });
  // The answer comes first: the phone's last copy, then the small /now answer, then each poll of the detail.
  const answer = useVillageNow(id, data ?? null, error ?? null);
  // A link like /village/gohar#where lands on that section once the page has its data.
  const { hash } = useLocation();
  const ready = Boolean(data);
  useEffect(() => {
    if (!ready || !hash) return;
    document.getElementById(hash.slice(1))?.scrollIntoView({ block: 'start' });
  }, [ready, hash]);

  const now = answer.now;
  if (!now) {
    if (answer.missing || (error && error.status === 404))
      return (
        <div className="wrap village-page">
          <EmptyState title={t('village.notfound')} action={<Link to="/" className="btn btn-ghost">{t('village.back')}</Link>} />
        </div>
      );
    if (error && !data)
      return (
        <div className="wrap village-page">
          <ErrorState error={error} onRetry={refresh} />
        </div>
      );
    // Nothing on this phone yet and nothing back: say what is coming and what to do meanwhile. No skeleton.
    return (
      <div className="wrap village-page vtop-wait">
        <p className="vwait-title">{lang === 'hi' ? 'गाँव का हाल आ रहा है…' : 'Getting the village’s level…'}</p>
        <p className="vwait-body">
          {lang === 'hi' ? 'ख़तरा दिखे तो इंतज़ार न करें: ऊँची जगह जाएँ और ' : 'If you see danger, do not wait: go to high ground and '}
          <a href="tel:112" className="go-link">
            {lang === 'hi' ? '112 पर कॉल करें' : 'call 112'}
          </a>
          .
        </p>
      </div>
    );
  }

  const v = data?.village ?? null;
  const latestAlert = data ? ([...data.alerts].sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null) : null;
  const trace = latestAlert?.decision_trace ?? null;
  // One time axis: live readings, or only the replay's while a replay runs (never 2023 and 2026 together).
  const readings = data && v ? data.readings.filter((r) => Boolean(r.replay) === Boolean(v.replay)).sort((a, b) => a.at.localeCompare(b.at)) : [];
  // Hysteresis: a level rises at once but drops one step only after 3 calm sweeps.
  const traceHolds = Boolean(v && trace && latestAlert?.level === v.level && holdLine(trace, lang));
  const hold =
    v && v.level !== 'normal' && (v.calm_sweeps > 0 || traceHolds)
      ? holdLine(null, lang, { level: v.level, raw: 'normal', calm: v.calm_sweeps, needed: trace?.hysteresis?.needed_to_drop ?? 3 })
      : null;
  const pastHere = data ? data.past_events.filter((e) => !e.level || (v && e.level === v.level)) : [];
  const past = data ? (pastHere.length ? pastHere : data.past_events) : [];

  const unknown = !now.level_known;
  const shown = unknown ? 'nodata' : now.level;
  const why = data?.nowcast ? (lang === 'hi' ? data.nowcast.text_hi : data.nowcast.text_en) : hold?.text ?? null;
  const urgent = now.level === 'warning' || now.level === 'critical';
  const place = now.safe_place;
  const audioAlert = latestAlert && latestAlert.has_audio && now.level !== 'normal' ? latestAlert : null;

  return (
    <div className={`village-page${urgent ? ' is-urgent' : ''}`}>
      <div className="wrap vtop">
        <nav className="vcrumb" aria-label={lang === 'hi' ? 'आप यहाँ हैं' : 'You are here'}>
          <Link to="/" className="go-link">
            <ArrowLeft aria-hidden="true" /> {lang === 'hi' ? 'गाँवों का हाल' : 'Village status'}
          </Link>
        </nav>
        <div className="vtop-main">
          <LevelBanner
            id="v-title"
            level={now.level}
            unknown={unknown}
            means={now.means}
            why={why}
            title={
              <>
                <span lang="hi">{now.name_hi}</span> <span className="lvb-en" lang="en">{now.name}</span>
                <span className="lvb-en"> · {districtLine(now.district, lang)}</span>
              </>
            }
          >
            <Freshness at={now.checked_at} offline={answer.offline} every />
          </LevelBanner>
          <DataStatusNote v={now} />
          <LiveLevelNote v={now} />
          <ActionList lines={now.actions} level={shown}>
            {audioAlert && <ListenButton alertId={audioAlert.id} hasAudio />}
            {urgent ? (
              <span className="vtop-112">
                <Call112 />
              </span>
            ) : (
              <a href="#where" className="go-link">
                <Mountain aria-hidden="true" /> {lang === 'hi' ? 'ऊँची जगह और रास्ता देखें' : 'See the high place and the route'}
                <ChevronRight aria-hidden="true" />
              </a>
            )}
          </ActionList>
          {data && <SirenLastTested sirens={data.sirens} />}
        </div>
        {place && (
          <aside className="vtop-aside" aria-labelledby="vwhere-h">
            <h2 id="vwhere-h" className="vside-h">
              {lang === 'hi' ? 'कहाँ जाएँ' : 'Where to go'}
            </h2>
            <p className="vside-name">{lang === 'hi' ? place.name_hi || place.name : place.name || place.name_hi}</p>
            <p className="vside-line">
              <span className={`vside-status s-${place.status.toLowerCase()}`}>{shelterWord(place.status, lang)}</span>
              {place.route_blocked && <span className="vside-status s-closed">{lang === 'hi' ? 'रास्ता बंद' : 'Route closed'}</span>}
            </p>
            <p className="vside-facts">
              {[
                place.headroom_m != null ? (lang === 'hi' ? `${Math.round(place.headroom_m)} मी ऊँचा` : `${Math.round(place.headroom_m)} m higher`) : null,
                place.route_length_m != null ? `${fmtNumber(place.route_length_m / 1000, lang, 1)} ${lang === 'hi' ? 'किमी' : 'km'}` : null,
                place.walk_min != null ? (lang === 'hi' ? `~${place.walk_min} मिनट पैदल` : `~${place.walk_min} min on foot`) : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
            <a href="#where" className="go-link">
              {lang === 'hi' ? 'नक्शा और रास्ता' : 'Map and route'} <ChevronRight aria-hidden="true" />
            </a>
          </aside>
        )}
      </div>

      {!data || !v ? (
        <div className="wrap v-body">
          {/* Below the answer only: the detail is still on its way. */}
          <SkeletonCards n={2} />
        </div>
      ) : (
      <div className="wrap v-body">
        {data.rollcall?.open && <RollCallCount rc={data.rollcall} />}
        {(data.directives ?? []).filter((d) => d.active).length > 0 && (
          <section aria-labelledby="dir-h">
            <h2 id="dir-h" className="h-sec">
              <Megaphone aria-hidden="true" /> {t('console.directive.active')}
            </h2>
            <ul className="directive-list">
              {(data.directives ?? [])
                .filter((d) => d.active)
                .map((d) => (
                  <li key={d.id} className={`directive-card dt-${d.type}`}>
                    <p className="dc-top">
                      <strong>{pick(enumLabels.directiveType[d.type])}</strong> · {fmtAgo(d.issued_at, lang)}
                    </p>
                    <p lang="hi" className="dc-hi">
                      {d.text_hi}
                    </p>
                    <p className="small muted">{d.text_en}</p>
                  </li>
                ))}
            </ul>
          </section>
        )}
        <section id="where" aria-labelledby="wtg-h" className="v-where">
          <h2 id="wtg-h" className="h-sec">
            <Tent aria-hidden="true" /> {t('safe.title')}
          </h2>
          <p className="muted">{t('safe.lead')}</p>
          <WhereToGo village={v} />
        </section>

        {readings.length > 1 && (
          <section aria-labelledby="trend-h">
            <h2 id="trend-h" className="h-sec">
              <TrendingUp aria-hidden="true" /> {t('village.trend')}
            </h2>
            <div className="trend-grid">
              <div className="card trend-card c-rain">
                <p className="small">{t('village.trend.rain')}</p>
                <Sparkline values={readings.map((r) => r.rain_24h_mm)} label={t('village.trend.rain')} unit=" mm" />
                <p className="small muted">
                  {fmtTime(readings[0].at, lang)} → {fmtTime(readings[readings.length - 1].at, lang)}
                </p>
              </div>
              <div className="card trend-card c-river">
                <p className="small">{t('village.trend.discharge')}</p>
                <Sparkline
                  values={readings.map((r) => r.discharge)}
                  label={t('village.trend.discharge')}
                  marks={v.thresholds ? (['watch', 'warning', 'critical'] as const).map((l) => ({ value: v.thresholds![l], className: `lv-${l}`, label: l })) : []}
                />
                <p className="small muted">{v.thresholds ? t('village.trend.lines') : t('village.no.thresholds')}</p>
              </div>
            </div>
          </section>
        )}

        <section aria-labelledby="why-h" data-tour="why">
          <h2 id="why-h" className="h-sec">
            <GaugeIcon aria-hidden="true" /> {t('village.why')}
          </h2>
          <p className="muted">{t('village.why.lead')}</p>
          <Evidence village={v} trace={trace} traceReplay={Boolean(latestAlert?.replay)} gauge={data.gauge} soil={data.soil} river={data.river} onChanged={refresh} />
        </section>

        {(data.staff_gauges?.gauges.length || canManageStaffGauge(user, v.id)) && (
          <section aria-labelledby="sg-h">
            <h2 id="sg-h" className="h-sec">
              <Ruler aria-hidden="true" /> {t('staff.title')}
            </h2>
            <p className="muted">{t('staff.lead')}</p>
            <StaffGaugeList view={data.staff_gauges} canManage={signedIn && canManageStaffGauge(user, v.id)} villageId={v.id} onChanged={refresh} />
          </section>
        )}

        <section aria-labelledby="past-h">
          <h2 id="past-h" className="h-sec">
            <History aria-hidden="true" /> {pastHere.length ? t('village.past') : t('village.past.any')}
          </h2>
          {past.length === 0 ? (
            <p className="muted">{t('village.past.empty')}</p>
          ) : (
            <ul className="past-list">
              {past.map((e, i) => (
                <li key={i} className="card past-item">
                  <span className="past-date">{fmtDate(e.date ?? e.at ?? null, lang)}</span>
                  {e.level && isLevel(e.level) && <LevelBadge level={e.level} size="sm" />}
                  {(() => {
                    const hi = e.note_hi ?? e.text_hi;
                    const en = e.note_en ?? e.text_en ?? e.title;
                    const useHi = lang === 'hi' && hi;
                    return <p lang={useHi ? 'hi' : 'en'}>{useHi ? hi : en ?? hi ?? ''}</p>;
                  })()}
                  {e.source_url ? (
                    <a className="small link" href={e.source_url} target="_blank" rel="noreferrer">
                      {e.source ?? 'Source'} ↗
                    </a>
                  ) : e.source ? (
                    <p className="small muted">{e.source}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="al-h" data-tour="village-alerts">
          <h2 id="al-h" className="h-sec">
            {t('village.alerts')}
          </h2>
          {data.alerts.length === 0 ? (
            <p className="muted">{t('live.alerts.empty')}</p>
          ) : (
            <ul className="alert-cards">
              {[...data.alerts]
                .sort((a, b) => b.created_at.localeCompare(a.created_at))
                .map((a) => (
                  <AlertCard key={a.id} alert={a} signedIn={signedIn} />
                ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="rp-h">
          <h2 id="rp-h" className="h-sec">
            {t('village.reports')}
          </h2>
          {data.reports.length === 0 ? (
            <p className="muted">{t('console.reports.empty')}</p>
          ) : (
            <ul className="report-mini">
              {data.reports.map((r) => (
                <li key={r.id} className="card">
                  <div className="ac-top">
                    <strong>{pick(enumLabels.reportType[r.report_type])}</strong>
                    <ReportStateChip state={r.state} />
                    {r.held && <span className="chip chip-sm chip-held">{lang === 'hi' ? 'जाँच के लिए रोकी गई' : 'Held for review'}</span>}
                    {r.replay && <ReplayChip />}
                  </div>
                  {(() => {
                    const words = humanizeSummary(r.summary_en, lang, r.report_type, r.severity) || r.transcript || r.text;
                    return words ? <p>{words}</p> : null;
                  })()}
                  <ReportCarried r={r} />
                  <p className="small muted">{fmtAgo(r.created_at, lang)}</p>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="ready-h">
          <h2 id="ready-h" className="h-sec">
            <ClipboardCheck aria-hidden="true" /> {t('ready.title')}
          </h2>
          <p className="muted">{t('ready.lead')}</p>
          <ReadinessCard villageId={v.id} readiness={v.readiness} checklist={data.checklist} />
        </section>
      </div>
      )}
      <StickyActionBar level={unknown ? 'normal' : now.level} place={place} />
    </div>
  );
}
