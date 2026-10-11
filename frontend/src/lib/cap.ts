import type { Alert } from '../types';

/** The public CAP 1.2 feed (ATOM index) on the API. */
export const capFeedUrl = (apiBase: string) => `${apiBase}/cap/alerts.atom`;

const SENT = ['approved', 'delivering', 'delivered', 'auto_sent_unapproved'];

/**
 * Mirrors backend services/cap.py is_published: only alerts that went out are in the
 * CAP feed. The failsafe broadcasts only critical or already-approved alerts.
 */
export function isCapPublished(a: Pick<Alert, 'status' | 'level' | 'approved'>): boolean {
  if (a.level === 'normal') return false;
  if (SENT.includes(a.status)) return true;
  if (a.status === 'failsafe') return a.level === 'critical' || a.approved;
  if (a.status === 'closed') return a.approved;
  return false;
}

/** The alert's CAP XML, or null when it was never published (pending, declined, expired). */
export function capXmlUrl(a: Pick<Alert, 'id' | 'status' | 'level' | 'approved'>, apiBase: string): string | null {
  return isCapPublished(a) ? `${apiBase}/cap/alerts/${encodeURIComponent(a.id)}.xml` : null;
}
