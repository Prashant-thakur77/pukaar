/**
 * Messaging cost of one village for one monsoon season: an ESTIMATE from list prices, to be replaced
 * with provider quotes and the measured AWS bill. Defaults and sources: the cost model in the pilot
 * research (voice from Plivo's India page, SMS from MSG91, GST at 18%).
 *
 * Each alert event = one voice call to every registered number, a re-call to the share who did not
 * confirm, one Hindi SMS (a Hindi segment holds 70 characters, so an alert is several segments) and
 * Telegram (free). Polly synthesises each alert once; at under ₹1 an event it is left out of the sum.
 */

export interface CostInputs {
  households: number;
  numbersPerHousehold: number;
  eventsPerSeason: number;
  /** 0..1: share of numbers that did not confirm and are called again. */
  recallShare: number;
  /** ₹ per minute of an outbound call. */
  voicePerMin: number;
  /** Minutes billed per call (1-minute pulse). */
  minutesPerCall: number;
  /** ₹ per SMS segment. */
  smsPerSegment: number;
  smsSegments: number;
  /** 0..1 */
  gstRate: number;
  villages: number;
}

export const DEFAULT_COST_INPUTS: CostInputs = {
  households: 150,
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

/** Pure: same inputs, same answer. Amounts are in rupees, unrounded; round only for display. */
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
