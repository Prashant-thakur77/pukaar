import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, cognitoSignIn, cognitoTotp, prefetchRoute } from './api';
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

  it('a village page fetched at boot is taken over by the page, not fetched twice', async () => {
    fetchMock.mockImplementation(async (u) => json(200, { url: String(u) }));
    prefetchRoute('/village/thunag');
    // The small answer first, then the full detail and the safe places.
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/public\/villages\/thunag\/now$/);
    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/villages\/thunag$/);
    expect(String(fetchMock.mock.calls[2][0])).toMatch(/\/villages\/thunag\/safe-places$/);
    const now = (await api.villageNow('thunag')) as unknown as { url: string };
    const v = (await api.village('thunag')) as unknown as { url: string };
    await api.safePlaces('thunag');
    expect(now.url).toMatch(/\/now$/);
    expect(v.url).toMatch(/\/villages\/thunag$/);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    // Taken once: the next poll fetches again. Other routes start nothing early.
    await api.village('thunag');
    expect(fetchMock).toHaveBeenCalledTimes(4);
    prefetchRoute('/report');
    expect(fetchMock).toHaveBeenCalledTimes(4);
    fetchMock.mockReset();
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

  it('web push: the key is fetched signed out; subscriptions carry the token and remove with DELETE', async () => {
    useAuth.setState({ token: 'tok123' });
    fetchMock
      .mockResolvedValueOnce(json(200, { key: 'BAAA', configured: true }))
      .mockResolvedValueOnce(json(200, { id: 'abc', user_agent: 'Chrome on Android', created_at: 'x', last_sent_at: null }))
      .mockResolvedValueOnce(json(200, { ok: true, id: 'abc' }))
      .mockResolvedValueOnce(json(429, { detail: { code: 'rate_limited', reason: 'One test notification a minute.' } }));
    await api.vapidKey();
    await api.addPushSubscription({ endpoint: 'https://fcm.googleapis.com/fcm/send/x', keys: { p256dh: 'B', auth: 'A' } });
    await api.removePushSubscription('abc');
    const err = (await api.pushTest().catch((e) => e)) as ApiError;
    const [u0, i0] = fetchMock.mock.calls[0];
    expect(String(u0)).toMatch(/\/push\/vapid-public-key$/);
    expect((i0?.headers as Record<string, string>).Authorization).toBeUndefined();
    const [, i1] = fetchMock.mock.calls[1];
    expect(i1?.method).toBe('POST');
    expect(JSON.parse(String(i1?.body)).keys.p256dh).toBe('B');
    expect((i1?.headers as Record<string, string>).Authorization).toBe('Bearer tok123');
    const [u2, i2] = fetchMock.mock.calls[2];
    expect(String(u2)).toMatch(/\/me\/push-subscriptions\/abc$/);
    expect(i2?.method).toBe('DELETE');
    expect(err.status).toBe(429);
    expect(err.code).toBe('rate_limited');
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

  it('marks a 503 workflow hiccup as retryable, not late', async () => {
    fetchMock.mockResolvedValueOnce(json(503, { detail: { code: 'retry', reason: 'Step Functions unreachable' } }));
    const err = (await api.approve('a1').catch((e) => e)) as ApiError;
    expect(err.isRetry).toBe(true);
    expect(err.isLate).toBe(false);
    expect(err.code).toBe('retry');
    expect(err.messageEn).toBe('Step Functions unreachable');
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

  it('roll-call: board and remind carry the token, the family link does not', async () => {
    useAuth.setState({ token: 'tok123' });
    fetchMock
      .mockResolvedValueOnce(json(200, []))
      .mockResolvedValueOnce(json(200, { first_name: null, village_name: 'Gohar', village_name_hi: 'गोहर', at: '2026-10-11T20:48:00Z', status: 'safe', exercise: false, simulated: false }));
    await api.rollcalls('gohar');
    const view = await api.safe('a.b');
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/rollcalls\?village_id=gohar$/);
    expect((fetchMock.mock.calls[0][1]?.headers as Record<string, string>).Authorization).toBe('Bearer tok123');
    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/safe\/a\.b$/);
    expect((fetchMock.mock.calls[1][1]?.headers as Record<string, string>).Authorization).toBeUndefined();
    expect(Object.keys(view).sort()).toEqual(['at', 'exercise', 'first_name', 'simulated', 'status', 'village_name', 'village_name_hi']);
  });

  it('roll-call: a reminder too soon is a 429 with both languages', async () => {
    fetchMock.mockResolvedValueOnce(
      json(429, { detail: { code: 'rate_limited', retry_after_seconds: 900, message_en: 'Try again in 15 min.', message_hi: '15 मिनट बाद फिर कोशिश करें।' } }),
    );
    const err = (await api.remindRollcall('rc_1').catch((e) => e)) as ApiError;
    expect(err.status).toBe(429);
    expect(err.code).toBe('rate_limited');
    expect(err.messageHi).toBe('15 मिनट बाद फिर कोशिश करें।');
    expect(fetchMock.mock.calls[0][1]?.method).toBe('POST');
  });

  it('flags sample data from the dev mock', async () => {
    fetchMock.mockResolvedValueOnce(json(200, [{ id: 'x', _sample: true }]));
    await api.villages();
    expect(useNet.getState().sample).toBe(true);
  });
});

