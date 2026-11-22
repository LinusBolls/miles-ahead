"""E1 - the VALUE term: TabPFN regression of the time until the next rental after a ride end (Berlin).

Target: idle_h = hours from a ride end until that car's next status change (~ next rental), right-censored (capped) at 48 h.
Split (time-based, no leakage): context/train = ride ends June 3-16 2024, test = ride ends June 17-22 (data cut June 23 00:00).
Features (all known at the ride-end moment):
  base   = the live stranding classifier's 11 raw features (hour, dow, charge, discounted, damage_count, size_code, electric,
           model_code, dist_center_km, x_km, y_km), via app/strand_tabpfn.featurize
  demand = base + deps_24h (rental starts in the 3x3 ~500 m cells around the car in the 24 h BEFORE the ride end)
                + free_cars (cars parked and not yet rented in the same neighbourhood AT the ride end)
           Only events strictly before t are used. Warm-up caveat: the data starts June 3 00:00, so on June 3 the 24 h
           look-back and the parked-car count are truncated.
Models:
  TabPFNRegressor (tabpfn-client, Prior Labs API), 10k random context (random_state=0, same rows as the live classifier),
  predictive distribution read as 19 quantiles (0.05..0.95) + mean.
  GBM = sklearn HistGradientBoostingRegressor, quantile loss at the same 19 levels (+ squared error for the mean),
  at the SAME budget (the same 10k rows) and at the FULL budget (all 210k train rows). LightGBM is not used (no libomp here).
  TabPFNClassifier (same context, label idle > 12 h) on the same test rows, to compare with P(idle > 12 h) derived from
  the regressor.
  Data-efficiency curve: TabPFN vs GBM at n = 500 / 2,000 / 10,000 train rows (base features).
Outputs: results/value_e1_*.{csv,json}, results/value_e1_*.png. API outputs are cached in results/cache/ so reruns are free.
Usage: TABPFN_TOKEN=... python value_tabpfn.py [--test-n 20000] [--no-api]
The token is read from the env and never printed.
"""
import argparse, json, os, sys, time
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import roc_auc_score, brier_score_loss

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
from app.strand_tabpfn import FEATURES, CATEGORICAL, featurize  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--test-n", type=int, default=20000)
ap.add_argument("--no-api", action="store_true")
ap.add_argument("--curve", default="500,2000,10000")
a = ap.parse_args()

R = os.path.join(HERE, "results"); C = os.path.join(R, "cache")
os.makedirs(C, exist_ok=True)
TZ = "Europe/Berlin"
SPLIT = pd.Timestamp("2024-06-17", tz=TZ); END = pd.Timestamp("2024-06-23", tz=TZ)
CAP = 48.0
QS = np.round(np.arange(0.05, 0.951, 0.05), 2)          # 19 quantile levels
I10, I25, I50, I75, I90 = [int(np.where(QS == q)[0][0]) for q in (0.1, 0.25, 0.5, 0.75, 0.9)]
H_LIST = [2, 6, 12, 24]

# ---------------- data + features ----------------
d = pd.read_parquet(os.path.join(HERE, "rideends_allcities_2024-06.parquet"))
ber = d[d.city == "BER"].copy()
ber["t"] = pd.to_datetime(ber.ride_end_utc).dt.tz_localize("UTC").dt.tz_convert(TZ)

# demand features from ALL Berlin events (arrivals = ride ends, departures = next rental start at the same spot)
CL, CO = 0.0045, 0.0073                                     # ~500 m cells
arr_t = ber.ride_end_utc.values.astype("datetime64[s]").astype(np.int64)
dep_t = arr_t + (ber.idle_h.values * 3600).astype(np.int64)
ci = np.round(ber.lat.values / CL).astype(np.int64); cj = np.round(ber.lon.values / CO).astype(np.int64)
key = ci * 100000 + cj
order = np.argsort(key, kind="stable")
k_sorted = key[order]
uk, start = np.unique(k_sorted, return_index=True)
end_ = np.r_[start[1:], len(k_sorted)]
A_by, D_by = {}, {}
for k, s, e in zip(uk, start, end_):
    idx = order[s:e]
    A_by[k] = np.sort(arr_t[idx]); D_by[k] = np.sort(dep_t[idx])


