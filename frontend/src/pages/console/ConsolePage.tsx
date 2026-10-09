import { Link, Navigate, useLocation } from 'react-router-dom';
import { Bell, FileText, History, LayoutList, Megaphone, ScrollText, Send, Sparkles } from 'lucide-react';
import { api } from '../../api';
import { AlertStatusChip, DeliveryChips } from '../../components/Chips';
import { LevelBadge } from '../../components/Level';
import { Call112 } from '../../components/Shell';
import { usePoll } from '../../hooks/usePoll';
import { useT } from '../../i18n';
import { fmtAgo } from '../../lib/format';
import { useAuth } from '../../store';
import { Approvals } from './Approvals';
import { Ask } from './Ask';
import { Directives } from './Directives';
import { Replay } from './Replay';
import { ReportFeed } from './ReportFeed';
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
  const villages = usePoll(() => api.villages(), []);
  const pending = usePoll(() => api.alerts({ status: 'pending' }), []);
  const recent = usePoll(() => api.alerts(), []);
  const reports = usePoll(() => api.reports(), []);
  const directives = usePoll(() => api.directives(), []);
  const replay = usePoll(() => api.replayStatus(), []);
  const vs = villages.data ?? [];
  const pendingN = pending.data?.length ?? 0;

  const refreshAlerts = () => {
    void pending.refresh();
    void recent.refresh();
    void villages.refresh();
  };

  const tabs = [
    { href: '#approvals', label: t('console.tab.approvals'), icon: Bell, badge: pendingN },
    { href: '#queue', label: t('console.tab.queue'), icon: LayoutList },
    { href: '#reports', label: t('console.tab.reports'), icon: FileText },
    { href: '#ask', label: t('console.tab.ask'), icon: Sparkles },
    { href: '#act', label: t('console.tab.act'), icon: Megaphone },
  ];

  return (
    <div className="console">
      <header className="console-head">
        <div className="wrap-wide ch-inner">
          <div>
            <p className="eyebrow">{t('console.title')}</p>
            <h1 className="display-3">
              {user ? t('console.signed.as', { u: user.username, r: user.role }) : t('console.title')}
            </h1>
          </div>
          <div className="ch-tools">
            <Link to="/audit" className="btn btn-ghost btn-press">
              <ScrollText aria-hidden="true" /> {t('console.audit')}
            </Link>
            <Call112 />
          </div>
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
        <section id="approvals" className="panel panel-approvals" aria-labelledby="ap-h">
          <h2 id="ap-h" className="panel-title">
            <Bell aria-hidden="true" /> {t('console.pending')}
            {pendingN > 0 && <span className="badge badge-pulse">{pendingN}</span>}
          </h2>
          <Approvals poll={pending} onChange={refreshAlerts} />
        </section>

        <section id="queue" className="panel panel-queue" aria-labelledby="q-h">
          <h2 id="q-h" className="panel-title">
            <LayoutList aria-hidden="true" /> {t('console.queue')}
          </h2>
          <VillageQueue poll={villages} />
        </section>

        <section id="ask" className="panel panel-ask" aria-labelledby="ask-h">
          <h2 id="ask-h" className="panel-title">
            <Sparkles aria-hidden="true" /> {t('console.ask')}
          </h2>
          <Ask villages={vs} />
        </section>

        <section id="reports" className="panel panel-reports" aria-labelledby="rp-h">
          <h2 id="rp-h" className="panel-title">
            <FileText aria-hidden="true" /> {t('console.reports')}
          </h2>
          <ReportFeed poll={reports} villages={vs} />
        </section>

        <div id="act" className="panel-stack">
          <section className="panel" aria-labelledby="dir-h">
            <h2 id="dir-h" className="panel-title">
              <Megaphone aria-hidden="true" /> {t('console.directive')}
            </h2>
            <Directives villages={vs} poll={directives} />
          </section>
          <section className="panel" aria-labelledby="rep-h">
            <h2 id="rep-h" className="panel-title">
              <History aria-hidden="true" /> {t('console.replay')}
            </h2>
            <Replay poll={replay} />
          </section>
          <section className="panel" aria-labelledby="tg-h">
            <h2 id="tg-h" className="panel-title">
              <Send aria-hidden="true" /> {t('console.tg')}
            </h2>
            <TelegramLink />
          </section>
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
                  <li key={a.id} className={`ra-row lv-${a.level}`}>
                    <div className="ac-top">
                      <LevelBadge level={a.level} size="sm" both={false} lang={lang} />
                      <Link to={`/village/${a.village_id}`} className="ra-name">
                        {lang === 'hi' ? a.village_name_hi : a.village_name}
                      </Link>
                      <AlertStatusChip status={a.status} />
                    </div>
                    <DeliveryChips approved={a.approved} delivered={a.delivered_count} acked={a.acknowledged_count} status={a.status} />
                    <p className="small muted">
                      {fmtAgo(a.created_at, lang)} ·{' '}
                      <Link className="link" to={`/audit?resource=${encodeURIComponent(a.id)}`}>
                        {t('console.audit')}
                      </Link>
                    </p>
                  </li>
                ))}
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}
