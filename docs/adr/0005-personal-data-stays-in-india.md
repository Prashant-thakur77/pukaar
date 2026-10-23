# 0005. Real personal data stays in India

- Status: Accepted. The India stack (`pukaar-prod`, ap-south-1) is defined in the template and not yet deployed; the live stack in us-east-1 holds demo and test data.
- Date: 23 October 2026

## Context

Pukaar holds villagers' phone numbers, Telegram chat ids, names, report photos and locations. The DPDP Act 2023 has no blanket localisation rule, but CERT-In's 2022 directions require ICT logs to be kept in India, government buyers expect a MeitY-empanelled cloud region, and the Central Government may restrict transfers abroad at any time (DPDP s.16).

## Decision

- No real villager's personal data is stored outside India. Production runs in AWS ap-south-1 (Mumbai), which is MeitY-empanelled; the us-east-1 stack is for synthetic data, judges and development only.
- The DDMA is the data fiduciary; Pukaar's operator is its data processor under a written contract ([docs/MOU_TEMPLATE.md](../MOU_TEMPLATE.md)).
- Logs of processing are kept for at least one year, which covers both CERT-In's 180 days and DPDP Rule 8(3).
- Public routes never expose names, phone numbers or chat ids; family links show a first name, a time and the village only.

## Consequences

- Bedrock in ap-south-1 runs only through cross-region inference profiles; prod uses a global or APAC profile, so model calls may be processed outside India. Only the decision trace and the template go to the model, never a phone number or a name.
- The consent and notice step, `/stop`, and retention and erasure jobs are still to be built before the DPDP Rules' duties start (about 13 May 2027).

## Held by

`backend/tests/test_public_privacy.py`, the template tests on the production stage, and [docs/DEPLOY.md](../DEPLOY.md) (Production stage).
