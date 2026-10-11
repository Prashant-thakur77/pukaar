import { describe, expect, it } from 'vitest';
import { afterActionFilename, afterActionPath, hasAfterAction } from './afterAction';

describe('after-action report', () => {
  it('is offered once the workflow has finished with the alert', () => {
    for (const s of ['delivered', 'declined', 'expired', 'auto_sent_unapproved', 'failsafe', 'closed'] as const)
      expect(hasAfterAction({ status: s }), s).toBe(true);
    for (const s of ['drafting', 'pending', 'approved', 'delivering'] as const) expect(hasAfterAction({ status: s }), s).toBe(false);
  });

  it('builds the route and a safe file name', () => {
    expect(afterActionPath('alr_1/x')).toBe('/alerts/alr_1%2Fx/after-action');
    expect(afterActionFilename({ id: 'alr_01ab', village_id: 'thunag', created_at: '2026-07-01T02:00:00Z' })).toBe(
      'pukaar-after-action-thunag-2026-07-01-alr_01ab.html',
    );
    expect(afterActionFilename({ id: '../x', village_id: 'a b', created_at: '' })).toBe('pukaar-after-action-a-b-undated-x.html');
  });
});
