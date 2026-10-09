import { api, ApiError } from '../api';
import { rememberTrackCode, useNet } from '../store';
import { attachmentToFile, deleteReportOffline, getPendingReports } from './idb';

export interface FlushResult {
  sent: number;
  failed: number;
  codes: string[];
}

let flushing: Promise<FlushResult> | null = null;

export async function refreshQueueCount(): Promise<number> {
  try {
    const n = (await getPendingReports()).length;
    useNet.getState().setQueued(n);
    return n;
  } catch {
    return 0;
  }
}

/**
 * Send every queued report as POST /reports multipart. A report leaves the
 * queue only after the server accepts it. Network errors stop the run (we are
 * offline again); a 4xx drops that one report so it cannot block the queue.
 */
export function flushQueue(): Promise<FlushResult> {
  flushing ??= (async () => {
    const result: FlushResult = { sent: 0, failed: 0, codes: [] };
    const pending = await getPendingReports();
    for (const item of pending) {
      try {
        const res = await api.createReport({
          village_id: item.village_id,
          text: item.text,
          lat: item.lat,
          lon: item.lon,
          reporter_name: item.reporter_name,
          audio: item.audio ? attachmentToFile(item.audio, 'voice.webm') : null,
          photo: item.photo ? attachmentToFile(item.photo, 'photo.jpg') : null,
          offline_created: true,
        });
        if (item.id != null) await deleteReportOffline(item.id);
        rememberTrackCode(res.track_code);
        result.sent++;
        result.codes.push(res.track_code);
      } catch (err) {
        result.failed++;
        if (err instanceof ApiError && err.status >= 400 && err.status < 500 && err.status !== 408 && err.status !== 429) {
          if (item.id != null) await deleteReportOffline(item.id);
          continue;
        }
        break;
      }
    }
    await refreshQueueCount();
    return result;
  })().finally(() => {
    flushing = null;
  });
  return flushing;
}
