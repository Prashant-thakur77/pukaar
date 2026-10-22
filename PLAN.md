# Pukaar Raahat (पुकार राहत) — build plan for the Web3 for Social Good Hackathon 2026

> **One line:** Pukaar already predicts the flood and proves the warning reached each phone. Raahat adds the last gap: it pays the household **before** the water rises, by a rule written before the monsoon, and every rupee is traceable from forecast to phone.

Branch: `web3-social-good`. This branch is for the SMU × GSR Foundation × UMA hackathon only. `main` stays the AWS / Environmental Hacks submission; nothing here is merged back without an explicit decision.

- Hackathon: https://dorahacks.io/hackathon/web3-social-good-2026
- Submission deadline: **25 Oct 2026, 05:30 IST** (Tech Track or Idea Track, same form)
- Screening 26–31 Oct → presentation video 1–3 Nov → shortlist 4 Nov → refine 5–25 Nov → finals **26 Nov, SMU Singapore (online allowed)**
- Prize: Champion $2,000 cash + up to $6,000 incubation grant; runner-up $1,250; third $750, per track

---

## 0. Why this wins (read this before building anything)

### 0.1 The judging rubric, and where the field is weak

| Criterion | Weight | What most of the 40 entries will do | What Raahat does |
|---|---|---|---|
| Social impact potential & problem relevance | 30% | Describe a problem | Show a live system with real alerts, a real Telegram bot, real villages, sourced death tolls, and a back-tested flood |
| Solution quality (technical execution) | 25% | A contract + a React form | A deployed AWS stack with 828 + 180 tests, plus 3 small audited-by-tests contracts, plus a public relief ledger |
| Innovation & meaningful use of Web3 | 20% | "We put X on chain" | **Anticipatory cash**: the forecast trigger *is* the payout trigger. The chain enforces a rule published before the flood and makes every payout auditable by donor, officer and villager. The chain does one job nobody else can: nobody can move the goalposts after the water rises |
| Feasibility & long-term sustainability | 15% | A roadmap slide | Pukaar is live since 11 Oct 2026; Raahat is one new module, testnet today, and the cash-out path (pradhan / Business Correspondent / UPI reference) is the one Indian relief already uses |
| Presentation & pitch | 10% | Slides | A 3-minute recorded demo on the deployed stack during a labelled replay of a real flood, the Polly voice, then the on-chain receipts appearing |

### 0.2 The evidence that makes "anticipatory cash" a judge-proof argument

These are the numbers to put in the pitch, the README and the video. All sourced; do not round them up.

- **Paying before the flood works.** WFP's 2020 Bangladesh pilot sent **$53 by mobile money to 23,000+ households about a week before the flood peak**. Recipients were **52% less likely to go a day without eating**, children were more likely to have eaten three meals, asset loss was lower, earning potential three months later was higher, and stated wellbeing was **18.7% higher**. Source: Oxford CSAE / WFP study, https://csae.web.ox.ac.uk/node/2183966 (working paper: https://ora.ox.ac.uk/objects/uuid:12ea16b2-edc0-4af5-8824-132aba4557bd). Also the IPA brief: https://poverty-action.org/sites/default/files/2026-09/IPA-BRIEF-Anticipatory%20Action%20Brief-r5_1554.pdf
- **Blockchain cash transfers already ran in a disaster.** Oxfam's UnBlocked Cash (Vanuatu, 2019, DAI + NFC cards via Sempo): onboarding **~3.6 minutes per person vs over an hour** in the 2018 Ambae response; 187 households, 29 vendors, ~1,209 people. Honest finding: direct transaction costs did not clearly fall because cash-out still depended on local financial providers. Source: https://reliefweb.int/report/vanuatu/unblocked-cash-piloting-accelerated-cash-transfer-delivery-vanuatu-research-report — **we cite the limitation too**; that is what the "feasibility" judges reward.
- **WFP Building Blocks** moves aid to 1M+ people on a permissioned chain and reports fee savings. Source: https://www.wfp.org/building-blocks. Also cite the critique (it is a single-operator ledger: https://davidgerard.co.uk/blockchain/2017/11/26/the-world-food-programmes-much-publicised-blockchain-has-one-participant-i-e-its-a-database/) and say why Raahat is different: three independent parties (district authority, pradhan, satellite oracle) sign, and donors verify on a public chain.
- **Himachal is where it matters.** 2023 monsoon: 500+ dead, recovery needs ₹8,667.66 crore (HP PDNA 2024). Mandi, 30 Jun–1 Jul 2025: 15 dead, 27 missing. Already sourced in README.md — reuse verbatim.
- **Early warning pays 10×.** Global Commission on Adaptation 2019: early-warning systems "save lives and assets worth at least ten times their cost"; 24 h of warning cuts damage 30%. Already in README.

