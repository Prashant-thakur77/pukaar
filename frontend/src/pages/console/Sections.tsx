import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, BellRing, Send } from 'lucide-react';
import { api } from '../../api';
import { DataStatusNote, LiveLevelNote, ShownLevel } from '../../components/DataStatus';
import { Skeleton } from '../../components/States';
import { usePoll } from '../../hooks/usePoll';
import { useT } from '../../i18n';
import { levelIsKnown } from '../../lib/dataStatus';
import { fmtAgo } from '../../lib/format';
import { useConsole } from './consoleContext';
import { Directives } from './Directives';
import { PushAlerts } from './PushAlerts';
import { Replay } from './Replay';
import { ReportFeed } from './ReportFeed';
import { RollCallPanel } from './RollCall';
import { SystemCard } from './System';
import { TelegramLink } from './TelegramLink';
import { VillageQueue } from './VillageQueue';
import { REPLAY_EVENT } from '../../lib/events';

/* The console's other sections: one job each, the existing panels in the console's frame. */

export function Page({ title, lead, children, wide = false }: { title: string; lead?: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={`cs-page${wide ? ' is-wide' : ''}`}>
      <header className="cs-page-head">
        <h1 className="cs-page-h">{title}</h1>
        {lead && <p className="cs-page-lead">{lead}</p>}
      </header>
      {children}
    </div>
  );
}

export function VillagesSection() {
  const { t } = useT();
  const c = useConsole();
  return (
    <Page title={t('cs.nav.villages')} lead={t('console.queue')}>
      <VillageQueue poll={c.villages} />
    </Page>
  );
}

/** The pradhan's own village first: its level, how long, and the three things they look after. */
export function MineSection() {
  const { t, lang } = useT();
  const c = useConsole();
  const mine = (c.villages.data ?? []).filter((v) => c.villageIds.includes(v.id));
  return (
    <Page title={t('cs.nav.mine')} lead={t('console.pradhan.note')}>
      {c.villages.loading && !c.villages.data ? (
        <Skeleton lines={3} />
      ) : !mine.length ? (
        <p className="muted">{t('console.mine.none')}</p>
      ) : (
        <ul className="myv-list">
          {mine.map((v) => (
            <li key={v.id} className={`myv-row lv-${levelIsKnown(v) ? v.level : 'nodata'}`}>
              <p className="myv-name">
                <span lang="hi">{v.name_hi}</span> <span className="tk-en">{v.name}</span>
              </p>
              <p className="myv-level">
                <ShownLevel v={v} size="md" plain />
                {v.level_since && <span className="small muted">{t('village.since', { t: fmtAgo(v.level_since, lang) })}</span>}
              </p>
              <DataStatusNote v={v} />
              <LiveLevelNote v={v} />
              <ul className="myv-links">
                <li>
                  <Link to={`/village/${v.id}#where`}>
                    {t('console.mine.shelters')} <ArrowRight aria-hidden="true" />
                  </Link>
                </li>
                <li>
                  <Link to="/console/rollcall">
                    {t('console.mine.rollcall')} <ArrowRight aria-hidden="true" />
                  </Link>
                </li>
                <li>
                  <Link to={`/village/${v.id}`}>
                    {t('console.mine.page')} <ArrowRight aria-hidden="true" />
                  </Link>
                </li>
              </ul>
            </li>
          ))}
        </ul>
      )}
    </Page>
  );
}

export function ReportsSection() {
  const { t } = useT();
  const c = useConsole();
  return (
    <Page title={t('cs.nav.reports')} wide>
      <ReportFeed poll={c.reports} villages={c.villages.data ?? []} canEdit={c.officer} />
    </Page>
  );
}

export function RollCallSection() {
  const { t } = useT();
  const c = useConsole();
  return (
    <Page title={t('rollcall.title')}>
      <RollCallPanel villages={c.villages.data ?? []} villageIds={c.officer ? null : c.villageIds} />
    </Page>
  );
}

export function DirectivesSection() {
  const { t } = useT();
  const c = useConsole();
  const directives = usePoll(() => api.directives(), []);
  return (
    <Page title={t('console.directive')}>
      <Directives villages={c.villages.data ?? []} poll={directives} />
    </Page>
  );
}

export function ReplaySection() {
  const { t } = useT();
  const c = useConsole();
  const replay = usePoll(() => api.replayStatus(), []);
  return (
    <Page title={t('console.replay')} lead={t('demo.lead')}>
      <section className="cs-card">
        <Replay
          poll={replay}
          canControl={c.officer}
          onChanged={() => {
            c.refreshAlerts();
            window.dispatchEvent(new Event(REPLAY_EVENT));
          }}
        />
      </section>
    </Page>
  );
}

export function SystemSection() {
  const { t } = useT();
  const c = useConsole();
  return (
    <Page title={t('system.title')} lead={t('demo.lead')}>
      <section className="cs-card">
        <SystemCard poll={c.health} />
      </section>
    </Page>
  );
}

export function SettingsSection() {
  const { t } = useT();
  const c = useConsole();
  return (
    <Page title={t('settings.title')} lead={t('settings.lead')}>
      <section className="cs-card" aria-labelledby="set-push">
        <h2 id="set-push" className="cs-card-h">
          <BellRing aria-hidden="true" /> {t('console.push')}
        </h2>
        <PushAlerts />
      </section>
      {c.officer && (
        <section className="cs-card" aria-labelledby="set-tg">
          <h2 id="set-tg" className="cs-card-h">
            <Send aria-hidden="true" /> {t('console.tg')}
          </h2>
          <TelegramLink />
        </section>
      )}
      <section className="cs-card" aria-labelledby="set-view">
        <h2 id="set-view" className="cs-card-h">
          {t('settings.view')}
        </h2>
        <label className="cs-check">
          <input type="checkbox" checked={c.showDemo} onChange={(e) => c.setShowDemo(e.target.checked)} />
          <span>{t('settings.demo')}</span>
        </label>
      </section>
    </Page>
  );
}
