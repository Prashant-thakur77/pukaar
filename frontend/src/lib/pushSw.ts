/*
 * Web Push logic for the service worker (src/sw.ts), kept free of worker globals so it is
 * unit-tested here. The backend (services/officer_push.py) sends the approval request with
 * the signed one-tap token; the Approve / Decline buttons POST it to the public
 * /approval/{token} route (the same call the approval page makes), so they work with the
 * console closed.
 */

export type PushAction = 'approve' | 'decline';

export interface PushPayload {
  kind?: string;
  title?: string;
  body?: string;
  tag?: string;
  renotify?: boolean;
  requireInteraction?: boolean;
  actions?: { action?: string; title?: string }[];
  data?: { url?: string; alert_id?: string; token?: string; drill?: boolean };
}

export interface NotificationData {
  kind: string;
  /** Same-origin path to open on a plain tap. */
  url: string;
  alert_id?: string;
  token?: string;
}

/** NotificationOptions plus the fields browsers support but TypeScript's DOM types leave out. */
export interface NotificationSpec {
  title: string;
  options: {
    body: string;
    tag?: string;
    lang: string;
    icon: string;
    badge: string;
    renotify?: boolean;
    requireInteraction: boolean;
    actions?: { action: PushAction; title: string }[];
    data: NotificationData;
  };
}

const ICON = '/favicon.svg';
const ACTION_TITLES: Record<PushAction, string> = { approve: '✅ मंज़ूर', decline: '✖ नहीं' };

export function isDecision(action: string): action is PushAction {
  return action === 'approve' || action === 'decline';
}

export function parsePush(text: string | null | undefined): PushPayload {
  if (!text) return {};
  try {
    const v: unknown = JSON.parse(text);
    return v && typeof v === 'object' && !Array.isArray(v) ? (v as PushPayload) : {};
  } catch {
    return { body: text.slice(0, 200) };
  }
}

export function approvalPath(token: string): string {
  return `/a/${encodeURIComponent(token)}`;
}

/** Only ever open a page of this app: a URL from another origin falls back to a local path. */
export function safePath(url: string | undefined, origin: string, fallback: string): string {
  if (!url) return fallback;
  try {
    const u = new URL(url, origin);
    if (u.origin === origin) return `${u.pathname}${u.search}${u.hash}`;
    // The API sends the deployed web URL; the path is ours even when the origin differs (preview, localhost).
    return /^\/(a|console)(\/|$|\?)/.test(u.pathname) ? `${u.pathname}${u.search}` : fallback;
  } catch {
    return fallback;
  }
}

const str = (v: unknown, max: number) => (typeof v === 'string' ? v.slice(0, max) : '');

export function notificationFromPush(p: PushPayload, origin: string): NotificationSpec {
  const token = str(p.data?.token, 2000);
  const alertId = str(p.data?.alert_id, 100);
  const kind = str(p.kind, 20) || (token ? 'approval' : 'info');
  const fallback = token ? approvalPath(token) : '/console';
  const actions =
    kind === 'approval' && token
      ? (p.actions ?? [])
          .map((a) => a?.action ?? '')
          .filter(isDecision)
          .map((action) => ({ action, title: ACTION_TITLES[action] }))
      : [];
  return {
    title: str(p.title, 120) || 'पुकार · Pukaar',
    options: {
      body: str(p.body, 400),
      tag: str(p.tag, 100) || alertId || undefined,
      lang: 'hi',
      icon: ICON,
      badge: ICON,
      renotify: Boolean(p.renotify && (p.tag || alertId)),
      requireInteraction: Boolean(p.requireInteraction),
      ...(actions.length ? { actions } : {}),
      data: { kind, url: safePath(p.data?.url, origin, fallback), alert_id: alertId || undefined, token: token || undefined },
    },
  };
}

export function decisionRequest(apiBase: string, token: string, action: PushAction): { url: string; init: RequestInit } {
  return {
    url: `${apiBase.replace(/\/$/, '')}/approval/${encodeURIComponent(token)}`,
    init: {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ decision: action }),
    },
  };
}

/** POST the decision; the HTTP status, or 0 when the network failed. Never throws. */
export async function sendDecision(
  fetchFn: (url: string, init: RequestInit) => Promise<{ status: number }>,
  apiBase: string,
  token: string,
  action: PushAction,
): Promise<number> {
  const { url, init } = decisionRequest(apiBase, token, action);
  try {
    return (await fetchFn(url, init)).status;
  } catch {
    return 0;
  }
}

/** The notification that replaces the request once the button was pressed. */
export function confirmation(action: PushAction, status: number, data: NotificationData): NotificationSpec {
  const page = data.token ? approvalPath(data.token) : '/console';
  const consolePath = data.alert_id ? `/console?alert=${encodeURIComponent(data.alert_id)}` : '/console';
  let title: string;
  let body: string;
  let url = consolePath;
  let sticky = false;
  if (status >= 200 && status < 300) {
    title = action === 'approve' ? '✅ मंज़ूर किया · Approved' : '✖ नहीं भेजा · Declined';
    body =
      action === 'approve'
        ? 'चेतावनी गाँव के फ़ोनों पर जा रही है। The alert is going out to the village.'
        : 'यह चेतावनी नहीं भेजी जाएगी। This alert will not be sent.'; // what the decline route does
  } else if (status === 409) {
    title = 'पहले ही फ़ैसला हो चुका · Already decided';
    body = 'किसी और ने फ़ैसला किया, या समय निकल गया। कुछ दोबारा नहीं भेजा गया। Someone else decided, or the time ran out.';
  } else if (status === 400 || status === 404 || status === 403) {
    title = 'लिंक सही नहीं · Link not valid';
    body = 'कंसोल खोलकर फ़ैसला करें। Open the console to decide.';
  } else {
    title = 'जवाब नहीं भेजा जा सका · Answer not sent';
    body = 'छूकर खोलें और फिर कोशिश करें। Tap to open and try again.';
    url = page;
    sticky = true;
  }
  return {
    title,
    options: {
      body,
      tag: data.alert_id || undefined,
      lang: 'hi',
      icon: ICON,
      badge: ICON,
      renotify: true,
      requireInteraction: sticky,
      data: { kind: 'confirmation', url, alert_id: data.alert_id },
    },
  };
}
