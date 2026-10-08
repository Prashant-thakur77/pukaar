# Research Context

Distilled project context from these external working docs:

- `Análisis del reto Pukaar Release.pdf`
- `Proyecto Pukaar_ Mejora y Ganancia.pdf`
- `Pukaar_Trabajo_Pendiente_Priorizado_v2.md.pdf`
- `Pukaar_Division_Trabajo_5_Personas.md.pdf`

This file is intentionally condensed. It should be used as a context aid, not as a source of hard guarantees.

Detailed fallback copies of the external source documents live in `docs/Project/context-sources/`.

## Current Framing

- The repo is no longer just a generic MVP. The operative framing is a competitive Project submission for **Pukaar**, with primary target **Global Resilience** and secondary/strategic target **LiteRT / Google AI Edge**.
- The strongest product story is not "flood dashboard" in general. It is:
  - offline-first local operation during connectivity loss
  - hybrid evidence from fixed camera + volunteer reports
  - auditable Pukaar AI reasoning in Spanish
  - meaningful edge or on-device Pukaar AI use
  - output that can plug into institutional emergency workflows

## What Judges Likely Care About

- Impact and vision carry the most weight.
- Video/storytelling and technical execution each matter heavily too.
- The project should answer "why Pukaar AI locally?" and "why not just a cloud model?" without hand-waving.
- Local inference, multimodality, offline behavior, and transparent reasoning are not side features; they are central to the pitch.

## Novelty Positioning

The strongest defensible novelty is the combination of:

1. Fixed-node visual telemetry with classical CV as the primary detector.
2. Volunteer reports parsed from Rioplatense Spanish into structured emergency signals.
3. Local Pukaar AI reasoning layered on top of deterministic evidence.
4. Operation during outages with queueing and later sync.
5. Export/interoperability toward emergency-management standards and public-sector use.

Important framing:

- OpenCV or deterministic sensing should remain the authoritative source for core hazard scoring where possible.
- Pukaar AI should be framed as a reasoning, explanation, structuring, and multimodal interpretation layer, not as a magical black box that invents critical safety decisions.
- This "deterministic firewall + LLM reasoning" pattern is strategically strong and should be preserved in docs, demos, and implementation choices.

## Research-Derived Priorities

When there is competition for time, the external docs strongly favor this order:

1. Demonstrable edge/on-device Pukaar AI path, especially LiteRT-aligned where feasible.
2. Clear interoperable emergency output, ideally CAP v1.2 framing.
3. Strong 3-minute video narrative with a real emergency operator story.
4. Argentine context in the demo, not a purely foreign placeholder demo.
5. Quantitative benchmark card: latency, throughput, memory, end-to-end timing, parsing quality.
6. Explicit anti-hallucination framing and safe human-auditable reasoning.
7. Native Pukaar AI differentiators such as multimodality and function calling when practical.

## Practical Guidance for This Repo

- If a task is ambiguous between "nice engineering cleanup" and "improves submission strength", favor the latter.
- If a task is ambiguous between "generic architecture elegance" and "clear demo evidence", favor the latter.
- If a task is ambiguous between "cloud convenience" and "edge credibility", favor the latter unless the user explicitly asks for a cloud-only shortcut.
- If a task is ambiguous between "custom local schema" and "recognized emergency interoperability framing", favor the latter.

## LiteRT / Edge Guidance

- The external research repeatedly treats real LiteRT or AI Edge alignment as a major leverage point, especially for special-prize positioning.
- Ollama remains a valid development/runtime bridge, but should not be the only story if the user is optimizing for the strongest judging angle.
- If LiteRT is not practical in time or on the current machine, the repo should still explain the attempted path and the exact fallback honestly.

## Output / Interoperability Guidance

- A narrow "SINAGIR-like" export is weaker than a standards-oriented framing.
- CAP v1.2 style interoperability is strategically stronger for the writeup and pitch because it generalizes beyond one local wrapper.
- Argentina-specific institutional compatibility is still valuable, but should be framed as one downstream integration path, not the only one.

## Demo Guidance

Preferred demo spine:

1. Human problem under degraded communications.
2. Fixed-node detection and local reasoning.
3. Volunteer offline report in colloquial Spanish.
4. Reconnection and sync.
5. Auditable alert output and actuation/interoperability.

Preferred demo evidence:

- local/offline transitions that are visible on screen
- actual latency/throughput numbers
- reasoning output tied to concrete signals
- evidence frame or supporting media
- Argentine setting where possible

## Competitive Differentiation

Relative to common comparators, the repo should emphasize that it is not just:

- a cloud flood forecast
- a crowdsourcing chatbot
- a single-sensor IoT alarm
- a generic Pukaar AI demo

It is strongest when presented as the intersection of:

- edge-native alerting
- human report fusion
- regional language specialization
- transparent reasoning
- emergency workflow interoperability

## Team-Split Guidance

If the user asks for planning or parallelization, the external division-of-work doc suggests five natural workstreams:

- edge node / LiteRT / benchmarks
- mobile / volunteer / offline path
- backend fusion / standards output / function calling
- storytelling / writeup / pitch
- integration / polish / compliance / end-to-end demo

That split is useful as planning context even if the actual team structure differs.

## Constraints to Preserve

- Do not fake real hardware paths or institutional integrations.
- Do not let speculative work eclipse the working demo.
- Do not break the offline-first story for the sake of architectural neatness.
- Do not weaken the Argentina/Rioplatense context in docs or demo choices without a reason.