### 0.3 What we learned from winners of comparable hackathons

| Winner | Hackathon | What judges rewarded | What we copy |
|---|---|---|---|
| GreenAfrica (Nigeria), 1st overall $135K | Hedera Africa 2025 ($1M, 13,000 devs) | A physical loop (bin → device → chain → airtime) with a *public live dashboard*; chain used only for proof | A public ledger page anyone can open with no login; the chain records proof, nothing else |
| Carboni (Egypt), 2nd overall | Hedera Africa 2025 | Used an existing framework (Hedera Guardian) rather than reinventing; granular, auditable units | Reuse our existing CAP 1.2 feed and after-action report as the *things we anchor*, do not invent new data |
| Effisend X Africa (Mexico), 3rd overall | Hedera Africa 2025 | AI agent + payments; "pay with your face" demo was visceral | Make the demo visceral: the Polly voice plays, then the payout receipt appears on the explorer within seconds |
| RDZ Health (Zimbabwe), $30K | Hedera Africa 2025 | Consent as an on-chain primitive — "why the chain is necessary" was undeniable | Our "why chain" is one sentence: *rules published before the flood cannot be changed after it* |
| Afiya (Nigeria), $20K | Hedera Africa 2025 | Complete, polished, familiar idea placed low | Don't ship a familiar idea; anticipatory cash on a forecast trigger is not in the DoraHacks corpus |
| UnBlocked Cash (Oxfam) | EU Horizon Prize "Blockchains for Social Good" (reported €1M winner, 2020 — verify before citing) | Field pilot, honest report of what did not improve | Publish a "what is real / replay / simulated / planned" table like README.md already does |

Anti-patterns that lose points with academic judges (SMU SCIS, UMA): governance tokens, DAO voting, NFT badges for volunteers, "decentralised sensor network", anything with a tokenomics slide. **None of these go in.**

---

## 1. What Raahat is (product definition)

### 1.1 The gap in Pukaar today

Pukaar closes the loop *forecast → level → approval → spoken alert → "मिल गया" → roll-call → after-action report*. After that, nothing is auditable about **money**: relief in India is sanctioned from SDRF/NDRF norms and reaches households days to weeks later through a chain of offices, with no public record a villager or donor can check. Raahat is the money layer, and it does exactly three things:

1. **Anchors** every published alert, acknowledgement summary and impact confirmation as a hash on a public chain (nobody can later claim no warning was issued, or back-date one).
2. **Publishes the relief rule before the season** (who gets how much at which level, with which confirmations) as a contract anyone can read. Officers approve releases; they cannot change amounts or eligibility after the fact.
3. **Pays in two tiers**: an **anticipatory** tranche when a village reaches *Warning* on the forecast (the Bangladesh evidence), and a **confirmed-impact** tranche when 2 of 3 attesters confirm the flood (pradhan, district officer, satellite oracle). Every payout is a public receipt with a UPI/cash-out reference hash and no personal data.

### 1.2 Who it is for

- **Villager / household**: hears the alert as today; if the rule fires, receives a Telegram message "राहत: ₹X आपके लिए जारी, प्रधान/बैंक मित्र से लें, रसीद कोड …" with a receipt link; no wallet, no app, no account. Cash-out through the existing pradhan / Business Correspondent / UPI path.
- **District officer (DDMA)**: one new approval type in the console, "Release relief for alert …", same one-tap pattern as alert approval. Sees the pool, the rule, and every release.
- **Pradhan**: attests impact (photos → hash), confirms cash-out receipts for their own village only (Cedar).
- **Donor / NGO / CSR / state fund**: funds the pool, reads the public ledger; sees forecast → alert → confirmations → payouts for every rupee.
- **Public / press / researchers**: `/raahat` page and the explorer, no login.

### 1.3 What is real, replay, simulated, planned (put this table in README and the pitch)

