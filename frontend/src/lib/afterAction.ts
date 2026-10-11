import type { Alert } from '../types';

/** Statuses of an alert the workflow is still working on (backend store/models.py OPEN_ALERT_STATUSES). */
const OPEN = ['drafting', 'pending', 'approved', 'delivering'];

/** The after-action report exists for every alert the workflow has finished with. */
export const hasAfterAction = (a: Pick<Alert, 'status'>): boolean => !OPEN.includes(a.status);

/** GET /alerts/{id}/after-action (officers, or the pradhan of the alert's village). */
export const afterActionPath = (id: string): string => `/alerts/${encodeURIComponent(id)}/after-action`;

/** File name for the downloaded copy: pukaar-after-action-<village>-<YYYY-MM-DD>-<id>.html */
export function afterActionFilename(a: Pick<Alert, 'id' | 'village_id' | 'created_at'>): string {
  const safe = (s: string) => s.replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '');
  const day = /^\d{4}-\d{2}-\d{2}/.test(a.created_at) ? a.created_at.slice(0, 10) : 'undated';
  return `pukaar-after-action-${safe(a.village_id)}-${day}-${safe(a.id)}.html`;
}
