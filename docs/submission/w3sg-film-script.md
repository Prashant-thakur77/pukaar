# Pukaar Raahat film script (2:48)

The narration of [docs/media/pukaar-raahat.mp4](../media/pukaar-raahat.mp4) (168.1 s, 1920×1080), rendered by `node video/record.mjs raahat` from [video/raahat.mjs](../../video/raahat.mjs) after `node video/raahat-live.mjs` staged the stack; this file is written by the same run, so the times and words below are the film's own. Timed captions: [pukaar-raahat.srt](../media/pukaar-raahat.srt).

Every number is read at render time: the rule's amounts and cooldown from the live API (the sealed rule on chain), Pandoh's household count from ReliefPool on Base Sepolia, the WFP figures from w3sg-sources.md, the Mandi 2025 figures and the Foundry test count from README.md, the satellite figures from data/raahat/satellite_2023.json, and the proof scene's output from `cast` against Base Sepolia when that scene was recorded. The live scenes are the deployed stack during a labelled replay (exercise=true on chain); tINR is a test token with no value, and every amount is illustrative, SDRF norms to be mapped with DDMA. The voice is Chatterbox TTS (open source) with its own built-in synthetic voice. 460 words in 168 s (164 words a minute).

## Chapters

```
0:00 The problem
0:34 What Raahat does
0:43 One flood, end to end
1:23 Three keys confirm the flood
2:06 The public ledger
2:14 Why a chain
2:33 Limits and close
```

## Video description

```
Pukaar Raahat (पुकार राहत): flood relief that reaches a Himalayan village before the river does, on a rule anyone can check. Pukaar's warning loop runs on AWS; Raahat anchors each alert on Base, releases relief on a rule sealed before the monsoon, confirms the flood with two of three independent keys (pradhan, officer, Sentinel-2) and records each household's receipt without personal data.

Testnet demo: tINR is a test token with no value; amounts are illustrative, SDRF norms to be mapped with DDMA. The flood shown is a labelled replay of July 2023.

Live: https://main.d227ld968f3fok.amplifyapp.com/raahat
Code: https://github.com/Prashant-thakur77/pukaar (branch web3-social-good)

0:00 The problem
0:34 What Raahat does
0:43 One flood, end to end
1:23 Three keys confirm the flood
2:06 The public ledger
2:14 Why a chain
2:33 Limits and close

Voice: Chatterbox TTS (open source) with its built-in synthetic voice.
Music and sound effects: synthesised for this video by video/narration/score.py and sfx.py (CC0). Stock footage: Pexels (Pexels License), credits in docs/media/CREDITS.md.
```

## 0:00 to 0:10 · Pukaar Raahat

Screen: Kinetic type on night blue, each phrase landing as it is said, key words in marigold, then the wordmark पुकार राहत.

> In 2025, a dog woke a Himalayan village at midnight. No warning reached them.
>
> And when relief comes, nobody can see where it goes.
>
> This is Pukaar Raahat.

## 0:10 to 0:20 · The problem

Screen: Stock footage (Pexels License; credits in docs/media/CREDITS.md): storm clouds over Himalayan ridges, a river in flood, a landslide.

> On the night of 30 June 2025, cloudbursts hit Mandi district: at least 10 dead, 34 missing.
>
> Relief is paid after the water, and the village can't check who got it.

## 0:20 to 0:34 · The evidence

Screen: Three numbers count up as they are said: the WFP / Oxford CSAE evaluation of anticipatory cash in the 2020 Bangladesh floods.

> Money before the water works.
>
> In Bangladesh in 2020, the World Food Programme sent $53 by mobile money, about a week before the flood peaked, to over 23,000 households.
>
> They were 52% less likely to go a day without eating.

## 0:34 to 0:43 · Pukaar Raahat

Screen: The wordmark, the one-liner and the three people in the loop, appearing as they are said.

> Today, Pukaar warns villages before a flood, live on AWS.
>
> Raahat adds the money: released before the river, on a sealed rule, every rupee on a public chain.

## 0:43 to 0:55 · The sealed rule

Screen: /raahat on the deployed site: the pool, checked by the browser against base-sepolia, and the rule card, sealed on 2026-10-22.

> The rule is set before the monsoon: at Warning, ₹1,500 per household; once the flood is confirmed, ₹4,000 more; then a 72-hour cooldown.
>
> Then it's sealed on chain. Nobody can change it mid-flood, not even us.

