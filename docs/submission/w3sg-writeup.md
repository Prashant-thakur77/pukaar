# Pukaar Raahat (पुकार राहत): Web3 for Social Good writeup

Flood warning that pays the household before the river rises: forecast-triggered anticipatory relief with a public, sealed rule.

- Track: Tech Track (built prototype, repo and demo)
- Code: https://github.com/Prashant-thakur77/pukaar/tree/web3-social-good
- Live relief ledger: https://main.d227ld968f3fok.amplifyapp.com/raahat (no sign-in)
- Contracts on Base Sepolia (chain 84532): AlertRegistry [`0x693F40F3C4321e4b0f9e282771a1ba19b4565Dd3`](https://sepolia.basescan.org/address/0x693F40F3C4321e4b0f9e282771a1ba19b4565Dd3), ReliefPool [`0x8ef8BCe3E7800845ae6b17A51bDe56554bF47C52`](https://sepolia.basescan.org/address/0x8ef8BCe3E7800845ae6b17A51bDe56554bF47C52), ImpactAttestation [`0x9e0285F6ECe2794F05148E88E6A89A19465e0bDF`](https://sepolia.basescan.org/address/0x9e0285F6ECe2794F05148E88E6A89A19465e0bDF), TestINR [`0x6b3C4E4E29233b8d3e336a6148702ab1D395a419`](https://sepolia.basescan.org/address/0x6b3C4E4E29233b8d3e336a6148702ab1D395a419)
- Demo video (3:00): to be added after recording ([script](w3sg-demo-script.md))
- Sources for every number: [w3sg-sources.md](w3sg-sources.md)
- Tags: Web3, Social Impact, Sustainability, AI, Decentralized Identity, DAPP

## Vision

Early warning saves lives; early cash saves livelihoods. Raahat makes both auditable by the people they are for.

## The problem

In the hill districts of Himachal Pradesh a mountain stream can turn into a flood within hours, often at night. The 2023 monsoon killed more than 500 people in the state, and its recovery needs came to ₹8,667.66 crore (HP Government PDNA, 2024). On 30 June and 1 July 2025, cloudbursts in Mandi district left 15 people dead and 27 missing.

Pukaar, our earlier build, already handles the warning: every 15 minutes it turns rain and river forecasts into a level by fixed rules, a district officer approves the alert in one tap, Amazon Polly speaks it in Hindi on Telegram, and each phone taps "मिल गया" (got it). It has been live on AWS since 11 Oct 2026.

What happens to money after that is invisible. Relief in India is sanctioned under SDRF and NDRF norms and reaches households days or weeks later through a chain of offices. Neither a villager nor a donor can check what was promised before the flood, what was released, or who received it.

## What Raahat adds

Raahat is one new module on top of the live warning loop. It does three things.

1. It anchors every published alert on a public chain: the keccak256 hash of the CAP 1.2 XML the alert is published as, its village, level and issue time, and at close the delivered and acknowledged counts and the hash of the after-action report. The record is write-once. Anyone can fetch the official CAP feed, hash it in their own browser and compare: the "re-verify" button on every alert does exactly that, and it reads the hash from the chain, not from our API.
2. It publishes the relief rule before the season as a contract, ReliefPool. The district authority writes the rule (₹1,500 per household when a village reaches Warning on the forecast, ₹4,000 per household when the flood is confirmed, one anticipatory payout per village per 72 hours) and calls `sealRules()`. After that no amount or threshold can change. A village's household list or cash-out agent can still change, because people register, but only after a public delay of one cooldown, announced on chain when it is scheduled. These amounts are illustrative: SDRF norms are still to be mapped with the DDMA.
3. It pays in two tiers. The anticipatory tranche is released when a village reaches Warning, before the water. The code works out eligibility, a district officer releases in one tap (the same pattern as approving an alert), and the contract checks the alert is anchored, the level meets the sealed rule and the village is out of its cooldown, then pays households × amount to the village's cash-out agent. The confirmed tranche needs two of three independent attesters (pradhan, district officer, satellite). Each payout ends in a public receipt per household: a salted household hash with a Merkle proof and a hash of the UPI or cash reference.

A villager needs no wallet, app or account. If the rule fires for a live alert they get a Telegram line, "पुकार राहत: … हर घर के लिए ₹1,500 जारी। प्रधान या बैंक मित्र से लें।", with a link to the receipt, and they cash out where Indian relief already goes: the pradhan, a Business Correspondent or UPI. On the testnet the message says plainly that it is test money.

## Why a chain adds something a database cannot

1. The rule is sealed before the hazard. No office can amend the amounts or the trigger after the water rises, and anyone can read the rule in the contract. The confirmed tranche, like the anticipatory one, pays a village once per cooldown, so one flood cannot be paid three times through three escalating alerts.
2. The confirmation comes from three parties who do not run the ledger: the pradhan (photo report, hashed), the district officer and a satellite check from Sentinel-2 imagery. One of them alone unlocks nothing.
3. A donor and a villager can verify the same receipts without trusting us. The CAP hash, the release and each household receipt are public transactions.

What the chain does not do: it does not forecast, it does not decide the level (code does, from IMD bands and GloFAS river thresholds), and it holds no personal data. A household is `keccak256(villageId, HMAC(salt, householdNo))`; names, phone numbers and chat ids stay in DynamoDB. There is no token sale, no DAO, no NFT and no upgradeable proxy: three small contracts and a test stablecoin.

## What is real, a replay, simulated or planned

| | |
|---|---|
| Real | The Pukaar warning loop on AWS; the contracts on Base Sepolia; every anchor and release transaction; the public ledger at /raahat; the Cedar policies and the audit row for every release |
| Replay | The July 2023 Beas flood replay drives the whole money path on testnet. It is labelled REPLAY everywhere, and on chain the alert carries `exercise=true`, as CAP carries `status=Exercise`. Exercise cooldowns are kept apart from live ones, so a demo can never block a real payout |
| Simulated | The money is TestINR (tINR), a test token with no value. The household register adds labelled demo households on the demo stack. On the testnet the backend holds the three attester keys (one per role, so they are different addresses on chain, but derived from one backend secret) and signs after Cedar checks the person; the cash-out agent is the backend's own address, holding the village's relief for the pradhan. The satellite pair covers Pandoh, for July 2023 only. The pradhan's photo in the demo is a labelled demo image, filed as a replay report |
| Planned | A real INR stablecoin or a bank/UPI rail (needs a licensed partner); SDRF norm mapping with the DDMA; the production chain chosen with the issuing authority. Each attester's own device key |

## How it is built

The four contracts (Solidity 0.8.26, OpenZeppelin 5) are AlertRegistry (87 lines), ReliefPool (161 lines), ImpactAttestation (82 lines) and TestINR (22 lines). Foundry runs 44 tests on them, including fuzzing on amounts and household counts, a token that tries to re-enter `release`, sealing, cooldowns, the exercise flag, two roles on one key counting as one attester, and Merkle receipts that are valid, replayed or from the wrong village. Line, branch and function coverage is 100%. The Merkle proofs in those tests are generated by the Python backend, so the same fixture proves the backend's trees verify on chain.

The backend is the existing Pukaar FastAPI and Step Functions stack with one new package, `raahat/`. The anchor runs after an alert's first successful delivery and again at close. Every chain call is wrapped: a failure is logged, counted as `RaahatTxFailed` (a CloudWatch alarm with its runbook section) and swallowed, and the alert goes out unchanged. That is the same rule Pukaar already applies to Bedrock. A conditional DynamoDB write claims each anchor and each release, so a re-run step or a double tap never sends twice.

Cedar decides who may release relief: district officers only; the public demo accounts, whose password is in the README, only for replay alerts. Every decision writes an audit row. The signer key lives in an SSM SecureString that only the API and workflow roles can read, and a template test fails the build if any other role can. Contract addresses come from stack parameters, so moving to Arbitrum Sepolia or Polygon Amoy is a configuration change.

The public /raahat page is Hindi-first and loads as its own chunk; the villager report page keeps its 129 kB budget and never downloads the chain library. It shows the pool balance (checked again from the chain in the browser), the sealed rule and a timeline per alert: anchored, heard (मिल गया counts), anticipatory relief, confirmed relief. It updates live through AppSync Events and has no axe violations.

Tests: 995 backend tests and 199 frontend tests pass, plus the 44 Foundry tests. The live smoke test checks the deployed stack, Raahat included.

## Who it is for

Five villages today (Thunag, Janjehli, Gohar and Pandoh in Mandi; Sujanpur in Hamirpur) and their registered households; the district officer; the pradhan; donors, NGOs and state funds who want to see where relief went; and any authority that already publishes CAP.

## Impact

WFP's 2020 Bangladesh pilot sent $53 by mobile money to more than 23,000 households about a week before the flood peak. Recipients were 52% less likely to go a day without eating, and their stated wellbeing was 18.7% higher (Oxford CSAE / WFP). Early warning systems save lives and assets worth at least ten times their cost (Global Commission on Adaptation, 2019). Raahat puts the two together on the trigger Pukaar already computes.

Oxfam's UnBlocked Cash pilot in Vanuatu (2019) cut onboarding to about 3.6 minutes per person but found that transaction costs did not clearly fall, because cash-out still went through local providers. We take that seriously: Raahat does not try to replace the cash-out path. It makes the rule and the receipts public and leaves the last step to the pradhan, the Business Correspondent or UPI.

## Feasibility

The warning loop has been live since 11 Oct 2026. Raahat is one module, deployed today on a testnet at no cost. Gas per alert on Base is a few cents (two transactions: the anchor and the outcome). Two partner dependencies stand between this and a pilot, and we name both: a licensed INR rail, and the DDMA's mapping of SDRF norms to the rule.

## Team

Prashant Bahuguna, Prashant Thakur, Puneet Yadav.
