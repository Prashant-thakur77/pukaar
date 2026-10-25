import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useT } from '../i18n';
import { applyTheme, usePrefs } from '../store';

/** The story pages are the only ones set in the display serif. */
const isStoryRoute = (p: string) => /^\/(how|proof|pilot)?\/?$/.test(p);
/** The officer pages keep their own look; water.css skins every other page. */
const isConsoleRoute = (p: string) => /^\/(console|login)(\/|$)/.test(p);

/** The tab's title in the page's language (index.html's is in both, for the moment before the app starts). */
export const SITE_TITLE = { hi: 'पुकार · हिमालय के गाँवों के लिए बाढ़ की चेतावनी', en: 'Pukaar · flood warnings for Himalayan villages' };

/**
 * <html lang>, the tab's title, the theme (villager pages light unless dark was chosen), the story serif and the
 * officer mark, for every layout. The console sets its own title (it counts what waits).
 */
export function useDocumentPrefs() {
  const { pathname } = useLocation();
  const { lang } = useT();
  const theme = usePrefs((s) => s.theme);
  const console_ = pathname.startsWith('/console');
  useEffect(() => {
    document.documentElement.lang = lang;
    if (!console_) document.title = SITE_TITLE[lang];
  }, [lang, console_]);
  useEffect(() => {
    applyTheme(theme, pathname);
    if (isStoryRoute(pathname)) document.documentElement.setAttribute('data-story', '');
    else document.documentElement.removeAttribute('data-story');
    if (isConsoleRoute(pathname)) document.documentElement.setAttribute('data-console', '');
    else document.documentElement.removeAttribute('data-console');
  }, [theme, pathname]);
}

