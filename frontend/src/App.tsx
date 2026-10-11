import { Component, lazy, Suspense, type ComponentType, type ReactNode } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import Shell from './components/Shell';
import { SkeletonCards } from './components/States';
import Report from './pages/Report';

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

// The villager report page is in the main bundle so it works offline at once;
// everything else (and MapLibre) loads on demand.
const Landing = lazyPage(() => import('./pages/Landing'));
const Live = lazyPage(() => import('./pages/Live'));
const How = lazyPage(() => import('./pages/How'));
const Agents = lazyPage(() => import('./pages/Agents'));
const Sensors = lazyPage(() => import('./pages/Sensors'));
const ConsolePage = lazyPage(() => import('./pages/console/ConsolePage'));
const VillagePage = lazyPage(() => import('./pages/VillagePage'));
const Track = lazyPage(() => import('./pages/Track'));
const Safe = lazyPage(() => import('./pages/Safe'));
const Approve = lazyPage(() => import('./pages/Approve'));
const Impact = lazyPage(() => import('./pages/Impact'));
const Login = lazyPage(() => import('./pages/Login'));
const Audit = lazyPage(() => import('./pages/Audit'));
const NotFound = lazyPage(() => import('./pages/NotFound'));

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
            <Route path="agents" element={<Agents />} />
            <Route path="sensors" element={<Sensors />} />
            <Route path="report" element={<Report />} />
            <Route path="t/:code" element={<Track />} />
            <Route path="safe/:token" element={<Safe />} />
            <Route path="a/:token" element={<Approve />} />
            <Route path="village/:id" element={<VillagePage />} />
            <Route path="console" element={<ConsolePage />} />
            <Route path="audit" element={<Audit />} />
            <Route path="impact" element={<Impact />} />
            <Route path="login" element={<Login />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
      </PageBoundary>
    </BrowserRouter>
  );
}
