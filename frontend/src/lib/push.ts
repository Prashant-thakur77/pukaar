/*
 * The console's side of Web Push: can this browser get approval alerts, and the key and id
 * helpers. The service worker side is src/lib/pushSw.ts; the server is services/officer_push.py.
 */

export type PushEnv = 'supported' | 'unsupported' | 'ios-install';

interface EnvProbe {
  userAgent: string;
  platform?: string;
  maxTouchPoints?: number;
  hasServiceWorker: boolean;
  hasPushManager: boolean;
  hasNotification: boolean;
  standalone: boolean;
}

export function probeEnvironment(): EnvProbe {
  const nav = typeof navigator !== 'undefined' ? navigator : undefined;
  const win = typeof window !== 'undefined' ? window : undefined;
  let standalone = false;
  try {
    standalone =
      Boolean(win?.matchMedia?.('(display-mode: standalone)').matches) ||
      (nav as (Navigator & { standalone?: boolean }) | undefined)?.standalone === true;
  } catch {
    standalone = false;
  }
  return {
    userAgent: nav?.userAgent ?? '',
    platform: nav?.platform,
    maxTouchPoints: nav?.maxTouchPoints,
    hasServiceWorker: Boolean(nav && 'serviceWorker' in nav),
    hasPushManager: Boolean(win && 'PushManager' in win),
    hasNotification: Boolean(win && 'Notification' in win),
    standalone,
  };
}

export function isIOS(p: Pick<EnvProbe, 'userAgent' | 'platform' | 'maxTouchPoints'>): boolean {
  if (/iPad|iPhone|iPod/.test(p.userAgent)) return true;
  // iPadOS asks for the desktop site and says "Macintosh"; a touch screen gives it away.
  return p.platform === 'MacIntel' && (p.maxTouchPoints ?? 0) > 1;
}

/** iOS and iPadOS (16.4+) deliver Web Push only to a site added to the Home Screen. */
export function pushEnvironment(p: EnvProbe = probeEnvironment()): PushEnv {
  const apis = p.hasServiceWorker && p.hasPushManager && p.hasNotification;
  if (isIOS(p) && !p.standalone) return 'ios-install';
  return apis ? 'supported' : 'unsupported';
}

export function urlBase64ToUint8Array(base64url: string): Uint8Array<ArrayBuffer> {
  const pad = '='.repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob((base64url + pad).replace(/-/g, '+').replace(/_/g, '/'));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

/** Was this subscription made with this server key? After `make vapid-keys ROTATE=1` it was not. */
export function sameKey(subscriptionKey: ArrayBuffer | null | undefined, serverKey: string): boolean {
  if (!subscriptionKey) return false;
  const a = new Uint8Array(subscriptionKey);
  const b = urlBase64ToUint8Array(serverKey);
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

/** The server's id for a subscription: the first 24 hex digits of SHA-256(endpoint). */
export async function subscriptionId(endpoint: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(endpoint));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0'))
    .join('')
    .slice(0, 24);
}
