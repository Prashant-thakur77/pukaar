import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as idb from './lib/idb';
import type { PendingReport } from './lib/idb';
import { flushQueue } from './lib/queue';
import { myTrackCodes, useNet } from './store';

vi.mock('./lib/idb', async (orig) => {
  const real = await orig<typeof import('./lib/idb')>();
  return {
    attachmentToFile: real.attachmentToFile,
    getPendingReports: vi.fn(),
    deleteReportOffline: vi.fn(),
  };
});

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function queued(over: Partial<PendingReport> = {}): PendingReport {
  return {
    id: 1,
    village_id: 'thunag',
    text: 'पानी पुल तक आ गया',
    lat: 31.56,
    lon: 77.17,
    audio: { blob: new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/webm' }), name: 'voice.webm', type: 'audio/webm' },
    photo: { blob: new Blob(['jpg'], { type: 'image/jpeg' }), name: 'photo.jpg', type: 'image/jpeg' },
    createdAt: 1,
    ...over,
  };
}

describe('offline queue flush', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useNet.setState({ queued: 0 });
    Object.defineProperty(globalThis, 'fetch', { configurable: true, writable: true, value: fetchMock });
  });

  it('POSTs each queued report as CONTRACT multipart and removes it', async () => {
    vi.mocked(idb.getPendingReports).mockResolvedValueOnce([queued()]).mockResolvedValueOnce([]);
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { report: { id: 'r1' }, track_code: 'PK42' }));

    const res = await flushQueue();

    expect(res).toEqual({ sent: 1, failed: 0, codes: ['PK42'] });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/reports$/);
    expect(init?.method).toBe('POST');
    const form = init?.body as FormData;
    expect(form.get('village_id')).toBe('thunag');
    expect(form.get('text')).toBe('पानी पुल तक आ गया');
    expect(form.get('lat')).toBe('31.56');
    expect(form.get('lon')).toBe('77.17');
    expect(form.get('offline_created')).toBe('true');
    const audio = form.get('audio') as File;
    expect(audio).toBeInstanceOf(File);
    expect(audio.name).toBe('voice.webm');
    expect(audio.type).toBe('audio/webm');
    expect((form.get('photo') as File).name).toBe('photo.jpg');
    // Old field names from the previous app must be gone.
    expect(form.get('site_id')).toBeNull();
    expect(form.get('transcript_text')).toBeNull();
    expect(idb.deleteReportOffline).toHaveBeenCalledWith(1);
    expect(myTrackCodes()[0].code).toBe('PK42');
    expect(useNet.getState().queued).toBe(0);
  });

  it('keeps reports queued when the network is down', async () => {
    vi.mocked(idb.getPendingReports).mockResolvedValueOnce([queued({ id: 1 }), queued({ id: 2 })]).mockResolvedValueOnce([queued(), queued()]);
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    const res = await flushQueue();

    expect(res.sent).toBe(0);
    expect(fetchMock).toHaveBeenCalledTimes(1); // stops at the first network failure
    expect(idb.deleteReportOffline).not.toHaveBeenCalled();
    expect(useNet.getState().queued).toBe(2);
  });

  it('drops a report the server rejects (4xx) and keeps going', async () => {
    vi.mocked(idb.getPendingReports).mockResolvedValueOnce([queued({ id: 1, village_id: 'nowhere' }), queued({ id: 2 })]).mockResolvedValueOnce([]);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(422, { detail: 'Unknown village' }))
      .mockResolvedValueOnce(jsonResponse(200, { report: { id: 'r2' }, track_code: 'PK2' }));

    const res = await flushQueue();

    expect(res).toEqual({ sent: 1, failed: 1, codes: ['PK2'] });
    expect(idb.deleteReportOffline).toHaveBeenCalledWith(1);
    expect(idb.deleteReportOffline).toHaveBeenCalledWith(2);
  });

  it('omits optional fields that are empty', async () => {
    vi.mocked(idb.getPendingReports).mockResolvedValueOnce([queued({ text: undefined, audio: undefined, photo: undefined, lat: null, lon: null })]).mockResolvedValueOnce([]);
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { report: { id: 'r3' }, track_code: 'PK3' }));
    await flushQueue();
    const form = fetchMock.mock.calls[0][1]?.body as FormData;
    expect([...form.keys()].sort()).toEqual(['offline_created', 'village_id']);
  });
});
