# analysis

Labelling, training and evaluation scripts, plus the committed result CSVs they produce. Raw inputs (the MILES
time series and derived parquet tables) are **not committed**; see "Reproduce" in the root README for the data layout.
All paths resolve from the repo root (override with `MILES_REPO=/path`). Use **June 3-22 2024 only**: the scraper's
status data breaks from June 24.

Install: `pip install -r requirements.txt` (Python 3.12).

| Script | What | Output |
|---|---|---|
| `build_rideends_allcities.py` | one row per customer ride end, all cities, June 2024, label `idle_h > 12` | `rideends_allcities_2024-06.parquet` (not committed) |
| `coldstart.py --tabpfn off` | new-city cold start: GBM on n local rides vs GBM trained on Berlin (transfer), 6 cities x 3 seeds | `coldstart_results_off.csv` (reruns byte-identical) |
| `coldstart.py --tabpfn api` | same, plus TabPFN on the **n local rides only (no Berlin context)** | `coldstart_results_api.csv`, see `NOTE_coldstart_results_api.md` |
| `berlin_likeforlike.py` | Berlin GBM with the cold-start feature recipe at 1k-30k rows; run from this folder | `berlin_likeforlike_gbm.csv` |
| `stranding.py`, `stranding_clean.py` | the stranding GBM with spatial and parking features (needs the parking tables) | printed metrics |
| `export_model.py` | exports the fallback GBM served by the console | `../model/stranding_gbm.joblib` (not committed), `../model/stranding_meta.json` |
| `berlin_parking/` | parking periods after each ride, classified against Berlin's street-parking geodata | `data/berlin_parking/parks_berlin_2024-06.parquet` |
| `parking_outcomes.py`, `parking_offstreet.py` | parking outcome / off-street labelling | `parks_outcomes_berlin_2024-06.parquet` (not committed) |
| `damage_rides.py` | damage-report features per ride | `rides_damage_berlin_2024-06.parquet` (not committed) |
| `fee_ledger.py` | reconstructs a Berlin parking-fee ledger; run from this folder | `fee_ledger_berlin_2024-06.parquet` (not committed) |

`rescue_stranded_validation.md` and `rescue_stranded_aggregates.csv` hold the stranding-frequency analysis
(2,681 strandings/day = 17.75% of Berlin ride ends; stranded cars are not low on fuel). The scripts that produced them
(`rescue_analysis.py`, `revenue_oppcost.py`) are pending.

**Pending (teammate's Prior Labs API reruns, scripts not yet in this repo):** the final stranding table
(TabPFN 10k 0.846 vs GBM 0.825 / 0.858, logistic 0.806), cold start with Berlin context (TabPFN 0.665 / 0.688 / 0.710),
the value map and the still-there model.
