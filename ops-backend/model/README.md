# model/

Model metadata and metrics — the numbers behind the README's TabPFN story.

- `tabpfn_meta.json` — TabPFN context spec (10k Berlin ride ends, June 3–16 2024), feature list, held-out metrics
  (AUC/Brier/ECE), the TabPFN-vs-GBM comparison, Carolina's clean-split results, decision thresholds, calibration
  bins, and the value model. Written by `../build_tabpfn.py`.
- `stranding_meta.json` — GBM stranding model spec: target, features, grid definition, validation AUC and the
  top-10% alert threshold. Written by `../../analysis/export_model.py`.

**Not committed** (rebuildable from the June-2024 dataset via the scripts; excluded by `.gitignore`):
`stranding_gbm.joblib` (trained GBM), `tabpfn_context.npz` (the 10k-row context), `cells_berlin.parquet`.
