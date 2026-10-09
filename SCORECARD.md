# SCORECARD.md

Rubric: PLAN.md 3a (0-5 each, 35 total). Every score cites evidence. Scores
come from independent reviewer agents, not from the builder.

| Date | Piece | Works | Safe | AWS depth | Usable | Honest | Demo | Code health | Total | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-09 | Backend + infra, review 1 | 3 | 2 | 4 | 3 | 3 | 4 | 4 | 23 | 95 tests pass; `sam validate --lint` valid; no deployed stack. Blockers: failsafe could broadcast an unapproved warning after a model timeout; Telegram `/start officer_<name>` let anyone take over approval links. 16 more findings. |

| 2026-10-09 | Web app, judge pass 1 (UI rubric) | 3 | 4 | 2 | 4 | 3 | 4 | 3 | 23 | Every DEMO.md step renders; bugs: map render loop, empty per-alert audit links, replay banner said 2025 during the 2023 replay, invalid link shown as "already decided". |

## Judge passes (event criteria, 0-10)

| Date | Idea and impact | Built on AWS | Design and usability | Execution | Demo readiness | Notes |
|---|---|---|---|---|---|---|
| 2026-10-09, pass 2 (local, not deployed) | 8 | 6 | 7.5 | 7 | 7 | Remaining: deploy; slower replay with a finished state; offline report should show its tracking code after sync; hide officer controls from pradhans; one audit row per delivery; align chip copy with DEMO.md. |
| 2026-10-09, pass 1 (local, not deployed) | 8 | 6 | 7 | 6 | 6 | Five changes asked: show AWS in the demo, fix audit links and hide reads, fix the banner year and stale cards, make the fallback read as working with a "why this level" view, fix the map loop and add a local approval-link button. |

| 2026-10-09 | Whole product, judge pass 2 | 3 | 4 | 2 | 4 | 5 | 4 | 4 | 26 | All 16 DEMO.md steps run locally with no console errors; Cedar deny audited; late and invalid links correct; offline queue sends. AWS depth stays 2 until deployed. |

## Loop decisions

- Review 1: Safe below 3 -> fix loop. Fixed 17 of 18 findings in `698c769`
  (all but concurrent village writes, listed as debt). 113 tests pass.

- Judge pass 1: all five changes taken. Backend part: invalid links get
  their own 400 page, `/health` names the workflow engine, a local-only
  route returns the officer's one-tap link for demos. Front-end part: see the
  next commit.

- Judge pass 2: backend part fixed (one deliver audit row per channel,
  `dev_link` as its own audited action, undo clears `verified_by`, default
  replay pace 4 s per data hour); front-end part in the next commit.
  Deploying is the human's step (PROGRESS.md "Needs human").

## Debt

- Concurrent recomputes of one village (sweep and a report at the same
  moment) write the village without a condition; two alerts can result.
  Low likelihood (15-minute sweeps); left with the score above.
- "Works" cannot exceed 3 until the stack is deployed and the PLAN.md
  "Done when" checks run live.
