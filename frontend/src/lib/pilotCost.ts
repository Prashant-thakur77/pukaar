/**
 * What Pukaar costs, and what it may save: ESTIMATES from list prices and stated assumptions, to be replaced
 * with provider quotes, the measured AWS bill and a monsoon of measured reach. docs/BUSINESS_MODEL.md gives every
 * source and formula; the numbers below are the same ones, so the page and the document cannot drift apart.
 *
 * 1. Messaging for one village and one monsoon (estimatePilotCost). Each alert event = one voice call to every
 *    registered number, a re-call to the share who did not confirm, one Hindi SMS (a Hindi segment holds 70
 *    characters, so an alert is several segments) and Telegram (free). Polly synthesises each alert once; at
 *    under ₹1 an event it is left out of the sum. Voice from Plivo's India page, SMS at the top of MSG91's range,
 *    GST at 18%.
 * 2. Everything else at three scales (scaleCost): fixed telecom, cloud, the platform and support fee, drills,
 *    field staff and the alarm layer (sirens, gauges, rain nodes), annualised.
 * 3. What it may avert (averted) and the break-even in lives. The lives averted are assumptions, not findings.
 */

export interface CostInputs {
  households: number;
  numbersPerHousehold: number;
  eventsPerSeason: number;
  /** 0..1: share of numbers that did not confirm and are called again. */
  recallShare: number;
  /** ₹ per minute of an outbound call. */
  voicePerMin: number;
  /** Minutes billed per call (1-minute pulse; 2 if the alert and the "press 1" prompt run past 60 s). */
  minutesPerCall: number;
  /** ₹ per SMS segment. */
  smsPerSegment: number;
  smsSegments: number;
  /** 0..1 */
  gstRate: number;
  villages: number;
}

/**
 * Mandi district, Census 2011: 2,03,747 rural households in 2,850 villages, about 71.5 a village. The default
 * village is an average Mandi village, not one of the five pilot villages (market towns, larger than average).
 */
export const MANDI_HOUSEHOLDS_PER_VILLAGE = 71;

export const DEFAULT_COST_INPUTS: CostInputs = {
  households: MANDI_HOUSEHOLDS_PER_VILLAGE,
  numbersPerHousehold: 1.5,
  eventsPerSeason: 15,
  recallShare: 0.4,
  voicePerMin: 0.38,
  minutesPerCall: 1,
  smsPerSegment: 0.25,
  smsSegments: 3,
  gstRate: 0.18,
  villages: 1000,
};

export type CostLineKey = 'voice' | 'recall' | 'sms' | 'telegram' | 'gst';

export interface CostLine {
  key: CostLineKey;
  perEvent: number;
  perSeason: number;
}

export interface CostEstimate {
  /** The inputs after cleaning (negative or non-numbers become 0, shares are held to 0..1). */
  inputs: CostInputs;
  numbers: number;
  recalls: number;
  lines: CostLine[];
  perEvent: number;
  perSeason: number;
  perHousehold: number;
  perNumber: number;
  forVillages: number;
}

const num = (x: number) => (Number.isFinite(x) && x > 0 ? x : 0);
const share = (x: number) => Math.min(1, num(x));

export function cleanInputs(raw: CostInputs): CostInputs {
  return {
    households: num(raw.households),
    numbersPerHousehold: num(raw.numbersPerHousehold),
    eventsPerSeason: num(raw.eventsPerSeason),
    recallShare: share(raw.recallShare),
    voicePerMin: num(raw.voicePerMin),
    minutesPerCall: num(raw.minutesPerCall),
    smsPerSegment: num(raw.smsPerSegment),
    smsSegments: num(raw.smsSegments),
    gstRate: share(raw.gstRate),
    villages: num(raw.villages),
  };
}

