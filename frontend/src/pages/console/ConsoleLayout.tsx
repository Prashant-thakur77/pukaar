import { useCallback, useEffect, useId, useMemo, useRef, useState, type ComponentType } from 'react';
import { Link, Navigate, NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  CalendarClock,
  Cog,
  FileText,
  HeartHandshake,
  History,
  Home,
  Inbox as InboxIcon,
  LayoutList,
  LogOut,
  Megaphone,
  Menu,
  Moon,
  QrCode,
  ScrollText,
  Server,
  Sparkles,
  Sun,
  SunMoon,
  UserPlus,
  X,
} from 'lucide-react';
import { api } from '../../api';
import { useHandOff } from '../../boot/handoff';
import { LivePill } from '../../components/LivePill';
import { Call112, PukaarMark } from '../../components/Shell';
import { useDocumentPrefs } from '../../hooks/useDocumentPrefs';
import { usePoll, type PollState } from '../../hooks/usePoll';
import { useT, type Key } from '../../i18n';
import { CHANNELS } from '../../lib/live';
import { DISTRICT_HI } from '../../lib/answerText';
import { readLS, useAuth, usePrefs, writeLS, type ThemePref } from '../../store';
import { ConsoleCtx, useConsole, type ConsoleData } from './consoleContext';
import '../../styles/console.css';
import '../../styles/console-shell.css';

/*
 * The officer's console (spec 4.9): its own header and a rail of sections instead of one long page.
 *   Inbox · Villages · Reports · Roll-call · Directives · Ask | Roster · Audit | Demo: Replay · Live demo · System | Settings
 * On a phone the rail becomes four bottom tabs (Inbox, Villages, Reports, More). The demo group is for the public
 * demo accounts (and a local stack, or anyone who turns it on in Settings): it never sits in the inbox.
 */

const DEMO_KEY = 'pukaar.console.demo';
const DISTRICT_KEY = 'pukaar.console.district';
const OPEN_REPORT = new Set(['received', 'transcribing', 'unverified', 'verified_auto', 'verified']);

export default function ConsoleLayout() {
  const token = useAuth((s) => s.token);
  const loc = useLocation();
  // Signed out: the sign-in page, then back here. The boot painter's page goes either way.
  useHandOff(true);
  if (!token) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
  return <Console />;
}

function Console() {
  useDocumentPrefs();
  const user = useAuth((s) => s.user);
  const me = usePoll(() => api.me(), [], 0);
  const role = me.data?.role ?? user?.role ?? 'officer';
  const username = me.data?.username ?? user?.username ?? '';
  const officer = role !== 'pradhan';
  const judge = /^judge/.test(username);
  const villages = usePoll(() => api.villages(), [], 15000, { live: [CHANNELS.levels, CHANNELS.rollcall] });
  const pending = usePoll(() => api.alerts({ status: 'pending' }), [], 15000, { live: [CHANNELS.alerts, CHANNELS.officer] });
  const alerts = usePoll(() => api.alerts(), [], 15000, { live: [CHANNELS.alerts, CHANNELS.deliveries] });
  const health = usePoll(() => api.health(), [], 60000);
  const roster = usePoll(() => (officer ? api.roster() : Promise.reject(new Error('pradhan'))), [officer], 120000);
  const reports = usePoll(() => api.reports(), [], 30000);
  const [demoPref, setDemoPref] = useState<boolean | null>(() => {
    const v = readLS(DEMO_KEY);
    return v === '1' ? true : v === '0' ? false : null;
  });
  // The demo group is on by default for the demo accounts and on a local stack; anyone can choose in Settings.
  const showDemo = demoPref ?? (judge || health.data?.mode === 'local');
  const setShowDemo = useCallback((on: boolean) => {
    writeLS(DEMO_KEY, on ? '1' : '0');
    setDemoPref(on);
  }, []);
  // The district selector (spec 4.9): one district at a time, or all; remembered on this device.
  const [districtPref, setDistrictPref] = useState(() => readLS(DISTRICT_KEY) ?? '');
  const districts = useMemo(() => [...new Set((villages.data ?? []).map((v) => v.district))].sort(), [villages.data]);
  const district = districts.includes(districtPref) ? districtPref : '';
  const setDistrict = useCallback((d: string) => {
    writeLS(DISTRICT_KEY, d);
    setDistrictPref(d);
  }, []);
  const inDistrict = useMemo(() => {
    if (!district) return null;
    return new Set((villages.data ?? []).filter((v) => v.district === district).map((v) => v.id));
  }, [district, villages.data]);
  const only = <T extends { village_id: string }>(p: PollState<T[]>): PollState<T[]> =>
    inDistrict && p.data ? { ...p, data: p.data.filter((x) => inDistrict.has(x.village_id)) } : p;
  const refreshAlerts = useCallback(() => {
    void pending.refresh();
    void alerts.refresh();
    void villages.refresh();
  }, [pending, alerts, villages]);
  const data: ConsoleData = {
    username,
    role,
    officer,
    judge,
    villageIds: me.data?.village_ids ?? user?.village_ids ?? [],
    villages: inDistrict && villages.data ? { ...villages, data: villages.data.filter((v) => inDistrict.has(v.id)) } : villages,
    pending: only(pending),
    alerts: only(alerts),
    health,
    roster,
    reports: only(reports),
    showDemo,
    setShowDemo,
    refreshAlerts,
    district,
    districts,
    setDistrict,
  };
  const pendingAll = data.pending;
  const pendingN = (pendingAll.data ?? []).filter((a) => a.status === 'pending').length;
  const openReports = (data.reports.data ?? []).filter((r) => OPEN_REPORT.has(r.state)).length;
  return (
    <ConsoleCtx.Provider value={data}>
      <div className={`cs${officer ? '' : ' is-pradhan'}`}>
        <a href="#cs-main" className="skip-link">
          <SkipText />
        </a>
        <ConsoleHeader pendingN={pendingN} />
        <Rail pendingN={pendingN} openReports={openReports} />
        <main id="cs-main" className="cs-main" tabIndex={-1}>
          <Outlet />
        </main>
        <BottomTabs pendingN={pendingN} openReports={openReports} />
      </div>
    </ConsoleCtx.Provider>
  );
}