| | |
|---|---|
| **Real** | The Pukaar loop on AWS (unchanged), the contracts deployed on a public testnet, every anchor/attest/release transaction, the public ledger page, the Cedar policies and audit log for the new actions |
| **Replay** | The July 2023 Beas flood replay triggers the whole money path on testnet; labelled REPLAY everywhere, including the on-chain `exercise=true` flag (mirrors CAP `status=Exercise`) |
| **Simulated** | The stablecoin is a test token ("tINR", 18 dp) we mint on testnet; the satellite oracle runs on the Sentinel-2 before/after already in `/impact`; cash-out receipts are entered by the demo pradhan |
| **Planned** | A real INR stable or a bank/UPI rail (needs a licensed partner), production chain choice with the issuing authority, SDRF norm mapping with the DDMA |

---

## 2. Architecture

```
Pukaar today                                   Raahat (new, this branch)
─────────────────────────────                  ─────────────────────────────────────────────
sweep → level rises                            
  → Step Functions approval                    
  → deliver (Telegram + Polly)  ──────────────▶ anchorAlert(alertId, hash(CAP xml), level, village, exercise)
  → "मिल गया", re-send                         
  → close (after-action, CAP)   ──────────────▶ anchorOutcome(alertId, hash(after-action), delivered, acked)
                                               
  level == WARNING (forecast only) ───────────▶ ReliefPool.release(alertId, TIER_ANTICIPATORY)  [officer approves]
                                               
  /impact Sentinel-2 diff ─────┐               
  pradhan photo report ────────┼──────────────▶ ImpactAttestation.attest(alertId, severity, evidenceHash)  (2 of 3)
  officer confirmation ────────┘                   └─▶ confirmed ─▶ ReliefPool.release(alertId, TIER_CONFIRMED) [officer approves]
                                               
                                               ReliefPool pays per-household amounts to the village's
                                               cash-out agent; each payout = PayoutReceipt(householdHash, amount, upiRefHash)
                                               
                                               /raahat public ledger ◀── indexer (backend reads events, caches in DynamoDB)
```

### 2.1 Chain choice

- **Base Sepolia** (EVM testnet). Reasons: free faucets, 2-second blocks (the receipt appears while the Polly voice is still playing), good explorer (BaseScan), viem/wagmi tooling, and the rubric is chain-agnostic. Everything is written against viem / web3.py so it moves to any EVM chain by changing `RAAHAT_CHAIN_ID` and `RAAHAT_RPC_URL`.
- Fallback if Base Sepolia faucets are flaky on demo day: Arbitrum Sepolia or Polygon Amoy (same code).
- Do **not** add a second chain "for coverage". One chain, done well.

### 2.2 Contracts (`contracts/`, Foundry, Solidity 0.8.26, OpenZeppelin 5)

Three contracts, each under ~150 lines. No upgradeability proxies (hackathon, testnet, honesty).

**`AlertRegistry.sol`** — the notarised warning record

```solidity
struct AlertRecord {
    bytes32 villageId;      // keccak256("gohar")
    uint8   level;          // 1 watch, 2 warning, 3 critical
    bytes32 capHash;        // keccak256 of the CAP 1.2 XML as served by /cap/alerts/{id}.xml
    string  capUri;         // the public URL so anyone can re-hash it
    uint64  issuedAt;       // alert created_at
    bool    exercise;       // replay or drill (mirrors CAP status=Exercise)
    uint32  delivered;      // filled by anchorOutcome
    uint32  acknowledged;   // filled by anchorOutcome
    bytes32 afterActionHash;// filled by anchorOutcome
}
function anchorAlert(bytes32 alertId, AlertRecord calldata r) external onlyRole(ORACLE_ROLE);
function anchorOutcome(bytes32 alertId, uint32 delivered, uint32 acked, bytes32 afterActionHash) external onlyRole(ORACLE_ROLE);
event AlertAnchored(bytes32 indexed alertId, bytes32 indexed villageId, uint8 level, bool exercise, bytes32 capHash);
event OutcomeAnchored(bytes32 indexed alertId, uint32 delivered, uint32 acknowledged);
```
ORACLE_ROLE = the Pukaar workflow Lambda's signer (key in SSM SecureString, same pattern as the Telegram token). One write per alert, one per close. Write-once: `anchorAlert` reverts if the id exists.

**`ImpactAttestation.sol`** — 2-of-3 confirmation that the flood happened

