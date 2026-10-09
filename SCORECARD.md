# SCORECARD.md

Rubric: PLAN.md 3a (0-5 each, 35 total). Every score cites evidence. Scores
come from independent reviewer agents, not from the builder.

| Date | Piece | Works | Safe | AWS depth | Usable | Honest | Demo | Code health | Total | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-09 | Backend + infra, review 1 | 3 | 2 | 4 | 3 | 3 | 4 | 4 | 23 | 95 tests pass; `sam validate --lint` valid; no deployed stack. Blockers: failsafe could broadcast an unapproved warning after a model timeout; Telegram `/start officer_<name>` let anyone take over approval links. 16 more findings. |

## Loop decisions

- Review 1: Safe below 3 -> fix loop. Fixed 17 of 18 findings in `698c769`
  (all but concurrent village writes, listed as debt). 113 tests pass.

## Debt

- Concurrent recomputes of one village (sweep and a report at the same
  moment) write the village without a condition; two alerts can result.
  Low likelihood (15-minute sweeps); left with the score above.
- "Works" cannot exceed 3 until the stack is deployed and the PLAN.md
  "Done when" checks run live.