/** Pure: same inputs, same answer. Amounts are in rupees, unrounded; round only for display. Messaging only. */
export function estimatePilotCost(raw: CostInputs): CostEstimate {
  const i = cleanInputs(raw);
  const numbers = i.households * i.numbersPerHousehold;
  const recalls = numbers * i.recallShare;
  const voice = numbers * i.minutesPerCall * i.voicePerMin;
  const recall = recalls * i.minutesPerCall * i.voicePerMin;
  const sms = numbers * i.smsSegments * i.smsPerSegment;
  const gst = (voice + recall + sms) * i.gstRate;
  const perEvent = voice + recall + sms + gst;
  const perSeason = perEvent * i.eventsPerSeason;
  const line = (key: CostLineKey, perEv: number): CostLine => ({ key, perEvent: perEv, perSeason: perEv * i.eventsPerSeason });
  return {
    inputs: i,
    numbers,
    recalls,
    lines: [line('voice', voice), line('recall', recall), line('sms', sms), line('telegram', 0), line('gst', gst)],
    perEvent,
    perSeason,
    perHousehold: i.households > 0 ? perSeason / i.households : 0,
    perNumber: numbers > 0 ? perSeason / numbers : 0,
    forVillages: perSeason * i.villages,
  };
}

/**
 * The billing risk past 60 seconds: if the spoken alert plus the "press 1" prompt runs over a minute, every
 * answered call bills two minutes on a 1-minute pulse. What that adds to a season, and as a share of it.
 */
export function longCallRisk(raw: CostInputs): { perSeason: number; extra: number; share: number } {
  const base = estimatePilotCost(raw);
  const minutes = Math.max(2, base.inputs.minutesPerCall);
  const long = estimatePilotCost({ ...base.inputs, minutesPerCall: minutes });
  const extra = long.perSeason - base.perSeason;
  return { perSeason: long.perSeason, extra, share: base.perSeason > 0 ? extra / base.perSeason : 0 };
}

/** Fixed telecom costs per sending deployment (not per village). Plivo number rental; DLT fees per entity and header. */
export const FIXED_TELECOM = {
  /** ₹ a month for one Indian number (Plivo, read 23 Oct 2026). */
  numberRentalPerMonth: 200,
  /** ₹ once per DLT principal entity. */
  dltOneOff: 5900,
  /** ₹ a year per registered SMS header. */
  dltPerHeaderYear: 590,
} as const;

/** One deployment's recurring fixed telecom cost a year: number rental and one DLT header (the one-off fee is not in it). */
export function fixedTelecomPerYear(headers = 1): number {
  return FIXED_TELECOM.numberRentalPerMonth * 12 + FIXED_TELECOM.dltPerHeaderYear * num(headers);
}

/* ------------------------------------------------------------------ all-in, at three scales ------------------------------------------------------------------ */

/** Unit costs of the all-in model. Each is an estimate unless docs/BUSINESS_MODEL.md cites it. */
export const UNIT_COSTS = {
  /** The supplier's platform and support fee, ₹ per village per year (proposed price). */
  platformPerVillage: 12000,
  /** One labelled drill a year and its materials, ₹ per village. */
  drillsPerVillage: 3000,
  /** Field coordinator, ₹ per full-time year (₹30,000 a month). */
  coordinatorPerYear: 360000,
  /** Technician including travel, ₹ per full-time year. */
  technicianPerYear: 450000,
  /** Alarm layer per village (siren node, gauge, rain node, pradhan box, relay share): docs/hardware/ALARM.md, untested. */
  alarmCapex: 163000,
  /** Its upkeep, ₹ a year (battery reserve, SIMs, visits, cloud). */
  alarmOpex: 30000,
  /** Annualised over this design life at this rate. */
  alarmLifeYears: 7,
  alarmRate: 0.08,
} as const;

export interface ScaleInputs {
  villages: number;
  /** Registered phone numbers across all villages. */
  numbers: number;
  /** Villages with the alarm layer (all of a pilot's, one in five at district and state scale). */
  alarmVillages: number;
  coordinatorsFte: number;
  techniciansFte: number;
  /** AWS ap-south-1, ₹ a year, rounded up from list prices. */
  cloudPerYear: number;
}

