import { describe, expect, it } from 'vitest';
import {
  DEFAULT_COST_INPUTS,
  DISTRICT_CASES,
  MANDI_HOUSEHOLDS_PER_VILLAGE,
  MESSAGING_PER_NUMBER,
  SCALES,
  alarmPerVillageYear,
  averted,
  avertedWithoutLives,
  benefitCostRatio,
  breakEven,
  capitalRecoveryFactor,
  estimatePilotCost,
  fixedTelecomPerYear,
  fmtRupees,
  fmtRupeesAbout,
  fmtRupeesShort,
  longCallRisk,
  scaleCost,
} from './pilotCost';

const at150 = { ...DEFAULT_COST_INPUTS, households: 150 };

describe('estimatePilotCost (messaging only)', () => {
  it('reproduces the cost model at 150 households, 15 events', () => {
    const e = estimatePilotCost(at150);
    expect(e.numbers).toBe(225);
    expect(e.recalls).toBe(90);
    const line = (k: string) => e.lines.find((l) => l.key === k)!;
    expect(line('voice').perEvent).toBeCloseTo(85.5, 6);
    expect(line('recall').perEvent).toBeCloseTo(34.2, 6);
    expect(line('sms').perEvent).toBeCloseTo(168.75, 6);
    expect(line('telegram').perEvent).toBe(0);
    expect(line('gst').perEvent).toBeCloseTo(0.18 * 288.45, 6);
    expect(e.perEvent).toBeCloseTo(340.371, 3);
    expect(e.perSeason).toBeCloseTo(5105.565, 3); // the old "about ₹5,100 per village", at twice Mandi's average village
    expect(e.perHousehold).toBeCloseTo(34.04, 2);
    expect(e.perNumber).toBeCloseTo(22.69, 2);
  });

  it('defaults to an average Mandi village (Census 2011: about 71 households)', () => {
    expect(MANDI_HOUSEHOLDS_PER_VILLAGE).toBe(71);
    const e = estimatePilotCost(DEFAULT_COST_INPUTS);
    expect(e.numbers).toBeCloseTo(106.5, 6);
    expect(e.perSeason).toBeCloseTo(106.5 * 22.6914, 1); // about ₹2,417
    expect(e.perNumber).toBeCloseTo(22.69, 2); // the unit does not depend on village size
    expect(e.forVillages).toBeCloseTo(e.perSeason * 1000, 6);
    expect(MESSAGING_PER_NUMBER).toBeCloseTo(22.69, 2);
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
    expect(estimatePilotCost({ ...DEFAULT_COST_INPUTS, households: 142 }).perSeason).toBeCloseTo(base.perSeason * 2, 6);
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

describe('the cost lines the sum leaves out', () => {
  it('a call past 60 s bills two minutes: the voice and re-call lines double', () => {
    const base = estimatePilotCost(DEFAULT_COST_INPUTS);
    const r = longCallRisk(DEFAULT_COST_INPUTS);
    const voice = base.lines.filter((l) => l.key === 'voice' || l.key === 'recall').reduce((s, l) => s + l.perSeason, 0);
    expect(r.extra).toBeCloseTo(voice * 1.18, 6);
    expect(r.share).toBeCloseTo(119.7 / 288.45, 4); // about 41% more at the defaults
    expect(longCallRisk({ ...DEFAULT_COST_INPUTS, voicePerMin: 0 }).extra).toBe(0);
  });

  it('fixed telecom: number rental and a DLT header a year', () => {
    expect(fixedTelecomPerYear()).toBe(200 * 12 + 590);
    expect(fixedTelecomPerYear(3)).toBe(2400 + 3 * 590);
  });
});

describe('all-in cost at three scales', () => {
  it('annualises the alarm layer at 7 years and 8%', () => {
    expect(capitalRecoveryFactor(0.08, 7)).toBeCloseTo(0.19207, 5);
    expect(capitalRecoveryFactor(0, 4)).toBe(0.25);
    expect(alarmPerVillageYear()).toBeCloseTo(61308, 0);
  });

  it('reproduces the research table: ₹7.6 lakh, ₹1.17 crore, ₹5.62 crore a year', () => {
    const pilot = scaleCost(SCALES.pilot);
    const district = scaleCost(SCALES.district);
    const state = scaleCost(SCALES.state);
    expect(pilot.total / 1e5).toBeCloseTo(7.6, 1);
    expect(pilot.perVillage).toBeCloseTo(152500, -3);
    expect(district.total / 1e7).toBeCloseTo(1.17, 2);
    expect(Math.round(district.perVillage / 100) * 100).toBe(39100);
    expect(state.total / 1e7).toBeCloseTo(5.62, 2);
    expect(district.capex).toBe(60 * 163000);
    expect(district.phoneOnly).toBeCloseTo(district.total - 60 * alarmPerVillageYear(), 6);
    const sum = district.lines.reduce((s, l) => s + l.amount, 0);
    expect(sum).toBeCloseTo(district.total, 6);
  });
});

describe('what a district may avert', () => {
  const cost = scaleCost(SCALES.district).total;

  it('low, central and high cases: about 0.9, 3.4 and 23', () => {
    expect(averted(DISTRICT_CASES.low) / 1e7).toBeCloseTo(1.04, 2);
    expect(averted(DISTRICT_CASES.central) / 1e7).toBeCloseTo(3.94, 2);
    expect(averted(DISTRICT_CASES.high) / 1e7).toBeCloseTo(26.9, 1);
    expect(benefitCostRatio(DISTRICT_CASES.low, cost)).toBeCloseTo(0.9, 1);
    expect(benefitCostRatio(DISTRICT_CASES.central, cost)).toBeCloseTo(3.4, 1);
    expect(Math.round(benefitCostRatio(DISTRICT_CASES.high, cost))).toBe(23);
  });

  it('the case rests on lives: without them the central case is under 1', () => {
    expect(avertedWithoutLives(DISTRICT_CASES.central) / cost).toBeLessThan(1);
  });

  it('breaks even at one life about every 15 months', () => {
    const b = breakEven(cost);
    expect(b.livesPerYear).toBeCloseTo(0.78, 2);
    expect(Math.round(b.monthsPerLife)).toBe(15);
    expect(breakEven(0).monthsPerLife).toBe(0);
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
  it('rounds a headline estimate', () => {
    expect(fmtRupeesAbout(39129)).toBe('₹39,100');
  });
});
