"""E3 - COLD START for the value term (idle hours until next rental, capped at 48 h) in a new city.

A new city has n local ride ends (n = 50 / 200 / 1000, sampled from its June 3-16), test = its June 17-22 (2,000 rows).
Features are city-agnostic: hour, dow, charge, discounted, damage_count, size_code, electric, dist_center_km, x_km, y_km
(centre = median of the n local training rows, as in coldstart.py), plus is_target_city (0 Berlin / 1 target) where the
context mixes cities.
Models:
  TabPFN local          TabPFNRegressor, context = the n local rows only
  TabPFN Berlin+local   TabPFNRegressor, context = 5,000 Berlin rows (June 3-16, random_state=0) + the n local rows
  GBM local             HistGradientBoosting quantile models on the n local rows
  GBM Berlin-transfer   HistGradientBoosting quantile models on 20k Berlin June 3-16 rows, applied as is (no local data)
  (GBM Berlin+local was dropped: 19 quantile refits on 20k rows per n x seed did not fit the time box.)
Metrics: CRPS (19-quantile approximation, hours), MAE of the median, 80% interval coverage. 3 seeds per n.
Usage: TABPFN_TOKEN=... python coldstart_value.py [--cities HAM,DUS] [--seeds 3]
"""
import argparse, json, os, time
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

ap = argparse.ArgumentParser()
ap.add_argument("--cities", default="HAM,DUS"); ap.add_argument("--seeds", type=int, default=3)
ap.add_argument("--ns", default="50,200,1000"); ap.add_argument("--no-api", action="store_true")
ap.add_argument("--plot-only", action="store_true", help="redraw the figure from results/value_e3_coldstart.csv")
a = ap.parse_args()
HERE = os.path.dirname(os.path.abspath(__file__)); R = os.path.join(HERE, "results"); C = os.path.join(R, "cache")
os.makedirs(C, exist_ok=True)
QS = np.round(np.arange(0.05, 0.951, 0.05), 2); I10, I50, I90 = 1, 9, 17
TZ = "Europe/Berlin"; CAP = 48.0
SIZES = ["L", "M", "P", "S", "X"]



def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sm = pd.read_csv(os.path.join(R, "value_e3_coldstart.csv"))
    sty = {"TabPFN Berlin+local": ("#2f6fdd", "-"), "TabPFN local": ("#2f6fdd", "--"), "GBM local": ("#d1792b", "--"),
           "GBM Berlin-transfer": ("#8a5a2b", ":")}
    cities = list(dict.fromkeys(sm.city))
    fig, ax = plt.subplots(1, len(cities), figsize=(5 * len(cities), 3.8))
    for x, city in zip(np.atleast_1d(ax), cities):
        for m, (c, ls) in sty.items():
            s_ = sm[(sm.city == city) & (sm.model == m)].sort_values("n")
            x.plot(s_.n, s_.crps, "o" + ls, color=c, label=m, ms=4)
        x.set_xscale("log"); x.set_xlabel(f"local ride ends in {city} (n)"); x.set_ylabel("CRPS, hours (lower is better)")
        x.set_title(f"New city {city}: idle-time distribution, test June 17-22", loc="left", fontsize=10)
        x.spines[["top", "right"]].set_visible(False)
    np.atleast_1d(ax)[0].legend(frameon=False, fontsize=8)
    fig.tight_layout(); fig.savefig(os.path.join(R, "value_e3_coldstart.png"), dpi=160)


if a.plot_only:
    plot(); raise SystemExit

df = pd.read_parquet(os.path.join(HERE, "rideends_allcities_2024-06.parquet"))
df["t"] = pd.to_datetime(df.ride_end_utc).dt.tz_localize("UTC").dt.tz_convert(TZ)
df = df[df.t < pd.Timestamp("2024-06-23", tz=TZ)].copy()
df["y"] = df.idle_h.clip(upper=CAP)
df["early"] = df.t < pd.Timestamp("2024-06-17", tz=TZ)
SIZE_CODE = {s: i for i, s in enumerate(SIZES)}


def feats(d, centre, flag):
    yk = (d.lat.values - centre[0]) * 111.2; xk = (d.lon.values - centre[1]) * 111.2 * np.cos(np.radians(centre[0]))
    return np.column_stack([d.t.dt.hour, d.t.dt.dayofweek, d.charge, d.discounted, d.damage_count,
                            d.size_class.map(SIZE_CODE).astype(float), d.electric, np.hypot(xk, yk), xk, yk,
                            np.full(len(d), flag, float)]).astype(float)


