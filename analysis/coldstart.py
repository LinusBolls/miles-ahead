"""Cold start: how well can we predict 'idle > 12 h after ride end' in a city with only n training rides?
Train on n rides sampled from the city's first two June weeks, test on its last two weeks.
Models: GBM (sklearn HistGradientBoosting), GBM trained on Berlin (transfer, no target data), TabPFN (if available).
Label-free + leave-one-out features only, computed from the n training rides (what a new city would have).
Usage: python coldstart.py [--tabpfn local|api|off] [--cities PTD,DUS,STR,DUI] [--seeds 3]
"""
import argparse, json, os, time
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, brier_score_loss

ap = argparse.ArgumentParser()
ap.add_argument("--tabpfn", default="off"); ap.add_argument("--cities", default="PTD,DUS,STR,DUI,AGB,UWP")
ap.add_argument("--seeds", type=int, default=3); ap.add_argument("--ns", default="50,100,200,500,1000")
ap.add_argument("--test-max", type=int, default=2000)
a = ap.parse_args()
P = "/Users/linusbolls/projects/vorfahrt/miles-ops/analysis/"
df = pd.read_parquet(P + "rideends_allcities_2024-06.parquet")
df["t"] = pd.to_datetime(df.ride_end_utc).dt.tz_localize("UTC").dt.tz_convert("Europe/Berlin")
df["y"] = (df.idle_h > 12).astype(int)
df["hour"] = df.t.dt.hour; df["dow"] = df.t.dt.dayofweek
df["size_code"] = df.size_class.map({s: i for i, s in enumerate(["L", "M", "P", "S", "X"])})
df["cell"] = (df.lat / 0.0036).round().astype(int).astype(str) + "_" + (df.lon / 0.0059).round().astype(int).astype(str)
FEATS = ["hour", "dow", "charge", "discounted", "damage_count", "size_code", "electric", "dist_center_km", "cell_density", "cell_rate_loo", "knn_rate"]

def featurize(train, test):
    """features from training rows only (label-free density; leave-one-out label rates for train rows)."""
    lat0, lon0 = train.lat.median(), train.lon.median()
    out = []
    for d, is_train in ((train, True), (test, False)):
        d = d.copy()
        d["dist_center_km"] = np.hypot((d.lat - lat0) * 111, (d.lon - lon0) * 68)
        cnt = train.groupby("cell").size(); pos = train.groupby("cell").y.sum()
        n_c = d.cell.map(cnt).fillna(0); p_c = d.cell.map(pos).fillna(0)
        if is_train: n_c, p_c = n_c - 1, p_c - d.y
        prior = train.y.mean()
        d["cell_density"] = n_c / len(train)
        d["cell_rate_loo"] = (p_c + 2 * prior) / (n_c + 2)
        # k nearest training ride ends (excluding self) -> stranded rate
        tx = np.c_[(train.lat.values - lat0) * 111, (train.lon.values - lon0) * 68]
        dx = np.c_[(d.lat.values - lat0) * 111, (d.lon.values - lon0) * 68]
        k = min(10, len(train) - 1)
        dist = ((dx[:, None, :] - tx[None, :, :]) ** 2).sum(-1)
        if is_train: np.fill_diagonal(dist, np.inf)
        idx = np.argpartition(dist, k, axis=1)[:, :k]
        d["knn_rate"] = train.y.values[idx].mean(1)
        out.append(d[FEATS].astype(float))
    return out

def tabpfn_model():
    if a.tabpfn == "local":
        from tabpfn import TabPFNClassifier
        return lambda: TabPFNClassifier(device="cpu", random_state=0)
    if a.tabpfn == "api":
        import tabpfn_client
        tabpfn_client.set_access_token(os.environ["TABPFN_TOKEN"])
        return lambda: tabpfn_client.TabPFNClassifier()
    return None
mk_tab = tabpfn_model()

# transfer baseline: GBM trained on Berlin with the same feature recipe (Berlin's own first 2 weeks as history)
ber = df[df.city == "BER"]
ber_tr = ber[ber.t.dt.day < 17].sample(20000, random_state=0)
Xb, _ = featurize(ber_tr, ber_tr.iloc[:1])
gbm_ber = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, random_state=0).fit(Xb, ber_tr.y)

rows = []
for city in a.cities.split(","):
    cd = df[df.city == city]
    pool, test = cd[cd.t.dt.day < 17], cd[cd.t.dt.day >= 17]
    test = test.sample(min(a.test_max, len(test)), random_state=0)
    for n in map(int, a.ns.split(",")):
        if n > len(pool): continue
        for seed in range(a.seeds):
            tr = pool.sample(n, random_state=seed)
            Xtr, Xte = featurize(tr, test)
            res = {"city": city, "n": n, "seed": seed, "test_n": len(test), "base_rate": round(test.y.mean(), 3)}
            g = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, random_state=seed, min_samples_leaf=max(5, n // 50)).fit(Xtr, tr.y)
            pg = g.predict_proba(Xte)[:, 1]
            res.update(gbm_auc=roc_auc_score(test.y, pg), gbm_brier=brier_score_loss(test.y, pg))
            # Berlin-trained GBM applied with target-city features (from n rides)
            pb = gbm_ber.predict_proba(Xte)[:, 1]
            res.update(ber_transfer_auc=roc_auc_score(test.y, pb), ber_transfer_brier=brier_score_loss(test.y, pb))
            if mk_tab:
                t0 = time.time(); m = mk_tab().fit(Xtr, tr.y.values); pt = m.predict_proba(Xte)[:, 1]
                res.update(tabpfn_auc=roc_auc_score(test.y, pt), tabpfn_brier=brier_score_loss(test.y, pt), tabpfn_s=round(time.time() - t0, 1))
            rows.append(res); print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in res.items()}), flush=True)
r = pd.DataFrame(rows)
r.to_csv(P + f"coldstart_results_{a.tabpfn}.csv", index=False)
cols = [c for c in r.columns if c.endswith("_auc") or c.endswith("_brier")]
print(r.groupby("n")[cols].mean().round(3).to_string())
print(r.groupby(["city", "n"])[cols].mean().round(3).to_string())
