# Scoring the back-test, and a source ablation

`backend/src/Pukaar/scripts/score.py` (`python -m Pukaar.scripts.score`) asks two questions
of the back-test: did the rules warn the villages that were actually hit, and which data
source did the work? It writes `data/scores.json` (copied to `frontend/src/data/scores.json`
for the Impact page); `scripts/build_charts.py` draws `docs/charts/scores.svg` from it.

The river trigger was rebuilt on 22 October 2026 (rules `risk-rules-v2`): a river cell chosen
for each village, return-period thresholds, the GloFAS ensemble probability, and official data
as corroboration. [The river trigger](#the-river-trigger) explains each part, and
[Results](#results) gives the scores before and after. In short: Watch days a year fell by
half to three quarters, and the one hit we had lost most of its lead time.

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
| river only | `river_level`: forecast discharge at the village's river cell against its 2-, 5- and 20-year discharges |
| both (Pukaar) | the final `level`: the higher of the two, one level up when both reach Watch |
| both + soil | the same, with the soil-moisture modifier on the rain bands (see [below](#soil-moisture-modifier)) |

The first three always run with the soil modifier off, whatever `PUKAAR_SOIL_MODIFIER` says,
so they stay comparable with earlier scores.

The replay has no archived ensemble, so the river runs in its deterministic mode here: the
archived daily discharge stands in for a perfect forecast, and the peak of today and the next
three days is compared with the thresholds. With a perfect forecast every ensemble member
would agree, so P is 0 or 1 and the ensemble rule gives the same level.

Against `data/ground_truth.json`:

- **hit**: the village was hit, and Watch was reached by the end of the event day (UTC).
- **miss**: the village was hit, and Watch was not reached by then.
- **false alarm**: nothing happened in the village, and Warning was reached at any time.
- **lead hours**: event day 00:00 UTC minus the first Watch, for hits; the table shows the median.
  If Watch was already held at the first archived hour, the lead is a lower bound (marked ≥).

Villages whose truth is `uncertain` are left out of every count.

## The river trigger

### 1. Which river cell

The Open-Meteo flood API serves GloFAS v4 on a 0.05° grid (about 5 km) and snaps a coordinate
to the nearest cell. The earlier calibration asked at each village's own coordinates, so for
Sujanpur it read a hillside cell (90th percentile 1.7 m³/s) instead of the Beas.

`python -m Pukaar.scripts.calibrate --cells` lists every cell whose centre is within 7 km of
the village, with its mean and highest daily discharge over 2015-2024, in
`data/river_cells.json`. The rule is the largest long-term mean flow within that radius. A
suggestion was accepted only when the cell drains the stream that runs through the village. Two
checks decided that:

- **OpenStreetMap waterways** within 4 km of the village (Overpass), which name the stream and
  show which way it flows.
- **The model's own routing**, inferred by mass balance from 2023-2024 daily series. Cell B is
  downstream of cell A when B's flow minus A's is never negative and is about one cell's local
  runoff. For example, the Janjehli cell drains into the Thunag cell with a residual of
  0.07 m³/s, which is Bakhli Khad as on the map.

| Village | Chosen cell | River | Verified | Why |
| --- | --- | --- | --- | --- |
| Thunag | 31.575, 77.175 (unchanged) | Bakhli Khad with Deola Nal | no | The rule's pick (31.575, 77.125; mean 3.1 m³/s) is Surah Khad, a parallel valley; Thunag's cell does not drain into it. Thunag's own cell carries the modelled Bakhli from Janjehli. It is still tiny (mean 0.6 m³/s), and the next Bakhli cell is 7.4 km downstream. |
| Janjehli | 31.525, 77.225 (unchanged) | Bakhli Khad headwaters | no | Bakhli Khad forms 30 m from the village. Every larger cell is downstream or in another valley. |
| Gohar | 31.575, 77.025 (unchanged) | Jhuni Khad with Bhurni Nala | no | The rule's pick (31.625, 77.075; 5.4 m³/s) is 4.4 m³/s modelled Bakhli Khad, 5.6 km downstream. GloFAS does not resolve the Jhuni above Gohar. |
| Pandoh | 31.675, 77.025 (one cell west; 2.8 km from the village) | Beas, below the khad confluences | yes (desk) | Beas main stem, 0.3 km away; it is the earlier cell plus the two khads (correlation 1.000). |
| Sujanpur | 31.825, 76.475 (one cell west; 3 km from the village) | Beas at Sujanpur Tira | yes (desk) | The earlier cell was a hillside (mean 0.85 m³/s). This one is the Beas (mean 232 m³/s), just below the Nyugal Khad confluence. |

"Verified" is a desk check against the map and the model, not a site visit (`cell_verified` in
`data/thresholds.json`).

**What this means.** Only two of the five villages had a wrong cell. For Thunag, Janjehli and
Gohar, the tiny cell *is* GloFAS's version of their khad. At 0.05°, the model has no larger
channel upstream of these villages. Their river signal stays weak whatever threshold is used,
and a gauge on the khad is the real fix.

### 2. Return-period thresholds

`python -m Pukaar.scripts.calibrate` takes the calendar-year maximum of the daily discharge at
the chosen cell and fits a Gumbel (EV1) distribution by the method of L-moments. GloFAS fits its
own return-period thresholds the same way. Years with fewer than 330 days of data are dropped.
The script asks for 1984-2024, but at these cells the archive has values only from 1997, so
n = 28 years.

    b0 = mean(x),  b1 = sum((i-1)/(n-1) * x_(i)) / n   (x ascending, i = 1..n)
    l2 = 2*b1 - b0,  beta = l2 / ln 2,  mu = b0 - 0.5772 * beta
    Q_T = mu - beta * ln(-ln(1 - 1/T))

Watch, Warning and Critical are the 2-, 5- and 20-year discharges. The old percentile values
are kept in `data/thresholds.json` under `percentile`, at the cell they came from. The
percentiles at the new cell are under `percentile_at_river_cell`.

| Village | Old watch / warning / critical (p90 / p97 / p99.5, old cell) | New watch / warning / critical (2 / 5 / 20 yr) | Record max (1997-2024) |
| --- | --- | --- | --- |
| Thunag | 1.14 / 1.53 / 2.10 | 1.43 / 1.97 / 2.66 | 2.85 |
| Janjehli | 1.03 / 1.36 / 1.82 | 1.28 / 1.76 / 2.37 | 2.91 |
| Gohar | 0.94 / 1.42 / 2.08 | 1.41 / 2.21 / 3.25 | 4.78 |
| Pandoh | 282 / 353 / 419 | 366 / 445 / 546 | 567 |
| Sujanpur | 1.7 / 3.2 / 4.6 (hillside cell) | 633 / 830 / 1086 | 1264 |

All values are in m³/s. The 99.5th percentile was not below the 2-year flood, as we had
suspected. At every cell it sits near the 5-year flood. The fatigue came from Watch at the 90th
percentile, which is well below the 2-year flood: GloFAS's monsoon hydrograph is a broad
seasonal hump, so p90 is crossed for weeks every year.

### 3. Ensemble probability

The live sweep asks the flood API for `ensemble=true` once a day per river cell. That gives the
control and 50 perturbed members, 51 in all, for today and three days ahead. The result is
cached for the UTC day (`services/fetch_cache.py`: in memory, and on AWS one DynamoDB item, so
a cold start does not fetch again). Rain and the deterministic discharge are still fetched
every 15 minutes.

For lead days 1-3 and each threshold, P is the share of members at or above it
(`risk_rules.exceedance_probabilities`). A level is raised when P ≥ 0.3 on any lead day, the
ECMWF reporting-point convention. `PUKAAR_RIVER_ENSEMBLE_P_MIN` changes the cut-off. The river
level is the higher of two things: today's discharge against the thresholds, and the
highest level whose P reaches the cut-off. If the deterministic forecast crosses Warning while
fewer than 30% of the members do, nothing is raised. If the ensemble is unavailable, the rule
falls back to the deterministic peak and adds `river_ensemble_unavailable` to `rules_fired`.

The decision trace carries a `river` evidence item: the cell, P per level and lead day, the
cut-off and the mode. The rule reads, for example, `river_ensemble:P(warning)=0.4>=0.3:warning`.
When the ensemble set the alert's level, CAP `certainty` comes from P: **Likely** at P ≥ 0.8
and **Possible** at P ≥ 0.3. The P value is also added as a `river_exceedance_probability`
parameter. Otherwise certainty keeps the level's default.

**Free tier.** Open-Meteo's free API is for non-commercial use only, about 10,000 calls a day.
A request counts as several calls when it asks for more than 10 variables or more than two
weeks of data. Per village per day:
- forecast rain: 96 calls;
- deterministic discharge: 96 calls;
- ensemble: one request of 51 members, about 5 calls.

That is roughly 200 calls a village a day, or about 50 villages on the free tier. **A pilot with
a district needs Open-Meteo's commercial plan** (or GloFAS through the Copernicus Early Warning
Data Store), both for the licence and for an uptime commitment. The 41-year calibration pulls
are heavy, about a thousand calls per cell, so the calibration script fetches one cell at a
time and waits out the per-minute limit.

### 4. Official data, as corroboration

`services/official_data.py` adds one item per source to every live reading. Officers see the
items in the trace, in the console's "Read the sources" step and in the after-action record.
They never lower a level. They raise one only when `PUKAAR_OFFICIAL_RAISES_LEVEL=true` (default
off), and they never count as a second source for "two sources agree". Every call has a timeout
(`PUKAAR_OFFICIAL_TIMEOUT_SECONDS`, 5 s) and is cached. A failure or a changed response becomes
`unavailable`, which says nothing; it never becomes "normal".

| Source | What is read | Default | Notes |
| --- | --- | --- | --- |
| CWC flood forecasting | `ffs.india-water.gov.in/ffm/api/station-water-level-above-warning/`: stations above warning (WARNING → watch, DANGER → warning, HFL → critical) | on | Verified live on 22 Oct 2026: 11 stations, none in Himachal. The response has only station codes. The station-list endpoints answer 404, and no Himachal Beas or Sutlej code could be confirmed, so `data/official_sources.json` maps none yet. The item says so ("no station codes mapped"). |
| IMD district warning | WMS GetFeatureInfo on `imd:Warnings_StateDistrict_Merged` at the village point; today's and tomorrow's colour (yellow → watch, orange → warning, red → critical) | on | Verified live. The colour covers every weather hazard, not floods alone. One call per district per day. |
| Google Flood Hub | `floodStatus:searchLatestFloodStatusByArea` over Himachal; gauges within 25 km of the river cell (ABOVE_NORMAL → watch, SEVERE → warning, EXTREME → critical) | off | Needs an API key (secret `flood_hub_api_key`) and `PUKAAR_FLOOD_HUB=true`. Data CC BY 4.0. |
| BIPAD (Nepal) | `bipadportal.gov.np/api/v1/river/`, the latest status per station | off | `PUKAAR_BIPAD=true` and station ids. Request adapted from CascadeWatch's `adapters/bipad.py` (Apache-2.0). Not reachable from our network on 22 Oct 2026, so the field names are tested on a synthetic payload only. |

The CWC and IMD parsers are tested on saved responses (`backend/tests/data/`, see
`official_samples.NOTICE.txt`).

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

Before is `risk-rules-v1`: percentile thresholds at the village point. After is
`risk-rules-v2`: return-period thresholds at the chosen river cell. Both use the same replay
rain and the same ground truth.

| Scenario | Configuration | Before: hits / misses, median lead | After: hits / misses, median lead |
| --- | --- | --- | --- |
| Himachal 2023 (1 village scored) | rain only | 1 / 0, 19 h | 1 / 0, 19 h |
| | river only | 1 / 0, ≥ 48 h | **0 / 1**, - |
| | both (Pukaar) | 1 / 0, ≥ 48 h | 1 / 0, **19 h** |
| | both + soil | 1 / 0, ≥ 48 h | 1 / 0, 19 h |
| Mandi 2025 (3 villages scored) | every configuration | 0 / 3, - | 0 / 3, - |

False alarms are n/a in both: no village is verified as quiet.

**Read plainly, the scored result got worse.** Pandoh, our one hit, is still a hit, but now
only through the rain forecast, 19 hours ahead instead of 48 or more. In the GloFAS reanalysis
the July 2023 Beas flood peaks at 298 m³/s at Pandoh's river cell. That is about a 1.2-year flow,
something this cell reaches almost every year, and below the 2-year Watch threshold of 366
m³/s. The old 90th percentile (282 m³/s) caught it because it was crossed most monsoons. That
same threshold held Pandoh at Watch about 48 days a year. GloFAS does not see the 2023 flood at
Pandoh as unusual: the real flood came from extreme rain, landslide debris and the Pandoh dam's
releases, none of which the model resolves. No return-period threshold catches it without firing
every year.

The 2025 cloudbursts are still missed by every configuration. No archived forecast crossed a
threshold at the three villages that were hit.

Back-test per village (`data/backtest.json`; times are UTC, first time each level was held):

| Scenario | Village | Before | After |
| --- | --- | --- | --- |
| Himachal 2023 | Thunag | Watch 8 Jul 04:00 | Watch 8 Jul 04:00 (rain) |
| | Janjehli | Watch 11 Jul 00:00 | never crossed |
| | Gohar | Critical 9 Jul 02:00 (Watch 8 Jul 00:00) | Warning 9 Jul 02:00 (Watch 8 Jul 05:00) |
| | Pandoh (event 9 Jul) | Critical 9 Jul 02:00 (Watch 7 Jul 00:00) | Warning 9 Jul 02:00 (Watch 8 Jul 05:00) |
| | Sujanpur | Critical 7 Jul 00:00 (hillside cell, peak 7.3 m³/s) | Critical 8 Jul 13:00 (Beas, peak 795 m³/s, a 4-year flow) |
| Mandi 2025 | Thunag, Janjehli, Gohar, Pandoh | never crossed | never crossed |
| | Sujanpur | Watch 30 Jun 06:00 (rain) | Watch 30 Jun 06:00 (rain) |

### Days a year at Watch, 2019-2024

This is how often the river alone would hold a village at Watch or above. It uses the GloFAS
daily reanalysis for 2019-2024 as a perfect forecast, with the sweep's look-ahead: a day counts
when the peak of that day and the next three is at or above the threshold. Before is the old
cell with the percentile thresholds; after is the chosen cell with the return-period
thresholds. Computed by `python -m Pukaar.scripts.calibrate --watch-days` and stored per village
under `watch_days` in `data/thresholds.json`.

| Village | Watch days a year, before → after (mean; range over the six years) | Warning days a year, before → after | Rises to Watch a year, before → after |
| --- | --- | --- | --- |
| Thunag | 47 (18-92) → 16 (0-43) | 13.2 → 1.8 | 1.7 → 0.5 |
| Janjehli | 43 (4-89) → 16 (0-42) | 13.8 → 2.7 | 1.3 → 0.5 |
| Gohar | 49 (21-90) → 11 (0-25) | 11.0 → 0 | 1.3 → 0.7 |
| Pandoh | 48 (0-85) → 24 (0-61) | 20.0 → 5.2 | 1.0 → 0.7 |
| Sujanpur | 56 (0-85) → 21 (0-41) | 14.3 → 1.7 | 0.8 → 1.3 |

- **Watch days fall by half to three quarters**, and Warning days fall to a few a year. In
  2020, 2021 and 2024 Thunag, Janjehli and Gohar never reach Watch.
- **Wet years still hold Watch for weeks.** 2023 holds Thunag at Watch for 43 days. Once a monsoon
  pushes a GloFAS cell past its 2-year flow, it stays there for weeks. One rise to Watch is
  still one approval, but the console shows Watch for a month. Sujanpur's rises go up (0.8 → 1.3)
  because the Beas cell has real flood waves where the hillside cell had one seasonal hump.
- **This is a perfect-forecast estimate.** The live rule uses the ensemble's P ≥ 0.3, which can
  fire on spread when the reanalysis does not and stay quiet when it does. These counts are not
  a measured live rate.

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

**Result** (`python -m Pukaar.scripts.score --soil`, with the return-period river thresholds;
per-village detail in `data/scores.json` under `soil_effect`):

| Scenario | Village | Truth | Max S | Hours S ≥ 0.8 | First Watch, off → on | First Warning, off → on | Hours at Warning or above, off → on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Himachal 2023 | Pandoh | event | 0.89 | 36 | 8 Jul 05:00 → same | 9 Jul 02:00 → same | 9 → 9 |
| | Thunag | uncertain | 1.00 | 63 | 8 Jul 04:00 → same | none → **9 Jul 00:00** | 0 → 11 |
| | Janjehli | uncertain | 1.00 | 97 | none → **8 Jul 09:00** | none → none | 0 → 0 |
| | Gohar | uncertain | 0.89 | 36 | 8 Jul 05:00 → same | 9 Jul 02:00 → same | 9 → 9 |
| | Sujanpur | uncertain | 0.89 | 23 | 7 Jul 00:00 → same | 7 Jul 16:00 → same | 43 → 43 |
| Mandi 2025 | Thunag | event | 0.67 | 0 | none → none | none → none | 0 → 0 |
| | Janjehli | event | 0.65 | 0 | none → none | none → none | 0 → 0 |
| | Gohar | event | 0.37 | 0 | none → none | none → none | 0 → 0 |
| | Pandoh, Sujanpur | uncertain | ≤ 0.50 | 0 | unchanged | unchanged | unchanged |

Times are UTC. Read plainly:

- **Scored outcomes do not change.** Pandoh 2023 is a hit with or without the modifier, 19 h
  ahead; the three villages hit in 2025 are still missed.
- **2025: the modifier never switched on.** The root zone before the 30 June cloudbursts was only
  moderately wet (S at most 0.67, early in the monsoon), and the archived rain forecast for the
  three villages that were hit stayed far below any band (at most 33 mm in 24 h). Soil moisture
  cannot rescue a cloudburst that the rain forecast does not see.
- **2023: the soil was saturated and the modifier did act**, all of it on villages whose outcome
  we could not verify. It raised Thunag to Warning for the first time (11 hours) and brought
  Janjehli to Watch, which it otherwise never reaches. Mandi district was hit hard on 9-11 July
  2023, so these may well be correct, but we cannot show that, and if Thunag stayed quiet that is
  one new false alarm.

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

- **Tiny sample.** Two events, four scored village-events. These are counts, not rates.
- **No false-alarm rate yet.** No village is verified as "nothing happened", because an
  absence of reports is not evidence of no damage. Until one is, false alarms are n/a.
- **Archived forecasts are reanalyses.** The historical-forecast and flood archives were
  assembled later; a live system would have seen noisier inputs, so the hit and lead
  numbers are optimistic.
- **No archived ensemble.** The replay cannot score the P ≥ 0.3 rule itself; it scores the
  thresholds with a perfect forecast.
- **28 years of annual maxima.** A 20-year discharge fitted on 28 years carries wide
  uncertainty; Critical in particular should be read as "rare at this cell", not as an exact
  return period.
- **GloFAS cannot see the khads.** Thunag, Janjehli and Gohar sit on streams the model represents
  with one or two cells. Their river levels mean little; rain, villager reports and a gauge do
  the work there.
- **Coarse truth.** Some entries are subdivision level (Gohar 2025) or constituency level
  (Janjehli 2025), and the event day is a UTC date, not an hour.
- **Forecast data only.** Villager reports, gauges and official feeds are not in the replay
  archive, so this does not score the full system.
