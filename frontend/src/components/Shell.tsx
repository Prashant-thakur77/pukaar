import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { History, LogOut, Menu, Moon, Phone, Sun, SunMoon, TriangleAlert, Wifi, WifiOff, X } from 'lucide-react';
import { api } from '../api';
import { useT } from '../i18n';
import { flushQueue, refreshQueueCount } from '../lib/queue';
import { useAuth, useNet, usePrefs, type ThemePref } from '../store';
import { usePoll } from '../hooks/usePoll';
import { fmtTime } from '../lib/format';
import { REPLAY_EVENT } from '../lib/events';

const NAV = [
  { to: '/live', key: 'nav.live' },
  { to: '/report', key: 'nav.report' },
  { to: '/console', key: 'nav.console' },
  { to: '/impact', key: 'nav.impact' },
] as const;

const THEMES: ThemePref[] = ['system', 'light', 'dark'];

export function Wordmark({ small }: { small?: boolean }) {
  return (
    <span className={`wordmark${small ? ' is-small' : ''}`}>
      <span className="wm-rings" aria-hidden="true">
        <i />
        <i />
      </span>
      <span lang="hi" className="wm-hi">
        पुकार
      </span>
      <span className="wm-en">Pukaar</span>
    </span>
  );
}

export function Call112({ variant = 'pill', breathe }: { variant?: 'pill' | 'fab'; breathe?: boolean }) {
  const { t } = useT();
  return (
    <a href="tel:112" className={`call112 call112-${variant}${breathe ? ' is-breathing' : ''}`} aria-label={t('shell.call112.aria')}>
      <Phone aria-hidden="true" />
      <span lang="hi" className="c112-hi">
        आपातकाल
      </span>
      <span className="c112-num">112</span>
    </a>
  );
}

function OnlineDot() {
  const { t } = useT();
  const online = useNet((s) => s.online);
  const queued = useNet((s) => s.queued);
  return (
    <span className={`net ${online ? 'is-on' : 'is-off'}`} role="status">
      {online ? <Wifi aria-hidden="true" /> : <WifiOff aria-hidden="true" />}
      <span className="net-word">{online ? t('shell.online') : t('shell.offline')}</span>
      {queued > 0 && <span className="net-q">{t('shell.queued', { n: queued })}</span>}
    </span>
  );
}

function Header() {
  const { t, lang, setLang, other } = useT();
  const theme = usePrefs((s) => s.theme);
  const setTheme = usePrefs((s) => s.setTheme);
  const user = useAuth((s) => s.user);
  const signOut = useAuth((s) => s.signOut);
  const { pathname } = useLocation();
  // The menu closes on navigation: it is only "open" for the path it was opened on.
  const [openOn, setOpenOn] = useState<string | null>(null);
  const open = openOn === pathname;
  const setOpen = (fn: (o: boolean) => boolean) => setOpenOn(fn(open) ? pathname : null);
  const ThemeIcon = theme === 'light' ? Sun : theme === 'dark' ? Moon : SunMoon;
  const nextTheme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];

  return (
    <header className={`site-header${pathname === '/' ? ' is-over-hero' : ''}`}>
      <div className="hdr-inner">
        <Link to="/" className="hdr-brand" aria-label="Pukaar पुकार — home">
          <Wordmark small />
        </Link>
        <nav className={`hdr-nav${open ? ' is-open' : ''}`} aria-label="Main">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => `hdr-link${isActive ? ' is-active' : ''}`}>
              {t(n.key)}
            </NavLink>
          ))}
          {user && (
            <button type="button" className="hdr-link hdr-signout" onClick={signOut}>
              <LogOut aria-hidden="true" /> {t('shell.signout')}
            </button>
          )}
        </nav>
        <div className="hdr-tools">
          <OnlineDot />
          <button
            type="button"
            className="icon-btn lang-btn"
            onClick={() => setLang(other)}
            aria-label={t('shell.lang')}
            title={t('shell.lang')}
          >
            <span lang={other}>{lang === 'hi' ? 'EN' : 'हि'}</span>
          </button>
          <button
            type="button"
            className="icon-btn"
            onClick={() => setTheme(nextTheme)}
            aria-label={`${t('shell.theme')}: ${t(`shell.theme.${theme}`)}`}
            title={`${t('shell.theme')}: ${t(`shell.theme.${theme}`)}`}
          >
            <ThemeIcon aria-hidden="true" />
          </button>
          <Call112 />
          <button
            type="button"
            className="icon-btn hdr-menu"
            aria-expanded={open}
            aria-label={open ? t('nav.close') : t('nav.menu')}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
          </button>
        </div>
      </div>
    </header>
  );
}

function SampleRibbon() {
  const sample = useNet((s) => s.sample);
  const { t } = useT();
  if (!sample) return null;
  return (
    <div className="sample-ribbon" role="note" title={t('shell.sample.note')}>
      <strong>SAMPLE DATA</strong> <span lang="hi">नमूना डेटा</span>
      <span className="sr-only">{t('shell.sample.note')}</span>
    </div>
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
  // The console announces replay start/reset so the banner updates at once.
  useEffect(() => {
    const on = () => void refresh();
    window.addEventListener(REPLAY_EVENT, on);
    return () => window.removeEventListener(REPLAY_EVENT, on);
  }, [refresh]);
  if (!data?.active && !data?.stale) return null;
  const pct = data.hours_total ? Math.round((data.hours_done / data.hours_total) * 100) : 0;
  return (
    <div className="replay-banner" role="status">
      <History aria-hidden="true" />
      <span>
        <strong>{t('common.replay')}</strong> ·{' '}
        {t('shell.replay', { title: (lang === 'hi' ? data.title_hi || data.title : data.title || data.title_hi) || data.source || data.scenario || '—' })}
      </span>
      {data.clock && (
        <span className="rb-clock">
          {t('shell.replay.clock')}: <b>{fmtTime(data.clock, lang)}</b>
        </span>
      )}
      {data.stale && (
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

function Footer() {
  const { t } = useT();
  return (
    <footer className="site-footer">
      <div className="ftr-inner">
        <div className="ftr-brand">
          <Wordmark />
          <p>{t('shell.footer')}</p>
        </div>
        <nav className="ftr-links" aria-label="Footer">
          {NAV.map((n) => (
            <Link key={n.to} to={n.to}>
              {t(n.key)}
            </Link>
          ))}
          <Link to="/login">{t('login.submit')}</Link>
        </nav>
        <div className="ftr-112">
          <Call112 />
          <p className="small">{t('shell.footer.data')}</p>
        </div>
      </div>
      <div className="ftr-giant" aria-hidden="true" lang="hi">
        पुकार
      </div>
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

export default function Shell() {
  const { pathname } = useLocation();
  const { lang } = useT();
  useNetworkWatch();
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [pathname]);
  const villager = pathname.startsWith('/report') || pathname.startsWith('/t/');
  return (
    <>
      <a href="#main" className="skip-link">
        {lang === 'hi' ? 'सीधे सामग्री पर जाएँ' : 'Skip to content'}
      </a>
      <Header />
      <ReplayBanner />
      <SampleRibbon />
      <main id="main" className="page" key={pathname} tabIndex={-1}>
        <Outlet />
      </main>
      {villager ? null : <Footer />}
      {pathname.startsWith('/t/') && <Call112 variant="fab" />}
    </>
  );
}
