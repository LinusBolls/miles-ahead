"""A (staff relocation) vs B (user reward) for stranded cars: hours of idle avoided, measured on June 2024 Berlin data.

Inputs
  miles-ops/backend/geo/replay_berlin_2024-06.parquet   one row per parking period after a customer ride (June 3-22),
        parked_hours = time to the next status change, p_tabpfn = out-of-sample TabPFN P(idle>12h) for June 17-22
  miles-ops/analysis/relocations_berlin_2024-06.parquet  staff relocations (relocations_june.py)
Definitions
  I       idle hours after a park (= parked_hours), capped at 48 h like tabpfn_meta.json "value"
  E_H     E[min(I, H)] (horizon-capped idle); value map = E_H per 400 m cell x 3 h bucket x class (car / van = size X),
          fitted on June 3-16 parks, shrunk toward the ring (2 km distance band) x bucket x class mean with weight 15
  flagged = June 17-22 parks with p_tabpfn >= 0.4556 (top 10 % threshold, tabpfn_meta.json)
Prints every number used in whitepaper/value_model.md.
Usage: miles-ops/backend/.venv/bin/python miles-ops/analysis/rescue_ab_value.py
"""
import os
import numpy as np, pandas as pd
from scipy.spatial import cKDTree

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TZ = "Europe/Berlin"
SPLIT = pd.Timestamp("2024-06-17", tz=TZ)
CAP, K, THR = 48.0, 15.0, 0.4556
CELL = (0.0036, 0.0059)
HS = (12, 24, 48)