```solidity
enum Attester { PRADHAN, OFFICER, SATELLITE }
function attest(bytes32 alertId, Attester who, uint8 severity, bytes32 evidenceHash) external;
// PRADHAN: msg.sender must hold PRADHAN_ROLE for that villageId (role key = keccak(villageId, "pradhan"))
// OFFICER: OFFICER_ROLE
// SATELLITE: ORACLE_ROLE (the backend, from the Sentinel-2 diff in services/external_data.py / frontend Impact)
function isConfirmed(bytes32 alertId) public view returns (bool); // >= 2 distinct attesters, severity >= 2
event Attested(bytes32 indexed alertId, Attester who, uint8 severity, bytes32 evidenceHash);
event Confirmed(bytes32 indexed alertId);
```
`evidenceHash` = keccak of the S3 object (photo set or satellite diff PNG) — the object stays private in S3; the hash is public. No PII on chain, ever.

**`ReliefPool.sol`** — the rule, the money, the receipts

```solidity
struct Rule {                       // set once per season by DDMA_ROLE, then frozen (sealRules())
    uint8   minLevelAnticipatory;   // 2 = warning
    uint256 amountAnticipatory;     // per household, tINR wei
    uint256 amountConfirmed;        // per household, on 2-of-3 confirmation
    uint32  cooldownHours;          // one anticipatory payout per village per cooldown
}
mapping(bytes32 villageId => bytes32 householdRoot) public households;   // Merkle root of keccak(villageId, saltedHouseholdNo)
mapping(bytes32 villageId => uint32) public householdCount;
mapping(bytes32 villageId => address) public cashOutAgent;               // pradhan / BC wallet for the village

function fund(uint256 amount) external;                                   // anyone (donor) — emits Funded(donor, amount)
function release(bytes32 alertId, uint8 tier) external onlyRole(DDMA_ROLE); // officer approves; contract checks:
   //  tier 1: AlertRegistry.level >= minLevelAnticipatory && !exercise-paid-twice && cooldown ok
   //  tier 2: ImpactAttestation.isConfirmed(alertId)
   //  amount = householdCount[village] * amountForTier; transfers tINR to cashOutAgent[village]
   //  emits Released(alertId, village, tier, households, total)
function receipt(bytes32 alertId, bytes32 householdHash, bytes32[] proof, bytes32 upiRefHash) external; // cashOutAgent for that village only
   //  verifies Merkle proof, one receipt per household per alert, emits PayoutReceipt(alertId, householdHash, upiRefHash)
function sealRules() external onlyRole(DDMA_ROLE);                        // after this, Rule is immutable for the season
```
Replay alerts (`exercise=true`) **can** release on testnet so the demo runs end to end, but the event carries `exercise=true` and the ledger labels it REPLAY, exactly like the CAP feed. A production deploy sets `allowExercisePayout=false` in the constructor.

**Design rules the contracts must satisfy (write Foundry tests for every line):**
- No personal data on chain: household = `keccak256(villageId, HMAC(serverSalt, householdNo))`; names, phones, chat ids never leave DynamoDB.
- Code decides eligibility, a human releases, the chain enforces the rule. Same philosophy as "code decides, the model words".
- Sealed rules: after `sealRules()`, no amount or threshold can change. This is the one-sentence "why chain".
- Every revert has a reason string the frontend shows in Hindi and English.
- Reentrancy guard on `release`; SafeERC20; OZ AccessControl with roles above; no `selfdestruct`, no `delegatecall`, no proxy.

**`TestINR.sol`** — 18-dp ERC20 "tINR", mintable by deployer only, clearly named *test*.

### 2.3 Backend (`backend/src/Pukaar/raahat/`)

