"""E2 - DESTINATION: where does a car picked up at (x, t) get driven to? Berlin, TabPFN classification over 10 zones.

Trips are reconstructed from rideends_allcities_2024-06.parquet (no separate start position column):
  pickup  = a ride end's position, at time ride_end + idle_h (the car stood there until its next rental started)
  dest    = the same vehicle's NEXT ride-end position
  kept if the next ride lasts 2 min .. 4 h (longer gaps are missed events or multi-day rentals).
Zones: k-means (k = 10, random_state = 0) on TRAIN destination positions (km grid around the centre).
Split: pickups June 3-16 (train/context), June 17-22 with arrival before June 23 (test). Time-based, no leakage.
Features known at pickup: hour, dow, x_km, y_km, dist_center_km, origin zone, size_code, electric, model_code, charge,
idle_before_h (how long the car had stood).
Models: TabPFNClassifier (API, 10k random context, random_state=0) vs HistGradientBoosting at 10k (same rows) and full
train; baselines: origin-zone historical frequency and origin-zone x 3h-bucket frequency (both on full train).
Metrics: top-1 / top-3 accuracy, log loss, mean km from the true destination to the centroid of the top-1 zone.
Usage: TABPFN_TOKEN=... python dest_tabpfn.py [--test-n 10000] [--no-api]
"""
import argparse, json, os, sys, time
import numpy as np, pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import log_loss

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
from app.strand_tabpfn import CENTER, KM_LAT, KM_LON, SIZES  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--test-n", type=int, default=10000)
ap.add_argument("--no-api", action="store_true")
a = ap.parse_args()
R = os.path.join(HERE, "results"); C = os.path.join(R, "cache"); os.makedirs(C, exist_ok=True)
TZ = "Europe/Berlin"
SPLIT = pd.Timestamp("2024-06-17", tz=TZ); END = pd.Timestamp("2024-06-23", tz=TZ)
K = 10

d = pd.read_parquet(os.path.join(HERE, "rideends_allcities_2024-06.parquet"))
b = d[d.city == "BER"].sort_values(["vehicle_id", "ride_end_utc"]).copy()
g = b.groupby("vehicle_id")
b["dlat"] = g.lat.shift(-1); b["dlon"] = g.lon.shift(-1); b["dend"] = g.ride_end_utc.shift(-1)
b["pick_utc"] = b.ride_end_utc + pd.to_timedelta(b.idle_h, unit="h")
b["dur_min"] = (b.dend - b.pick_utc).dt.total_seconds() / 60
b = b[b.dend.notna() & (b.dur_min >= 2) & (b.dur_min <= 240)].copy()
b["tp"] = b.pick_utc.dt.tz_localize("UTC").dt.tz_convert(TZ)
b["tend"] = b.dend.dt.tz_localize("UTC").dt.tz_convert(TZ)
b = b[b.tend < END]
for p, la, lo in (("o", "lat", "lon"), ("d", "dlat", "dlon")):
    b[p + "y"] = (b[la] - CENTER[0]) * KM_LAT; b[p + "x"] = (b[lo] - CENTER[1]) * KM_LON
b["trip_km"] = np.hypot(b.dx - b.ox, b.dy - b.oy)
train = b[b.tp < SPLIT]; test_all = b[b.tp >= SPLIT]
km = KMeans(K, random_state=0, n_init=10).fit(train[["dx", "dy"]].values)
cent = km.cluster_centers_
for df in (train, test_all):
    df["dz"] = km.predict(df[["dx", "dy"]].values); df["oz"] = km.predict(df[["ox", "oy"]].values)
vocab = {m: i for i, m in enumerate(train.model.value_counts().index)}
FEATS = ["hour", "dow", "ox", "oy", "dist_c", "oz", "size_code", "electric", "model_code", "charge", "idle_before_h"]
CAT = [FEATS.index("oz"), FEATS.index("size_code"), FEATS.index("model_code")]


def X_of(df):
    return np.column_stack([df.tp.dt.hour, df.tp.dt.dayofweek, df.ox, df.oy, np.hypot(df.ox, df.oy), df.oz,
                            [SIZES.index(s) if s in SIZES else np.nan for s in df.size_class], df.electric,
                            [vocab.get(m, np.nan) for m in df.model], df.charge, df.idle_h.clip(upper=48)]).astype(float)


ctx = train.sample(10000, random_state=0)
test = test_all.sample(min(a.test_n, len(test_all)), random_state=0)
Xc, Xt, Xtr = X_of(ctx), X_of(test), X_of(train)
yc, yt, ytr = ctx.dz.values, test.dz.values, train.dz.values
np.savez_compressed(os.path.join(C, "dest_arrays.npz"), Xc=Xc, yc=yc, Xt=Xt)
print(f"trips train {len(train)}, test week {len(test_all)} -> scored {len(test)}; median trip {b.trip_km.median():.1f} km; "
      f"same-zone share test {(test.dz == test.oz).mean():.3f}")
print("zone sizes (train dest):", np.bincount(ytr, minlength=K).tolist())

credits = []


def usage():
    from tabpfn_client.client import ServiceClient
    from tabpfn_client.config import get_access_token
    return int(ServiceClient.get_api_usage(get_access_token())["current_usage"])


