/*
 * The app's own files, which a production index.html does not load by itself: boot-plugin.ts moves Vite's
 * module script, module preloads and stylesheets into <script type="application/json" id="pk-assets">, and
 * the boot painter loads them when the answer is on screen (or at once, on a page with no answer to paint).
 * On slow 3G this keeps 150 kB of code and styles from queueing in front of the 2 kB answer. If the painter
 * never ran (blocked or broken), boot/fallback.ts loads them at the end of parsing instead.
 */
import type { PkAssets } from './pk-assets';

export type { PkAssets };
export type AnswerRoute = keyof PkAssets['answer'];

export function readAssets(): PkAssets | null {
  const el = document.getElementById('pk-assets');
  if (!el?.textContent) return null;
  try {
    return JSON.parse(el.textContent) as PkAssets;
  } catch {
    return null;
  }
}

/** Attaches the stylesheets and starts the app. Safe to call twice: the second call does nothing. */
export function loadApp(a: PkAssets, route: AnswerRoute | null): void {
  const d = document;
  if (d.documentElement.hasAttribute('data-pk-app')) return;
  d.documentElement.setAttribute('data-pk-app', '');
  const add = (rel: string, href: string, full = false) => {
    const l = d.createElement('link');
    l.rel = rel;
    l.href = href;
    l.setAttribute('crossorigin', '');
    if (full) l.setAttribute('data-pk-full', '');
    d.head.append(l);
  };
  for (const href of [...a.css, ...(route ? a.answer[route] : [])]) add('stylesheet', href, true);
  for (const href of a.pre) add('modulepreload', href);
  const s = d.createElement('script');
  s.type = 'module';
  s.setAttribute('crossorigin', '');
  s.src = a.js;
  d.head.append(s);
}
