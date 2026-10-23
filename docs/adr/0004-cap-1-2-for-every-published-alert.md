# 0004. Every published alert is a CAP 1.2 message

- Status: Accepted
- Date: 23 October 2026

## Context

India's national alert platform, SACHET (NDMA, built by C-DOT), and the cell broadcast system launched on 2 May 2026 run on the Common Alerting Protocol. Only the warning agencies (IMD, CWC and others) and the SDMAs may issue and authorise alerts on them. A district system that speaks its own format can never be relayed by them, and a closed format locks a district into one supplier.

## Decision

- Every alert that actually goes out is also published as a CAP 1.2 message (`/cap/alerts.atom`, `/cap/alerts/{id}.xml`), with Hindi and English `info` blocks, OASIS event codes, the district's LGD geocode, an `Update` that references every alert still in force and a `Cancel` all-clear.
- Replays and drills are `status=Exercise`, never `Actual`. Pending, declined and expired alerts are never published.
- The sender is the issuing authority. On the dev stack the sender says "(demo)"; a production stack refuses to deploy without the DDMA's own sender and name.
- Pukaar consumes SACHET and IMD as inputs and asks the SDMA for a broadcast; it does not originate SACHET or cell broadcast alerts itself.

## Consequences

- Any CAP reader can parse Pukaar's alerts without custom code, and an SDMA can relay them ([docs/SACHET.md](../SACHET.md)).
- Nothing reads the feed officially yet.

## Held by

`backend/tests/test_cap.py` (every level validated against the OASIS CAP 1.2 schema) and `backend/tests/test_cap_profile.py` (the Google Public Alerts profile rules).
