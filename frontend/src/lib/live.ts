// Live push from AWS AppSync Events over one WebSocket.
//
// Protocol (docs.aws.amazon.com/appsync/latest/eventapi/event-api-websocket-protocol.html):
//   connect   wss://<realtime>/event/realtime, subprotocols ["aws-appsync-event-ws", "header-<base64url auth>"]
//   send      {type:"connection_init"}            <- {type:"connection_ack", connectionTimeoutMs}
//   send      {type:"subscribe", id, channel, authorization}  <- subscribe_success | subscribe_error
//   receive   {type:"data", id, event}  and  {type:"ka"} about once a minute
//
// The public namespace is read with the public, subscribe-only API key; the officer namespace
// with the signed-in user's Cognito ID token. Events are only a nudge: a page that gets one
// refetches its data from the API, and keeps polling (slower) in case a push is lost.

import { useEffect, useRef, useSyncExternalStore } from 'react';
import { useAuth } from '../store';

export const CHANNELS = {
  levels: '/public/levels',
  alerts: '/public/alerts',
  deliveries: '/public/deliveries',
  rollcall: '/public/rollcall',
  officer: '/officer/alerts',
} as const;

/** Every public channel: what /live and the village pages listen to. */
export const PUBLIC_CHANNELS: string[] = [CHANNELS.levels, CHANNELS.alerts, CHANNELS.deliveries, CHANNELS.rollcall];

export type LiveStatus = 'off' | 'connecting' | 'live' | 'retrying' | 'paused';

export interface LiveEvent {
  channel: string;
  data: Record<string, unknown>;
}

export interface LiveConfig {
  httpDomain: string;
  realtimeDomain: string;
  apiKey: string;
}

type Listener = (e: LiveEvent) => void;

interface SocketLike {
  readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: unknown) => void) | null;
  onerror: ((ev: unknown) => void) | null;
}

export type SocketFactory = (url: string, protocols: string[]) => SocketLike;

export interface LiveClientOptions {
  config: LiveConfig;
  getToken?: () => string | null;
  socket?: SocketFactory;
  random?: () => number;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (id: unknown) => void;
}

const OPEN = 1;
const DEFAULT_TIMEOUT_MS = 300_000; // AppSync's documented connection timeout
const MAX_BACKOFF_MS = 30_000;

export function liveConfig(): LiveConfig | null {
  const env = import.meta.env;
  const httpDomain = env.VITE_EVENTS_HTTP_DOMAIN?.trim();
  const realtimeDomain = env.VITE_EVENTS_REALTIME_DOMAIN?.trim();
  const apiKey = env.VITE_EVENTS_API_KEY?.trim();
  return httpDomain && realtimeDomain && apiKey ? { httpDomain, realtimeDomain, apiKey } : null;
}

/** JSON -> base64url without padding, as the subprotocol header wants. */
export function base64url(value: unknown): string {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** Exponential backoff with jitter (AWS "equal jitter"): 1 s, 2 s, 4 s ... capped at 30 s. */
export function backoffMs(attempt: number, random: () => number = Math.random): number {
  const cap = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** Math.min(attempt, 10));
  return Math.round(cap / 2 + (cap / 2) * random());
}

/** A data message's event may be one JSON string or a list of them. */
function parseEvents(raw: unknown): Record<string, unknown>[] {
  const items = Array.isArray(raw) ? raw : [raw];
  const out: Record<string, unknown>[] = [];
  for (const item of items) {
    let v: unknown = item;
    if (typeof v === 'string') {
      try {
        v = JSON.parse(v);
      } catch {
        continue;
      }
    }
    if (v && typeof v === 'object' && !Array.isArray(v)) out.push(v as Record<string, unknown>);
  }
  return out;
}

interface Sub {
  id: string;
  channel: string;
  state: 'idle' | 'pending' | 'ok' | 'error';
  listeners: Set<Listener>;
}

export class LiveClient {
  status: LiveStatus = 'off';
  private readonly config: LiveConfig;
  private readonly getToken: () => string | null;
  private readonly makeSocket: SocketFactory;
  private readonly random: () => number;
  private readonly setTimer: (fn: () => void, ms: number) => unknown;
  private readonly clearTimer: (id: unknown) => void;
  private ws: SocketLike | null = null;
  private acked = false;
  private attempt = 0;
  private retryTimer: unknown = null;
  private kaTimer: unknown = null;
  private timeoutMs = DEFAULT_TIMEOUT_MS;
  private nextId = 0;
  private readonly subs = new Map<string, Sub>(); // by channel
  private readonly statusListeners = new Set<() => void>();
  private version = 0;

  constructor(opts: LiveClientOptions) {
    this.config = opts.config;
    this.getToken = opts.getToken ?? (() => null);
    this.makeSocket =
      opts.socket ?? ((url, protocols) => new WebSocket(url, protocols) as unknown as SocketLike);
    this.random = opts.random ?? Math.random;
    this.setTimer = opts.setTimer ?? ((fn, ms) => setTimeout(fn, ms));
    this.clearTimer = opts.clearTimer ?? ((id) => clearTimeout(id as ReturnType<typeof setTimeout>));
  }

