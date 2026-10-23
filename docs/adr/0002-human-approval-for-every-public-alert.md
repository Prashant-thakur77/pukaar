# 0002. A DDMA officer approves every public alert

- Status: Accepted
- Date: 23 October 2026

## Context

Under the Disaster Management Act 2005, s.30(2)(xiv), the early-warning mechanism of a district belongs to its DDMA. A private system has no authority to warn the public, and s.54 punishes a false warning that causes panic. Officers also act more readily when the evidence is in front of them: in Kerala (2018), Kedarnath (2013) and Kathmandu (2024) warnings existed and the decision to act lagged.

## Decision

- Nothing reaches the public unless a named DDMA officer approves it. Each alert is a Step Functions execution that waits on a task token ([`infra/approval.asl.json`](../../infra/approval.asl.json)); the officer approves in the console, from a signed single-use link, or from a Web Push button.
- An unanswered approval moves to the next officer on the district's duty roster, then to the whole roster and the ADM or DM, with an alarm.
- Critical auto-send (sending a critical alert when every officer has timed out) is off by default (`CriticalAutoSend=false`) and may only be turned on with the DDMA's written sign-off, recorded in the order adopting Pukaar.
- Cedar decides who may approve, with a default deny; every allow and deny is written to an append-only audit log, and an action whose audit write fails is not allowed to stand.
- Drills are labelled as drills; replays never reach a real phone.

## Consequences

- Approval adds minutes. The design keeps them short (the evidence, the exact message and its recipients on one screen; hold one second to approve) and measures them: approval time is one of the pilot's ten metrics ([docs/PILOT_PROTOCOL.md](../PILOT_PROTOCOL.md)).
- A district must keep a staffed duty roster. Officers are not yet scoped by district in Cedar, and there is no DDMA-head or state role; both are needed before a second district joins.

## Held by

`backend/tests/test_asl.py` (approve, decline, timeout to the next officer, auto-send off and on, failsafe), the Cedar policy tests, and the audit guard in `backend/src/Pukaar/policy/guard.py`.
