# model/

Metadata and metrics of the models the console serves.

- `tabpfn_meta.json` - the **served** TabPFN model: 10k Berlin ride-end context (June 3-16 2024, `random_state=0`),
  the 11 features, out-of-sample metrics on June 17-22 (`metrics.tabpfn_clean_split`: AUC 0.822, Brier 0.112,
  ECE 0.015), the relocate threshold (0.4556 = top 10% of ride ends; 56.2% of those really stranded), calibration
  bins, and the Prior Labs API calls used for the replay precompute. Written by `../backend/build_tabpfn.py`.
  `metrics_carolina` is an older teammate run (TabPFN 0.824 / GBM 0.84) from before the final feature set; the root
  README's results table supersedes it. `metrics.gbm_in_sample_replay` is in-sample and not a baseline.
- `stranding_meta.json` - the **fallback** GBM used when a TabPFN call fails or times out: target, features, grid,
  validation AUC and threshold. Written by `../analysis/export_model.py`.

**Not committed** (rebuildable with the scripts; excluded by `.gitignore`): `stranding_gbm.joblib`,
`tabpfn_context.npz` (the 10k-row context), `cells_berlin.parquet`.
