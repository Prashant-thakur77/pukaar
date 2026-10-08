import { create } from 'zustand';
import {
  attachmentToFile,
  deleteReportOffline,
  getPendingReports,
  type PendingAttachment,
} from './lib/idb';

export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api';

function appendAttachment(
  formData: FormData,
  fieldName: 'photo' | 'audio',
  attachment?: PendingAttachment,
) {
  if (!attachment) {
    return;
  }

  const fallbackName = fieldName === 'photo' ? 'evidence-photo.bin' : 'evidence-audio.bin';
  formData.append(fieldName, attachmentToFile(attachment, fallbackName));
}

export interface Site {
  id: string;
  name: string;
  region: string;
  lat: number;
  lng: number;
  description?: string;
  is_active: boolean;
}

export interface FusedAlert {
  id: number;
  site_id: string;
  level: 'green' | 'yellow' | 'orange' | 'red';
  score: number;
  summary: string;
  created_at: string;
  trigger_source?: string;
  reasoning_summary?: string | null;
  reasoning_chain?: string | null;
  reasoning_model?: string | null;
}

interface AppState {
  isOnline: boolean;
  sites: Site[];
  alerts: FusedAlert[];
  queueCount: number;
  setOnline: (status: boolean) => void;
  fetchSites: () => Promise<void>;
  fetchAlerts: () => Promise<void>;
  checkConnectivity: () => Promise<void>;
  updateQueueCount: () => Promise<void>;
  flushQueue: () => Promise<void>;
}

export const useAppStore = create<AppState>((set, get) => ({
  isOnline: true,
  sites: [],
  alerts: [],
  queueCount: 0,

  setOnline: (status) => set({ isOnline: status }),

  fetchSites: async () => {
    try {
      const res = await fetch(`${API_BASE}/sites`);
      if (res.ok) {
        const data = await res.json();
        set({ sites: data });
      }
    } catch (err) {
      console.error('Failed to fetch sites', err);
    }
  },

  fetchAlerts: async () => {
    try {
      const res = await fetch(`${API_BASE}/alerts`);
      if (res.ok) {
        const data = await res.json();
        set({ alerts: data });
      }
    } catch (err) {
      console.error('Failed to fetch alerts', err);
    }
  },

  checkConnectivity: async () => {
    try {
      const res = await fetch(`${API_BASE}/settings/connectivity`);
      if (res.ok) {
        const data = await res.json();
        set({ isOnline: data.is_online });
      } else {
        set({ isOnline: false });
      }
    } catch {
      set({ isOnline: false });
    }
    await get().updateQueueCount();
  },

  updateQueueCount: async () => {
    const pending = await getPendingReports();
    set({ queueCount: pending.length });
  },

  flushQueue: async () => {
    const { isOnline, updateQueueCount } = get();
    if (!isOnline) {
      alert('Cannot flush queue while offline');
      return;
    }

    const pending = await getPendingReports();
    if (pending.length === 0) {
      return;
    }

    let successCount = 0;
    for (const report of pending) {
      try {
        const formData = new FormData();
        formData.append('site_id', report.site_id);
        formData.append('reporter_name', report.reporter_name);
        formData.append('reporter_role', report.reporter_role);
        formData.append('transcript_text', report.transcript_text);
        formData.append('offline_created', String(report.offline_created));
        appendAttachment(formData, 'photo', report.photo_attachment);
        appendAttachment(formData, 'audio', report.audio_attachment);

        const res = await fetch(`${API_BASE}/reports`, {
          method: 'POST',
          body: formData,
        });

        if (res.ok) {
          await deleteReportOffline(report.id as number);
          successCount++;
        }
      } catch (err) {
        console.error('Failed to send report from queue', err);
      }
    }

    if (successCount > 0) {
      try {
        await fetch(`${API_BASE}/sync/flush`, { method: 'POST' });
      } catch (err) {
        console.error('Failed to flush backend sync queue', err);
      }

      await updateQueueCount();
      alert(`Successfully sent ${successCount} reports from queue.`);
      return;
    }

    await updateQueueCount();
  },
}));
