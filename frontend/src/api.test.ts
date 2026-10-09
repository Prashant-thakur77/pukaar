import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';
import { useAuth, useNet } from './store';

const fetchMock = vi.fn<typeof fetch>();
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('api client', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useAuth.setState({ token: null, user: null });
    useNet.setState({ sample: false });
    Object.defineProperty(globalThis, 'fetch', { configurable: true, writable: true, value: fetchMock });
  });

  it('sends the bearer token on officer routes and not on public ones', async () => {
    useAuth.setState({ token: 'tok123' });
    fetchMock.mockResolvedValueOnce(json(200, [])).mockResolvedValueOnce(json(200, { counters: {}, villages: [], recent_alerts: [], replay: { active: false } }));
    await api.alerts({ status: 'pending' });
    await api.overview();
    const [u1, i1] = fetchMock.mock.calls[0];
    expect(String(u1)).toMatch(/\/alerts\?status=pending$/);
    expect((i1?.headers as Record<string, string>).Authorization).toBe('Bearer tok123');
    expect((fetchMock.mock.calls[1][1]?.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('turns a 409 late approval into a typed error with both languages', async () => {
    fetchMock.mockResolvedValueOnce(json(409, { detail: { code: 'late', message_en: 'Already decided.', message_hi: 'पहले ही फ़ैसला हो चुका है।' } }));
    const err = (await api.approve('a1').catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.isLate).toBe(true);
    expect(err.code).toBe('late');
    expect(err.messageEn).toBe('Already decided.');
    expect(err.messageHi).toBe('पहले ही फ़ैसला हो चुका है।');
  });

  it('reads a 403 denial reason (string or object)', async () => {
    fetchMock.mockResolvedValueOnce(json(403, { detail: 'pradhan cannot approve alerts' }));
    const e1 = (await api.approve('a1').catch((e) => e)) as ApiError;
    expect(e1.isDenied).toBe(true);
    expect(e1.messageEn).toBe('pradhan cannot approve alerts');

    fetchMock.mockResolvedValueOnce(json(403, { detail: { code: 'policy_denied', reason: 'Policy officer-approves-alerts' } }));
    const e2 = (await api.approve('a1').catch((e) => e)) as ApiError;
    expect(e2.messageEn).toBe('Policy officer-approves-alerts');
    expect(e2.code).toBe('policy_denied');
  });

  it('reports network failure as status 0', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const err = (await api.villages().catch((e) => e)) as ApiError;
    expect(err.status).toBe(0);
    expect(err.isNetwork).toBe(true);
  });

  it('handles FastAPI validation arrays and non-JSON bodies', async () => {
    fetchMock.mockResolvedValueOnce(json(422, { detail: [{ loc: ['body', 'state'], msg: 'Input should be a valid state' }] }));
    const e1 = (await api.setReportState('r1', 'verified').catch((e) => e)) as ApiError;
    expect(e1.messageEn).toBe('Input should be a valid state');

    fetchMock.mockResolvedValueOnce(new Response('Bad gateway', { status: 502 }));
    const e2 = (await api.villages().catch((e) => e)) as ApiError;
    expect(e2.status).toBe(502);
    expect(e2.messageEn).toBe('Bad gateway');
  });

  it('signs out on 401 when a token was used', async () => {
    useAuth.setState({ token: 'expired', user: { username: 'officer1', role: 'officer', village_ids: [] } });
    fetchMock.mockResolvedValueOnce(json(401, { detail: 'expired' }));
    await api.me().catch(() => {});
    expect(useAuth.getState().token).toBeNull();
  });

  it('flags sample data from the dev mock', async () => {
    fetchMock.mockResolvedValueOnce(json(200, [{ id: 'x', _sample: true }]));
    await api.villages();
    expect(useNet.getState().sample).toBe(true);
  });
});
