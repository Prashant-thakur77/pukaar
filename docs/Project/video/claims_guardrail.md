# Claims guardrail

Single source of truth for what the pitch can and cannot say. Anyone editing
narration, captions, screen text, or repo-facing copy should diff against this
file first.

## A. Safe claims (current MVP — say freely)

- "When connectivity fails, a local Pukaar AI-powered flood warning node can still watch, reason, alert, and sync later." (thesis)
- "Offline-first flood warning system."
- "Pukaar AI runs close to the evidence, not only in the cloud."
- "The fixed node builds a temporal evidence pack from curated frames."
- "Pukaar AI produces an assessment level, temporal summary, reasoning summary, and critical evidence."
- "Every non-green alert exposes a reasoning summary in Spanish plus a deterministic rule trace."
- "Volunteer reports are queued locally and synced when connectivity returns."
- "The alert package is schema-tagged for SINAGIR."
- "Aligned with Plan Nacional para la Reducción del Riesgo de Desastres 2025–2029 priorities on local preparedness."
- "MVP demo on public and simulated scenarios."
- "Audible siren on the device itself when the local node fires an alert."
- "On-device Android volunteer flow uses LiteRT-LM Android to load the same `pukaar-model-2b.litertlm` artifact as the backend." (only if that path is shown — see `docs/Project/android_pukaar-ai.md`)

## B. Reserved for public-data evaluation (NOT in this video)

These become safe only after the planned evaluation on public flood datasets.

- Any percentage-based claim about detection or classification quality.
- "Outperforms a rules baseline by X."
- "Lead-time vs baseline of X minutes."
- "Generalizes across N rivers / sites."
- Any ROC, PR or confusion-matrix figure.
- Any comparison to other models (cloud or otherwise).

## C. Reserved for real local field data (NOT in this video)

- "Validated on Litoral data."
- "Operating with Defensa Civil / municipal partners."
- "Deployed at <site>."
- "Detected real event on <date>."
- "Saved / evacuated N people."
- Any photo or video that includes identifiable real victims, real responders without consent, or real incident PII.

## D. Quoted lines from `narration.md` and their classification

| Line                                                                                                  | Class | Why                                              |
| ----------------------------------------------------------------------------------------------------- | ----- | ------------------------------------------------ |
| "Flood warnings often depend on the one thing that disappears first."                                 | A     | Editorial framing, not a metric.                 |
| "Pukaar AI runs close to the evidence, not only in the cloud."                                            | A     | Architectural claim, true today.                 |
| "The output is an assessment level, a temporal summary, a reasoning summary..."                       | A     | Schema claim, verifiable in code.                |
| "This is structured local reporting, not a benchmark result."                                         | A     | Honesty disclaimer.                              |
| "When connectivity returns, the queue drains."                                                        | A     | Demonstrated by `scripts/demo_connectivity.py`.  |
| "MVP demo on public and simulated scenarios."                                                         | A     | Honesty disclaimer.                              |
| "Public-data validation next. Real local data after that."                                            | A     | Roadmap, not a result.                           |
| "Predicts floods N minutes in advance."                                                               | C     | Forbidden — appears nowhere.                     |
| "98% accurate on Litoral data."                                                                       | C     | Forbidden — appears nowhere.                     |

## E. QC checklist before render

- [ ] No spoken word in `narration.md` falls in class B or C.
- [ ] No on-screen text in `screen_text.md` falls in class B or C.
- [ ] Every UI-heavy block carries the `MVP DEMO — public/simulated scenario` watermark.
- [ ] No real-PII volunteer reports.
- [ ] No real partner / agency logo without sign-off.
- [ ] End card states roadmap honestly: "MVP today · Public-data evaluation next · Real local data after that".

## F. If a judge asks "do you have benchmark numbers?"

Answer template (do not improvise stronger):

> Not in this video. We have a 82-example Rioplatense corpus and a few-shot
> structurer with internal numbers in `docs/Project/rioplatense_eval.md`,
> but we treat that as developer-facing, not a marketing claim. The next
> milestone is evaluation on public flood data, then real local data.
