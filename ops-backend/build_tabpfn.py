"""Offline build for "Tonight's moves" (run once, locally; needs TABPFN_TOKEN in the env, never printed):

  1. model/tabpfn_context.npz   fixed 10k-row Berlin context: ride ends June 3-16 2024, label idle > 12 h, raw features
  2. replay TabPFN scores      every replay ride end scored OUT-OF-SAMPLE via the Prior Labs API, in a few big batches:
                                June 17-22 rows with the June 3-16 context (= the live context, Carolina's clean split),
                                June 3-16 rows with a 10k context drawn from June 17-22 (disjoint labels).
                                Written as column `p_tabpfn` into geo/replay_berlin_2024-06.{parquet,npz}.
  3. model/tabpfn_meta.json    features, model vocab, thresholds (quantile-matched TabPFN vs GBM), calibration bins,
                                metrics on the clean split, API calls used.
  4. geo/demand_berlin.npz      demand per cell x hour-of-week (customer ride starts June 3-16 / 2 weeks), a legal
                                representative parking point per cell, mean idle per cell (for Relocate targets/value).

Usage: TABPFN_TOKEN=... .venv-tabpfn/bin/python build_tabpfn.py [--skip-api] [--chunk 50000]
"""
import argparse, json, os, sys, time
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from app.strand_tabpfn import FEATURES, CATEGORICAL, featurize  # noqa: E402

A = os.path.join(HERE, "..", "analysis") + "/"
MODEL = os.path.join(HERE, "..", "model")
GEO = os.path.join(HERE, "geo")
TZ = "Europe/Berlin"
SPLIT = pd.Timestamp("2024-06-17", tz=TZ)
END = pd.Timestamp("2024-06-23", tz=TZ)
CELL = (0.0036, 0.0059)

ap = argparse.ArgumentParser()
ap.add_argument("--skip-api", action="store_true", help="reuse p_tabpfn already in the replay parquet")
ap.add_argument("--chunk", type=int, default=50000)
a = ap.parse_args()


def feats(df, vocab):
    t = df.t
    return featurize(t.dt.hour.values, t.dt.dayofweek.values, df.charge.values, df.discounted.values, df.damage_count.values,
                     df.size_class.values, df.electric.values, df.model.values, df.lat.values, df.lon.values, vocab)


def auc(y, p):
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, p))


def calib_bins(y, p, edges):
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum() >= 30:
            out.append({"lo": round(float(lo), 3), "hi": round(float(hi), 3), "n": int(m.sum()), "rate": round(float(y[m].mean()), 3),
                        "mean_p": round(float(p[m].mean()), 3)})
    return out


def ece(y, p, n=10):
    e, edges = 0.0, np.linspace(0, 1, n + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi)
        if m.any():
            e += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(e)


# ---------------- data ----------------
ride = pd.read_parquet(A + "rideends_allcities_2024-06.parquet")
ride = ride[ride.city == "BER"].copy()
ride["t"] = pd.to_datetime(ride.ride_end_utc).dt.tz_localize("UTC").dt.tz_convert(TZ)
ride = ride[ride.t < END]
ride["y"] = (ride.idle_h > 12).astype(int)
vc = ride[ride.t < SPLIT].model.value_counts()
vocab = {m: i for i, m in enumerate(vc.index)}
ctxA = ride[ride.t < SPLIT].sample(10000, random_state=0)
ctxB = ride[(ride.t >= SPLIT)].sample(10000, random_state=0)
XA, yA = feats(ctxA, vocab), ctxA.y.values
XB, yB = feats(ctxB, vocab), ctxB.y.values
np.savez_compressed(os.path.join(MODEL, "tabpfn_context.npz"), X=XA.astype(np.float32), y=yA.astype(np.int8), features=np.array(FEATURES))
print(f"context A: {len(XA)} rows, base rate {yA.mean():.3f}; context B (June 17-22): base {yB.mean():.3f}")

rp_path = os.path.join(GEO, "replay_berlin_2024-06.parquet")
rp = pd.read_parquet(rp_path)
rp["t"] = pd.to_datetime(rp.parked_from_utc).dt.tz_localize("UTC").dt.tz_convert(TZ)
j = rp[["vehicle_id", "parked_from_utc"]].merge(ride[["vehicle_id", "ride_end_utc", "charge", "discounted", "damage_count"]],
                                                left_on=["vehicle_id", "parked_from_utc"], right_on=["vehicle_id", "ride_end_utc"], how="left")
j = j.drop_duplicates(["vehicle_id", "parked_from_utc"])
assert len(j) == len(rp)
rq = pd.DataFrame({"t": rp.t, "charge": j.charge.fillna(rp.ch1.where(rp.ch1 >= 0)).values,
                   "discounted": j.discounted.fillna(0).values, "damage_count": j.damage_count.fillna(rp.prior_damage).values,
                   "size_class": rp.size_class.values, "electric": rp.electric.values, "model": rp.model.values,
                   "lat": rp.latitude.values, "lon": rp.longitude.values})
