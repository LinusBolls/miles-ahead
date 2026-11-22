"""Out-of-time test on REAL November 2026 Berlin ride ends + TabPFN context refresh ("swap the context, no retraining").

Data: the live scraper's Postgres on bolls (read-only snapshot), vehicle_changes since 2026-11-21 13:05 UTC.
Ride ends and the 11 TabPFN features are rebuilt exactly as the live scorer does (backend/app/live.py + main.py
strand_loop + strand_tabpfn.featurize). Label = idle_h > 12, idle_h = time to the vehicle's next status change
(same definition as the June 2024 label in build_rideends_allcities.py). Ride ends whose 12 h window is not yet
complete (t0 + 12 h > last scraper row) are dropped (right-censoring).

Stages (each cached, so re-running costs no TabPFN credits unless --rescore):
  --pull     snapshot vehicle_changes / MilesDiscountChange / vehicles from bolls (read-only) into results/oot_2026_raw/
  build      ride-end dataset -> results/oot_2026_rideends.parquet
  score      TabPFN API calls (June context; June+early-2026 context; early-2026-only context) -> results/oot_2026_scores.parquet
  eval       metrics, bootstrap CIs, baselines (June GBM fallback, GBM retrained on the refreshed rows, isotonic)
  plot       results/oot_2026.png

Usage: TABPFN_TOKEN=... python oot_2026.py [--pull] [--rescore] [--split-utc 2026-11-21T18:30]
"""
import argparse, json, math, os, subprocess, sys, time, warnings
from datetime import timedelta

import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BACK = os.path.join(HERE, "..", "backend")
sys.path.insert(0, BACK)
from app.strand_tabpfn import FEATURES, CATEGORICAL, featurize  # noqa: E402

MODEL = os.path.join(HERE, "..", "model")
GEO = os.path.join(BACK, "geo")
RES = os.path.join(HERE, "results")
RAW = os.path.join(RES, "oot_2026_raw")
TZ = "Europe/Berlin"
RIDE = {"USER_IN_RIDE", "PAUSED_BY_USER"}
LIVE_START = pd.Timestamp("2026-11-21 13:10", tz="UTC")   # live TabPFN scoring started
AIRPORT = (52.355, 52.372, 13.495, 13.535)
H = 12.0
SWEEP = (5000, 2000)   # pre-declared June-subsample sizes for the mixed context (all reported, none picked)
JSUB = {}
GAPS = []   # scraper outages found by build()

ap = argparse.ArgumentParser()
ap.add_argument("--pull", action="store_true")
ap.add_argument("--rescore", action="store_true")
ap.add_argument("--split-utc", default=None, help="context/test split; default = time-ordered median ride end")
ap.add_argument("--boot", type=int, default=2000)
a = ap.parse_args()
os.makedirs(RAW, exist_ok=True)

PULL_SQL = {
    "vc": 'select id, at, "milesId", op, old_status, new_status, old_charge, new_charge, old_damage, new_damage, latitude, longitude from vehicle_changes order by id',
    "disc": 'select id, "milesId", time, discount from "MilesDiscountChange" order by id',
    "veh": 'SELECT v."milesId", m.name model, m.electric, s.name size_class, c."milesId" city FROM "MilesVehicle" v '
           'JOIN "MilesVehicleModel" m ON m.id = v."modelId" LEFT JOIN "MilesVehicleSize" s ON s.id = m."sizeId" '
           'LEFT JOIN "MilesCity" c ON c.id = v."firstFoundCityId"',
    "lk": 'select "milesId", status, discounted, updated from "MilesVehicleLastKnown"',
}


def pull():
    for k, sql in PULL_SQL.items():
        cmd = ("cd /opt/miles-scraper && set -a && . ./.env && set +a && docker compose exec -T postgres psql -U $DB_USER -d $DB_NAME "
               f"-v ON_ERROR_STOP=1 -q -c 'BEGIN READ ONLY; COPY ({sql}) TO STDOUT WITH CSV HEADER; COMMIT;' < /dev/null")
        out = subprocess.run(["ssh", "bolls", cmd], capture_output=True, check=True).stdout
        open(os.path.join(RAW, f"oot_{k}.csv"), "wb").write(out)
        print("pulled", k, out.count(b"\n") - 1, "rows")