function SkipText() {
  const { t } = useT();
  return <>{t('nav.skip')}</>;
}

/* ---------- the sections ---------- */

interface Item {
  to: string;
  key: Key;
  icon: ComponentType<{ 'aria-hidden'?: boolean | 'true' }>;
  badge?: number;
  urgent?: boolean;
}

function useItems(pendingN: number, openReports: number): { main: Item[]; work: Item[]; demo: Item[]; end: Item[] } {
  const c = useConsole();
  const main: Item[] = [
    ...(c.officer ? [] : [{ to: '/console/mine', key: 'cs.nav.mine' as Key, icon: Home }]),
    ...(c.role === 'pradhan' ? [{ to: '/console/enrol', key: 'cs.nav.enrol' as Key, icon: UserPlus }] : []),
    { to: '/console/inbox', key: 'cs.nav.inbox', icon: InboxIcon, badge: pendingN, urgent: (c.pending.data ?? []).some((a) => a.status === 'pending' && a.level === 'critical') },
    { to: '/console/villages', key: 'cs.nav.villages', icon: LayoutList },
    { to: '/console/reports', key: 'cs.nav.reports', icon: FileText, badge: openReports },
    { to: '/console/rollcall', key: 'cs.nav.rollcall', icon: HeartHandshake },
    ...(c.officer
      ? [
          { to: '/console/directives', key: 'cs.nav.directives' as Key, icon: Megaphone },
          { to: '/console/ask', key: 'cs.nav.ask' as Key, icon: Sparkles },
        ]
      : []),
  ];
  const work: Item[] = c.officer
    ? [
        { to: '/console/roster', key: 'cs.nav.roster', icon: CalendarClock },
        { to: '/console/enrol', key: 'cs.nav.enrol', icon: UserPlus },
        { to: '/console/audit', key: 'cs.nav.audit', icon: ScrollText },
      ]
    : [];
  const demo: Item[] = c.showDemo
    ? [
        { to: '/console/replay', key: 'cs.nav.replay', icon: History },
        ...(c.role === 'officer' || c.role === 'state_operator' ? [{ to: '/console/demo', key: 'cs.nav.livedemo' as Key, icon: QrCode }] : []),
        { to: '/console/system', key: 'cs.nav.system', icon: Server },
      ]
    : [];
  const end: Item[] = [{ to: '/console/settings', key: 'cs.nav.settings', icon: Cog }];
  return { main, work, demo, end };
}

