import { Component, lazy, Suspense, type ComponentType, type ReactNode } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import Shell, { BareShell } from './components/Shell';
import { SkeletonCards } from './components/States';

/**
 * After a deploy, a tab (or a service worker) still running the previous build asks for chunk files that no
 * longer exist. Reload once to pick up the new build instead of rendering a blank page.
 */
function lazyPage<T extends ComponentType>(load: () => Promise<{ default: T }>) {
  return lazy(() =>
    load().catch((err) => {
      try {
        if (!sessionStorage.getItem('pukaar.chunk-reload')) {
          sessionStorage.setItem('pukaar.chunk-reload', '1');
          window.location.reload();
          return new Promise<{ default: T }>(() => {});
        }
      } catch {
        /* storage blocked: fall through to the error boundary */
      }
      throw err;
    }),
  );
}

/** Anything that still fails shows a way out, never a white screen. */
class PageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="wrap" style={{ padding: '64px 16px', textAlign: 'center' }}>
        <p className="eyebrow">पुकार · Pukaar</p>
        <h1 className="display-3">कुछ गड़बड़ हुई · Something went wrong</h1>
        <p className="muted">Reload to get the latest version. In an emergency, call 112.</p>
        <button type="button" className="btn btn-accent" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}

// Every page loads on demand, so the village answer's code is small; the report page's chunk is fetched as
// soon as the phone is idle (main.tsx), and the service worker keeps all of them for offline use.
const Report = lazyPage(() => import('./pages/Report'));
const Landing = lazyPage(() => import('./pages/Landing'));
const Live = lazyPage(() => import('./pages/Live'));
const How = lazyPage(() => import('./pages/How'));
const VillagePage = lazyPage(() => import('./pages/VillagePage'));
const Track = lazyPage(() => import('./pages/Track'));
const Safe = lazyPage(() => import('./pages/Safe'));
const Approve = lazyPage(() => import('./pages/Approve'));
const Proof = lazyPage(() => import('./pages/Proof'));
const Pilot = lazyPage(() => import('./pages/Pilot'));
const Login = lazyPage(() => import('./pages/Login'));
const Roster = lazyPage(() => import('./pages/console/Roster'));
// The console has its own layout (spec 4.9); each section is its own chunk where it is heavy.
const ConsoleLayout = lazyPage(() => import('./pages/console/ConsoleLayout'));
const Inbox = lazyPage(() => import('./pages/console/Inbox'));
const AuditPage = lazyPage(() => import('./pages/console/AuditPage'));
const Enrol = lazyPage(() => import('./pages/console/Enrol'));
const GroupReview = lazyPage(() => import('./pages/console/GroupReview'));
const AskSection = lazyPage(() => import('./pages/console/AskSection'));
const LiveDemo = lazyPage(() => import('./pages/console/LiveDemo'));
const section = (name: keyof typeof import('./pages/console/Sections')) =>
  lazyPage(() => import('./pages/console/Sections').then((m) => ({ default: m[name] as ComponentType })));
const VillagesSection = section('VillagesSection');
const MineSection = section('MineSection');
const ReportsSection = section('ReportsSection');
const RollCallSection = section('RollCallSection');
const DirectivesSection = section('DirectivesSection');
const ReplaySection = section('ReplaySection');
const SystemSection = section('SystemSection');
const SettingsSection = section('SettingsSection');
const NotFound = lazyPage(() => import('./pages/NotFound'));

/**
 * Old paths open their new place, so no link breaks: the officer pages their console section, with the same query
 * (an audit filter, a roster week); /agents and /sensors their chapter of /how; /impact is /proof.
 */
function MovedTo({ to, hash: chapter }: { to: string; hash?: string }) {
  const { search, hash } = useLocation();
  return <Navigate to={`${to}${search}${chapter ?? hash}`} replace />;
}

function PageFallback() {
  return (
    <div className="wrap" style={{ paddingTop: 32 }}>
      <SkeletonCards n={3} />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <PageBoundary>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<Landing />} />
            <Route path="live" element={<Live />} />
            <Route path="how" element={<How />} />
            <Route path="agents" element={<MovedTo to="/how" hash="#agents" />} />
            <Route path="sensors" element={<MovedTo to="/how" hash="#sensors" />} />
            <Route path="report" element={<Report />} />
            <Route path="t/:code" element={<Track />} />
            <Route path="safe/:token" element={<Safe />} />
            <Route path="village/:id" element={<VillagePage />} />
            <Route path="audit" element={<MovedTo to="/console/audit" />} />
            <Route path="roster" element={<MovedTo to="/console/roster" />} />
            <Route path="proof" element={<Proof />} />
            <Route path="impact" element={<MovedTo to="/proof" />} />
            <Route path="pilot" element={<Pilot />} />
            <Route path="login" element={<Login />} />
            <Route path="*" element={<NotFound />} />
          </Route>
          <Route element={<BareShell />}>
            <Route path="a/:token" element={<Approve />} />
          </Route>
          <Route path="console" element={<ConsoleLayout />}>
            <Route index element={<Navigate to="inbox" replace />} />
            <Route path="inbox" element={<Inbox />} />
            <Route path="inbox/:alertId" element={<Inbox />} />
            <Route path="mine" element={<MineSection />} />
            <Route path="villages" element={<VillagesSection />} />
            <Route path="reports" element={<ReportsSection />} />
            <Route path="rollcall" element={<RollCallSection />} />
            <Route path="directives" element={<DirectivesSection />} />
            <Route path="ask" element={<AskSection />} />
            <Route path="roster" element={<Roster />} />
            <Route path="audit" element={<AuditPage />} />
            <Route path="enrol" element={<Enrol />} />
            <Route path="group" element={<GroupReview />} />
            <Route path="replay" element={<ReplaySection />} />
            <Route path="demo" element={<LiveDemo />} />
            <Route path="system" element={<SystemSection />} />
            <Route path="settings" element={<SettingsSection />} />
            <Route path="*" element={<Navigate to="/console/inbox" replace />} />
          </Route>
        </Routes>
      </Suspense>
      </PageBoundary>
    </BrowserRouter>
  );
}
