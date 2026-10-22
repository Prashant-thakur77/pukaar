# Pukaar Raahat: 3-minute demo script

Recorded on the deployed stack (`pukaar-raahat`, Base Sepolia) during a labelled replay of the July 2023 Beas flood. Narration in English with Hindi captions; the Hindi alert voice is the real Amazon Polly clip. Re-use the narration pipeline in `video/` (stage the screens live first, then render).

## Before recording

1. `make reset-demo STAGE=raahat`, then sign in to the console as `officer1`.
2. Check `/raahat`: the pool shows its balance, the rule card says "sealed", and the browser check line is green.
3. Open BaseScan on the AlertRegistry and ReliefPool addresses in two tabs.
4. Start the replay with `speed_seconds_per_hour` at 3 so Sujanpur reaches Warning inside a minute.

## Shots

| Time | Screen | Narration (English; Hindi captions) |
|---|---|---|
| 0:00–0:20 | Mandi 2025 headline, the Syathi dog story (existing footage) | "On 1 July 2025 a cloudburst hit Mandi. In Syathi, a dog woke the village. No warning reached them. And when relief came, nobody could see where it went." |
| 0:20–0:45 | `/live` map; Sujanpur rising; the REPLAY banner | "Pukaar is live on AWS for five villages. Every 15 minutes, code, not a model, turns forecasts into a level. Tonight we replay July 2023." |
| 0:45–1:10 | Console: the Sujanpur alert pending, Listen (Polly Hindi plays), Approve | "An officer approves in one tap. Polly speaks it in Hindi. Every phone taps मिल गया." |
| 1:10–1:30 | `/village/sujanpur`: open "Chain receipt", press Re-verify; then the BaseScan tab with `AlertAnchored` and exercise = true | "The moment the warning goes out, its CAP record is anchored on a public chain. This button fetches the official feed and hashes it in your browser. It matches. Nobody can say later that no warning was issued." |
| 1:30–2:00 | `/raahat` rule card ("sealed since …"), then Console → Release relief: "Tier 1 · 42 households × ₹1,500 = ₹63,000" → Release → confirm | "This part is new. The relief rule was written and sealed before the monsoon. When Sujanpur reaches Warning on the forecast, before the water, the officer releases the anticipatory tranche. In Bangladesh, $53 a week before the flood made families 52% less likely to go a day without eating." |
| 2:00–2:30 | `/raahat` ledger: the Sujanpur row fills (anchored → मिल गया → anticipatory relief, with the transaction); BaseScan `Released` event | "The ledger updates as it happens. Every rupee is a public transaction a donor, a journalist or a villager can open. No wallet, no app, no account for the villager." |
| 2:30–2:50 | The confirmed tier waiting on "2 of 3"; the real / replay / simulated / planned table | "After the flood, three independent parties confirm it: the pradhan, the district officer and the satellite. Two of three unlock the second tranche. The money today is a test token; the rail and the SDRF amounts need the DDMA and a licensed partner." |
| 2:50–3:00 | Team, 112 | "Pukaar Raahat: the call that reaches the village before the river, and the help that does too." |

## On-screen labels

- Every amount on screen carries "illustrative, SDRF norms to be mapped with DDMA".
- The replay banner and the REPLAY chip stay visible whenever replay data is on screen; the chain receipt shows "Exercise (exercise=true)".
- Captions say "tINR is test money with no value" the first time an amount appears.

## If something fails while recording

- Chain slow: the ledger reads from the table and the page says so; wait for the next block (2 s on Base).
- A release refused: the console shows the reason in words (for example "This village had relief recently (cooldown)"). Reset the demo and replay again; exercise cooldowns never touch live ones.
