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
import App from './App';
import { applyTheme, usePrefs } from './store';

applyTheme(usePrefs.getState().theme);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
