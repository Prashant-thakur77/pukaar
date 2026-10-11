import { useState } from 'react';
import { TimeToEar } from '../../components/TimeToEar';
import { Link, Navigate, useLocation } from 'react-router-dom';
import { Bell, ChevronDown, Cloud, FileText, History, LayoutList, Megaphone, MonitorCog, ScrollText, Send, Server, Sparkles } from 'lucide-react';
import { api, API_BASE } from '../../api';
import { AlertStatusChip, DeliveryChips } from '../../components/Chips';
import { LevelBadge } from '../../components/Level';
import { Call112 } from '../../components/Shell';
import { usePoll } from '../../hooks/usePoll';
import { useT } from '../../i18n';
import { auditLinkForAlert } from '../../lib/audit';
import { capXmlUrl } from '../../lib/cap';
import { fmtAgo, fmtTime } from '../../lib/format';
import { Skeleton } from '../../components/States';
import { Headline, StatStrip } from '../../components/PageBand';
import type { Alert } from '../../types';
import { useAuth } from '../../store';
import { Approvals } from './Approvals';
import { Ask } from './Ask';
import { Directives } from './Directives';
import { Replay } from './Replay';
import { ReportFeed } from './ReportFeed';
import { SystemCard } from './System';
import { TelegramLink } from './TelegramLink';
import { VillageQueue } from './VillageQueue';

export default function ConsolePage() {
  const token = useAuth((s) => s.token);
  const loc = useLocation();
  if (!token) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  return <Console />;
}