# ------------------------------------------------------------------ build
def hav_m(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a_ = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 12742000 * math.asin(math.sqrt(a_))


def build():
    vc = pd.read_csv(os.path.join(RAW, "oot_vc.csv"), parse_dates=["at"])
    vc["at"] = pd.to_datetime(vc["at"], utc=True, format="ISO8601")
    veh = pd.read_csv(os.path.join(RAW, "oot_veh.csv")).set_index("milesId")
    veh["electric"] = veh["electric"].map({"t": True, "f": False})
    disc = pd.read_csv(os.path.join(RAW, "oot_disc.csv"))
    disc["time"] = pd.to_datetime(disc["time"]).dt.tz_localize("UTC")
    data_end = vc["at"].max()
    vc = vc.sort_values("id").reset_index(drop=True)

    # --- replay live.py process(): per-vehicle charge/damage state, Berlin ride ends (status) + silent rides
    charge, damage, pos = {}, {}, {}
    ends = []
    city = veh["city"].to_dict()
    for r in vc.itertuples(index=False):
        vid = r.milesId
        if r.new_charge == r.new_charge and r.new_charge is not None:
            charge[vid] = int(round(r.new_charge))
        if r.new_damage == r.new_damage and r.new_damage is not None:
            damage[vid] = r.new_damage
        if city.get(vid) != "BER":
            continue
        if r.new_status == "DEPLOYED_FOR_RENTAL" and r.latitude == r.latitude:
            kind = None
            if r.old_status in RIDE:
                kind = "ride"
            elif r.op == "UPDATE" and r.old_status == "DEPLOYED_FOR_RENTAL" and vid in pos:
                plat, plon = pos[vid]
                if (r.old_charge == r.old_charge and r.new_charge == r.new_charge and r.new_charge < r.old_charge
                        and hav_m(plat, plon, r.latitude, r.longitude) >= 150):
                    kind = "silent_ride"   # live.py: moved >= 150 m AND fuel dropped = undetected customer ride
            if kind:
                ends.append(dict(change_id=r.id, vid=vid, t0=r.at, kind=kind, lat=r.latitude, lon=r.longitude,
                                 charge=charge.get(vid), damage_count=damage.get(vid) or 0))
            pos[vid] = (r.latitude, r.longitude)
        elif r.latitude == r.latitude:
            pos[vid] = (r.latitude, r.longitude)
    df = pd.DataFrame(ends)

    # --- label: next status change of the vehicle after the ride end (June definition: any row where the car is not
    #     DEPLOYED_FOR_RENTAL on either side). Alternative label also ends idle at a silent ride / tow (>= 150 m jump).
    by_v = {v: g for v, g in vc.groupby("milesId")}
    t1, t1_any = [], []
    for e in df.itertuples(index=False):
        g = by_v[e.vid]
        g = g[g["id"] > e.change_id]
        st = g[(g["new_status"] != "DEPLOYED_FOR_RENTAL") | (g["old_status"] != "DEPLOYED_FOR_RENTAL")]
        t1.append(st["at"].iloc[0] if len(st) else pd.NaT)
        mv = g[g["latitude"].notna()]
        jump = mv[[hav_m(e.lat, e.lon, la, lo) >= 150 for la, lo in zip(mv["latitude"], mv["longitude"])]]
        cands = [x for x in [st["at"].iloc[0] if len(st) else None, jump["at"].iloc[0] if len(jump) else None] if x is not None]
        t1_any.append(min(cands) if cands else pd.NaT)
    df["t1"] = pd.to_datetime(t1, utc=True); df["t1_any"] = pd.to_datetime(t1_any, utc=True)
    df["idle_status_h"] = (df["t1"] - df["t0"]).dt.total_seconds() / 3600
    df["idle_h"] = (df["t1_any"] - df["t0"]).dt.total_seconds() / 3600
    df["complete"] = df["t0"] + pd.Timedelta(hours=H) <= data_end
    # Primary label: no status change AND no >= 150 m move within 12 h. In June 2024 the status alone captured ~99% of
    # rides; in Nov 2026 the scraper misses about half of all rides as status changes (silent jumps), so status-only
    # would call a re-rented car "idle". y_status (status-only) is kept as a sensitivity check.
    df["y"] = ((df["idle_h"] > H) | df["idle_h"].isna()).astype(int)
    df["y_status"] = ((df["idle_status_h"] > H) | df["idle_status_h"].isna()).astype(int)
    # Scraper outages (no row at all for > 10 min): ride ends detected in the 15 min burst after an outage have an
    # unknown true end time (dropped); a label is ambiguous when the first idle-ending event was only detected in a
    # post-outage burst and the outage straddles t0 + 12 h (the car may have left before or after the 12 h mark).
    ts = vc["at"].sort_values().reset_index(drop=True)
    dt_ = ts.diff()
    gaps = [(ts[i - 1], ts[i]) for i in dt_[dt_ > pd.Timedelta(minutes=10)].index]
    burst = pd.Timedelta(minutes=15)
    df["post_gap_burst"] = False; df["label_ambiguous"] = False
    for g0, g1 in gaps:
        if g1 - g0 >= pd.Timedelta(minutes=30):   # short outages (< 30 min) shift t0 by < 45 min: kept
            df.loc[(df["t0"] >= g1) & (df["t0"] < g1 + burst), "post_gap_burst"] = True
        te = df["t1_any"]; h12 = df["t0"] + pd.Timedelta(hours=H)
        df.loc[(te >= g1) & (te < g1 + burst) & (h12 > g0) & (h12 < te), "label_ambiguous"] = True
    GAPS[:] = [(str(g0), str(g1), round((g1 - g0).total_seconds() / 3600, 2)) for g0, g1 in gaps]
    json.dump([(str(g0), str(g1), round((g1 - g0).total_seconds() / 3600, 2)) for g0, g1 in gaps],
              open(os.path.join(RES, "oot_2026_scraper_gaps.json"), "w"), indent=1)

    # --- discounted: live strand_loop reads MilesVehicleLastKnown.discounted at batch time (<= 60 s after the ride end);
    #     reconstructed as-of t0 + 60 s from the discount change log (discounted = discount != NONE)
    disc = disc.sort_values("time")
    dd = pd.merge_asof(df.assign(tq=df["t0"] + pd.Timedelta(seconds=60)).sort_values("tq"), disc[["milesId", "time", "discount"]],
                       left_on="tq", right_on="time", left_by="vid", right_by="milesId", direction="backward")
    df = dd.drop(columns=["tq", "milesId", "time"]).sort_values("change_id").reset_index(drop=True)
    # MilesVehicleLastKnown.discounted is true exactly for DYNAMIC / 10_ANNIVERSARY (checked on the snapshot), false for
    # NONE and BONUSRIDE-*
    df["discounted"] = (~df["discount"].fillna("NONE").str.match(r"^(NONE|BONUSRIDE)")).astype(int)
    df = df.join(veh[["model", "electric", "size_class"]], on="vid")
    df["airport"] = df["lat"].between(AIRPORT[0], AIRPORT[1]) & df["lon"].between(AIRPORT[2], AIRPORT[3])
    tl = df["t0"].dt.tz_convert(TZ)
    df["hour"], df["dow"] = tl.dt.hour, tl.dt.dayofweek
    meta = json.load(open(os.path.join(MODEL, "tabpfn_meta.json")))
    X = featurize(df.hour.values, df.dow.values, df.charge.values, df.discounted.values, df.damage_count.values,
                  df.size_class.values, df.electric.values, df.model.values, df.lat.values, df.lon.values, meta["model_vocab"])
    for i, f in enumerate(FEATURES):
        df["f_" + f] = X[:, i]
    df["data_end"] = data_end
    df.to_parquet(os.path.join(RES, "oot_2026_rideends.parquet"))
    return df


def gbm_rows(df):
    """Production GBM fallback features (needs the geo classifier, as in engine.park / main.strand_loop)."""
    from app.geo import BerlinGeo
    from app.model import Stranding
    geo = BerlinGeo(os.path.join(GEO, "berlin_geo.pkl.gz"))
    m = Stranding(MODEL, os.path.join(GEO, "cells_berlin.json"))
    cls = geo.classify(df.lat.tolist(), df.lon.tolist())
    rows = []
    for r, c in zip(df.itertuples(index=False), cls):
        tl = r.t0.tz_convert(TZ)
        rows.append(m.features_for(r.lat, r.lon, tl, r.charge, c, r.size_class, r.electric, r.damage_count))
    return m, rows


# ------------------------------------------------------------------ metrics
def ece(y, p, bins=10):
    y, p = np.asarray(y), np.asarray(p)
    idx = np.minimum((p * bins).astype(int), bins - 1)
    return float(sum(abs(y[idx == b].mean() - p[idx == b].mean()) * (idx == b).sum() for b in range(bins) if (idx == b).any()) / len(y))


def metrics(y, p, thr_old=None):
    from sklearn.metrics import roc_auc_score, brier_score_loss
    y, p = np.asarray(y), np.asarray(p, float)
    k = max(1, int(round(0.1 * len(p))))
    top = np.argsort(-p, kind="stable")[:k]
    d = dict(n=int(len(y)), pos=int(y.sum()), base_rate=round(float(y.mean()), 4), auc=round(float(roc_auc_score(y, p)), 4),
             brier=round(float(brier_score_loss(y, p)), 4), ece10=round(ece(y, p), 4), mean_p=round(float(p.mean()), 4),
             p90=round(float(np.quantile(p, 0.9)), 4), top10_precision=round(float(y[top].mean()), 4), top10_n=int(k))
    if thr_old is not None:
        d["thr_old"] = thr_old
        d["flagged_share_at_old_thr"] = round(float((p >= thr_old).mean()), 4)
        fl = p >= thr_old
        d["precision_at_old_thr"] = round(float(y[fl].mean()), 4) if fl.any() else None
    d["thr_for_10pct"] = d["p90"]
    return d


def boot_auc(y, ps, B, seed=0):
    """Bootstrap 95% CIs for AUC per score and paired CIs for differences vs the first score."""
    from sklearn.metrics import roc_auc_score
    rng = np.random.default_rng(seed)
    y = np.asarray(y); n = len(y)
    names = list(ps)
    res = {k: [] for k in names}
    for _ in range(B):
        i = rng.integers(0, n, n)
        if y[i].min() == y[i].max():
            continue
        for k in names:
            res[k].append(roc_auc_score(y[i], ps[k][i]))
    out = {k: [round(float(np.quantile(v, 0.025)), 4), round(float(np.quantile(v, 0.975)), 4)] for k, v in res.items()}
    base = np.array(res[names[0]])
    diff = {f"{k} - {names[0]}": [round(float(np.quantile(np.array(res[k]) - base, q)), 4) for q in (0.025, 0.5, 0.975)] for k in names[1:]}
    return out, diff


def boot_ece(y, p, B, seed=1):
    rng = np.random.default_rng(seed); y = np.asarray(y); p = np.asarray(p); n = len(y)
    v = [ece(y[i], p[i]) for i in (rng.integers(0, n, n) for _ in range(B))]
    return [round(float(np.quantile(v, 0.025)), 4), round(float(np.quantile(v, 0.975)), 4)]


def reliability(y, p, bins=10):
    y, p = np.asarray(y), np.asarray(p)
    idx = np.minimum((p * bins).astype(int), bins - 1)
    return [dict(lo=b / bins, hi=(b + 1) / bins, n=int((idx == b).sum()), mean_p=round(float(p[idx == b].mean()), 4),
                 rate=round(float(y[idx == b].mean()), 4)) for b in range(bins) if (idx == b).any()]


# ------------------------------------------------------------------ TabPFN
class Credits:
    def __init__(self, token):
        from tabpfn_client.client import ServiceClient
        self.sc, self.token = ServiceClient, token
        self.start = self.now()

    def now(self):
        return int(self.sc.get_api_usage(self.token)["current_usage"])


def tabpfn_scores(Xc, yc, Xt, token):
    import tabpfn_client
    tabpfn_client.set_access_token(token)
    clf = tabpfn_client.TabPFNClassifier(random_state=0, categorical_features_indices=CATEGORICAL)
    clf.fit(np.asarray(Xc, float), np.asarray(yc, int))
    return clf.predict_proba(np.asarray(Xt, float))[:, 1]


def main():
    if a.pull:
        pull()
    df = build()
    F = ["f_" + f for f in FEATURES]
    base = df[(df.t0 >= LIVE_START) & df.complete & ~df.airport & ~df.post_gap_burst & ~df.label_ambiguous]
    print(f"ride ends BER total {len(df)}, kinds {df.kind.value_counts().to_dict()}, airport {int(df.airport.sum())}, "
          f"complete {int(df.complete.sum())}, data_end {df.data_end.iloc[0]}")
    d = base.sort_values("t0").reset_index(drop=True)   # primary: every ride end the live service scores (status + silent)
    print(f"evaluation set (status+silent ride ends, live window, complete, no airport/burst/ambiguous): n={len(d)}, base rate {d.y.mean():.3f}, "
          f"t0 {d.t0.min()} .. {d.t0.max()}")
    split = pd.Timestamp(a.split_utc, tz="UTC") if a.split_utc else d.t0.iloc[len(d) // 2]
    early, late = d[d.t0 < split], d[d.t0 >= split]
    print(f"split {split}: early n={len(early)} (base {early.y.mean():.3f}), late n={len(late)} (base {late.y.mean():.3f})")

    z = np.load(os.path.join(MODEL, "tabpfn_context.npz"))
    Xj, yj = z["X"], z["y"]
    rng = np.random.default_rng(0)
    JSUB.update({k_: np.sort(rng.choice(len(yj), k_, replace=False)) for k_ in SWEEP})
    meta = json.load(open(os.path.join(MODEL, "tabpfn_meta.json")))
    thr_t, thr_g = meta["threshold"]["tabpfn"], meta["threshold"]["gbm"]

    sp = os.path.join(RES, "oot_2026_scores.parquet")
    cached = pd.read_parquet(sp) if os.path.exists(sp) and not a.rescore else None
    cp = os.path.join(RES, "oot_2026_calls.json")
    prev = json.load(open(cp)) if os.path.exists(cp) else {}
    need = (cached is None or not set(d.change_id).issubset(set(cached.change_id)) or prev.get("split") != str(split)
            or len(prev.get("calls", [])) != 3 + len(SWEEP))
    calls = []
    if cached is not None and not need:
        sc = cached
        calls = prev["calls"]
    else:
        token = os.environ["TABPFN_TOKEN"]
        cr = Credits(token)
        sc = d[["change_id"]].copy()
        jobs = [("tabpfn_june", Xj, yj, d[F].values, d.index),
                ("tabpfn_june+2026", np.vstack([Xj, early[F].values]), np.concatenate([yj, early.y.values]), late[F].values, late.index),
                ("tabpfn_2026only", early[F].values, early.y.values, late[F].values, late.index)]
        for k_ in SWEEP:
            js = JSUB[k_]
            jobs.append((f"tabpfn_june{k_ // 1000}k+2026", np.vstack([Xj[js], early[F].values]), np.concatenate([yj[js], early.y.values]),
                         late[F].values, late.index))
        for name, Xc, yc, Xt, ix in jobs:
            c0, t0 = cr.now(), time.time()
            if c0 - cr.start > 1_200_000:
                raise SystemExit(f"credit guard: {c0 - cr.start:,} used, stopping before {name}")
            p = tabpfn_scores(Xc, yc, Xt, token)
            sc.loc[ix, name] = p
            c1 = cr.now()
            calls.append(dict(name=name, context_rows=int(len(yc)), context_pos_rate=round(float(np.mean(yc)), 4),
                              test_rows=int(len(Xt)), credits=c1 - c0, seconds=round(time.time() - t0, 1)))
            print(calls[-1])
        sc.attrs["split"] = str(split)
        pd.DataFrame(sc).to_parquet(sp)
        json.dump({"split": str(split), "calls": calls}, open(cp, "w"), indent=1)
    d = d.merge(sc.drop_duplicates("change_id"), on="change_id", how="left")
    early, late = d[d.t0 < split], d[d.t0 >= split]

    # ---- baselines
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.isotonic import IsotonicRegression
    gm, rows = gbm_rows(d)
    d["gbm_june"] = gm.predict(rows)
    cat_mask = [i in CATEGORICAL for i in range(len(FEATURES))]

    def hgb(X, y):
        m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=20,
                                           l2_regularization=1.0, categorical_features=cat_mask, random_state=0)
        Xc = np.nan_to_num(np.asarray(X, float), nan=-1) if False else np.asarray(X, float)
        Xc = Xc.copy()
        for i in CATEGORICAL:
            Xc[:, i] = np.where(np.isnan(Xc[:, i]), np.nan, Xc[:, i])
        return m.fit(Xc, y)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        g_ref = hgb(np.vstack([Xj, early[F].values]), np.concatenate([yj, early.y.values]))
        for k_ in SWEEP:
            g_ = hgb(np.vstack([Xj[JSUB[k_]], early[F].values]), np.concatenate([yj[JSUB[k_]], early.y.values]))
            d.loc[late.index, f"gbm11_june{k_ // 1000}k+2026"] = g_.predict_proba(late[F].values)[:, 1]
        g_26 = hgb(early[F].values, early.y.values)
        g_j = hgb(Xj, yj)
    d.loc[late.index, "gbm11_june+2026"] = g_ref.predict_proba(late[F].values)[:, 1]
    d.loc[late.index, "gbm11_2026only"] = g_26.predict_proba(late[F].values)[:, 1]
    d["gbm11_june10k"] = g_j.predict_proba(d[F].values)[:, 1]
    # isotonic recalibration of the frozen scores, fitted on the early 2026 rows, applied to the late rows
    for col in ("tabpfn_june", "gbm_june"):
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(d.loc[early.index, col], early.y)
        d.loc[late.index, col + "+iso2026"] = iso.predict(d.loc[late.index, col])
    early, late = d[d.t0 < split], d[d.t0 >= split]

    out = {"generated_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "data_end_utc": str(d.data_end.iloc[0]),
           "window_utc": [str(d.t0.min()), str(d.t0.max())], "split_utc": str(split),
           "label": "idle_h > 12, idle_h = time to the vehicle's next status change or next >= 150 m move (= not rented/moved again within 12 h; "
                    "the June 2024 status-only label captured the same thing because that scraper saw ~99% of rides); censored rows dropped",
           "set": "Berlin customer ride ends (USER_IN_RIDE/PAUSED_BY_USER -> DEPLOYED_FOR_RENTAL), live window from 2026-11-21 13:10 UTC, "
                  "airport box excluded (as live)",
           "scraper_outages_utc": GAPS,
           "counts": {"ber_ride_ends_all": int(len(df)), "eval_status_ride_ends": int((d.kind == "ride").sum()),
                      "eval_silent_ride_ends": int((d.kind == "silent_ride").sum()),
                      "post_outage_burst_excluded": int((df.post_gap_burst & (df.t0 >= LIVE_START) & df.complete).sum()),
                      "ambiguous_label_excluded": int((df.label_ambiguous & ~df.post_gap_burst & (df.t0 >= LIVE_START) & df.complete).sum()),
                      "airport_excluded": int((df.airport & (df.t0 >= LIVE_START) & df.complete).sum()),
                      "censored_excluded": int(((df.t0 >= LIVE_START) & ~df.complete).sum()),
                      "eval": int(len(d)), "early": int(len(early)), "late": int(len(late))},
           "feature_coverage_2026": {"model_unknown_to_june_vocab": round(float(d.f_model_code.isna().mean()), 4),
                                     "unknown_models": d.loc[d.f_model_code.isna(), "model"].value_counts().head(10).to_dict(),
                                     "discounted_share": round(float(d.discounted.mean()), 4),
                                     "june_context_discounted_share": round(float(np.nanmean(Xj[:, FEATURES.index("discounted")])), 4),
                                     "charge_missing": round(float(d.f_charge.isna().mean()), 4)},
           "june_reference": {"tabpfn_clean_split": meta["metrics"]["tabpfn_clean_split"], "threshold": meta["threshold"]},
           "tabpfn_calls": calls, "credits_used": int(sum(c["credits"] for c in calls))}

    # 1) frozen June context on ALL 2026 rows
    out["frozen_all"] = {"tabpfn_june": metrics(d.y, d.tabpfn_june, thr_t), "gbm_june_fallback": metrics(d.y, d.gbm_june, thr_g),
                         "gbm11_june10k": metrics(d.y, d.gbm11_june10k)}
    ci, diff = boot_auc(d.y.values, {"tabpfn_june": d.tabpfn_june.values, "gbm_june_fallback": d.gbm_june.values,
                                     "gbm11_june10k": d.gbm11_june10k.values}, a.boot)
    out["frozen_all"]["auc_ci95"], out["frozen_all"]["auc_diff_ci95"] = ci, diff
    out["frozen_all"]["ece_ci95_tabpfn_june"] = boot_ece(d.y.values, d.tabpfn_june.values, a.boot)
    # sensitivity: status-only label (June definition taken literally), and status ride ends only
    out["frozen_all"]["sens_status_only_label"] = metrics(d.y_status, d.tabpfn_june, thr_t)
    st = d[d.kind == "ride"]
    out["frozen_all"]["sens_status_ride_ends_only"] = metrics(st.y, st.tabpfn_june, thr_t)
    out["frozen_all"]["sens_status_ride_ends_only_gbm"] = metrics(st.y, st.gbm_june, thr_g)

    # 2) late rows: frozen vs refreshed context vs baselines (strict time order)
    cols = ["tabpfn_june", "tabpfn_june+2026", "tabpfn_2026only", "tabpfn_june+iso2026", "gbm_june", "gbm_june+iso2026",
            "gbm11_june+2026", "gbm11_2026only"] + [f"{m}_june{k_ // 1000}k+2026" for k_ in SWEEP for m in ("tabpfn", "gbm11")]
    thr_for = {"tabpfn_june": thr_t, "tabpfn_june+2026": thr_t, "tabpfn_2026only": thr_t, "tabpfn_june+iso2026": thr_t,
               "gbm_june": thr_g, "gbm_june+iso2026": thr_g, "gbm11_june+2026": thr_g, "gbm11_2026only": thr_g}
    thr_for.update({f"tabpfn_june{k_ // 1000}k+2026": thr_t for k_ in SWEEP}); thr_for.update({f"gbm11_june{k_ // 1000}k+2026": thr_g for k_ in SWEEP})
    out["late"] = {c: metrics(late.y, late[c], thr_for[c]) for c in cols}
    ci, diff = boot_auc(late.y.values, {c: late[c].values for c in cols}, a.boot)
    out["late_auc_ci95"], out["late_auc_diff_ci95_vs_tabpfn_june"] = ci, diff
    ref = f"tabpfn_june{min(SWEEP) // 1000}k+2026"
    _, out["late_auc_diff_ci95_vs_" + ref] = boot_auc(late.y.values, {ref: late[ref].values, "gbm_june": late["gbm_june"].values,
        f"gbm11_june{min(SWEEP) // 1000}k+2026": late[f"gbm11_june{min(SWEEP) // 1000}k+2026"].values,
        "gbm11_june+2026": late["gbm11_june+2026"].values, "tabpfn_june+iso2026": late["tabpfn_june+iso2026"].values}, a.boot)
    out["late_ece_ci95"] = {c: boot_ece(late.y.values, late[c].values, a.boot) for c in cols if c.startswith("tabpfn")}
    out["late_reliability"] = {c: reliability(late.y, late[c]) for c in ("tabpfn_june", "tabpfn_june+2026", "tabpfn_june2k+2026", "tabpfn_2026only")}
    out["early_frozen"] = metrics(early.y, early.tabpfn_june, thr_t)

    json.dump(out, open(os.path.join(RES, "oot_2026.json"), "w"), indent=1, default=str)
    d.drop(columns=[c for c in d.columns if c.startswith("f_")]).to_parquet(os.path.join(RES, "oot_2026_scored.parquet"))
    plot(out, late)
    write_md(out)
    print(json.dumps({k: out[k] for k in ("counts", "credits_used")}, indent=1))
    for c in cols:
        m = out["late"][c]
        print(f"late {c:22s} AUC {m['auc']:.3f} {out['late_auc_ci95'][c]} ECE {m['ece10']:.3f} flag@old {m.get('flagged_share_at_old_thr')} thr10 {m['p90']:.3f} prec10 {m['top10_precision']:.3f}")
    m = out["frozen_all"]["tabpfn_june"]
    print(f"ALL frozen tabpfn AUC {m['auc']} {out['frozen_all']['auc_ci95']['tabpfn_june']} ECE {m['ece10']} base {m['base_rate']} flag@old {m['flagged_share_at_old_thr']} prec10 {m['top10_precision']}")


def plot(out, late):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(12, 5.2), gridspec_kw={"width_ratios": [1, 1.25]})
    ink, mute = "#1f2328", "#8c959f"
    styles = {"tabpfn_june": ("June 2024 context (frozen)", "#8c959f", "o"),
              "tabpfn_june+2026": ("June 10k + first Nov-2026 hours", "#54aeff", "s"),
              "tabpfn_june2k+2026": ("June 2k + first Nov-2026 hours", "#0550ae", "D"),
              "tabpfn_2026only": ("first Nov-2026 hours only", "#bc4c00", "^")}
    ax.plot([0, 1], [0, 1], ls=":", c=mute, lw=1)
    for c, (lab, col, mk) in styles.items():
        if c == "tabpfn_2026only":
            continue   # in the table (ECE 0.077); left out here to keep the diagram readable
        r = [b for b in out["late_reliability"][c] if b["n"] >= 15]   # bins with < 15 rides are noise
        x = [b["mean_p"] for b in r]; y = [b["rate"] for b in r]
        ax.plot(x, y, c=col, lw=1.6, marker=mk, ms=5, label=f"{lab}  ECE {out['late'][c]['ece10']:.3f}")
        ax.scatter(x, y, s=[8 + 2.5 * math.sqrt(b["n"]) ** 1.5 for b in r], c=col, marker=mk, alpha=0.35, zorder=3, lw=0)
    ax.set_xlim(0, 0.8); ax.set_ylim(0, 0.8)
    ax.set_xlabel("predicted P(idle > 12 h)"); ax.set_ylabel("observed share idle > 12 h")
    ax.set_title(f"Calibration on later Nov-2026 ride ends (n={len(late)}, bins with n>=15)", fontsize=10, color=ink, loc="left")
    ax.legend(fontsize=7.5, frameon=False, loc="upper left")
    names = [("tabpfn_june", "TabPFN, June 10k ctx (frozen)"), ("tabpfn_june+2026", "TabPFN, June 10k + Nov ctx"),
             ("tabpfn_june5k+2026", "TabPFN, June 5k + Nov ctx"), ("tabpfn_june2k+2026", "TabPFN, June 2k + Nov ctx"),
             ("tabpfn_2026only", "TabPFN, Nov ctx only"),
             ("tabpfn_june+iso2026", "TabPFN June + isotonic(Nov)"), ("gbm_june", "GBM fallback (June 210k)"),
             ("gbm11_june+2026", "GBM retrained June 10k + Nov"), ("gbm11_june5k+2026", "GBM retrained June 5k + Nov"),
             ("gbm11_june2k+2026", "GBM retrained June 2k + Nov"), ("gbm11_2026only", "GBM retrained Nov only")]
    for i, (c, lab) in enumerate(names):
        m, (lo, hi) = out["late"][c]["auc"], out["late_auc_ci95"][c]
        col = "#0969da" if c.startswith("tabpfn") else "#8c959f"
        bx.errorbar(m, i, xerr=[[m - lo], [hi - m]], fmt="o", c=col, capsize=3, lw=1.4)
        bx.text(hi + 0.005, i, f"{m:.3f}", va="center", fontsize=8, color=ink)
    bx.axvline(out["june_reference"]["tabpfn_clean_split"]["auc"], ls="--", c=mute, lw=1)
    bx.text(out["june_reference"]["tabpfn_clean_split"]["auc"] - 0.002, len(names) - 0.6, "June 2024 test AUC", fontsize=7.5, color=mute, ha="right")
    bx.set_yticks(range(len(names))); bx.set_yticklabels([l for _, l in names], fontsize=8); bx.invert_yaxis()
    bx.set_xlabel("AUC with bootstrap 95% CI"); bx.set_title("Ranking, same later Nov-2026 rows", fontsize=10, color=ink, loc="left")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False); bx.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(RES, "oot_2026.png"), dpi=160)


