import { useLayoutEffect } from 'react';

/*
 * The hand-over from the boot painter (boot.ts) to React. index.html holds the painter's page in #pk-boot and
 * React's in #root, which the critical CSS hides while #pk-boot exists. When a page has what it needs to
 * draw its answer (or knows it cannot), it calls useHandOff: #pk-boot goes in the same frame and React's page
 * shows, styled, because the hand-over waits for the full stylesheet. Without the painter it does nothing.
 */

let done = false;

/** The full stylesheets the painter (or the fallback) attached with the app (boot/assets.ts). None in dev. */
function fullCss(): HTMLLinkElement[] {
  if (typeof document === 'undefined') return [];
  return [...document.querySelectorAll<HTMLLinkElement>('link[data-pk-full]')];
}

const loaded = (l: HTMLLinkElement) => {
  try {
    return Boolean(l.sheet && l.sheet.cssRules);
  } catch {
    // A cross-origin sheet without CORS throws on cssRules, but it has loaded.
    return Boolean(l.sheet);
  }
};

/** Resolves when every full stylesheet has loaded (or failed: the page shows rather than waits forever). */
export function fullCssReady(): Promise<void> {
  const pending = fullCss().filter((l) => !loaded(l));
  if (!pending.length) return Promise.resolve();
  return new Promise((ok) => {
    let left = pending.length;
    const one = () => {
      left -= 1;
      if (left <= 0) ok();
    };
    for (const l of pending) {
      l.addEventListener('load', one, { once: true });
      l.addEventListener('error', one, { once: true });
    }
  });
}

/** Remove the boot painter's page now, or as soon as the full stylesheet is in. */
export function handOff(): void {
  if (done || typeof document === 'undefined') return;
  const boot = document.getElementById('pk-boot');
  if (!boot) {
    done = true;
    return;
  }
  const finish = () => {
    if (done) return;
    done = true;
    boot.remove();
  };
  const pending = fullCss().filter((l) => !loaded(l));
  if (!pending.length) finish();
  else void fullCssReady().then(finish);
}

/** Hand over once `ready` is true, before the browser paints React's page. */
export function useHandOff(ready: boolean): void {
  useLayoutEffect(() => {
    if (ready) handOff();
  }, [ready]);
}

/** The pages the painter draws an answer for; every other page hands over on its first frame. */
export const isAnswerPath = (p: string) => p === '/' || /^\/village\/[^/]+\/?$/.test(p);