XR = feats(rq, vocab)
yR = (rp.parked_hours.values > 12).astype(int)
late = (rp.t >= SPLIT).values
print(f"replay rows {len(rp)}: June 3-16 {(~late).sum()}, June 17-22 {late.sum()}; joined {j.discounted.notna().mean():.1%}")

# ---------------- API ----------------
calls = []
if a.skip_api and "p_tabpfn" in rp.columns:
    pR = rp.p_tabpfn.values.astype(float)
else:
    import tabpfn_client
    tok = os.environ["TABPFN_TOKEN"]
    tabpfn_client.set_access_token(tok)
    print("usage before:", tabpfn_client.get_api_usage())
    pR = np.full(len(rp), -1.0)
    for name, X, y, sel in (("ctxA", XA, yA, late), ("ctxB", XB, yB, ~late)):
        clf = tabpfn_client.TabPFNClassifier(random_state=0, categorical_features_indices=CATEGORICAL)
        clf.fit(X, y)
        idx = np.where(sel)[0]
        for k in range(0, len(idx), a.chunk):
            part = idx[k:k + a.chunk]
            t0 = time.time()
            for attempt in range(3):
                try:
                    pR[part] = clf.predict_proba(XR[part])[:, 1]
                    break
                except Exception as ex:
                    print("retry", attempt, type(ex).__name__, str(ex).replace(tok, "***")[:200]); time.sleep(5)
            else:
                raise SystemExit("API failed 3x")
            calls.append({"context": name, "rows": int(len(part)), "s": round(time.time() - t0, 1)})
            print(calls[-1], flush=True)
    print("usage after:", tabpfn_client.get_api_usage())
    rp["p_tabpfn"] = pR.astype(np.float32)
    rp.drop(columns=["t"]).to_parquet(rp_path, index=False, compression="zstd")
    npz = os.path.join(GEO, "replay_berlin_2024-06.npz")
    z = dict(np.load(npz))
    z["p_tabpfn"] = pR.astype(np.float32)
    np.savez_compressed(npz, **z)

# ---------------- metrics, thresholds, calibration ----------------
from sklearn.metrics import brier_score_loss
pT, yT = pR[late], yR[late]
gbm = rp.p_strand.values.astype(float)
met = {"tabpfn_clean_split": {"n": int(late.sum()), "auc": round(auc(yT, pT), 3), "brier": round(float(brier_score_loss(yT, pT)), 3),
                              "ece": round(ece(yT, pT), 3), "base_rate": round(float(yT.mean()), 3),
                              "note": "context 10k ride ends June 3-16, test = replay ride ends June 17-22 (parking periods)"},
       "tabpfn_all_replay_oos": {"n": int(len(pR)), "auc": round(auc(yR, pR), 3)},
       "gbm_in_sample_replay": {"auc": round(auc(yR, gbm), 3), "note": "GBM fit on June 3-22: in-sample"}}
print(json.dumps(met, indent=1))
SHARE = float(os.environ.get("MOVE_SHARE", "0.10"))   # top share of ride ends that become Relocate candidates
thr_t = float(np.quantile(pR, 1 - SHARE)); thr_g = float(np.quantile(gbm, 1 - SHARE))
prec_t = float(yR[pR >= thr_t].mean()); prec_g = float(yR[gbm >= thr_g].mean())
edges = np.array([0, .05, .1, .15, .2, .25, .3, .35, .4, .45, .5, .55, .6, .65, .7, .8, .9, 1.0001])
cal_t = calib_bins(yT, pT, edges)                 # clean split, same context as live
cal_g = calib_bins(yR, gbm, edges)                # in-sample (labelled so in the UI)
EUR_H = 227e6 / 19000 / 8760
H_s = float(ride.idle_h[ride.y == 1].clip(upper=48).mean()); H_ns = float(ride.idle_h[ride.y == 0].mean())

