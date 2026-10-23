import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { ChevronDown, CloudOff, History, LogOut, Menu, Moon, Phone, Sun, SunMoon, TriangleAlert, X } from 'lucide-react';
import { api } from '../api';
import { useT, type Key } from '../i18n';
import { flushQueue, refreshQueueCount } from '../lib/queue';
import { useAuth, useNet, usePrefs, type ThemePref } from '../store';
import { usePoll } from '../hooks/usePoll';
import { fmtTime } from '../lib/format';
import { REPLAY_EVENT } from '../lib/events';
import { useTour } from '../lib/tour';
import { LivePill } from './LivePill';
import { isAnswerPath, useHandOff } from '../boot/handoff';
import { useDocumentPrefs } from '../hooks/useDocumentPrefs';
import { bootState } from '../boot/protocol';
import './shell.css';

/** The guided tour's code loads only when a tour is asked for (?tour=1) or running. */
const TourHost = lazy(() => import('./Tour').then((m) => ({ default: m.TourHost })));
function TourGate() {
  const { search } = useLocation();
  const active = useTour((s) => s.active);
  if (!active && !/[?&]tour=1\b/.test(search)) return null;
  return (
    <Suspense fallback={null}>
      <TourHost />
    </Suspense>
  );
}

/** Officer pages: the live-push pill belongs in their header, not the public one. */
const isStaffRoute = (p: string) => /^\/(console|audit|roster)(\/|$)/.test(p);

type NavItem = { to: string; key: Key; sub?: Key };
/** The four public places (spec 2.3): status, report, how it works, proof and pilot. */
const PROOF: NavItem[] = [
  { to: '/proof', key: 'nav.impact', sub: 'nav.impact.sub' },
  { to: '/pilot', key: 'nav.pilot', sub: 'nav.pilot.sub' },
];

/** A header item that opens a short list (desktop). Closes on navigation, Escape and a click away. */
function NavGroup({ label, items, id }: { label: string; items: NavItem[]; id: string }) {
  const { t } = useT();
  const { pathname } = useLocation();
  const [openOn, setOpenOn] = useState<string | null>(null);
  const open = openOn === pathname;
  const ref = useRef<HTMLDivElement>(null);
  const active = items.some((g) => pathname === g.to);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpenOn(null);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpenOn(null);
    };
    document.addEventListener('pointerdown', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('pointerdown', away);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);
  return (
    <div className={`hd-group${open ? ' is-open' : ''}`} ref={ref}>
      <button
        type="button"
        className={`hd-link${active ? ' is-active' : ''}`}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpenOn(open ? null : pathname)}
      >
        {label} <ChevronDown aria-hidden="true" className="hd-caret" />
      </button>
      <div className="hd-pop" id={id}>
        {items.map((g) => (
          <NavLink key={g.to} to={g.to} end className={({ isActive }) => `hd-pop-link${isActive ? ' is-active' : ''}`}>
            <span className="hd-pop-title">{t(g.key)}</span>
            {g.sub && <span className="hd-pop-sub">{t(g.sub)}</span>}
          </NavLink>
        ))}
      </div>
    </div>
  );
}

const THEMES: ThemePref[] = ['system', 'light', 'dark'];

/** The mark: the river-blue disc, two Himalayan peaks, the river under them and the call rising from the village. */
export function PukaarMark({ size = 30 }: { size?: number }) {
  return (
    <svg className="pk-mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <circle cx="16" cy="16" r="16" fill="var(--accent)" />
      <path d="M4.5 22.5 11 12.5l3.6 5.2L19 10l8.5 12.5z" fill="var(--on-accent)" />
      <path d="M4 25.6c2 0 2-1.2 4-1.2s2 1.2 4 1.2 2-1.2 4-1.2 2 1.2 4 1.2 2-1.2 4-1.2 2 1.2 4 1.2" fill="none" stroke="var(--on-accent)" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M8.2 9.6a4 4 0 0 1 0-4.6M5.6 11.4a7.2 7.2 0 0 1 0-8.2" fill="none" stroke="var(--on-accent)" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <span className="wordmark">
      <PukaarMark size={28} />
      <span lang="hi" className="wm-hi">
        पुकार
      </span>
      <span className="wm-en" lang="en">
        Pukaar
      </span>
    </span>
  );
}

/** 112, a real tel: link, in the header on every route. The sticky bar and the footer reuse it. */
export function Call112({ compact = false }: { compact?: boolean }) {
  const { t } = useT();
  return (
    <a href="tel:112" className={`call112${compact ? ' is-compact' : ''}`} aria-label={t('shell.call112.aria')}>
      <Phone aria-hidden="true" />
      {!compact && (
        <span lang="hi" className="c112-hi">
          आपातकाल
        </span>
      )}
      <span className="c112-num">112</span>
    </a>
  );
}