  // -- public API -------------------------------------------------------------------
  /** Listen to one channel; returns the unsubscribe function. Connects on first use. */
  subscribe(channel: string, listener: Listener): () => void {
    let sub = this.subs.get(channel);
    if (!sub) {
      sub = { id: `s${++this.nextId}`, channel, state: 'idle', listeners: new Set() };
      this.subs.set(channel, sub);
      if (this.acked) this.sendSubscribe(sub);
    }
    sub.listeners.add(listener);
    if (this.status === 'off') this.connect();
    return () => {
      const s = this.subs.get(channel);
      if (!s) return;
      s.listeners.delete(listener);
      if (s.listeners.size > 0) return;
      this.subs.delete(channel);
      if (this.acked && (s.state === 'ok' || s.state === 'pending')) this.send({ type: 'unsubscribe', id: s.id });
      this.notify();
      if (this.subs.size === 0) this.close('off');
    };
  }

  /** True when the socket is up and every one of these channels is subscribed. */
  isLive(channels: string[]): boolean {
    return this.status === 'live' && channels.every((c) => this.subs.get(c)?.state === 'ok');
  }

  /** Subscribed channels that were refused (for example an officer channel without a token). */
  failed(): string[] {
    return [...this.subs.values()].filter((s) => s.state === 'error').map((s) => s.channel);
  }

  hasSubscribers(): boolean {
    return this.subs.size > 0;
  }

  onChange(fn: () => void): () => void {
    this.statusListeners.add(fn);
    return () => this.statusListeners.delete(fn);
  }

  /** A number that changes whenever status or a subscription state changes. */
  snapshot(): number {
    return this.version;
  }

  /** Page hidden: drop the socket (no reconnect) until resume(). */
  pause(): void {
    if (this.status === 'off' || this.status === 'paused') return;
    this.close('paused');
  }

  resume(): void {
    if (this.status === 'paused' && this.subs.size > 0) {
      this.attempt = 0;
      this.connect();
    }
  }

  // -- connection -------------------------------------------------------------------
  connect(): void {
    this.cancelRetry();
    this.dropSocket();
    this.acked = false;
    this.setStatus(this.attempt > 0 ? 'retrying' : 'connecting');
    const header = this.connectAuth();
    let ws: SocketLike;
    try {
      ws = this.makeSocket(`wss://${this.config.realtimeDomain}/event/realtime`, [
        'aws-appsync-event-ws',
        `header-${base64url(header)}`,
      ]);
    } catch {
      this.scheduleRetry();
      return;
    }
    this.ws = ws;
    ws.onopen = () => this.send({ type: 'connection_init' });
    ws.onmessage = (ev) => this.handleMessage(typeof ev.data === 'string' ? ev.data : String(ev.data));
    ws.onerror = () => {
      /* onclose follows and schedules the retry */
    };
    ws.onclose = () => {
      if (this.ws !== ws) return; // an old socket we already replaced
      this.ws = null;
      this.acked = false;
      this.clearKa();
      for (const s of this.subs.values()) s.state = 'idle';
      if (this.status !== 'off' && this.status !== 'paused') this.scheduleRetry();
    };
  }

  /** Handles one server message; exported through the class for tests. */
  handleMessage(raw: string): void {
    let msg: { type?: string; id?: string; event?: unknown; connectionTimeoutMs?: number };
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    switch (msg.type) {
      case 'connection_ack':
        this.acked = true;
        this.attempt = 0;
        this.timeoutMs = typeof msg.connectionTimeoutMs === 'number' ? msg.connectionTimeoutMs : DEFAULT_TIMEOUT_MS;
        this.armKa();
        for (const s of this.subs.values()) this.sendSubscribe(s);
        this.setStatus('live');
        return;
      case 'ka':
        this.armKa();
        return;
      case 'subscribe_success':
        this.setSubState(msg.id, 'ok');
        return;
      case 'subscribe_error':
        this.setSubState(msg.id, 'error');
        return;
      case 'data': {
        this.armKa();
        const sub = [...this.subs.values()].find((s) => s.id === msg.id);
        if (!sub) return;
        for (const data of parseEvents(msg.event)) {
          for (const fn of [...sub.listeners]) {
            try {
              fn({ channel: sub.channel, data });
            } catch {
              /* a listener's bug must not stop the others */
            }
          }
        }
        return;
      }
      case 'unsubscribe_success':
      case 'unsubscribe_error':
      case 'broadcast_error':
        return;
      case 'error':
      case 'connection_error':
        // The connection itself was refused (expired key or token, throttling): back off and retry.
        this.dropSocket();
        this.acked = false;
        this.clearKa();
        for (const s of this.subs.values()) s.state = 'idle';
        this.scheduleRetry();
        return;
      default:
        return;
    }
  }

  private connectAuth(): Record<string, string> {
    // Connect with the public key; each subscription carries its own auth. After a refused attempt a
    // signed-in user tries the ID token instead, so one expired credential does not keep everyone off.
    const token = this.attempt % 2 === 1 ? this.getToken() : null;
    return token
      ? { host: this.config.httpDomain, Authorization: token }
      : { host: this.config.httpDomain, 'x-api-key': this.config.apiKey };
  }

