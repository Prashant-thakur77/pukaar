# 06_claims_qc.md

Claims QC handoff template.

## Source Of Truth

- `../claims_guardrail.md`
- `../DESIGN.md`

## Status

- Rough-cut QC: pending.
- Final subtitle QC: pending.
- Final on-screen text QC: pending.

## Required Checks

- [ ] No accuracy percentage.
- [ ] No lead-time claim.
- [ ] No deployed/partner operation claim.
- [ ] No real local validation claim.
- [ ] MVP/public/simulated disclaimer visible in every UI-heavy block.
- [ ] Credits included for AFP/Wikimedia/generated or stock assets.
- [ ] End card says: `MVP today - Public-data evaluation next - Real local data after that`.

## Line Audit

| Source | Text | Class | Action |
| --- | --- | --- | --- |
| narration | Pending final transcript | pending | Generate from actual take |
| screen_text | Pending locked edit | pending | Compare against `screen_text.md` |

## Final Gate

Final render is blocked while any line is class B or class C.
