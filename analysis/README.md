# analysis

Model and evaluation scripts, plus the committed result CSVs they produce. The raw parquet inputs (ride ends,
parking outcomes, damage, fee ledger — all derived from the private MILES scraper DB, June 3–22 2024) are **not
committed** (see `.gitignore`).

- `coldstart.py` — cross-city cold-start curves, TabPFN vs. GBM vs. Berlin-transfer, at increasing ride counts.
  `--tabpfn local|api|off`. Results: `coldstart_results_api.csv`, `coldstart_results_off.csv`.
- `berlin_likeforlike.py` — Berlin TabPFN-vs-GBM as context/training size grows. Results: `berlin_likeforlike_gbm.csv`.
- `stranding.py`, `stranding_clean.py` — the stranding (idle > 12 h) GBM: features, training, validation.
- `export_model.py` — exports the trained GBM + `stranding_meta.json`.
- `build_rideends_allcities.py` — builds the ride-ends feature table for all cities.
- `parking_outcomes.py`, `parking_offstreet.py` — parking-outcome / off-street labelling.
- `damage_rides.py` — damage-report features.
- `fee_ledger.py` — reconstructs the Berlin parking-fee ledger from the 2024 data.

Use **June 3–22 2024 only**; June 24 onward has broken labels (scraper behaviour changed).
