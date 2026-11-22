"""Is 'this car will sit idle > 12 h' predictable at ride end? Berlin June 2024.
Spatial features: historical demand in a ~400 m grid cell (ride starts per cell from weeks 1-2), distance to centre,
parking context; temporal: hour, weekday; car: fuel, discount, model size. Train weeks 1-2 history -> eval weeks 3-4.
"""
import os as _os
_REPO = _os.environ.get("MILES_REPO", _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../.."))) + "/"  # repo root; raw data goes in data/ (see README)
import duckdb, numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score

P = _REPO + "miles-ops/analysis/"
r = pd.read_parquet(P + "rides_damage_berlin_2024-06.parquet")
parks = pd.read_parquet(P + "parks_outcomes_berlin_2024-06.parquet")
r = r.merge(parks[["vehicle_id", "parked_from_utc", "latitude", "longitude", "ch1", "inside_sbahn_ring", "paid_zone_fee_eur_h"]],
            left_on=["vehicle_id", "ride_end"], right_on=["vehicle_id", "parked_from_utc"], how="left")
r["end_local"] = pd.to_datetime(r.ride_end).dt.tz_localize("UTC").dt.tz_convert("Europe/Berlin")
r["cell"] = (r.latitude / 0.0036).round().astype("Int64").astype(str) + "_" + (r.longitude / 0.0059).round().astype("Int64").astype(str)
r["week"] = (r.end_local.dt.day - 3) // 7  # 0..3
hist = r[r.week <= 1]
starts = hist.groupby("cell").size().rename("cell_starts_hist")  # ride ENDS = arrivals; use starts proxy below
# demand proxy: ride starts in cell = rides whose *start* was there; approximate with arrivals (symmetric-ish) and idle median
cell_idle = hist.groupby("cell").parked_hours.median().rename("cell_median_idle_hist")
r = r.join(starts, on="cell").join(cell_idle, on="cell")
r["cell_starts_hist"] = r.cell_starts_hist.fillna(0); r["cell_median_idle_hist"] = r.cell_median_idle_hist.fillna(r.parked_hours.median())
r["dist_center_km"] = np.hypot((r.latitude - 52.5163) * 111, (r.longitude - 13.3777) * 68)
r["hour"] = r.end_local.dt.hour; r["dow"] = r.end_local.dt.dayofweek
r["y"] = (r.parked_hours > 12).astype(int)
area_map = {a: i for i, a in enumerate(sorted(r.end_area.dropna().unique()))}
r["area_code"] = r.end_area.map(area_map)
r["size_code"] = r.size_class.astype("category").cat.codes
feats = ["cell_starts_hist", "cell_median_idle_hist", "dist_center_km", "hour", "dow", "ch1", "end_dist", "end_offstreet", "area_code",
         "size_code", "electric", "prior_damage", "inside_sbahn_ring"]
X = r[feats].astype(float)
tr, te = r.week <= 1, r.week >= 2
print(f"base rate idle>12h: {r.y.mean():.1%}  (train {tr.sum():,}, test {te.sum():,})")
m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05).fit(X[tr], r.y[tr])
p = m.predict_proba(X[te])[:, 1]
print(f"GBM  AUC {roc_auc_score(r.y[te], p):.3f}  AP {average_precision_score(r.y[te], p):.3f}")
for k in (0.05, 0.10, 0.20):
    thr = np.quantile(p, 1 - k); sel = p >= thr
    print(f"  top {int(k*100)}% flagged: precision {r.y[te][sel].mean():.1%} (base {r.y[te].mean():.1%}), recall {r.y[te][sel].sum()/r.y[te].sum():.1%}, median idle {r.parked_hours[te][sel].median():.1f} h")
# TabPFN on a subsample (sponsor track) if available
try:
    from tabpfn import TabPFNClassifier
    rng = np.random.default_rng(0)
    itr = rng.choice(np.where(tr)[0], 3000, replace=False); ite = rng.choice(np.where(te)[0], 3000, replace=False)
    t = TabPFNClassifier(device="cpu").fit(X.iloc[itr], r.y.iloc[itr])
    pt = t.predict_proba(X.iloc[ite])[:, 1]
    pg = m.predict_proba(X.iloc[ite])[:, 1]
    print(f"TabPFN (3k train) AUC {roc_auc_score(r.y.iloc[ite], pt):.3f} vs GBM (full train) on same 3k test {roc_auc_score(r.y.iloc[ite], pg):.3f}")
except Exception as e:
    print("TabPFN not run:", type(e).__name__, str(e)[:200])
# what does a stranded ride end look like? cells with worst idle
w = r[te].groupby("cell").agg(n=("y", "size"), stranded=("y", "mean"), med_idle=("parked_hours", "median"), lat=("latitude", "median"), lon=("longitude", "median"))
print("\nworst cells (>=40 ride ends in test weeks):"); print(w[w.n >= 40].sort_values("stranded", ascending=False).head(8).round(3).to_string())
rides_per_car_day = len(r) / (r.vehicle_id.nunique() * 28)
idle_hours_excess = (r.parked_hours.clip(upper=72) - 12).clip(lower=0)[r.y == 1].sum() / 28
print(f"\nrides per car-day {rides_per_car_day:.2f}; excess idle beyond 12 h: {idle_hours_excess:,.0f} car-hours/day in Berlin; stranded ride ends/day {r.y.sum()/28:.0f}")