rp = pd.read_parquet(os.path.join(ROOT, "miles-ops/backend/geo/replay_berlin_2024-06.parquet"))
rp["t"] = pd.to_datetime(rp.parked_from_utc).dt.tz_localize("UTC").dt.tz_convert(TZ)
rp["I"] = rp.parked_hours.clip(upper=CAP)
rp["b"] = rp.t.dt.hour // 3
rp["cls"] = np.where(rp.size_class == "X", "van", "car")
rp["x"] = (rp.longitude - 13.405) * 68.0
rp["y"] = (rp.latitude - 52.52) * 111.0
rp["cell"] = np.round(rp.latitude / CELL[0]).astype(np.int64) * 100000 + np.round(rp.longitude / CELL[1]).astype(np.int64)
rp["c1"] = np.floor(rp.x).astype(int) * 1000 + np.floor(rp.y).astype(int)
rp["ring"] = (np.hypot(rp.x, rp.y) // 2).clip(upper=9).astype(int)
for H in HS:
    rp[f"m{H}"] = rp.parked_hours.clip(upper=H)
rp["ts"] = (rp.t - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds() / 3600.0          # hours since epoch
rp["te"] = rp.ts + rp.parked_hours
tr, te = rp[rp.t < SPLIT], rp[rp.t >= SPLIT]
days_te = (te.t.max() - SPLIT).total_seconds() / 86400
RHO = 227.0e6 / 19000 / 8760   # EUR revenue per car-hour, MILES 2024 annual report (tabpfn_meta.json value.eur_per_car_h)

# ---------------- value map (empirical baseline for the TabPFN regressor) ----------------
ring_m = tr.groupby(["ring", "b", "cls"])[[f"m{H}" for H in HS]].mean()
cm = tr.groupby(["cell", "b", "cls"]).agg(n=("I", "size"), **{f"m{H}": (f"m{H}", "mean") for H in HS},
                                          ring=("ring", "first"), lat=("latitude", "mean"), lon=("longitude", "mean"))
cm = cm.reset_index()
prior = ring_m.loc[list(zip(cm.ring, cm.b, cm.cls))].values
for k, H in enumerate(HS):
    cm[f"E{H}"] = (cm[f"m{H}"] * cm.n + prior[:, k] * K) / (cm.n + K)
VM = cm.set_index(["cell", "b", "cls"])


def vm_lookup(cells, bs, clss, H):
    idx = pd.MultiIndex.from_arrays([cells, bs, clss])
    v = VM[f"E{H}"].reindex(idx).values
    return v


# out-of-sample check of the value map on June 17-22 parks
for H in (12, 48):
    pred = vm_lookup(te.cell.values, te.b.values, te.cls.values, H)
    city = tr.groupby(["b", "cls"])[f"m{H}"].mean().reindex(pd.MultiIndex.from_arrays([te.b, te.cls])).values
    ok = ~np.isnan(pred)
    yv = te[f"m{H}"].values[ok]
    print(f"[value map H={H}] test parks {ok.sum():,}: MAE cell-map {np.mean(np.abs(yv - pred[ok])):.2f} h vs city x bucket "
          f"{np.mean(np.abs(yv - city[ok])):.2f} h; corr(pred, realised) {np.corrcoef(pred[ok], yv)[0,1]:.3f}")
print(f"idle distribution (all parks, uncapped): mean {rp.parked_hours.mean():.2f} h, median {rp.parked_hours.median():.2f} h, "
      f"P(I>12) {(rp.parked_hours>12).mean():.3f}")

# ---------------- residual idle of a car that has already waited e hours (1 km cell) ----------------
grp = {c: np.sort(g.parked_hours.values) for c, g in rp.groupby("c1")}
cum = {c: np.concatenate([[0], np.cumsum(v[::-1])])[::-1] for c, v in grp.items()}   # suffix sums
ring_grp = {r: np.sort(g.parked_hours.values) for r, g in rp.groupby("ring")}


def residual(c1, ring, e, nmin=10, H=CAP):
    """E[min(I - e, H) | I > e] among parks in the same 1 km cell (fallback: same 2 km ring): the expected further
    idle, within a horizon of H hours from now, of a car that has already stood e hours there."""
    v = grp.get(c1)
    if v is None or (v > e).sum() < nmin:
        v = ring_grp[ring]
    m = v > e
    return (np.minimum(v[m] - e, H).mean()) if m.any() else np.nan, int(m.sum())


# ---------------- A: realised staff relocations ----------------
rel = pd.read_parquet(os.path.join(ROOT, "miles-ops/analysis/relocations_berlin_2024-06.parquet"))
rel = rel.dropna(subset=["delay_h", "dlat"])
rel["x"] = (rel.olon - 13.405) * 68; rel["y"] = (rel.olat - 52.52) * 111
rel["c1"] = np.floor(rel.x).astype(int) * 1000 + np.floor(rel.y).astype(int)
rel["ring"] = (np.hypot(rel.x, rel.y) // 2).clip(upper=9).astype(int)
res = [residual(c, r, e) for c, r, e in zip(rel.c1, rel.ring, rel.delay_h)]
rel["stay_resid"] = [r[0] for r in res]
rel["wait48"] = rel.wait_after_h.clip(upper=CAP)
rel["saved"] = rel.stay_resid - rel.wait48
v = rel.dropna(subset=["saved"])
print(f"\n[A realised] staff relocations with a matched stay-counterfactual: {len(v):,}")
print(f"  stayers' residual idle (same 1 km cell, already idle as long): mean {v.stay_resid.mean():.2f} h, median {v.stay_resid.median():.2f}")
print(f"  relocated cars' wait to next rental (cap 48): mean {v.wait48.mean():.2f} h, median {v.wait48.median():.2f}")
print(f"  hours saved per relocation: mean {v.saved.mean():.2f} h, median {v.saved.median():.2f}; "
      f"by delay<12h {v[v.delay_h<12].saved.mean():.2f} / 12-24h {v[v.delay_h.between(12,24)].saved.mean():.2f} / >24h {v[v.delay_h>24].saved.mean():.2f}")
for H in (12, 24):
    sr = np.array([residual(c, r, e, H=H)[0] for c, r, e in zip(v.c1, v.ring, v.delay_h)])
    sv = sr - v.wait_after_h.clip(upper=H).values
    print(f"  common horizon H={H} h from the relocation: stay {np.nanmean(sr):.2f} h, moved {v.wait_after_h.clip(upper=H).mean():.2f} h, "
          f"saved mean {np.nanmean(sv):.2f} h (median {np.nanmedian(sv):.2f})")
print(f"  idle hours already lost before staff arrive (delay, cap 48): mean {v.delay_h.clip(upper=CAP).mean():.2f} h")
dk = rel.dlon.notna()
rel["dcell"] = np.round(rel.dlat / CELL[0]).astype(np.int64) * 100000 + np.round(rel.dlon / CELL[1]).astype(np.int64)
rel["db"] = rel.t1.dt.tz_convert(TZ).dt.hour // 3

# idle cars already parked in the drop-off cell at drop-off time (saturation proxy)
by_cell = {c: (np.sort(g.ts.values), np.sort(g.te.values)) for c, g in rp.groupby("cell")}


def idle_present(cells, ts):
    out = np.zeros(len(cells), int)
    for i, (c, t) in enumerate(zip(cells, ts)):
        s = by_cell.get(c)
        if s is not None:
            out[i] = np.searchsorted(s[0], t, "right") - np.searchsorted(s[1], t, "right")
    return out


rel["t1h"] = (rel.t1 - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds() / 3600.0
rel["present"] = idle_present(rel.dcell.values, rel.t1h.values)
print(f"  idle MILES cars already in the 400 m drop-off cell at drop-off: median {rel.present.median():.0f}, "
      f"share 0: {(rel.present==0).mean():.3f}, share >=3: {(rel.present>=3).mean():.3f}")
vmd = vm_lookup(rel.dcell.values, rel.db.values, np.array(["car"] * len(rel)), 48)
print(f"  value-map E48 at staff drop-off cells: median {np.nanmedian(vmd):.2f} h (realised wait median {rel.wait48.median():.2f})")

# ---------------- flagged cars (the rescue population), June 17-22 ----------------
f = te[te.p_tabpfn >= THR].copy()
print(f"\n[flagged] June 17-22 parks with p_tabpfn >= {THR}: {len(f):,} = {len(f)/days_te:.0f}/day; "
      f"realised strand rate {(f.parked_hours>12).mean():.3f}; mean p {f.p_tabpfn.mean():.3f}")
for H in HS:
    print(f"  E[min(I,{H})] flagged {f[f'm{H}'].mean():.2f} h  vs all test parks {te[f'm{H}'].mean():.2f} h")
hs = {"car": (21.44, 2.877), "van": (24.40, 2.839)}   # demand_berlin.npz h_strand_/h_no_strand_ (build_class_idle.py)
f["E1_model"] = [p * hs[c][0] + (1 - p) * hs[c][1] for p, c in zip(f.p_tabpfn, f.cls)]
print(f"  code's E1 = p*h_strand+(1-p)*h_no_strand: mean {f.E1_model.mean():.2f} h vs realised mean min(I,48) {f.m48.mean():.2f} h")

# timing: hours avoidable if moved at ride end + 0.5 h (B) vs at ride end + 24.1 h (A, median staff delay)
E2A = float(v.wait48.mean())
for tau, lab in ((0.5, "B at +0.5 h"), (24.1, "A at +24.1 h (median staff delay)")):
    still = f.parked_hours > tau
    gain = ((f.I - tau).clip(lower=0) - E2A).where(still, 0).clip(lower=0)
    print(f"  {lab}: still idle {still.mean():.3f}; avoidable idle per flagged car (dest wait = staff mean {E2A:.2f} h) "
          f"{gain.mean():.2f} h; per car still idle {gain[still].mean():.2f} h")
    E2A24 = float(v.wait_after_h.clip(upper=24).mean())
    g24 = ((f.parked_hours - tau).clip(lower=0, upper=24) - E2A24).where(still, 0).clip(lower=0)
    print(f"    H=24 from the move (dest wait = staff mean capped 24 = {E2A24:.2f} h): per flagged car {g24.mean():.2f} h; per car still idle {g24[still].mean():.2f} h")

# ---------------- B: users who actually start a MILES ride near a flagged car ----------------
rp = rp.sort_values(["vehicle_id", "t"]).reset_index(drop=True)
nxt = rp.groupby("vehicle_id").shift(-1)
trip = pd.DataFrame({"sx": rp.x, "sy": rp.y, "start": rp.te, "s_e": rp.parked_hours, "s_c1": rp.c1, "s_ring": rp.ring,
                     "dcell": nxt.cell, "arr": nxt.ts, "dx": nxt.x, "dy": nxt.y, "vid": rp.vehicle_id})
trip = trip[rp.next_status.isin(["USER_IN_RIDE", "BOOKED_BY_USER"]).values & trip.arr.notna().values]
trip = trip[(trip.arr - trip.start).between(0.05, 6)]
trip["dcell"] = trip.dcell.astype(np.int64)
trip["db"] = ((pd.to_datetime(trip.arr * 3600, unit="s", utc=True).dt.tz_convert(TZ).dt.hour) // 3).values
trip["E48d"] = vm_lookup(trip.dcell.values, trip.db.values, np.array(["car"] * len(trip)), 48)
trip["E24d"] = vm_lookup(trip.dcell.values, trip.db.values, np.array(["car"] * len(trip)), 24)
trip["km"] = np.hypot(trip.dx - trip.sx, trip.dy - trip.sy)
tree = cKDTree(np.c_[trip.sx.values, trip.sy.values])
print(f"\n[B] customer trips June 3-22 with a known destination: {len(trip):,}; median straight-line km {trip.km.median():.2f}")

# value of the best cell nearby (what A could choose) vs. typical user destination, for flagged cars
cells = cm[(cm.cls == "car") & (cm.n >= 20)]
cxy = np.c_[(cells.lon.values - 13.405) * 68, (cells.lat.values - 52.52) * 111]
ctree = cKDTree(cxy)
E24_by = {bb: g for bb, g in cells.groupby("b")}
trees_b = {bb: (cKDTree(np.c_[(g.lon.values - 13.405) * 68, (g.lat.values - 52.52) * 111]), g.E24.values) for bb, g in E24_by.items()}


def best_near(xx, yy, bb, R):
    t_ = trees_b.get(int(bb))
    if t_ is None:
        return np.nan
    ii = t_[0].query_ball_point([xx, yy], R)
    return float(np.min(t_[1][ii])) if ii else np.nan


fs = f.sample(min(len(f), 4000), random_state=0)
rows = []
for r in fs.itertuples():
    for rad in (0.4, 0.8):
        idx = tree.query_ball_point([r.x, r.y], rad)
        if not idx:
            rows.append((r.Index, rad, 0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan)); continue
        tt = trip.iloc[idx]
        tt = tt[(tt.start >= r.ts + 0.25) & (tt.start <= r.ts + 3) & (tt.vid != r.vehicle_id)]
        if not len(tt):
            rows.append((r.Index, rad, 0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan)); continue
        wait = tt.start.values - r.ts                       # car sits until the user takes it
        idle_move = np.minimum(wait + tt.E48d.values, CAP)  # unproductive hours if this user moves it
        j = int(np.nanargmin(idle_move)) if np.isfinite(idle_move).any() else 0
        # swap: the car this user really took (O) stays put instead; its residual idle at its own spot
        o = tt.iloc[j]
        o_res, _ = residual(int(o.s_c1), int(o.s_ring), o.s_e)
        sat = idle_present([int(o.dcell)], [o.arr])[0] - 1   # minus the user's own car (its park starts at arrival)
        i24 = min(wait[j] + tt.E24d.values[j], 24.0)
        det = [best_near(dx_, dy_, db_, 1.0) for dx_, dy_, db_ in zip(tt.dx.values, tt.dy.values, tt.db.values)]
        det = np.minimum(wait + np.array(det, float) + 0.1, 24.0)   # +6 min to drive the extra <=1 km
        i24det = np.nanmin(det) if np.isfinite(det).any() else np.nan
        o24 = min(residual(int(o.s_c1), int(o.s_ring), o.s_e, H=24)[0] + wait[j], 24.0)
        rows.append((r.Index, rad, len(tt), idle_move[j], np.nanmedian(idle_move), o_res + wait[j], tt.km.values[j], sat, i24, o24, i24det))
B = pd.DataFrame(rows, columns=["i", "rad", "n_users", "idle_best", "idle_med", "o_resid", "km_best", "sat", "i24", "o24", "i24det"])
for rad in (0.4, 0.8):
    b = B[B.rad == rad].merge(fs[["I", "m48", "m24"]], left_on="i", right_index=True)
    has = b.n_users > 0
    gain_car = (b.m48 - b.idle_best).where(has)
    gain_med = (b.m48 - b.idle_med).where(has)
    gain_swap = (b.m48 - b.o_resid).where(has)       # system gain if the user would have rented car O anyway
    walk = rad / 4.8 * 60
    print(f"  radius {rad} km (~{walk:.0f} min walk): flagged cars with >=1 MILES ride start nearby within 0.25-3 h: {has.mean():.3f}; "
          f"users per such car median {b.n_users[has].median():.0f}")
    print(f"    car-level hours avoided (best user's destination): mean {gain_car.mean():.2f} h, median {gain_car.median():.2f}; "
          f"(median user) mean {gain_med.mean():.2f} h")
    print(f"    system gain if that user would have rented another car anyway (swap): mean {gain_swap.mean():.2f} h")
    print(f"    H=24: car-level {(b.m24 - b.i24).where(has).mean():.2f} h, swap {(b.m24 - b.o24).where(has).mean():.2f} h, "
          f"per flagged car (0 if no user nearby) car-level {(b.m24 - b.i24).where(has, 0).mean():.2f} h")
    print(f"    H=24 with a <=1 km detour to the best cell near the destination: car-level {(b.m24 - b.i24det).where(has).mean():.2f} h")
    print(f"    best user's trip km median {b.km_best[has].median():.2f}; other idle cars already in its destination cell: median "
          f"{b.sat[has].median():.0f}, share 0 {(b.sat[has]==0).mean():.3f}, share >=3 {(b.sat[has]>=3).mean():.3f}")
    print(f"    flagged cars with a user whose destination saves >= 4 h: {((b.m48 - b.idle_best) >= 4).mean():.3f} of all flagged")

best = {}
for R in (1.0, 3.0, 12.0):
    out = []
    for r in fs.itertuples():
        idx = ctree.query_ball_point([r.x, r.y], R)
        cc = cells.iloc[idx]
        cc = cc[cc.b == r.b]
        out.append(cc.E48.min() if len(cc) else np.nan)
    best[R] = np.array(out)
    out24 = np.array([best_near(r.x, r.y, r.b, R) for r in fs.itertuples()])
    print(f"  [H=24] best cell within {R} km: dedicated move saves {np.nanmean(fs.m24.values - np.minimum(out24 + 0.25, 24)):.2f} h (incl. 15 min move)")
    print(f"  best value-map cell within {R:>4} km of a flagged car (same bucket, n>=20): mean E48 {np.nanmean(best[R]):.2f} h "
          f"-> car-level hours avoided vs staying {np.nanmean(fs.m48.values - best[R]):.2f} h")

# ---------------- ride-end to strand: how far is the nearest 'good' cell ----------------
good = cells[cells.E48 <= 3.0]
gtree = {bb: cKDTree(np.c_[(g.lon.values - 13.405) * 68, (g.lat.values - 52.52) * 111]) for bb, g in good.groupby("b")}
d = np.array([gtree[r.b].query([r.x, r.y])[0] if r.b in gtree else np.nan for r in fs.itertuples()])
print(f"  distance from flagged car to nearest cell with E48 <= 3 h (same bucket): median {np.nanmedian(d):.2f} km, "
      f"p75 {np.nanpercentile(d,75):.2f}, share <=1 km {np.nanmean(d<=1):.3f}, <=3 km {np.nanmean(d<=3):.3f}")

# worked example: car, p = 0.55, moved to a cell with 1.7 h typical wait
p = 0.55; e1 = p * 21.44 + (1 - p) * 2.877
print(f"\n[example] p=0.55 car: E1 = {e1:.2f} h; minus target 1.7 h = {e1-1.7:.2f} h; x {RHO:.3f} EUR/h = EUR {(e1-1.7)*RHO:.2f} revenue")
# horizon sensitivity of the example via the flagged-car empirical distribution near p=0.55
near = te[(te.p_tabpfn - 0.55).abs() < 0.03]
for H in HS:
    print(f"  H={H}: E[min(I,H)] for cars with p in 0.52-0.58 (n={len(near)}) = {near[f'm{H}'].mean():.2f} h")