| File | Does | Hooks into |
|---|---|---|
| `chain.py` | web3.py client; signer from SSM (`/pukaar/dev/raahat/signer_key`); `anchor_alert`, `anchor_outcome`, `attest_satellite`, `read_pool`, `read_events`; every call wrapped: failure is logged + counted (`RaahatTxFailed` metric), **never raises into the alert path** (an alert must go out even if the chain is down — same rule as Bedrock fallback) | `workflow/steps.py` deliver step (after first delivery) and `step_close` |
| `rules.py` | Mirrors the on-chain Rule for display + pre-checks; `eligible_tier(alert, attestations)` | console approvals |
| `households.py` | Builds the Merkle tree per village from `Recipient` rows (salted); writes root once per season; produces proofs for the cash-out agent UI | `store/repo.py` (new rows `RAAHAT#HOUSEHOLDS#<village>`) |
| `attest.py` | Satellite attester: reuses the Sentinel-2 before/after diff behind `/impact`; severity from flooded-pixel fraction; uploads diff PNG to S3, attests its hash | `services/external_data.py`, `frontend/src/pages/Impact.tsx` data |
| `indexer.py` | Reads contract events (last N blocks, checkpoint in DynamoDB) into `RAAHAT#LEDGER#` rows so `/raahat` loads fast and works if the RPC is slow | `handlers/sweep.py` (every 15 min) + on-demand after our own tx |
| `api/routers/raahat.py` | Public: `GET /raahat/pool`, `GET /raahat/ledger?village=`, `GET /raahat/alerts/{id}` (anchor + attestations + releases + receipts, explorer links). Officer: `POST /raahat/alerts/{id}/release` (Cedar `release_relief`), `POST /raahat/alerts/{id}/attest` (Cedar `attest_impact`). Pradhan: `POST /raahat/receipts` (Cedar `record_receipt`, own village) | `infra/template.yaml` public route list, `docs/CONTRACT.md` |
| `policy/base.cedar` | New actions: `release_relief` (officer, never a public judge account on a live alert — same guard as `deliver`), `attest_impact` (officer any village; pradhan own village), `record_receipt` (pradhan own village), `view_ledger` (everyone) | audit log unchanged |
| `infra/template.yaml` | `RAAHAT_RPC_URL`, `RAAHAT_CHAIN_ID`, contract addresses as parameters; SSM read permission for the signer key on the workflow + api roles only; a `RaahatTxFailed` alarm | `tests/test_template_safety.py` must pass (no `*`, nothing hourly) |

Telegram: after a `Released` event, the delivery module sends each registered recipient of that village: *"पुकार राहत: {village} के हर घर के लिए ₹{amount} जारी। {agent} से लें। रसीद: {short link}"* — only for live alerts; replays go to the stub channel like every other message.

### 2.4 Frontend (`frontend/src/`)

| Page / component | What it shows |
|---|---|
| `pages/Raahat.tsx` (`/raahat`, public, Hindi-first) | **The relief ledger.** Top: pool balance, rule (plain words: "चेतावनी पर ₹X हर घर, पुष्टि पर ₹Y"), sealed-since date, donors count. Then a timeline per alert: Forecast → Alert anchored (tx) → मिल गया {acked}/{delivered} → Attestations (3 chips: प्रधान / अधिकारी / उपग्रह) → Released tier 1 / tier 2 (tx, total) → Receipts {n}/{households}. Every tx is a BaseScan link. REPLAY banner reused from `components/LivePill` / `PageBand` |
| `components/ChainReceipt.tsx` | A small card: hash, block, time, explorer link, "re-verify" button that fetches the CAP XML and re-hashes it in the browser (judges love this — it proves the anchor without trusting us) |
| `pages/VillagePage.tsx` | New section "राहत": this village's rule, last release, receipts progress |
| `pages/console/Relief.tsx` | Officer: pending releases (eligible alerts with tier + amount + why), one-tap **Release** (same `ConfirmDialog` as approvals), attest impact (severity + photo hash from the report), pool health |
| `pages/console/Receipts.tsx` | Pradhan: list of households (salted ids + first name only, never phone), enter UPI/cash-out reference → signed receipt |
| `pages/Landing.tsx` | One new counter: "राहत पहुँची: ₹X / {households} घर" + a line in the story strip |
| `pages/How.tsx` | A "Where the money goes" diagram (the ASCII above, drawn) |
| `lib/chain.ts` | viem public client, read-only; `verifyCapHash(uri, onChainHash)`; explorer URL helper |

Rules: no wallet connect for villagers or officers (officers sign in with Cognito; the backend signs). Donor "fund the pool" is a wallet action — use a plain `viem` `walletClient` on the `/raahat` page behind a "I am a donor" disclosure; no RainbowKit theme noise. Keep the 129 kB report-page budget untouched (`/raahat` is a separate chunk).

### 2.5 Tests (the thing that makes "solution quality" 25% real)