function ThemeButton({ inSheet = false }: { inSheet?: boolean }) {
  const { t } = useT();
  const theme = usePrefs((s) => s.theme);
  const setTheme = usePrefs((s) => s.setTheme);
  const ThemeIcon = theme === 'light' ? Sun : theme === 'dark' ? Moon : SunMoon;
  const nextTheme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  const label = `${t('shell.theme')}: ${t(`shell.theme.${theme}`)}`;
  return (
    <button type="button" className={inSheet ? 'sheet-row' : 'hd-icon'} onClick={() => setTheme(nextTheme)} aria-label={inSheet ? undefined : label} title={label}>
      <ThemeIcon aria-hidden="true" />
      {inSheet && <span>{label}</span>}
    </button>
  );
}

/** The menu on phones: a full-height sheet, 56 px rows. */
function MenuSheet({ onClose }: { onClose: () => void }) {
  const { t } = useT();
  const user = useAuth((s) => s.user);
  const signOut = useAuth((s) => s.signOut);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', esc);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', esc);
      document.body.style.overflow = prev;
    };
  }, [onClose]);
  const row = ({ isActive }: { isActive: boolean }) => `sheet-row${isActive ? ' is-active' : ''}`;
  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-label={t('nav.menu')} id="hd-sheet">
      <div className="sheet-top">
        <Wordmark />
        <button ref={closeRef} type="button" className="hd-icon" onClick={onClose} aria-label={t('nav.close')}>
          <X aria-hidden="true" />
        </button>
      </div>
      <nav aria-label="Main" className="sheet-nav">
        <NavLink to="/" end className={row}>
          {t('nav.status')}
        </NavLink>
        <NavLink to="/report" className={row}>
          {t('nav.report')}
        </NavLink>
        <NavLink to="/live" className={row}>
          {t('nav.map')}
        </NavLink>
        <NavLink to="/how" end className={row}>
          {t('nav.how')}
        </NavLink>
        <p className="sheet-h">{t('nav.proof')}</p>
        {PROOF.map((g) => (
          <NavLink key={g.to} to={g.to} end className={row}>
            {t(g.key)}
          </NavLink>
        ))}
      </nav>
      <div className="sheet-tools">
        {user ? (
          <>
            <NavLink to="/console" className={row}>
              {user.role === 'pradhan' ? t('console.title.pradhan') : t('nav.console')}
            </NavLink>
            <button type="button" className="sheet-row" onClick={signOut}>
              <LogOut aria-hidden="true" /> <span>{t('shell.signout')}</span>
            </button>
          </>
        ) : (
          <NavLink to="/login" className={row}>
            {t('nav.officer.signin')}
          </NavLink>
        )}
        <ThemeButton inSheet />
        <a className="sheet-row" href="https://github.com/Prashant-thakur77/pukaar" target="_blank" rel="noreferrer">
          GitHub ↗
        </a>
      </div>
    </div>
  );
}

function Header() {
  const { t, lang, setLang, other } = useT();
  const user = useAuth((s) => s.user);
  const signOut = useAuth((s) => s.signOut);
  const { pathname } = useLocation();
  // The sheet closes on navigation: it is only "open" for the path it was opened on. A tap on the boot
  // painter's menu button, before this header existed, opens it now.
  const [openOn, setOpenOn] = useState<string | null>(() => (bootState()?.menu ? pathname : null));
  const open = openOn === pathname;
  const close = useCallback(() => setOpenOn(null), []);
  return (
    <header className="hd">
      <div className="hd-inner">
        <Link to="/" className="hd-brand" aria-label="पुकार Pukaar: गाँवों का हाल · village status">
          <Wordmark />
        </Link>
        <nav className="hd-nav" aria-label="Main">
          <NavLink to="/" end className={({ isActive }) => `hd-link${isActive ? ' is-active' : ''}`}>
            {t('nav.status')}
          </NavLink>
          <NavLink to="/report" className={({ isActive }) => `hd-link${isActive ? ' is-active' : ''}`}>
            {t('nav.report')}
          </NavLink>
          <NavLink to="/how" end className={({ isActive }) => `hd-link${isActive ? ' is-active' : ''}`}>
            {t('nav.how')}
          </NavLink>
          <NavGroup label={t('nav.proof')} items={PROOF} id="hd-proof" />
        </nav>
        <div className="hd-tools">
          {isStaffRoute(pathname) && <LivePill header />}
          {user ? (
            <span className="hd-desk hd-user">
              <NavLink to="/console" className={({ isActive }) => `hd-link${isActive ? ' is-active' : ''}`}>
                {user.role === 'pradhan' ? t('console.title.pradhan') : t('nav.console')}
              </NavLink>
              <button type="button" className="hd-icon" onClick={signOut} aria-label={t('shell.signout')} title={t('shell.signout')}>
                <LogOut aria-hidden="true" />
              </button>
            </span>
          ) : (
            <NavLink to="/login" className={({ isActive }) => `hd-link hd-desk${isActive ? ' is-active' : ''}`}>
              {t('nav.officer')}
            </NavLink>
          )}
          <button type="button" className="hd-icon hd-lang" onClick={() => setLang(other)} aria-label={t('shell.lang')} title={t('shell.lang')}>
            <span lang={other}>{lang === 'hi' ? 'EN' : 'हि'}</span>
          </button>
          <span className="hd-desk">
            <ThemeButton />
          </span>
          <Call112 />
          <button
            type="button"
            className="hd-icon hd-menu"
            aria-expanded={open}
            aria-controls="hd-sheet"
            aria-label={t('nav.menu')}
            onClick={() => setOpenOn(pathname)}
          >
            <Menu aria-hidden="true" />
          </button>
        </div>
      </div>
      {open && <MenuSheet onClose={close} />}
    </header>
  );
}