  private subscribeAuth(channel: string): Record<string, string> | null {
    if (channel.startsWith('/public/')) return { host: this.config.httpDomain, 'x-api-key': this.config.apiKey };
    const token = this.getToken();
    return token ? { host: this.config.httpDomain, Authorization: token } : null;
  }

  private sendSubscribe(sub: Sub): void {
    const authorization = this.subscribeAuth(sub.channel);
    if (!authorization) {
      sub.state = 'error'; // an officer channel with nobody signed in: stay on polling for it
      this.notify();
      return;
    }
    sub.state = 'pending';
    this.send({ type: 'subscribe', id: sub.id, channel: sub.channel, authorization });
    this.notify();
  }

  private setSubState(id: string | undefined, state: Sub['state']): void {
    const sub = [...this.subs.values()].find((s) => s.id === id);
    if (!sub) return;
    sub.state = state;
    this.notify();
  }

  private send(msg: unknown): void {
    if (this.ws && this.ws.readyState === OPEN) {
      try {
        this.ws.send(JSON.stringify(msg));
      } catch {
        /* the close handler takes over */
      }
    }
  }

  private armKa(): void {
    this.clearKa();
    this.kaTimer = this.setTimer(() => {
      // No keep-alive within the timeout: the connection is dead even if the socket looks open.
      this.dropSocket();
      this.acked = false;
      for (const s of this.subs.values()) s.state = 'idle';
      this.scheduleRetry();
    }, this.timeoutMs);
  }

  private clearKa(): void {
    if (this.kaTimer !== null) this.clearTimer(this.kaTimer);
    this.kaTimer = null;
  }

  private scheduleRetry(): void {
    this.cancelRetry();
    if (this.subs.size === 0) {
      this.setStatus('off');
      return;
    }
    const delay = backoffMs(this.attempt, this.random);
    this.attempt += 1;
    this.setStatus('retrying');
    this.retryTimer = this.setTimer(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }

  private cancelRetry(): void {
    if (this.retryTimer !== null) this.clearTimer(this.retryTimer);
    this.retryTimer = null;
  }

  private dropSocket(): void {
    const ws = this.ws;
    this.ws = null;
    if (!ws) return;
    ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
    try {
      ws.close(1000);
    } catch {
      /* already closed */
    }
  }

  private close(next: 'off' | 'paused'): void {
    this.cancelRetry();
    this.clearKa();
    this.dropSocket();
    this.acked = false;
    for (const s of this.subs.values()) s.state = 'idle';
    this.setStatus(next);
  }

  private setStatus(s: LiveStatus): void {
    this.status = s;
    this.notify();
  }

  private notify(): void {
    this.version += 1;
    for (const fn of [...this.statusListeners]) fn();
  }
}

// -- one shared client per page ---------------------------------------------------------
let shared: LiveClient | null | undefined;

export function getLiveClient(): LiveClient | null {
  if (shared === undefined) {
    const config = liveConfig();
    shared = config ? new LiveClient({ config, getToken: () => useAuth.getState().token }) : null;
    if (shared && typeof document !== 'undefined') {
      const client = shared;
      document.addEventListener('visibilitychange', () =>
        document.visibilityState === 'hidden' ? client.pause() : client.resume(),
      );
      window.addEventListener('pagehide', () => client.pause());
      window.addEventListener('pageshow', () => client.resume());
    }
  }
  return shared;
}

/** Tests only. */
export function setLiveClientForTests(client: LiveClient | null | undefined): void {
  shared = client;
}

const noop = () => () => {};

/** Re-renders on any change of the shared client's state. */
function useLiveVersion(client: LiveClient | null): number {
  return useSyncExternalStore(
    client ? (fn) => client.onChange(fn) : noop,
    () => (client ? client.snapshot() : 0),
    () => 0,
  );
}

/**
 * Subscribe to `channels` while mounted and call `onEvent` for each event.
 * Returns `live`: true only while the socket is up and every channel is subscribed,
 * so callers can relax their polling honestly.
 */
export function useLiveEvents(channels: string[], onEvent: (e: LiveEvent) => void): { live: boolean; status: LiveStatus } {
  const client = getLiveClient();
  const handler = useRef(onEvent);
  useEffect(() => {
    handler.current = onEvent;
  });
  const key = channels.join(',');
  useEffect(() => {
    if (!client || !key) return;
    const offs = key.split(',').map((c) => client.subscribe(c, (e) => handler.current(e)));
    return () => offs.forEach((off) => off());
  }, [client, key]);
  useLiveVersion(client);
  return { live: client ? client.isLive(key ? key.split(',') : []) : false, status: client ? client.status : 'off' };
}

/** For the header pill: is any page using live push right now, and is it up? */
export function useLiveStatus(): { configured: boolean; inUse: boolean; status: LiveStatus; failed: string[] } {
  const client = getLiveClient();
  useLiveVersion(client);
  if (!client) return { configured: false, inUse: false, status: 'off', failed: [] };
  return { configured: true, inUse: client.hasSubscribers(), status: client.status, failed: client.failed() };
}