- `contracts/test/*.t.sol` (Foundry): roles, write-once anchor, 2-of-3 logic (same attester twice ≠ 2), rule sealing, cooldown, Merkle receipt (valid, replayed, wrong village), exercise flag, reentrancy, fuzz on amounts. Target: 100% line coverage on the three contracts; print it in README.
- `backend/tests/test_raahat_*.py`: chain client with a scripted web3 (no network) — tx built right, failure never propagates to the alert path, indexer checkpoints; Cedar: pradhan refused on other village, judge account refused on live; households Merkle root deterministic; attestation severity from pixel fraction.
- `backend/tests/test_template_safety.py`: extend — only workflow + api roles may read the signer parameter; alarm exists.
- `frontend/src/lib/chain.test.ts`: `verifyCapHash` on a fixture; ledger timeline from fixture events; Hindi strings present.
- `scripts/smoke.mjs`: + `/raahat/pool` and `/raahat/ledger` return 200 and link to a real tx.
- Playwright + axe on `/raahat`: 0 violations (keep the badge honest).

---

## 3. Build order (do it in this order; each step leaves the stack deployable)

### Step 0 — Scaffold (½ day)
- `contracts/` with Foundry (`forge init --no-git`), OZ 5, `TestINR.sol`, deploy script `script/Deploy.s.sol` writing addresses to `contracts/deployments/base-sepolia.json`.
- `backend/src/Pukaar/raahat/__init__.py`, `chain.py` with read-only functions first; `web3>=7` added to `pyproject.toml`.
- `frontend/src/lib/chain.ts` with viem; `/raahat` route that renders the pool read from chain.
- Makefile: `make raahat-deploy`, `make raahat-fund`, `make raahat-seed-households`, `make raahat-anvil` (local chain for tests and local mode).
- Local mode (`core/local.py`) runs against anvil so `make dev` still needs no AWS and no testnet.

### Step 1 — Anchor (½ day)
- `AlertRegistry` + tests → deploy.
- Hook `anchor_alert` after first successful delivery; `anchor_outcome` in `step_close`.
- `ChainReceipt` card on the alert view in the console and on the village page.
- **Checkpoint demo:** start replay → alert approved → BaseScan shows `AlertAnchored` with `exercise=true`; "re-verify" re-hashes the CAP XML in the browser and matches.

### Step 2 — Rule + anticipatory release (1 day)
- `ReliefPool` + `TestINR` + tests → deploy; `sealRules()` with: anticipatory at Warning ₹1,500/household, confirmed ₹4,000/household, cooldown 72 h (numbers are illustrative; write "illustrative, SDRF norms to be mapped with DDMA" everywhere they appear).
- Households: Merkle root per village from recipients (salted), `make raahat-seed-households`.
- Cedar `release_relief`; console `Relief.tsx`; `POST /raahat/alerts/{id}/release`.
- Telegram relief message (live only).
- **Checkpoint demo:** Sujanpur hits Critical in replay → console shows "Release tier 1: 42 households × ₹1,500" → one tap → `Released` event → `/raahat` timeline updates via AppSync (publish a `raahat` event on the public namespace: ids and amounts only).

### Step 3 — Attestation + confirmed release (1 day)
- `ImpactAttestation` + tests → deploy.
- Satellite attester from the existing Sentinel-2 diff; officer attest from console; pradhan attest from a verified photo report (hash of the S3 object).
- Confirmed → tier 2 release eligible → same approval flow.
- Receipts: pradhan enters UPI ref → `receipt()` with Merkle proof → `PayoutReceipt`.
- **Checkpoint demo:** three chips turn green, tier 2 releases, receipts fill 0 → n.

### Step 4 — Ledger, indexer, polish (1 day)
- `indexer.py` in the sweep; `/raahat` reads cached rows, falls back to RPC.
- Landing counter, How diagram, village section.
- axe pass, i18n (`i18n.ts`) for every new string, cheap-phone check on `/raahat` (no 3D).
- README section "Raahat: where the money goes" + the real/replay/simulated/planned table + contract addresses + coverage badge.

### Step 5 — Submission assets (½ day, before 25 Oct 05:30 IST)
- DoraHacks BUIDL (see §5).
- 3-minute demo video (see §4). Re-use the Chatterbox TTS narration pipeline in `video/`.
- `docs/submission/w3sg-writeup.md`.

If time runs out before 25 Oct: **ship Steps 0–2 as Tech Track** (anchor + anticipatory release is already the novel part) and put Step 3 under "Planned, 5–25 Nov refinement window". The hackathon explicitly gives finalists Nov 5–25 to refine with mentors; use it for attestation and receipts.

