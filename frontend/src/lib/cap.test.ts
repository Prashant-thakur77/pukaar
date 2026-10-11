import { describe, expect, it } from 'vitest';
import type { Alert } from '../types';
import { capFeedUrl, capXmlUrl, isCapPublished } from './cap';

const a = (status: Alert['status'], level: Alert['level'] = 'warning', approved = false) => ({ id: 'alr_1', status, level, approved });

describe('CAP links', () => {
  it('links only alerts that went out', () => {
    for (const s of ['approved', 'delivering', 'delivered', 'auto_sent_unapproved'] as const) expect(isCapPublished(a(s))).toBe(true);
    for (const s of ['drafting', 'pending', 'declined', 'expired'] as const) expect(isCapPublished(a(s))).toBe(false);
    expect(isCapPublished(a('failsafe', 'critical'))).toBe(true);
    expect(isCapPublished(a('failsafe', 'warning'))).toBe(false);
    expect(isCapPublished(a('closed', 'watch', true))).toBe(true);
  });

  it('builds the API URLs', () => {
    expect(capFeedUrl('https://api.example')).toBe('https://api.example/cap/alerts.atom');
    expect(capXmlUrl(a('delivered'), 'https://api.example')).toBe('https://api.example/cap/alerts/alr_1.xml');
    expect(capXmlUrl(a('pending'), 'https://api.example')).toBeNull();
  });
});
