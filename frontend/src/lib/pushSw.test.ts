import { describe, expect, it, vi } from 'vitest';
import { confirmation, decisionRequest, notificationFromPush, parsePush, safePath, sendDecision, type PushPayload } from './pushSw';

const ORIGIN = 'https://main.example.amplifyapp.com';
const TOKEN = 'eyJhIjoiYWxyXzEifQ.c2ln';

// What services/officer_push.approval_payload sends (tests/test_push.py checks the server side).
const approval: PushPayload = {
  kind: 'approval',
  title: 'पुकार: थुनाग चेतावनी',
  body: 'पुकार: थुनाग के लिए चेतावनी।\n10 मिनट में मंज़ूरी दें · Approve within 10 min',
  tag: 'alr_1',
  renotify: true,
  requireInteraction: true,
  actions: [
    { action: 'approve', title: '✅ मंज़ूर' },
    { action: 'decline', title: '✖ नहीं' },
  ],
  data: { url: `${ORIGIN}/a/${TOKEN}`, alert_id: 'alr_1', token: TOKEN, drill: false },
};

describe('push notification', () => {
  it('shows the approval request with Approve and Decline and keeps the token', () => {
    const n = notificationFromPush(approval, ORIGIN);
    expect(n.title).toBe('पुकार: थुनाग चेतावनी');
    expect(n.options.tag).toBe('alr_1');
    expect(n.options.renotify).toBe(true);
    expect(n.options.requireInteraction).toBe(true);
    expect(n.options.actions).toEqual([
      { action: 'approve', title: '✅ मंज़ूर' },
      { action: 'decline', title: '✖ नहीं' },
    ]);
    expect(n.options.data).toEqual({ kind: 'approval', url: `/a/${TOKEN}`, alert_id: 'alr_1', token: TOKEN });
  });

  it('drops unknown actions and any action without a token', () => {
    const odd = notificationFromPush({ ...approval, actions: [{ action: 'delete-everything', title: 'x' }, { action: 'approve' }] }, ORIGIN);
    expect(odd.options.actions).toEqual([{ action: 'approve', title: '✅ मंज़ूर' }]);
    const test = notificationFromPush({ kind: 'test', title: 'Test', actions: [{ action: 'approve' }], data: { url: `${ORIGIN}/console` } }, ORIGIN);
    expect(test.options.actions).toBeUndefined();
    expect(test.options.data.url).toBe('/console');
  });

  it('never opens another site', () => {
    expect(safePath('https://evil.example/steal', ORIGIN, '/console')).toBe('/console');
    expect(safePath('https://evil.example/a/x', ORIGIN, '/console')).toBe('/a/x'); // our own page, on this origin
    expect(safePath('javascript:alert(1)', ORIGIN, '/console')).toBe('/console');
    expect(safePath(undefined, ORIGIN, '/a/t')).toBe('/a/t');
    // the API's web URL can differ from this origin (preview deploys): our own paths are kept
    expect(safePath('https://other.example/a/tok', ORIGIN, '/console')).toBe('/a/tok');
    expect(safePath(`${ORIGIN}/console?alert=a1`, ORIGIN, '/')).toBe('/console?alert=a1');
  });

  it('survives an empty or non-JSON push', () => {
    expect(parsePush(null)).toEqual({});
    expect(parsePush('[1,2]')).toEqual({});
    expect(parsePush('plain words').body).toBe('plain words');
    const n = notificationFromPush({}, ORIGIN);
    expect(n.title).toBe('पुकार · Pukaar');
    expect(n.options.data.url).toBe('/console');
  });
});

describe('notification buttons', () => {
  it('POST the decision to the public signed-link route, same body as the approval page', () => {
    const { url, init } = decisionRequest('https://api.example.com/', TOKEN, 'decline');
    expect(url).toBe(`https://api.example.com/approval/${TOKEN}`);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ decision: 'decline' });
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it('report the status, or 0 when offline', async () => {
    const ok = vi.fn().mockResolvedValue({ status: 200 });
    expect(await sendDecision(ok, 'https://api.example.com', TOKEN, 'approve')).toBe(200);
    expect(ok).toHaveBeenCalledWith(`https://api.example.com/approval/${TOKEN}`, expect.objectContaining({ method: 'POST' }));
    const offline = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    expect(await sendDecision(offline, 'https://api.example.com', TOKEN, 'approve')).toBe(0);
  });

  it('confirm the outcome in a notification that replaces the request', () => {
    const data = { kind: 'approval', url: `/a/${TOKEN}`, alert_id: 'alr_1', token: TOKEN };
    const ok = confirmation('approve', 200, data);
    expect(ok.title).toContain('Approved');
    expect(ok.options.tag).toBe('alr_1');
    expect(ok.options.data.url).toBe('/console?alert=alr_1');
    expect(confirmation('decline', 200, data).title).toContain('Declined');
    expect(confirmation('approve', 409, data).title).toContain('Already decided');
    expect(confirmation('approve', 400, data).title).toContain('not valid');
    const failed = confirmation('approve', 0, data);
    expect(failed.title).toContain('not sent');
    expect(failed.options.requireInteraction).toBe(true);
    expect(failed.options.data.url).toBe(`/a/${TOKEN}`); // tap to open the approval page and try again
    expect(confirmation('approve', 503, data).options.data.url).toBe(`/a/${TOKEN}`);
  });
});