def demand_feats(df):
    t = df.ride_end_utc.values.astype("datetime64[s]").astype(np.int64)
    qi = np.round(df.lat.values / CL).astype(np.int64); qj = np.round(df.lon.values / CO).astype(np.int64)
    deps = np.zeros(len(df)); free = np.zeros(len(df))
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            kk = (qi + di) * 100000 + (qj + dj)
            for k in np.unique(kk):
                m = kk == k
                if k not in A_by:
                    continue
                Ak, Dk = A_by[k], D_by[k]
                tt = t[m]
                deps[m] += np.searchsorted(Dk, tt, "left") - np.searchsorted(Dk, tt - 86400, "left")
                free[m] += np.searchsorted(Ak, tt, "left") - np.searchsorted(Dk, tt, "right")
    return deps, np.maximum(free, 0)


ber = ber[ber.t < END].copy()                                # same filtering as backend/build_tabpfn.py
ber["y"] = ber.idle_h.clip(upper=CAP)
train = ber[ber.t < SPLIT]; test_all = ber[ber.t >= SPLIT]
vc = train.model.value_counts(); vocab = {m: i for i, m in enumerate(vc.index)}
ctx = train.sample(10000, random_state=0)                    # identical rows to the live classifier's context
test = test_all.sample(min(a.test_n, len(test_all)), random_state=0)
print(f"train {len(train)} (ctx 10k), test week {len(test_all)} -> scored {len(test)}; cap {CAP} h; "
      f"censored share test {(test.idle_h >= CAP).mean():.3f}")


def X_of(df, demand):
    t = df.t
    X = featurize(t.dt.hour.values, t.dt.dayofweek.values, df.charge.values, df.discounted.values, df.damage_count.values,
                  df.size_class.values, df.electric.values, df.model.values, df.lat.values, df.lon.values, vocab)
    if demand:
        dp, fr = demand_feats(df)
        X = np.column_stack([X, dp, fr])
    return X


t0 = time.time()
X = {}
for dm in (False, True):
    X[("ctx", dm)] = X_of(ctx, dm); X[("test", dm)] = X_of(test, dm); X[("train", dm)] = X_of(train, dm)
print(f"features built in {time.time() - t0:.0f}s; demand feature medians (test): deps_24h "
      f"{np.median(X[('test', True)][:, -2]):.0f}, free_cars {np.median(X[('test', True)][:, -1]):.0f}")
yc, yt, ytr = ctx.y.values, test.y.values, train.y.values


# ---------------- TabPFN via API (cached) ----------------
credits_log = []


def usage():
    import tabpfn_client
    from tabpfn_client.client import ServiceClient
    from tabpfn_client.config import get_access_token
    return int(ServiceClient.get_api_usage(get_access_token())["current_usage"])


def api_init():
    import tabpfn_client
    tabpfn_client.set_access_token(os.environ["TABPFN_TOKEN"])


def cached(name, fn):
    p = os.path.join(C, name + ".npz")
    if os.path.exists(p):
        return dict(np.load(p))
    if a.no_api:
        raise SystemExit(f"no cache for {name} and --no-api")
    u0 = usage(); t0 = time.time()
    out = fn()
    u1 = usage()
    credits_log.append({"call": name, "credits": u1 - u0, "s": round(time.time() - t0, 1)})
    print(credits_log[-1], flush=True)
    np.savez_compressed(p, **out)
    return out


def tab_reg(Xc, yc_, Xt, cat):
    def f():
        import tabpfn_client
        m = tabpfn_client.TabPFNRegressor(random_state=0, categorical_features_indices=cat)
        m.fit(Xc, yc_)
        o = m.predict(Xt, output_type="main", quantiles=list(QS))
        q = np.column_stack(o["quantiles"]) if isinstance(o["quantiles"], list) else np.asarray(o["quantiles"])
        if q.shape[0] != len(Xt):
            q = q.T
        return {"q": q.astype(np.float32), "mean": np.asarray(o["mean"], np.float32), "median": np.asarray(o["median"], np.float32)}
    return f


