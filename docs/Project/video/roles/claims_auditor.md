# claims_auditor.md

Owns factual, compliance, and attribution QC.

## Inputs

- `../DESIGN.md`
- `../claims_guardrail.md`
- `../narration.md`
- `../screen_text.md`
- `../edit/master.srt`
- `../edit/master.es.srt`
- `../edit/preview.mp4`

## Responsibilities

- Classify every spoken line and on-screen text as A/B/C per `claims_guardrail.md`.
- Verify credits for AFP/Wikimedia/generated assets.
- Confirm no metric is invented or stronger than repo evidence.
- Confirm no real person, responder, agency logo, or partner claim appears without approval.

## Outputs

- `../edit/claims_qc.md`
- Corrections to `../handoffs/04_edit_decisions.json` when a line/cut must change.

## Done

- `claims_qc.md` has only class A approved lines.
- Any unresolved metric is marked pending validation, not presented as fact.
- Final render is blocked if any B/C line remains.
