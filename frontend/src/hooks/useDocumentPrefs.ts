import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useT } from '../i18n';
import { applyTheme, usePrefs } from '../store';

/** The story pages are the only ones set in the display serif. */
const isStoryRoute = (p: string) => /^\/(how|proof|pilot)?\/?$/.test(p);

/** <html lang>, the theme (villager pages light unless dark was chosen) and the story serif, for every layout. */
export function useDocumentPrefs() {
  const { pathname } = useLocation();
  const { lang } = useT();
  const theme = usePrefs((s) => s.theme);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  useEffect(() => {
    applyTheme(theme, pathname);
    if (isStoryRoute(pathname)) document.documentElement.setAttribute('data-story', '');
    else document.documentElement.removeAttribute('data-story');
  }, [theme, pathname]);
}

