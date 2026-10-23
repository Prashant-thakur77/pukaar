# Pukaar Raahat film: storyboard

Written before the render. The film is `node video/record.mjs raahat` from `video/raahat.mjs` (scene list, narration, cues), staged by `node video/raahat-live.mjs`. Target: under 3:00, 1920×1080, English narration (Chatterbox, built-in synthetic voice), word-by-word captions, an original score from `video/narration/score.py`, −14 LUFS.

The film tells one story: a flood that nobody warned about, money that came late and couldn't be traced, then the same kind of flood played through Raahat on the live stack. The demo half is one continuous take of a single alert (Pandoh, July 2023 replay) moving through every step on AWS and Base Sepolia, in the order it happens. Every number is read at render time from the stack, the chain or the repo, and a missing number fails the render.

Judging lens (DoraHacks, Web3 for Social Good): impact (the evidence card and the village story), use of web3 that earns its place (the "why a chain" card and the four chain properties shown working), working product (all live scenes are the deployed stack and a public testnet), honesty (labels on screen throughout, and a "not real yet" card).

## Rules on screen

- The replay is labelled the whole time: the REPLAY banner and chip in the app, and "exercise" on chain (`isExercise` is read out in the proof scene).
- Each scene that shows money carries "tINR has no value" and "illustrative, SDRF norms to be mapped with DDMA", either on an overlay card or on the app's own caveat line.
- Only demo accounts are shown. Households appear only as labels and hashes, and the UPI references typed on camera are labelled as demo references.

## Scenes

Times come from the `--plan` pass (Chatterbox takes, Whisper-checked). The render rewrites them exactly in `docs/submission/w3sg-film-script.md`.

| # | Time | Scene | On screen | Narration | Sound |
|---|---|---|---|---|---|
| 1 | 0:00 | hook | Kinetic type on night blue; marigold on "dog", "No warning", "see where it goes"; wordmark पुकार राहत | "In 2025, a dog woke a Himalayan village at midnight. No warning reached them. And when relief comes, nobody can see where it goes. This is Pukaar Raahat." | Tense pulse; riser into a half-second drop, then a hit on the wordmark |
| 2 | ~0:12 | problem | Pexels footage: storm time-lapse over ridges, river in flood, landslide scar | Mandi, 30 June 2025: at least 10 dead, 34 missing (README, Down To Earth). "Relief is paid after the water, and the village can't check who got it." | Sombre piano and pad; whoosh in |
| 3 | ~0:23 | evidence | Three numbers count up: $53, 23,000+, 52% | WFP / Oxford CSAE, Bangladesh 2020: money a week before the peak; 52% less likely to go a day without eating | Hope: the pad opens to D major; hit as 52% lands |
| 4 | ~0:38 | turn | Wordmark, one-liner, three people (officer, pradhan, anyone) | "Today, Pukaar warns villages… Raahat adds the money: released before the river, on a sealed rule, every rupee on a public chain." | The drive starts at 112 bpm with a hit |
| 5 | ~0:48 | rule | Live `/raahat`: the pool checked by the browser, then the rule card zoomed and boxed | ₹1,500 at Warning, ₹4,000 once the flood is confirmed, 72 h cooldown; "sealed… not even us" | Drive |
| 6 | ~1:02 | approve | Officer console (hero overlay), Pandoh's Hindi draft boxed, Approve and confirm | "Now July 2023, replayed… Pandoh reaches Warning…" | Drive; the click lands on a beat |
| 7 | ~1:11 | anchor | `/raahat?alert=…`: chain receipt with the exercise chip; Re-verify pressed, green match | "anchored on Base… hashes it in your browser. It matches." | Drive |
| 8 | ~1:19 | tier1 | Console Release relief: "Tier 1 · 30 households × ₹1,500"; Release, confirm, Released + tx | "Code checks the sealed rule… One tap releases tier one, before the water… The contract checks the rule again, and pays." | Drive |
| 9 | ~1:31 | pradhan | Pradhan console (demo account): "Flood confirmation (2 of 3)", photo report chosen, Send | "three independent keys… the pradhan attests first, from a verified photo" | Build: fuller arpeggio |
| 10 | ~1:39 | officer | Officer types a note, Attest as officer; chips go green, "Confirmed"; satellite check starts | "Two of three agree: the flood is confirmed. And the satellite adds a third." | Build |
| 11 | ~1:40 | sat | Sentinel-2 before (3 June) and after (23 July) as served by the live site; 2.07 → 4.10 km² over 317.7 km²; Severity 3; evidence hash | Read from `data/raahat/satellite_2023.json` | Build; hit on the card |
| 12 | ~1:58 | tier2 | Console: tier 2 released | "Confirmation unlocks tier two: ₹4,000 for each household. The contract checks the three keys itself." | Build |
| 13 | ~2:06 | receipts | Pradhan types a demo UPI reference, Record receipt; the row is boxed | "On chain, it's a receipt for a hashed household: no name, no phone number." | Build |
| 14 | ~2:14 | ledger | Public `/raahat` signed out: Pandoh's row, every step with its link | "It all lands on one public page…" | Build |
| 15 | ~2:19 | explorer | Blockscout: tier 1's transaction (success, the tINR transfer) | "Anyone can open every transaction: no wallet, no account." | Build |
| 16 | ~2:24 | why | Four ticks: sealed rule, 2 of 3 keys, public receipts, warnings never wait | "Why a chain?…" | The drive returns |
| 17 | ~2:33 | proof | Terminal: `cast call` output read when the scene is recorded: rulesSealed, isExercise, isConfirmed / attesterCount, released / receiptCount | "Read from Base Sepolia right now… 53 contract tests, full coverage." | Drive |
| 18 | ~2:43 | honest | Three gaps → what would replace each | Test token, illustrative amounts, custodial testnet keys | Reflect: drums out |
| 19 | ~2:50 | close | "The river will still rise. Now help reaches first." Wordmark, live URL, repo | Same | Resolve and swell; music alone for the last ~3 s |

## Order of real actions (one take)

`raahat-live.mjs`: reset the demo and the exercise cooldowns, start the replay, file the DEMO photo, wait for Pandoh's pending Warning. Then each scene's off-camera `prepare` waits for the previous step to be on chain before it records:

approve → (anchor sent) → Re-verify → tier 1 → (tier 1 mined) → pradhan attests → (on chain) → officer attests, satellite → (confirmed, satellite on chain) → tier 2 → (mined) → receipt → ledger, explorer, proof.

A full run spends 30 × (₹1,500 + ₹4,000) = 165,000 tINR from the pool; the staging script refuses to start if the pool can't cover it.

## Checks after the render

Whisper word match ≥ 0.95 on the final mix, −14 LUFS integrated and ≤ −1.5 dBTP, a contact sheet, phone-size readability (frames at 360 px wide), the .srt, a 720p copy, and the YouTube title, description and thumbnail.