def write_md(o):
    L = o["late"]; F = o["frozen_all"]
    c = o["counts"]

    def row(name, m, ci=None, ece_ci=None):
        return (f"| {name} | {m['n']} | {m['base_rate']:.3f} | {m['auc']:.3f}" + (f" [{ci[0]:.3f}, {ci[1]:.3f}]" if ci else "") +
                f" | {m['ece10']:.3f}" + (f" [{ece_ci[0]:.3f}, {ece_ci[1]:.3f}]" if ece_ci else "") +
                f" | {m['brier']:.3f} | {m['mean_p']:.3f} | {m.get('flagged_share_at_old_thr', '-')} | {m['p90']:.3f} | {m['top10_precision']:.3f} |")
    hdr = "| model | n | base rate | AUC [95% CI] | ECE10 [95% CI] | Brier | mean p | flagged @ old thr | thr for 10% | top-10% precision |\n|---|---|---|---|---|---|---|---|---|---|"
    s = [f"# Out-of-time test on real November 2026 Berlin ride ends\n",
         f"Generated {o['generated_utc']}. Data: live scraper snapshot up to {o['data_end_utc']}. Ride ends {o['window_utc'][0]} .. {o['window_utc'][1]} (UTC).",
         f"Label: {o['label']}. Set: {o['set']}.\n",
         f"Counts: {json.dumps(c)}. TabPFN credits used by the scoring run: {o['credits_used']:,} (all runs while building this analysis: 90,000).\n",
         f"Scraper outages (UTC): {json.dumps(o['scraper_outages_utc'])}.\n",
         "## 1. Frozen June 2024 context on all 2026 rows\n", hdr,
         row("TabPFN, June 10k context (= live)", F["tabpfn_june"], F["auc_ci95"]["tabpfn_june"], F["ece_ci95_tabpfn_june"]),
         row("GBM fallback (June, 13 feat incl. geo)", F["gbm_june_fallback"], F["auc_ci95"]["gbm_june_fallback"]),
         row("GBM on the same June 10k rows, 11 feat", F["gbm11_june10k"], F["auc_ci95"]["gbm11_june10k"]),
         f"\nJune 2024 reference (TabPFN, same context, June 17-22 test): AUC {o['june_reference']['tabpfn_clean_split']['auc']}, "
         f"ECE {o['june_reference']['tabpfn_clean_split']['ece']}, base rate {o['june_reference']['tabpfn_clean_split']['base_rate']}.",
         f"Paired AUC differences vs TabPFN (median, 95% CI): {json.dumps(F['auc_diff_ci95'])}",
         f"Sensitivity (TabPFN June context): status-only label AUC {F['sens_status_only_label']['auc']} (base {F['sens_status_only_label']['base_rate']}); "
         f"status-detected ride ends only AUC {F['sens_status_ride_ends_only']['auc']} (n {F['sens_status_ride_ends_only']['n']}, base {F['sens_status_ride_ends_only']['base_rate']}), "
         f"GBM on them {F['sens_status_ride_ends_only_gbm']['auc']}.\n",
         f"## 2. Context refresh: later rows (t0 >= {o['split_utc']}), strict time order\n",
         "Context = what TabPFN conditions on; no weights are trained. Isotonic and GBM rows are the fair baselines at the same data budget.\n", hdr]
    for k, lab in [("tabpfn_june", "TabPFN, June 10k context (frozen)"), ("tabpfn_june+2026", "TabPFN, June 10k + early Nov rows as context"),
                   ("tabpfn_2026only", "TabPFN, early Nov rows only as context"), ("tabpfn_june+iso2026", "TabPFN frozen + isotonic fit on early Nov"),
                   ("gbm_june", "GBM fallback (June)"), ("gbm_june+iso2026", "GBM fallback + isotonic fit on early Nov"),
                   ("gbm11_june+2026", "GBM retrained on June 10k + early Nov"), ("gbm11_2026only", "GBM retrained on early Nov only")] + \
                  [(f"{m}_june{k_ // 1000}k+2026", f"{'TabPFN context' if m == 'tabpfn' else 'GBM retrained on'}: June {k_ // 1000}k subsample + early Nov")
                   for k_ in SWEEP for m in ("tabpfn", "gbm11")]:
        s.append(row(lab, L[k], o["late_auc_ci95"][k], o["late_ece_ci95"].get(k)))
    s.append(f"\nPaired AUC differences vs frozen TabPFN (2.5%, median, 97.5%): {json.dumps(o['late_auc_diff_ci95_vs_tabpfn_june'])}\n")
    k2 = [k for k in o if k.startswith("late_auc_diff_ci95_vs_tabpfn_june") and k != "late_auc_diff_ci95_vs_tabpfn_june"]
    for k in k2:
        s.append(f"Paired AUC differences, {k[len('late_auc_diff_ci95_vs_'):]} as reference: {json.dumps(o[k])}\n")
    s.append(f"TabPFN calls: {json.dumps(o['tabpfn_calls'])}\n")
    s.append(f"Feature coverage: {json.dumps(o['feature_coverage_2026'])}\n")
    s.append("""## Caveats (read before quoting any number)

- One day of data. Labelled ride ends cover only 2026-11-21 13:16-16:50 and 21:27-21:46 UTC (Saturday afternoon + early evening).
  The scraper was down 16:50-21:12 UTC (and 01:21-04:08, 06:26-08:20 UTC overnight); ride ends detected in the 15 min after an
  outage have an unknown true end time and are dropped; 7 labels that an outage made ambiguous are dropped.
- Label. In Nov 2026 the scraper sees only about half of all rides as status changes (the rest are "silent" jumps: the car
  reappears >= 150 m away, median 5.7 km, 87% with a fuel drop). The label therefore ends the idle period at the next status
  change OR the next >= 150 m move. Status-only would mark re-rented cars as idle (base rate 38%, nonsense). In June 2024 status
  alone matched 99% of rides, so this is the same quantity ("not rented again within 12 h"), measured with a weaker scraper.
- The live service does not store per-ride-end scores (and restarted on 2026-11-22 09:10 UTC, which re-scored history with the GBM),
  so the frozen-context scores were recomputed with the same frozen 10k June context, random_state=0, same 11 features.
- The refresh is an optimistic simulation of "yesterday's rows in today's context": the context rows' labels (12 h windows) are only
  known up to 12 h after each ride end, so in strict operation those rows could not yet be used for the later rows of the SAME day.
  Context and test also share the same evening/night. Isotonic and retrained GBM baselines get exactly the same early rows.
- Early (context) rows are afternoon (base rate 7%), later rows run into the evening (15%): time-of-day differs between context and test.
  This is why the Nov-only context is badly calibrated.
- The June 5k/2k subsample sizes were chosen after seeing the 10k and 0k results. All sizes tried are reported; none were dropped.
- 71% of 2026 ride ends are car models that do not exist in the June vocabulary (VW Polo GP, Opel Corsa Hybrid, Opel Astra ST,
  Toyota Yaris Cross Hybrid), so model_code is missing for them in live scoring too.
""")
    open(os.path.join(RES, "oot_2026.md"), "w").write("\n".join(s))


if __name__ == "__main__":
    main()