/** Connectivity only by exception: a full-width line under the header when the phone is offline. */
function OfflineBanner() {
  const { t } = useT();
  const online = useNet((s) => s.online);
  const queued = useNet((s) => s.queued);
  if (online && queued === 0) return null;
  return (
    <div className="offline-banner" role="status">
      <CloudOff aria-hidden="true" />
      <span>
        {online ? null : t('shell.offline.banner')}
        {queued > 0 && <> {online ? '' : '· '}{t('shell.queued', { n: queued })}</>}
      </span>
    </div>
  );
}

function SampleRibbon() {
  const sample = useNet((s) => s.sample);
  const { t } = useT();
  if (!sample) return null;
  return (
    <aside className="sample-ribbon" aria-label="Sample data" title={t('shell.sample.note')}>
      <strong lang="en">Sample data</strong> <span lang="hi">नमूना डेटा</span>
      <span className="sr-only">{t('shell.sample.note')}</span>
    </aside>
  );
}

const REPLAY_ROUTES = ['/live', '/console', '/village', '/audit'];

function ReplayBanner() {
  const { pathname } = useLocation();
  const on = REPLAY_ROUTES.some((r) => pathname.startsWith(r));
  if (!on) return null;
  return <ReplayBannerInner />;
}

function ReplayBannerInner() {
  const { t, lang } = useT();
  const { data, refresh } = usePoll(() => api.replayStatus(), [], 15000);
  const officer = useAuth((s) => s.user?.role === 'officer');
  // The console announces replay start/reset so the banner updates at once.
  useEffect(() => {
    const on = () => void refresh();
    window.addEventListener(REPLAY_EVENT, on);
    return () => window.removeEventListener(REPLAY_EVENT, on);
  }, [refresh]);
  // Finished: the worker stopped at the last hour, but replay data stays until Reset.
  // Only officers (who can press Reset) see it after it ends; the public sees it while it runs.
  const finished = Boolean(officer && data && !data.active && data.hours_total > 0 && data.hours_done >= data.hours_total);
  if (!data || (!data.active && !data.stale && !finished)) return null;
  const pct = data.hours_total ? Math.round((data.hours_done / data.hours_total) * 100) : 0;
  const title = (lang === 'hi' ? data.title_hi || data.title : data.title || data.title_hi) || data.source || data.scenario || '—';
  return (
    <div className={`replay-banner${finished ? ' is-finished' : ''}`} role="status">
      <History aria-hidden="true" />
      <span>
        <strong>{t('common.replay')}</strong> · {finished ? t('shell.replay.done') : t('shell.replay', { title })}
      </span>
      {data.clock && (
        <span className="rb-clock">
          {t('shell.replay.clock')}: <b>{fmtTime(data.clock, lang)}</b>
        </span>
      )}
      {data.stale && !finished && (
        <span className="rb-stale">
          <TriangleAlert aria-hidden="true" /> {t('shell.replay.stale')}
        </span>
      )}
      <span className="rb-bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={t('shell.replay.clock')}>
        <i style={{ width: `${pct}%` }} />
      </span>
    </div>
  );
}