---

## 4. Demo script (3:00, recorded on the deployed stack during a labelled replay)

| Time | Screen | Narration (English; Hindi captions) |
|---|---|---|
| 0:00–0:20 | Pitch poster → Mandi 2025 headline → Syathi dog story (existing footage) | "On 1 July 2025 a cloudburst hit Mandi. In Syathi, a dog woke the village. No warning reached them. And when relief came, nobody could see where it went." |
| 0:20–0:45 | `/live` map, 3D, Sujanpur | "Pukaar is live on AWS for five villages. Every 15 minutes, code — not a model — turns forecasts into a level. Tonight we replay July 2023." |
| 0:45–1:10 | Console: alert pending → Listen (Polly Hindi plays) → Approve | "An officer approves in one tap. Polly speaks it in Hindi. Every phone taps 'मिल गया'." |
| 1:10–1:30 | BaseScan tab: `AlertAnchored`, exercise=true; `/raahat` re-verify button hashes the CAP XML live | "The moment the warning goes out, its CAP record is anchored on a public chain. Anyone can re-hash the official feed and check. Nobody can say later that no warning was issued." |
| 1:30–2:00 | Console → Relief: "Tier 1 · 42 घर × ₹1,500 · rule sealed 1 June" → Release → `/raahat` timeline fills | "This is the part that is new. The relief rule was written and sealed before the monsoon. When Sujanpur reaches Warning on the forecast — before the water — the officer releases the anticipatory tranche. In Bangladesh, $53 a week before the flood made families 52% less likely to go a day without eating." |
| 2:00–2:30 | Three attestation chips: प्रधान photo → अधिकारी → उपग्रह (Sentinel-2 before/after) → Confirmed → Tier 2 → receipts counter fills | "After the flood, three independent parties confirm it: the pradhan, the district officer, and the satellite. Two of three unlocks the second tranche. Each household's receipt is public, each household's identity is not." |
| 2:30–2:50 | `/raahat` full ledger, donor view, Landing counter | "A donor, a journalist or a villager sees the same ledger: forecast, warning, who heard it, who confirmed, who was paid. No wallet, no app, no account for the villager." |
| 2:50–3:00 | Real/replay/simulated table, team, 112 | "Testnet today. The loop is live. Pukaar Raahat: the call that reaches the village before the river — and the help that does too." |

Record with `video/` tooling; captions in Hindi and English; the Polly clip is the real one.

---

## 5. Submission (DoraHacks BUIDL fields)

- **Name:** Pukaar Raahat (पुकार राहत)
- **Tagline:** Flood warning that pays the household before the river rises — forecast-triggered anticipatory relief with a public, sealed rule.
- **Track:** Tech Track (prototype + repo + demo). Mention Idea Track eligibility is moot since it is built.
- **Tags:** Web3, Social Impact, Sustainability, AI, Decentralized Identity (household hashes / attester roles), DAPP
- **Vision (≤ 2 lines):** Early warning saves lives; early cash saves livelihoods. Raahat makes both auditable by the people they are for.
- **Problem:** README §The problem, trimmed to 120 words, + one paragraph on relief opacity and delay (cite HP PDNA; avoid unverified leakage percentages).
- **Solution:** §1.1 three points.
- **Why Web3 adds meaningful value (their exact question):** (1) a rule sealed before the hazard that no office can amend after it; (2) three independent attesters, none of whom runs the ledger; (3) receipts a donor and a villager can both verify without trusting the operator. Say plainly what the chain does *not* do: it does not forecast, decide the level, or hold personal data.
- **Beneficiaries:** five villages today (Thunag, Janjehli, Gohar, Pandoh in Mandi; Sujanpur in Hamirpur), ~N registered households; Himachal's 9.45M mobile subscribers; any CAP-speaking authority.
- **Impact potential:** the WFP numbers; the 10× early-warning return; the UN Early Warnings for All 2027 target.
- **Feasibility:** live since 11 Oct 2026; one new module; cash-out through existing BC/pradhan/UPI; SDRF mapping and INR rail named as the two partner dependencies.
- **Links:** repo (this branch), live site, `/raahat`, BaseScan contract addresses, demo video, pitch deck PDF (10 slides, same story as the video), CAP feed.
- **Team:** as README (Prashant Bahuguna, Prashant Thakur, Puneet Yadav) — confirm who submits; DoraHacks ties the BUIDL to one account.

