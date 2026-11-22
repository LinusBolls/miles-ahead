"""Annual scenarios for the hybrid (B first: "take this flagged car where you're going anyway"; staff only for the tail).
Inputs: [measured] relocations_june.py / rescue_ab_value.py, [sourced] annual report & wage/cost sources (value_model.md
section 5.1), [ASSUMPTION] acceptance a and incremental share q (sensitivities). Usage: python3 miles-ops/analysis/ab_scenarios.py

Credit policy: destination-priced, face R = min(EUR 5 cap, R*), R* = expected value of the rescue (mu = 0) given the
user's stated destination. Credit cost to MILES between R(1-m) (redeemed on a ride that would not otherwise happen)
and R (redeemed on a ride that would have happened anyway).
"""
import itertools
import os
import numpy as np, pandas as pd

RHO = 226.96e6 / 19000 / 8760
M = (0.228, 0.793)
S = 0.988
FLAG, REACH = 1288, 0.806          # flagged/day; share with a MILES ride start <= 0.8 km within 3 h
H_CAR = (5.93, 7.76)               # hours saved, going anyway (10 min) .. with <= 1 km detour (H = 24 h)
H_SWAP = 1.00                      # hours saved if the user would have rented another MILES car anyway
CAP = 5.0
A = (0.05, 0.10, 0.20)
Q = (0.50, 0.75, 1.00)


def net_per_rescue(m, h, q, full_cost):
    v = S * RHO * m * (q * h + (1 - q) * H_SWAP)
    r = min(CAP, v)
    c = r if full_cost else r * (1 - m)
    return v, r, v - c


rows = []
for a, q in itertools.product(A, Q):
    per_day = FLAG * REACH * a
    nets = [net_per_rescue(m, h, q, fc)[2] for m in M for h in H_CAR for fc in (True, False)]
    rows.append((a, q, per_day, min(nets) * per_day * 365, max(nets) * per_day * 365))
df = pd.DataFrame(rows, columns=["accept", "q", "rescues_day", "net_lo", "net_hi"])
pd.set_option("display.width", 160)
print("net contribution per year (EUR), destination-priced credit capped at EUR 5")
print(df.assign(net_lo=lambda d: (d.net_lo / 1e3).round(0), net_hi=lambda d: (d.net_hi / 1e3).round(0)).to_string(index=False))
print("per-rescue value v and credit face r at the corners (q=0.75):")
for m in M:
    for h in H_CAR:
        v, r, _ = net_per_rescue(m, h, 0.75, True)
        print(f"  m={m} h={h}: value EUR {v:.2f}, credit face EUR {r:.2f}")
# flat EUR 5 credit for comparison (no destination pricing)
for a in A:
    per_day = FLAG * REACH * a
    lo = (S * RHO * M[0] * (0.75 * H_CAR[0] + 0.25 * H_SWAP) - CAP) * per_day * 365
    hi = (S * RHO * M[1] * (0.75 * H_CAR[1] + 0.25 * H_SWAP) - CAP * (1 - M[1])) * per_day * 365
    print(f"flat EUR 5, q=0.75, a={a:.0%}: EUR {lo/1e3:.0f}k .. {hi/1e3:.0f}k per year")

# staff hours MILES could redeploy under the tail rule (send staff only if expected saving >= break-even 15.1 h)
here = os.path.dirname(os.path.abspath(__file__))
rel = pd.read_parquet(os.path.join(here, "relocations_berlin_2024-06.parquet")).dropna(subset=["delay_h"])
rp = pd.read_parquet(os.path.join(here, "..", "backend", "geo", "replay_berlin_2024-06.parquet"))
x = (rp.longitude - 13.405) * 68; y = (rp.latitude - 52.52) * 111
c1 = np.floor(x).astype(int) * 1000 + np.floor(y).astype(int)
grp = {c: np.sort(v) for c, v in rp.parked_hours.groupby(c1)}
rx = (rel.olon - 13.405) * 68; ry = (rel.olat - 52.52) * 111
rc = np.floor(rx).astype(int) * 1000 + np.floor(ry).astype(int)
E2 = rel.wait_after_h.clip(upper=24).mean()
exp_save = []
for c, e in zip(rc, rel.delay_h):
    v = grp.get(c)
    if v is None or (v > e).sum() < 10:
        exp_save.append(np.nan); continue
    exp_save.append(np.minimum(v[v > e] - e, 24).mean() - E2)
exp_save = np.array(exp_save)
ok = ~np.isnan(exp_save)
print(f"\nstaff relocations whose expected saving (cell residual, H=24, minus mean drop-off wait {E2:.2f} h) >= 15.1 h: "
      f"{np.mean(exp_save[ok] >= 15.1):.3f} of {ok.sum()}; >= 10 h: {np.mean(exp_save[ok] >= 10):.3f}; mean {np.nanmean(exp_save):.2f} h")
days = 20
moves_day = len(rel) / days
for lo_h, hi_h in ((0.86, 1.05),):
    print(f"staff-hours on relocation today: {moves_day:.0f}/day x {lo_h}-{hi_h} h = {moves_day*lo_h:.0f}-{moves_day*hi_h:.0f} h/day "
          f"= {moves_day*lo_h*365/1e3:.0f}k-{moves_day*hi_h*365/1e3:.0f}k h/yr")
