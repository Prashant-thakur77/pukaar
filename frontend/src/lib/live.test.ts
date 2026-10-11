import { describe, expect, it } from 'vitest';
import { backoffMs, base64url, CHANNELS, LiveClient, type LiveEvent, type SocketFactory } from './live';

const CONFIG = {
  httpDomain: 'abc.appsync-api.us-east-1.amazonaws.com',
  realtimeDomain: 'abc.appsync-realtime-api.us-east-1.amazonaws.com',
  apiKey: 'da2-publickey',
};

class FakeSocket {
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  closed = false;
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  readonly url: string;
  readonly protocols: string[];
  constructor(url: string, protocols: string[]) {
    this.url = url;
    this.protocols = protocols;
  }
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.closed = true;
    this.readyState = 3;
  }
  open() {
    this.readyState = 1;
    this.onopen?.({});
  }
  receive(msg: unknown) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
  drop() {
    this.readyState = 3;
    this.onclose?.({});
  }
}

/** Manual timers so keep-alive and backoff can be driven by hand. */
function harness(token: string | null = null) {
  const sockets: FakeSocket[] = [];
  const timers = new Map<number, { fn: () => void; ms: number }>();
  let next = 0;
  const factory: SocketFactory = (url, protocols) => {
    const s = new FakeSocket(url, protocols);
    sockets.push(s);
    return s;
  };
  const client = new LiveClient({
    config: CONFIG,
    getToken: () => token,
    socket: factory,
    random: () => 0.5,
    setTimer: (fn, ms) => {
      timers.set(++next, { fn, ms });
      return next;
    },
    clearTimer: (id) => timers.delete(id as number),
  });
  const fire = (ms: number) => {
    for (const [id, t] of [...timers]) {
      if (t.ms === ms) {
        timers.delete(id);
        t.fn();
      }
    }
  };
  const last = () => sockets[sockets.length - 1];
  return { client, sockets, timers, fire, last };
}

function decodeHeader(protocol: string) {
  const b64 = protocol.replace(/^header-/, '').replace(/-/g, '+').replace(/_/g, '/');
  return JSON.parse(atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4)));
}

