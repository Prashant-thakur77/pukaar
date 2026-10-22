import { describe, expect, it } from 'vitest';
import { DEFAULT_COST_INPUTS, estimatePilotCost, fmtRupees, fmtRupeesShort } from './pilotCost';

describe('estimatePilotCost', () => {
  it('reproduces the cost model with its defaults (150 households, 15 events)', () => {
    const e = estimatePilotCost(DEFAULT_COST_INPUTS);
    expect(e.numbers).toBe(225);
    expect(e.recalls).toBe(90);
    const line = (k: string) => e.lines.find((l) => l.key === k)!;
    expect(line('voice').perEvent).toBeCloseTo(85.5, 6);
    expect(line('recall').perEvent).toBeCloseTo(34.2, 6);
    expect(line('sms').perEvent).toBeCloseTo(168.75, 6);
    expect(line('telegram').perEvent).toBe(0);
    expect(line('gst').perEvent).toBeCloseTo(0.18 * 288.45, 6);
    expect(e.perEvent).toBeCloseTo(340.371, 3); // "about ₹340"
    expect(e.perSeason).toBeCloseTo(5105.565, 3); // "about ₹5,100 per village"
    expect(line('voice').perSeason).toBeCloseTo(1282.5, 6);
    expect(e.perHousehold).toBeCloseTo(34.04, 2);
    expect(e.perNumber).toBeCloseTo(22.69, 2);
    expect(e.forVillages).toBeCloseTo(5105565, 0); // 1,000 villages: about ₹51 lakh
  });

  it('lines add up to the per-event and per-season totals', () => {
    const e = estimatePilotCost({ ...DEFAULT_COST_INPUTS, households: 412, recallShare: 0.25, smsSegments: 2 });
    const sumEv = e.lines.reduce((s, l) => s + l.perEvent, 0);
    const sumSe = e.lines.reduce((s, l) => s + l.perSeason, 0);
    expect(sumEv).toBeCloseTo(e.perEvent, 9);
    expect(sumSe).toBeCloseTo(e.perSeason, 9);
  });

  it('scales linearly with households, events and villages', () => {
    const base = estimatePilotCost(DEFAULT_COST_INPUTS);
    expect(estimatePilotCost({ ...DEFAULT_COST_INPUTS, households: 300 }).perSeason).toBeCloseTo(base.perSeason * 2, 6);
    expect(estimatePilotCost({ ...DEFAULT_COST_INPUTS, eventsPerSeason: 30 }).perSeason).toBeCloseTo(base.perSeason * 2, 6);
    expect(estimatePilotCost({ ...DEFAULT_COST_INPUTS, villages: 10 }).forVillages).toBeCloseTo(base.perSeason * 10, 6);
  });

  it('never goes negative or NaN on bad input, and holds shares to 0..1', () => {
    const e = estimatePilotCost({
      ...DEFAULT_COST_INPUTS,
      households: -5,
      recallShare: 3,
      gstRate: Number.NaN,
      villages: Number.POSITIVE_INFINITY,
    });
    expect(e.inputs.households).toBe(0);
    expect(e.inputs.recallShare).toBe(1);
    expect(e.inputs.gstRate).toBe(0);
    expect(e.inputs.villages).toBe(0);
    expect(e.perSeason).toBe(0);
    expect(e.perHousehold).toBe(0);
    expect(e.perNumber).toBe(0);
  });

  it('free channels cost nothing: no paid calls and no SMS leaves zero', () => {
    const e = estimatePilotCost({ ...DEFAULT_COST_INPUTS, voicePerMin: 0, smsPerSegment: 0 });
    expect(e.perEvent).toBe(0);
  });
});

describe('rupee formatting', () => {
  it('uses Indian grouping, paise only for small amounts', () => {
    expect(fmtRupees(5105.565)).toBe('₹5,106');
    expect(fmtRupees(123456.7)).toBe('₹1,23,457');
    expect(fmtRupees(34.04)).toBe('₹34.04');
    expect(fmtRupees(0)).toBe('₹0');
  });
  it('reads large sums in lakh and crore', () => {
    expect(fmtRupeesShort(5105565, 'en')).toBe('₹51.1 lakh');
    expect(fmtRupeesShort(5105565, 'hi')).toBe('₹51.1 लाख');
    expect(fmtRupeesShort(25e7, 'en')).toBe('₹25 crore');
    expect(fmtRupeesShort(5106, 'en')).toBe('₹5,106');
  });
});
