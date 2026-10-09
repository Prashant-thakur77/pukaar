import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as idb from './idb';
import { flushQueue } from './queue';
import { resolvePhase, type Phase } from './reportPhase';
import { useNet } from '../store';

vi.mock('./idb', async (orig) => {
  const real = await orig<typeof import('./idb')>();
  return { attachmentToFile: real.attachmentToFile, getPendingReports: vi.fn(), deleteReportOffline: vi.fn() };
});

const fetchMock = vi.fn<typeof fetch>();

describe('report screen: queued -> done', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useNet.setState({ queued: 0, flushed: {} });
    Object.defineProperty(globalThis, 'fetch', { configurable: true, writable: true, value: fetchMock });
  });

  it('stays queued until the queue reports this id as sent', () => {
    const queued: Phase = { k: 'queued', id: 7 };
    expect(resolvePhase(queued, {})).toBe(queued);
    expect(resolvePhase(queued, { 8: 'PKOTHER' })).toBe(queued);
    expect(resolvePhase(queued, { 7: 'PK77' })).toEqual({ k: 'done', code: 'PK77', late: true });
  });

  it('leaves other phases alone', () => {
    const done: Phase = { k: 'done', code: 'PK1' };
    expect(resolvePhase(done, { 7: 'PK77' })).toBe(done);
    expect(resolvePhase({ k: 'queued', id: null }, { 7: 'PK77' })).toEqual({ k: 'queued', id: null });
  });

  it('a flush after reconnecting turns the queued screen into the tracking code', async () => {
    vi.mocked(idb.getPendingReports)
      .mockResolvedValueOnce([{ id: 7, village_id: 'thunag', text: 'पानी बढ़ रहा है', createdAt: 1 }])
      .mockResolvedValueOnce([]);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ report: { id: 'r7' }, track_code: 'PK77' }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    const phase: Phase = { k: 'queued', id: 7 };

    await flushQueue();

    expect(useNet.getState().flushed).toEqual({ 7: 'PK77' });
    expect(resolvePhase(phase, useNet.getState().flushed)).toEqual({ k: 'done', code: 'PK77', late: true });
  });

  it('a failed flush keeps the queued screen', async () => {
    vi.mocked(idb.getPendingReports).mockResolvedValueOnce([{ id: 7, village_id: 'thunag', createdAt: 1 }]).mockResolvedValueOnce([{ id: 7, village_id: 'thunag', createdAt: 1 }]);
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await flushQueue();
    expect(resolvePhase({ k: 'queued', id: 7 }, useNet.getState().flushed)).toEqual({ k: 'queued', id: 7 });
  });
});