describe('live push client (AppSync Events WebSocket)', () => {
  it('connects with the event subprotocol and the public key in a base64url header', () => {
    const { client, last } = harness();
    client.subscribe(CHANNELS.levels, () => {});
    const ws = last();
    expect(ws.url).toBe(`wss://${CONFIG.realtimeDomain}/event/realtime`);
    expect(ws.protocols[0]).toBe('aws-appsync-event-ws');
    expect(ws.protocols[1]).toMatch(/^header-[A-Za-z0-9_-]+$/);
    expect(decodeHeader(ws.protocols[1])).toEqual({ host: CONFIG.httpDomain, 'x-api-key': CONFIG.apiKey });
    expect(client.status).toBe('connecting');
    ws.open();
    expect(ws.sent).toEqual([{ type: 'connection_init' }]);
  });

  it('subscribes after connection_ack, goes live on subscribe_success and delivers data', () => {
    const { client, last } = harness('id-token');
    const got: LiveEvent[] = [];
    client.subscribe(CHANNELS.alerts, (e) => got.push(e));
    client.subscribe(CHANNELS.officer, (e) => got.push(e));
    const ws = last();
    ws.open();
    ws.receive({ type: 'connection_ack', connectionTimeoutMs: 300000 });
    const subs = ws.sent.filter((m) => m.type === 'subscribe');
    expect(subs).toHaveLength(2);
    const pub = subs.find((m) => m.channel === CHANNELS.alerts)!;
    const off = subs.find((m) => m.channel === CHANNELS.officer)!;
    // public channel: the API key; officer channel: the Cognito ID token
    expect(pub.authorization).toEqual({ host: CONFIG.httpDomain, 'x-api-key': CONFIG.apiKey });
    expect(off.authorization).toEqual({ host: CONFIG.httpDomain, Authorization: 'id-token' });
    expect(String(pub.id)).toMatch(/^[a-zA-Z0-9-_+]{1,128}$/);
    expect(client.isLive([CHANNELS.alerts])).toBe(false); // not until AppSync confirms

    ws.receive({ type: 'subscribe_success', id: pub.id });
    ws.receive({ type: 'subscribe_success', id: off.id });
    expect(client.status).toBe('live');
    expect(client.isLive([CHANNELS.alerts, CHANNELS.officer])).toBe(true);

    // event as one JSON string, and as a list of JSON strings
    ws.receive({ type: 'data', id: pub.id, event: JSON.stringify({ type: 'alert', alert_id: 'a1', status: 'approved' }) });
    ws.receive({ type: 'data', id: off.id, event: [JSON.stringify({ type: 'approval', kind: 'approved' })] });
    ws.receive({ type: 'data', id: 'unknown', event: '{}' });
    ws.receive({ type: 'data', id: pub.id, event: 'not json' });
    expect(got).toEqual([
      { channel: CHANNELS.alerts, data: { type: 'alert', alert_id: 'a1', status: 'approved' } },
      { channel: CHANNELS.officer, data: { type: 'approval', kind: 'approved' } },
    ]);
  });

  it('marks a refused subscription as failed and an officer channel without a token never asks', () => {
    const { client, last } = harness(null);
    client.subscribe(CHANNELS.levels, () => {});
    client.subscribe(CHANNELS.officer, () => {});
    const ws = last();
    ws.open();
    ws.receive({ type: 'connection_ack', connectionTimeoutMs: 300000 });
    const subs = ws.sent.filter((m) => m.type === 'subscribe');
    expect(subs.map((m) => m.channel)).toEqual([CHANNELS.levels]); // no token: officer not attempted
    expect(client.failed()).toEqual([CHANNELS.officer]);
    ws.receive({ type: 'subscribe_error', id: subs[0].id, errors: [{ errorType: 'UnauthorizedException' }] });
    expect(client.isLive([CHANNELS.levels])).toBe(false);
    expect(client.failed()).toEqual([CHANNELS.levels, CHANNELS.officer]);
  });

  it('treats a missing keep-alive as a dead connection and reconnects with backoff', () => {
    const { client, sockets, timers, fire, last } = harness();
    client.subscribe(CHANNELS.levels, () => {});
    const ws = last();
    ws.open();
    ws.receive({ type: 'connection_ack', connectionTimeoutMs: 1000 });
    expect([...timers.values()].map((t) => t.ms)).toEqual([1000]);
    ws.receive({ type: 'ka' }); // re-arms: still one keep-alive timer
    expect([...timers.values()].map((t) => t.ms)).toEqual([1000]);

    fire(1000); // no ka in time
    expect(ws.closed).toBe(true);
    expect(client.status).toBe('retrying');
    const delay = backoffMs(0, () => 0.5);
    expect([...timers.values()].map((t) => t.ms)).toEqual([delay]);
    fire(delay);
    expect(sockets).toHaveLength(2);
    const ws2 = last();
    ws2.open();
    ws2.receive({ type: 'connection_ack', connectionTimeoutMs: 300000 });
    expect(ws2.sent.filter((m) => m.type === 'subscribe').map((m) => m.channel)).toEqual([CHANNELS.levels]);
  });

  it('backs off after a socket close or a connection error, and grows the delay', () => {
    const { client, timers, fire, last, sockets } = harness('tok');
    client.subscribe(CHANNELS.levels, () => {});
    last().drop();
    const first = [...timers.values()][0].ms;
    fire(first);
    expect(sockets).toHaveLength(2);
    // the second attempt tries the signed-in token for the connection
    expect(decodeHeader(last().protocols[1])).toEqual({ host: CONFIG.httpDomain, Authorization: 'tok' });
    last().open();
    last().receive({ type: 'error', errors: [{ errorType: 'UnauthorizedException' }] });
    const second = [...timers.values()][0].ms;
    expect(second).toBeGreaterThan(first);
    expect(client.status).toBe('retrying');
  });

  it('closes on page hide without reconnecting, and resumes on show', () => {
    const { client, timers, last, sockets } = harness();
    client.subscribe(CHANNELS.levels, () => {});
    last().open();
    last().receive({ type: 'connection_ack', connectionTimeoutMs: 300000 });
    client.pause();
    expect(last().closed).toBe(true);
    expect(client.status).toBe('paused');
    expect(timers.size).toBe(0);
    client.resume();
    expect(sockets).toHaveLength(2);
    expect(client.status).toBe('connecting');
  });

  it('unsubscribes the last listener and closes when nobody listens', () => {
    const { client, last } = harness();
    const off1 = client.subscribe(CHANNELS.levels, () => {});
    const off2 = client.subscribe(CHANNELS.levels, () => {});
    const ws = last();
    ws.open();
    ws.receive({ type: 'connection_ack', connectionTimeoutMs: 300000 });
    const id = ws.sent.find((m) => m.type === 'subscribe')!.id;
    ws.receive({ type: 'subscribe_success', id });
    off1();
    expect(ws.sent.some((m) => m.type === 'unsubscribe')).toBe(false); // one listener left
    off2();
    expect(ws.sent.filter((m) => m.type === 'unsubscribe')).toEqual([{ type: 'unsubscribe', id }]);
    expect(ws.closed).toBe(true);
    expect(client.status).toBe('off');
  });

  it('encodes headers as unpadded base64url and caps the backoff', () => {
    expect(base64url({ a: '>>>?' })).not.toMatch(/[+/=]/);
    expect(backoffMs(0, () => 0)).toBe(500);
    expect(backoffMs(0, () => 1)).toBe(1000);
    expect(backoffMs(50, () => 1)).toBe(30000);
  });
});