## 0:55 to 1:04 · Officer console

Screen: The officer console (Cognito, demo account) during a labelled replay of the July 2023 Beas flood: Pandoh's pending Warning, its Hindi draft, Approve.

> Now July 2023, replayed on the deployed stack, labelled as an exercise.
>
> Pandoh reaches Warning. The officer approves the Hindi alert in one tap.

## 1:04 to 1:11 · Anchored on chain

Screen: /raahat?alert=… on the deployed site: Pandoh's ledger row with the REPLAY chip and its chain receipt (exercise=true); Re-verify fetches the public CAP feed and hashes it in the browser.

> As it goes out, the alert is anchored on Base.
>
> Re-verify fetches the public alert feed and hashes it in your browser. It matches.

## 1:11 to 1:23 · Tier 1 · before the water

Screen: The officer console's Release relief panel: Pandoh's tier 1 (households × the anticipatory amount, illustrative), Release, the confirm dialog, then Released with its transaction.

> Code checks the sealed rule: Pandoh is at Warning, 30 households registered.
>
> One tap releases tier one, before the water: 30 times ₹1,500.
>
> The contract checks the rule again, and pays.

## 1:23 to 1:31 · Pradhan attests

Screen: The console signed in as Pandoh's pradhan (demo account): Flood confirmation (2 of 3), attesting from a verified photo report (a labelled DEMO photo filed for the replay).

> After the flood, three independent keys can confirm it.
>
> Pandoh's pradhan attests first, from a verified photo of the village.

## 1:31 to 1:39 · Officer and satellite attest

Screen: The officer console: the officer attests severity 2 with a short note, the chips turn green, "Confirmed", then Run the satellite check (Sentinel-2).

> The district officer attests, severity two.
>
> Two of three agree: the flood is confirmed.
>
> And the satellite adds a third.

## 1:39 to 1:50 · Satellite evidence

Screen: Sentinel-2 before and after over the Beas around Pandoh dam (AWS Open Data), as served by the live site; the water measured, the severity, and the evidence hash put on chain (keccak256 of the public after-flood water-mask PNG).

> Sentinel-2 images of the river, before and after: water went from 2.07 to 4.10 square kilometres.
>
> Severity three. The image's hash goes on chain, so anyone can check it.

## 1:50 to 1:58 · Tier 2 · confirmed

Screen: The officer console: three green attestation chips, Confirmed, and tier 2 released.

> Confirmation unlocks tier two: ₹4,000 for each household.
>
> The contract checks the three keys itself.

## 1:58 to 2:06 · Receipts

Screen: The pradhan's console: the household list (labels and hashes only), a demo UPI reference typed in, Record receipt, Receipt recorded.

> The pradhan records each payment's UPI reference.
>
> On chain, it's a receipt for a hashed household: no name, no phone number.

## 2:06 to 2:11 · Public ledger

Screen: /raahat on the deployed site, signed out: Pandoh's row (REPLAY) with every step and its transaction links, and the totals kept apart for live and replay.

> It all lands on one public page: the alert, both tranches, three confirmations, the receipts.

## 2:11 to 2:14 · Public explorer

Screen: Tier 1's release transaction on Blockscout (an independent public explorer for Base Sepolia): success, the ReliefPool call and the tINR token transfer.

> Anyone can open every transaction: no wallet, no account.

## 2:14 to 2:23 · Why a chain

Screen: Four reasons, each landing as it is said.

> Why a chain? A rule nobody can quietly change, a confirmation no one person controls, receipts anyone can audit.
>
> And if the chain is down, the warning still goes out.

## 2:23 to 2:33 · Live proof

Screen: Real output of cast (Foundry) against base-sepolia, captured when this scene was recorded: the rule sealed, the alert marked exercise, the flood confirmed by three attesters, both tranches released, the receipts.

> Read from Base Sepolia right now: the rule sealed, the alert marked as an exercise, three attesters, both tranches, the receipt.
>
> 53 contract tests, full coverage.

## 2:33 to 2:41 · Not real yet

Screen: Three honest limits, each with what would replace it.

> What's not real yet: the money is a test token.
>
> The amounts await the state's relief norms, and our server holds the testnet keys.

## 2:41 to 2:48 · Pukaar Raahat

Screen: End card: the callback line, the wordmark, the live URL, the repository and what it runs on.

> The river will still rise. Now help reaches first.
