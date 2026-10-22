// Pukaar Raahat routes (docs/CONTRACT.md), apart from api.ts so the villager report page's main bundle never
// carries them: only the lazily loaded Raahat pages and panels import this.
import { request } from '../api';
import type {
  RaahatAnchor,
  RaahatAttestations,
  RaahatHousehold,
  RaahatLedger,
  RaahatPool,
  RaahatRelease,
  RaahatRelief,
} from '../types';

const enc = encodeURIComponent;

export const raahatApi = {
  raahatPool: () => request<RaahatPool>('/raahat/pool', { auth: false }),
  raahatAnchor: (alertId: string) => request<RaahatAnchor>(`/raahat/alerts/${enc(alertId)}`, { auth: false }),
  raahatLedger: (villageId = '') =>
    request<RaahatLedger>(`/raahat/ledger${villageId ? `?village_id=${enc(villageId)}` : ''}`, { auth: false }),
  raahatRelief: (alertId: string) => request<RaahatRelief>(`/raahat/alerts/${enc(alertId)}/relief`),
  raahatAttestations: (alertId: string) =>
    request<RaahatAttestations>(`/raahat/alerts/${enc(alertId)}/attestations`, { auth: false }),
  raahatAttest: (alertId: string, body: { who: 'officer' | 'satellite' | 'pradhan'; severity?: number; note?: string; report_id?: string }) =>
    request<{ state: string; tx: string | null }>(`/raahat/alerts/${enc(alertId)}/attest`, { method: 'POST', body }),
  raahatHouseholds: (alertId: string) => request<RaahatHousehold[]>(`/raahat/alerts/${enc(alertId)}/households`),
  raahatReceipt: (alertId: string, household: string, upiRef: string) =>
    request<{ state: string; tx: string | null }>('/raahat/receipts', {
      method: 'POST',
      body: { alert_id: alertId, household, upi_ref: upiRef },
    }),
  raahatRelease: (alertId: string, tier: 1 | 2) =>
    request<RaahatRelease & { alert_id: string }>(`/raahat/alerts/${enc(alertId)}/release`, { method: 'POST', body: { tier } }),

};
