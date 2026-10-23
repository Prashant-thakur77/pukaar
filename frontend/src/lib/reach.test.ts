import { describe, expect, it } from 'vitest';
import { attestable, canRequestSachet, findGroup, groupDecisions, groupPath, sachetClipboard, todayIst, type AlertGroup, type ImportRow, type SachetPackage } from './reach';

describe('grouped approval', () => {
  const villages = [{ alert_id: 'a1' }, { alert_id: 'a2' }, { alert_id: 'a3' }];

  it('approves every village unless it is marked declined', () => {
    expect(groupDecisions(villages, new Set(['a2']))).toEqual([
      { alert_id: 'a1', decision: 'approved' },
      { alert_id: 'a2', decision: 'declined' },
      { alert_id: 'a3', decision: 'approved' },
    ]);
    expect(groupDecisions(villages, new Set()).every((d) => d.decision === 'approved')).toBe(true);
  });

  it('names a group by district, cause and stream, and finds it again', () => {
    const g = { district: 'Mandi', cause: 'rain', stream: 'replay' } as AlertGroup;
    expect(groupPath(g)).toBe('/console/group?d=Mandi&c=rain&s=replay');
    expect(findGroup([g], 'Mandi', 'rain', 'replay')).toBe(g);
    expect(findGroup([g], 'Mandi', 'river', 'replay')).toBeNull();
  });
});

describe('the SACHET request', () => {
  it('is offered on a published Warning or Critical only', () => {
    expect(canRequestSachet({ level: 'critical', status: 'delivered' })).toBe(true);
    expect(canRequestSachet({ level: 'warning', status: 'approved' })).toBe(true);
    expect(canRequestSachet({ level: 'warning', status: 'closed', approved: true })).toBe(true);
    expect(canRequestSachet({ level: 'warning', status: 'closed', approved: false })).toBe(false);
    expect(canRequestSachet({ level: 'watch', status: 'delivered' })).toBe(false);
    expect(canRequestSachet({ level: 'critical', status: 'pending' })).toBe(false);
    expect(canRequestSachet({ level: 'critical', status: 'declined' })).toBe(false);
  });

  it('copies both texts, the steps and the not-sent line', () => {
    const p = {
      text_hi: 'जिला आपदा प्रबंधन मंडी: थुनाग में बाढ़।',
      text_en: 'DDMA Mandi: Flood warning for Thunag.',
      limits: { hi: { pages: 1 }, en: { pages: 2 } },
      radius_km: 5,
      filename: 'alr_1-sachet-request.xml',
      steps_en: ['Call 1070.', 'E-mail the file.'],
      not_sent_en: 'Pukaar has not sent a broadcast.',
    } as unknown as SachetPackage;
    const text = sachetClipboard(p);
    expect(text).toContain('Hindi (cell broadcast, 1 page):\nजिला');
    expect(text).toContain('English (cell broadcast, 2 pages):');
    expect(text).toContain('1. Call 1070.\n2. E-mail the file.');
    expect(text.trim().endsWith('Pukaar has not sent a broadcast.')).toBe(true);
  });
});

describe('the vetted import', () => {
  it('lets only rows that passed every check be attested', () => {
    const rows = [
      { row: 1, status: 'ok' },
      { row: 2, status: 'error' },
      { row: 3, status: 'duplicate' },
      { row: 4, status: 'exists' },
      { row: 5, status: 'ok' },
    ] as ImportRow[];
    expect(attestable(rows)).toEqual([1, 5]);
  });

  it('dates consent in India time', () => {
    expect(todayIst(new Date('2026-10-23T19:00:00Z'))).toBe('2026-10-24');
    expect(todayIst(new Date('2026-10-23T18:00:00Z'))).toBe('2026-10-23');
  });
});
