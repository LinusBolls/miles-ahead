"""Weak points W1 ("the idle is intentional coverage") and W2 ("why not a minimum-wage employee"), measured on June 2024
Berlin data. Prints every number used in whitepaper/value_model.md section "Weak points and answers".

Inputs
  miles-ops/backend/geo/replay_berlin_2024-06.parquet   one row per parking period after a customer ride (June 3-22);
        parked_hours = time to next status change; p_tabpfn = out-of-sample TabPFN P(idle>12h) for June 17-22
  miles-ops/analysis/relocations_berlin_2024-06.parquet  staff relocations (relocations_june.py)
Definitions
  next rental of a park = the same vehicle's next park, reached by a customer ride (next_status USER_IN_RIDE/BOOKED_BY_USER)
        km = straight-line km between the two parks; fare = unlock + per-km tariff x km x road factor (ASSUMPTION 1.3)
        tariff (sourced, miles-mobility.com/en-de/pricing, accessed 2026-11-22): S/M EUR 1 + 0.79/km; vans EUR 2 + 1.29/km
  centre/edge = inside_sbahn_ring flag of the park; distance bands from Alexanderplatz (13.405 E, 52.52 N)
  available supply at time t = replay parks with ts <= t < te, plus staff drop-offs idle from t1 until next rental
        (under-counts cars idle after non-customer events other than relocation)
  flagged = June 17-22 parks with p_tabpfn >= 0.4556 (tabpfn_meta.json threshold)
Usage: miles-ops/backend/.venv/bin/python miles-ops/analysis/weak_points.py
"""
import os
import numpy as np, pandas as pd
from scipy.spatial import cKDTree

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TZ = "Europe/Berlin"
SPLIT = pd.Timestamp("2024-06-17", tz=TZ)
THR = 0.4556
CELL = (0.0036, 0.0059)                      # ~400 m
ROAD = 1.3                                   # ASSUMPTION road factor
TAR = {"car": (1.0, 0.79), "van": (2.0, 1.29)}
RHO = 226.96e6 / 19000 / 8760