CAT = [5]
ber = df[(df.city == "BER") & df.early]
bc = (ber.lat.median(), ber.lon.median())
bgb = ber.sample(20000, random_state=1)            # GBM Berlin rows (20k, as in coldstart.py, keeps 18 refits fast)
Xb_all = feats(bgb, bc, 0); yb_all = bgb.y.values
bctx = ber.sample(5000, random_state=0); Xb5, yb5 = feats(bctx, bc, 0), bctx.y.values


def usage():
    from tabpfn_client.client import ServiceClient
    from tabpfn_client.config import get_access_token
    return int(ServiceClient.get_api_usage(get_access_token())["current_usage"])


if not a.no_api:
    import tabpfn_client
    tabpfn_client.set_access_token(os.environ["TABPFN_TOKEN"]); u_start = usage()


def tab(name, Xc, yc, Xt):
    p = os.path.join(C, name + ".npz")
    if os.path.exists(p):
        return np.load(p)["q"]
    if a.no_api:
        raise SystemExit("no cache " + name)
    import tabpfn_client
    for attempt in range(3):
        try:
            m = tabpfn_client.TabPFNRegressor(random_state=0, categorical_features_indices=CAT).fit(Xc, yc)
            q = np.asarray(m.predict(Xt, output_type="quantiles", quantiles=list(QS)))
            break
        except Exception as ex:
            print("retry", attempt, type(ex).__name__); time.sleep(5)
    else:
        raise SystemExit("API failed")
    q = q.T if q.shape[0] != len(Xt) else q
    np.savez_compressed(p, q=q); return q


def gbm(X, y, Xt):
    n = len(X)
    kw = dict(max_iter=300 if n > 2000 else 150, learning_rate=0.05, random_state=0, min_samples_leaf=max(5, min(20, n // 50)),
              categorical_features=[i in CAT for i in range(X.shape[1])])
    return np.column_stack([HistGradientBoostingRegressor(loss="quantile", quantile=float(al), **kw).fit(X, y).predict(Xt) for al in QS])


def score(y, q):
    q = np.sort(q, 1); E = y[:, None] - q
    return {"crps": float(2 * np.mean(np.maximum(QS * E, (QS - 1) * E))), "mae": float(np.mean(np.abs(y - q[:, I50]))),
            "cover80": float(np.mean((y >= q[:, I10]) & (y <= q[:, I90])))}


rows = []
gbm_ber_cache = {}
for city in a.cities.split(","):
    cd = df[df.city == city]; pool, test = cd[cd.early], cd[~cd.early].sample(2000, random_state=0)
    yt = test.y.values
    for n in map(int, a.ns.split(",")):
        for seed in range(a.seeds):
            tr = pool.sample(n, random_state=seed); cc = (tr.lat.median(), tr.lon.median())
            Xl, yl, Xt = feats(tr, cc, 1), tr.y.values, feats(test, cc, 1)
            res = {"city": city, "n": n, "seed": seed}
            for nm, q in (("TabPFN local", tab(f"cs_{city}_{n}_{seed}_local", Xl, yl, Xt)),
                          ("TabPFN Berlin+local", tab(f"cs_{city}_{n}_{seed}_berlocal", np.vstack([Xb5, Xl]), np.r_[yb5, yl], Xt)),
                          ("GBM local", gbm(Xl, yl, Xt))):
                for k, v in score(yt, q).items():
                    res[f"{nm}|{k}"] = v
            # Berlin-only GBM, applied with the target city's centre from the n local rows
            Xt0 = Xt.copy(); Xt0[:, -1] = 0
            key = "ber"
            if key not in gbm_ber_cache:
                gbm_ber_cache[key] = [HistGradientBoostingRegressor(loss="quantile", quantile=float(al), max_iter=300, learning_rate=0.05,
                                                                    random_state=0, categorical_features=[i in CAT for i in range(Xb_all.shape[1])]).fit(Xb_all, yb_all) for al in QS]
            qb = np.column_stack([m.predict(Xt0) for m in gbm_ber_cache[key]])
            for k, v in score(yt, qb).items():
                res[f"GBM Berlin-transfer|{k}"] = v
            rows.append(res); print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in res.items() if "crps" in k or k in ("city", "n", "seed")}), flush=True)
r = pd.DataFrame(rows)
r.to_csv(os.path.join(R, "value_e3_coldstart_raw.csv"), index=False)
long = r.melt(id_vars=["city", "n", "seed"]); long[["model", "metric"]] = long.variable.str.split("|", expand=True)
summ = long.groupby(["city", "n", "model", "metric"]).value.mean().unstack("metric").reset_index()
summ.to_csv(os.path.join(R, "value_e3_coldstart.csv"), index=False)
print(summ.round(3).to_string(index=False))
if not a.no_api:
    print("credits used this run:", usage() - u_start)
plot()
