// Pukaar Raahat: the public ledger as a timeline per alert (pure, no chain access).
import type { Lang } from '../store';
import type { RaahatLedgerItem } from '../types';

/** Whole tINR (18 decimals) as rupees with Indian grouping: "63000000000000000000000" -> "63,000". */
export function inr(wei: string | bigint, lang: Lang = 'en'): string {
  return new Intl.NumberFormat(lang === 'hi' ? 'hi-IN' : 'en-IN').format(BigInt(wei) / 10n ** 18n);
}

export type StepState = 'done' | 'waiting' | 'failed';
export type LedgerStep = {
  key: 'anchored' | 'heard' | 'tier1' | 'attested' | 'tier2' | 'receipts';
  state: StepState;
  tx?: string | null;
  acknowledged?: number | null;
  delivered?: number | null;
  households?: number | null;
  totalWei?: string | null;
  attesters?: { who: 'pradhan' | 'officer' | 'satellite'; severity: number | null }[];
  receipts?: number;
};

/** Alert anchored -> heard (मिल गया / delivered) -> tier 1 released -> flood confirmed (2 of 3) -> tier 2 released ->
 * receipts reached households. */
export function timelineSteps(item: RaahatLedgerItem): LedgerStep[] {
  const anchored: StepState = item.anchor_state === 'sent' ? 'done' : item.anchor_state === 'failed' ? 'failed' : 'waiting';
  const heard: StepState = item.outcome_tx ? 'done' : 'waiting';
  const tier = (t: 1 | 2): LedgerStep => {
    const r = item.releases.find((x) => x.tier === t);
    const state: StepState = r?.state === 'sent' ? 'done' : r?.state === 'failed' ? 'failed' : 'waiting';
    return { key: t === 1 ? 'tier1' : 'tier2', state, tx: r?.tx ?? null, households: r?.households ?? null, totalWei: r?.total_wei ?? null };
  };
  const att = item.attestations ?? {};
  const attesters = (['pradhan', 'officer', 'satellite'] as const).map((who) => ({
    who,
    severity: att[who]?.state === 'sent' ? att[who]!.severity : null,
  }));
  const paidTo = Math.max(0, ...item.releases.filter((r) => r.state === 'sent').map((r) => r.households ?? 0));
  const receipts = item.receipts ?? 0;
  return [
    { key: 'anchored', state: anchored, tx: item.anchor_tx },
    { key: 'heard', state: heard, tx: item.outcome_tx, acknowledged: item.acknowledged, delivered: item.delivered },
    tier(1),
    { key: 'attested', state: item.confirmed ? 'done' : 'waiting', attesters },
    tier(2),
    { key: 'receipts', state: paidTo > 0 && receipts >= paidTo ? 'done' : 'waiting', receipts, households: paidTo },
  ];
}

type Total = { wei: bigint; households: number; releases: number };

/** What reached villages, from sent releases only; replays and drills are counted apart, never as live relief. */
export function ledgerTotals(items: RaahatLedgerItem[]): { live: Total; exercise: Total } {
  const out = { live: { wei: 0n, households: 0, releases: 0 }, exercise: { wei: 0n, households: 0, releases: 0 } };
  for (const it of items)
    for (const r of it.releases) {
      if (r.state !== 'sent' || !r.total_wei) continue;
      const t = it.exercise ? out.exercise : out.live;
      t.wei += BigInt(r.total_wei);
      t.households += r.households ?? 0;
      t.releases += 1;
    }
  return out;
}

/** An attester's chip: done only when the chain has it (or its transaction was mined); failed and pending show as such. */
export function attesterState(a: { state: string; on_chain: boolean } | null | undefined): 'none' | 'done' | 'pending' | 'failed' {
  if (!a) return 'none';
  if (a.on_chain || a.state === 'sent') return 'done';
  return a.state === 'failed' ? 'failed' : 'pending';
}
