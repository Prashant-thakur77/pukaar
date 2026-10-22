import { useSyncExternalStore } from 'react';

/** A media query, live: true while it matches. */
export function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(query);
      mq.addEventListener('change', cb);
      return () => mq.removeEventListener('change', cb);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** Re-renders every `ms` (for "4 min waiting" lines). */
export function useNow(ms = 30_000): number {
  return useSyncExternalStore(
    (cb) => {
      const t = window.setInterval(cb, ms);
      return () => window.clearInterval(t);
    },
    () => Math.floor(Date.now() / ms) * ms,
    () => 0,
  );
}
