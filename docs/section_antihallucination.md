# Anti-hallucination defense

How Pukaar prevents Pukaar AI from inventing facts that would
trigger a false flood alert. Companion document for `docs/writeup.md`.
Source of truth for claim discipline: `docs/Project/video/claims_guardrail.md`.

## 1. Concrete risk

In this domain a hallucination is not a stylistic flaw; it is an operational
incident. A false positive escalated to Defensa Civil consumes scarce
resources, erodes trust, and trains responders to ignore the next alert. A
false negative (model confidently labels a rising waterline as "stable")
means people are not warned. Both failure modes are unacceptable, so the
system is built so that no single Pukaar AI output can, by itself, fire a
public alert.

## 2. Layered defense

### Layer 1 — Evidence curation before the LLM

The node never sends a raw video stream to Pukaar AI. The
`MultimodalEvidenceBuilder`
(`backend/src/Pukaar/services/pukaar_assessment.py`) extracts a
small set of curated, optimized frames via ffmpeg, bounded by
`pukaar_multimodal_max_frames` and `image_max_side`. Pukaar AI reasons on a
deterministic, reproducible bundle that is persisted as a JSON manifest
(`persist_json_artifact("pukaar-assessment")`) so any verdict can be
re-audited frame by frame.
Honest note: this build is multimodal-only; we do not run an OpenCV
ground-truth check before the LLM. That hardening is `[TODO]` and listed
as a limitation in section 6.

### Layer 2 — Pukaar AI on the evidence pack, not on the stream

Pukaar AI (E2B via local Ollama, `pukaar-model:2b`) only ever sees the
`TemporalEvidencePack`. Thinking is explicitly disabled
(`"think": False` in `adapters/llm.py`) so the model returns its answer in
`message.content` instead of a free-form `thinking` channel that the rest
of the pipeline cannot parse.

### Layer 3 — Structured output, not free text

Free text cannot trigger actions. Two enforcement paths:

- Volunteer report parsing (`OpenAICompatibleLLM.structure_observation`)
  pins a JSON schema with closed enums (`water_level_category`,
  `trend`, `road_status`, `bridge_status`, `urgency`) and uses Ollama's
  native `"format": "json"` mode. Output that does not parse is discarded
  via `_extract_json`, and the pipeline degrades to the rule-based
  `_fallback_parse`.
- Visual assessment (`Pukaar AIAssessmentRunner.assess`) is required to
  return a typed `AssessmentVerdict`. If the runner returns `None` or
  invalid fields, `PukaarAssessmentEngine._fallback_verdict` emits a
  conservative `yellow` "under manual review" verdict instead of
  trusting the malformed answer.

### Layer 4 — Deterministic backend fusion

A Pukaar AI verdict is an input, not a decision. `decision_engine.py` fuses
node, volunteer and hydromet evidence using temporal decay
(`temporal_weight`, `STALE_DECAY_FLOOR=0.45`) and fixed score thresholds
(`level_from_score`: 0.40 / 0.62 / 0.82). Critical escalations require
multiple corroborating sources (`supporting_sources`), and every
`FusedAlert` carries a deterministic `decision_trace` listing the rules
that fired, alongside Pukaar AI's `reasoning_chain` (see
`docs/Project/thinking-mode.md`). The rule trace exists precisely so
the LLM summary can be cross-checked.

### Layer 5 — Human-in-the-loop for public alerts

No automated path emits a SINAGIR public alert. The on-device siren and
SINAGIR-tagged package (`docs/Project/sinagir-mapping.md`) are
designed for Defensa Civil review; the regulatory and process
boundaries live in `docs/compliance_argentina.md`.

## 3. Claim discipline (A/B/C)

The video, README and any judge-facing copy are bound to
`docs/Project/video/claims_guardrail.md`:

- Class A — architectural and behavioral claims verifiable in code today
  (offline-first, schema-tagged for SINAGIR, reasoning summary in
  Spanish, queue-and-sync).
- Class B — any percentage, lead-time, or comparison claim. Forbidden
  until a public-dataset evaluation is recorded.
- Class C — any claim of real deployment, real victims saved, or named
  partner. Forbidden until real local field data exists.

The QC checklist (section E of that file) gates every render.

## 4. Thinking mode

`reasoning.py` produces the Spanish `reasoning_summary` /
`reasoning_chain` shown to operators. Green alerts skip the LLM
(`reasoning_model: rule-skip-green`, 0 ms cost). When Ollama is
unreachable, a deterministic `rule-fallback` summary is emitted so
alerting never blocks on model availability. The chain is a coarse
surrogate over Pukaar AI's own structured explanation, not a token trace
— this is stated explicitly in `docs/Project/thinking-mode.md`.

## 5. Observed metrics

From `docs/Project/rioplatense_eval.md` (82-example Rioplatense corpus,
15-example held-out test split, `pukaar-model:2b` via local Ollama):

- rules baseline mean field accuracy: 45.33%.
- Pukaar AI + 12-shot prompt mean: ~78–82%.
- `gpt-4o-mini` reference on the same split: ~85%.

These are developer-facing numbers (Class B in the guardrail) and are not
used in the pitch. Visual-assessment false-positive / false-negative
rates on a public flood dataset: `[TODO]`.

## 6. Honest limitations

- No OpenCV pre-check on the evidence frame today; visual ground truth
  rests entirely on Pukaar AI multimodal. Adding a classical waterline
  estimator as a Layer 1 sanity check is `[TODO]`.
- The reasoning chain is an extracted surrogate, not a raw CoT trace.
- The Rioplatense corpus is small (82) and regional; generalization
  outside the Litoral is unproven.
- The runner-unavailable fallback emits `yellow`, which is conservative
  for safety but will produce nuisance alerts under prolonged Ollama
  outages.
- No public-dataset evaluation has been run yet, so detection-quality
  claims remain forbidden per the guardrail.
</content>
</invoke>