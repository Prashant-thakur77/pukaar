import { describe, expect, it } from 'vitest';
import type { Audit } from '../types';
import { actionWords, applyFilters, auditCsv, auditKind, auditLinkForAlert, filterAudit, groupReads, normaliseResource, readFilters, villageOf, writeFilters } from './audit';

const row = (action: string, decision: 'allow' | 'deny' = 'allow', id = action + decision, extra: Partial<Audit> = {}): Audit => ({
  at: '2026-10-09T07:00:00Z',
  id,
  actor: 'officer1',
  role: 'officer',
  action,
  resource: 'app:pukaar',
  decision,
  reason: '',
  ...extra,
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

  it('links alerts by their audit resource, in the console', () => {
    expect(auditLinkForAlert('alr_1')).toBe('/console/audit?q=alert%3Aalr_1&all=1');
    expect(normaliseResource(' alr_01abc ')).toBe('alert:alr_01abc');
    expect(normaliseResource('alert:alr_01abc')).toBe('alert:alr_01abc');
    expect(normaliseResource('app:pukaar')).toBe('app:pukaar');
  });
});

describe('the audit page (spec 4.11)', () => {
  const villageOfAlert = (id: string) => ({ alr_g: 'gohar', alr_t: 'thunag' })[id];
  const rows = [
    row('approve', 'allow', 'a1', { resource: 'alert:alr_g', at: '2026-10-09T07:05:00Z' }),
    row('view_roster', 'allow', 'r1', { actor: 'judge', at: '2026-10-09T07:04:00Z' }),
    row('view_roster', 'allow', 'r2', { actor: 'judge', at: '2026-10-09T07:03:00Z' }),
    row('view_roster', 'allow', 'r3', { actor: 'judge', at: '2026-10-09T07:01:00Z' }),
    row('set_shelter_status', 'allow', 's1', { resource: 'village:thunag' }),
    row('approve', 'deny', 'd1', { actor: 'judge', resource: 'alert:alr_t' }),
    row('view_reports', 'deny', 'd2', { actor: 'pradhan_thunag' }),
  ];

  it('defaults to changes and decisions: allowed reads hidden, denied reads kept', () => {
    const f = readFilters(new URLSearchParams(''));
    const v = applyFilters(rows, f, villageOfAlert);
    expect(v.rows.map((r) => r.id)).toEqual(['a1', 's1', 'd1', 'd2']);
    expect(v.hiddenReads).toBe(3);
  });

  it('filters by type, village and person, and keeps the filters in the URL', () => {
    const f = readFilters(new URLSearchParams('type=alerts&village=thunag&person=judge&all=1'));
    expect(applyFilters(rows, f, villageOfAlert).rows.map((r) => r.id)).toEqual(['d1']);
    expect(writeFilters(f, '2026-10-09')).toEqual({ all: '1', type: 'alerts', village: 'thunag', person: 'judge', date: '2026-10-09' });
    expect(applyFilters(rows, readFilters(new URLSearchParams('type=denied')), villageOfAlert).rows.map((r) => r.id)).toEqual(['d1', 'd2']);
    expect(applyFilters(rows, readFilters(new URLSearchParams('type=field')), villageOfAlert).rows.map((r) => r.id)).toEqual(['s1']);
    // An unknown type in a pasted link is ignored, not obeyed.
    expect(readFilters(new URLSearchParams('type=nope')).kind).toBe('');
  });

  it('folds a run of the same event into one line with its span; an alert decision never folds', () => {
    const lines = groupReads(applyFilters(rows, readFilters(new URLSearchParams('all=1')), villageOfAlert).rows);
    const roster = lines.find((l) => l.row.action === 'view_roster');
    expect(roster).toMatchObject({ count: 3, from: '2026-10-09T07:01:00Z', to: '2026-10-09T07:04:00Z' });
    expect(groupReads([row('approve', 'allow', 'x1'), row('approve', 'allow', 'x2')])).toHaveLength(2);
    expect(groupReads([row('test_siren', 'allow', 's1'), row('test_siren', 'allow', 's2')])).toMatchObject([{ count: 2 }]);
  });

  it('says what happened in words and knows the village', () => {
    expect(actionWords('approve', 'hi')).toBe('चेतावनी मंज़ूर की');
    expect(actionWords('approve', 'en')).toBe('approved an alert');
    expect(actionWords('brand_new', 'en')).toBe('brand new');
    expect(auditKind('view_console')).toBe('reads');
    expect(auditKind('sound_siren')).toBe('devices');
    expect(villageOf({ resource: 'village:gohar' }, villageOfAlert)).toBe('gohar');
    expect(villageOf({ resource: 'alert:alr_t' }, villageOfAlert)).toBe('thunag');
    expect(villageOf({ resource: 'app:pukaar' }, villageOfAlert)).toBeNull();
  });

  it('exports exactly the rows shown as CSV, quoting what needs it', () => {
    const csv = auditCsv([row('approve', 'allow', 'c1', { reason: 'Officers run the console, approve "and" decline' })]);
    expect(csv.split('\n')[0]).toBe('at,actor,role,action,resource,decision,reason');
    expect(csv).toContain('"Officers run the console, approve ""and"" decline"');
  });
});