rp = pd.read_parquet(os.path.join(ROOT, "miles-ops/backend/geo/replay_berlin_2024-06.parquet"))
rp["t"] = pd.to_datetime(rp.parked_from_utc).dt.tz_localize("UTC").dt.tz_convert(TZ)
rp["cls"] = np.where(rp.size_class == "X", "van", "car")
rp["x"] = (rp.longitude - 13.405) * 68.0
rp["y"] = (rp.latitude - 52.52) * 111.0
rp["dc"] = np.hypot(rp.x, rp.y)
rp["band"] = pd.cut(rp.dc, [0, 5, 10, 15, 99], labels=["0-5 km", "5-10 km", "10-15 km", ">15 km"], right=False)
rp["cell"] = np.round(rp.latitude / CELL[0]).astype(np.int64) * 100000 + np.round(rp.longitude / CELL[1]).astype(np.int64)
rp["ts"] = (rp.t - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds() / 3600.0
rp["te"] = rp.ts + rp.parked_hours
rp = rp.sort_values(["vehicle_id", "t"]).reset_index(drop=True)
nxt = rp.groupby("vehicle_id").shift(-1)
rp["n_km"] = np.hypot(nxt.x - rp.x, nxt.y - rp.y)
rp["n_dur_h"] = nxt.ts - rp.te
rp["n_dc"] = nxt.dc
ok = rp.next_status.isin(["USER_IN_RIDE", "BOOKED_BY_USER"]) & nxt.ts.notna() & rp.n_dur_h.between(0.05, 6)
rp.loc[~ok, ["n_km", "n_dur_h", "n_dc"]] = np.nan
unl = np.where(rp.cls == "van", TAR["van"][0], TAR["car"][0])
pkm = np.where(rp.cls == "van", TAR["van"][1], TAR["car"][1])
rp["fare"] = unl + pkm * rp.n_km * ROAD
te = rp[rp.t >= SPLIT]
days_te = (te.t.max() - SPLIT).total_seconds() / 86400
f = te[te.p_tabpfn >= THR].copy()
print(f"parks {len(rp):,}; with a valid next customer rental {ok.sum():,} ({ok.mean():.3f}); flagged June 17-22 {len(f):,} "
      f"= {len(f)/days_te:.0f}/day")

# =========================== W1a: the rental that ends a stranding ===========================
print("\n[W1a] next rental after the park, by idle length and location (straight-line km; fare at tariff x road 1.3)")
v = rp[ok].copy()
v["strand"] = np.where(v.parked_hours > 12, ">12 h idle", "<=12 h idle")
v["zone"] = np.where(v.inside_sbahn_ring, "inside S-Bahn ring", "outside ring")
for keys in (["zone", "strand"], ["band", "strand"]):
    g = v.groupby(keys, observed=True).agg(n=("fare", "size"), km_med=("n_km", "median"), km_mean=("n_km", "mean"),
                                           dur_med_min=("n_dur_h", lambda s: s.median() * 60), fare_mean=("fare", "mean"),
                                           idle_mean=("parked_hours", lambda s: s.clip(upper=48).mean()),
                                           sum_fare=("fare", "sum"),
                                           sum_h=("parked_hours", lambda s: s.clip(upper=48).sum()),
                                           sum_ride=("n_dur_h", "sum"),
                                           dest_dc_med=("n_dc", "median"))
    g["eur_per_cycle_h"] = g.sum_fare / (g.sum_h + g.sum_ride)       # fare per car-hour of (idle + ride)
    g["eur_per_idle_h"] = g.sum_fare / g.sum_h
    print(g[["n", "km_med", "km_mean", "dur_med_min", "fare_mean", "idle_mean", "eur_per_idle_h", "eur_per_cycle_h",
             "dest_dc_med"]].round(2).to_string())
# the same for all parks in a zone (what an hour of car time yields there on average)
for z, g in v.groupby("zone"):
    print(f"  {z}: all parks fare per car-hour of idle+ride {g.fare.sum() / (g.parked_hours.clip(upper=48).sum() + g.n_dur_h.sum()):.2f} EUR"
          f"; share of parks idle >12 h {(g.parked_hours > 12).mean():.3f}")
# flagged cars specifically
fv = f[f.fare.notna()]
fs = fv[fv.parked_hours > 12]
print(f"  flagged cars that stranded (>12 h), next rental: km median {fs.n_km.median():.2f}, fare mean {fs.fare.mean():.2f}, "
      f"idle mean (cap 48) {fs.parked_hours.clip(upper=48).mean():.2f} h -> EUR {fs.fare.sum()/fs.parked_hours.clip(upper=48).sum():.2f} per idle h")
nf = te[(te.p_tabpfn < THR) & te.fare.notna()]
print(f"  non-flagged test parks: fare mean {nf.fare.mean():.2f}, idle mean {nf.parked_hours.clip(upper=48).mean():.2f} h "
      f"-> EUR {nf.fare.sum()/nf.parked_hours.clip(upper=48).sum():.2f} per idle h")
print(f"  flagged outside S-Bahn ring share {(~f.inside_sbahn_ring).mean():.3f}; all test parks outside {(~te.inside_sbahn_ring).mean():.3f}")
# does a longer next rental compensate? break-even: extra fare needed to justify the extra idle at the fleet yield
for zone_in in (True, False):
    a = v[(v.inside_sbahn_ring == zone_in) & (v.parked_hours > 12)]
    b = v[(v.inside_sbahn_ring == zone_in) & (v.parked_hours <= 12)]
    d_fare = a.fare.mean() - b.fare.mean()
    d_idle = a.parked_hours.clip(upper=48).mean() - b.parked_hours.clip(upper=48).mean()
    print(f"  {'inside' if zone_in else 'outside'} ring: stranding-ending rental earns EUR {d_fare:+.2f} more than a normal one "
          f"but costs {d_idle:.1f} extra idle h = EUR {d_idle*RHO:.2f} of average car-time (rho {RHO:.3f})")

# =========================== W1b: does MILES relocate outward? ===========================
rel = pd.read_parquet(os.path.join(ROOT, "miles-ops/analysis/relocations_berlin_2024-06.parquet")).dropna(subset=["dlat"])
rel["dir"] = np.select([rel.dc_d < rel.dc_o - 1, rel.dc_d > rel.dc_o + 1], ["inward >1 km", "outward >1 km"], "lateral +-1 km")
print(f"\n[W1b] staff relocations {len(rel):,}: " + ", ".join(f"{k} {c} ({c/len(rel):.3f})" for k, c in rel.dir.value_counts().items()))
rel["hb"] = pd.cut(rel.hour, [0, 6, 10, 16, 20, 24], right=False, labels=["00-06", "06-10", "10-16", "16-20", "20-24"])
print(pd.crosstab(rel.hb, rel.dir, normalize="index").round(3).to_string())
print(pd.crosstab(rel.hb, rel.dir).to_string())
for k, g in rel.groupby("dir"):
    print(f"  {k}: origin dist median {g.dc_o.median():.1f} km, dest {g.dc_d.median():.1f} km, wait after median "
          f"{g.wait_after_h.median():.2f} h / mean (cap 48) {g.wait_after_h.clip(upper=48).mean():.2f} h, delay median {g.delay_h.median():.1f} h")
ber = np.hypot((rel.dlon - 13.5033) * 68, (rel.dlat - 52.3667) * 111) < 3
txl = np.hypot((rel.dlon - 13.2877) * 68, (rel.dlat - 52.5597) * 111) < 1.5
print(f"  destinations within 3 km of BER airport: {ber.sum()} ({ber.mean():.3f}); outward moves to BER: {(ber & (rel.dir=='outward >1 km')).sum()}")
ob = rel[rel.dir == "outward >1 km"]
print(f"  outward moves ending outside 10 km: {(ob.dc_d > 10).sum()}; starting inside 5 km: {(ob.dc_o < 5).sum()}")

# =========================== W1c: coverage, is the flagged car the last one around? ===========================
sup = pd.DataFrame({"x": rp.x, "y": rp.y, "ts": rp.ts, "te": rp.te, "vid": rp.vehicle_id})
rel["x"] = (rel.dlon - 13.405) * 68; rel["y"] = (rel.dlat - 52.52) * 111
rel["ts"] = (rel.t1 - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds() / 3600.0
sup = pd.concat([sup, pd.DataFrame({"x": rel.x, "y": rel.y, "ts": rel.ts, "te": rel.ts + rel.wait_after_h.fillna(48),
                                    "vid": rel.vehicle_id})], ignore_index=True)
win = (sup.te > f.ts.min() - 1) & (sup.ts < f.ts.max() + 49)
sup = sup[win].reset_index(drop=True)
tree = cKDTree(np.c_[sup.x.values, sup.y.values])
S_ts, S_te, S_vid = sup.ts.values, sup.te.values, sup.vid.values
# customer rental starts (trip origins) for "competing rentals while the flagged car sat"
starts = rp[ok][["x", "y", "te"]].rename(columns={"te": "t0"}).reset_index(drop=True)
stree = cKDTree(np.c_[starts.x.values, starts.y.values])
S0 = starts.t0.values


def neighbours(px, py, t, vid, r, at):
    idx = tree.query_ball_point([px, py], r)
    idx = np.asarray(idx, int)
    m = (S_ts[idx] <= at) & (S_te[idx] > at) & (S_vid[idx] != vid)
    return int(m.sum())


for lab, dt in (("at ride end", 0.0), ("at ride end +0.5 h", 0.5)):
    n5 = np.array([neighbours(a, b, t, i, 0.5, t + dt) for a, b, t, i in zip(f.x, f.y, f.ts, f.vehicle_id)])
    n10 = np.array([neighbours(a, b, t, i, 1.0, t + dt) for a, b, t, i in zip(f.x, f.y, f.ts, f.vehicle_id)])
    f[f"n5_{dt}"], f[f"n10_{dt}"] = n5, n10
    print(f"\n[W1c] flagged cars, other available MILES cars {lab}: within 500 m median {np.median(n5):.0f}, "
          f"share 0 (last car within 500 m) {(n5==0).mean():.3f}; within 1 km median {np.median(n10):.0f}, share 0 {(n10==0).mean():.3f}; "
          f">=3 within 500 m {(n5>=3).mean():.3f}; >=5 within 500 m {(n5>=5).mean():.3f}")
n5, n10 = f["n5_0.5"].values, f["n10_0.5"].values
# competing rentals: customer rentals that started within 500 m while the flagged car was still idle (first 12 h)
comp = []
for a, b, t, h in zip(f.x, f.y, f.ts, f.parked_hours):
    idx = np.asarray(stree.query_ball_point([a, b], 0.5), int)
    tt = S0[idx]
    comp.append(int(((tt > t + 0.05) & (tt < t + min(h, 12))).sum()))
f["comp"] = comp
cls = np.select([n10 == 0, n5 == 0, n5 <= 2], ["sole within 1 km", "sole within 500 m (others <=1 km)", "1-2 others within 500 m"],
                ">=3 others within 500 m")
f["cov"] = cls
g = f.groupby("cov").agg(n=("p_tabpfn", "size"), strand=("parked_hours", lambda s: (s > 12).mean()),
                         idle48=("parked_hours", lambda s: s.clip(upper=48).mean()),
                         idle_h_sum=("parked_hours", lambda s: s.clip(upper=48).sum()),
                         comp_med=("comp", "median"), comp_any=("comp", lambda s: (s > 0).mean()),
                         outside=("inside_sbahn_ring", lambda s: 1 - s.mean()))
g["share"] = g.n / g.n.sum()
g["share_idle_h"] = g.idle_h_sum / g.idle_h_sum.sum()
print(g[["n", "share", "strand", "idle48", "share_idle_h", "comp_med", "comp_any", "outside"]].round(3).to_string())
st = f[f.parked_hours > 12]
print(f"  flagged cars that DID strand: n {len(st):,}; while they sat (first 12 h) another MILES rental started within 500 m in "
      f"{(st.comp>0).mean():.3f} of cases (median {st.comp.median():.0f} rentals)")
sole = (n5 == 0)
print(f"  guard 'no rescue if it leaves the 500 m disc empty' removes {sole.mean():.3f} of flagged cars and "
      f"{f.parked_hours.clip(upper=48)[sole].sum()/f.parked_hours.clip(upper=48).sum():.3f} of their idle hours")
print(f"  guard 'no rescue if it leaves the 1 km disc empty' removes {(n10==0).mean():.3f} of flagged cars")
# demand in sole-coverage discs: rentals per day starting within 500 m (June 3-16 training period)
trs = starts[starts.t0 < f.ts.min()]
ttree = cKDTree(np.c_[trs.x.values, trs.y.values])
d_tr = (f.ts.min() - trs.t0.min()) / 24
dem = np.array([len(ttree.query_ball_point([a, b], 0.5)) for a, b in zip(f.x, f.y)]) / d_tr
f["dem"] = dem
for k, gg in f.groupby("cov"):
    print(f"  {k}: customer rentals starting within 500 m per day (June 3-16) median {gg.dem.median():.1f}")

# =========================== W2: staff alternatives ===========================
print("\n[W2] concentration of flagged ride ends (June 17-22)")
cc = f.groupby("cell").size().sort_values(ascending=False)
ncell = len(cc)
top20 = cc.iloc[: int(np.ceil(0.2 * ncell))].sum() / cc.sum()
print(f"  400 m cells with >=1 flagged car: {ncell}; top 20 % of these cells hold {top20:.3f} of flagged cars; "
      f"cells needed for 50 %: {(cc.cumsum() < 0.5 * cc.sum()).sum() + 1}")
allc = te.groupby("cell").size()
print(f"  (all 400 m cells with any ride end in the test week: {len(allc)})")
for k in (1, 5, 10, 20):
    s = cc.iloc[:k].sum()
    print(f"  top-{k} cells: {s} flagged = {s/cc.sum():.3f} of all = {s/days_te:.1f}/day in total, {s/days_te/k:.1f}/day per cell")
top5 = cc.index[:5]
ff = f[f.cell.isin(top5)]
print(f"  top-5 cells: centroid lat/lon " + "; ".join(f"{f[f.cell==c].latitude.mean():.4f},{f[f.cell==c].longitude.mean():.4f}"
                                                 f" (n={cc[c]}, strand {(f[f.cell==c].parked_hours>12).mean():.2f})" for c in top5))
hr = ff.t.dt.hour.value_counts().sort_index()
print(f"  top-5 flagged by local hour (6 days): " + " ".join(f"{h}:{n}" for h, n in hr.items()))
print(f"  top-5 cells: max flagged per cell per clock hour over the week: {ff.groupby(['cell', ff.t.dt.floor('h')]).size().max()}")
c1 = (np.floor(f.x).astype(int) * 1000 + np.floor(f.y).astype(int))
cc1 = c1.value_counts()
print(f"  1 km cells with flagged cars: {len(cc1)}; top 20 % hold {cc1.iloc[:int(np.ceil(0.2*len(cc1)))].sum()/cc1.sum():.3f}; "
      f"top-5 hold {cc1.iloc[:5].sum()/cc1.sum():.3f} ({cc1.iloc[:5].sum()/days_te:.1f}/day)")
# hour profile of all flagged ride ends (night share)
h = f.t.dt.hour
print(f"  flagged ride ends 22:00-06:00 share {((h>=22)|(h<6)).mean():.3f}; 00-06 {(h<6).mean():.3f}")

# staff at ride end, around the clock
FLAG_DAY = len(f) / days_te
still = (f.parked_hours > 0.5).mean()
moves = FLAG_DAY * still
for lab, hpm, wage in (("low", 0.86, 13.90 * 1.2115), ("high", 1.05, 35.8)):
    sh = moves * hpm
    print(f"  staff at ride end ({lab}): {moves:.0f} moves/day x {hpm} h = {sh:.0f} staff-h/day = {sh/8:.0f} eight-hour shifts/day "
          f"= {sh*365/1650:.0f} FTE (ASSUMPTION 1,650 productive h/FTE/yr); wages EUR {sh*365*wage/1e6:.2f}M/yr")
for lab, ca in (("low", 16.4), ("high", 42.9)):
    print(f"  full cost per move EUR {ca} -> EUR {moves*365*ca/1e6:.2f}M/yr")
print(f"  value of those moves at 9.18 h x rho m: EUR {moves*365*9.18*RHO*0.228/1e6:.2f}M - {moves*365*9.18*RHO*0.793/1e6:.2f}M/yr")
nshift = f.groupby(f.t.dt.hour).size() / days_te
print(f"  flagged per clock hour (mean/day): min {nshift.min():.0f} at {nshift.idxmin()}h, max {nshift.max():.0f} at {nshift.idxmax()}h")

# rescuer's own trip: fare of trips that start within 800 m of a flagged car 0.25-3 h after its ride end (the B pool)
trip_fare = rp[ok][["x", "y", "te", "fare", "n_km"]].reset_index(drop=True)
tt = cKDTree(np.c_[trip_fare.x.values, trip_fare.y.values])
T0, FA, KM = trip_fare.te.values, trip_fare.fare.values, trip_fare.n_km.values
pool_f, pool_k = [], []
for a, b, t in zip(f.x, f.y, f.ts):
    idx = np.asarray(tt.query_ball_point([a, b], 0.8), int)
    m = (T0[idx] >= t + 0.25) & (T0[idx] <= t + 3)
    pool_f.extend(FA[idx][m]); pool_k.extend(KM[idx][m])
pool_f, pool_k = np.array(pool_f), np.array(pool_k)
print(f"\n[W2] rides that start within 800 m of a flagged car 0.25-3 h after its ride end: n {len(pool_f):,}; "
      f"straight km median {np.median(pool_k):.2f}; fare (tariff x road 1.3) median EUR {np.median(pool_f):.2f}, mean {pool_f.mean():.2f}")

# =========================== W2: "station an employee at the top-5 hotspots" ===========================
E2 = 4.93      # mean wait (cap 24) after a staff drop-off, rescue_ab_value.py [A realised]
for lab, sel in (("top-5 cells", f.cell.isin(top5)), ("top-20 cells", f.cell.isin(cc.index[:20])), ("all flagged", f.cell.notna())):
    g = f[sel]
    still = g.parked_hours > 0.5
    gain = ((g.parked_hours - 0.5).clip(lower=0, upper=24) - E2).where(still, 0).clip(lower=0)
    print(f"  {lab}: n {len(g)}, strand {(g.parked_hours>12).mean():.3f}, avoidable h per flagged car (H=24, dest wait {E2}) "
          f"{gain.mean():.2f}; per car still idle {gain[still].mean():.2f}")
pk = ff[(ff.t.dt.hour >= 16) & (ff.t.dt.hour < 22)]
print(f"  top-5 flagged 16:00-22:00: {len(pk)} over {days_te:.1f} days = {len(pk)/days_te:.1f}/day "
      f"= {len(pk)/days_te/5:.1f} per cell per 6-h shift")
# sanity: supply counts for all test parks by zone
smp = te.sample(4000, random_state=0)
n5s = np.array([neighbours(a, b, t, i, 0.5, t) for a, b, t, i in zip(smp.x, smp.y, smp.ts, smp.vehicle_id)])
for z in (True, False):
    m = smp.inside_sbahn_ring.values == z
    print(f"  sanity, random test parks {'inside' if z else 'outside'} ring: other cars within 500 m median {np.median(n5s[m]):.0f}, share 0 {(n5s[m]==0).mean():.3f}")

# =========================== BER airport (hotspot #1): a coverage case? ===========================
dB = np.hypot((rp.longitude - 13.5106) * 68, (rp.latitude - 52.3647) * 111) < 1.5
b = rp[dB & ok]
print(f"\n[BER] parks within 1.5 km of BER T1 (June 3-22): {dB.sum()}, with next customer rental {len(b)}; strand share {(rp[dB].parked_hours>12).mean():.3f}; "
      f"next rental km median {b.n_km.median():.1f}, fare mean EUR {b.fare.mean():.2f}, idle mean (cap 48) {b.parked_hours.clip(upper=48).mean():.1f} h "
      f"-> EUR {b.fare.sum()/(b.parked_hours.clip(upper=48).sum()+b.n_dur_h.sum()):.2f} per car-hour of idle+ride")
fB = np.hypot((f.longitude - 13.5106) * 68, (f.latitude - 52.3647) * 111) < 1.5
print(f"  flagged at BER June 17-22: {fB.sum()} ({fB.mean():.3f} of flagged, {fB.sum()/days_te:.1f}/day), strand {(f[fB].parked_hours>12).mean():.3f}")
