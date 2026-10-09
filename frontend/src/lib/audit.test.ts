import { describe, expect, it } from 'vitest';
import type { Audit } from '../types';
import { auditLinkForAlert, filterAudit, normaliseResource } from './audit';

const row = (action: string, decision: 'allow' | 'deny' = 'allow', id = action + decision): Audit => ({
  at: '2026-10-09T07:00:00Z',
  id,
  actor: 'officer1',
  role: 'officer',
  action,
  resource: 'app:pukaar',
  decision,
  reason: '',
});

describe('audit filter', () => {
  const rows = [row('view_console'), row('read_audit'), row('view_reports'), row('approve'), row('approve', 'deny'), row('view_console', 'deny')];

  it('hides allowed routine reads by default and keeps every deny', () => {
    const v = filterAudit(rows, false);
    expect(v.rows.map((r) => r.id)).toEqual(['approveallow', 'approvedeny', 'view_consoledeny']);
    expect(v.hiddenReads).toBe(3);
    expect(v.denies).toBe(2);
  });

  it('shows everything when reads are on', () => {
    const v = filterAudit(rows, true);
    expect(v.rows).toHaveLength(rows.length);
    expect(v.hiddenReads).toBe(0);
  });

  it('links alerts by their audit resource', () => {
    expect(auditLinkForAlert('alr_1')).toBe('/audit?resource=alert%3Aalr_1');
    expect(normaliseResource(' alr_01abc ')).toBe('alert:alr_01abc');
    expect(normaliseResource('alert:alr_01abc')).toBe('alert:alr_01abc');
    expect(normaliseResource('app:pukaar')).toBe('app:pukaar');
  });
});
