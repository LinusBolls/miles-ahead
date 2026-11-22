"""Train the stranding model (idle > 12 h after ride end) on Berlin June 2024 and export artifacts for the live service."""
import os as _os
_REPO = _os.environ.get("MILES_REPO", _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../.."))) + "/"  # repo root; raw data goes in data/ (see README)
import json, joblib, numpy as np, pandas as pd, sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
P = _REPO + "miles-ops/"
r = pd.read_parquet(P + "analysis/rides_damage_berlin_2024-06.parquet")
parks = pd.read_parquet(P + "analysis/parks_outcomes_berlin_2024-06.parquet")
r = r.merge(parks[["vehicle_id", "parked_from_utc", "latitude", "longitude", "ch1", "inside_sbahn_ring"]],
            left_on=["vehicle_id", "ride_end"], right_on=["vehicle_id", "parked_from_utc"], how="left").dropna(subset=["latitude"])
r["end_local"] = pd.to_datetime(r.ride_end).dt.tz_localize("UTC").dt.tz_convert("Europe/Berlin")
CELL_LAT, CELL_LON = 0.0036, 0.0059
r["cell"] = (r.latitude / CELL_LAT).round().astype(int).astype(str) + "_" + (r.longitude / CELL_LON).round().astype(int).astype(str)
r["week"] = (r.end_local.dt.day - 3) // 7
# June 24-30 is a scraper collection gap (missed rides inflate idle). Use ride ends June 3-22 only.
r = r[r.end_local.dt.day <= 22].copy()
NDAYS = 20
def cell_stats(h):
    return h.groupby("cell").agg(cell_starts_hist=("y0", "size"), cell_median_idle_hist=("parked_hours", "median"))
r["y0"] = 1; r["y"] = (r.parked_hours > 12).astype(int)
r["dist_center_km"] = np.hypot((r.latitude - 52.5163) * 111, (r.longitude - 13.3777) * 68)
r["hour"] = r.end_local.dt.hour; r["dow"] = r.end_local.dt.dayofweek
AREAS = ["bus_lane", "legal", "loading_zone", "no_legal_parking_nearby", "no_legal_parking_nearby_outer", "no_stopping", "taxi_stand"]
SIZES = ["L", "M", "P", "S", "X"]
r["area_code"] = r.end_area.map({a: i for i, a in enumerate(AREAS)})
r["size_code"] = r.size_class.map({s: i for i, s in enumerate(SIZES)})
FEATS = ["cell_starts_hist", "cell_median_idle_hist", "dist_center_km", "hour", "dow", "ch1", "end_dist", "end_offstreet", "area_code",
         "size_code", "electric", "prior_damage", "inside_sbahn_ring"]
def frame(df, cs):
    d = df.drop(columns=[c for c in ["cell_starts_hist", "cell_median_idle_hist"] if c in df]).join(cs, on="cell")
    d["cell_starts_hist"] = d.cell_starts_hist.fillna(0) * (14 / cs_days[id(cs)])
    d["cell_median_idle_hist"] = d.cell_median_idle_hist.fillna(r.parked_hours.median())
    return d[FEATS].astype(float)
# validation (history weeks 0-1 -> test June 17-22), then final fit on all 4 weeks with stats from all 4 weeks
cs_hist = cell_stats(r[r.week <= 1]); cs_days = {id(cs_hist): 14}
tr, te = r.week <= 1, r.week >= 2
m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=0).fit(frame(r[tr], cs_hist), r.y[tr])
p = m.predict_proba(frame(r[te], cs_hist))[:, 1]
auc = roc_auc_score(r.y[te], p); thr10 = float(np.quantile(p, 0.9)); prec10 = float(r.y[te][p >= thr10].mean())
cs_all = cell_stats(r); cs_days[id(cs_all)] = NDAYS
mf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=0).fit(frame(r, cs_all), r.y)
pall = mf.predict_proba(frame(r, cs_all))[:, 1]
joblib.dump(mf, P + "model/stranding_gbm.joblib")
cs_all.assign(cell_starts_hist=cs_all.cell_starts_hist * (14 / NDAYS)).reset_index().to_parquet(P + "model/cells_berlin.parquet", index=False)  # per 14 days
meta = dict(target="parked_hours > 12 after a customer ride end", city="BER", train="Berlin 2024-06-03..2024-06-22 (June 24-30 excluded: collection gap)",
            features=FEATS, areas=AREAS, sizes=SIZES, cell_deg=[CELL_LAT, CELL_LON], cell_key="round(lat/0.0036)_round(lon/0.0059)",
            cell_starts_hist_unit="ride ends in cell per 14 days", center=[52.5163, 13.3777],
            validation=dict(auc=round(auc, 3), base_rate=round(float(r.y[te].mean()), 3), precision_top10pct=round(prec10, 3)),
            alert_threshold_top10pct=round(float(np.quantile(pall, 0.9)), 4), sklearn=sklearn.__version__)
json.dump(meta, open(P + "model/stranding_meta.json", "w"), indent=1)
print(json.dumps(meta["validation"]), "thr", meta["alert_threshold_top10pct"], "sklearn", sklearn.__version__)
