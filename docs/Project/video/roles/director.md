# director.md

Owns the whole video pipeline and final submission readiness.

## Inputs

- `../DESIGN.md`
- `../timeline.md`
- `../shot_list.md`
- `../edit/edl.json`
- `../claims_guardrail.md`

## Responsibilities

- Keep the edit on the 3:00 structure.
- Decide when a missing asset uses a fallback.
- Coordinate Persona A/B/C for demo, metrics, screencasts, and filming.
- Block any claim that violates `claims_guardrail.md`.
- Approve `preview.mp4` before final export.

## Outputs

- `../handoffs/01_script.md`
- `../handoffs/02_shot_plan.md`
- Final sign-off notes in `../edit/claims_qc.md`

## Done

- Every block has a primary asset or explicit fallback.
- All credits and disclaimers are represented in the edit.
- Submission checklist (assets present, claims cleared, credits attached) is complete or has an honest blocker note.
