import { describe, expect, it } from 'vitest';
import { dict } from '../i18n';
import type { RaahatLedger } from '../types';
import { inr, ledgerTotals, timelineSteps } from './ledger';
import fixture from './fixtures/ledger.json';

const ledger = fixture as RaahatLedger;

describe('relief ledger timeline', () => {
  it('a replay with an anchor, its outcome and a tier-1 release', () => {
    const steps = timelineSteps(ledger.items[0]);
    expect(steps.map((s) => [s.key, s.state])).toEqual([
      ['anchored', 'done'],
      ['heard', 'done'],
      ['tier1', 'done'],
      ['attested', 'done'],
      ['tier2', 'waiting'],
      ['receipts', 'waiting'],
    ]);
    expect(steps[3].attesters).toEqual([
      { who: 'pradhan', severity: null },
      { who: 'officer', severity: 2 },
      { who: 'satellite', severity: 3 },
    ]);
    expect(steps[5]).toMatchObject({ receipts: 5, households: 42 });
    expect(steps[0].tx).toBe('0xaaa');
    expect(steps[1]).toMatchObject({ acknowledged: 37, delivered: 42, tx: '0xbbb' });
    expect(steps[2]).toMatchObject({ tx: '0xccc', households: 42, totalWei: '63000000000000000000000' });
  });

  it('receipts are done when every household paid has one', () => {
    const item = { ...ledger.items[0], receipts: 42 };
    expect(timelineSteps(item)[5].state).toBe('done');
  });

  it('an alert still open: heard is pending, nothing released', () => {
    const steps = timelineSteps(ledger.items[1]);
    expect(steps.map((s) => s.state)).toEqual(['done', 'waiting', 'waiting', 'waiting', 'waiting', 'waiting']);
  });

  it('a failed anchor and a failed release say so, never "done"', () => {
    const steps = timelineSteps(ledger.items[2]);
    expect(steps[0].state).toBe('failed');
    expect(steps[2].state).toBe('failed');
    expect(steps[3].state).toBe('waiting');
  });

  it('totals count only sent releases, and live separately from exercises', () => {
    expect(ledgerTotals(ledger.items)).toEqual({
      live: { wei: 0n, households: 0, releases: 0 },
      exercise: { wei: 63000n * 10n ** 18n, households: 42, releases: 1 },
    });
  });

  it('every Raahat string has Hindi and English', () => {
    const keys = Object.keys(dict).filter((k) => k.startsWith('raahat.'));
    expect(keys.length).toBeGreaterThan(30);
    for (const k of keys) {
      const e = dict[k as keyof typeof dict];
      expect(/[ऀ-ॿ]/.test(e.hi), k).toBe(true);
      expect(e.en.trim(), k).not.toBe('');
    }
    for (const step of ['anchored', 'heard', 'tier1', 'attested', 'tier2', 'receipts']) expect(dict[`raahat.step.${step}` as keyof typeof dict]).toBeTruthy();
    for (const code of ['not_anchored', 'rules_not_sealed', 'level_below_rule', 'already_released', 'cooldown', 'no_households',
      'no_agent', 'pool_too_small', 'not_confirmed', 'exercise_not_allowed', 'chain_unreachable', 'raahat_off'])
      expect(dict[`raahat.why.${code}` as keyof typeof dict], code).toBeTruthy();
  });
});

describe('inr', () => {
  it('whole rupees from tINR wei with Indian grouping', () => {
    expect(inr('63000000000000000000000')).toBe('63,000');
    expect(inr(1500n * 10n ** 18n)).toBe('1,500');
    expect(inr('500000000000000000000000')).toBe('5,00,000');
  });
});