# ---------------- demand per cell x hour-of-week ----------------
z = np.load(os.path.join(GEO, "replay_berlin_2024-06.npz"))
t1 = pd.to_datetime(z["t1"]).tz_localize("UTC").tz_convert(TZ)
cust = ~(z["ops_next"] | z["tow_proxy"])
wk = (t1 >= pd.Timestamp("2024-06-03", tz=TZ)) & (t1 < SPLIT) & cust
lat, lon = z["lat"][wk], z["lon"][wk]
how = (t1.dayofweek[wk] * 24 + t1.hour[wk]).values
ci, cj = np.round(lat / CELL[0]).astype(int), np.round(lon / CELL[1]).astype(int)
keys = ci.astype(np.int64) * 100000 + cj
uk, inv = np.unique(keys, return_inverse=True)
dem = np.zeros((len(uk), 168), np.float32)
np.add.at(dem, (inv, how), 0.5)   # 2 weeks -> per week
legal = rp.area_type.values == "legal"
# representative legal parking point per cell: the legal ride-end position closest to the cell's legal-park centroid
pk_keys = np.round(rp.latitude.values / CELL[0]).astype(np.int64) * 100000 + np.round(rp.longitude.values / CELL[1]).astype(int)
dfp = pd.DataFrame({"k": pk_keys, "lat": rp.latitude.values, "lon": rp.longitude.values, "legal": legal,
                    "idle": np.minimum(rp.parked_hours.values, 48), "early": ~late})
lp = dfp[dfp.legal]
cen = lp.groupby("k")[["lat", "lon"]].transform("mean")
lp = lp.assign(d=(lp.lat - cen.lat) ** 2 + ((lp.lon - cen.lon) * 0.61) ** 2)
rep = lp.loc[lp.groupby("k").d.idxmin(), ["k", "lat", "lon"]].set_index("k")
# typical idle after a ride end per cell x 3-hour bucket of the day (time-aware: evening ride ends sit overnight)
dfp["b"] = (rp.t.dt.hour.values // 3)
ear = dfp[dfp.early]
gb = ear.groupby("b").idle.mean()                     # city mean per bucket
st = ear.groupby(["k", "b"]).idle.agg(["mean", "count"])
gm = float(ear.idle.mean())
keep = np.array([k in rep.index for k in uk])
uk, dem = uk[keep], dem[keep]
idle = np.zeros((len(uk), 8), np.float32)
for bi in range(8):
    sb = st.xs(bi, level="b") if bi in st.index.get_level_values("b") else None
    for ii, k in enumerate(uk):
        g = float(gb.get(bi, gm))
        if sb is not None and k in sb.index:
            mu, n = sb.loc[k, "mean"], sb.loc[k, "count"]
            idle[ii, bi] = (mu * n + g * 15) / (n + 15)   # shrink small cells toward the city mean of the bucket
        else:
            idle[ii, bi] = g
print("city idle per 3h bucket:", gb.round(1).to_dict())
np.savez_compressed(os.path.join(GEO, "demand_berlin.npz"), key=uk, demand=dem.astype(np.float16),
                    lat=rep.loc[uk].lat.values, lon=rep.loc[uk].lon.values, idle=idle)
print(f"demand cells {len(uk)}; total starts/week {dem.sum():,.0f}; city mean idle {gm:.2f} h")

meta = {
    "features": FEATURES, "categorical": [FEATURES[i] for i in CATEGORICAL], "model_vocab": vocab,
    "context": {"rows": 10000, "range": "Berlin ride ends 2024-06-03..2024-06-16", "label": "idle > 12 h", "base_rate": round(float(yA.mean()), 3),
                "sample": "random_state=0 from rideends_allcities_2024-06.parquet, city == BER"},
    "metrics": met, "metrics_carolina": {"berlin_10k_auc": 0.824, "brier": 0.115, "ece": 0.008, "gbm_210k_auc": 0.840,
                                          "note": "Carolina, Prior Labs API, train June 3-16 / test June 17-23"},
    "threshold": {"tabpfn": round(thr_t, 4), "gbm": round(thr_g, 4), "share": SHARE,
                  "precision_tabpfn": round(prec_t, 3), "precision_gbm": round(prec_g, 3)},
    "calibration": {"tabpfn": cal_t, "gbm": cal_g, "tabpfn_basis": "out-of-sample, June 17-22 ride ends scored with the June 3-16 context",
                    "gbm_basis": "in-sample (GBM fit on June 3-22)"},
    "value": {"eur_per_car_h": round(EUR_H, 3), "h_strand": round(H_s, 2), "h_no_strand": round(H_ns, 2),
              "basis": "MILES 2024 audited report: €227M revenue / ~19k cars / 8,760 h; idle hours from Berlin ride ends June 3-16 (capped at 48 h)"},
    "replay_precompute": {"api_calls": calls, "n_calls": len(calls) + (2 if calls else 0), "note": "n_calls counts 2 fits (context uploads) + predict calls"},
}
if not calls and os.path.exists(os.path.join(MODEL, "tabpfn_meta.json")):   # --skip-api: keep the record of the real run
    meta["replay_precompute"] = json.load(open(os.path.join(MODEL, "tabpfn_meta.json"))).get("replay_precompute", meta["replay_precompute"])
json.dump(meta, open(os.path.join(MODEL, "tabpfn_meta.json"), "w"), indent=1, ensure_ascii=False)
print("thresholds", meta["threshold"])
