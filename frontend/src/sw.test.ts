import { beforeAll, describe, expect, it, vi } from 'vitest';

// The worker's wiring, run against a fake ServiceWorkerGlobalScope. Workbox is stubbed: the
// precache list and caching routes are checked by the production build (`npm run build`).
const routes: unknown[] = [];
vi.mock('workbox-core', () => ({ clientsClaim: vi.fn() }));
vi.mock('workbox-expiration', () => ({ ExpirationPlugin: vi.fn() }));
vi.mock('workbox-precaching', () => ({
  cleanupOutdatedCaches: vi.fn(),
  createHandlerBoundToURL: vi.fn(() => 'index-handler'),
  precacheAndRoute: vi.fn(),
}));
vi.mock('workbox-routing', () => ({
  NavigationRoute: vi.fn(),
  registerRoute: vi.fn((...args: unknown[]) => routes.push(args)),
}));
vi.mock('workbox-strategies', () => ({ CacheFirst: vi.fn() }));

type Handler = (event: unknown) => void;
const handlers: Record<string, Handler> = {};
const shown: { title: string; options: Record<string, unknown> }[] = [];
const opened: string[] = [];
const fakeSelf = {
  __WB_MANIFEST: [{ url: 'index.html', revision: '1' }],
  location: { origin: 'https://app.example' },
  skipWaiting: vi.fn(() => Promise.resolve()),
  addEventListener: (type: string, fn: Handler) => {
    handlers[type] = fn;
  },
  registration: {
    showNotification: vi.fn(async (title: string, options: Record<string, unknown>) => {
      shown.push({ title, options });
    }),
  },
  clients: {
    matchAll: vi.fn(async () => []),
    openWindow: vi.fn(async (url: string) => {
      opened.push(url);
      return null;
    }),
  },
};

function fire(type: string, event: Record<string, unknown>): Promise<unknown> {
  let pending: Promise<unknown> = Promise.resolve();
  handlers[type]({ ...event, waitUntil: (p: Promise<unknown>) => (pending = p) });
  return pending;
}

const TOKEN = 'abc.def';
const payload = {
  kind: 'approval',
  title: 'पुकार: थुनाग चेतावनी',
  body: 'text',
  tag: 'alr_1',
  renotify: true,
  requireInteraction: true,
  actions: [{ action: 'approve', title: '✅ मंज़ूर' }, { action: 'decline', title: '✖ नहीं' }],
  data: { url: `https://app.example/a/${TOKEN}`, alert_id: 'alr_1', token: TOKEN },
};

beforeAll(async () => {
  vi.stubGlobal('self', fakeSelf);
  await import('./sw');
});

describe('service worker', () => {
  it('keeps the offline routes: navigation fallback plus the two tile caches', () => {
    expect(fakeSelf.skipWaiting).toHaveBeenCalled();
    expect(routes).toHaveLength(3);
  });

  it('shows a push as a notification with Approve and Decline', async () => {
    await fire('push', { data: { text: () => JSON.stringify(payload) } });
    expect(shown.at(-1)?.title).toBe('पुकार: थुनाग चेतावनी');
    expect(shown.at(-1)?.options.actions).toEqual(payload.actions);
    expect(shown.at(-1)?.options.tag).toBe('alr_1');
  });

  it('Approve posts the decision and confirms it, without opening the console', async () => {
    const fetchMock = vi.fn(async () => ({ status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const close = vi.fn();
    const data = shown.at(-1)!.options.data;
    await fire('notificationclick', { action: 'approve', notification: { data, close } });
    expect(close).toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/approval/${encodeURIComponent(TOKEN)}`,
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ decision: 'approve' }) }),
    );
    expect(shown.at(-1)?.title).toContain('Approved');
    expect(opened).toEqual([]);
  });

  it('a late Decline says so', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ status: 409 })));
    const data = { kind: 'approval', url: `/a/${TOKEN}`, alert_id: 'alr_1', token: TOKEN };
    await fire('notificationclick', { action: 'decline', notification: { data, close: vi.fn() } });
    expect(shown.at(-1)?.title).toContain('Already decided');
  });

  it('a plain tap opens the approval page', async () => {
    const data = { kind: 'approval', url: `/a/${TOKEN}`, alert_id: 'alr_1', token: TOKEN };
    await fire('notificationclick', { action: '', notification: { data, close: vi.fn() } });
    expect(opened.at(-1)).toBe(`https://app.example/a/${TOKEN}`);
  });
});