export type ScaleKey = 'pilot' | 'district' | 'state';

export const SCALES: Record<ScaleKey, ScaleInputs> = {
  // 5 villages, about 3,400 people; the pilot villages are larger than Mandi's average.
  pilot: { villages: 5, numbers: 1125, alarmVillages: 5, coordinatorsFte: 0.5, techniciansFte: 0.25, cloudPerYear: 60000 },
  // 300 at-risk villages, 3 lakh people: 3,00,000 ÷ 4.56 people a household × 1.5 numbers ≈ 98,600 numbers.
  district: { villages: 300, numbers: 98600, alarmVillages: 60, coordinatorsFte: 2, techniciansFte: 1, cloudPerYear: 150000 },
  // 1,000 panchayat-sized units, 10 lakh numbers, one coordinator per district.
  state: { villages: 1000, numbers: 1000000, alarmVillages: 200, coordinatorsFte: 12, techniciansFte: 3, cloudPerYear: 600000 },
};

/** Capital recovery factor: r(1+r)^n / ((1+r)^n − 1). */
export function capitalRecoveryFactor(rate: number, years: number): number {
  if (years <= 0) return 0;
  if (rate <= 0) return 1 / years;
  const g = (1 + rate) ** years;
  return (rate * g) / (g - 1);
}

/** One village's alarm layer a year: the capex annualised plus upkeep (about ₹61,300). */
export function alarmPerVillageYear(): number {
  return UNIT_COSTS.alarmCapex * capitalRecoveryFactor(UNIT_COSTS.alarmRate, UNIT_COSTS.alarmLifeYears) + UNIT_COSTS.alarmOpex;
}

/** Messaging per registered number per monsoon at the default prices (₹22.69); it does not depend on village size. */
export const MESSAGING_PER_NUMBER = estimatePilotCost(DEFAULT_COST_INPUTS).perNumber;

export type ScaleLineKey = 'messaging' | 'telecom' | 'cloud' | 'platform' | 'drills' | 'coordinators' | 'technicians' | 'alarm';

export interface ScaleCost {
  inputs: ScaleInputs;
  lines: { key: ScaleLineKey; amount: number }[];
  total: number;
  perVillage: number;
  /** The phone loop alone: the total without the alarm layer. */
  phoneOnly: number;
  /** One-time alarm hardware, inside the total through the annualised line. */
  capex: number;
}

/** All-in cost a year at one scale. Pure. */
export function scaleCost(s: ScaleInputs, messagingPerNumber = MESSAGING_PER_NUMBER): ScaleCost {
  const lines: ScaleCost['lines'] = [
    { key: 'messaging', amount: num(s.numbers) * num(messagingPerNumber) },
    { key: 'telecom', amount: fixedTelecomPerYear() },
    { key: 'cloud', amount: num(s.cloudPerYear) },
    { key: 'platform', amount: num(s.villages) * UNIT_COSTS.platformPerVillage },
    { key: 'drills', amount: num(s.villages) * UNIT_COSTS.drillsPerVillage },
    { key: 'coordinators', amount: num(s.coordinatorsFte) * UNIT_COSTS.coordinatorPerYear },
    { key: 'technicians', amount: num(s.techniciansFte) * UNIT_COSTS.technicianPerYear },
    { key: 'alarm', amount: num(s.alarmVillages) * alarmPerVillageYear() },
  ];
  const total = lines.reduce((t, l) => t + l.amount, 0);
  const alarm = lines.find((l) => l.key === 'alarm')!.amount;
  return {
    inputs: s,
    lines,
    total,
    perVillage: s.villages > 0 ? total / s.villages : 0,
    phoneOnly: total - alarm,
    capex: num(s.alarmVillages) * UNIT_COSTS.alarmCapex,
  };
}

/* ------------------------------------------------------------------ what it may avert ------------------------------------------------------------------ */

