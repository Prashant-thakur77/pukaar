import { lazy, Suspense } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import Shell from './components/Shell';
import { SkeletonCards } from './components/States';
import Report from './pages/Report';

// The villager report page is in the main bundle so it works offline at once;
// everything else (and MapLibre) loads on demand.
const Landing = lazy(() => import('./pages/Landing'));
const Live = lazy(() => import('./pages/Live'));
const ConsolePage = lazy(() => import('./pages/console/ConsolePage'));
const VillagePage = lazy(() => import('./pages/VillagePage'));
const Track = lazy(() => import('./pages/Track'));
const Approve = lazy(() => import('./pages/Approve'));
const Impact = lazy(() => import('./pages/Impact'));
const Login = lazy(() => import('./pages/Login'));
const Audit = lazy(() => import('./pages/Audit'));
const NotFound = lazy(() => import('./pages/NotFound'));

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
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<Landing />} />
            <Route path="live" element={<Live />} />
            <Route path="report" element={<Report />} />
            <Route path="t/:code" element={<Track />} />
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
    </BrowserRouter>
  );
}
