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
  decision_trace?: string | null;
  reasoning_summary?: string | null;
  reasoning_chain?: string | null;
  reasoning_model?: string | null;
}

export interface SiteExperimentalSettings {
  site_id: string;
  historical_context_enabled: boolean;
  forecast_enabled: boolean;
  forecast_horizon_minutes: number;
  forecast_critical_threshold: number;
  updated_at: string;
}

export interface HistoricalContextHit {
  id: number;
  source: string;
  title: string;
  summary: string;
  threshold_level?: number | null;
  jurisdiction?: string | null;
  effective_from?: string | null;
  effective_to?: string | null;
  source_uri?: string | null;
  rank: number;
}

interface AppState {
  isOnline: boolean;
  sites: Site[];
  alerts: FusedAlert[];
  queueCount: number;
  siteSettings: Record<string, SiteExperimentalSettings>;
  siteHistoricalContext: Record<string, HistoricalContextHit[]>;
  setOnline: (status: boolean) => void;
  fetchSites: () => Promise<void>;
  fetchAlerts: (options?: { historicalContext?: boolean }) => Promise<void>;
  fetchSiteExperimentalSettings: (siteId: string) => Promise<SiteExperimentalSettings | null>;
  updateSiteExperimentalSettings: (siteId: string, payload: Partial<SiteExperimentalSettings>) => Promise<SiteExperimentalSettings | null>;
  fetchSiteHistoricalContext: (siteId: string, options?: { waterLevel?: number; query?: string }) => Promise<HistoricalContextHit[]>;
  checkConnectivity: () => Promise<void>;
  updateQueueCount: () => Promise<void>;
  flushQueue: () => Promise<void>;
}

export const useAppStore = create<AppState>((set, get) => ({
  isOnline: true,
  sites: [],
  alerts: [],
  queueCount: 0,
  siteSettings: {},
  siteHistoricalContext: {},

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

  fetchAlerts: async (options) => {
    try {
      const query = options?.historicalContext ? '?historical_context=true' : '';
      const res = await fetch(`${API_BASE}/alerts${query}`);
      if (res.ok) {
        const data = await res.json();
        set({ alerts: data });
      }
    } catch (err) {
      console.error('Failed to fetch alerts', err);
    }
  },

  fetchSiteExperimentalSettings: async (siteId) => {
    try {
      const res = await fetch(`${API_BASE}/sites/${encodeURIComponent(siteId)}/experimental-settings`);
      if (!res.ok) return null;
      const data = (await res.json()) as SiteExperimentalSettings;
      set((state) => ({ siteSettings: { ...state.siteSettings, [siteId]: data } }));
      return data;
    } catch (err) {
      console.error('Failed to fetch site experimental settings', err);
      return null;
    }
  },

  updateSiteExperimentalSettings: async (siteId, payload) => {
    try {
      const res = await fetch(`${API_BASE}/sites/${encodeURIComponent(siteId)}/experimental-settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) return null;
      const data = (await res.json()) as SiteExperimentalSettings;
      set((state) => ({ siteSettings: { ...state.siteSettings, [siteId]: data } }));
      return data;
    } catch (err) {
      console.error('Failed to update site experimental settings', err);
      return null;
    }
  },

  fetchSiteHistoricalContext: async (siteId, options) => {
    try {
      const params = new URLSearchParams();
      if (typeof options?.waterLevel === 'number') params.set('water_level', String(options.waterLevel));
      if (options?.query) params.set('query', options.query);
      const qs = params.toString();
      const res = await fetch(`${API_BASE}/sites/${encodeURIComponent(siteId)}/historical-context${qs ? `?${qs}` : ''}`);
      if (!res.ok) return [];
      const data = await res.json();
      const hits = Array.isArray(data.hits) ? data.hits as HistoricalContextHit[] : [];
      set((state) => ({ siteHistoricalContext: { ...state.siteHistoricalContext, [siteId]: hits } }));
      return hits;
    } catch (err) {
      console.error('Failed to fetch site historical context', err);
      return [];
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
      await updateQueueCount();
      alert(`Successfully sent ${successCount} reports from queue.`);
      return;
    }

    await updateQueueCount();
  },
}));
