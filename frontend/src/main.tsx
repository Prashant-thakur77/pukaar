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
import { handOff } from './boot/handoff';
import { loadLang, scopeFor } from './i18n';

applyTheme(usePrefs.getState().theme);
// Pages hand over from the boot painter once they have their answer; never leave it standing longer than this.
setTimeout(handOff, 12_000);
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

// Only the language this page shows is downloaded before the first render; the other follows when idle.
const lang = usePrefs.getState().lang[scopeFor(window.location.pathname)];
const render = () =>
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
loadLang(lang).then(render, render);
// Nice to have, never in the way: once the page has loaded and the network has had 8 s of quiet for it.
const later = (f: () => void) => {
  const go = () => setTimeout(() => ('requestIdleCallback' in window ? window.requestIdleCallback(f, { timeout: 8000 }) : f()), 8000);
  if (document.readyState === 'complete') go();
  else window.addEventListener('load', go, { once: true });
};
later(() => {
  void loadLang(lang === 'hi' ? 'en' : 'hi').catch(() => {});
  // The report page, so "water rising? report it" opens at once, and offline if the signal goes.
  void import('./pages/Report').catch(() => {});
});
