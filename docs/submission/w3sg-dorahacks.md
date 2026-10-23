# DoraHacks BUIDL: what goes in each field

For the Web3 for Social Good Hackathon 2026 (SMU × GSR Foundation × UMA). Deadline: 25 Oct 2026, 05:30 IST (24 Oct, 00:00 UTC). Submit to the Tech Track.

## Fields

BUIDL name

```
Pukaar Raahat (पुकार राहत)
```

Logo: `docs/media/pukaar-raahat-logo.png` (480×480).

Vision (the short pitch)

```
Flood relief that reaches a Himalayan village before the river. A forecast releases cash on a rule sealed on chain before the monsoon, 2 of 3 independent keys confirm the flood, and each household gets a public receipt with no personal data.
```

Track: Tech Track. Is this BUIDL an AI agent: No.

Tags: Web3, Social Impact, Blockchain, Sustainability, DAPP, AI.

Links

```
GitHub:        https://github.com/Prashant-thakur77/pukaar/tree/web3-social-good
Live demo:     https://main.d227ld968f3fok.amplifyapp.com/raahat
Demo video:    <YouTube link after upload>
```

Team: Prashant Bahuguna, Prashant Thakur, Puneet Yadav.

## Details (paste as markdown)

```markdown
**Pukaar Raahat** pays a flood-hit household before the water arrives, on a rule anyone can read, and shows every rupee on a public chain.

- Live ledger, no sign-in: https://main.d227ld968f3fok.amplifyapp.com/raahat
- Code: https://github.com/Prashant-thakur77/pukaar/tree/web3-social-good
- Contracts on Base Sepolia (84532): AlertRegistry `0x693F40F3C4321e4b0f9e282771a1ba19b4565Dd3`, ReliefPool `0x8ef8BCe3E7800845ae6b17A51bDe56554bF47C52`, ImpactAttestation `0x9e0285F6ECe2794F05148E88E6A89A19465e0bDF`, TestINR `0x6b3C4E4E29233b8d3e336a6148702ab1D395a419`

## The problem

In Himachal Pradesh a mountain stream can flood a village within hours, often at night. On 30 June 2025 cloudbursts hit Mandi district: 15 dead and 27 missing by 9 July. In Syathi village no report says any warning arrived; a dog woke the families. Relief comes later, through SDRF norms and a chain of offices, and neither the villager nor a donor can check what was promised, what was released, or who received it.

Our earlier build, Pukaar, already fixes the warning. It has run live on AWS since 11 October 2026: every 15 minutes it turns rain and river forecasts into a level by fixed rules, a district officer approves the alert in one tap, Amazon Polly speaks it in Hindi on Telegram, and each phone taps "मिल गया" (got it). Raahat adds the money.

## Why it matters

Cash before a flood works. In WFP's 2020 Bangladesh pilot, $53 by mobile money about a week before the flood peak reached more than 23,000 households. They were 52% less likely to go a day without eating, and their wellbeing was 18.7% higher (Oxford CSAE / WFP). Raahat puts that money on the trigger Pukaar already computes, for five villages in Mandi and Hamirpur today.

## How it works

1. **Anchor.** Every published alert's CAP 1.2 XML is hashed onto AlertRegistry, write-once, with `exercise=true` for replays and drills. The "Re-verify" button on every alert reads the hash from the chain, fetches the public CAP feed and hashes it in your browser.
2. **A sealed rule.** The district authority writes the rule into ReliefPool and calls `sealRules()` before the season: ₹1,500 per household at Warning, ₹4,000 once the flood is confirmed, one payout per village per 72 hours. After the seal no amount or threshold can change. Household lists can, but only after a public delay. (Amounts are illustrative; SDRF norms are to be mapped with the DDMA.)
3. **Tier 1, before the water.** Code checks eligibility, a district officer releases in one tap, and the contract checks again (anchored, level, cooldown) before paying.
4. **Tier 2, confirmed.** Two of three independent keys must attest the flood: the village pradhan (from a verified photo, hashed), the district officer, and a Sentinel-2 satellite check (water 2.07 → 4.10 km² over 317.7 km² for July 2023; the image's hash goes on chain).
5. **Receipts.** Each household gets a public receipt: a salted household hash with a Merkle proof and a hash of the UPI or cash reference. Names, phone numbers and chat ids never leave the database.

A villager needs no wallet, app or account. They cash out where Indian relief already goes: the pradhan, a Business Correspondent or UPI.

## Why a chain

- The rule is sealed before the hazard: no office can change the amounts or the trigger once the water rises.
- No single person confirms a flood: two of three independent keys must agree.
- A donor, a journalist and a villager can check the same receipts without trusting us.
- If the chain is down, the warning still goes out. Every chain call is wrapped, logged, counted as `RaahatTxFailed` with an alarm, and swallowed.

There is no token sale, DAO, NFT or upgradeable proxy: four small contracts and a test stablecoin.

## Built and tested

- Solidity 0.8.26 with OpenZeppelin 5: four contracts, 53 Foundry tests with 100% line, branch and function coverage. The tests include fuzzing, a re-entrant token, sealing, cooldowns, the exercise flag and Merkle receipts generated by the Python backend.
- AWS backend (FastAPI, Step Functions, DynamoDB, Cedar policies with an audit row for every release): 1,006 backend and 200 frontend tests pass.
- The signer key lives in SSM, readable only by two roles; a template test enforces it.
- The public /raahat page is Hindi-first, loads as its own chunk and has no axe violations. The villager's report page keeps its 129 kB budget.

## Try it in two minutes

1. Open https://main.d227ld968f3fok.amplifyapp.com/raahat (no sign-in): the pool balance (your browser checks it against the chain), the sealed rule, and every alert's timeline with its transactions. Press **Re-verify** on any alert.
2. To run a flood yourself, sign in at /login as `judge`, password `Judge-E5FCkUl3uY-2026`. Start the July 2023 replay in the console and approve Pandoh's Warning. Under **Release relief**, release tier 1, attest as officer, run the satellite check, then release tier 2. Judge accounts act on replays only, and every replay is labelled on chain.

## What is not real yet

The money is TestINR, a test token with no value; a real pilot needs a licensed INR rail. The amounts await mapping to SDRF norms with the district authority. On the testnet our server holds the attesters' keys; in a pilot each officer and pradhan signs on their own device.

Team: Prashant Bahuguna, Prashant Thakur, Puneet Yadav.
```

## YouTube (upload before submitting)

- File: `docs/media/pukaar-raahat.mp4` (2:48, 1080p).
- Title: `Pukaar Raahat: flood relief before the river (Web3 for Social Good 2026)`
- Description: the block under "Video description" in `docs/submission/w3sg-film-script.md`.
- Thumbnail: `docs/media/pukaar-raahat-thumbnail.jpg`. Captions: upload `docs/media/pukaar-raahat.srt` as English.
- Visibility Public or Unlisted; "No, it's not made for kids"; category Science & Technology.

After uploading, put the link in the BUIDL's video field and in `docs/submission/w3sg-writeup.md`.

## Later rounds

From 26 to 31 October, eligible teams are invited to send a presentation video (due 1 to 3 November). The final is on 26 November at SMU. The film and `w3sg-writeup.md` are the base for both.