def tab_clf(Xc, yc_, Xt, cat):
    def f():
        import tabpfn_client
        m = tabpfn_client.TabPFNClassifier(random_state=0, categorical_features_indices=cat)
        m.fit(Xc, yc_)
        return {"p": m.predict_proba(Xt)[:, 1].astype(np.float32)}
    return f


if not a.no_api:
    api_init()
    u_start = usage()
CAT = list(CATEGORICAL)
pred = {}
pred["TabPFN 10k"] = cached("tab_reg_base_10k", tab_reg(X[("ctx", False)], yc, X[("test", False)], CAT))
pred["TabPFN 10k +demand"] = cached("tab_reg_demand_10k", tab_reg(X[("ctx", True)], yc, X[("test", True)], CAT))
clf = {"base": cached("tab_clf_base_10k", tab_clf(X[("ctx", False)], (yc > 12).astype(int), X[("test", False)], CAT)),
       "demand": cached("tab_clf_demand_10k", tab_clf(X[("ctx", True)], (yc > 12).astype(int), X[("test", True)], CAT))}


# ---------------- GBM baselines ----------------
def gbm_fit_predict(Xtr, ytr_, Xte, seed=0, tuned=False):
    """default: 300 iters, lr 0.05, 31 leaves (sklearn early stopping auto-on above 10k rows).
    tuned: 1000 iters max, lr 0.1, 63 leaves, early stopping on a 10% validation split (patience 20) - a stronger
    configuration picked a priori (no test-set search), to check that GBM is not handicapped."""
    cat = np.zeros(Xtr.shape[1], bool); cat[CAT] = True
    kw = dict(max_iter=300, learning_rate=0.05, categorical_features=cat, random_state=seed,
              min_samples_leaf=max(5, min(20, len(Xtr) // 50)))
    if tuned:
        kw.update(max_iter=1000, learning_rate=0.1, max_leaf_nodes=63, early_stopping=True, validation_fraction=0.1,
                  n_iter_no_change=20)
    q = np.column_stack([HistGradientBoostingRegressor(loss="quantile", quantile=float(al), **kw).fit(Xtr, ytr_).predict(Xte)
                         for al in QS])
    mean = HistGradientBoostingRegressor(loss="squared_error", **kw).fit(Xtr, ytr_).predict(Xte)
    return {"q": q, "mean": mean}


def gbm_cached(name, *args, **kw):
    p = os.path.join(C, "gbm_" + name.replace(" ", "_").replace("(", "").replace(")", "").replace("+", "") + ".npz")
    if os.path.exists(p):
        return dict(np.load(p))
    o = gbm_fit_predict(*args, **kw); np.savez_compressed(p, **o); return o


FULL = f"GBM full ({len(train) // 1000}k)"
for dm, tag in ((False, ""), (True, " +demand")):
    t0 = time.time()
    pred["GBM 10k" + tag] = gbm_cached("GBM 10k" + tag, X[("ctx", dm)], yc, X[("test", dm)])
    pred[FULL + tag] = gbm_cached(FULL + tag, X[("train", dm)], ytr, X[("test", dm)])
    pred["GBM 10k tuned" + tag] = gbm_cached("GBM 10k tuned" + tag, X[("ctx", dm)], yc, X[("test", dm)], tuned=True)
    pred[FULL + " tuned" + tag] = gbm_cached(FULL + " tuned" + tag, X[("train", dm)], ytr, X[("test", dm)], tuned=True)
    print(f"GBMs{tag} in {time.time() - t0:.0f}s", flush=True)


# ---------------- metrics ----------------
def pinball(y, q, al):
    e = y - q
    return float(np.mean(np.maximum(al * e, (al - 1) * e)))


def p_exceed(q, h):
    """P(Y > h) from a quantile grid by linear interpolation of the CDF; clamped to [1-0.95, 1-0.05] outside the grid
    (P(Y>h) for h beyond the grid is reported as <=0.05 / >=0.95 - a resolution limit of a 19-quantile read-out)."""
    out = np.empty(len(q))
    for i, row in enumerate(q):
        out[i] = 1 - np.interp(h, row, QS, left=QS[0] / 2, right=1 - (1 - QS[-1]) / 2)
    return out


def ece(y, p, n=10):
    e, edges = 0.0, np.linspace(0, 1, n + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi) if hi < 1 else (p >= lo)
        if m.any():
            e += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(e)


rows, cover_rows, exceed_rows = [], [], []
per_row = {}
y12 = (yt > 12).astype(int)
for name, o in pred.items():
    q = np.sort(np.asarray(o["q"], float), axis=1)          # fix quantile crossing (GBM)
    o["q"] = q
    med = q[:, I50]
    crps = 2 * np.mean([pinball(yt, q[:, i], al) for i, al in enumerate(QS)])
    E = yt[:, None] - q
    per_row[name] = {"crps": 2 * np.mean(np.maximum(QS * E, (QS - 1) * E), axis=1), "ae": np.abs(yt - med)}
    r = {"model": name, "n_train": 10000 if "10k" in name else len(train), "features": "demand" if "demand" in name else "base",
         "MAE_median_h": np.mean(np.abs(yt - med)), "RMSE_mean_h": np.sqrt(np.mean((yt - np.asarray(o["mean"])) ** 2)),
         "pinball_q10": pinball(yt, q[:, I10], 0.1), "pinball_q50": pinball(yt, q[:, I50], 0.5),
         "pinball_q90": pinball(yt, q[:, I90], 0.9), "CRPS_approx_h": crps,
         "cover80_q10_q90": np.mean((yt >= q[:, I10]) & (yt <= q[:, I90])), "width80_h": np.mean(q[:, I90] - q[:, I10]),
         "cover50_q25_q75": np.mean((yt >= q[:, I25]) & (yt <= q[:, I75]))}
    for h in H_LIST:
        p = p_exceed(q, h); yy = (yt > h).astype(int)
        r[f"AUC_P>{h}h"] = roc_auc_score(yy, p); r[f"ECE_P>{h}h"] = ece(yy, p)
        exceed_rows.append({"model": name, "h": h, "base_rate": yy.mean(), "mean_p": p.mean(), "auc": roc_auc_score(yy, p),
                            "brier": brier_score_loss(yy, p), "ece": ece(yy, p)})
    rows.append(r)
    for i, al in enumerate(QS):
        cover_rows.append({"model": name, "q": al, "frac_below": float(np.mean(yt <= q[:, i]))})

for nm, o in clf.items():
    p = o["p"].astype(float)
    exceed_rows.append({"model": f"TabPFN classifier 10k ({nm})", "h": 12, "base_rate": y12.mean(), "mean_p": p.mean(),
                        "auc": roc_auc_score(y12, p), "brier": brier_score_loss(y12, p), "ece": ece(y12, p)})

res = pd.DataFrame(rows); exc = pd.DataFrame(exceed_rows); cov = pd.DataFrame(cover_rows)
# naive baselines: training-set quantiles (no features) and hour x distance-band historical quantiles
naive_q = np.tile(np.quantile(ytr, QS), (len(yt), 1))
band = lambda df: (df.t.dt.hour.values // 2) * 10 + np.minimum((featurize(df.t.dt.hour.values, df.t.dt.dayofweek.values, df.charge.values, df.discounted.values, df.damage_count.values, df.size_class.values, df.electric.values, df.model.values, df.lat.values, df.lon.values, vocab)[:, 8] // 3), 5).astype(int)
btr, bte = band(train), band(test)
tbl = {b: np.quantile(ytr[btr == b], QS) for b in np.unique(btr)}
hist_q = np.array([tbl.get(b, np.quantile(ytr, QS)) for b in bte])
for name, q in (("No features (train quantiles)", naive_q), ("Historical hour x distance-band quantiles (full train)", hist_q)):
    res.loc[len(res)] = {"model": name, "n_train": len(train), "features": "-", "MAE_median_h": np.mean(np.abs(yt - q[:, I50])),
                         "RMSE_mean_h": np.nan, "pinball_q10": pinball(yt, q[:, I10], .1), "pinball_q50": pinball(yt, q[:, I50], .5),
                         "pinball_q90": pinball(yt, q[:, I90], .9), "CRPS_approx_h": 2 * np.mean([pinball(yt, q[:, i], al) for i, al in enumerate(QS)]),
                         "cover80_q10_q90": np.mean((yt >= q[:, I10]) & (yt <= q[:, I90])), "width80_h": np.mean(q[:, I90] - q[:, I10]),
                         "cover50_q25_q75": np.mean((yt >= q[:, I25]) & (yt <= q[:, I75]))}

pd.set_option("display.width", 250)
cols = ["model", "MAE_median_h", "RMSE_mean_h", "pinball_q10", "pinball_q50", "pinball_q90", "CRPS_approx_h", "cover80_q10_q90",
        "width80_h", "cover50_q25_q75", "AUC_P>12h", "ECE_P>12h"]
print(res[cols].round(3).to_string(index=False))
print(exc.round(3).to_string(index=False))
res.to_csv(os.path.join(R, "value_e1_metrics.csv"), index=False)

# paired bootstrap (1,000 resamples of the test rows): TabPFN minus GBM; negative = TabPFN better
rng = np.random.default_rng(0); B = rng.integers(0, len(yt), (1000, len(yt)))
boot = []
for tag in ("", " +demand"):
    ref = per_row["TabPFN 10k" + tag]
    for g in ("GBM 10k", FULL, "GBM 10k tuned", FULL + " tuned"):
        o = per_row[g + tag]
        for met in ("crps", "ae"):
            dlt = ref[met] - o[met]
            bs = dlt[B].mean(1)
            boot.append({"tabpfn": "TabPFN 10k" + tag, "vs": g + tag, "metric": "CRPS_h" if met == "crps" else "MAE_h",
                         "diff": dlt.mean(), "ci95_lo": np.quantile(bs, .025), "ci95_hi": np.quantile(bs, .975)})
bt = pd.DataFrame(boot); print(bt.round(3).to_string(index=False))
bt.to_csv(os.path.join(R, "value_e1_bootstrap.csv"), index=False)
exc.to_csv(os.path.join(R, "value_e1_exceedance.csv"), index=False)
cov.to_csv(os.path.join(R, "value_e1_quantile_calibration.csv"), index=False)

# ---------------- data-efficiency curve (base features) ----------------
curve = []
for n in map(int, a.curve.split(",")):
    sub = train.sample(n, random_state=0) if n != 10000 else ctx
    Xs = X_of(sub, False)
    o = pred["TabPFN 10k"] if n == 10000 else cached(f"tab_reg_base_{n}", tab_reg(Xs, sub.y.values, X[("test", False)], CAT))
    g = pred["GBM 10k"] if n == 10000 else gbm_fit_predict(Xs, sub.y.values, X[("test", False)])
    for name, oo in (("TabPFN", o), ("GBM", g)):
        q = np.sort(np.asarray(oo["q"], float), axis=1)
        curve.append({"model": name, "n": n, "CRPS_approx_h": 2 * np.mean([pinball(yt, q[:, i], al) for i, al in enumerate(QS)]),
                      "MAE_median_h": float(np.mean(np.abs(yt - q[:, I50]))),
                      "cover80": float(np.mean((yt >= q[:, I10]) & (yt <= q[:, I90]))),
                      "AUC_P>12h": roc_auc_score(y12, p_exceed(q, 12))})
gfull = pred[FULL]
curve.append({"model": "GBM", "n": len(train), "CRPS_approx_h": 2 * np.mean([pinball(yt, gfull["q"][:, i], al) for i, al in enumerate(QS)]),
              "MAE_median_h": float(np.mean(np.abs(yt - gfull["q"][:, I50]))),
              "cover80": float(np.mean((yt >= gfull["q"][:, I10]) & (yt <= gfull["q"][:, I90]))),
              "AUC_P>12h": roc_auc_score(y12, p_exceed(gfull["q"], 12))})
cv = pd.DataFrame(curve); print(cv.round(3).to_string(index=False))
cv.to_csv(os.path.join(R, "value_e1_curve.csv"), index=False)

# ---------------- figures ----------------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
INK, MUTED, TAB, GBM_C, GBMF = "#1f2328", "#8c959f", "#2f6fdd", "#d1792b", "#8a5a2b"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": MUTED})

fig, ax = plt.subplots(1, 2, figsize=(10, 4))
for name, c in (("TabPFN", TAB), ("GBM", GBM_C)):
    s = cv[(cv.model == name) & (cv.n <= 10000)].sort_values("n")
    ax[0].plot(s.n, s.CRPS_approx_h, "o-", color=c, label=f"{name} (n train rows)")
    ax[1].plot(s.n, s["AUC_P>12h"], "o-", color=c, label=name)
f = cv[cv.n > 10000].iloc[0]
ax[0].axhline(f.CRPS_approx_h, color=GBMF, ls="--", lw=1, label=f"GBM full ({int(f.n / 1000)}k rows)")
ax[1].axhline(f["AUC_P>12h"], color=GBMF, ls="--", lw=1, label=f"GBM full ({int(f.n / 1000)}k rows)")
ft = res.set_index("model").loc[FULL + " tuned"]
ax[0].axhline(ft.CRPS_approx_h, color=GBMF, ls=":", lw=1.4, label=f"GBM full, tuned ({len(train) // 1000}k rows)")
ax[1].axhline(ft["AUC_P>12h"], color=GBMF, ls=":", lw=1.4, label=f"GBM full, tuned ({len(train) // 1000}k rows)")
for x in ax:
    x.set_xscale("log"); x.set_xlabel("training rows (Berlin ride ends June 3-16)")
ax[0].set_ylabel("CRPS, hours (lower is better)"); ax[1].set_ylabel("AUC of derived P(idle > 12 h)")
ax[0].set_title("Idle-time distribution, test week June 17-22", loc="left", fontsize=10)
ax[1].set_title("Stranding ranking from the regressor", loc="left", fontsize=10)
ax[0].legend(frameon=False, fontsize=8); ax[1].legend(frameon=False, fontsize=8)
fig.tight_layout(); fig.savefig(os.path.join(R, "value_e1_budget.png"), dpi=160); plt.close(fig)

fig, ax = plt.subplots(figsize=(4.8, 4.4))
ax.plot([0, 1], [0, 1], color=MUTED, lw=1, ls=":")
for name, c in (("TabPFN 10k", TAB), ("GBM 10k", GBM_C), (FULL + " tuned", GBMF)):
    s = cov[cov.model == name]
    ax.plot(s.q, s.frac_below, "o-", ms=3, color=c, label=name)
ax.set_xlabel("nominal quantile level"); ax.set_ylabel("share of test ride ends below the predicted quantile")
ax.set_title("Are the predicted quantiles honest?\n(on the diagonal = calibrated)", loc="left", fontsize=10)
ax.legend(frameon=False, fontsize=8); fig.tight_layout(); fig.savefig(os.path.join(R, "value_e1_calibration.png"), dpi=160)
plt.close(fig)

summary = {"split": "context/train ride ends 2024-06-03..16, test 2024-06-17..22 (Berlin)", "cap_h": CAP, "test_n": int(len(test)),
           "test_week_n": int(len(test_all)), "train_n": int(len(train)), "quantiles": QS.tolist(),
           "censored_share_test": float((test.idle_h >= CAP).mean()), "api_calls": credits_log,
           "account_credits_delta_during_run": (usage() - u_start) if not a.no_api else None,
           "credits_note": "account-wide delta: includes the live service and other experiments running at the same time",
           "client": "tabpfn-client " + __import__("importlib.metadata").metadata.version("tabpfn-client")}
json.dump(summary, open(os.path.join(R, "value_e1_summary.json"), "w"), indent=1)
print(json.dumps(summary, indent=1))
