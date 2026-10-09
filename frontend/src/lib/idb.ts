import { openDB } from 'idb';
import type { DBSchema, IDBPDatabase } from 'idb';

export interface PendingAttachment {
  blob: Blob;
  name: string;
  type: string;
}

/** A report saved on the phone while offline. Field names follow POST /reports. */
export interface PendingReport {
  id?: number;
  village_id: string;
  text?: string;
  lat?: number | null;
  lon?: number | null;
  reporter_name?: string;
  photo?: PendingAttachment;
  audio?: PendingAttachment;
  createdAt: number;
}

interface PukaarDB extends DBSchema {
  reports: {
    value: PendingReport;
    key: number;
    indexes: { 'by-date': number };
  };
}

let dbPromise: Promise<IDBPDatabase<PukaarDB>> | null = null;

function db() {
  // v2: fields renamed to match the CONTRACT; old v1 queue is dropped.
  dbPromise ??= openDB<PukaarDB>('pukaar-queue', 2, {
    upgrade(database) {
      if (database.objectStoreNames.contains('reports')) database.deleteObjectStore('reports');
      const store = database.createObjectStore('reports', { keyPath: 'id', autoIncrement: true });
      store.createIndex('by-date', 'createdAt');
    },
  });
  return dbPromise;
}

export async function saveReportOffline(report: Omit<PendingReport, 'id' | 'createdAt'>): Promise<number> {
  return (await db()).add('reports', { ...report, createdAt: Date.now() });
}

export function toPendingAttachment(blob: Blob | null | undefined, fallbackName: string): PendingAttachment | undefined {
  if (!blob) return undefined;
  const name = blob instanceof File && blob.name ? blob.name : fallbackName;
  return { blob, name, type: blob.type || 'application/octet-stream' };
}

export function attachmentToFile(attachment: PendingAttachment, fallbackName: string): File {
  const name = attachment.name || fallbackName;
  const type = attachment.type || attachment.blob.type || 'application/octet-stream';
  return new File([attachment.blob], name, { type });
}

export async function getPendingReports(): Promise<PendingReport[]> {
  return (await db()).getAllFromIndex('reports', 'by-date');
}

export async function deleteReportOffline(id: number): Promise<void> {
  await (await db()).delete('reports', id);
}