P = {}
cp = os.path.join(C, "dest_tab_clf_10k.npz")
if os.path.exists(cp):
    P["TabPFN 10k"] = np.load(cp)["p"]
else:
    if a.no_api:
        raise SystemExit("no cache")
    import tabpfn_client
    tabpfn_client.set_access_token(os.environ["TABPFN_TOKEN"])
    u0 = usage(); t0 = time.time()
    # one INTERNAL_ERROR was seen on the first try: retry, then fall back to no categorical hints
    for attempt, cat in enumerate((CAT, CAT, None)):
        try:
            m = tabpfn_client.TabPFNClassifier(random_state=0, categorical_features_indices=cat).fit(Xc, yc.astype(np.int64))
            # 10k test rows x 10 classes in one call failed server-side (INTERNAL_ERROR); 5k chunks work
            p = np.vstack([m.predict_proba(Xt[k:k + 5000]) for k in range(0, len(Xt), 5000)])
            print(f"dest TabPFN ok on attempt {attempt + 1}, categorical={cat}")
            break
        except Exception as ex:
            print("retry", attempt, type(ex).__name__, str(ex).replace(os.environ["TABPFN_TOKEN"], "***")[:160]); time.sleep(5)
    else:
        raise SystemExit("TabPFN API failed 3x")
    pf = np.zeros((len(Xt), K)); pf[:, m.classes_.astype(int)] = p
    P["TabPFN 10k"] = pf
    np.savez_compressed(cp, p=pf)
    credits.append({"call": "dest_tab_clf_10k", "credits": usage() - u0, "s": round(time.time() - t0, 1)}); print(credits[-1])


def gbm(X, y):
    cat = np.zeros(X.shape[1], bool); cat[CAT] = True
    m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, categorical_features=cat, random_state=0).fit(X, y)
    pf = np.zeros((len(Xt), K)); pf[:, m.classes_] = m.predict_proba(Xt); return pf


P["GBM 10k"] = gbm(Xc, yc)
P[f"GBM full ({len(train) // 1000}k)"] = gbm(Xtr, ytr)


def freq(keys_tr, keys_te, alpha=1.0):
    glob = np.bincount(ytr, minlength=K) / len(ytr)
    tab = pd.crosstab(keys_tr, ytr).reindex(columns=range(K), fill_value=0)
    out = np.tile(glob, (len(keys_te), 1))
    for i, k in enumerate(keys_te):
        if k in tab.index:
            c = tab.loc[k].values; out[i] = (c + alpha * glob * K) / (c.sum() + alpha * K)
    return out


P["Origin-zone frequency (full train)"] = freq(train.oz.values, test.oz.values)
P["Origin-zone x 3h frequency (full train)"] = freq(train.oz.values * 10 + train.tp.dt.hour.values // 3,
                                                   test.oz.values * 10 + test.tp.dt.hour.values // 3)
rows = []
for name, p in P.items():
    p = np.clip(p, 1e-6, 1); p = p / p.sum(1, keepdims=True)
    top = np.argsort(-p, 1)
    top1 = top[:, 0]
    rows.append({"model": name, "top1_acc": float(np.mean(top1 == yt)), "top3_acc": float(np.mean((top[:, :3] == yt[:, None]).any(1))),
                 "log_loss": float(log_loss(yt, p, labels=range(K))),
                 "km_true_to_top1_centroid": float(np.mean(np.hypot(test.dx.values - cent[top1, 0], test.dy.values - cent[top1, 1]))),
                 "km_true_to_expected_point": float(np.mean(np.hypot(test.dx.values - p @ cent[:, 0], test.dy.values - p @ cent[:, 1])))})
res = pd.DataFrame(rows)
print(res.round(3).to_string(index=False))
res.to_csv(os.path.join(R, "dest_e2_metrics.csv"), index=False)
json.dump({"k_zones": K, "zone_centroids_km": cent.round(2).tolist(), "train_trips": int(len(train)), "test_week_trips": int(len(test_all)),
           "test_n": int(len(test)), "api_calls": credits, "features": FEATS}, open(os.path.join(R, "dest_e2_summary.json"), "w"), indent=1)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(7, 3.6))
order = res.sort_values("top3_acc").reset_index(drop=True)
cols = ["#2f6fdd" if m.startswith("TabPFN") else "#d1792b" if m.startswith("GBM") else "#8c959f" for m in order.model]
ax.barh(order.model, order.top3_acc, color=cols, alpha=.35, label="top-3")
ax.barh(order.model, order.top1_acc, color=cols, label="top-1")
for i, r in order.iterrows():
    ax.text(r.top3_acc + .005, i, f"{r.top1_acc:.0%} / {r.top3_acc:.0%}", va="center", fontsize=8)
ax.set_xlim(0, 1); ax.set_xlabel("accuracy, test week June 17-22 (10 destination zones)")
ax.spines[["top", "right"]].set_visible(False)
ax.set_title("Where will the next renter drive this car? top-1 / top-3", loc="left", fontsize=10)
fig.tight_layout(); fig.savefig(os.path.join(R, "dest_e2_accuracy.png"), dpi=160)
