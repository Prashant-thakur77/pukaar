import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/inter/wght.css';
import '@fontsource-variable/noto-sans-devanagari/wght.css';
import '@fontsource/bebas-neue/latin-400.css';
import '@fontsource/anton/latin-400.css';
import '@fontsource/kalam/devanagari-700.css';
import '@fontsource/kalam/latin-700.css';
import './theme.css';
import './app.css';
import './pages.css';
import './agents.css';
import App from './App';
import { applyTheme, usePrefs } from './store';

applyTheme(usePrefs.getState().theme);

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
