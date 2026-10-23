# 0001. Rules, not a model, set the level

- Status: Accepted
- Date: 23 October 2026

## Context

A flood level (Normal, Watch, Warning, Critical) decides whether a district officer is woken, which villages are asked to move and, under DM Act s.54, whether a false warning has been issued. A language model can invent a number or a place, cannot explain its answer in terms an officer or a court can check, and changes when its provider changes it. IMD and CWC publish thresholds a district already trusts.

## Decision

Code sets every level, every recipient list and every decision to ask an officer:

- IMD's 24-hour rain bands (64.5, 115.6 and 204.5 mm), each village's own 2-, 5- and 20-year river discharge from its 1984–2024 record, the heavy-burst hourly rule, a river gauge (2 of the last 3 good readings), an officer-verified villager report, and hysteresis on the way down. The rules and their thresholds live in [`risk_rules.py`](../../backend/src/Pukaar/services/risk_rules.py) and [`data/thresholds.json`](../../data/thresholds.json).
- A model may only word the alert: it fills a fixed Hindi template, and a checker rejects any number or place that is not in the decision trace. If the model is down or refused, the fixed template goes out, labelled `rule-fallback`. The live stack runs on that fallback today.
- Every level carries its decision trace: each reading, the line it was measured against and the rule that fired.

## Consequences

- An officer, an auditor or IMD can check every level by hand.
- The rules miss what their inputs miss. In the back-test the global forecasts missed the 30 June 2025 Mandi cloudburst at every village ([docs/SCORING.md](../SCORING.md)); the answer is better inputs (gauges, rain nodes, villager reports), not a model.
- Thresholds must be validated with IMD Shimla and IIT Mandi before a live season, and must never contradict a live IMD red or orange warning ([docs/MOU_TEMPLATE.md](../MOU_TEMPLATE.md)).
- A change to the rules or thresholds is a change to who is warned: it needs a code-owner review and a back-test run.

## Held by

`backend/tests/test_risk_rules.py` (the exact band edges, each village's percentiles), the draft checker tests in `backend/tests/test_llm_and_drafting.py`, and the Cedar policy that gives the drafting agent read-only tools.