---

## 6. Judging-criteria checklist (tick before submitting)

- [ ] **Impact 30%** — sourced numbers in README, video and BUIDL; a real bot anyone can `/start gohar`; back-test shown with its miss (2025) stated.
- [ ] **Quality 25%** — contracts 100% covered, backend tests green (`make test`), live smoke includes `/raahat`, axe 0 on `/raahat`, template safety extended.
- [ ] **Web3 20%** — one-sentence "why chain" on the landing page and in the first 90 s of the video; no token/DAO/NFT anywhere; real/replay/simulated table.
- [ ] **Feasibility 15%** — "Planned" rows name the partner and the step; costs section updated (testnet = ₹0; mainnet gas estimate per alert).
- [ ] **Pitch 10%** — 3:00 video, Hindi captions, Polly voice real, explorer visible on screen; 10-slide PDF.

---

## 7. Risks and how we pre-empt them

| Risk | Mitigation |
|---|---|
| Judge: "a database could do this" | The sealed rule + three attesters who don't run the ledger + public re-verify button. Say it in the first minute. |
| Judge: "who pays gas / who runs the oracle" | Backend signer is the issuing authority (DDMA) in production; gas per alert on Base ≈ cents; we show the number. Oracle is one of three attesters, never alone sufficient. |
| Judge: "privacy of villagers" | Nothing personal on chain; household = salted hash; receipts show first name only off-chain (Cedar); same discipline as the after-action report. |
| Judge: "anticipatory payouts on a wrong forecast" | Cite the 2025 miss; anticipatory tier is small, cooldown-limited, and released by a human; the evidence (WFP) says the cost of a false positive is far below the cost of a late payment. |
| Chain/RPC down during the live demo | Pre-record the video; in a live Q&A, the ledger reads from the DynamoDB cache and shows "chain read failed, showing cached" (honest). |
| Faucet empty | Fund the signer and the pool two days early; keep 0.2 ETH-equivalent on two chains. |
| Scope creep | Steps 0–2 are the submission. 3–4 are the refinement window. Nothing else. |

---

## 8. Open decisions (owner decides before Step 0)

1. **Chain:** Base Sepolia (default) vs Arbitrum Sepolia vs Polygon Amoy — pick by faucet reliability on 23 Oct.
2. **Illustrative amounts:** ₹1,500 / ₹4,000 per household, 72 h cooldown — or map to published SDRF ex-gratia norms if findable with a source.
3. **Who submits on DoraHacks** and whether the repo link is this branch URL or a fork named `pukaar-raahat`.
4. **Pitch deck:** 10 slides, same story — build after the video.

---

## 9. Sources to cite (keep the list in `docs/submission/w3sg-sources.md`)

- Anticipatory cash, Bangladesh 2020: https://csae.web.ox.ac.uk/node/2183966 ; https://ora.ox.ac.uk/objects/uuid:12ea16b2-edc0-4af5-8824-132aba4557bd ; https://poverty-action.org/sites/default/files/2026-09/IPA-BRIEF-Anticipatory%20Action%20Brief-r5_1554.pdf ; trial registry https://www.socialscienceregistry.org/trials/6576
- Anticipation Hub evidence database: https://www.anticipation-hub.org/experience/evidence-database/evidence-list
- Oxfam UnBlocked Cash research report: https://reliefweb.int/report/vanuatu/unblocked-cash-piloting-accelerated-cash-transfer-delivery-vanuatu-research-report ; https://www.oxfam.org/en/node/16213
- WFP Building Blocks: https://www.wfp.org/building-blocks ; critique: https://davidgerard.co.uk/blockchain/2017/11/26/the-world-food-programmes-much-publicised-blockchain-has-one-participant-i-e-its-a-database/
- Hedera Africa Hackathon 2025 winners (comparables): https://www.hashgraph.swiss/news-all/2025-hedera-africa-hackathon-announces-winners-officially-becomes-the-largest-web3-hackathon-globally ; https://dorahacks.io/hackathon/hederahackafrica/winner
- Everything already cited in README.md (WMO MHEWS 2024, GCA 2019, HP PDNA 2024, Cumiskey 2015, GSMA SACHET 2025, Census 2011, TRAI 2026).