/** Value of a statistical life, India: ₹1.5 crore (lowest Indian estimate found) and ₹4.47 crore (ISEC WP 407). */
export const VSL = { low: 1.5e7, high: 4.47e7 } as const;
/** A large animal (buffalo or cow), SDRF-norm value as reported; to be confirmed against the MHA letter. */
export const ANIMAL_VALUE = 37500;

export interface BenefitCase {
  /** ASSUMED, not measured: no flash-flood warning study for the Indian Himalaya exists. */
  livesPerYear: number;
  vsl: number;
  animalsPerYear: number;
  exposedHouseholds: number;
  /** 0..1: share of exposed households warned in time to save goods. */
  shareSaving: number;
  /** ₹ of movable goods saved per such household (27–55% of Nepal Karnali's ₹73,000, for minutes of warning, not hours). */
  goodsPerHousehold: number;
}

export type CaseKey = 'low' | 'central' | 'high';

/** A 300-village district a year. */
export const DISTRICT_CASES: Record<CaseKey, BenefitCase> = {
  low: { livesPerYear: 0.5, vsl: VSL.low, animalsPerYear: 25, exposedHouseholds: 500, shareSaving: 0.2, goodsPerHousehold: 20000 },
  central: { livesPerYear: 2, vsl: VSL.low, animalsPerYear: 50, exposedHouseholds: 1000, shareSaving: 0.3, goodsPerHousehold: 25000 },
  high: { livesPerYear: 5, vsl: VSL.high, animalsPerYear: 150, exposedHouseholds: 2000, shareSaving: 0.5, goodsPerHousehold: 40000 },
};

/** ₹ a year averted: lives × VSL + animals × ₹37,500 + exposed households × share warned in time × goods saved. */
export function averted(c: BenefitCase): number {
  return num(c.livesPerYear) * num(c.vsl) + num(c.animalsPerYear) * ANIMAL_VALUE + num(c.exposedHouseholds) * share(c.shareSaving) * num(c.goodsPerHousehold);
}

/** The same without lives: what the case is worth on livestock and goods alone. */
export function avertedWithoutLives(c: BenefitCase): number {
  return averted({ ...c, livesPerYear: 0 });
}

/** Benefit-cost ratio: averted ÷ cost. */
export function benefitCostRatio(c: BenefitCase, costPerYear: number): number {
  return costPerYear > 0 ? averted(c) / costPerYear : 0;
}

/** Lives a year that pay for the cost on their own, and the months between them (district: about 0.78 and 15). */
export function breakEven(costPerYear: number, vsl: number = VSL.low): { livesPerYear: number; monthsPerLife: number } {
  const livesPerYear = vsl > 0 ? num(costPerYear) / vsl : 0;
  return { livesPerYear, monthsPerLife: livesPerYear > 0 ? 12 / livesPerYear : 0 };
}

/* ------------------------------------------------------------------ display ------------------------------------------------------------------ */

/** Rupees for display: whole rupees from ₹100 up (and ₹0), paise below; Indian grouping (1,23,456) in both languages. */
export function fmtRupees(x: number): string {
  const digits = Math.abs(x) >= 100 || x === 0 ? 0 : 2;
  return `₹${x.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

/** Large sums in lakh and crore, the way an Indian budget reads them. */
export function fmtRupeesShort(x: number, lang: 'hi' | 'en'): string {
  if (x >= 1e7) return `₹${(x / 1e7).toLocaleString('en-IN', { maximumFractionDigits: 2 })} ${lang === 'hi' ? 'करोड़' : 'crore'}`;
  if (x >= 1e5) return `₹${(x / 1e5).toLocaleString('en-IN', { maximumFractionDigits: 1 })} ${lang === 'hi' ? 'लाख' : 'lakh'}`;
  return fmtRupees(x);
}

/** An estimate rounded for a headline: ₹39,129 → ₹39,100. */
export function fmtRupeesAbout(x: number, step = 100): string {
  return fmtRupees(Math.round(x / step) * step);
}
