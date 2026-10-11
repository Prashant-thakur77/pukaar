# Scoring the back-test, and a source ablation

`backend/src/Pukaar/scripts/score.py` (`python -m Pukaar.scripts.score`) asks two questions
of the back-test: did the rules warn the villages that were actually hit, and which data
source did the work? It writes `data/scores.json` (copied to `frontend/src/data/scores.json`
for the Impact page); `scripts/build_charts.py` draws `docs/charts/scores.svg` from it.

![Hits, misses and false alarms per configuration](charts/scores.svg)

## Method

The archived hours of each replay scenario (`data/replay/*`) go through the same code as
`scripts/backtest.py`: `risk_rules.assess` on each hourly reading, then the production
hysteresis (`apply_hysteresis`: rise at once, step down after three calm sweeps). No
villager reports and no gauges are used; this scores the forecast data alone.

Four configurations, each through the same hysteresis:

| Configuration | Level each hour |
| --- | --- |
| rain only | `rain_level`: IMD 24 h rain bands (64.5 / 115.6 / 204.5 mm) |
| river only | `river_level`: forecast peak discharge against the village's percentile thresholds |
| both (Pukaar) | the final `level`: the higher of the two, one level up when both reach Watch |
| both + soil | the same, with the soil-moisture modifier on the rain bands (see [below](#soil-moisture-modifier)) |

The first three always run with the soil modifier off, whatever `PUKAAR_SOIL_MODIFIER` says,
so they stay comparable with earlier scores.

Against `data/ground_truth.json`:

- **hit**: the village was hit, and Watch was reached by the end of the event day (UTC).
- **miss**: the village was hit, and Watch was not reached by then.
- **false alarm**: nothing happened in the village, and Warning was reached at any time.
- **lead hours**: event day 00:00 UTC minus the first Watch, for hits; the table shows the median.
  If Watch was already held at the first archived hour, the lead is a lower bound (marked ≥).

Villages whose truth is `uncertain` are left out of every count.

## Ground truth

Only what public reporting says, checked on 2026-10-11. Where we found no village-specific
report for the dates, the village is `uncertain`; we did not guess.

| Scenario | Village | Truth | Event day | Source |
| --- | --- | --- | --- | --- |
| Himachal, 7-11 July 2023 | Pandoh | event | 2023-07-09 | [Newslaundry, 8 Aug 2023](https://www.newslaundry.com/2023/08/08/our-lives-are-set-back-25-years-in-himachal-a-village-loses-everything-to-floods-2): Beas flood waves crossed Pandoh on 9 and 10 July |
| | Thunag | uncertain | | [Tribune video report](https://www.tribuneindia.com/news/himachal/video-scary-visuals-of-flash-flood-from-mandis-thunag-in-himachal-pradesh-cloudburst-triggers-major-landslide-in-solans-chewa-village-524420), date inside the window not confirmed |
| | Janjehli | uncertain | | none found |
| | Gohar | uncertain | | none found for Gohar itself |
| | Sujanpur | uncertain | | [Tribune](https://www.tribuneindia.com/news/himachal/28-of-five-families-rescued-in-hamipur-423690): Khairi flooding reported for June and August 2023, not 7-11 July |
| Mandi, 30 June-1 July 2025 | Thunag | event | 2025-06-30 | [Down To Earth](https://www.downtoearth.org.in/natural-disasters/cloudbursts-devastate-himachals-mandi-at-least-10-dead-34-missing-after-1900-excess-rain-on-july-1): over 150 homes and shops in Thunag market destroyed |
| | Gohar | event | 2025-06-30 | same: 5 deaths in Gohar subdivision (subdivision level) |
| | Janjehli | event | 2025-06-30 | same: all of Seraj hit, about 10% of the Chail-Janjheli road destroyed |
| | Pandoh | uncertain | | none found |
| | Sujanpur | uncertain | | none found (Hamirpur district) |

## Results

| Scenario | Configuration | Hits | Misses | False alarms | Median lead |
| --- | --- | --- | --- | --- | --- |
| Himachal 2023 (1 village scored) | rain only | 1 | 0 | n/a | 19 h |
| | river only | 1 | 0 | n/a | ≥ 48 h |
| | both (Pukaar) | 1 | 0 | n/a | ≥ 48 h |
| | both + soil | 1 | 0 | n/a | ≥ 48 h |
| Mandi 2025 (3 villages scored) | rain only | 0 | 3 | n/a | - |
| | river only | 0 | 3 | n/a | - |
| | both (Pukaar) | 0 | 3 | n/a | - |
| | both + soil | 0 | 3 | n/a | - |

Read plainly: 1 hit and 3 misses out of 4 scored village-events. In July 2023 the river
forecast flagged Pandoh from the first archived hour, at least 48 hours before the flood
reached it; rain alone flagged it 19 hours before. Combining the sources never did worse
than the better single source here. The 2025 cloudburst was missed by every configuration:
no archived forecast crossed a threshold for the three villages that were hit. That is the
gap a verified villager report is meant to fill.

## Soil moisture modifier

**Why.** The same rain on wet ground does more damage. Antecedent rainfall and soil moisture
condition Himalayan landslides and flash floods: in Darjeeling, 20-day antecedent rainfall gave
the best-fitting landslide thresholds; NASA's LHASA v2 uses SMAP antecedent soil moisture; and
the 2023 monsoon set off thousands of landslides in Mandi and Kullu after weeks of rain.

**What it does** (`services/soil.py`, applied in `risk_rules.assess`):

- The sweep reads root-zone soil moisture from the same Open-Meteo forecast request as the rain
  (no extra call): the mean of the `soil_moisture_9_to_27cm` and `soil_moisture_27_to_81cm`
  layers at the current hour. The top layers (0-1, 1-3, 3-9 cm) swing with every shower; the root
  zone is what stays wet after days of rain, which is the antecedent state.
- Saturation `S = clip((sm - dry) / (wet - dry), 0, 1)`, where `dry` and `wet` are the village's own
  5th and 95th percentiles over two years of hourly values (2024-2025, Open-Meteo
  historical-forecast API, the same layers and model family the sweep reads;
  `python -m Pukaar.scripts.calibrate --soil`, stored as `soil: {dry, wet}` in
  `data/thresholds.json`). The ERA5-Land archive API was not used because it reports different
  layers (7-28 and 28-100 cm). If a village has no calibrated range, 0.15 / 0.45 m³/m³ is used and
  the page says so.
- When `S >= 0.8`, the IMD rain bands are multiplied by `1 - 0.3 × (S - 0.8) / 0.2`: at most 30%
  lower at full saturation, never below 70% of IMD (rounded up to 0.1 mm). The rule
  `soil_saturated:S=0.92:bands x0.82` goes into `rules_fired`, and the soil reading, `S`, the factor
  and the state go into the decision trace. Soil only moves the rain bands: it never raises a level
  on its own, and it is not counted as an independent source for "two sources agree".
- Behind `PUKAAR_SOIL_MODIFIER` (default **off**, see the decision below).

**Calibrated ranges** (m³/m³, root zone): Thunag 0.236-0.406, Janjehli 0.245-0.407, Gohar and
Pandoh 0.169-0.339 (same model cell), Sujanpur 0.142-0.336.

**Archived soil for the replays.** `python -m Pukaar.scripts.fetch_replay --soil` writes
`data/replay/<scenario>/soil.json` (about 5 KB each): one root-zone value per hour from the
historical-forecast API, beside the existing rain and river files.

**Result** (`python -m Pukaar.scripts.score --soil`; per-village detail in `data/scores.json`
under `soil_effect`):

| Scenario | Village | Truth | Max S | Hours S ≥ 0.8 | First Watch, off → on | First Warning, off → on | Hours at Warning or above, off → on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Himachal 2023 | Pandoh | event | 0.89 | 36 | 7 Jul 00:00 → same | 8 Jul 05:00 → same | 39 → 45 |
| | Thunag | uncertain | 1.00 | 63 | 8 Jul 04:00 → same | none → **9 Jul 00:00** | 0 → 11 |
| | Janjehli | uncertain | 1.00 | 97 | 11 Jul 00:00 → **8 Jul 09:00** | none → none | 0 → 0 |
| | Gohar | uncertain | 0.89 | 36 | 8 Jul 00:00 → same | 8 Jul 05:00 → same | 39 → 45 |
| | Sujanpur | uncertain | 0.89 | 23 | 7 Jul 00:00 → same | 7 Jul 00:00 → same | 97 → 97 |
| Mandi 2025 | Thunag | event | 0.67 | 0 | none → none | none → none | 0 → 0 |
| | Janjehli | event | 0.65 | 0 | none → none | none → none | 0 → 0 |
| | Gohar | event | 0.37 | 0 | none → none | none → none | 0 → 0 |
| | Pandoh, Sujanpur | uncertain | ≤ 0.50 | 0 | unchanged | unchanged | unchanged |

Times are UTC. Read plainly:

- **Scored outcomes do not change.** Pandoh 2023 was already a hit with at least 48 h of lead;
  the three villages hit in 2025 are still missed.
- **2025: the modifier never switched on.** The root zone before the 30 June cloudbursts was only
  moderately wet (S at most 0.67, early in the monsoon), and the archived rain forecast for the
  three villages that were hit stayed far below any band (at most 33 mm in 24 h). Soil moisture
  cannot rescue a cloudburst that the rain forecast does not see.
- **2023: the soil was saturated and the modifier did act**, all of it on villages whose outcome
  we could not verify. It raised Thunag to Warning for the first time (11 hours) and brought
  Janjehli's first Watch 2.6 days earlier; Gohar and Pandoh held Warning 6 hours longer.
  Mandi district was hit hard on 9-11 July 2023, so these may well be correct, but we cannot show
  that, and if Thunag stayed quiet that is one new false alarm.

**Decision: default off.** The rule we set was "on by default only if the back-test shows it adds
no false alarms". It cannot show that: no village is verified as quiet, so false alarms are not
countable, and the only place it changed a Warning is an unverified village. It also added no hit.
The modifier ships, is tested, appears in every trace and on the village page ("if it were on:
rain bands × 0.82"), and can be switched on with `PUKAAR_SOIL_MODIFIER=true`. Revisit when a quiet
village is verified for a wet spell, or when more events are scored.

**Limits of this test.** Soil moisture here is a model state (the forecast models' land surface),
not a measurement such as SMAP. The calibration window (2024-2025) contains the 2025 scenario, so
2025 is in-sample for the range; 2023 is out of sample. The replay uses the archived value at each
hour, which is closer to an analysis than to what a live forecast would have shown.

## Limitations

- **Tiny sample.** Two events, four scored villages. These are counts, not rates.
- **No false-alarm rate yet.** No village is verified as "nothing happened", because an
  absence of reports is not evidence of no damage. Until one is, false alarms are n/a.
- **Archived forecasts are reanalyses.** The historical-forecast and flood archives were
  assembled later; a live system would have seen noisier inputs, so the hit and lead
  numbers are optimistic.
- **Coarse truth.** Some entries are subdivision level (Gohar 2025) or constituency level
  (Janjehli 2025), and the event day is a UTC date, not an hour.
- **Window start.** Pandoh 2023 was already at Watch at the first archived hour, so its lead
  is censored; a longer archive could show a longer or a shorter lead.
- **Forecast data only.** Villager reports and gauges are not in the replay archive, so
  this does not score the full system.