/** One slim band: the line, 112, two link columns and the data credits. No giant wordmark. */
function Footer() {
  const { t, lang } = useT();
  const user = useAuth((s) => s.user);
  const signOut = useAuth((s) => s.signOut);
  const en = lang === 'en';
  return (
    <footer className="ft">
      <div className="ft-inner">
        <div className="ft-brand">
          <p className="ft-line" lang="hi">
            नदी से पहले, गाँव तक।
          </p>
          <p className="ft-lead">{t('shell.footer')}</p>
          <Call112 />
        </div>
        <nav className="ft-col" aria-label={en ? 'Use it' : 'इस्तेमाल करें'}>
          <Link to="/">{t('nav.status')}</Link>
          <Link to="/report">{t('nav.report')}</Link>
          <Link to="/live">{t('nav.map')}</Link>
          <a href="https://t.me/PukaarRescuebot" target="_blank" rel="noreferrer">
            {en ? 'Alerts on Telegram' : 'Telegram पर चेतावनी'} ↗
          </a>
          {user ? (
            <button type="button" className="ft-signout" onClick={signOut}>
              <LogOut aria-hidden="true" /> {t('shell.signout')}
            </button>
          ) : (
            <Link to="/login">{t('nav.officer.signin')}</Link>
          )}
        </nav>
        <nav className="ft-col" aria-label={en ? 'How it works' : 'कैसे काम करता है'}>
          <Link to="/how">{t('nav.how')}</Link>
          <Link to="/how#agents">{t('nav.agents')}</Link>
          <Link to="/how#sensors">{t('nav.sensors')}</Link>
          <Link to="/proof">{t('nav.impact')}</Link>
          <Link to="/pilot">{t('nav.pilot')}</Link>
          <a href="https://github.com/Prashant-thakur77/pukaar" target="_blank" rel="noreferrer">
            GitHub ↗
          </a>
        </nav>
      </div>
      <p className="ft-credits">
        <span>{t('shell.footer.data')}</span> <span>© 2026 Pukaar · {en ? 'Built in Himachal' : 'हिमाचल में बना'}</span>
      </p>
    </footer>
  );
}

function useNetworkWatch() {
  const setOnline = useNet((s) => s.setOnline);
  useEffect(() => {
    const on = () => {
      setOnline(true);
      void flushQueue();
    };
    const off = () => setOnline(false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    void refreshQueueCount().then((n) => {
      if (n > 0 && navigator.onLine) void flushQueue();
    });
    return () => {
      window.removeEventListener('online', on);
      window.removeEventListener('offline', off);
    };
  }, [setOnline]);
}

/** The visitor asked their system for less motion: jump instead of gliding. */
function reducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;
}

/** The one-tap approval link (spec 4.13): the mark and 112 only; no menu, no footer, nothing to wander into. */
export function BareShell() {
  const { lang } = useT();
  useHandOff(true);
  useDocumentPrefs();
  return (
    <>
      <a href="#main" className="skip-link">
        {lang === 'hi' ? 'सीधे सामग्री पर जाएँ' : 'Skip to content'}
      </a>
      <header className="hd">
        <div className="hd-inner">
          <span className="hd-brand">
            <Wordmark />
          </span>
          <div className="hd-tools">
            <Call112 />
          </div>
        </div>
      </header>
      <main id="main" className="page" tabIndex={-1}>
        <Outlet />
      </main>
    </>
  );
}

export default function Shell() {
  const { pathname, hash } = useLocation();
  // The boot painter draws the answer pages itself; every other page takes over on its first frame.
  useHandOff(!isAnswerPath(pathname));
  const { lang } = useT();
  useNetworkWatch();
  useDocumentPrefs();
  const lastPath = useRef(pathname);
  useEffect(() => {
    // Links like /#story land on that section; everything else starts at the top. A jump within
    // the same page glides there; a new page starts at once (and nothing glides with reduced motion).
    const samePage = lastPath.current === pathname;
    lastPath.current = pathname;
    const behavior: ScrollBehavior = samePage && !reducedMotion() ? 'smooth' : 'instant';
    const target = hash ? document.getElementById(hash.slice(1)) : null;
    if (!target) {
      window.scrollTo({ top: 0, behavior: 'instant' });
      return;
    }
    target.scrollIntoView({ behavior, block: 'start' });
    // Data arriving above the section can push it down; settle once more unless the reader scrolled.
    const landed = window.scrollY;
    const tm = setTimeout(() => {
      if (window.scrollY === landed) target.scrollIntoView({ behavior, block: 'start' });
    }, 900);
    return () => clearTimeout(tm);
  }, [pathname, hash]);
  const villager = pathname.startsWith('/report') || pathname.startsWith('/t/');
  return (
    <>
      <a href="#main" className="skip-link">
        {lang === 'hi' ? 'सीधे सामग्री पर जाएँ' : 'Skip to content'}
      </a>
      <Header />
      <OfflineBanner />
      <ReplayBanner />
      <SampleRibbon />
      <main id="main" className="page" key={pathname} tabIndex={-1}>
        <Outlet />
      </main>
      {villager ? null : <Footer />}
      <TourGate />
    </>
  );
}
