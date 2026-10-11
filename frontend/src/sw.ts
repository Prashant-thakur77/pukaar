/// <reference lib="webworker" />
/*
 * Pukaar's service worker (vite-plugin-pwa, injectManifest).
 *
 * 1. The same offline behaviour the generated worker had: the app shell is precached, page
 *    navigations fall back to /index.html (never /api/), map and elevation tiles are cached
 *    first, old precaches are cleaned up, and a new worker takes over at once (autoUpdate).
 * 2. Web Push for officers: the approval request shows with Approve / Decline buttons; a
 *    button POSTs the decision to /approval/{token} and shows the result, so it works with
 *    the console closed. A plain tap opens the approval page. Logic: src/lib/pushSw.ts.
 */
import { clientsClaim } from 'workbox-core';
import { ExpirationPlugin } from 'workbox-expiration';
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute, type PrecacheEntry } from 'workbox-precaching';
import { NavigationRoute, registerRoute } from 'workbox-routing';
import { CacheFirst } from 'workbox-strategies';
import { confirmation, isDecision, notificationFromPush, parsePush, sendDecision, type NotificationData } from './lib/pushSw';

declare const self: ServiceWorkerGlobalScope & { __WB_MANIFEST: (PrecacheEntry | string)[] };

const API_BASE: string = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8000').replace(/\/$/, '');

void self.skipWaiting();
clientsClaim();

precacheAndRoute(self.__WB_MANIFEST);
cleanupOutdatedCaches();
registerRoute(new NavigationRoute(createHandlerBoundToURL('/index.html'), { denylist: [/^\/api\//] }));
registerRoute(
  ({ url }) => url.hostname === 'tile.openstreetmap.org',
  new CacheFirst({ cacheName: 'osm-tiles', plugins: [new ExpirationPlugin({ maxEntries: 300, maxAgeSeconds: 7 * 24 * 3600 })] }),
  'GET',
);
registerRoute(
  ({ url }) => url.hostname === 's3.amazonaws.com' && url.pathname.startsWith('/elevation-tiles-prod/'),
  new CacheFirst({ cacheName: 'dem-tiles', plugins: [new ExpirationPlugin({ maxEntries: 300, maxAgeSeconds: 30 * 24 * 3600 })] }),
  'GET',
);

// -- Web Push ------------------------------------------------------------------------------
self.addEventListener('push', (event) => {
  let text: string | null = null;
  try {
    text = event.data ? event.data.text() : null;
  } catch {
    text = null;
  }
  const n = notificationFromPush(parsePush(text), self.location.origin);
  event.waitUntil(self.registration.showNotification(n.title, n.options as NotificationOptions));
});

async function openPage(path: string): Promise<void> {
  const target = new URL(path, self.location.origin).href;
  const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  const exact = windows.find((w) => w.url === target);
  if (exact) {
    await exact.focus();
    return;
  }
  await self.clients.openWindow(target);
}

self.addEventListener('notificationclick', (event) => {
  const data = (event.notification.data ?? { kind: 'info', url: '/console' }) as NotificationData;
  event.notification.close();
  const action = event.action;
  if (isDecision(action) && data.token) {
    event.waitUntil(
      (async () => {
        const status = await sendDecision((url, init) => fetch(url, init), API_BASE, data.token!, action);
        const c = confirmation(action, status, data);
        await self.registration.showNotification(c.title, c.options as NotificationOptions);
      })(),
    );
    return;
  }
  event.waitUntil(openPage(data.url || '/console'));
});
