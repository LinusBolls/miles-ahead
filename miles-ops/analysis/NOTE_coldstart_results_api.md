# NOTE on `coldstart_results_api.csv`

This file is an **early, small run** of `coldstart.py --tabpfn api` (2 cities: PTD and AGB; n = 50 and 200; 2 seeds;
at most 1,000 test rows per city). It is kept for the record. **It is not the source of the README's cold-start
numbers.**

In this run TabPFN got **only the n local rides as context, with no Berlin rows** (`coldstart.py` calls
`fit(Xtr, ...)` on the local sample only). With 50-200 rows and no Berlin context it does poorly:

| n | TabPFN (local rides only) | GBM, local rides only | GBM trained on Berlin (transfer) |
|---|---|---|---|
| 50 | 0.580 | 0.552 | 0.637 |
| 200 | 0.552 | 0.626 | 0.633 |

(Mean AUC over the rows in the CSV.)

The README's cold-start result (TabPFN 0.665 / 0.688 / 0.710 at n = 50 / 200 / 1000) uses a different setup:
**Berlin ride ends plus the n local rides as context**. That number comes from a teammate's Prior Labs API rerun
whose script is not yet in this repository ("scripts pending" in the root README). The GBM baselines in
`coldstart_results_off.csv` (`coldstart.py --tabpfn off`, 6 cities x 3 seeds) are reproducible from this repo.

Takeaway: TabPFN needs the Berlin context to win the new-city case. Without it, on a few dozen local rides, a
Berlin-trained GBM is better.