describe('Cognito sign-in with an authenticator app (MFA)', () => {
  const amz = (i: number) => ({
    url: String(fetchMock.mock.calls[i][0]),
    target: (fetchMock.mock.calls[i][1]?.headers as Record<string, string>)['X-Amz-Target'],
    body: JSON.parse(String(fetchMock.mock.calls[i][1]?.body)) as Record<string, unknown>,
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv('VITE_COGNITO_REGION', 'ap-south-1');
    vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'client123');
    Object.defineProperty(globalThis, 'fetch', { configurable: true, writable: true, value: fetchMock });
  });
  afterEach(() => vi.unstubAllEnvs());

  it('a password alone is enough when the account has no MFA', async () => {
    fetchMock.mockResolvedValueOnce(json(200, { AuthenticationResult: { IdToken: 'id-1' } }));
    expect(await cognitoSignIn('officer1', 'pw')).toEqual({ kind: 'done', token: 'id-1' });
    const c = amz(0);
    expect(c.url).toBe('https://cognito-idp.ap-south-1.amazonaws.com/');
    expect(c.target).toBe('AWSCognitoIdentityProviderService.InitiateAuth');
    expect(c.body).toMatchObject({ AuthFlow: 'USER_PASSWORD_AUTH', ClientId: 'client123' });
  });

  it('an enrolled account answers SOFTWARE_TOKEN_MFA with the app code', async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { ChallengeName: 'SOFTWARE_TOKEN_MFA', Session: 's1', ChallengeParameters: { USER_ID_FOR_SRP: 'dso_mandi' } }))
      .mockResolvedValueOnce(json(200, { AuthenticationResult: { IdToken: 'id-2' } }));
    const step = await cognitoSignIn('DSO_Mandi', 'pw');
    expect(step).toEqual({ kind: 'totp', username: 'dso_mandi', session: 's1' });
    if (step.kind === 'done') throw new Error('expected a TOTP step');
    expect(await cognitoTotp(step, '123 456')).toBe('id-2');
    const c = amz(1);
    expect(c.target).toBe('AWSCognitoIdentityProviderService.RespondToAuthChallenge');
    expect(c.body).toEqual({
      ChallengeName: 'SOFTWARE_TOKEN_MFA',
      ClientId: 'client123',
      Session: 's1',
      ChallengeResponses: { USERNAME: 'dso_mandi', SOFTWARE_TOKEN_MFA_CODE: '123456' },
    });
  });

  it('a first sign-in with MFA required registers the app (MFA_SETUP), then signs in', async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { ChallengeName: 'MFA_SETUP', Session: 's1', ChallengeParameters: {} }))
      .mockResolvedValueOnce(json(200, { SecretCode: 'JBSWY3DPEHPK3PXP', Session: 's2' }))
      .mockResolvedValueOnce(json(200, { Status: 'SUCCESS', Session: 's3' }))
      .mockResolvedValueOnce(json(200, { AuthenticationResult: { IdToken: 'id-3' } }));
    const step = await cognitoSignIn('officer1', 'pw');
    expect(step).toMatchObject({ kind: 'setup', username: 'officer1', session: 's2', secret: 'JBSWY3DPEHPK3PXP' });
    if (step.kind !== 'setup') throw new Error('expected the setup step');
    expect(step.uri).toBe('otpauth://totp/Pukaar:officer1?secret=JBSWY3DPEHPK3PXP&issuer=Pukaar');
    expect(amz(1)).toMatchObject({ target: 'AWSCognitoIdentityProviderService.AssociateSoftwareToken', body: { Session: 's1' } });
    expect(await cognitoTotp(step, '654321')).toBe('id-3');
    expect(amz(2)).toMatchObject({
      target: 'AWSCognitoIdentityProviderService.VerifySoftwareToken',
      body: { Session: 's2', UserCode: '654321' },
    });
    expect(amz(3).body).toEqual({ ChallengeName: 'MFA_SETUP', ClientId: 'client123', Session: 's3', ChallengeResponses: { USERNAME: 'officer1' } });
  });

  it('a wrong code is an error, and no token is returned', async () => {
    fetchMock.mockResolvedValueOnce(json(400, { __type: 'CodeMismatchException', message: 'Invalid code received for user' }));
    const err = (await cognitoTotp({ kind: 'totp', username: 'u', session: 's' }, '000000').catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(400);
    fetchMock.mockResolvedValueOnce(json(200, { Status: 'ERROR' }));
    const setup = { kind: 'setup' as const, username: 'u', session: 's', secret: 'K', uri: 'otpauth://x' };
    expect(((await cognitoTotp(setup, '000000').catch((e) => e)) as ApiError).status).toBe(400);
    expect(fetchMock).toHaveBeenCalledTimes(2); // never went on to RespondToAuthChallenge
  });
});
