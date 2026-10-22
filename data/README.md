# Data

Everything Pukaar reads at run time or shows as evidence. Every file is either
fetched from an open source and saved here, or computed from those files by a
script in this repository. The few hand-entered files say so in their `_note`.

| File | What it holds | Source | Rebuilt by |
|---|---|---|---|
| `villages.json` | The five villages (Gohar, Janjehli, Pandoh, Sujanpur, Thunag): coordinates, river cell, officers' order of escalation, illustrative gauge settings | Coordinates from the Open-Meteo geocoding API (GeoNames), not verified on the ground | Edit by hand |
| `thresholds.json` | Each village's river watch, warning and critical levels (the 2-, 5- and 20-year discharges of a Gumbel fit to annual maxima at the village's river cell; the earlier 90th/97th/99.5th percentiles kept under `percentile`), days a year at Watch before and after, and its soil-moisture range | Open-Meteo flood API (GloFAS) and historical-forecast API | `python -m Pukaar.scripts.calibrate` (`--watch-days`, `--soil`) |
| `river_cells.json` | The GloFAS cells within 7 km of each village, the one chosen as its river cell, the river's name and why (checked against OpenStreetMap and the model's routing) | Open-Meteo flood API; OpenStreetMap (ODbL) via Overpass | `python -m Pukaar.scripts.calibrate --cells`, then the choice by hand |
| `official_sources.json` | Which official feeds speak for which village: CWC station codes and rivers, IMD district, Flood Hub radius, BIPAD stations | Hand-kept | Edit by hand |
| `replay/himachal_2023_07/`, `replay/mandi_2025/` | Archived hourly forecasts for the July 2023 Beas floods and the 30 June–1 July 2025 Mandi cloudbursts, replayed through the live loop | Open-Meteo historical-forecast and flood APIs | `python -m Pukaar.scripts.fetch_replay` |
| `probes/` | Single-village archive pulls used to check the replays | Open-Meteo | Fetched once, kept for reference |
| `backtest.json` | For each scenario and village: the first time each level was reached, the river's peak day and the lead time, including "never crossed" | Computed from `replay/` with the rules in `services/risk_rules.py` | `python -m Pukaar.scripts.backtest` |
| `ground_truth.json` | What actually happened in each village during each scenario, with the source for every entry | News and government reports, cited per entry | Edit by hand, with a source |
| `scores.json` | The back-test scored against `ground_truth.json`, with a source ablation (rain only, river only, both); method in [docs/SCORING.md](../docs/SCORING.md) | Computed | `python -m Pukaar.scripts.score` |
| `evidence.json` | The sourced numbers shown on the landing and how-it-works pages | Published reports and papers, cited per entry | Edit by hand, with a source |
| `pilot_readiness.json` | The pilot-readiness checklist on /pilot: each item's status (done, in progress, not started), why it matters and its owner | Hand-kept; statuses are honest as of `updated` | Edit by hand (the page picks it up at the next web build) |
| `safe_places/*.geojson`, `summary.json` | Named high ground near each village and slope-aware walking routes to it | © OpenStreetMap contributors (ODbL), via Overpass; heights from Mapzen Terrain Tiles on AWS Open Data | `scripts/build_safe_places.py` |

Licences: OpenStreetMap data is ODbL and must keep its attribution; Open-Meteo
data is CC BY 4.0; Terrain Tiles are open data on AWS. The backend scripts run
from `backend/` with `PYTHONPATH=src`.