function RailLink({ item }: { item: Item }) {
  const { t } = useT();
  const Icon = item.icon;
  return (
    <NavLink to={item.to} className={({ isActive }) => `cs-rail-link${isActive ? ' is-active' : ''}`}>
      <Icon aria-hidden="true" />
      <span className="cs-rail-word">{t(item.key)}</span>
      {item.badge ? (
        <span className={`cs-count${item.urgent ? ' is-urgent' : ''}`} aria-label={`${item.badge}`}>
          {item.badge}
        </span>
      ) : null}
    </NavLink>
  );
}

function Rail({ pendingN, openReports }: { pendingN: number; openReports: number }) {
  const { t } = useT();
  const { main, work, demo, end } = useItems(pendingN, openReports);
  return (
    <nav className="cs-rail" aria-label={t('cs.nav.label')}>
      <ul>
        {main.map((i) => (
          <li key={i.to}>
            <RailLink item={i} />
          </li>
        ))}
      </ul>
      {work.length > 0 && (
        <ul>
          {work.map((i) => (
            <li key={i.to}>
              <RailLink item={i} />
            </li>
          ))}
        </ul>
      )}
      {demo.length > 0 && (
        <div className="cs-rail-group">
          <p className="cs-rail-h" id="cs-demo-h">
            {t('cs.nav.demo')}
          </p>
          <ul aria-labelledby="cs-demo-h">
            {demo.map((i) => (
              <li key={i.to}>
                <RailLink item={i} />
              </li>
            ))}
          </ul>
        </div>
      )}
      <ul className="cs-rail-end">
        {end.map((i) => (
          <li key={i.to}>
            <RailLink item={i} />
          </li>
        ))}
        <li>
          <Link to="/" className="cs-rail-link cs-rail-public">
            <span className="cs-rail-word">{t('cs.nav.public')} ↗</span>
          </Link>
        </li>
      </ul>
    </nav>
  );
}

/** Phones: four tabs at the thumb (Inbox, Villages, Reports, More); More opens the rest as a sheet. */
function BottomTabs({ pendingN, openReports }: { pendingN: number; openReports: number }) {
  const { t } = useT();
  const { main, work, demo, end } = useItems(pendingN, openReports);
  const { pathname } = useLocation();
  const [openOn, setOpenOn] = useState<string | null>(null);
  const open = openOn === pathname;
  const tabs = main.filter((i) => ['/console/inbox', '/console/villages', '/console/reports', '/console/mine'].includes(i.to)).slice(0, 3);
  const rest = [...main.filter((i) => !tabs.includes(i)), ...work, ...demo, ...end];
  const restActive = rest.some((i) => pathname.startsWith(i.to));
  return (
    <>
      <nav className="cs-tabs" aria-label={t('cs.nav.label')}>
        {tabs.map((i) => {
          const Icon = i.icon;
          return (
            <NavLink key={i.to} to={i.to} className={({ isActive }) => `cs-tab${isActive ? ' is-active' : ''}`}>
              <span className="cs-tab-icon">
                <Icon aria-hidden="true" />
                {i.badge ? <span className={`cs-count${i.urgent ? ' is-urgent' : ''}`}>{i.badge}</span> : null}
              </span>
              <span>{t(i.key)}</span>
            </NavLink>
          );
        })}
        <button type="button" className={`cs-tab${restActive ? ' is-active' : ''}`} aria-expanded={open} aria-controls="cs-more" onClick={() => setOpenOn(pathname)}>
          <span className="cs-tab-icon">
            <Menu aria-hidden="true" />
          </span>
          <span>{t('cs.nav.more')}</span>
        </button>
      </nav>
      {open && <MoreSheet items={rest} onClose={() => setOpenOn(null)} />}
    </>
  );
}

function MoreSheet({ items, onClose }: { items: Item[]; onClose: () => void }) {
  const { t } = useT();
  const signOut = useAuth((s) => s.signOut);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', esc);
    return () => document.removeEventListener('keydown', esc);
  }, [onClose]);
  return (
    <div className="sheet cs-sheet" role="dialog" aria-modal="true" aria-label={t('cs.nav.more')} id="cs-more">
      <div className="sheet-top">
        <span className="cs-brand">
          <PukaarMark size={28} /> <span className="cs-brand-word">{t('cs.brand')}</span>
        </span>
        <button ref={closeRef} type="button" className="hd-icon" onClick={onClose} aria-label={t('nav.close')}>
          <X aria-hidden="true" />
        </button>
      </div>
      <nav className="sheet-nav" aria-label={t('cs.nav.more')}>
        {items.map((i) => {
          const Icon = i.icon;
          return (
            <NavLink key={i.to} to={i.to} className={({ isActive }) => `sheet-row${isActive ? ' is-active' : ''}`}>
              <Icon aria-hidden="true" /> {t(i.key)}
              {i.badge ? <span className="cs-count">{i.badge}</span> : null}
            </NavLink>
          );
        })}
        <Link to="/" className="sheet-row">
          {t('cs.nav.public')} ↗
        </Link>
        <button type="button" className="sheet-row" onClick={signOut}>
          <LogOut aria-hidden="true" /> {t('shell.signout')}
        </button>
      </nav>
    </div>
  );
}

