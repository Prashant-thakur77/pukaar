import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './tokens.css';
import './app.css';
import './pages.css';
import './agents.css';
import './gauges.css';
import './roster.css';
import './editorial.css';
import App from './App';
import { prefetchRoute } from './api';
import { applyTheme, usePrefs } from './store';

applyTheme(usePrefs.getState().theme);
prefetchRoute(window.location.pathname);
// The answer pages' own code starts downloading now, beside their data, not after React's first render.
if (/^\/village\/[^/]+\/?$/.test(window.location.pathname)) void import('./pages/VillagePage').catch(() => {});
else if (window.location.pathname === '/') void import('./pages/Landing').catch(() => {});

// Vite fires this when a preloaded chunk of an older build is gone: reload once into the new build.
window.addEventListener('vite:preloadError', () => {
  try {
    if (sessionStorage.getItem('pukaar.chunk-reload')) return;
    sessionStorage.setItem('pukaar.chunk-reload', '1');
  } catch {
    return;
  }
  window.location.reload();
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
