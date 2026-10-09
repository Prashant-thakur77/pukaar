/** Screen state of the villager report page. */
export type Phase =
  | { k: 'compose' }
  | { k: 'sending' }
  | { k: 'queued'; id: number | null }
  | { k: 'done'; code: string; late?: boolean };

/**
 * A report saved offline becomes "done" once the queue has sent it: the
 * queue records (queue id -> tracking code) in the net store when the server
 * accepts it, after an `online` event or a retry.
 */
export function resolvePhase(phase: Phase, flushed: Record<number, string>): Phase {
  if (phase.k !== 'queued' || phase.id == null) return phase;
  const code = flushed[phase.id];
  return code ? { k: 'done', code, late: true } : phase;
}