/* ---------- the header ---------- */

const THEMES: ThemePref[] = ['system', 'light', 'dark'];

function OnDuty() {
  const { t } = useT();
  const c = useConsole();
  const now = c.roster.data?.now ?? [];
  const d = now.find((x) => x.primary) ?? null;
  const text = useMemo(() => {
    if (!d?.primary) return c.roster.data ? t('cs.onduty.none') : null;
    const until = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(d.ends_at));
    return t('cs.onduty', { who: d.primary, shift: t(d.shift === 'day' ? 'cs.shift.day' : 'cs.shift.night'), until: `${until} IST` });
  }, [d, c.roster.data, t]);
  if (!c.officer || !text) return null;
  return <p className="cs-duty">{text}</p>;
}

/** "ज़िला: मंडी ▾": the console shows one district, or all of them. Only when there is more than one. */
function DistrictPick() {
  const { lang } = useT();
  const c = useConsole();
  const id = useId();
  if (c.districts.length < 2) return null;
  const name = (d: string) => (lang === 'hi' ? DISTRICT_HI[d] ?? d : d);
  return (
    <label className="cs-district" htmlFor={id}>
      <span className="cs-district-k">{lang === 'hi' ? 'ज़िला' : 'District'}</span>
      <span className="select-wrap">
        <select id={id} value={c.district} onChange={(e) => c.setDistrict(e.target.value)}>
          <option value="">{lang === 'hi' ? 'सभी ज़िले' : 'All districts'}</option>
          {c.districts.map((d) => (
            <option key={d} value={d}>
              {name(d)}
            </option>
          ))}
        </select>
      </span>
    </label>
  );
}

function ConsoleHeader({ pendingN }: { pendingN: number }) {
  const { t, lang, setLang, other } = useT();
  const c = useConsole();
  const signOut = useAuth((s) => s.signOut);
  const theme = usePrefs((s) => s.theme);
  const setTheme = usePrefs((s) => s.setTheme);
  const ThemeIcon = theme === 'light' ? Sun : theme === 'dark' ? Moon : SunMoon;
  const nextTheme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  const themeLabel = `${t('shell.theme')}: ${t(`shell.theme.${theme}`)}`;
  // The tab's title counts what waits, so a background tab still says it.
  useEffect(() => {
    const base = `${t('cs.brand')} · पुकार Pukaar`;
    document.title = pendingN ? `(${pendingN}) ${base}` : base;
  }, [pendingN, t]);
  return (
    <header className="cs-hd">
      <div className="cs-hd-in">
        <Link to="/console/inbox" className="cs-brand" aria-label={`पुकार Pukaar ${t('cs.brand')}`}>
          <PukaarMark size={28} />
          <span className="wm-hi" lang="hi">
            पुकार
          </span>
          <span className="cs-brand-word">{c.officer ? t('cs.brand') : t('console.title.pradhan')}</span>
        </Link>
        <DistrictPick />
        <OnDuty />
        <div className="cs-tools">
          <LivePill header />
          <button type="button" className="hd-icon hd-lang" onClick={() => setLang(other)} aria-label={t('shell.lang')} title={t('shell.lang')}>
            <span lang={other}>{lang === 'hi' ? 'EN' : 'हि'}</span>
          </button>
          <button type="button" className="hd-icon cs-desk" onClick={() => setTheme(nextTheme)} aria-label={themeLabel} title={themeLabel}>
            <ThemeIcon aria-hidden="true" />
          </button>
          <span className="cs-user cs-desk" title={c.judge ? t('cs.demo.badge') : undefined}>
            <span className="cs-user-name">{c.username}</span>
            {c.judge && <span className="cs-demo-chip">demo</span>}
          </span>
          <button type="button" className="hd-icon cs-desk" onClick={signOut} aria-label={t('shell.signout')} title={t('shell.signout')}>
            <LogOut aria-hidden="true" />
          </button>
          <Call112 compact />
        </div>
      </div>
    </header>
  );
}
