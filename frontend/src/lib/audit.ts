import type { Audit } from '../types';

/** Routine page reads: allowed ones are hidden on /audit unless "Show reads" is on. */
export const ROUTINE_READS = ['view_console', 'read_audit', 'view_reports'] as const;

/** Audit rows name alerts as `alert:<id>`. */
export const alertResource = (alertId: string) => `alert:${alertId}`;
export const auditLinkForAlert = (alertId: string) => `/audit?resource=${encodeURIComponent(alertResource(alertId))}`;

/** A bare alert id typed into the filter box is turned into the audit resource. */
export function normaliseResource(q: string): string {
  const s = q.trim();
  return /^alr_[a-z0-9]+$/i.test(s) ? alertResource(s) : s;
}

export const isRoutineRead = (a: Pick<Audit, 'action'>) => (ROUTINE_READS as readonly string[]).includes(a.action);

export interface AuditView {
  rows: Audit[];
  hiddenReads: number;
  denies: number;
}

/** Hides allowed routine reads (denied reads always stay visible) and counts denies. */
export function filterAudit(rows: Audit[], showReads: boolean): AuditView {
  const visible = showReads ? rows : rows.filter((a) => a.decision === 'deny' || !isRoutineRead(a));
  return { rows: visible, hiddenReads: rows.length - visible.length, denies: rows.filter((a) => a.decision === 'deny').length };
}
