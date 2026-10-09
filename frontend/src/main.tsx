import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/inter/wght.css';
import '@fontsource-variable/noto-sans-devanagari/wght.css';
import '@fontsource/bebas-neue/latin-400.css';
import './theme.css';
import './app.css';
import App from './App';
import { applyTheme, usePrefs } from './store';

applyTheme(usePrefs.getState().theme);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