function Console() {
  const { t, lang } = useT();
  const user = useAuth((s) => s.user);
  // The role comes from /me (the stored login copy is only a first guess).
  const me = usePoll(() => api.me(), [], 0);
  const role = me.data?.role ?? user?.role ?? 'officer';
  const officer = role !== 'pradhan';
  const villages = usePoll(() => api.villages(), []);
  const pending = usePoll(() => api.alerts({ status: 'pending' }), []);
  const recent = usePoll(() => api.alerts(), []);
  const reports = usePoll(() => api.reports(), []);
  const directives = usePoll(() => api.directives(), []);
  const replay = usePoll(() => api.replayStatus(), []);
  const health = usePoll(() => api.health(), [], 60000);
  const vs = villages.data ?? [];
  const pendingN = pending.data?.filter((a) => a.status === 'pending').length ?? 0;
  const mode = health.data?.mode;
  const raised = vs.filter((v) => v.level !== 'normal').length;

  const refreshAlerts = () => {
    void pending.refresh();
    void recent.refresh();
    void villages.refresh();
  };
  const refreshAll = () => {
    refreshAlerts();
    void reports.refresh();
    void directives.refresh();
    void health.refresh();
  };

  const tabs = [
    { href: '#approvals', label: t('console.tab.approvals'), icon: Bell, badge: pendingN },
    { href: '#queue', label: t('console.tab.queue'), icon: LayoutList },
    { href: '#reports', label: t('console.tab.reports'), icon: FileText },
    ...(officer
      ? [
          { href: '#ask', label: t('console.tab.ask'), icon: Sparkles },
          { href: '#act', label: t('console.tab.act'), icon: Megaphone },
        ]
      : []),
  ];

  return (
    <div className={`console${officer ? '' : ' is-pradhan'}`}>
      <header className="console-head pg-band pg-night">
        <div className="wrap-wide ch-inner pg-inner">
          <div className="pg-text">
            <p className="pg-eyebrow">
              <span className="live-dot" aria-hidden="true" />
              {officer ? t('console.title') : t('console.title.pradhan')}
              {user && (
                <span className="ch-who">
                  {' · '}
                  {t('console.signed.as', { u: me.data?.username ?? user.username, r: role })}
                </span>
              )}
            </p>
            <h1 className="pg-title">
              <Headline text={officer ? t('console.title') : t('console.title.pradhan')} />
            </h1>
            {!officer && <p className="small muted pradhan-note">{t('console.pradhan.note')}</p>}
          </div>
          <div className="ch-tools">
            {mode && (
              <span className={`chip mode-chip ${mode === 'aws' ? 'chip-good' : 'chip-warn'}`}>
                {mode === 'aws' ? <Cloud aria-hidden="true" /> : <MonitorCog aria-hidden="true" />}
                {t('console.mode.chip', { m: mode === 'aws' ? t('system.mode.aws') : t('system.mode.local') })}
              </span>
            )}
            {officer && (
              <Link to="/audit" className="btn btn-ghost btn-press">
                <ScrollText aria-hidden="true" /> {t('console.audit')}
              </Link>
            )}
            <Call112 />
          </div>
        </div>
        <div className="wrap-wide pg-extra">
          <StatStrip
            stats={[
              { key: 'p', value: pendingN, label: t('console.pending'), tone: pendingN > 0 ? 'alert' : undefined },
              { key: 'v', value: vs.length || '—', label: t('counter.villages_watched') },
              { key: 'a', value: raised, label: lang === 'hi' ? 'सामान्य से ऊपर' : 'Above normal', tone: raised > 0 ? 'alert' : undefined },
              { key: 'r', value: reports.data?.length ?? '—', label: t('counter.reports_received') },
            ]}
          />
        </div>
        <nav className="console-tabs wrap-wide" aria-label="Console sections">
          {tabs.map((tb) => (
            <a key={tb.href} href={tb.href} className="ctab">
              <tb.icon aria-hidden="true" /> {tb.label}
              {tb.badge ? <span className="badge">{tb.badge}</span> : null}
            </a>
          ))}
        </nav>
      </header>

      <div className="console-grid wrap-wide">
        <div className="console-top">
          <section className="panel panel-compact panel-replay" aria-labelledby="rep-h">
            <h2 id="rep-h" className="panel-title">
              <History aria-hidden="true" /> {t('console.replay')}
            </h2>
            <Replay poll={replay} onChanged={refreshAll} canControl={officer} />
          </section>
          <section className="panel panel-compact panel-system" aria-labelledby="sys-h">
            <h2 id="sys-h" className="panel-title">
              <Server aria-hidden="true" /> {t('system.title')}
            </h2>
            <SystemCard poll={health} />
          </section>
        </div>

        <section id="approvals" className="panel panel-approvals" aria-labelledby="ap-h">
          <h2 id="ap-h" className="panel-title">
            <Bell aria-hidden="true" /> {t('console.pending')}
            {pendingN > 0 && <span className="badge badge-pulse">{pendingN}</span>}
          </h2>
          <Approvals poll={pending} onChange={refreshAlerts} localMode={mode === 'local'} canDecide={officer} />
        </section>

        <section id="queue" className="panel panel-queue" aria-labelledby="q-h">
          <h2 id="q-h" className="panel-title">
            <LayoutList aria-hidden="true" /> {t('console.queue')}
          </h2>
          <VillageQueue poll={villages} />
        </section>

        {officer && (
          <section id="ask" className="panel panel-ask" aria-labelledby="ask-h">
            <h2 id="ask-h" className="panel-title">
              <Sparkles aria-hidden="true" /> {t('console.ask')}
            </h2>
            <Ask villages={vs} />
          </section>
        )}

        <section id="reports" className="panel panel-reports" aria-labelledby="rp-h">
          <h2 id="rp-h" className="panel-title">
            <FileText aria-hidden="true" /> {t('console.reports')}
          </h2>
          <ReportFeed poll={reports} villages={vs} canEdit={officer} />
        </section>

        <div id="act" className="panel-stack">
          {officer && (
            <>
              <section className="panel" aria-labelledby="dir-h">
                <h2 id="dir-h" className="panel-title">
                  <Megaphone aria-hidden="true" /> {t('console.directive')}
                </h2>
                <Directives villages={vs} poll={directives} />
              </section>
              <section className="panel" aria-labelledby="tg-h">
                <h2 id="tg-h" className="panel-title">
                  <Send aria-hidden="true" /> {t('console.tg')}
                </h2>
                <TelegramLink />
              </section>
            </>
          )}
          <section className="panel" aria-labelledby="ra-h">
            <h2 id="ra-h" className="panel-title">
              <Bell aria-hidden="true" /> {t('console.alerts.recent')}
            </h2>
            <ul className="recent-alerts">
              {(recent.data ?? [])
                .slice()
                .sort((a, b) => b.created_at.localeCompare(a.created_at))
                .slice(0, 6)
                .map((a) => (
                  <RecentAlert key={a.id} alert={a} showAudit={officer} />
                ))}
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}

/** A recent alert with its per-recipient deliveries (GET /alerts/{id}) in an expander. */
function RecentAlert({ alert: a, showAudit }: { alert: Alert; showAudit: boolean }) {
  const { t, lang } = useT();
  const [open, setOpen] = useState(false);
  const sent = ['delivering', 'delivered', 'closed', 'auto_sent_unapproved', 'failsafe'].includes(a.status) || a.delivered_count > 0;
  const cap = capXmlUrl(a, API_BASE);
  return (
    <li className={`ra-row lv-${a.level}`}>
      <div className="ac-top">
        <LevelBadge level={a.level} size="sm" both={false} lang={lang} />
        <Link to={`/village/${a.village_id}`} className="ra-name">
          {lang === 'hi' ? a.village_name_hi : a.village_name}
        </Link>
        <AlertStatusChip status={a.status} />
      </div>
      <DeliveryChips approved={a.approved} delivered={a.delivered_count} acked={a.acknowledged_count} status={a.status} />
      <p className="small muted">
        {fmtAgo(a.created_at, lang)}
        {showAudit && (
          <>
            {' · '}
            <Link className="link" to={auditLinkForAlert(a.id)}>
              {t('console.audit')}
            </Link>
          </>
        )}
        {cap && (
          <>
            {' · '}
            <a className="link" href={cap} target="_blank" rel="noreferrer" title={t('console.cap.title')}>
              CAP XML ↗
            </a>
          </>
        )}
      </p>
      {sent && (
        <>
          <button type="button" className="trace-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {t('console.deliveries', { n: a.recipients_count || a.delivered_count })}
            <ChevronDown aria-hidden="true" className={open ? 'rot' : ''} />
          </button>
          {open && <Deliveries alertId={a.id} />}
        </>
      )}
    </li>
  );
}

function Deliveries({ alertId }: { alertId: string }) {
  const { t, lang } = useT();
  const { data, error, loading } = usePoll(() => api.alert(alertId), [alertId], 15000);
  if (loading && !data) return <Skeleton lines={2} />;
  if (error && !data) return <p className="small bad-text">{error.messageEn}</p>;
  const ds = data?.deliveries ?? [];
  if (!ds.length) return <p className="small muted">{t('console.deliveries.none')}</p>;
  return (
    <>
    {data && <TimeToEar alert={data.alert} deliveries={ds} />}
    <ul className="dl-list">
      {ds.map((d) => (
        <li key={d.recipient_id}>
          <strong>{d.name}</strong>
          <span className={`chip ${d.channel === 'stub' ? 'chip-muted' : ''}`}>{d.channel === 'stub' ? t('console.channel.stub') : t('console.channel.telegram')}</span>
          <span className="small">
            {d.sent_at ? t('console.delivery.sent', { t: fmtTime(d.sent_at, lang) }) : t('console.delivery.notsent')}
            {' · '}
            {d.acknowledged_at ? <span className="ok-text">✓ {t('console.delivery.acked', { t: fmtTime(d.acknowledged_at, lang) })}</span> : <span className="muted">{t('console.delivery.noack')}</span>}
            {d.error && <span className="bad-text"> · {d.error}</span>}
          </span>
        </li>
      ))}
    </ul>
    </>
  );
}
