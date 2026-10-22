import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { translate, type Key } from '../i18n';
import { fmtNumber } from '../lib/format';
import type { Lang } from '../store';
import type { Counters } from '../types';
import { CountUp } from './CountUp';
import { LANDING_COUNTERS } from '../lib/counters';
import { CounterRow } from './CounterRow';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const COUNTERS: Counters = {
  villages_watched: 5,
  alerts_sent: 0,
  phones_acknowledged: 0,
  reports_received: 2,
  drills_delivered: 1,
  replay_alerts_approved: 3,
  forecast_checks_24h: 480,
  gauge_readings_24h: 1234567,
  gauge_readings_24h_simulated: 1234567,
};

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

function render(node: ReactNode) {
  act(() => root.render(node));
}

const tFor = (lang: Lang) => (key: Key, vars?: Record<string, string | number>) => translate(lang, key, vars);

function tiles() {
  return [...host.querySelectorAll('li.counter')].map((li) => ({
    num: li.querySelector('.counter-num')?.textContent ?? '',
    label: li.querySelector('.counter-label')?.textContent ?? '',
    note: li.querySelector('.counter-note')?.textContent ?? null,
  }));
}

describe('CounterRow', () => {
  it('shows a dash for every counter while loading', () => {
    render(<CounterRow counters={null} lang="en" t={tFor('en')} />);
    const row = tiles();
    expect(row).toHaveLength(LANDING_COUNTERS.length);
    expect(row.map((r) => r.num)).toEqual(LANDING_COUNTERS.map(() => '—'));
    expect(host.textContent).not.toContain('None yet');
  });

  it('says "None yet" instead of a bare 0 when no flood alert has gone out', () => {
    render(<CounterRow counters={COUNTERS} lang="en" t={tFor('en')} zeroNote="All 5 villages are at Normal right now." />);
    const sent = tiles()[LANDING_COUNTERS.indexOf('alerts_sent')];
    expect(sent.num).toBe('None yet');
    expect(sent.label).toBe('Flood alerts sent for real (not drills or replays)');
    expect(sent.note).toBe('All 5 villages are at Normal right now.');
    // every other counter still shows its number, even a real 0 elsewhere would
    expect(tiles().filter((r) => r.num === '0')).toEqual([]);
  });

  it('shows the numbers, with labels that say exactly what they count', () => {
    render(<CounterRow counters={{ ...COUNTERS, alerts_sent: 2 }} lang="en" t={tFor('en')} zeroNote="ignored when not zero" />);
    const byKey = Object.fromEntries(LANDING_COUNTERS.map((k, i) => [k, tiles()[i]]));
    expect(byKey.villages_watched.num).toBe('5');
    expect(byKey.alerts_sent).toEqual({ num: '2', label: 'Flood alerts sent for real (not drills or replays)', note: null });
    expect(byKey.forecast_checks_24h).toMatchObject({ num: '480', label: 'Forecast checks, last 24 h (every village, every 15 min)' });
    expect(byKey.drills_delivered).toMatchObject({ num: '1', label: 'Drill alerts delivered to real phones' });
    expect(byKey.replay_alerts_approved.num).toBe('3');
    expect(byKey.reports_received.num).toBe('2');
  });

  it('shows a dash, not a made-up 0, for a counter an older API does not send', () => {
    const old = { villages_watched: 5, alerts_sent: 1, phones_acknowledged: 0, reports_received: 2 } as unknown as Counters;
    render(<CounterRow counters={old} lang="en" t={tFor('en')} />);
    const byKey = Object.fromEntries(LANDING_COUNTERS.map((k, i) => [k, tiles()[i].num]));
    expect(byKey).toEqual({
      villages_watched: '5', forecast_checks_24h: '—', alerts_sent: '1', drills_delivered: '—',
      replay_alerts_approved: '—', reports_received: '2',
    });
  });

  it('labels every counter in Hindi too', () => {
    render(<CounterRow counters={COUNTERS} lang="hi" t={tFor('hi')} zeroNote={translate('hi', 'landing.clear', { n: 5 })} />);
    const sent = tiles()[LANDING_COUNTERS.indexOf('alerts_sent')];
    expect(sent.num).toBe('अभी तक कोई नहीं');
    expect(sent.note).toBe('अभी सभी 5 गाँव सामान्य हैं।');
    for (const r of tiles()) expect(r.label).toMatch(/[ऀ-ॿ]/);
  });
});

describe('Hindi number formatting', () => {
  it('keeps Latin digits with Indian lakh grouping, the same as English (India)', () => {
    expect(fmtNumber(1234567, 'hi')).toBe('12,34,567');
    expect(fmtNumber(1234567, 'en')).toBe('12,34,567');
    expect(fmtNumber(480, 'hi')).toBe('480');
    expect(fmtNumber(1234567, 'hi')).not.toMatch(/[०-९]/);
    expect(fmtNumber(null, 'hi')).toBe('—');
  });

  it('renders Hindi counters with the same digits', () => {
    render(<CountUp value={1234567} lang="hi" />);
    expect(host.textContent).toBe('12,34,567');
  });
});

describe('CountUp', () => {
  it('shows the value at once, as plain text: live numbers never count up', () => {
    render(<CountUp value={1234} lang="en" className="counter-num" />);
    const el = host.querySelector('.countup') as HTMLElement;
    expect(el.textContent).toBe('1,234');
    expect(el.classList.contains('counter-num')).toBe(true);
    expect(el.querySelector('[aria-hidden="true"]')).toBeNull();
  });

  it('shows a dash for a missing value', () => {
    render(<CountUp value={null} lang="en" />);
    expect(host.textContent).toBe('—');
  });
});
